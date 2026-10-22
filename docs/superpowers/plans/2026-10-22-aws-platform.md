# AWS platform plan (2026-10-22)

Goal: add a Terraform-managed AWS deployment (ECS Fargate API + ingestion worker, S3, SQS + DLQ, RDS,
Secrets Manager, CloudWatch) without changing local behaviour. Nothing is applied; no AWS account is touched.

## What the repo actually is (inspected, not assumed)

| Brief assumed | Reality | Decision |
|---|---|---|
| Celery + Redis | Neither exists. Jobs are FastAPI `BackgroundTasks`; state lives in Postgres `ingest_jobs`. In-process rate limiter. | Do not add Celery/Redis. SQS is the durable queue the ingestion skill says is required before scaling past one worker. |
| pgvector | Vectors live in Qdrant (`source_chunks`). Retrieval, ingest, list and delete all use the Qdrant client. | Keep Qdrant. RDS is plain PostgreSQL (users, conversations, jobs). Replacing Qdrant has no justification and would touch retrieval quality. |
| vLLM | Optional `LLM_PROVIDER=local` over HTTP, a benchmarking target. | Out of scope. Not deployed; API reaches Groq/OpenAI as today. |
| Structured logs / metrics | `app/core/telemetry.py` already emits content-free JSON and `X-Request-ID`; `/metrics` is Prometheus with an optional bearer token. | Extend, do not replace. |
| Health | `/health` is readiness (DB + Qdrant, 503 on failure). | Add `/health/live` (no dependencies) for ALB/ECS liveness. |

Hazards found that the AWS design must handle:
1. `recover_interrupted_ingest_jobs()` marks every queued/running job as error on startup. With several tasks, one API
   restart would kill jobs running in workers. Gate to the local queue backend only.
2. `create_all_tables()` runs DDL on every start. Concurrent tasks race. Guard with a Postgres advisory lock and a
   setting to disable it for workers.
3. `/metrics` would be reachable through the ALB. Block it at the listener; scrape from inside the VPC.
4. Rate limiter is per process, so limits multiply by task count. Documented limitation, not fixed here.

## Application changes (all additive, local defaults unchanged)

- `app/core/config.py`: `storage_backend` (local|s3), `queue_backend` (local|sqs), bucket/queue/region, retry and
  visibility settings, `log_format`, `retain_uploads`, `run_migrations_on_startup`, DB parts (host/port/name/user/password/sslmode)
  assembled into `database_url` when a host is given (so the RDS-managed secret needs no URL in Terraform state).
  Production validation refuses unsafe combinations.
- `app/services/blobs/`: `BlobStore` protocol, `LocalBlobStore`, `S3BlobStore` (SSE, bounded reads, lazy boto3).
- `app/services/queueing/`: versioned job message, `SQSQueue` (send/receive/ack/extend/release), correlation id in attributes.
- `app/services/ingestion/runner.py`: one `run_ingest_message()` used by both the local background task and the worker.
- `ingest_jobs`: columns `attempts`, `dedupe_key`, `lease_until` (added by the existing `_migrate` pattern).
  Idempotency: deterministic source IDs already exist; add job-level dedupe of active jobs and an atomic claim so a
  duplicate SQS delivery of a finished job is acknowledged without re-running.
- `app/worker/`: long-poll loop, bounded concurrency, visibility heartbeat, exponential backoff, final-attempt handling
  (SQS redrive moves the message to the DLQ), SIGTERM graceful shutdown that releases unfinished messages, and a tiny
  stdlib HTTP server for `/livez`, `/readyz`, `/metrics`.
- Logging: JSON formatter + redaction filter, request/correlation id on every line. Worker metrics added to the existing registry.

## Containers
`docker/Dockerfile`: multi-stage, pinned base, non-root, embedding model baked in, `api` and `worker` targets, HEALTHCHECK.
Root `Dockerfile` and `docker-compose.yml` are untouched so local dev is unchanged.

## Terraform (`infra/terraform`, plain resources, no third-party modules)
network, ecr, s3, sqs (+DLQ, redrive), rds, qdrant (single EC2 + encrypted EBS + DLM snapshots), secrets, iam (separate
execution and task roles per service, scoped OIDC deploy role), ecs (two independent services, circuit-breaker rollback,
autoscaling), alb (HTTPS, `/metrics` blocked), cloudwatch (log groups, alarms, dashboard, SNS). No account IDs; no secret values.
Validation: `terraform fmt -check` and `validate` via the official image (`init -backend=false`).

## CI/CD (`.github/workflows`)
`ci.yml`: ruff, pytest, pip-audit, gitleaks, image builds + Trivy scan, terraform fmt/validate + Trivy config scan.
`deploy.yml`: manual, OIDC, environment-gated; builds, pushes, registers task definition, updates one service.

## Tests (no AWS credentials, no network)
config, blob stores, SQS queue, runner retries/idempotency/permanent errors, worker loop + shutdown, health, metrics,
log redaction, ingest endpoints under both backends, infra hygiene (no account IDs / secrets in `infra/`).

## Docs
`docs/aws/`: architecture, deployment, rollback, backups-and-recovery, security, cost, limitations.

## Not verifiable here (will be reported as such)
Any real AWS behaviour (apply, IAM evaluation, ECS placement, SQS redrive timing, RDS SSL), arm64 images, Trivy/gitleaks results if not runnable locally.
