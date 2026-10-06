import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from eval.serving_load import (run_cell, summarize, replay_request, api_request, SSEProtocolError,
                              ArtifactWriter, parse_args, main)
from eval.serving_metrics import parse_engine_metrics, counter_changes
from eval.workloads import WorkloadCase, Workloads, load_workloads
from app.core.config import settings
from app.services import llm


def case(category="document_qa", identifier="qa"):
    return WorkloadCase(id=identifier, category=category, query="question", messages=[
        {"role": "system", "content": "context"}, {"role": "user", "content": "question"}])


def workload_file(tmp_path):
    path = tmp_path / "workloads.json"
    path.write_text(Workloads(corpus_sha256="a" * 64, cases=[case()]).model_dump_json())
    return path


@pytest.mark.asyncio
async def test_closed_loop_replenishes_workers_until_request_limit():
    active = peak = calls = 0
    async def request(case, identifier):
        nonlocal active, peak, calls
        active += 1
        calls += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return {"status": "ok", "output_tokens": 2}
    rows = []
    report = await run_cell([case()], request, concurrency=4, duration_s=2, max_requests=20,
                            timeout_s=1, write=rows.append, cell_id="test")
    assert calls == 20 and peak == 4
    requests = [row for row in rows if row["event"] == "request"]
    assert len({row["request_id"] for row in requests}) == 20
    assert report["summary"]["completed_ok"] == 20
    assert report["summary"]["latency_p95_s"] is None
    assert report["summary"]["insufficient_samples"]


@pytest.mark.asyncio
async def test_arrival_schedule_rejects_excess_instead_of_hidden_queue():
    active = peak = 0
    async def request(case, identifier):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.08)
        active -= 1
        return {"status": "ok"}
    rows = []
    report = await run_cell([case()], request, concurrency=1, duration_s=.1, max_requests=5,
                            timeout_s=1, arrival_rate=100, write=rows.append, cell_id="rate")
    assert report["summary"]["offered"] == 5
    assert report["summary"]["load_generator_rejected"] >= 3
    assert peak == 1
    assert any(r.get("error_type") == "load_generator_capacity" for r in rows)


@pytest.mark.asyncio
async def test_cancellation_saves_partial_records_and_cleans_workers():
    entered = asyncio.Event()
    async def request(case, identifier):
        entered.set()
        await asyncio.Event().wait()
    rows = []
    task = asyncio.create_task(run_cell([case()], request, concurrency=2, duration_s=2,
        max_requests=10, timeout_s=30, write=rows.append, cell_id="cancel"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rows[-1]["event"] == "cell_summary"
    assert rows[-1]["interrupted"]
    assert rows[-1]["summary"]["cancelled"] == 2


@pytest.mark.asyncio
async def test_timeout_and_errors_preserved_without_raw_error_secrets():
    count = 0
    async def request(case, identifier):
        nonlocal count
        count += 1
        if count == 1:
            await asyncio.sleep(1)
        raise ValueError("credential-secret")
    rows = []
    report = await run_cell([case()], request, concurrency=1, duration_s=1, max_requests=2,
                            timeout_s=.01, write=rows.append, cell_id="errors")
    assert report["summary"]["timeouts"] == 1
    assert report["summary"]["errors"] == 1
    assert "credential-secret" not in json.dumps(rows)


def test_summary_uses_wall_time_unknown_usage_and_explicit_slo():
    rows = [{"status": "ok", "total_s": 2, "output_tokens": 10},
            {"status": "ok", "total_s": 4, "output_tokens": None},
            {"status": "error", "total_s": 1}]
    report = summarize(rows, 10, min_samples=2, latency_slo=3)
    assert report["successful_requests_per_second"] == .2
    assert report["output_tokens_per_second"] is None
    assert report["latency_p95_s"] == 4
    assert report["slo_goodput_requests_per_second"] == .1
    assert report["error_rate"] == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_replay_does_not_guess_tokens_or_mutate_prompt():
    captured = []
    async def stream(messages, **kwargs):
        captured.extend(messages)
        yield "many words in one delta"
    original = case()
    with patch.object(llm, "chat_stream", stream):
        row = await replay_request(original, "id", "bust")
    assert row["output_tokens"] is None
    assert row["content_chunks"] == 1
    assert original.messages[0].content == "context"
    assert captured[0]["content"].startswith("request_id: id")


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [
    ("event: status\ndata: thinking\n\nevent: token\ndata: hello\ndata: world\n\nevent: done\ndata: [DONE]\n\n", "ok"),
    ("event: done\ndata: [DONE]\n\n", "empty"),
    ("event: error\ndata: secret\n\n", "error"),
    ("event: token\ndata: partial\n\n", "error"),
])
async def test_api_sse_semantics_and_source_filters(body, status):
    def handler(request):
        assert request.headers["authorization"] == "Bearer token"
        assert request.headers["x-request-id"] == "request-id"
        assert json.loads(request.content) == {"query": "question", "source_ids": ["source-1"]}
        assert request.url.path == "/api/v1/chat"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    async with httpx.AsyncClient(base_url="http://app/api/v1/", headers={"Authorization": "Bearer token"},
                                 transport=httpx.MockTransport(handler)) as client:
        workload = case().model_copy(update={"source_ids": ["source-1"]})
        if status == "error":
            with pytest.raises(SSEProtocolError):
                await api_request(client, workload, "request-id")
        else:
            row = await api_request(client, workload, "request-id")
            assert row["status"] == status
            assert row["ttft_s"] is None and row["output_tokens"] is None
            assert (row["first_answer_s"] is not None) == (status == "ok")


def test_manifest_validation_fingerprint_and_capture_requirement(tmp_path):
    path = workload_file(tmp_path)
    first = load_workloads(path, "replay")
    assert first.fingerprint() == load_workloads(path, "replay").fingerprint()
    assert first.fingerprint() != first.model_copy(update={"corpus_sha256": "b" * 64}).fingerprint()
    with pytest.raises(ValueError):
        Workloads(corpus_sha256="a" * 64, cases=[case(), case()])
    path.write_text(Workloads(corpus_sha256="a" * 64,
        cases=[case().model_copy(update={"messages": []})]).model_dump_json())
    with pytest.raises(ValueError, match="captured messages"):
        load_workloads(path, "replay")
    assert load_workloads(path, "api")


def test_artifacts_refuse_overwrite_and_flush_incrementally(tmp_path):
    directory = tmp_path / "run"
    writer = ArtifactWriter(directory, {"run_id": "id"})
    writer.write({"event": "request", "status": "error"})
    assert json.loads((directory / "events.jsonl").read_text())["schema_version"] == 2
    writer.close()
    with pytest.raises(FileExistsError):
        ArtifactWriter(directory, {"run_id": "other"})


def test_metrics_preserve_engine_labels_buckets_and_counter_reset():
    text = 'vllm:generation_tokens_total{engine="0"} 10\nvllm:generation_tokens_total{engine="1"} 20\n'
    text += 'vllm:latency_bucket{le="1",engine="0"} 4\nvllm:latency_bucket{le="+Inf",engine="0"} 8\n'
    samples = parse_engine_metrics(text)
    assert len(samples) == 4
    after = parse_engine_metrics(text.replace(' 10\n', ' 15\n').replace(' 20\n', ' 2\n'))
    deltas = counter_changes(samples, after)
    counters = [row for row in deltas if row["name"].endswith("_total")]
    assert counters[0]["delta"] == 5
    assert counters[1]["delta"] is None and counters[1]["reset"]


@pytest.mark.asyncio
async def test_cli_validate_only_is_offline_and_creates_nothing(tmp_path):
    path = workload_file(tmp_path)
    with patch.object(llm, "chat_stream") as stream:
        await main(["--workloads", str(path), "--out-dir", str(tmp_path / "run"), "--validate-only"])
    stream.assert_not_called()
    assert not (tmp_path / "run").exists()


@pytest.mark.asyncio
async def test_cli_run_persists_repeats_and_restores_fallback(tmp_path):
    path = workload_file(tmp_path)
    original = (settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model)
    async def stream(messages, **kwargs):
        assert settings.fallback_llm_provider == "none"
        assert settings.groq_fallback_chat_model == ""
        kwargs["usage_sink"].update(completion_tokens=2, prompt_tokens=5, finish_reason="stop")
        yield "hello"
    with patch.object(llm, "chat_stream", stream):
        await main(["--workloads", str(path), "--out-dir", str(tmp_path / "run"), "--provider", "groq",
                    "--requests", "3", "--concurrency", "1,2", "--repeats", "2", "--warmup", "1"])
    assert original == (settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model)
    rows = [json.loads(line) for line in (tmp_path / "run/events.jsonl").read_text().splitlines()]
    assert len([r for r in rows if r["event"] == "cell_summary" and r["phase"] == "measurement"]) == 4
    assert rows[-1]["outcome"] == "complete"
    assert len({r["run_id"] for r in rows}) == 1


@pytest.mark.parametrize("arguments", [["--concurrency", "1,0"], ["--arrival-rates", "nan"],
                                         ["--duration", "-1"], ["--warmup", "-1"]])
def test_invalid_load_parameters_fail_before_io(arguments):
    with pytest.raises(SystemExit):
        parse_args(["--workloads", "missing.json", "--out-dir", "unused", *arguments])


@pytest.mark.asyncio
async def test_duration_stops_new_work_but_drains_inflight():
    rows = []
    async def request(case, identifier):
        await asyncio.sleep(.04)
        return {"status": "ok"}
    report = await run_cell([case()], request, concurrency=1, duration_s=.01, max_requests=20,
                            timeout_s=1, write=rows.append, cell_id="duration")
    assert report["stop_reason"] == "duration"
    assert report["summary"]["offered"] == 1
    assert report["summary"]["wall_s"] >= .04


@pytest.mark.asyncio
async def test_capture_preserves_categories_filters_and_refuses_missing_context(tmp_path, monkeypatch):
    from eval import capture_bench_prompts as capture
    workload = case().model_copy(update={"source_ids": ["specific-source"]})
    path = tmp_path / "input.json"
    path.write_text(Workloads(corpus_sha256="a" * 64, cases=[workload]).model_dump_json())
    monkeypatch.setattr(capture, "_load_tokenizer", lambda: object())
    async def fake_capture(c, tokenizer, source_ids):
        assert source_ids == ["specific-source"]
        return {"messages": [{"role": "user", "content": "captured prompt"}]}
    monkeypatch.setattr(capture, "_capture_one", fake_capture)
    await capture.capture_workloads(path, tmp_path / "captured.json")
    result = load_workloads(tmp_path / "captured.json", "replay")
    assert result.cases[0].category == "document_qa"
    assert result.cases[0].messages[0].content == "captured prompt"
    async def failed_capture(*args, **kwargs):
        raise ValueError("No synthesis prompt")
    monkeypatch.setattr(capture, "_capture_one", failed_capture)
    with pytest.raises(ValueError):
        await capture.capture_workloads(path, tmp_path / "failed.json")
    assert not (tmp_path / "failed.json").exists()


@pytest.mark.asyncio
async def test_cli_saves_failed_run_and_restores_configuration(tmp_path, monkeypatch):
    path = workload_file(tmp_path)
    original = (settings.llm_provider, settings.fallback_llm_provider)
    monkeypatch.setattr(settings, "local_base_url", "")
    with pytest.raises(ValueError):
        await main(["--workloads", str(path), "--out-dir", str(tmp_path / "failed")])
    rows = [json.loads(line) for line in (tmp_path / "failed/events.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "run_end" and rows[-1]["outcome"] == "error"
    assert original == (settings.llm_provider, settings.fallback_llm_provider)


@pytest.mark.asyncio
async def test_engine_sampling_tracks_resets_between_boundary_samples():
    from eval.serving_load import poll_engine
    values = iter([10, 0, 20, 30])
    calls = 0
    class Client:
        async def get(self, url, timeout):
            nonlocal calls
            calls += 1
            return httpx.Response(200, text=f'vllm:generation_tokens_total{{engine="0"}} {next(values)}\n',
                                  request=httpx.Request("GET", url))
    class Stop:
        def is_set(self):
            return calls >= 3
        async def wait(self):
            raise TimeoutError
    rows = []
    ready = asyncio.Event()
    await poll_engine(Client(), "http://server/metrics", rows.append, "cell", Stop(), ready)
    assert ready.is_set()
    assert calls == 4
    assert rows[-1]["changes"][0]["reset"]
    assert rows[-1]["changes"][0]["delta"] is None


@pytest.mark.asyncio
async def test_cell_summary_records_a_wall_clock_window_that_brackets_the_requests():
    from datetime import datetime, timezone

    async def request(case, identifier):
        await asyncio.sleep(.02)
        return {"status": "ok"}
    before = datetime.now(timezone.utc)
    rows = []
    report = await run_cell([case()], request, concurrency=1, duration_s=.1, max_requests=3,
                            timeout_s=1, write=rows.append, cell_id="window")
    after = datetime.now(timezone.utc)
    window = report["window"]
    assert window["clock"] == "benchmark_client_wall_clock_utc"
    started, ended = datetime.fromisoformat(window["started_at"]), datetime.fromisoformat(window["ended_at"])
    assert before <= started <= ended <= after
    assert (ended - started).total_seconds() >= .06          # spans the three sequential requests
    assert rows[-1]["window"] == window                      # the persisted event carries it too


@pytest.mark.asyncio
async def test_warmup_and_measurement_cells_have_separate_windows():
    async def request(case, identifier):
        return {"status": "ok"}
    rows = []
    warm = await run_cell([case()], request, concurrency=1, duration_s=1, max_requests=1, timeout_s=1,
                          write=rows.append, cell_id="x-warmup", phase="warmup")
    await asyncio.sleep(.05)
    measured = await run_cell([case()], request, concurrency=1, duration_s=1, max_requests=1, timeout_s=1,
                              write=rows.append, cell_id="x")
    assert warm["window"]["ended_at"] <= measured["window"]["started_at"]


# --- p99 ------------------------------------------------------------------------------------------

def _ok_rows(count, ttft=True):
    return [{"status": "ok", "total_s": index / 100, **({"ttft_s": index / 1000} if ttft else {})}
            for index in range(1, count + 1)]


def test_p99_is_reported_only_with_at_least_100_successes():
    summary = summarize(_ok_rows(100), 10, min_samples=100)
    assert summary["latency_p99_s"] == pytest.approx(0.99)         # nearest rank: the 99th of 100 (second largest)
    assert summary["ttft_p99_s"] == pytest.approx(0.099)
    assert summary["p99_min_samples"] == 100


def test_p99_is_null_below_the_floor_even_when_a_lower_min_samples_allows_p95():
    summary = summarize(_ok_rows(64), 10, min_samples=64)           # the earlier held-out setting
    assert summary["latency_p95_s"] is not None                    # p95 still available at 64
    assert summary["latency_p99_s"] is None and summary["ttft_p99_s"] is None
    assert summary["p99_min_samples"] == 100


def test_p99_floor_follows_a_larger_min_samples_and_ttft_counts_only_known_values():
    assert summarize(_ok_rows(120), 10, min_samples=150)["latency_p99_s"] is None
    mixed = _ok_rows(100) + [{"status": "ok", "total_s": 5.0}] * 10        # 10 successes without a TTFT
    summary = summarize(mixed, 10, min_samples=100)
    assert summary["latency_p99_s"] is not None and summary["ttft_p99_s"] == pytest.approx(0.099)
    few_ttft = _ok_rows(100)[:50] + [{"status": "ok", "total_s": 1.0}] * 50
    assert summarize(few_ttft, 10, min_samples=100)["ttft_p99_s"] is None


def test_failed_requests_never_enter_the_p99():
    rows = _ok_rows(100) + [{"status": "error", "total_s": 999.0}]
    assert summarize(rows, 10, min_samples=100)["latency_p99_s"] == pytest.approx(0.99)
