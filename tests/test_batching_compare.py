import json

import pytest

from eval.batching_compare import compare_batching, main


def row(concurrency, mode, wall, tokens=1000, n_total=16, n_ok=16, provider="local", timestamp="2026-10-06T10:00:00+00:00"):
    base = {"provider": provider, "concurrency": concurrency, "timestamp": timestamp,
            "summary": {"n_total": n_total, "n_ok": n_ok, "wall_time_s": wall, "total_output_tokens": tokens,
                        "aggregate_tok_s": tokens / wall if wall else None}}
    return base if mode is None else {**base, "mode": mode}


def test_reports_wall_time_speedup_and_throughput_ratio_per_shared_batch_size():
    result = compare_batching([row(4, "serial", 100), row(4, "concurrent", 25),
                               row(16, "serial", 400), row(16, "concurrent", 50)])
    by_n = {entry["batch_size"]: entry for entry in result["batches"]}
    assert by_n[4]["comparable"] and by_n[4]["wall_time_speedup"] == pytest.approx(4.0)
    assert by_n[4]["throughput_ratio"] == pytest.approx(4.0) and by_n[16]["wall_time_speedup"] == pytest.approx(8.0)
    assert by_n[4]["serial_wall_s"] == 100 and by_n[4]["concurrent_wall_s"] == 25 and by_n[4]["n_requests"] == 16
    assert any("One run per mode" in limit for limit in result["limits"])


def test_old_rows_without_a_mode_field_count_as_concurrent():
    result = compare_batching([row(4, "serial", 80), row(4, None, 20)])
    assert result["batches"][0]["wall_time_speedup"] == pytest.approx(4.0)


def test_batch_size_one_is_skipped_and_unmatched_sizes_are_listed():
    result = compare_batching([row(1, "serial", 10), row(1, "concurrent", 10), row(4, "serial", 40),
                               row(16, "concurrent", 20)])
    assert result["batches"] == []
    assert result["skipped"] == {"batch_size_1": "serial and concurrent are identical by construction",
                                 "serial_only": [4], "concurrent_only": [16]}


@pytest.mark.parametrize("serial,concurrent,reason", [
    (row(4, "serial", 100, n_ok=15), row(4, "concurrent", 25), "failed requests"),
    (row(4, "serial", 100), row(4, "concurrent", 25, n_ok=14), "failed requests"),
    (row(4, "serial", 100, n_total=8, n_ok=8), row(4, "concurrent", 25), "different numbers of requests"),
    (row(4, "serial", 0), row(4, "concurrent", 25), "wall time"),
])
def test_pairs_with_failures_different_sizes_or_no_wall_time_are_not_comparable_and_have_no_ratios(serial, concurrent, reason):
    entry = compare_batching([serial, concurrent])["batches"][0]
    assert entry["comparable"] is False and reason in entry["reason"]
    assert entry["wall_time_speedup"] is None and entry["throughput_ratio"] is None


def test_flags_when_output_lengths_differ_enough_to_mix_batching_with_length():
    entry = compare_batching([row(4, "serial", 100, tokens=1000), row(4, "concurrent", 25, tokens=1400)])["batches"][0]
    assert entry["comparable"] and entry["output_length_differs"] is True
    assert "output length" in entry["caveat"] and entry["output_tokens_serial"] == 1000
    same = compare_batching([row(4, "serial", 100, tokens=1000), row(4, "concurrent", 25, tokens=1050)])["batches"][0]
    assert same["output_length_differs"] is False and "caveat" not in same


def test_duplicate_rows_and_mixed_providers_are_refused():
    with pytest.raises(ValueError, match="multiple rows"):
        compare_batching([row(4, "serial", 100), row(4, "serial", 90), row(4, "concurrent", 25)])
    with pytest.raises(ValueError, match="one provider"):
        compare_batching([row(4, "serial", 100), row(4, "concurrent", 25, provider="groq")])
    with pytest.raises(ValueError, match="no rows"):
        compare_batching([])


def test_cli_filters_by_provider_and_window_and_prints_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bench.jsonl"
    rows = [row(4, "serial", 100), row(4, "concurrent", 25),
            row(4, "serial", 999, timestamp="2026-10-05T10:00:00+00:00"),       # outside the window
            row(4, "serial", 5, provider="groq")]                               # other provider
    path.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr("sys.argv", ["batching_compare", "--jsonl", str(path), "--since", "2026-10-06T00:00:00+00:00",
                                     "--until", "2026-10-07T00:00:00+00:00"])
    main()
    printed = json.loads(capsys.readouterr().out)
    assert printed["batches"][0]["wall_time_speedup"] == pytest.approx(4.0)
