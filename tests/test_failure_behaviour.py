import pytest

from eval.failure_behaviour import analyze

# Timeline (seconds from load start): fault injected at 10, inject command returns at 10.5, restore issued at 40,
# restore command returns at 41. Load runs to 60.
FAULTS = {"inject_at_s": 10.0, "inject_returned_s": 10.5, "restore_at_s": 40.0, "restore_returned_s": 41.0,
          "inject_exit": 0, "restore_exit": 0}


def req(dispatch, done, status="ok"):
    return {"status": status, "dispatch_offset_s": dispatch, "scheduled_offset_s": dispatch, "total_s": done - dispatch}


def health(*points):
    return [{"t": t, "status": status} for t, status in points]


def test_requests_are_assigned_to_before_during_after_by_dispatch_time_with_their_own_error_rates():
    requests = ([req(1, 2), req(5, 6), req(9, 9.5)]                                   # before
                + [req(12, 72 - 12, "timeout"), req(20, 21, "error"), req(30, 31, "error")]   # during
                + [req(45, 46), req(50, 51, "error"), req(55, 56)])                  # after
    result = analyze(requests, [], FAULTS, duration_s=60)
    assert result["windows"]["before"] == {"offered": 3, "ok": 3, "error_rate": 0.0, "by_status": {"ok": 3}}
    assert result["windows"]["in_flight_at_injection"]["offered"] == 0
    during = result["windows"]["during"]
    assert during["offered"] == 3 and during["ok"] == 0 and during["error_rate"] == 1.0
    assert during["by_status"] == {"timeout": 1, "error": 2}
    after = result["windows"]["after"]
    assert after["offered"] == 3 and after["ok"] == 2 and after["error_rate"] == pytest.approx(1 / 3)


def test_requests_in_flight_when_the_fault_hits_are_their_own_window_so_the_baseline_stays_clean():
    # Dispatched at 9.9, still running at the injection (10.0) and failed at 10.2: a casualty of the fault, not baseline.
    requests = [req(1, 2), req(5, 6), req(9.9, 10.2, "error"), req(12, 13, "error")]
    windows = analyze(requests, [], FAULTS, duration_s=60)["windows"]
    assert windows["before"]["offered"] == 2 and windows["before"]["error_rate"] == 0.0
    assert windows["in_flight_at_injection"] == {"offered": 1, "ok": 0, "error_rate": 1.0, "by_status": {"error": 1}}
    assert windows["during"]["offered"] == 1
    assert sum(w["offered"] for w in windows.values()) == len(requests)             # every request is in exactly one window


def test_during_reports_how_many_of_its_requests_only_finished_after_the_restore():
    # Four requests sent while the fault was active: two fail inside the window, two are sent in the last instant before
    # the restore and are served after it. The headline error rate mixes them, so they are reported separately too.
    requests = [req(12, 15, "timeout"), req(20, 23, "timeout"), req(39.9, 40.4), req(39.95, 40.5)]
    during = analyze(requests, [], FAULTS, duration_s=60)["windows"]["during"]
    assert during["offered"] == 4 and during["error_rate"] == 0.5
    assert during["of_which_finished_after_restore"] == {"offered": 2, "ok": 2}
    none = analyze([req(12, 15, "timeout")], [], FAULTS, duration_s=60)["windows"]["during"]
    assert none["of_which_finished_after_restore"] == {"offered": 0, "ok": 0}
    before = analyze([req(1, 2)], [], FAULTS, duration_s=60)["windows"]["before"]
    assert "of_which_finished_after_restore" not in before                       # only the during window has it


def test_time_to_first_error_is_the_first_failed_completion_after_the_fault_was_injected():
    requests = [req(2, 3, "error"), req(9, 12.5, "error"), req(15, 17, "error")]      # the one at 3 s predates the fault
    assert analyze(requests, [], FAULTS, duration_s=60)["time_to_first_error_s"] == pytest.approx(2.5)


def test_no_error_after_the_fault_is_reported_as_none_with_a_note_never_zero():
    result = analyze([req(1, 2), req(20, 21)], [], FAULTS, duration_s=60)
    assert result["time_to_first_error_s"] is None
    assert any("no error was observed" in note for note in result["observations"])


def test_recovery_needs_a_request_dispatched_after_the_restore_that_succeeds():
    # A request dispatched at 35 (still faulted) that completes OK at 43 after the restore is NOT recovery evidence.
    requests = [req(35, 43), req(44, 49, "error"), req(46, 47.5)]
    result = analyze(requests, [], FAULTS, duration_s=60)
    assert result["time_to_recovery_s"] == pytest.approx(7.5)                         # 47.5 - 40.0
    assert result["time_to_recovery_after_restore_returned_s"] == pytest.approx(6.5)  # 47.5 - 41.0
    assert result["recovered_by_end"] is True


def test_no_successful_request_after_the_restore_means_no_recovery_is_claimed():
    result = analyze([req(45, 50, "error"), req(52, 57, "timeout")], [], FAULTS, duration_s=60)
    assert result["time_to_recovery_s"] is None and result["recovered_by_end"] is False
    assert any("no successful request was dispatched after the restore" in note for note in result["observations"])


def test_hosted_fallback_is_recorded_as_absent_when_nothing_succeeds_while_the_fault_is_active():
    result = analyze([req(1, 2), req(12, 13, "error"), req(20, 80, "timeout"), req(45, 46)], [], FAULTS, duration_s=60)
    fallback = result["fallback_behaviour"]
    assert fallback["documented"].startswith("none for provider local")
    assert fallback["succeeded_while_fault_active"] == 0 and fallback["observed"].startswith("no fallback observed")


def test_a_request_that_succeeds_after_the_inject_command_returned_and_before_the_restore_is_flagged_unexpected():
    # dispatched at 20, completed OK at 21, both inside the fault window: something served it despite the fault.
    result = analyze([req(20, 21), req(10.2, 10.4)], [], FAULTS, duration_s=60)       # 10.2 predates inject_returned
    fallback = result["fallback_behaviour"]
    assert fallback["succeeded_while_fault_active"] == 1 and fallback["observed"].startswith("UNEXPECTED")
    assert any("UNEXPECTED" in note for note in result["observations"])


def test_health_timeline_is_compared_with_the_documented_behaviour():
    probes = health((2, 200), (6, 200), (11, 503), (20, 503), (39, 503), (41, 503), (43, 200), (45, 200))
    result = analyze([], probes, FAULTS, duration_s=60)["health_serving"]
    assert result["probed"] is True and result["probes"] == 8
    assert result["documented_behaviour"] == {"healthy_before_fault": True, "unhealthy_during_fault": True,
                                             "healthy_after_restore": True}
    assert result["matches_documentation"] is True
    assert result["first_unhealthy_after_inject_s"] == pytest.approx(1.0)             # 11 - 10
    assert result["healthy_again_after_restore_s"] == pytest.approx(3.0)              # 43 - 40


def test_health_that_never_goes_unhealthy_or_never_recovers_does_not_match_the_documentation():
    stays_up = analyze([], health((2, 200), (20, 200), (45, 200)), FAULTS, duration_s=60)["health_serving"]
    assert stays_up["documented_behaviour"]["unhealthy_during_fault"] is False
    assert stays_up["matches_documentation"] is False and stays_up["first_unhealthy_after_inject_s"] is None
    stays_down = analyze([], health((2, 200), (20, 503), (45, 503)), FAULTS, duration_s=60)["health_serving"]
    assert stays_down["documented_behaviour"]["healthy_after_restore"] is False
    assert stays_down["healthy_again_after_restore_s"] is None and stays_down["matches_documentation"] is False


def test_connection_errors_count_as_unhealthy_and_an_unhealthy_start_flags_the_precondition():
    probes = [{"t": 2, "status": None, "error_type": "ConnectError"}, {"t": 20, "status": 503}, {"t": 45, "status": 200}]
    result = analyze([], probes, FAULTS, duration_s=60)["health_serving"]
    assert result["documented_behaviour"]["healthy_before_fault"] is False
    assert result["matches_documentation"] is False


def test_without_health_probes_nothing_is_claimed_about_health():
    result = analyze([req(1, 2)], [], FAULTS, duration_s=60)["health_serving"]
    assert result == {"probed": False, "probes": 0, "documented_behaviour": {
        "healthy_before_fault": None, "unhealthy_during_fault": None, "healthy_after_restore": None},
        "matches_documentation": None, "first_unhealthy_after_inject_s": None, "healthy_again_after_restore_s": None}


def test_rows_without_a_dispatch_offset_are_ignored_and_the_fault_record_is_echoed():
    rejected = {"status": "rejected", "scheduled_offset_s": 1.0, "total_s": 0.0}
    result = analyze([rejected, req(1, 2)], [], FAULTS, duration_s=60)
    assert result["windows"]["before"]["offered"] == 1
    assert result["fault"] == FAULTS and result["load_duration_s"] == 60


# --- orchestration -----------------------------------------------------------------------------------

import asyncio  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import shlex  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from eval.failure_behaviour import FaultCommandError, command_sha256, run_command, run_failure_behaviour  # noqa: E402
from tests.test_serving_load import case  # noqa: E402


class FakeServer:
    """A model server whose requests and health probe fail while `down` is True."""

    def __init__(self, inject_exit=0, restore_exit=0):
        self.down, self.injected, self.restored = False, 0, 0
        self.inject_exit, self.restore_exit = inject_exit, restore_exit
        self.inject_called = asyncio.Event()

    async def request(self, _case, _identifier):
        await asyncio.sleep(0.02)
        if self.down:
            raise ConnectionError("connection refused")
        return {"status": "ok"}

    async def health(self):
        return (503, None) if self.down else (200, None)

    async def inject(self):
        self.down = True
        self.injected += 1
        self.inject_called.set()
        return self.inject_exit

    async def restore(self):
        self.down = False
        self.restored += 1
        return self.restore_exit


def read_events(directory):
    return [json.loads(line) for line in (Path(directory) / "events.jsonl").read_text().splitlines()]


def manifest(**extra):
    return {"schema_version": 2, "mode": "failure_behaviour", "run_id": "fb-1", "target": "replay", "provider": "local",
            "workload_sha256": "w", "deployment": {}, **extra}


def run_kwargs(server, tmp_path, **overrides):
    return {"cases": [case()], "request": server.request, "out_dir": tmp_path / "run", "manifest": manifest(),
            "concurrency": 2, "duration_s": 1.4, "timeout_s": 5, "fault_at_s": 0.4, "fault_duration_s": 0.5,
            "inject": server.inject, "restore": server.restore, "health": server.health, "health_interval_s": 0.05,
            "command_hashes": {"inject": "i" * 64, "restore": "r" * 64}, **overrides}


@pytest.mark.asyncio
async def test_full_run_measures_the_fault_window_recovery_and_health_against_the_documented_behaviour(tmp_path):
    server = FakeServer()
    summary = await run_failure_behaviour(**run_kwargs(server, tmp_path))
    assert server.injected == 1 and server.restored == 1
    assert summary["windows"]["before"]["error_rate"] == 0
    # Windows are by dispatch time, so a request sent in the last ~20 ms before the restore can finish after it and
    # succeed; that boundary effect is real, so the test allows for it instead of demanding exactly 1.0.
    assert summary["windows"]["during"]["error_rate"] >= 0.9
    assert 0 <= summary["time_to_first_error_s"] < 0.4 and summary["recovered_by_end"] is True
    assert 0 <= summary["time_to_recovery_s"] < 0.4
    assert summary["fallback_behaviour"]["observed"].startswith("no fallback observed")
    assert summary["health_serving"]["matches_documentation"] is True
    events = read_events(tmp_path / "run")
    kinds = [e["event"] for e in events]
    assert kinds.count("fault_event") == 2 and "health_probe" in kinds and "cell_summary" in kinds
    assert "failure_behaviour_summary" in kinds and events[-1] == {**events[-1], "event": "run_end", "outcome": "complete"}
    assert "run_summary" not in kinds                                    # so comparison and capacity refuse this directory


@pytest.mark.asyncio
async def test_the_restore_command_still_runs_exactly_once_when_the_run_is_cancelled_after_the_fault(tmp_path):
    server = FakeServer()
    task = asyncio.create_task(run_failure_behaviour(**run_kwargs(server, tmp_path, duration_s=30, fault_duration_s=20)))
    await asyncio.wait_for(server.inject_called.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.restored == 1 and server.down is False                 # the server is never left faulted
    assert read_events(tmp_path / "run")[-1]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_a_failed_inject_command_aborts_early_still_attempts_a_restore_and_records_the_error(tmp_path):
    server = FakeServer(inject_exit=7)
    started = time.monotonic()
    with pytest.raises(FaultCommandError, match="inject"):
        await run_failure_behaviour(**run_kwargs(server, tmp_path, duration_s=30, fault_duration_s=20))
    assert time.monotonic() - started < 10                                # the 30 s load was cancelled, not waited out
    assert server.restored == 1
    events = read_events(tmp_path / "run")
    assert events[-1]["outcome"] == "error"
    assert [e["exit_code"] for e in events if e["event"] == "fault_event"][0] == 7


@pytest.mark.asyncio
async def test_commands_are_recorded_only_as_hashes_and_exit_codes(tmp_path):
    secret = "ssh secret-host.example kill -STOP 4242"
    hashes = {"inject": hashlib.sha256(secret.encode()).hexdigest(), "restore": "r" * 64}
    server = FakeServer()
    await run_failure_behaviour(**run_kwargs(server, tmp_path, command_hashes=hashes))
    text = (tmp_path / "run" / "events.jsonl").read_text() + (tmp_path / "run" / "manifest.json").read_text()
    assert "secret-host" not in text and "kill -STOP" not in text
    faults = [e for e in read_events(tmp_path / "run") if e["event"] == "fault_event"]
    assert faults[0]["command_sha256"] == hashes["inject"] and faults[0]["kind"] == "inject"
    assert faults[1]["kind"] == "restore" and faults[1]["exit_code"] == 0


@pytest.mark.asyncio
async def test_a_run_without_a_health_probe_claims_nothing_about_health(tmp_path):
    summary = await run_failure_behaviour(**run_kwargs(FakeServer(), tmp_path, health=None))
    assert summary["health_serving"]["probed"] is False and summary["health_serving"]["matches_documentation"] is None


@pytest.mark.asyncio
async def test_the_failure_directory_is_refused_by_the_comparison_and_capacity_tools(tmp_path):
    from eval.capacity_plan import estimate_capacity
    from eval.quantization_compare import compare_sustained_runs
    await run_failure_behaviour(**run_kwargs(FakeServer(), tmp_path))
    run = tmp_path / "run"
    with pytest.raises(ValueError):
        compare_sustained_runs(run, run)
    with pytest.raises(ValueError):
        estimate_capacity([run], latency_slo_s=None, max_error_rate=0.01, headroom=0.7, target_rps=None)


@pytest.mark.asyncio
async def test_the_load_cell_records_a_wall_clock_window_so_gpu_samples_can_be_attached(tmp_path):
    from eval import gpu_utilization as gu
    await run_failure_behaviour(**run_kwargs(FakeServer(), tmp_path))
    report = gu.build_report(tmp_path / "run", tmp_path / "no-samples.jsonl", clock_offset_s=0.0)
    assert len(report["cells"]) == 1 and report["cells"][0]["window"] is not None


@pytest.mark.asyncio
async def test_run_command_returns_the_exit_code_and_none_on_timeout():
    python = shlex.quote(sys.executable)                       # the path may contain spaces; commands are not run in a shell
    assert await run_command(f'{python} -c "import sys; sys.exit(3)"', timeout_s=20) == 3
    assert await run_command(f'{python} -c "pass"', timeout_s=20) == 0
    assert await run_command(f'{python} -c "import time; time.sleep(30)"', timeout_s=0.3) is None


def test_the_word_failover_is_not_used_in_code_or_docs():
    paths = [Path("eval/failure_behaviour.py"), Path("docs/benchmarking.md"), Path("docs/serving-observability.md"),
             Path("docs/superpowers/specs/2026-10-06-harness-improvements-design.md"),
             Path("docs/superpowers/plans/2026-10-06-harness-improvements.md"),
             Path("docs/superpowers/plans/2026-10-06-live-gpu-session.md")]
    offenders = [str(path) for path in paths if "failover" in path.read_text().lower()]
    assert offenders == []


# --- CLI ---------------------------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402

from app.services import llm  # noqa: E402
from eval.failure_behaviour import main, parse_args  # noqa: E402
from tests.test_serving_load import workload_file  # noqa: E402

NOOP = f'{shlex.quote(sys.executable)} -c "pass"'
CLI_BASE = ["--workloads", "w.json", "--out-dir", "out", "--inject-cmd", "inject", "--restore-cmd", "restore",
            "--duration", "20", "--fault-at", "5", "--fault-duration", "5"]


def test_commands_are_required_and_only_run_with_an_explicit_confirmation():
    with pytest.raises(SystemExit):
        parse_args(["--workloads", "w.json", "--out-dir", "o", "--duration", "20", "--yes-run-fault-commands"])
    with pytest.raises(SystemExit):                                       # commands given but not confirmed
        parse_args(CLI_BASE)
    args = parse_args([*CLI_BASE, "--yes-run-fault-commands"])
    assert args.inject_cmd == "inject" and args.concurrency == 16


def test_the_fault_must_end_before_the_load_does():
    with pytest.raises(SystemExit):
        parse_args(["--workloads", "w.json", "--out-dir", "o", "--inject-cmd", "i", "--restore-cmd", "r",
                    "--duration", "20", "--fault-at", "15", "--fault-duration", "5", "--yes-run-fault-commands"])


def test_api_runs_need_a_token_and_use_reuse_mode():
    with pytest.raises(SystemExit):
        parse_args([*CLI_BASE, "--target", "api", "--yes-run-fault-commands"])
    args = parse_args([*CLI_BASE, "--target", "api", "--auth-token-file", "t", "--yes-run-fault-commands"])
    assert args.cache_mode == "reuse"


@pytest.mark.asyncio
async def test_validate_only_needs_no_confirmation_and_creates_nothing(tmp_path, capsys):
    path = workload_file(tmp_path)
    await main(["--workloads", str(path), "--out-dir", str(tmp_path / "run"), "--inject-cmd", "i", "--restore-cmd", "r",
                "--duration", "20", "--fault-at", "5", "--fault-duration", "5", "--validate-only"])
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert not (tmp_path / "run").exists()


@pytest.mark.asyncio
async def test_cli_run_reports_honestly_when_the_fault_commands_do_not_affect_the_server(tmp_path, capsys):
    path = workload_file(tmp_path)

    async def stream(messages, **kwargs):
        await asyncio.sleep(0.02)
        kwargs["usage_sink"].update(completion_tokens=2, prompt_tokens=5, finish_reason="stop")
        yield "hello"
    original = (llm.settings.llm_provider, llm.settings.fallback_llm_provider)
    with patch.object(llm, "chat_stream", stream):
        analysis = await main(["--workloads", str(path), "--out-dir", str(tmp_path / "run"), "--provider", "groq",
                               "--inject-cmd", NOOP, "--restore-cmd", NOOP, "--duration", "1.6", "--fault-at", "0.4",
                               "--fault-duration", "0.5", "--concurrency", "2", "--yes-run-fault-commands"])
    assert original == (llm.settings.llm_provider, llm.settings.fallback_llm_provider)      # settings restored
    assert analysis["time_to_first_error_s"] is None                          # the no-op fault caused no error
    assert analysis["fallback_behaviour"]["observed"].startswith("UNEXPECTED")  # and the tool says so, not "all good"
    assert any("no error was observed" in note for note in analysis["observations"])
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["mode"] == "failure_behaviour" and manifest["fault"]["inject_command_sha256"] == command_sha256(NOOP)
    assert "-c" not in json.dumps(manifest["fault"])                          # the command text is not recorded
    assert "observations" in json.loads(capsys.readouterr().out)


def test_the_subcommand_is_reachable_through_the_benchmark_entry_point(tmp_path):
    import subprocess
    path = workload_file(tmp_path)
    done = subprocess.run([sys.executable, "-m", "eval.inference_benchmark", "failure-behaviour", "--workloads", str(path),
                           "--out-dir", str(tmp_path / "o"), "--inject-cmd", "i", "--restore-cmd", "r",
                           "--duration", "20", "--fault-at", "5", "--fault-duration", "5", "--validate-only"],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and json.loads(done.stdout.splitlines()[-1])["valid"] is True


def test_the_runbook_documents_each_new_command_and_flag_that_exists_in_the_code():
    docs = " ".join(Path("docs/benchmarking.md").read_text().split())
    for flag in ("--prefix-cache-comparison", "--engine", "--yes-run-fault-commands", "--inject-cmd", "--restore-cmd",
                 "--fault-at", "--fault-duration", "--health-url", "eval.batching_compare", "failure-behaviour"):
        assert flag in docs, flag
    args = parse_args([*CLI_BASE, "--yes-run-fault-commands", "--health-url", "http://127.0.0.1:1/h"])
    assert args.health_url and args.fault_at == 5
    for phrase in ("no hosted fallback", "in_flight_at_injection", "UNEXPECTED", "SHA-256 hashes", "run_summary",
                   "second-largest", "control", "unverified", "of_which_finished_after_restore"):
        assert phrase in docs, phrase
    lowered = docs.lower()
    for banned in ("failover", "human evaluation", "ground truth", "statistically significant"):
        assert banned not in lowered, banned
