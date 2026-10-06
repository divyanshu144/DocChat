# Phase 2: sustained benchmarks and Prometheus metrics

Extend the existing inference benchmark CLI with a `sustained` subcommand, backed
by focused workload/load modules. Existing burst commands and artifacts retain
schema/semantics. New runs have schema v2, explicit run/cell/request IDs, workload
and corpus hashes, optional deployment manifest, and incremental JSONL output.

Two targets: captured prompt replay via the current LLM seam, and authenticated
DocChat chat SSE requests. Two schedules: closed-loop concurrency and fixed-rate
arrivals with a bounded in-flight limit. Exceeding that limit is recorded as a
load-generator rejection, not silently queued or omitted. Warmups are excluded
from measurement; timeouts, errors, truncations and missing usage remain visible.
Latency from scheduled arrival and service dispatch are distinct. Unknown usage
never becomes a chunk count. Repeated cells report overall and category summaries;
small sample percentiles are explicitly flagged. Partial runs retain evidence.

Use prometheus-client with an isolated single-process registry. Update metrics from
Phase 1 telemetry: request outcomes/duration/first-answer, in-flight, stage timing,
LLM attempts/TTFT/tokens, retrieval failures/empty results, retries and critic parser
failures. Only bounded route/stage/provider/outcome labels, no text or identities.
Expose /api/v1/metrics with optional static bearer protection, and retain versioned
vLLM metric snapshots with labels via the standard exposition parser.

Ship optional scrape configuration and Grafana panel/query definitions, not a
running monitoring stack. No GPU provisioning, live performance/quality claims,
production rate-limit bypass, benchmark UI or capacity estimator in this phase.
