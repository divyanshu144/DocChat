"""Standalone GPU sampler: run it ON the GPU host next to the model server.

Copy this single file to the host; it uses only the standard library (``pynvml`` is optional) and imports nothing
from this repository. It writes timestamped JSONL that ``eval.gpu_utilization`` later aligns with a benchmark run.

    python gpu_sampler.py samples.jsonl --interval 1.0     # stop with Ctrl-C or SIGTERM

Backends, in order: ``pynvml``, then the ``nvidia-smi`` CSV query. If neither works it writes an explicit
"unavailable" header (so the reason survives) and exits with status 3; it never writes invented samples.
Records are content-free: GPU index, utilization, memory and power only (no process lists, names or hostname).
Timestamps are the host wall clock in UTC at sampling time. Utilization is the share of the sample period in which at
least one kernel was running; 100% does not mean the GPU is fully used, and it does not show efficiency.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
CLOCK_SOURCE = "gpu_host_wall_clock_utc"
SMI_QUERY = "index,utilization.gpu,memory.used,memory.total,power.draw"
EXIT_UNAVAILABLE, EXIT_EXISTS = 3, 4


def _number(text):
    """Parse a numeric field; "[N/A]", "N/A", "" and non-finite values become None (never a guess)."""
    try:
        value = float(str(text).strip())
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def parse_nvidia_smi(output):
    """Parse ``--format=csv,noheader,nounits`` rows into sample dicts. Raises ValueError on a malformed row."""
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = [part.strip() for part in line.split(",")]
        index = _number(fields[0]) if len(fields) == 5 else None
        if index is None:
            raise ValueError("unexpected nvidia-smi row")
        rows.append({"gpu": int(index), "util_pct": _number(fields[1]), "mem_used_mib": _number(fields[2]),
                     "mem_total_mib": _number(fields[3]), "power_w": _number(fields[4])})
    return rows


def pynvml_backend():
    """Return ("pynvml", read) or None when pynvml or an NVIDIA driver is unavailable."""
    try:
        import pynvml
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
    except Exception:  # noqa: BLE001 - any NVML failure means "not usable here"
        return None

    def read():
        rows = []
        for index, handle in enumerate(handles):
            util, memory = pynvml.nvmlDeviceGetUtilizationRates(handle), pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:  # noqa: BLE001 - power is optional on some GPUs and virtual devices
                power = None
            rows.append({"gpu": index, "util_pct": float(util.gpu), "mem_used_mib": memory.used / 1048576,
                         "mem_total_mib": memory.total / 1048576, "power_w": power})
        return rows
    return ("pynvml", read) if handles else None


def nvidia_smi_backend(runner=subprocess.run):
    """Return ("nvidia-smi", read) after one successful probe, or None."""
    def read():
        result = runner(["nvidia-smi", f"--query-gpu={SMI_QUERY}", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=10, check=True)
        return parse_nvidia_smi(result.stdout)
    try:
        return ("nvidia-smi", read) if read() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def choose_backend(factories=(pynvml_backend, nvidia_smi_backend)):
    for factory in factories:
        backend = factory()
        if backend is not None:
            return backend
    return None


def run(path, interval_s, *, duration_s=None, backend=None, stop=None,
        clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic, wait=None):
    """Write the JSONL file; return 0, or EXIT_UNAVAILABLE when no backend works. Refuses to overwrite.

    Ticks are scheduled against a fixed monotonic deadline, so a slow read (an `nvidia-smi` subprocess can take a
    noticeable fraction of a second) does not stretch the period. If a read ever takes longer than the interval the
    schedule re-anchors rather than firing a burst of catch-up samples.
    """
    stop = stop or threading.Event()
    wait = wait or stop.wait
    with Path(path).open("x") as sink:
        def write(record):
            sink.write(json.dumps({**record, "ts": clock().isoformat()}, allow_nan=False) + "\n")
            sink.flush()

        header = {"event": "sampler_start", "schema_version": SCHEMA_VERSION, "clock_source": CLOCK_SOURCE,
                  "interval_s": interval_s}
        if backend is None:
            write({**header, "backend": "unavailable",
                   "unavailable_reason": "neither pynvml nor a working nvidia-smi was found"})
            return EXIT_UNAVAILABLE
        name, read = backend
        write({**header, "backend": name})
        ticks, started, reason = 0, monotonic(), "stopped"
        next_tick = started
        while not stop.is_set():
            try:
                for row in read():
                    write({"event": "gpu_sample", **row})
            except Exception as exc:  # noqa: BLE001 - keep sampling; record the type only (content-free)
                write({"event": "sampler_error", "error_type": type(exc).__name__})
            ticks += 1
            if duration_s is not None and monotonic() - started >= duration_s:
                reason = "duration"
                break
            next_tick += interval_s
            now = monotonic()
            if next_tick <= now:  # the read overran the interval: do not burst to catch up
                next_tick = now
            wait(max(0.0, next_tick - now))
        write({"event": "sampler_stop", "ticks": ticks, "reason": reason})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="JSONL file to create (refuses to overwrite)")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between samples (default 1.0)")
    parser.add_argument("--duration", type=float, help="stop after this many seconds (default: until signalled)")
    args = parser.parse_args(argv)
    if args.interval <= 0 or (args.duration is not None and args.duration <= 0):
        parser.error("--interval and --duration must be positive")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        status = run(args.output, args.interval, duration_s=args.duration, backend=choose_backend(), stop=stop)
    except FileExistsError:
        print(f"refusing to overwrite {args.output}", file=sys.stderr)
        return EXIT_EXISTS
    if status == EXIT_UNAVAILABLE:
        print("no GPU backend available (install pynvml or ensure nvidia-smi works); wrote an 'unavailable' header",
              file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
