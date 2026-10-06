# Monitoring setup and later Grafana panels

`GET /api/v1/metrics` exposes the official Python Prometheus client's text format.
Set `METRICS_BEARER_TOKEN` and configure Prometheus with the corresponding bearer
file when needed; otherwise keep this endpoint on a private network. Scrapes are
excluded from request telemetry so monitoring does not inflate request rates.
The registry is single-process, matching DocChat's current single-worker deployment.
Do not start multiple independent workers and assume their metrics or limits aggregate.

An example, not a deployed stack: `deploy/observability/prometheus.yml`. Adjust the
API prefix and network targets. vLLM is a separate scrape job: its GPU queue/KV cache
metrics must not be confused with application request metrics. Pin the engine and
check the actual exposition names. Device utilization/memory needs a GPU exporter;
KV-cache occupancy alone is not GPU utilization.

Suggested Grafana panels (default API prefix below):

| Panel | PromQL / source |
|---|---|
| Successful chat requests/sec | `sum(rate(docchat_requests_total{route="/api/v1/chat",outcome="ok"}[5m]))` |
| Chat error/cancellation ratio | `sum(rate(docchat_requests_total{route="/api/v1/chat",outcome!="ok"}[5m])) / sum(rate(docchat_requests_total{route="/api/v1/chat"}[5m]))` |
| p95 full chat latency | `histogram_quantile(0.95, sum by (le) (rate(docchat_request_duration_seconds_bucket{route="/api/v1/chat",outcome="ok"}[5m])))` |
| p95 first answer | `histogram_quantile(0.95, sum by (le) (rate(docchat_first_answer_seconds_bucket{route="/api/v1/chat"}[5m])))` |
| Active HTTP requests | `docchat_requests_inflight` |
| Stage p95 | `histogram_quantile(0.95, sum by (le,stage) (rate(docchat_stage_duration_seconds_bucket[5m])))` |
| Model TTFT p95 | `histogram_quantile(0.95, sum by (le,provider) (rate(docchat_llm_ttft_seconds_bucket[5m])))` |
| Output tokens/sec | `sum by (provider) (rate(docchat_llm_tokens_total{direction="output"}[5m]))` |
| Missing usage | `sum by (provider) (rate(docchat_llm_missing_usage_total[5m]))` |
| Explicit model retries | `sum by (provider) (rate(docchat_llm_retries_total[5m]))` |
| Retrieval problems | Rates of `docchat_retrieval_failures_total` and `docchat_empty_retrieval_total` |
| Critic behavior | Rates of `docchat_critic_parse_failures_total` and `docchat_replans_total` |
| Engine pressure | vLLM running/waiting requests, KV occupancy, prefix hits and preemptions; verify version-specific names |

Request outcomes include stream failures despite HTTP 200; status-class labels
alone cannot identify these failures. Request histograms span the complete response,
not just response-header time. Stage spans include retries/iterations, so summing
nested stage histograms double-counts; use individual stages or the top-level request.
Buckets range from 10 ms through 320 s plus infinity; tune after measuring real SLOs.
TTFT is observed only on streams. Enable LOCAL_STREAM_COMPLETIONS for model TTFT in
normal graph requests, and distinguish it from first-answer delivery.

No request IDs, users, document names, queries or model-name strings appear as metric
labels. Provider/stage/outcome are fixed sets; HTTP route labels are registered route
templates, with unmatched requests grouped together. Correlate an incident through
content-free request logs, not high-cardinality metric labels.

Choose alert thresholds after establishing workload-specific SLOs. Initial alerts:
sustained error ratio with a minimum traffic floor, p95 over the agreed budget,
increasing engine backlog, preemptions, missing token usage and critic parse failures.
No dashboard or monitoring service is automatically provisioned by this change.

References: [Python client histograms](https://prometheus.github.io/client_python/instrumenting/histogram/),
[exposition parser](https://prometheus.github.io/client_python/parser/).
