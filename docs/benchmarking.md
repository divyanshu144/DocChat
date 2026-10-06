# Sustained DocChat workloads (schema v2)

Phase 2 extends `python -m eval.inference_benchmark` with a `sustained` subcommand.
Historical invocations, JSONL files and burst statistics remain unchanged. New files
are separate, versioned artifacts; do not append them to historical JSONL or compare
burst throughput directly to sustained throughput.

## Workload preparation

Start with `data/workloads.example.json`. It is an authoring template, **not an
executed benchmark or a labeled dataset**. Replace placeholder source/chunk IDs,
questions and the zero corpus hash using a fixed, redistributable corpus. Use the
same normalized corpus fingerprint convention as `eval/retrieval_eval.py` (sorted
point IDs and chunk text). The runner records the supplied fingerprint but does not
independently verify the live Qdrant index. Avoid concurrent ingestion while measuring.

Cases have unique IDs, a category, query, source filters, output token budget and
optional evidence labels. Categories: document_qa, summarisation, long_context,
multi_document, negative_control. Labels categorize intent; they do not prove prompt
length or evidence coverage. The existing 12,000-character context cap still applies.
Summaries cover retrieved context, not necessarily a complete document. Check actual
provider input-token counts before claiming long-context performance. Add more cases
and distractors before making externally meaningful claims.

Offline schema check, with no service calls or output directory creation:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target api --workloads data/workloads.example.json \
  --out-dir /tmp/not-created --validate-only
```

For prompt replay, capture each real planner/retriever/synthesizer prompt:

```bash
venv/bin/python -m eval.capture_bench_prompts \
  --workloads /path/to/authored-workloads.json \
  --out /path/to/captured-workloads.json
```

**Capture calls the configured planner model** and reads the real index. It can
incur API cost. It does not generate synthesis answers. No-context or failed cases
abort capture rather than silently changing the dataset. Negative controls that
produce no synthesis prompt belong in API mode. Capture refuses existing outputs.
Captured manifests contain document text; keep private corpora out of source control.
The legacy no-argument capture command retains its original JSONL behavior.

## Prompt replay

Prepare the local serving config and deployment manifest described in
`serving-observability.md` and `vllm_setup.md`. Then, only when a server is ready:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target replay --provider local \
  --workloads /path/to/captured-workloads.json \
  --deployment-manifest /path/to/actual-deployment.json \
  --concurrency 1,4,16,32,64 --duration 60 --requests 1000 \
  --repeats 3 --warmup 4 --timeout 120 --min-samples 100 \
  --cache-mode bust --latency-slo 30 \
  --metrics-url http://127.0.0.1:18000/metrics \
  --out-dir reports/my-new-sustained-run
```

Each cell maintains the requested in-flight concurrency until its duration or request
limit, then drains outstanding requests within their deadlines. Levels and repeats
run sequentially. Warmup requests are written but excluded from measurement. Record
cold start separately. `--cache-mode bust` prepends a unique prefix as the legacy
harness does; it changes the prompt. `reuse` preserves prompts. Measure both separately
and verify actual prefix-cache behavior from server samples.

Replay disables both cross-provider and Groq model fallback for the duration and
restores settings/clients afterward. It uses provider sampling defaults; repeats
therefore assess variation, not bitwise deterministic generation. Do not run this
standalone CLI inside an application worker with shared settings.

For arrival-rate testing, specify rates and an in-flight safety limit:

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target replay --provider local --workloads /path/to/captured-workloads.json \
  --concurrency 64 --arrival-rates 0.5,1,2,4 \
  --duration 120 --requests 2000 --repeats 3 --out-dir reports/my-rate-run
```

Arrivals use a fixed cadence, not a Poisson distribution. Capacity-exceeding arrivals
are counted as **load-generator rejections**, never an invisible queue. If the event
loop misses an arrival by an entire interval it records `missed_schedule` instead
of catching up with a burst. Inspect rejection and scheduling-lag records; offered
rate is not accepted throughput. Run the load generator near the serving host for
engine comparisons and record network/location differences separately.

## End-to-end API mode

Use an isolated benchmark account/database/index. Every request creates a new
conversation and persists messages through the normal application. Use a token file
containing a current access token; the CLI does not sign up, refresh or bypass auth.
Ensure token lifetime exceeds the sweep. Restrict source IDs to the benchmark corpus.

```bash
venv/bin/python -m eval.inference_benchmark sustained \
  --target api --api-base-url http://127.0.0.1:8081/api/v1/ \
  --auth-token-file /private/path/benchmark-access-token \
  --workloads /path/to/authored-workloads.json \
  --concurrency 1,4,16,32,64 --duration 60 --requests 1000 \
  --repeats 3 --out-dir reports/my-api-run
```

Default chat limits are 30 requests/minute/IP. Set an explicit higher limit only in
the isolated benchmark deployment; the client never bypasses production limits.
HTTP 429/401 and SSE error events are failures. Configure and record server fallback
policy yourself: API mode cannot change remote configuration. Output limits remain
server-defined (the manifest's per-case cap applies only to replay).

API timing includes planning, retrieval, verification and persistence. Status events
are not first answer. Success requires answer content and the normal done marker.
A 200 with an error event or incomplete stream fails. API SSE carries no model-token
usage or model TTFT, so those fields stay null; correlate request IDs with app traces
and Prometheus. API mode preserves queries and only supports cache reuse.

## Artifacts and interpretation

Each new output directory contains `manifest.json` and flushed `events.jsonl`:

- Manifest: run ID, corpus/workload hashes, prompt hashes, source commit and Python
  source hash (including uncommitted Python changes), load settings and allowlisted
  deployment fields. No authorization values or token-file paths are copied.
- Request: cell/request/case/category IDs, warmup/measurement phase, status, timing,
  provider token usage and finish reason where available. No prompts or answers.
- Cell summary: errors, timeouts, cancellations, generator rejections, empty outputs,
  truncations, success p50/p95, model TTFT/first answer p95, requests/sec, tokens/sec,
  optional latency-SLO goodput, and category summaries.
- Run summary: mean/min/max/sample standard deviation across repeats for each load.
  This is observed run-to-run variation, not a confidence interval.
- Optional vLLM samples preserve labels/histogram buckets and per-series counter
  deltas. Missing series and observed resets yield unknown deltas. Sampling can miss
  resets between polls. Shared server traffic cannot be attributed to this run.
- Final outcome distinguishes completed, failed and cancelled sweeps. Interrupted
  cells persist partial rows and a summary where graceful cancellation is possible.
  Abrupt process termination may leave no final summary; never call it complete.

Percentiles describe successful requests only; always read error rates beside them.
By default p95 requires at least 100 successes **per reported group**. A category
may lack enough samples even when the overall cell has enough. P50 from smaller
samples remains descriptive. No p99 or confidence claim is made.

Token throughput is null unless every successful request reported output usage;
stream chunk counts are never treated as tokens. Decode speed is explicitly a client
estimate. Throughput denominator includes the final drain, and category rates are
contributions to the mixed workload over the same wall time. A request-limited run
may finish before the configured duration; `stop_reason` records why it stopped.
This alone is not an SLO-certified sustainable-capacity result.

Total request latency starts at scheduled arrival; `service_s` starts at dispatch.
Model TTFT and API first-answer timings start at dispatch. Scheduling lag is separate,
not GPU queue time. For latency-SLO goodput, failures and rejected requests contribute
zero. Truncated successful responses remain in throughput but are counted separately;
answer completeness/groundedness is Phase 3 work.

For schema-v2 speed comparisons:

```bash
venv/bin/python -m eval.quantization_compare \
  --baseline-run reports/fp16-sustained --variant-run reports/awq-sustained
```

The tool refuses incomplete runs, mismatched IDs/workloads/load settings/source
snapshots, and missing or incompatible core deployment metadata. It does not verify
physical host identity or isolate quantization causally. API comparisons additionally
require matching declared `application_revision` and `application_config_sha256`
in the deployment manifests: the runner source hash is not the remote server hash. Legacy timestamp comparisons
still work. Neither mode establishes answer quality.

No GPU or live throughput run was performed while implementing Phase 2.
