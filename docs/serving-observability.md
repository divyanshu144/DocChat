# Serving and tracing

Phase 2 now adds [sustained benchmarks](benchmarking.md) and
[Prometheus monitoring](grafana-plan.md). Phase 1 timing definitions below remain
the contract; implementation history is retained in the final section.

DocChat keeps its FastAPI/LangGraph application and separate vLLM HTTP server.
`app/services/llm.py` remains the public entry point. The local backend uses the
small `InferenceBackend` contract in `app/services/inference/types.py`; callers
still receive a string or async text iterator. Hosted providers retain their SDKs.
Ollama/SGLang compatibility is not claimed until their contract tests run.

## Configuration and ownership

Set `LLM_PROVIDER=local`, `LOCAL_BASE_URL` (including `/v1`), `LOCAL_CHAT_MODEL`,
and optionally `LOCAL_API_KEY`. Invalid local URLs or missing models fail clearly;
credentials are not included in configuration errors. Hosted operation needs no GPU.

`INFERENCE_CONNECT_TIMEOUT_S` (5), `INFERENCE_READ_TIMEOUT_S` (60),
`INFERENCE_POOL_TIMEOUT_S` (5), and `INFERENCE_MAX_CONNECTIONS` (100) configure the
local/OpenAI HTTPX transport. Read timeout is an inactivity timeout, not a total
request deadline. Hosted SDK timeout policies are unchanged. No application queue
or retry policy has been added for vLLM. Local failures are never silently retried
against a hosted model.

Clients belong to an event loop and connection configuration. Changing a URL or key
creates a new client without closing an in-flight client's pool. API/MCP shutdown
and the benchmark runner close all clients for their loop. Standalone scripts should
call `await close_llm_clients()` in a finally block. Runtime per-request mutation of
shared settings is unsupported; benchmark provider switching is sequential.

## Timing records

`app.core.telemetry` emits JSON messages through Python logging. Existing logging
formatters may prepend a timestamp/level. No document text, prompts, output text,
credentials or raw error messages are included in these new timing records.
LangSmith is separate: its existing prompt/output capture policy is unchanged.

HTTP requests return `X-Request-Id`; safe supplied IDs are preserved. MCP queries
and standalone public generation calls create their own IDs. vLLM requests carry
that ID as `X-Request-Id`; whether the server logs it depends on server configuration.
Each span includes request ID, span ID, parent ID, outcome and duration in seconds.
LLM attempts include actual provider/model and a request-wide attempt index, so
Groq fallback attempts and OpenAI temperature retries are distinguishable.
SDK-internal retries are not separately visible in these application spans.

Boundaries:
- HTTP duration covers the ASGI response through body completion, including a stream.
- `first_answer_s` is first answer SSE marker delivery to ASGI send, not browser paint
  or a progress event. It includes graph and persistence latency.
- Graph stages carry a one-based iteration; retrieval additionally separates model
  initialization, query embedding, Qdrant search and lexical reranking.
- `llm.attempt` measures backend completion or stream duration. Nonstream TTFT is null.
- Stream TTFT ends at first nonempty text delta, ignoring role/usage-only events.
- `content_duration_s` spans first to last text delta, excluding trailing usage.
- `decode_tokens_per_second_estimate` is `(completion_tokens - 1) / content_duration`.
  It is only a client estimate: a chunk may contain multiple tokens. Unknown usage,
  one-token outputs or zero content duration yield null, never chunk-count throughput.
- `queue_wait_s` is null: no request-level engine timing has been verified. HTTP pool
  waiting, network and prefill remain included in model timings, not falsely split.

Set `LOCAL_STREAM_COMPLETIONS=true` to measure model TTFT during normal graph calls.
The application buffers these streams internally and returns the full draft to the
same grounding/critic steps. Default false preserves the nonstream backend path.
Neither mode sends unverified drafts to the UI. Sampling temperature and output caps
are preserved. Model behavior under streaming still needs live acceptance testing.

Graph failures translated into SSE errors are recorded as errors despite HTTP 200.
Disconnect/cancellation closes local response streams and records cancellation.
Closing an HTTP connection is not proof that a remote engine immediately reclaims
all GPU work; verify that behavior during live acceptance.

## Readiness

`GET /api/v1/health` retains DB/Qdrant checks. The separate
`GET /api/v1/health/serving` checks that the configured local model appears in
`/v1/models`, using a bounded timeout and no generation. It returns 503 on failure,
200 when found, and `not_applicable` for hosted providers. It is a readiness probe,
not proof of successful inference or model quality.

## Engine metrics and the per-cell prefix-cache summary

The sustained benchmark polls the engine's `/metrics` for the metric family selected by `--engine`
(`vllm` by default; `sglang` is unverified, see [benchmarking](benchmarking.md#engine-selection---engine)).
Each cell's counter changes now also yield a prefix-cache hit-rate summary (tokens queried, hit, and the rate) or
an explicit `unavailable` reason. It is an engine-side counter ratio for that cell, not a statement about answer
quality, and it is only as good as the series names for the engine version in use.

## GPU utilization (a separate signal)

vLLM's `/metrics` endpoint does not provide GPU compute utilization, so it is not part of the Prometheus metrics
above. It is sampled on the GPU host by `eval/gpu_sampler.py` and attached to a finished benchmark run by
`eval.gpu_utilization` (see [benchmarking](benchmarking.md#gpu-utilization-optional-separate-signal) for the
runbook). It is content-free: GPU index, utilization, memory and power with timestamps, no prompts or process lists.

**What the number is.** It is the share of the sample period in which at least one kernel was running, so 100 percent
does not mean the GPU is fully used. One small kernel that is always resident can read 100 percent while most of the
GPU's compute and memory bandwidth sits idle. The sample period is the driver's own, not this sampler's interval.

**What it does not tell you.** It does not show that the GPU was used efficiently, and a low reading does not show
where a limit was. It is not memory bandwidth, achieved FLOPs or per-request GPU time. Interpret it beside the other
signals, never instead of them:

| Signal | Source | Answers |
|---|---|---|
| KV-cache usage | vLLM `/metrics` | how close the engine is to cache capacity |
| Waiting requests / queue depth | vLLM `/metrics` | whether requests are queueing in the engine |
| GPU utilization | host sampler (this section) | whether any kernel was running during the sample period |

### How to read it

These are prompts for the next check, not diagnoses. Each row says what the combination MAY suggest.

| Utilization | KV-cache pressure | Queue | What it MAY suggest | Check next |
|---|---|---|---|---|
| High | Low | Not growing | The GPU may have had work to do while cache capacity may not have been what limited this cell. It does not show the work was efficient. | Whether throughput still rises when concurrency rises across the sweep; per-request decode rate; whether a smaller or quantized model changes throughput. |
| High | Near 100 percent | Growing | The engine may be at its capacity for this configuration: cache full and requests waiting. | Preemptions and waiting-request counts over the window; whether errors or timeouts rise at that concurrency; whether less retrieved context, fewer concurrent sequences or more capacity changes the picture. |
| Low | Any | Growing | Requests may be waiting for something other than GPU kernels (scheduling, CPU-side work, cache limits), or the reading may be unreliable. It is not proof of any one cause. | Whether the cell is `ok` and aligned (status, offset provenance, sample count, coverage); KV-cache usage; host CPU; engine limits such as maximum sequences; load-generator rejections and scheduling lag; whether the sampler ran for the whole window. |

Alignment depends on two clocks (the benchmark client's and the GPU host's). The attach step takes an explicit offset
and records whether it was supplied or assumed to be zero, and it warns when an unmeasured offset meets a short window.
Samples that do not cover a cell's window leave that cell `unavailable` rather than reporting a biased mean.
**Status: built and offline-tested with fixtures; no live measurement has been taken yet.**

## Verification and next phase

Offline tests cover transport payloads, usage tails, malformed/unterminated streams,
request isolation, retries, cancellations, lifecycle, readiness and graph spans.
Live acceptance remains pending: run a pinned server, probe its models, submit a
real ingested-document question, inspect stage/model records, and check disconnect
behavior and output compatibility with internal buffering on/off.

Phase 2 exposes `/api/v1/metrics` and adds an explicit `sustained` benchmark subcommand
with schema-v2 artifacts. Historical burst statistics retain their original semantics.
No automatic GPU provisioning, monitoring service or application deployment occurred.
A GPU utilization sampler and attach step now exist (offline-tested only); no live GPU measurement has occurred.
