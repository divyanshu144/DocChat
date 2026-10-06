import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from eval import gpu_utilization as gu

BASE = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def make_run(tmp_path, cells=None, gpu_count=1, schema=2, with_windows=True):
    """A minimal schema-v2 run directory: warmup cell [0, 20] and one measurement cell [60, 90] by default."""
    cells = cells or [{"cell_id": "r1-c4-rateNone-warmup", "phase": "warmup", "start": 0, "end": 20},
                      {"cell_id": "r1-c4-rateNone", "phase": "measurement", "start": 60, "end": 90}]
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps(
        {"schema_version": schema, "run_id": "run-1", "deployment": {"gpu_count": gpu_count}}))
    events = []
    for cell in cells:
        event = {"event": "cell_summary", "schema_version": 2, "run_id": "run-1", "cell_id": cell["cell_id"],
                 "phase": cell["phase"], "concurrency": cell.get("concurrency", 4),
                 "arrival_rate": cell.get("rate"), "interrupted": False, "summary": {}}
        if with_windows:
            event["window"] = {"started_at": at(cell["start"]), "ended_at": at(cell["end"]),
                               "clock": "benchmark_client_wall_clock_utc"}
        events.append(event)
    events.append({"event": "run_end", "outcome": "complete", "schema_version": 2, "run_id": "run-1"})
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return run


def make_samples(tmp_path, samples, interval_s=1.0, header=None, extra_lines=(), name="samples.jsonl"):
    """samples: (seconds_from_BASE, gpu_index, util_pct|None)."""
    lines = [json.dumps({"event": "sampler_start", "schema_version": 1, "backend": "fake",
                         "clock_source": "gpu_host_wall_clock_utc", "interval_s": interval_s, "ts": at(0),
                         **(header or {})})]
    for seconds, gpu, util in samples:
        lines.append(json.dumps({"event": "gpu_sample", "ts": at(seconds), "gpu": gpu, "util_pct": util,
                                 "mem_used_mib": 1000.0 + gpu, "mem_total_mib": 40000.0, "power_w": 200.0}))
    lines.extend(extra_lines)
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


def series(start, end, gpu=0, value=lambda t: 50.0):
    return [(t, gpu, value(t)) for t in range(start, end + 1)]


def only_cell(report):
    assert len(report["cells"]) == 1                      # warmup cells are never attached
    return report["cells"][0]


def test_normal_window_reports_mean_p95_max_and_sample_count(tmp_path):
    run = make_run(tmp_path)
    # utilization equals the second offset inside the window: 1..31 (inclusive of both window edges)
    samples = (series(40, 59, value=lambda t: 5.0) + series(60, 90, value=lambda t: float(t - 59))
               + series(91, 110, value=lambda t: 5.0))
    report = gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0)
    cell = only_cell(report)
    stats = cell["per_gpu"]["0"]
    assert cell["status"] == "ok" and stats["status"] == "ok"
    assert stats["n_samples"] == 31 and stats["max_pct"] == 31.0
    assert stats["mean_pct"] == pytest.approx(16.0)
    assert stats["p95_pct"] == 30.0                       # nearest rank, same as serving_load.percentile
    assert stats["memory_used_mib_max"] == 1000.0 and stats["power_w_mean"] == 200.0


def test_warmup_window_is_excluded(tmp_path):
    run = make_run(tmp_path)
    samples = series(0, 20, value=lambda t: 99.0) + series(40, 59, value=lambda t: 1.0) + series(60, 90, value=lambda t: 20.0)
    report = gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0)
    cell = only_cell(report)
    assert cell["cell_id"] == "r1-c4-rateNone" and "warmup" not in cell["cell_id"]
    stats = cell["per_gpu"]["0"]
    assert stats["mean_pct"] == 20.0 and stats["max_pct"] == 20.0     # the 99% warmup samples do not leak in


def test_missing_samples_file_records_unavailable_with_a_reason_and_no_values(tmp_path):
    run = make_run(tmp_path)
    report = gu.attach(run, tmp_path / "does-not-exist.jsonl")
    cell = only_cell(report)
    assert cell["status"] == "unavailable" and "not found" in cell["reason"] and cell["per_gpu"] == {}
    assert report["samples_sha256"] is None
    assert json.loads((run / gu.FILENAME).read_text())["cells"][0]["status"] == "unavailable"


def test_too_few_samples_in_the_window_is_unavailable_not_estimated(tmp_path):
    run = make_run(tmp_path)
    # 10-second sampler interval: four samples (60, 70, 80, 90) inside the 30-second window, which they cover
    samples = [(55, 0, 40.0), (60, 0, 41.0), (70, 0, 42.0), (80, 0, 43.0), (90, 0, 44.0), (95, 0, 45.0)]
    report = gu.attach(run, make_samples(tmp_path, samples, interval_s=10.0), clock_offset_s=0.0, min_samples=10)
    stats = only_cell(report)["per_gpu"]["0"]
    assert stats["status"] == "unavailable" and stats["n_samples"] == 4
    assert "minimum is 10" in stats["reason"] and "mean_pct" not in stats
    assert only_cell(report)["status"] == "unavailable"


def test_clock_offset_aligns_a_gpu_host_clock_that_runs_ahead(tmp_path):
    # The GPU host clock is 30 s ahead of the benchmark client: every sample timestamp is +30 s.
    ahead = [(t + 30, 0, 80.0) for t in range(40, 111)]
    run = make_run(tmp_path)
    samples = make_samples(tmp_path, ahead)
    unaligned = gu.build_report(run, samples)                       # offset not supplied -> assumed zero
    assert only_cell(unaligned)["status"] == "unavailable"
    assert "do not cover" in only_cell(unaligned)["per_gpu"]["0"]["reason"]   # misaligned, so never reported as ok
    assert unaligned["alignment"]["offset_provenance"] == "assumed_zero_not_measured"
    aligned = gu.attach(run, samples, clock_offset_s=30.0)
    stats = only_cell(aligned)["per_gpu"]["0"]
    assert only_cell(aligned)["status"] == "ok" and stats["mean_pct"] == 80.0 and stats["n_samples"] == 31
    assert aligned["alignment"]["clock_offset_s"] == 30.0
    assert aligned["alignment"]["offset_provenance"] == "operator_supplied"
    assert aligned["alignment"]["sampler_clock"] == "gpu_host_wall_clock_utc"
    assert aligned["alignment"]["window_clock"] == ["benchmark_client_wall_clock_utc"]


def test_multi_gpu_host_reports_each_gpu_separately_and_never_averages_across_gpus(tmp_path):
    run = make_run(tmp_path, gpu_count=2)
    samples = series(40, 110, gpu=0, value=lambda t: 90.0) + series(40, 110, gpu=1, value=lambda t: 10.0)
    report = gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0)
    cell = only_cell(report)
    assert cell["status"] == "ok" and set(cell["per_gpu"]) == {"0", "1"}
    assert cell["per_gpu"]["0"]["mean_pct"] == 90.0 and cell["per_gpu"]["1"]["mean_pct"] == 10.0
    assert "mean_pct" not in cell                                    # no cross-GPU aggregate
    assert report["gpu_count"] == {"sampled": 2, "manifest": 2, "matches_manifest": True}


def test_multi_gpu_host_with_one_gpu_short_is_partial(tmp_path):
    run = make_run(tmp_path, gpu_count=2)
    samples = series(40, 110, gpu=0) + series(80, 110, gpu=1)       # gpu 1 only covers the end of the window
    cell = only_cell(gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0))
    assert cell["status"] == "partial"
    assert cell["per_gpu"]["0"]["status"] == "ok" and cell["per_gpu"]["1"]["status"] == "unavailable"
    assert "gpu 1" in cell["reason"]


def test_gpu_count_mismatch_with_the_manifest_is_flagged_not_corrected(tmp_path):
    run = make_run(tmp_path, gpu_count=1)
    samples = series(40, 110, gpu=0) + series(40, 110, gpu=1)
    report = gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0)
    assert report["gpu_count"] == {"sampled": 2, "manifest": 1, "matches_manifest": False}
    assert set(only_cell(report)["per_gpu"]) == {"0", "1"}


def test_artifact_without_a_recorded_window_is_unavailable(tmp_path):
    run = make_run(tmp_path, with_windows=False)
    cell = only_cell(gu.attach(run, make_samples(tmp_path, series(40, 110)), clock_offset_s=0.0))
    assert cell["status"] == "unavailable" and "window not recorded" in cell["reason"] and cell["window"] is None


def test_samples_that_start_late_do_not_cover_the_window(tmp_path):
    run = make_run(tmp_path)
    report = gu.attach(run, make_samples(tmp_path, series(80, 110)), clock_offset_s=0.0, min_samples=5)
    stats = only_cell(report)["per_gpu"]["0"]
    assert stats["status"] == "unavailable" and "do not cover" in stats["reason"] and "mean_pct" not in stats


def test_sampler_that_reported_no_backend_makes_every_cell_unavailable_with_its_reason(tmp_path):
    run = make_run(tmp_path)
    path = make_samples(tmp_path, [], header={"backend": "unavailable", "unavailable_reason": "no driver on this host"})
    cell = only_cell(gu.attach(run, path, clock_offset_s=0.0))
    assert cell["status"] == "unavailable" and "no driver on this host" in cell["reason"]


def test_null_utilization_samples_are_ignored_and_malformed_lines_are_counted(tmp_path):
    run = make_run(tmp_path)
    samples = series(40, 110, value=lambda t: None if t % 2 else 60.0)
    path = make_samples(tmp_path, samples, extra_lines=["{not json", json.dumps({"event": "sampler_error",
                                                                              "error_type": "RuntimeError", "ts": at(70)})])
    report = gu.attach(run, path, clock_offset_s=0.0)
    stats = only_cell(report)["per_gpu"]["0"]
    assert stats["mean_pct"] == 60.0 and stats["n_samples"] == 16     # 16 even seconds in [60, 90]
    assert report["malformed_lines"] == 1 and report["sampler_error_records"] == 1


def test_attach_never_modifies_run_artifacts_and_refuses_to_overwrite(tmp_path):
    run = make_run(tmp_path)
    before = {name: (run / name).read_bytes() for name in ("manifest.json", "events.jsonl")}
    samples = make_samples(tmp_path, series(40, 110))
    gu.attach(run, samples, clock_offset_s=0.0)
    assert {name: (run / name).read_bytes() for name in before} == before
    saved = (run / gu.FILENAME).read_text()
    with pytest.raises(FileExistsError):
        gu.attach(run, samples, clock_offset_s=0.0)
    assert (run / gu.FILENAME).read_text() == saved


def test_attach_requires_a_schema_v2_run_with_measurement_cells(tmp_path):
    with pytest.raises(ValueError, match="schema-v2"):
        gu.build_report(make_run(tmp_path, schema=1), tmp_path / "x.jsonl")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "manifest.json").write_text(json.dumps({"schema_version": 2, "run_id": "r"}))
    (empty / "events.jsonl").write_text(json.dumps({"event": "run_end"}) + "\n")
    with pytest.raises(ValueError, match="no measurement cells"):
        gu.build_report(empty, tmp_path / "x.jsonl")


def test_report_is_content_free_and_carries_the_meaning_notes(tmp_path):
    run = make_run(tmp_path)
    report = gu.attach(run, make_samples(tmp_path, series(40, 110)), clock_offset_s=0.0)
    text = json.dumps(report)
    assert report["samples_file"] == "samples.jsonl" and str(tmp_path) not in text   # basename only, no paths
    assert any("busy, not that it was efficient" in note for note in report["notes"])
    assert not ({"prompt", "answer", "messages", "hostname"} & set(report))


def test_summarize_by_load_aggregates_repeats_and_counts_repeats_without_data(tmp_path):
    cells = [{"cell_id": "r1-c4", "phase": "measurement", "start": 60, "end": 90},
             {"cell_id": "r2-c4", "phase": "measurement", "start": 200, "end": 230}]
    run = make_run(tmp_path, cells)
    samples = series(40, 110, value=lambda t: 40.0) + series(190, 215, value=lambda t: 80.0)   # r2 not fully covered
    report = gu.attach(run, make_samples(tmp_path, samples), clock_offset_s=0.0)
    summary = gu.summarize_by_load(report)[(4, None)]
    assert summary["repeats"] == 2 and summary["status"] == "partial"
    assert summary["per_gpu"]["0"]["repeats_with_data"] == 1 and summary["per_gpu"]["0"]["mean_pct"] == 40.0
    assert summary["reasons"]


def test_load_gpu_utilization_is_none_when_nothing_was_attached(tmp_path):
    run = make_run(tmp_path)
    assert gu.load_gpu_utilization(run) is None
    gu.attach(run, make_samples(tmp_path, series(40, 110)), clock_offset_s=0.0)
    assert gu.load_gpu_utilization(run)["run_id"] == "run-1"


def test_cli_attach_writes_the_file_and_reports_cell_counts(tmp_path, capsys):
    run = make_run(tmp_path)
    path = make_samples(tmp_path, series(40, 110))
    assert gu.main(["attach", str(run), str(path), "--clock-offset-s", "0"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["cells"] == {"ok": 1, "partial": 0, "unavailable": 0}
    assert printed["offset_provenance"] == "operator_supplied" and Path(printed["written"]).exists()


# --- clock offset: sign convention and warnings ------------------------------------------------

def test_offset_sign_convention_is_gpu_host_minus_client_and_a_flipped_sign_fails(tmp_path):
    # GPU host AHEAD of the client by 30 s: the correct offset is +30, and the flipped sign (-30) would double the error.
    ahead_dir = tmp_path / "ahead"
    ahead_dir.mkdir()
    run = make_run(ahead_dir)
    ahead = make_samples(tmp_path, [(t + 30, 0, 80.0) for t in range(40, 111)], name="ahead.jsonl")
    assert only_cell(gu.build_report(run, ahead, clock_offset_s=30.0))["status"] == "ok"
    assert only_cell(gu.build_report(run, ahead, clock_offset_s=-30.0))["status"] == "unavailable"
    # GPU host BEHIND the client by 45 s: the correct offset is -45, and the flipped sign (+45) must fail.
    behind_dir = tmp_path / "behind"
    behind_dir.mkdir()
    run = make_run(behind_dir)
    behind = make_samples(tmp_path, [(t - 45, 0, 80.0) for t in range(40, 111)], name="behind.jsonl")
    assert only_cell(gu.build_report(run, behind, clock_offset_s=-45.0))["status"] == "ok"
    assert only_cell(gu.build_report(run, behind, clock_offset_s=45.0))["status"] == "unavailable"


def test_sign_convention_is_defined_once_and_quoted_by_the_report_cli_help_and_docs(tmp_path, capsys):
    run = make_run(tmp_path)
    report = gu.build_report(run, make_samples(tmp_path, series(40, 110)), clock_offset_s=0.0)
    assert report["alignment"]["convention"] == gu.OFFSET_CONVENTION
    with pytest.raises(SystemExit):
        gu.main(["attach", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert " ".join(gu.OFFSET_CONVENTION.split()) in help_text
    docs = " ".join(Path("docs/benchmarking.md").read_text().split())
    assert " ".join(gu.OFFSET_CONVENTION.split()) in docs                  # drift between code and runbook fails here
    assert "gpu_host_clock - benchmark_client_clock" in gu.OFFSET_CONVENTION


def short_cell_run(tmp_path, seconds):
    return make_run(tmp_path, [{"cell_id": "r1-c1-rateNone", "phase": "measurement", "start": 60, "end": 60 + seconds}])


def test_warns_when_offset_is_assumed_zero_and_a_cell_window_is_short(tmp_path):
    run = short_cell_run(tmp_path, 20)
    report = gu.attach(run, make_samples(tmp_path, series(40, 100)))                  # no offset supplied
    assert report["alignment"]["offset_provenance"] == "assumed_zero_not_measured"
    [warning] = report["warnings"]
    assert warning["code"] == "offset_not_measured_short_windows" and warning["cells"] == ["r1-c1-rateNone"]
    assert "not measured" in warning["message"] and "--clock-offset-s" in warning["message"]
    assert only_cell(report)["status"] in {"ok", "unavailable", "partial"}            # a warning, never an error


def test_no_warning_when_the_offset_was_supplied_or_every_window_is_long_enough(tmp_path):
    supplied_dir = tmp_path / "supplied"
    supplied_dir.mkdir()
    run = short_cell_run(supplied_dir, 20)
    samples = make_samples(tmp_path, series(40, 100))
    assert gu.build_report(run, samples, clock_offset_s=0.0)["warnings"] == []          # operator supplied it
    long_dir = tmp_path / "long"
    long_dir.mkdir()
    at_threshold = short_cell_run(long_dir, 30)                                            # exactly 30 s: no warning
    assert gu.build_report(at_threshold, samples)["warnings"] == []


def test_cli_prints_the_warning_on_stderr_and_lists_its_code(tmp_path, capsys):
    run = short_cell_run(tmp_path, 10)
    path = make_samples(tmp_path, series(40, 100))
    assert gu.main(["attach", str(run), str(path)]) == 0
    captured = capsys.readouterr()
    assert "WARNING" in captured.err and "offset" in captured.err
    assert json.loads(captured.out)["warnings"] == ["offset_not_measured_short_windows"]


# --- dry check ----------------------------------------------------------------------------------

def test_dry_check_prints_expected_vs_actual_and_spans_and_writes_nothing(tmp_path):
    run = make_run(tmp_path)
    samples = make_samples(tmp_path, series(40, 110))
    before = {p.name: p.read_bytes() for p in (run / "manifest.json", run / "events.jsonl", samples)}
    lines = gu.dry_check(run, samples, clock_offset_s=0.0)
    text = "\n".join(lines)
    assert "offset +0.00s (operator_supplied); sampler interval 1.0s" in text
    assert "r1-c4-rateNone: window 30.0s, expected ~30 samples per GPU, actual gpu0=31 -> ok" in text
    assert "samples span" in text and "windows span" in text
    assert not (run / gu.FILENAME).exists()                                       # nothing written
    assert {p.name: p.read_bytes() for p in (run / "manifest.json", run / "events.jsonl", samples)} == before


def test_dry_check_explains_a_problem_without_failing_or_writing(tmp_path):
    run = make_run(tmp_path)
    late = make_samples(tmp_path, series(85, 110))                                  # sampler started late
    text = "\n".join(gu.dry_check(run, late, clock_offset_s=0.0, min_samples=5))
    assert "-> unavailable" in text and "do not cover" in text
    missing = "\n".join(gu.dry_check(run, tmp_path / "nope.jsonl"))
    assert "sampler file not found" in missing and "unknown" in missing
    assert not (run / gu.FILENAME).exists()


def test_cli_dry_check_writes_nothing_even_after_a_real_attach(tmp_path, capsys):
    run = make_run(tmp_path)
    samples = make_samples(tmp_path, series(40, 110))
    assert gu.main(["attach", str(run), str(samples), "--clock-offset-s", "0", "--dry-check"]) == 0
    out = capsys.readouterr().out
    assert "expected ~30 samples per GPU" in out and not (run / gu.FILENAME).exists()
    gu.attach(run, samples, clock_offset_s=0.0)
    saved = (run / gu.FILENAME).read_text()
    assert gu.main(["attach", str(run), str(samples), "--clock-offset-s", "0", "--dry-check"]) == 0   # no overwrite error
    assert (run / gu.FILENAME).read_text() == saved


# --- the report and docs do not overclaim --------------------------------------------------------

SENTENCE = ("share of the sample period in which at least one kernel was running, so 100 percent "
            "does not mean the GPU is fully used")


def _gpu_doc_text():
    obs = Path("docs/serving-observability.md").read_text()
    bench = Path("docs/benchmarking.md").read_text()
    return (obs[obs.index("## GPU utilization (a separate signal)"):obs.index("## Verification and next phase")]
            + bench[bench.index("## GPU utilization (optional, separate signal)"):])


def test_docs_define_utilization_precisely_and_never_equate_busy_with_efficient():
    text = " ".join(_gpu_doc_text().split())
    assert SENTENCE in " ".join(Path("docs/serving-observability.md").read_text().split())
    assert "not that it was efficient" in text and "a low reading does not show where a limit was" in text
    lowered = text.lower()
    for banned in ("bottleneck", "saturated", "is efficient", "means efficient", "high utilization means"):
        assert banned not in lowered, banned


def test_how_to_read_it_table_hedges_every_row_and_has_no_made_up_numbers():
    obs = Path("docs/serving-observability.md").read_text()
    table = obs[obs.index("### How to read it"):obs.index("Alignment depends on two clocks")]
    rows = [line for line in table.splitlines() if line.startswith(("| High", "| Low"))]
    assert len(rows) == 3
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert " may " in f" {cells[3].lower()} ", row                      # the "What it MAY suggest" cell is hedged
        assert cells[4], row                                                  # and every row says what to check next
    assert "proves" not in table.lower() and "diagnos" in table.lower()      # framed as prompts, not diagnoses
    assert not [w for w in table.replace("100 percent", "").split() if w.rstrip("%.,;").isdigit()]


def test_attach_report_notes_carry_the_same_precise_definition(tmp_path):
    report = gu.build_report(make_run(tmp_path), make_samples(tmp_path, series(40, 110)), clock_offset_s=0.0)
    notes = " ".join(report["notes"])
    assert "at least one kernel was running" in notes and "100% does not mean the GPU is fully used" in notes
    assert "not that it was efficient" in notes and "does not show where a limit was" in notes


# --- runbook stays in sync with the code ---------------------------------------------------------

def test_runbook_flags_exist_in_the_cli_and_the_first_live_run_section_is_complete(capsys):
    bench = Path("docs/benchmarking.md").read_text()
    section = bench[bench.index("### First live run"):bench.index("### What gets recorded per cell")]
    with pytest.raises(SystemExit):
        gu.main(["attach", "--help"])
    help_text = capsys.readouterr().out
    for flag in ("--dry-check", "--clock-offset-s", "--min-samples"):
        assert flag in bench and flag in help_text, flag
    for must_have in ("Short window", "Clock offset", "Sampler started late or stopped early", "matches_manifest",
                      "operator_supplied", "illustration only"):
        assert must_have in section, must_have
    for status in ("`ok`", "`partial`", "`unavailable`"):
        assert status in section


def test_fake_example_numbers_are_labelled_as_illustrations():
    bench = Path("docs/benchmarking.md").read_text()
    paragraph = next(p for p in bench.split("\n\n") if "1760000042.50" in p)
    assert "made up" in paragraph and "not a measurement" in paragraph
    assert "+30.30" in paragraph and "-22.20" in paragraph                  # the arithmetic in the example is right
    assert 1760000042.50 - 1760000012.20 == pytest.approx(30.30)
    assert 1759999990.00 - 1760000012.20 == pytest.approx(-22.20)
