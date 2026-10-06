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

## Verification and next phase

Offline tests cover transport payloads, usage tails, malformed/unterminated streams,
request isolation, retries, cancellations, lifecycle, readiness and graph spans.
Live acceptance remains pending: run a pinned server, probe its models, submit a
real ingested-document question, inspect stage/model records, and check disconnect
behavior and output compatibility with internal buffering on/off.

Phase 2 exposes `/api/v1/metrics` and adds an explicit `sustained` benchmark subcommand
with schema-v2 artifacts. Historical burst statistics retain their original semantics.
No automatic GPU provisioning, monitoring service or application deployment occurred.
