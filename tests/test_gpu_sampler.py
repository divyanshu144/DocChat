import ast
import json
import subprocess
import sys
import threading
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eval import gpu_sampler as gs

SMI = "0, 87, 30123, 46068, 245.31\n1, 12, 1024, 46068, [N/A]\n"
SAMPLE_KEYS = {"event", "ts", "gpu", "util_pct", "mem_used_mib", "mem_total_mib", "power_w"}


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def ticking_clock():
    state = {"n": 0}

    def clock():
        state["n"] += 1
        return datetime(2026, 10, 6, 12, 0, state["n"], tzinfo=timezone.utc)
    return clock


def fake_backend(ticks, stop=None, rows=None):
    """A backend that returns `rows` each tick and sets `stop` after `ticks` reads."""
    rows = rows or [{"gpu": 0, "util_pct": 50.0, "mem_used_mib": 100.0, "mem_total_mib": 200.0, "power_w": 90.0}]
    calls = {"n": 0}

    def reader():
        calls["n"] += 1
        if stop is not None and calls["n"] >= ticks:
            stop.set()
        return [dict(r) for r in rows]
    return "fake", reader


def test_nvidia_smi_output_parses_and_na_power_becomes_null_not_zero():
    rows = gs.parse_nvidia_smi(SMI)
    assert rows[0] == {"gpu": 0, "util_pct": 87.0, "mem_used_mib": 30123.0, "mem_total_mib": 46068.0, "power_w": 245.31}
    assert rows[1]["power_w"] is None and rows[1]["gpu"] == 1


def test_nvidia_smi_na_utilization_is_null_and_malformed_rows_raise():
    assert gs.parse_nvidia_smi("0, [N/A], 10, 20, 5\n")[0]["util_pct"] is None
    with pytest.raises(ValueError):
        gs.parse_nvidia_smi("garbage line\n")
    with pytest.raises(ValueError):
        gs.parse_nvidia_smi("0, 1, 2\n")


def test_nvidia_smi_backend_uses_the_runner_and_returns_none_when_missing():
    def ok_runner(cmd, **kwargs):
        assert cmd[0] == "nvidia-smi" and "--format=csv,noheader,nounits" in cmd
        return types.SimpleNamespace(stdout=SMI)
    name, reader = gs.nvidia_smi_backend(ok_runner)
    assert name == "nvidia-smi" and len(reader()) == 2

    def missing(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi")
    assert gs.nvidia_smi_backend(missing) is None

    def failing(cmd, **kwargs):
        raise subprocess.CalledProcessError(9, cmd)
    assert gs.nvidia_smi_backend(failing) is None


def test_pynvml_backend_with_a_fake_module(monkeypatch):
    fake = types.ModuleType("pynvml")
    fake.nvmlInit = lambda: None
    fake.nvmlDeviceGetCount = lambda: 2
    fake.nvmlDeviceGetHandleByIndex = lambda i: i
    fake.nvmlDeviceGetUtilizationRates = lambda h: types.SimpleNamespace(gpu=40 + h)
    fake.nvmlDeviceGetMemoryInfo = lambda h: types.SimpleNamespace(used=1048576 * 10, total=1048576 * 80)

    def power(h):
        if h == 1:
            raise RuntimeError("not supported")
        return 250000
    fake.nvmlDeviceGetPowerUsage = power
    monkeypatch.setitem(sys.modules, "pynvml", fake)
    name, reader = gs.pynvml_backend()
    rows = reader()
    assert name == "pynvml" and [r["gpu"] for r in rows] == [0, 1]
    assert rows[0]["util_pct"] == 40.0 and rows[0]["power_w"] == 250.0 and rows[0]["mem_total_mib"] == 80.0
    assert rows[1]["power_w"] is None                      # unsupported power is null, never estimated


def test_pynvml_backend_is_none_when_not_installed_or_driver_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)       # makes `import pynvml` raise ImportError
    assert gs.pynvml_backend() is None
    broken = types.ModuleType("pynvml")

    def boom():
        raise RuntimeError("NVML shared library not found")
    broken.nvmlInit = boom
    monkeypatch.setitem(sys.modules, "pynvml", broken)
    assert gs.pynvml_backend() is None


def test_neither_backend_available_writes_an_unavailable_header_and_no_samples(tmp_path, monkeypatch):
    assert gs.choose_backend(factories=(lambda: None, lambda: None)) is None
    out = tmp_path / "samples.jsonl"
    status = gs.run(out, 1.0, backend=None, clock=ticking_clock())
    rows = read(out)
    assert status == gs.EXIT_UNAVAILABLE and len(rows) == 1
    assert rows[0]["event"] == "sampler_start" and rows[0]["backend"] == "unavailable"
    assert "unavailable_reason" in rows[0] and rows[0]["clock_source"] == gs.CLOCK_SOURCE
    assert not any(r["event"] == "gpu_sample" for r in rows)


def test_main_exits_nonzero_without_a_traceback_when_no_backend(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gs, "choose_backend", lambda: None)
    assert gs.main([str(tmp_path / "s.jsonl")]) == gs.EXIT_UNAVAILABLE
    assert "no GPU backend available" in capsys.readouterr().err


def test_normal_run_writes_header_timestamped_samples_per_gpu_and_a_stop_record(tmp_path):
    out = tmp_path / "samples.jsonl"
    stop = threading.Event()
    rows = [{"gpu": 0, "util_pct": 60.0, "mem_used_mib": 1.0, "mem_total_mib": 2.0, "power_w": 100.0},
            {"gpu": 1, "util_pct": 30.0, "mem_used_mib": 1.0, "mem_total_mib": 2.0, "power_w": None}]
    status = gs.run(out, 0.0, backend=fake_backend(3, stop, rows), stop=stop, clock=ticking_clock())
    records = read(out)
    assert status == 0
    assert records[0]["event"] == "sampler_start" and records[0]["backend"] == "fake"
    samples = [r for r in records if r["event"] == "gpu_sample"]
    assert len(samples) == 6 and {r["gpu"] for r in samples} == {0, 1}
    assert records[-1] == {"event": "sampler_stop", "ticks": 3, "reason": "stopped", "ts": records[-1]["ts"]}
    stamps = [datetime.fromisoformat(r["ts"]) for r in records]
    assert stamps == sorted(stamps) and all(s.tzinfo is not None for s in stamps)


def test_records_are_content_free(tmp_path):
    out = tmp_path / "samples.jsonl"
    stop = threading.Event()
    gs.run(out, 0.0, backend=fake_backend(2, stop), stop=stop, clock=ticking_clock())
    for record in read(out):
        if record["event"] == "gpu_sample":
            assert set(record) == SAMPLE_KEYS
        assert not ({"hostname", "host", "pid", "process", "processes", "name", "uuid", "prompt", "answer"} & set(record))


def test_duration_stops_the_run(tmp_path):
    out = tmp_path / "samples.jsonl"
    gs.run(out, 0.01, duration_s=0.05, backend=fake_backend(10**6), clock=ticking_clock())
    records = read(out)
    assert records[-1]["reason"] == "duration" and records[-1]["ticks"] >= 1


def test_a_failing_read_is_recorded_by_type_only_and_sampling_continues(tmp_path):
    out = tmp_path / "samples.jsonl"
    stop = threading.Event()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("secret detail that must not be written")
        if calls["n"] >= 3:
            stop.set()
        return [{"gpu": 0, "util_pct": 1.0, "mem_used_mib": 1.0, "mem_total_mib": 2.0, "power_w": None}]
    gs.run(out, 0.0, backend=("fake", flaky), stop=stop, clock=ticking_clock())
    text = out.read_text()
    assert "secret detail" not in text
    errors = [r for r in read(out) if r["event"] == "sampler_error"]
    assert errors == [{"event": "sampler_error", "error_type": "RuntimeError", "ts": errors[0]["ts"]}]
    assert sum(r["event"] == "gpu_sample" for r in read(out)) == 2


def test_refuses_to_overwrite_an_existing_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "samples.jsonl"
    out.write_text("keep me\n")
    with pytest.raises(FileExistsError):
        gs.run(out, 1.0, backend=fake_backend(1))
    assert out.read_text() == "keep me\n"
    monkeypatch.setattr(gs, "choose_backend", lambda: fake_backend(1))
    assert gs.main([str(out)]) == gs.EXIT_EXISTS
    assert "refusing to overwrite" in capsys.readouterr().err


def test_stop_event_ends_a_running_sampler_cleanly(tmp_path):
    out = tmp_path / "samples.jsonl"
    stop = threading.Event()
    worker = threading.Thread(target=gs.run, args=(out, 0.01),
                              kwargs={"backend": fake_backend(10**6), "stop": stop})
    worker.start()
    stop.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert read(out)[-1]["event"] == "sampler_stop"


def test_sampler_imports_only_the_standard_library_and_optional_pynvml():
    tree = ast.parse(Path(gs.__file__).read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    third_party = {m for m in modules if m not in sys.stdlib_module_names}
    assert third_party <= {"pynvml"}, third_party
    assert not ({"app", "eval", "httpx"} & modules)


class FakeTime:
    """A controllable monotonic clock: reads cost time, waits advance it, nothing really sleeps."""

    def __init__(self, read_cost):
        self.now, self.read_cost, self.read_times = 0.0, read_cost, []

    def monotonic(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds
        return False

    def reader(self):
        self.read_times.append(self.now)
        self.now += self.read_cost
        return [{"gpu": 0, "util_pct": 1.0, "mem_used_mib": 1.0, "mem_total_mib": 2.0, "power_w": None}]


def test_sampling_period_is_fixed_and_not_stretched_by_slow_reads(tmp_path):
    fake = FakeTime(read_cost=0.3)                      # an nvidia-smi call that takes 0.3 s
    gs.run(tmp_path / "s.jsonl", 1.0, duration_s=4.0, backend=("fake", fake.reader),
           clock=ticking_clock(), monotonic=fake.monotonic, wait=fake.wait)
    assert fake.read_times == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0])      # not 0, 1.3, 2.6, ...


def test_a_read_slower_than_the_interval_reanchors_instead_of_bursting(tmp_path):
    fake = FakeTime(read_cost=1.5)                      # slower than the 1.0 s interval
    gs.run(tmp_path / "s.jsonl", 1.0, duration_s=6.0, backend=("fake", fake.reader),
           clock=ticking_clock(), monotonic=fake.monotonic, wait=fake.wait)
    gaps = [b - a for a, b in zip(fake.read_times, fake.read_times[1:], strict=False)]
    assert all(gap == pytest.approx(1.5) for gap in gaps)                    # one read after another, no zero-gap burst
    assert len(fake.read_times) >= 3
