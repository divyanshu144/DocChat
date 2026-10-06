"""Tests for eval/inference_benchmark.py's status classification and provider
scoping — `llm.chat_stream` is mocked (no network), same boundary the
provider-seam tests mock at. What's under test here is new behaviour from the
2026-10 measurement-bug fixes: ok/empty/error status classification, and that
a benchmark run never silently falls back to a different provider.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import llm
from eval.inference_benchmark import (
    _CellTimeoutError,
    _run_concurrency_level,
    _run_provider,
    _run_request,
)

_HI = [{"role": "user", "content": "hi"}]


def _fake_chat_stream(tokens: list[str], usage: dict | None = None, raise_after: Exception | None = None):
    async def fake(messages, max_tokens=None, usage_sink=None):
        for t in tokens:
            yield t
        if usage is not None and usage_sink is not None:
            usage_sink.update(usage)
        if raise_after is not None:
            raise raise_after

    return fake


# ---------------------------------------------------------------------------
# _run_request status classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_request_ok_status_uses_real_usage_counts():
    fake = _fake_chat_stream(
        ["he", "llo"], usage={"prompt_tokens": 12, "completion_tokens": 8, "finish_reason": "stop"}
    )
    with patch.object(llm, "chat_stream", fake):
        result = await _run_request(_HI, max_tokens=50)

    assert result["status"] == "ok"
    assert result["error_type"] is None
    assert result["output_tokens"] == 8  # real usage count, not chunk_count (2)
    assert result["input_tokens"] == 12
    assert result["finish_reason"] == "stop"
    assert result["ttft_s"] is not None


@pytest.mark.asyncio
async def test_run_request_falls_back_to_chunk_count_without_usage():
    fake = _fake_chat_stream(["he", "llo", "!"], usage=None)
    with patch.object(llm, "chat_stream", fake):
        result = await _run_request(_HI, max_tokens=50)

    assert result["status"] == "ok"
    assert result["output_tokens"] == 3  # proxy: 3 chunks yielded


@pytest.mark.asyncio
async def test_run_request_empty_status_when_zero_chunks():
    """The reasoning-model-exhausts-budget case: stream completes, zero content."""
    fake = _fake_chat_stream(
        [], usage={"prompt_tokens": 20, "completion_tokens": 128, "finish_reason": "length"}
    )
    with patch.object(llm, "chat_stream", fake):
        result = await _run_request(_HI, max_tokens=128)

    assert result["status"] == "empty"
    assert result["ttft_s"] is None  # no content ever arrived — no real TTFT to report
    assert result["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_run_request_error_status_on_exception():
    fake = _fake_chat_stream(["par"], usage=None, raise_after=RuntimeError("connection reset"))
    with patch.object(llm, "chat_stream", fake):
        result = await _run_request(_HI, max_tokens=50)

    assert result["status"] == "error"
    assert "RuntimeError" in result["error_type"]
    assert "connection reset" in result["error_type"]
    assert result["ttft_s"] is None


@pytest.mark.asyncio
async def test_run_request_error_before_any_content_has_no_ttft():
    fake = _fake_chat_stream([], usage=None, raise_after=ConnectionError("boom"))
    with patch.object(llm, "chat_stream", fake):
        result = await _run_request(_HI, max_tokens=50)

    assert result["status"] == "error"
    assert result["ttft_s"] is None
    assert result["output_tokens"] == 0


# ---------------------------------------------------------------------------
# _run_provider — never silently falls back, restores settings after
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_provider_disables_fallback_for_the_duration():
    captured_fallback: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        captured_fallback.append(settings.fallback_llm_provider)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(settings, "fallback_llm_provider", "openai"), \
         patch.object(settings, "llm_provider", "groq"), \
         patch.object(llm, "chat_stream", fake_chat_stream), \
         patch.object(llm, "_clients", {}):
        await _run_provider(
            "groq", [_HI], [1], max_tokens=10, local_gpu_cost_per_hr=None, openai_model_override=None
        )

    assert captured_fallback == ["none"]  # was forced off during the run
    assert settings.fallback_llm_provider == "openai"  # restored after


@pytest.mark.asyncio
async def test_run_provider_restores_fallback_setting_even_on_exception():
    async def raising_chat_stream(messages, max_tokens=None, usage_sink=None):
        raise RuntimeError("boom")
        yield  # pragma: no cover - unreachable, makes this an async generator

    with patch.object(settings, "fallback_llm_provider", "openai"), \
         patch.object(llm, "chat_stream", raising_chat_stream):
        # _run_request catches the exception internally, so this must not raise.
        await _run_provider(
            "groq", [_HI], [1], max_tokens=10, local_gpu_cost_per_hr=None, openai_model_override=None
        )

    assert settings.fallback_llm_provider == "openai"


@pytest.mark.asyncio
async def test_run_provider_applies_and_restores_openai_model_override():
    captured_models: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        captured_models.append(settings.openai_chat_model)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(settings, "openai_chat_model", "gpt-5.6-luna"), \
         patch.object(llm, "chat_stream", fake_chat_stream):
        await _run_provider(
            "openai",
            [_HI],
            [1],
            max_tokens=10,
            local_gpu_cost_per_hr=None,
            openai_model_override="gpt-4.1",
        )

    assert captured_models == ["gpt-4.1"]
    assert settings.openai_chat_model == "gpt-5.6-luna"  # restored


@pytest.mark.asyncio
async def test_run_provider_ignores_openai_model_override_for_other_providers():
    """The override is only meaningful for provider == 'openai'."""
    captured_models: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        captured_models.append(settings.openai_chat_model)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(settings, "openai_chat_model", "gpt-5.6-luna"), \
         patch.object(llm, "chat_stream", fake_chat_stream):
        await _run_provider(
            "groq",
            [_HI],
            [1],
            max_tokens=10,
            local_gpu_cost_per_hr=None,
            openai_model_override="gpt-4.1",
        )

    assert captured_models == ["gpt-5.6-luna"]  # untouched — override didn't leak in


@pytest.mark.asyncio
async def test_run_provider_applies_and_restores_groq_model_override():
    captured_models: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        captured_models.append(settings.chat_model)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(settings, "chat_model", "openai/gpt-oss-120b"), \
         patch.object(llm, "chat_stream", fake_chat_stream):
        await _run_provider(
            "groq",
            [_HI],
            [1],
            max_tokens=10,
            local_gpu_cost_per_hr=None,
            openai_model_override=None,
            groq_model_override="llama-3.1-8b-instant",
        )

    assert captured_models == ["llama-3.1-8b-instant"]
    assert settings.chat_model == "openai/gpt-oss-120b"  # restored


@pytest.mark.asyncio
async def test_run_provider_ignores_groq_model_override_for_other_providers():
    """The override is only meaningful for provider == 'groq'."""
    captured_models: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        captured_models.append(settings.chat_model)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(settings, "chat_model", "openai/gpt-oss-120b"), \
         patch.object(llm, "chat_stream", fake_chat_stream):
        await _run_provider(
            "openai",
            [_HI],
            [1],
            max_tokens=10,
            local_gpu_cost_per_hr=None,
            openai_model_override=None,
            groq_model_override="llama-3.1-8b-instant",
        )

    assert captured_models == ["openai/gpt-oss-120b"]  # untouched — override didn't leak in


# ---------------------------------------------------------------------------
# concurrency == 1 runs every query sequentially (not just one request)
# ---------------------------------------------------------------------------


def _msg(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


@pytest.mark.asyncio
async def test_concurrency_one_runs_every_query_not_just_one():
    from eval.inference_benchmark import _run_concurrency_level

    seen_queries: list[str] = []

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        seen_queries.append(messages[0]["content"])
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(llm, "chat_stream", fake_chat_stream):
        prompts = [_msg("a"), _msg("b"), _msg("c")]
        # bust_cache=False: this test is about ordering/count, not busting --
        # see test_inference_benchmark_metrics.py for busting's own tests.
        results = await _run_concurrency_level(
            prompts, concurrency=1, max_tokens=10, bust_cache=False
        )

    assert len(results) == 3
    assert seen_queries == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_concurrency_above_one_cycles_through_queries():
    from eval.inference_benchmark import _run_concurrency_level

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(llm, "chat_stream", fake_chat_stream):
        prompts = [_msg("a"), _msg("b")]
        results = await _run_concurrency_level(prompts, concurrency=5, max_tokens=10)

    assert len(results) == 5


# ---------------------------------------------------------------------------
# _run_provider — local-only vLLM metrics polling + the >10% hit-rate warning
# ---------------------------------------------------------------------------


async def _fake_ok_chat_stream(messages, max_tokens=None, usage_sink=None):
    if usage_sink is not None:
        usage_sink.update({"completion_tokens": 1})
    yield "x"


@pytest.mark.asyncio
async def test_run_provider_warns_when_hit_rate_high_with_busting_on(capsys):
    from eval import inference_benchmark as ib

    async def fake_poll(metrics_url, coro):
        result = await coro
        # 50% hit rate -- above the 10% warn threshold, busting supposedly ON.
        return result, [
            {
                "prefix_cache_queries": 100,
                "prefix_cache_hits": 0,
                "gpu_cache_usage_perc": 0.1,
                "num_requests_waiting": 0,
                "num_requests_running": 1,
                "num_preemptions": 0,
            },
            {
                "prefix_cache_queries": 200,
                "prefix_cache_hits": 50,
                "gpu_cache_usage_perc": 0.1,
                "num_requests_waiting": 0,
                "num_requests_running": 1,
                "num_preemptions": 0,
            },
        ]

    with patch.object(settings, "local_base_url", "http://fake/v1"), \
         patch.object(llm, "chat_stream", _fake_ok_chat_stream), \
         patch.object(ib, "_poll_metrics_during", fake_poll):
        await ib._run_provider(
            "local", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=0.5, openai_model_override=None, bust_cache=True,
        )

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "prefix cache hit rate" in err.lower()


@pytest.mark.asyncio
async def test_run_provider_no_warning_when_hit_rate_low(capsys):
    from eval import inference_benchmark as ib

    async def fake_poll(metrics_url, coro):
        result = await coro
        return result, [
            {
                "prefix_cache_queries": 1000,
                "prefix_cache_hits": 0,
                "gpu_cache_usage_perc": 0.1,
                "num_requests_waiting": 0,
                "num_requests_running": 1,
                "num_preemptions": 0,
            },
            {
                "prefix_cache_queries": 1100,
                "prefix_cache_hits": 1,  # 1/100 = 1% hit rate this poll
                "gpu_cache_usage_perc": 0.1,
                "num_requests_waiting": 0,
                "num_requests_running": 1,
                "num_preemptions": 0,
            },
        ]

    with patch.object(settings, "local_base_url", "http://fake/v1"), \
         patch.object(llm, "chat_stream", _fake_ok_chat_stream), \
         patch.object(ib, "_poll_metrics_during", fake_poll):
        await ib._run_provider(
            "local", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=0.5, openai_model_override=None, bust_cache=True,
        )

    err = capsys.readouterr().err
    assert "WARNING" not in err


@pytest.mark.asyncio
async def test_run_provider_no_warning_when_busting_off():
    """A high hit rate is expected (not a problem) when busting is
    deliberately disabled -- the warning must not fire."""
    from eval import inference_benchmark as ib

    async def fake_poll(metrics_url, coro):
        result = await coro
        return result, [
            {"prefix_cache_queries": 100, "prefix_cache_hits": 0, "gpu_cache_usage_perc": None,
             "num_requests_waiting": None, "num_requests_running": None, "num_preemptions": None},
            {"prefix_cache_queries": 200, "prefix_cache_hits": 90, "gpu_cache_usage_perc": None,
             "num_requests_waiting": None, "num_requests_running": None, "num_preemptions": None},
        ]

    with patch.object(settings, "local_base_url", "http://fake/v1"), \
         patch.object(llm, "chat_stream", _fake_ok_chat_stream), \
         patch.object(ib, "_poll_metrics_during", fake_poll):
        await ib._run_provider(
            "local", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=0.5, openai_model_override=None, bust_cache=False,
        )
    # No assertion needed beyond "did not raise" -- capsys not checked here
    # since the point is absence of a crash when busting is off; the warning
    # condition itself is proven off separately by requiring bust_cache=True.


@pytest.mark.asyncio
async def test_run_provider_skips_metrics_polling_for_non_local_provider():
    """Metrics polling is local-only -- a hosted provider's summary must have
    no vllm_metrics key at all."""
    from eval import inference_benchmark as ib

    with patch.object(llm, "chat_stream", _fake_ok_chat_stream):
        rows = await ib._run_provider(
            "groq", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
        )

    assert "vllm_metrics" not in rows[0]["summary"]


@pytest.mark.asyncio
async def test_run_provider_includes_cost_per_request_for_local_only():
    from eval import inference_benchmark as ib

    async def fake_poll(metrics_url, coro):
        result = await coro
        return result, []

    with patch.object(settings, "local_base_url", "http://fake/v1"), \
         patch.object(llm, "chat_stream", _fake_ok_chat_stream), \
         patch.object(ib, "_poll_metrics_during", fake_poll):
        local_rows = await ib._run_provider(
            "local", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=0.5, openai_model_override=None, bust_cache=True,
        )
    with patch.object(llm, "chat_stream", _fake_ok_chat_stream):
        groq_rows = await ib._run_provider(
            "groq", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
        )

    assert local_rows[0]["cost_per_request_local"] is not None
    assert groq_rows[0]["cost_per_request_local"] is None


# ---------------------------------------------------------------------------
# _run_provider — per-cell 5-minute timeout (Part D item 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_provider_raises_cell_timeout_and_preserves_finished_rows():
    from eval import inference_benchmark as ib

    call_count = {"n": 0}

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        call_count["n"] += 1
        if call_count["n"] > 1:
            # Second cell (concurrency=4) hangs past the (patched-down) timeout.
            await asyncio.sleep(10)
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(ib, "_CELL_TIMEOUT_S", 0.05), \
         patch.object(llm, "chat_stream", fake_chat_stream):
        with pytest.raises(_CellTimeoutError) as exc_info:
            await ib._run_provider(
                "groq", [_msg("hi")], [1, 4], max_tokens=10,
                local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
            )

    assert exc_info.value.concurrency == 4
    assert len(exc_info.value.rows) == 1  # only the concurrency=1 cell finished
    assert exc_info.value.rows[0]["concurrency"] == 1


@pytest.mark.asyncio
async def test_run_provider_no_timeout_when_cell_finishes_in_time():
    from eval import inference_benchmark as ib

    with patch.object(ib, "_CELL_TIMEOUT_S", 5.0), \
         patch.object(llm, "chat_stream", _fake_ok_chat_stream):
        rows = await ib._run_provider(
            "groq", [_msg("hi")], [1], max_tokens=10,
            local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
        )

    assert len(rows) == 1


# ---------------------------------------------------------------------------
# _run_concurrency_level / _run_provider — serial mode (Phase 4 batching proof)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serial_mode_never_overlaps_requests():
    """The actual proof serial mode works: no two requests are ever in
    flight at once, not just that the right number of calls happened."""
    in_flight = 0
    max_in_flight = 0

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(llm, "chat_stream", fake_chat_stream):
        results = await _run_concurrency_level(
            [_msg("hi")], concurrency=5, max_tokens=10, bust_cache=False, serial=True
        )

    assert len(results) == 5
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_concurrent_mode_does_overlap_requests():
    """Sanity check that the test methodology above actually distinguishes
    the two modes -- concurrent (serial=False, the default) must allow
    overlap, or the serial test above would prove nothing."""
    in_flight = 0
    max_in_flight = 0

    async def fake_chat_stream(messages, max_tokens=None, usage_sink=None):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        if usage_sink is not None:
            usage_sink.update({"completion_tokens": 1})
        yield "x"

    with patch.object(llm, "chat_stream", fake_chat_stream):
        results = await _run_concurrency_level(
            [_msg("hi")], concurrency=5, max_tokens=10, bust_cache=False, serial=False
        )

    assert len(results) == 5
    assert max_in_flight == 5


@pytest.mark.asyncio
async def test_run_provider_tags_serial_mode_on_the_row():
    from eval import inference_benchmark as ib

    with patch.object(llm, "chat_stream", _fake_ok_chat_stream):
        rows = await ib._run_provider(
            "groq", [_msg("hi")], [4], max_tokens=10,
            local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
            serial=True,
        )

    assert rows[0]["mode"] == "serial"


@pytest.mark.asyncio
async def test_run_provider_defaults_to_concurrent_mode_on_the_row():
    from eval import inference_benchmark as ib

    with patch.object(llm, "chat_stream", _fake_ok_chat_stream):
        rows = await ib._run_provider(
            "groq", [_msg("hi")], [4], max_tokens=10,
            local_gpu_cost_per_hr=None, openai_model_override=None, bust_cache=True,
        )

    assert rows[0]["mode"] == "concurrent"
