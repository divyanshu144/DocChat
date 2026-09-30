"""Unit tests for eval/inference_benchmark.py's pure logic.

Percentiles, summarization, and cost math — no LLM, no `eval` marker, runs in
the normal suite. Live requests (`_run_request` / `_run_provider`) are
exercised manually against real endpoints, same bar as eval/benchmark.py.
"""

import json
import math
from pathlib import Path

import pytest

from eval.inference_benchmark import (
    _bust_prompt,
    _cost_for_run,
    _fmt_row,
    _load_prompts,
    _local_cost_per_1m_output_tokens,
    _local_cost_per_request,
    _parse_prometheus_metrics,
    _percentile,
    _summarize,
    _summarize_vllm_metrics,
)


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


def test_percentile_p50_of_odd_count():
    assert _percentile([1.0, 2.0, 3.0], 50) == 2.0


def test_percentile_p100_is_the_max():
    assert _percentile([1.0, 5.0, 3.0], 100) == 5.0


def test_percentile_p0_is_the_min():
    assert _percentile([3.0, 1.0, 5.0], 0) == 1.0


def test_percentile_single_value():
    assert _percentile([7.0], 50) == 7.0
    assert _percentile([7.0], 99) == 7.0


def test_percentile_empty_raises():
    """Silent 0.0 would read as a real (impossibly fast) measurement."""
    with pytest.raises(ValueError):
        _percentile([], 50)


def test_percentile_unsorted_input():
    assert _percentile([9.0, 1.0, 5.0, 3.0, 7.0], 50) == 5.0


# ---------------------------------------------------------------------------
# _summarize
# ---------------------------------------------------------------------------


def _ok(ttft: float, total: float, tokens: int, input_tokens: int = 10) -> dict:
    return {
        "status": "ok",
        "error_type": None,
        "finish_reason": "stop",
        "input_tokens": input_tokens,
        "output_tokens": tokens,
        "ttft_s": ttft,
        "total_s": total,
    }


def _error(total: float = 0.1, error_type: str = "TimeoutError: boom") -> dict:
    return {
        "status": "error",
        "error_type": error_type,
        "finish_reason": None,
        "input_tokens": None,
        "output_tokens": 0,
        "ttft_s": None,
        "total_s": total,
    }


def _empty(total: float = 0.5, finish_reason: str = "length") -> dict:
    return {
        "status": "empty",
        "error_type": None,
        "finish_reason": finish_reason,
        "input_tokens": 20,
        "output_tokens": 0,
        "ttft_s": None,
        "total_s": total,
    }


def test_summarize_single_ok_result_is_insufficient_samples():
    """n_ok=1 < _MIN_SAMPLES_FOR_PERCENTILES (4) -- basic counters are still
    reported, but no percentile is computed from one data point."""
    s = _summarize([_ok(0.1, 1.0, 50)], wall_time_s=1.0)
    assert s["n_total"] == 1
    assert s["n_ok"] == 1
    assert s["error_rate"] == 0.0
    assert s["empty_rate"] == 0.0
    assert s["total_output_tokens"] == 50
    assert s["wall_time_s"] == 1.0
    assert s["insufficient_samples"] is True
    assert s["aggregate_tok_s"] is None
    assert "ttft_p50" not in s


def test_summarize_four_ok_results_computes_percentiles():
    """n_ok=4 meets the threshold -- percentiles/aggregate are real numbers,
    not nulled."""
    results = [_ok(0.1, 1.0, 50), _ok(0.1, 1.0, 50), _ok(0.1, 1.0, 50), _ok(0.1, 1.0, 50)]
    s = _summarize(results, wall_time_s=1.0)
    assert s["insufficient_samples"] is False
    assert s["ttft_p50"] == 0.1
    assert s["latency_p50"] == 1.0
    assert s["aggregate_tok_s"] == pytest.approx(200.0)  # 4*50 tokens / 1.0s


def test_summarize_wall_time_is_passed_through_not_derived():
    """wall_time_s must be the caller's actually-measured batch duration, not
    something _summarize infers from individual request timings — see the
    2026-09-30 concurrency=1 sequential-wall-time bug this replaced."""
    s = _summarize([_ok(0.1, 1.0, 10), _error(total=3.0), _ok(0.15, 2.0, 10)], wall_time_s=5.5)
    assert s["wall_time_s"] == 5.5  # not max(total_s)=3.0, not sum=6.15 -- exactly what was passed


def test_summarize_sequential_batch_wall_time_can_exceed_any_single_request():
    """The concurrency=1 case runs every query sequentially: real wall time is
    close to the SUM of request durations, which can be far more than any
    single request's own total_s. _summarize must not silently cap it at
    max(total_s) the way the old (buggy) derivation did."""
    requests = [_ok(0.1, 1.0, 10) for _ in range(8)]
    real_wall_time = 8.0  # ~sum of 8 sequential 1.0s requests
    s = _summarize(requests, wall_time_s=real_wall_time)
    assert s["wall_time_s"] == 8.0
    assert s["wall_time_s"] > max(r["total_s"] for r in requests)


def test_summarize_error_and_empty_excluded_from_percentiles():
    ok_results = [_ok(0.1, 1.0, 50)] * 4
    s = _summarize(ok_results + [_error(), _empty()], wall_time_s=1.0)
    assert s["n_total"] == 6
    assert s["n_ok"] == 4
    assert s["ttft_p50"] == 0.1  # only the ok requests contribute
    assert s["latency_p50"] == 1.0


def test_summarize_error_rate_and_empty_rate():
    s = _summarize([_ok(0.1, 1.0, 50), _error(), _empty(), _empty()], wall_time_s=1.0)
    assert s["error_rate"] == pytest.approx(0.25)
    assert s["empty_rate"] == pytest.approx(0.50)


def test_summarize_all_failed_omits_percentile_keys():
    """No successful request means no percentile can be computed — the keys
    must be absent, not defaulted to 0.0 (which would read as a real,
    impossibly fast measurement)."""
    s = _summarize([_error(), _empty()], wall_time_s=0.5)
    assert s["n_ok"] == 0
    assert "ttft_p50" not in s
    assert "latency_p50" not in s
    assert "decode_tok_s_p50" not in s
    assert s["error_rate"] == 0.5
    assert s["empty_rate"] == 0.5


def test_summarize_empty_results_list_does_not_raise():
    s = _summarize([], wall_time_s=0.0)
    assert s["n_total"] == 0
    assert s["n_ok"] == 0
    assert s["error_rate"] == 0.0
    assert s["empty_rate"] == 0.0
    assert s["wall_time_s"] == 0.0
    assert "ttft_p50" not in s


def test_summarize_aggregate_tok_s_uses_wall_time_not_sum_of_request_times():
    """Throughput under load is total work over wall-clock time, not the sum
    of each request's own latency (which double-counts concurrent overlap)."""
    results = [_ok(0.1, 2.0, 100), _ok(0.1, 2.0, 100), _ok(0.1, 2.0, 100), _ok(0.1, 2.0, 100)]
    s = _summarize(results, wall_time_s=2.0)
    assert s["aggregate_tok_s"] == pytest.approx(200.0)  # 400 tokens / 2.0s


def test_summarize_decode_tok_s_excludes_non_positive_decode_window():
    """A single-chunk response can have total_s == ttft_s (zero decode
    window) — must be excluded, not divide-by-zero or divide-by-negative."""
    results = [_ok(1.0, 1.0, 50), _ok(1.0, 1.0, 50), _ok(1.0, 1.0, 50), _ok(0.1, 1.0, 90)]
    s = _summarize(results, wall_time_s=1.0)
    # Only the fourth request has a positive (total_s - ttft_s) = 0.9s window;
    # the other three have total_s == ttft_s (zero window), excluded.
    assert s["decode_tok_s_p50"] == pytest.approx(90 / 0.9)


def test_summarize_legacy_field_present_and_labelled():
    s = _summarize([_ok(0.1, 2.0, 100)], wall_time_s=2.0)
    assert s["legacy_avg_tokens_per_sec"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# insufficient_samples
# ---------------------------------------------------------------------------


def test_insufficient_samples_true_below_threshold():
    for n in (0, 1, 2, 3):
        s = _summarize([_ok(0.1, 1.0, 50)] * n, wall_time_s=1.0)
        assert s["insufficient_samples"] is True, f"n_ok={n} should be insufficient"


def test_insufficient_samples_false_at_and_above_threshold():
    for n in (4, 5, 10):
        s = _summarize([_ok(0.1, 1.0, 50)] * n, wall_time_s=1.0)
        assert s["insufficient_samples"] is False, f"n_ok={n} should be sufficient"


def test_insufficient_samples_nulls_percentiles_decode_and_agg_not_omits():
    """Spec: null, not omitted -- a consumer checking summary['aggregate_tok_s']
    gets an explicit None, not a KeyError."""
    s = _summarize([_ok(0.1, 1.0, 50)] * 3, wall_time_s=1.0)
    assert s["aggregate_tok_s"] is None
    assert "ttft_p50" not in s  # percentiles still omitted (never computed)
    assert "decode_tok_s_p50" not in s


def test_insufficient_samples_mixed_with_errors_counts_only_ok():
    """3 ok + 5 errors = n_ok=3, still insufficient, even though n_total=8."""
    s = _summarize([_ok(0.1, 1.0, 50)] * 3 + [_error()] * 5, wall_time_s=1.0)
    assert s["n_total"] == 8
    assert s["n_ok"] == 3
    assert s["insufficient_samples"] is True


# ---------------------------------------------------------------------------
# _cost_for_run
# ---------------------------------------------------------------------------


def test_cost_for_hosted_provider_scales_with_tokens():
    cost = _cost_for_run("groq", total_output_tokens=1_000_000, wall_time_s=100.0)
    assert cost == pytest.approx(0.20)


def test_cost_for_hosted_provider_ignores_wall_time():
    """Hosted cost is token-metered, not time-metered — wall time must not leak in."""
    fast = _cost_for_run("openai", total_output_tokens=500_000, wall_time_s=1.0)
    slow = _cost_for_run("openai", total_output_tokens=500_000, wall_time_s=1000.0)
    assert fast == slow == pytest.approx(5.00)


def test_cost_for_local_scales_with_wall_time_not_tokens():
    """The rented GPU bills for time, whether or not it was generating."""
    cost = _cost_for_run(
        "local", total_output_tokens=0, wall_time_s=3600.0, local_gpu_cost_per_hr=0.50
    )
    assert cost == pytest.approx(0.50)


def test_cost_for_local_is_independent_of_token_count():
    idle = _cost_for_run(
        "local", total_output_tokens=0, wall_time_s=1800.0, local_gpu_cost_per_hr=0.50
    )
    busy = _cost_for_run(
        "local", total_output_tokens=100_000, wall_time_s=1800.0, local_gpu_cost_per_hr=0.50
    )
    assert idle == busy == pytest.approx(0.25)


def test_cost_for_local_without_gpu_cost_is_nan_not_zero():
    """A silent 0.0 would look like a real (free) measurement."""
    assert math.isnan(_cost_for_run("local", total_output_tokens=100, wall_time_s=1.0))


def test_cost_for_unknown_provider_is_nan_not_zero():
    assert math.isnan(_cost_for_run("anthropic", total_output_tokens=100, wall_time_s=1.0))


# ---------------------------------------------------------------------------
# _local_cost_per_1m_output_tokens
# ---------------------------------------------------------------------------


def test_local_cost_per_1m_matches_the_spec_formula():
    # gpu $/hr / (aggregate_tok_s * 3600 / 1e6)
    result = _local_cost_per_1m_output_tokens(aggregate_tok_s=100.0, local_gpu_cost_per_hr=1.0)
    assert result == pytest.approx(1.0 / (100.0 * 3600 / 1_000_000))


def test_local_cost_per_1m_is_none_when_nothing_generated():
    """Zero throughput has no real $/token rate — None, not 0.0 or inf."""
    assert _local_cost_per_1m_output_tokens(aggregate_tok_s=0.0, local_gpu_cost_per_hr=0.50) is None


def test_local_cost_per_1m_higher_throughput_is_cheaper_per_token():
    slow = _local_cost_per_1m_output_tokens(aggregate_tok_s=10.0, local_gpu_cost_per_hr=1.0)
    fast = _local_cost_per_1m_output_tokens(aggregate_tok_s=100.0, local_gpu_cost_per_hr=1.0)
    assert fast < slow


# ---------------------------------------------------------------------------
# _fmt_row
# ---------------------------------------------------------------------------


def test_fmt_row_contains_concurrency_and_cost():
    summary = _summarize([_ok(0.1, 1.0, 50)], wall_time_s=1.0)
    line = _fmt_row(16, summary, cost=0.0042, local_cost_per_1m=None)
    assert "16" in line
    assert "0.0042" in line


def test_fmt_row_shows_na_when_all_requests_failed():
    summary = _summarize([_error(), _empty()], wall_time_s=0.5)
    line = _fmt_row(4, summary, cost=0.0, local_cost_per_1m=None)
    assert "n/a" in line
    assert "err= 50%" in line
    assert "empty= 50%" in line


def test_fmt_row_shows_local_per_token_cost_when_given():
    summary = _summarize([_ok(0.1, 1.0, 50)], wall_time_s=1.0)
    line = _fmt_row(1, summary, cost=0.001, local_cost_per_1m=0.25)
    assert "0.25" in line


# ---------------------------------------------------------------------------
# _load_prompts
# ---------------------------------------------------------------------------


def _write_prompts_file(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "prompts.jsonl"
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def test_load_prompts_returns_each_rows_messages(tmp_path):
    path = _write_prompts_file(
        tmp_path,
        [
            {"id": "a", "messages": [{"role": "user", "content": "q1"}]},
            {"id": "b", "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "q2"}]},
        ],
    )
    prompts = _load_prompts(path)
    assert prompts == [
        [{"role": "user", "content": "q1"}],
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "q2"}],
    ]


def test_load_prompts_skips_blank_lines(tmp_path):
    path = tmp_path / "prompts.jsonl"
    path.write_text(
        json.dumps({"id": "a", "messages": [{"role": "user", "content": "q"}]}) + "\n\n\n"
    )
    assert _load_prompts(path) == [[{"role": "user", "content": "q"}]]


def test_load_prompts_empty_file_raises():
    """A silently-empty workload would run zero requests and report nothing
    wrong — better to fail loudly at load time."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl") as f:
        f.flush()
        with pytest.raises(ValueError):
            _load_prompts(Path(f.name))


# ---------------------------------------------------------------------------
# _bust_prompt
# ---------------------------------------------------------------------------


def test_bust_prompt_makes_two_calls_on_the_same_input_different():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    a = _bust_prompt(messages)
    b = _bust_prompt(messages)
    assert a[0]["content"] != b[0]["content"]


def test_bust_prompt_prepends_unique_line_to_first_message():
    messages = [{"role": "system", "content": "original sys content"}, {"role": "user", "content": "hi"}]
    busted = _bust_prompt(messages)
    assert busted[0]["content"].startswith("request_id: ")
    assert busted[0]["content"].endswith("original sys content")


def test_bust_prompt_only_touches_the_first_message():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "unchanged"}]
    busted = _bust_prompt(messages)
    assert busted[1]["content"] == "unchanged"


def test_bust_prompt_applies_to_lone_user_message_when_no_system_message():
    """The bare eval/cases.py path has no system message -- the unique line
    goes at the start of the only (user) message instead."""
    messages = [{"role": "user", "content": "bare query"}]
    busted = _bust_prompt(messages)
    assert busted[0]["role"] == "user"
    assert busted[0]["content"].startswith("request_id: ")
    assert busted[0]["content"].endswith("bare query")


def test_bust_prompt_does_not_mutate_the_input_list():
    """The same `prompts` list is reused across every concurrency level and
    cycled within each one -- busting must not leave a stale unique line
    burned into the shared list."""
    messages = [{"role": "user", "content": "hi"}]
    original_content = messages[0]["content"]
    _bust_prompt(messages)
    assert messages[0]["content"] == original_content


def test_bust_prompt_unique_lines_have_no_collisions_across_many_calls():
    messages = [{"role": "user", "content": "hi"}]
    lines = {_bust_prompt(messages)[0]["content"] for _ in range(200)}
    assert len(lines) == 200


# ---------------------------------------------------------------------------
# _parse_prometheus_metrics / _summarize_vllm_metrics
# ---------------------------------------------------------------------------


_SAMPLE_METRICS_TEXT = """\
# HELP vllm:num_requests_running Number of requests currently running.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running 3.0
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting 1.0
# TYPE vllm:gpu_cache_usage_perc gauge
vllm:gpu_cache_usage_perc 0.42
# TYPE vllm:prefix_cache_queries_total counter
vllm:prefix_cache_queries_total 1000.0
# TYPE vllm:prefix_cache_hits_total counter
vllm:prefix_cache_hits_total 50.0
"""


def test_parse_prometheus_metrics_reads_known_fields():
    values = _parse_prometheus_metrics(_SAMPLE_METRICS_TEXT)
    assert values["vllm:num_requests_running"] == 3.0
    assert values["vllm:gpu_cache_usage_perc"] == 0.42
    assert values["vllm:prefix_cache_queries_total"] == 1000.0


def test_parse_prometheus_metrics_skips_comments_and_malformed_lines():
    text = "# just a comment\n\nvllm:num_requests_running 2.0\nnot_a_valid_line\n"
    values = _parse_prometheus_metrics(text)
    assert values == {"vllm:num_requests_running": 2.0}


def test_parse_prometheus_metrics_handles_labeled_metrics():
    text = 'vllm:something{model="x"} 5.0\n'
    values = _parse_prometheus_metrics(text)
    assert values["vllm:something"] == 5.0


def _sample(queries=None, hits=None, kv=None, waiting=None, running=None, preemptions=None):
    return {
        "prefix_cache_queries": queries,
        "prefix_cache_hits": hits,
        "gpu_cache_usage_perc": kv,
        "num_requests_waiting": waiting,
        "num_requests_running": running,
        "num_preemptions": preemptions,
    }


def test_summarize_vllm_metrics_empty_samples_returns_all_none():
    result = _summarize_vllm_metrics([])
    assert result == {
        "prefix_cache_hit_rate": None,
        "peak_gpu_cache_usage_pct": None,
        "peak_num_requests_waiting": None,
        "peak_num_requests_running": None,
        "preemptions_during_cell": None,
    }


def test_summarize_vllm_metrics_preemptions_is_a_delta_not_a_max():
    """num_preemptions is a monotonic counter -- the per-cell figure is how
    many happened during the cell (last-first), not the largest single
    sample, which for a monotonic counter would just be the last value."""
    samples = [_sample(preemptions=10), _sample(preemptions=13), _sample(preemptions=15)]
    result = _summarize_vllm_metrics(samples)
    assert result["preemptions_during_cell"] == 5  # 15 - 10, not max(10,13,15)=15


def test_summarize_vllm_metrics_preemptions_none_with_fewer_than_two_samples():
    result = _summarize_vllm_metrics([_sample(preemptions=10)])
    assert result["preemptions_during_cell"] is None


def test_summarize_vllm_metrics_zero_preemptions_is_zero_not_none():
    """A clean cell (no preemptions) must read as 0, not None -- None means
    'we don't know', 0 means 'we know and it was zero'."""
    samples = [_sample(preemptions=5), _sample(preemptions=5)]
    result = _summarize_vllm_metrics(samples)
    assert result["preemptions_during_cell"] == 0


def test_summarize_vllm_metrics_hit_rate_is_a_delta_not_an_average():
    """Counters are monotonic -- hit rate must be computed from
    (last - first), not by averaging each sample's own ratio."""
    samples = [
        _sample(queries=1000, hits=50),
        _sample(queries=1100, hits=60),  # +100 queries, +10 hits this poll
        _sample(queries=1200, hits=70),  # +100 queries, +10 hits this poll
    ]
    result = _summarize_vllm_metrics(samples)
    # delta hits / delta queries = (70-50) / (1200-1000) = 20/200 = 0.10
    assert result["prefix_cache_hit_rate"] == pytest.approx(0.10)


def test_summarize_vllm_metrics_zero_query_delta_is_none_not_zero_division():
    samples = [_sample(queries=1000, hits=50), _sample(queries=1000, hits=50)]
    result = _summarize_vllm_metrics(samples)
    assert result["prefix_cache_hit_rate"] is None


def test_summarize_vllm_metrics_peaks_are_max_across_samples():
    samples = [
        _sample(kv=0.1, waiting=0, running=1),
        _sample(kv=0.9, waiting=5, running=2),  # peak KV and waiting here
        _sample(kv=0.3, waiting=2, running=8),  # peak running here
    ]
    result = _summarize_vllm_metrics(samples)
    assert result["peak_gpu_cache_usage_pct"] == 0.9
    assert result["peak_num_requests_waiting"] == 5
    assert result["peak_num_requests_running"] == 8


def test_summarize_vllm_metrics_missing_fields_do_not_crash():
    """A scrape that only found some metric names (see the module's
    unverified-names caveat) must still summarize the fields it has."""
    samples = [_sample(kv=0.5), _sample(kv=0.6)]  # no queries/hits/waiting/running
    result = _summarize_vllm_metrics(samples)
    assert result["peak_gpu_cache_usage_pct"] == 0.6
    assert result["prefix_cache_hit_rate"] is None
    assert result["peak_num_requests_waiting"] is None


# ---------------------------------------------------------------------------
# _local_cost_per_request
# ---------------------------------------------------------------------------


def test_local_cost_per_request_matches_the_spec_formula():
    # gpu $/hr x wall time / n_ok
    result = _local_cost_per_request(wall_time_s=3600.0, local_gpu_cost_per_hr=2.0, n_ok=4)
    assert result == pytest.approx(2.0 * 1.0 / 4)  # 1 hour of $2/hr split 4 ways = $0.50


def test_local_cost_per_request_none_when_no_successes():
    """Zero successful requests has no real per-request cost -- None, not a
    ZeroDivisionError and not a fabricated 0."""
    assert _local_cost_per_request(wall_time_s=10.0, local_gpu_cost_per_hr=1.0, n_ok=0) is None


def test_local_cost_per_request_more_successes_means_cheaper_per_request():
    fewer = _local_cost_per_request(wall_time_s=10.0, local_gpu_cost_per_hr=1.0, n_ok=1)
    more = _local_cost_per_request(wall_time_s=10.0, local_gpu_cost_per_hr=1.0, n_ok=10)
    assert more < fewer


# ---------------------------------------------------------------------------
# _local_cost_per_1m_output_tokens with insufficient_samples (aggregate=None)
# ---------------------------------------------------------------------------


def test_local_cost_per_1m_none_when_aggregate_is_none():
    """insufficient_samples cells have aggregate_tok_s=None -- the per-1M-token
    cost must follow suit, not crash on a None comparison."""
    assert _local_cost_per_1m_output_tokens(None, local_gpu_cost_per_hr=1.0) is None
