import asyncio

import httpx
import pytest

from eval.serving_metrics import (ENGINE_METRIC_PREFIXES, ENGINE_METRIC_STATUS, counter_changes,
                                   parse_engine_metrics, prefix_cache_summary)

VLLM_TEXT = ('vllm:num_requests_waiting{model_name="m"} 3\n'
             '# TYPE vllm:prefix_cache_queries_total counter\n'
             'vllm:prefix_cache_queries_total{model_name="m"} %s\n'
             '# TYPE vllm:prefix_cache_hits_total counter\n'
             'vllm:prefix_cache_hits_total{model_name="m"} %s\n')
SGLANG_TEXT = 'sglang:num_running_reqs{model_name="m"} 2\nsglang:token_usage{model_name="m"} 0.5\n'


def changes(before, after):
    return counter_changes(parse_engine_metrics(before), parse_engine_metrics(after))


def test_default_parsing_is_unchanged_and_ignores_other_engines():
    series = parse_engine_metrics(VLLM_TEXT % (0, 0) + SGLANG_TEXT)
    assert {row["name"] for row in series} >= {"vllm:num_requests_waiting", "vllm:prefix_cache_queries_total"}
    assert not any(row["name"].startswith("sglang:") for row in series)


def test_sglang_prefix_selects_only_sglang_series():
    series = parse_engine_metrics(VLLM_TEXT % (0, 0) + SGLANG_TEXT, ENGINE_METRIC_PREFIXES["sglang"])
    assert {row["name"] for row in series} == {"sglang:num_running_reqs", "sglang:token_usage"}


def test_sglang_metric_names_are_marked_unverified_and_vllm_names_cite_their_basis():
    assert ENGINE_METRIC_STATUS["sglang"].startswith("UNVERIFIED")
    assert "v0.30.0" in ENGINE_METRIC_STATUS["vllm"]
    assert set(ENGINE_METRIC_PREFIXES) == set(ENGINE_METRIC_STATUS) == {"vllm", "sglang"}


def test_prefix_cache_summary_computes_a_token_hit_rate_from_counter_deltas():
    summary = prefix_cache_summary(changes(VLLM_TEXT % (100, 40), VLLM_TEXT % (1100, 540)))
    assert summary == {"status": "ok", "queries": 1000.0, "hits": 500.0, "hit_rate": 0.5,
                       "queries_metric": "vllm:prefix_cache_queries_total", "hits_metric": "vllm:prefix_cache_hits_total",
                       "unit": "tokens"}


def test_prefix_cache_summary_sums_label_series_and_accepts_the_older_names():
    two = ('vllm:gpu_prefix_cache_queries_total{engine="0"} %d\nvllm:gpu_prefix_cache_queries_total{engine="1"} %d\n'
           'vllm:gpu_prefix_cache_hits_total{engine="0"} %d\nvllm:gpu_prefix_cache_hits_total{engine="1"} %d\n')
    summary = prefix_cache_summary(changes(two % (0, 0, 0, 0), two % (100, 300, 20, 60)))
    assert summary["queries"] == 400 and summary["hits"] == 80 and summary["hit_rate"] == pytest.approx(0.2)
    assert summary["queries_metric"] == "vllm:gpu_prefix_cache_queries_total"


@pytest.mark.parametrize("rows,reason", [
    (None, "no counter changes"),
    ([], "no prefix-cache counters"),
])
def test_prefix_cache_summary_is_unavailable_without_data(rows, reason):
    summary = prefix_cache_summary(rows)
    assert summary["status"] == "unavailable" and reason in summary["reason"] and "hit_rate" not in summary


def test_prefix_cache_summary_is_unavailable_after_a_counter_reset_or_with_zero_queries():
    reset = prefix_cache_summary(changes(VLLM_TEXT % (500, 100), VLLM_TEXT % (50, 10)))
    assert reset["status"] == "unavailable" and "reset" in reset["reason"]
    idle = prefix_cache_summary(changes(VLLM_TEXT % (500, 100), VLLM_TEXT % (500, 100)))
    assert idle["status"] == "unavailable" and "no prefix-cache queries" in idle["reason"]


def test_prefix_cache_summary_refuses_engines_whose_metric_names_are_unverified():
    rows = changes(VLLM_TEXT % (0, 0), VLLM_TEXT % (10, 5))
    summary = prefix_cache_summary(rows, engine="sglang")
    assert summary["status"] == "unavailable" and "unverified" in summary["reason"]


@pytest.mark.asyncio
async def test_poll_engine_records_the_prefix_cache_summary_with_the_engine_prefix():
    from eval.serving_load import poll_engine
    bodies = iter([VLLM_TEXT % (0, 0), VLLM_TEXT % (200, 150), VLLM_TEXT % (400, 300)])
    calls = 0

    class Client:
        async def get(self, url, timeout):
            nonlocal calls
            calls += 1
            return httpx.Response(200, text=next(bodies), request=httpx.Request("GET", url))

    class Stop:
        def is_set(self):
            return calls >= 2

        async def wait(self):
            raise TimeoutError
    rows = []
    await poll_engine(Client(), "http://server/metrics", rows.append, "cell", Stop(), asyncio.Event())
    event = rows[-1]
    assert event["event"] == "engine_counter_changes"
    assert event["prefix_cache"]["hit_rate"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_poll_engine_with_sglang_keeps_only_sglang_series_and_marks_the_cache_summary_unavailable():
    from eval.serving_load import poll_engine
    calls = 0

    class Client:
        async def get(self, url, timeout):
            nonlocal calls
            calls += 1
            return httpx.Response(200, text='sglang:num_aborted_requests_total{m="a"} %d\n' % calls,
                                  request=httpx.Request("GET", url))

    class Stop:
        def is_set(self):
            return calls >= 2

        async def wait(self):
            raise TimeoutError
    rows = []
    await poll_engine(Client(), "http://server/metrics", rows.append, "cell", Stop(), asyncio.Event(), engine="sglang")
    assert rows[-1]["prefix_cache"]["status"] == "unavailable" and "unverified" in rows[-1]["prefix_cache"]["reason"]
    assert all(row["status"] == "ok" for row in rows if row["event"] == "engine_metrics")


# --- --engine option and manifest ------------------------------------------------------------------

def test_engine_option_defaults_to_vllm_and_rejects_unknown_engines():
    from eval.serving_load import parse_args
    base = ["--workloads", "w.json", "--out-dir", "o"]
    assert parse_args(base).engine == "vllm"
    assert parse_args([*base, "--engine", "sglang"]).engine == "sglang"
    with pytest.raises(SystemExit):
        parse_args([*base, "--engine", "tgi"])


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["vllm", "sglang"])
async def test_manifest_records_the_engine_family_and_the_verification_status(tmp_path, engine):
    import json
    from unittest.mock import patch

    from app.services import llm
    from eval.serving_load import main
    from tests.test_serving_load import workload_file
    path = workload_file(tmp_path)

    async def stream(messages, **kwargs):
        kwargs["usage_sink"].update(completion_tokens=2, prompt_tokens=5, finish_reason="stop")
        yield "hello"
    with patch.object(llm, "chat_stream", stream):
        await main(["--workloads", str(path), "--out-dir", str(tmp_path / "run"), "--provider", "groq",
                    "--requests", "2", "--concurrency", "1", "--repeats", "1", "--warmup", "0", "--engine", engine])
    manifest = json.loads((tmp_path / "run/manifest.json").read_text())
    assert manifest["engine_family"] == engine
    assert manifest["engine_metrics_status"] == ENGINE_METRIC_STATUS[engine]
    assert manifest["schema_version"] == 2                      # additive: still a v2 manifest
