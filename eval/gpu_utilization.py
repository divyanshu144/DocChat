"""Attach GPU-sampler output to a schema-v2 sustained benchmark run, per measured cell.

    python -m eval.gpu_utilization attach RUN_DIR SAMPLES.jsonl [--clock-offset-s S] [--min-samples N]

The sampler (``eval/gpu_sampler.py``) runs on the GPU host and its file is copied back after the sweep, so this is a
post-run step. It writes ``RUN_DIR/gpu-utilization.json`` (never overwriting, and never touching ``manifest.json`` or
``events.jsonl``). Only measurement cells are attached: warmup cells are separate calls and are skipped.

Nothing is estimated. A cell is ``unavailable`` (with a reason) when the file is missing, the sampler reported no
backend, the artifact has no recorded window, a GPU has too few samples in the window, or its samples do not cover
the window. Utilization is the share of the sample period in which at least one kernel was running (100% is not
"fully used"); it shows the GPU was busy, not that it was efficient. Read it beside KV-cache usage and queue depth. Content-free: it carries numbers and timestamps only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eval.serving_load import percentile

FILENAME = "gpu-utilization.json"
DEFAULT_MIN_SAMPLES = 10
COVERAGE_TOLERANCE_INTERVALS = 2
# The ONE definition of the offset sign. The report, the CLI help and docs/benchmarking.md all quote it, and a test
# fails if the docs drift. Example (illustration): if the GPU host clock reads 30 s later than the client's, pass +30.
OFFSET_CONVENTION = ("clock_offset_s = gpu_host_clock - benchmark_client_clock; "
                     "a sample's time on the client clock is its timestamp minus the offset")
SHORT_WINDOW_S = 30.0
NOTES = ["Utilization is the share of the sample period in which at least one kernel was running; 100% does not mean "
         "the GPU is fully used",
         "It shows the GPU was busy, not that it was efficient, and a low reading does not show where a limit was",
         "It is one signal beside KV-cache usage and queue depth, not a replacement for either",
         "Statistics are per GPU; no cross-GPU average is computed",
         "Unavailable cells are never filled in or estimated"]


def _parse_ts(text) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError("naive timestamp")
    return value.astimezone(timezone.utc)


def read_samples(path: Path) -> dict:
    """Parse a sampler file; malformed lines are skipped and counted, never repaired."""
    header, samples, errors, malformed = None, [], 0, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            event = record.get("event")
            if event == "sampler_start":
                header = record
            elif event == "sampler_error":
                errors += 1
            elif event == "gpu_sample":
                samples.append({"ts": _parse_ts(record["ts"]), "gpu": int(record["gpu"]),
                                "util_pct": record.get("util_pct"), "mem_used_mib": record.get("mem_used_mib"),
                                "mem_total_mib": record.get("mem_total_mib"), "power_w": record.get("power_w")})
        except (ValueError, KeyError, TypeError, AttributeError):
            malformed += 1
    return {"header": header, "samples": samples, "sampler_error_records": errors, "malformed_lines": malformed}


def _gpu_stats(gpu_samples, start, end, interval_s, min_samples):
    """Statistics for one GPU in one window, or an explicit unavailable reason."""
    inside = [s for s in gpu_samples if start <= s["ts"] <= end]
    values = [s["util_pct"] for s in inside if s["util_pct"] is not None]
    if len(values) < min_samples:
        return {"status": "unavailable", "n_samples": len(values),
                "reason": f"{len(values)} usable sample(s) in the window; minimum is {min_samples}"}
    tolerance = timedelta(seconds=COVERAGE_TOLERANCE_INTERVALS * interval_s)
    first, last = min(s["ts"] for s in inside), max(s["ts"] for s in inside)
    if first - start > tolerance or end - last > tolerance:
        return {"status": "unavailable", "n_samples": len(values),
                "reason": (f"samples do not cover the measured window (first sample {(first - start).total_seconds():.1f}s "
                           f"after start, last {(end - last).total_seconds():.1f}s before end; "
                           f"tolerance {tolerance.total_seconds():.1f}s)")}
    used = [s["mem_used_mib"] for s in inside if s["mem_used_mib"] is not None]
    total = [s["mem_total_mib"] for s in inside if s["mem_total_mib"] is not None]
    power = [s["power_w"] for s in inside if s["power_w"] is not None]
    return {"status": "ok", "n_samples": len(values), "mean_pct": sum(values) / len(values),
            "p95_pct": percentile(values, .95), "max_pct": max(values),
            "memory_used_mib_max": max(used) if used else None, "memory_total_mib": max(total) if total else None,
            "power_w_mean": sum(power) / len(power) if power else None, "power_samples": len(power)}


def _cell(event, parsed, offset_s, min_samples, file_state):
    cell = {"cell_id": event.get("cell_id"), "concurrency": event.get("concurrency"),
            "arrival_rate": event.get("arrival_rate"), "interrupted": bool(event.get("interrupted")),
            "window": None, "per_gpu": {}}

    def unavailable(reason):
        return {**cell, "status": "unavailable", "reason": reason}
    window = event.get("window")
    if not isinstance(window, dict) or "started_at" not in window or "ended_at" not in window:
        return unavailable("cell window not recorded (artifact predates window recording)")
    cell["window"] = {"started_at": window["started_at"], "ended_at": window["ended_at"]}
    if file_state is not None:
        return unavailable(file_state)
    header = parsed["header"]
    if header is None:
        return unavailable("sampler file has no sampler_start header")
    if header.get("backend") == "unavailable":
        return unavailable(f"sampler reported no GPU backend: {header.get('unavailable_reason', 'unknown reason')}")
    interval_s = header.get("interval_s")
    if not isinstance(interval_s, (int, float)) or interval_s <= 0:
        return unavailable("sampler header has no valid interval_s")
    if not parsed["samples"]:
        return unavailable("sampler file contains no gpu_sample records")
    try:
        start, end = _parse_ts(window["started_at"]), _parse_ts(window["ended_at"])
    except ValueError:
        return unavailable("cell window timestamps are not valid timezone-aware ISO times")
    shift = timedelta(seconds=offset_s)
    by_gpu = defaultdict(list)
    for sample in parsed["samples"]:
        by_gpu[sample["gpu"]].append({**sample, "ts": sample["ts"] - shift})
    per_gpu = {str(gpu): _gpu_stats(rows, start, end, interval_s, min_samples) for gpu, rows in sorted(by_gpu.items())}
    ok = [stats["status"] == "ok" for stats in per_gpu.values()]
    status = "ok" if all(ok) else ("partial" if any(ok) else "unavailable")
    result = {**cell, "status": status, "per_gpu": per_gpu}
    if status != "ok":
        result["reason"] = "; ".join(f"gpu {gpu}: {stats['reason']}" for gpu, stats in per_gpu.items()
                                     if stats["status"] != "ok")
    return result


def _window_seconds(window):
    try:
        return (_parse_ts(window["ended_at"]) - _parse_ts(window["started_at"])).total_seconds()
    except (ValueError, KeyError, TypeError):
        return None


def _warnings(cells, clock_offset_s):
    """Warn (never fail) when the offset was not measured and some cells are short enough for small drift to matter."""
    if clock_offset_s is not None:
        return []
    short = [c["cell_id"] for c in cells
             if c["window"] and (_window_seconds(c["window"]) or SHORT_WINDOW_S) < SHORT_WINDOW_S]
    if not short:
        return []
    return [{"code": "offset_not_measured_short_windows", "cells": short,
             "message": (f"The clock offset was assumed to be zero (not measured) and {len(short)} cell(s) have a "
                         f"measured window under {SHORT_WINDOW_S:.0f} s. A small clock difference between the GPU "
                         "host and the benchmark client can push samples outside a window that short and make the "
                         "cell unavailable. Measure the offset and pass --clock-offset-s.")}]


def build_report(run_dir: Path, samples_path: Path, *, clock_offset_s=None, min_samples=DEFAULT_MIN_SAMPLES) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest.get("schema_version") != 2:
        raise ValueError("GPU utilization attaches to schema-v2 sustained runs only")
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines() if line.strip()]
    measurement = [e for e in events if e.get("event") == "cell_summary" and e.get("phase") == "measurement"]
    if not measurement:
        raise ValueError("run has no measurement cells")
    file_state, parsed, digest = None, {"header": None, "samples": [], "sampler_error_records": 0,
                                        "malformed_lines": 0}, None
    if samples_path.exists():
        parsed = read_samples(samples_path)
        digest = hashlib.sha256(samples_path.read_bytes()).hexdigest()
    else:
        file_state = "sampler file not found"
    offset = 0.0 if clock_offset_s is None else float(clock_offset_s)
    cells = [_cell(e, parsed, offset, min_samples, file_state) for e in measurement]
    sampled = sorted({s["gpu"] for s in parsed["samples"]})
    expected = (manifest.get("deployment") or {}).get("gpu_count")
    header = parsed["header"] or {}
    return {"schema_version": 1, "run_id": manifest.get("run_id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "samples_file": samples_path.name, "samples_sha256": digest,
            "sampler": {"backend": header.get("backend"), "interval_s": header.get("interval_s"),
                        "clock_source": header.get("clock_source"), "schema_version": header.get("schema_version")},
            "sampler_error_records": parsed["sampler_error_records"], "malformed_lines": parsed["malformed_lines"],
            "alignment": {"sampler_clock": header.get("clock_source"),
                          "window_clock": sorted({(e.get("window") or {}).get("clock") for e in measurement
                                                  if e.get("window")}) or None,
                          "clock_offset_s": offset,
                          "offset_provenance": "assumed_zero_not_measured" if clock_offset_s is None
                          else "operator_supplied",
                          "convention": OFFSET_CONVENTION},
            "parameters": {"min_samples": min_samples, "coverage_tolerance_intervals": COVERAGE_TOLERANCE_INTERVALS},
            "gpu_count": {"sampled": len(sampled) or None, "manifest": expected,
                          "matches_manifest": (len(sampled) == expected) if sampled and expected else None},
            "warnings": _warnings(cells, clock_offset_s), "cells": cells, "notes": NOTES}


def attach(run_dir: Path, samples_path: Path, **kwargs) -> dict:
    """Build the report and write it next to the run's artifacts; refuses to overwrite an earlier attachment."""
    report = build_report(run_dir, samples_path, **kwargs)
    with (run_dir / FILENAME).open("x") as sink:
        sink.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def load_gpu_utilization(run_dir: Path) -> dict | None:
    """The attached report, or None when this run has none."""
    path = Path(run_dir) / FILENAME
    return json.loads(path.read_text()) if path.exists() else None


def summarize_by_load(report: dict) -> dict:
    """Aggregate per-repeat cells by (concurrency, arrival_rate) for comparison output.

    Per GPU: mean of the repeat means, the worst repeat p95, the overall max and the total sample count, using only
    repeats whose cell has data for that GPU. Repeats without data are counted, not averaged in.
    """
    groups = defaultdict(list)
    for cell in report["cells"]:
        groups[(cell["concurrency"], cell["arrival_rate"])].append(cell)
    result = {}
    for key, cells in groups.items():
        per_gpu = {}
        for gpu in sorted({g for c in cells for g in c["per_gpu"]}, key=int):
            ok = [c["per_gpu"][gpu] for c in cells if c["per_gpu"].get(gpu, {}).get("status") == "ok"]
            if ok:
                per_gpu[gpu] = {"repeats_with_data": len(ok), "mean_pct": sum(s["mean_pct"] for s in ok) / len(ok),
                                "p95_pct_worst_repeat": max(s["p95_pct"] for s in ok),
                                "max_pct": max(s["max_pct"] for s in ok), "n_samples": sum(s["n_samples"] for s in ok)}
        reasons = sorted({c["reason"] for c in cells if c["status"] != "ok" and c.get("reason")})
        status = "ok" if per_gpu and all(c["status"] == "ok" for c in cells) else ("partial" if per_gpu else "unavailable")
        entry = {"status": status, "repeats": len(cells), "per_gpu": per_gpu}
        if reasons:
            entry["reasons"] = reasons
        result[key] = entry
    return result


def dry_check(run_dir: Path, samples_path: Path, *, clock_offset_s=None, min_samples=DEFAULT_MIN_SAMPLES) -> list[str]:
    """Read-only preview for the first live run: expected vs actual samples per cell and sample span vs window span."""
    report = build_report(run_dir, samples_path, clock_offset_s=clock_offset_s, min_samples=min_samples)
    interval, align = report["sampler"]["interval_s"], report["alignment"]
    lines = [f"offset {align['clock_offset_s']:+.2f}s ({align['offset_provenance']}); sampler interval {f'{interval}s' if interval else 'unknown'}"]
    for cell in report["cells"]:
        secs = _window_seconds(cell["window"]) if cell["window"] else None
        expected = f"~{secs / interval:.0f}" if secs and interval else "unknown"
        actual = ", ".join(f"gpu{g}={st.get('n_samples', 0)}" for g, st in cell["per_gpu"].items()) or "none"
        lines.append(f"{cell['cell_id']}: window {secs if secs is None else round(secs, 1)}s, expected {expected} "
                     f"samples per GPU, actual {actual} -> {cell['status']}" + (f" ({cell['reason']})" if cell.get("reason") else ""))
    windows = [c["window"] for c in report["cells"] if c["window"]]
    samples = read_samples(samples_path)["samples"] if samples_path.exists() else []
    if windows and samples:
        times = [s["ts"] - timedelta(seconds=align["clock_offset_s"]) for s in samples]
        lines.append(f"samples span {min(times).isoformat()} .. {max(times).isoformat()} (client clock)")
        lines.append(f"windows span {min(w['started_at'] for w in windows)} .. {max(w['ended_at'] for w in windows)}")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    attach_parser = sub.add_parser("attach", help="attach sampler output to a run directory")
    attach_parser.add_argument("run_dir", type=Path)
    attach_parser.add_argument("samples", type=Path)
    attach_parser.add_argument("--clock-offset-s", type=float,
                               help=OFFSET_CONVENTION + " (default: assume 0, recorded as not measured)")
    attach_parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    attach_parser.add_argument("--dry-check", action="store_true", help="print expected vs actual samples; write nothing")
    args = parser.parse_args(argv)
    if args.min_samples < 1:
        parser.error("--min-samples must be at least 1")
    if args.dry_check:
        print("\n".join(dry_check(args.run_dir, args.samples, clock_offset_s=args.clock_offset_s,
                                  min_samples=args.min_samples)))
        return 0
    report = attach(args.run_dir, args.samples, clock_offset_s=args.clock_offset_s, min_samples=args.min_samples)
    counts = {status: sum(c["status"] == status for c in report["cells"]) for status in ("ok", "partial", "unavailable")}
    for warning in report["warnings"]:
        print(f"WARNING: {warning['message']}", file=sys.stderr)
    print(json.dumps({"written": str(args.run_dir / FILENAME), "cells": counts,
                      "offset_provenance": report["alignment"]["offset_provenance"],
                      "warnings": [w["code"] for w in report["warnings"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
