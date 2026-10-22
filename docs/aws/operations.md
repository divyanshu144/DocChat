# Operations: health, logs, correlation ids, metrics, alarms

## Health endpoints

| Endpoint | Used by | Checks | Fails when |
|---|---|---|---|
| `GET /api/v1/health/live` | ALB target group, ECS container health check | The process answers | The process is wedged. **No dependency checks**, so a PostgreSQL or Qdrant outage never makes the ALB drain healthy tasks |
| `GET /api/v1/health` | Humans, post-deploy smoke test | PostgreSQL `SELECT 1` and Qdrant `/collections`, 3 s each | Either dependency is down (503; connection details are never returned) |
| `GET /api/v1/health/serving` | Local-LLM benchmarking only | Optional vLLM readiness | n/a for AWS |
| Worker `GET :8080/livez` | ECS container health check | The worker's event loop is still ticking | The loop has stalled for 30 s |
| Worker `GET :8080/readyz` | Scraping/diagnostics | Embedding model loaded, not stopping, fewer than 5 consecutive queue errors | Starting, draining, or SQS unreachable |

## Correlation ids

Every request gets an `X-Request-ID` (an inbound one is honoured only if it matches `[A-Za-z0-9_.-]{1,128}`; otherwise a
UUID is generated) and returns it in the response. When a request enqueues ingestion, that id travels in the SQS message as
`correlation_id` and the worker runs the job inside the same trace, so **one id follows a document from upload through the
worker's retries**:

```
fields @timestamp, @message
| filter request_id = "<id from the X-Request-ID response header>"
| sort @timestamp asc
```

Run that against both log groups (`/docchat/<env>/api` and `/docchat/<env>/worker`).

## Access log

uvicorn's own access log is disabled in JSON mode because it records query strings. The `request` telemetry event replaces it: one
JSON line per request with `method`, `route` (the route template, never the real ids), `status_code`, `duration_s`, `outcome`,
`transport` and `request_id`, and no query string. `tests/test_access_log.py` proves this.

## Structured logs

`LOG_FORMAT=json` (set in the image) produces one object per line:
`ts, level, logger, message, env, request_id, ...fields`. Events the application emits as telemetry (`request`, `span`,
`ingest_job`, `llm_retry`) are flattened into top-level fields. Redaction rules and what is never logged are in
[security](security.md). Useful Logs Insights queries:

```
# Failed or retried ingests
fields @timestamp, job_id, source_type, outcome, receive_count, error_type
| filter message = "ingest_job" and outcome != "done" | sort @timestamp desc

# Slowest routes
stats pct(duration_s, 95) by route | filter message = "request" and transport = "http"
```

## Metrics (Prometheus text format at `/api/v1/metrics`, and `:8080/metrics` on the worker)

Existing: `docchat_requests_total`, `_request_duration_seconds`, `_requests_inflight`, `_first_answer_seconds`,
`_stage_duration_seconds`, `_llm_*` (attempts, duration, TTFT, tokens, retries), retrieval and critic counters.

Added for the queue path:

| Metric | Labels | Meaning |
|---|---|---|
| `docchat_ingest_jobs_total` | `source_type`, `outcome` (`done` `retry` `failed` `dead_letter` `duplicate` `cancelled`) | Every attempt, by outcome |
| `docchat_ingest_job_duration_seconds` | same | Attempt duration |
| `docchat_worker_polls_total` | `result` (`messages` `empty` `error` `poison`) | Queue health from the worker's side |
| `docchat_worker_inflight_jobs` | none | Jobs being processed now |

Labels are bounded sets or route templates; nothing user-controlled becomes a label value.

**Scraping:** the load balancer blocks `/api/v1/metrics`, so something inside the VPC must scrape it (and send the bearer
token). This repository does **not** ship that collector; the options are a Prometheus/Alloy/OpenTelemetry-collector sidecar
or a separate scraper service, writing to Amazon Managed Prometheus or Grafana Cloud. Until you add one, the CloudWatch
alarms below (built from AWS-native metrics and log filters) are what pages you.

## Alarms (all notify the SNS topic `alarm_topic_arn`; set `alarm_email` to subscribe an address)

| Alarm | Fires when | First thing to check |
|---|---|---|
| `api-5xx` | 10+ target 5xx in 5 min | API logs, `level = ERROR` |
| `api-latency-p95` | p95 > 10 s for 3 of 5 minutes | LLM provider latency, Qdrant |
| `api-unhealthy-hosts` | any task failing its health check | ECS service events |
| `api/worker-running-tasks-low` | fewer tasks than the configured minimum (missing data counts as breaching) | ECS events; a failed deploy |
| `api/worker-cpu-high`, `-memory-high` | >85% for 15 min | Scale limits; large PDFs on the worker |
| `ingest-job-dead-lettered` | a job failed its last attempt (from the worker's JSON log line; fires first) | Worker log for that `job_id` |
| `ingest-dlq-not-empty` | any message in the DLQ (confirms the move) | [Redrive procedure](backups-and-recovery.md) |
| `ingest-oldest-message-age` | oldest queued message > 15 min | Worker down, or capacity; backlog alarm scales workers out |
| `api-error-logs` | 5+ ERROR log lines in 5 min | Log search |
| `rds-cpu-high`, `rds-free-storage-low`, `rds-connections-high` | 80% CPU, <2 GiB free, >80 connections | Pool sizing: tasks x (`db_pool_size` + `db_max_overflow`) |
| `qdrant-status-check`, `qdrant-auto-recover` | EC2 status check failed; system failure triggers auto-recover | [Qdrant restore](backups-and-recovery.md) |

The CloudWatch dashboard `<project>-<env>` charts requests/5xx, p95 latency, queue depth and age (main and DLQ), ECS CPU and
memory, and RDS. Worker autoscaling adds 1 task when 10 or more messages stay visible for 2 minutes (3 tasks at 100 or
more) and removes 1 after 15 empty minutes, within `worker_min_count`/`worker_max_count`.

## Capacity notes

- DB connections: each API task opens up to `db_pool_size + db_max_overflow` (10 + 20 by default). 6 API tasks plus workers
  can exceed a small instance's `max_connections`; the connection alarm is the early warning.
- The worker holds the per-source advisory lock on a dedicated connection while ingesting, so concurrency of 2 uses up to
  2 extra connections per worker task.
- Image size is about 1.4 GB (ONNX runtime, PyMuPDF, the baked embedding model); first start on a new Fargate host pulls it.

## Scale-in, deploys and interrupted jobs

**Scale-in cannot stop a worker that is busy.** Two layers:

1. The scale-in alarm (`worker-backlog-clear`) counts queued messages plus in-flight messages
   (`ApproximateNumberOfMessagesVisible + ApproximateNumberOfMessagesNotVisible`), so a queue that only holds running jobs is not
   treated as empty.
2. While a worker has at least one job in flight it turns on ECS task scale-in protection through the ECS agent endpoint
   (`app/worker/protection.py`). It is renewed every minute (it expires after 5 minutes by itself if the worker dies) and
   released when the worker is idle. If the endpoint is missing or fails, the worker keeps running without protection and logs
   `task_protection_unavailable` once, with no error text. The worker task role needs `ecs:UpdateTaskProtection`, scoped to
   this cluster's tasks.

Protection stops autoscaling only. A deploy, a Spot reclaim, an out-of-memory kill or a crash can still end a worker mid-job.

**An interrupted job still uses one of its attempts.** SQS raises `ApproximateReceiveCount` every time it hands the message out,
whether or not the job failed. A job that is interrupted twice and then finishes on the third delivery is fine; one that is
interrupted three times is moved to the DLQ with the default `INGEST_MAX_ATTEMPTS=3`, even though it never failed on its own.

How the pieces relate:

| Setting | Default | Rule of thumb |
|---|---|---|
| `INGEST_MAX_ATTEMPTS` (and queue `maxReceiveCount`) | 3 | Expected interruptions + real retries + 1. Use 5 if you deploy often during long jobs or run the worker on Spot |
| `INGEST_JOB_TIMEOUT_S` | 1800 | Longer than your slowest normal job. A timeout counts as a failed attempt |
| `SQS_VISIBILITY_TIMEOUT_S` | 300 | Only the time to notice a dead worker; the heartbeat extends it while a job runs |
| Worker drain (`WORKER_SHUTDOWN_TIMEOUT_S`) | 90 | Jobs longer than this are cancelled during a deploy and cost one attempt |

A typical web page or small PDF takes seconds to a minute, so 3 attempts is plenty. For large files that take many minutes,
raise `ingest_max_attempts` and avoid deploying while the queue is busy.

## The one remaining gap in job recording

Sending before inserting closes the "API died after commit, before send" hole, so no job is left `queued` with no message. What
remains: a message that **expires from the queue** (retention is 4 days) while no workers are running. Its job row, if one
exists, stays `queued`; new submissions of the same source are not blocked (stale queued rows are ignored after
`INGEST_QUEUED_STALE_S`). The `ingest-oldest-message-age` alarm fires after 15 minutes of waiting work, which is long before
the 4 day limit, so a worker outage is noticed well in time. No sweeper is needed.
