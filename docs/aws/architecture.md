# AWS architecture

Status: **designed, validated offline, never applied.** See [limitations](limitations.md) for exactly what has and has not been verified.

The AWS platform is an additive deployment path. Local development (`docker compose up`, SQLite or the compose
PostgreSQL, in-process background jobs) is unchanged and needs no AWS credentials.

## What the application actually is

Inspected before designing; several assumptions in the original brief did not match the repository.

| Brief assumed | Repository reality | Decision |
|---|---|---|
| Celery + Redis | Neither exists. Ingestion ran as FastAPI `BackgroundTasks`, with job state in the PostgreSQL `ingest_jobs` table and a startup sweep that marked interrupted jobs as failed. The ingestion skill states a durable shared queue is required before running more than one worker. | **Do not add Celery or Redis.** Amazon SQS is the durable queue. The in-process path stays as the local default. |
| pgvector | Vectors live in **Qdrant** (`source_chunks`). Retrieval, ingestion, source listing and deletion all use the Qdrant client. | **Keep Qdrant.** RDS is plain PostgreSQL for users, conversations and job state. Enabling pgvector would add an unused extension and force a rewrite of retrieval with no benefit. |
| vLLM | Optional `LLM_PROVIDER=local` HTTP backend used for benchmarking. | Not deployed. The API calls Groq/OpenAI exactly as before. |
| Structured logs, metrics | Content-free JSON telemetry, `X-Request-ID`, and a Prometheus `/metrics` already existed. | Extended, not replaced. |

## Topology

```
                         Internet
                            |
                    +-------v--------+   :443 (ACM cert)   /api/v1/metrics -> 403 at the listener
                    |      ALB       |   health check: /api/v1/health/live
                    +-------+--------+
                            | :8000 (ALB security group only)
        private subnets     |
   +------------------------v-----------------------+        +---------------------------+
   |  ECS Fargate service "api"  (2+ tasks)         |        |  ECS Fargate service      |
   |  FastAPI, chat + auth + enqueue                |        |  "worker"  (1+ tasks)     |
   +-----+-----------+------------+-----------------+        |  long-polls SQS, ingests  |
         |           |            |                          +--+--------+--------+------+
         | SendMessage            | PutObject                   |        |        |
         |           |            |                  Receive/   | GetObj |        |
         v           v            v                  Delete     v        v        v
   +----------+  +--------+  +----------+            +-----------+  +--------+  +----------+
   | SQS      |  | RDS    |  | S3 docs  |            |  SQS      |  | S3     |  | Qdrant   |
   | ingest   |  | PG 16  |  | (KMS)    |            |  + DLQ    |  |        |  | EC2+EBS  |
   +----+-----+  +--------+  +----------+            +-----------+  +--------+  +----------+
        | maxReceiveCount = INGEST_MAX_ATTEMPTS
        v
   +----------+      API and worker both talk to: RDS (5432), Qdrant (6333), AWS APIs (443)
   |   DLQ    |      Only the API talks to: the LLM provider.  Only the worker fetches user URLs.
   +----------+
```

Everything except the ALB runs in private subnets. Egress goes through a NAT gateway (HTTPS only) and an S3 gateway endpoint.

## Ingestion flow (SQS path)

1. `POST /ingest/{pdf,youtube,web}/jobs` (API). For a PDF the upload is stored in S3 under `uploads/<job-id>/source.<ext>`;
   the key contains neither the filename nor any content.
2. The API computes a **dedupe key** (the deterministic source id the ingesters already use: content SHA-256 for files,
   canonical URL for web pages, video id for YouTube). If an identical job is queued or running and was updated within
   `INGEST_DEDUPE_WINDOW_S`, that job is returned instead of creating another.
3. The message (job id, type, storage key or URL, correlation id) is sent **first**, then the job row is inserted, and the
   insert ignores a row that already exists. If the API dies in between, the worker creates the row itself when it claims the
   message (`claim_job`), so there is never a "queued" row without a message behind it. If the send fails, no row is created
   and the API returns 503. If the send works but the insert fails, the API also returns 503; the work still runs, and a retry
   is deduplicated. An identical job that is still `queued` after `INGEST_QUEUED_STALE_S` (default 10 minutes) is ignored by
   deduplication, so one dead row can never block resubmission.
4. A worker receives the message and **claims** the job atomically. A finished job is acknowledged without re-running;
   a job with a live lease is treated as a duplicate; an expired lease is re-claimed (crash recovery).
5. The worker takes a **per-source PostgreSQL advisory lock** so two workers never rewrite the same source at once
   (Qdrant replacement is delete-then-upsert, not transactional). The lock is released automatically if the worker dies.
6. Ingest runs (`pdf.py`/`web.py`/`youtube.py`, unchanged). While it runs a heartbeat extends the SQS visibility timeout
   and the DB lease. On success the job is `done` and the message is deleted.

### Retries and dead-letter handling

| Outcome | What happens |
|---|---|
| Transient failure (network, 5xx, Qdrant down) | Job returns to `queued`/`retrying`; visibility is set to an exponential backoff (`base * 2^(n-1)`, capped). |
| Final allowed attempt fails | Job is marked `error`; the message is released immediately and SQS moves it to the DLQ (`maxReceiveCount` equals `INGEST_MAX_ATTEMPTS`; one variable sets both). A CloudWatch alarm fires on any DLQ message. |
| Permanent failure (`ValueError`: unsupported type, no readable text, blocked URL; missing upload) | Job is marked `error` and the message is deleted. Retrying cannot help. |
| Malformed message | Never parsed into work; skipped and left for the redrive policy. Its body is never logged. |
| Worker receives SIGTERM | Stops polling, finishes in-flight jobs within `WORKER_SHUTDOWN_TIMEOUT_S`, then cancels the rest. A cancelled job goes back to `queued` and its message is released for another worker. |
| Worker is killed | The lease (two thirds of the visibility timeout) lapses *before* SQS redelivers, so the redelivered message is re-claimed rather than discarded as a duplicate. |

## Local versus AWS

| Concern | Local (default) | AWS |
|---|---|---|
| Queue | FastAPI `BackgroundTasks` (`QUEUE_BACKEND=local`) | SQS (`QUEUE_BACKEND=sqs`) |
| Document storage | Temp file, deleted after ingest (`STORAGE_BACKEND=local`) | S3, retained for redrive, expired by lifecycle |
| Database | SQLite or compose PostgreSQL | RDS PostgreSQL 16 (TLS enforced) |
| Vector store | Qdrant from compose | Qdrant on EC2 with a dedicated EBS volume |
| Startup recovery | Marks interrupted jobs failed | Disabled (the lease logic recovers instead) |
| DDL on startup | Always | API only, serialised by an advisory lock |
| Logs | Plain text | One JSON object per line, redacted |
| Secrets | `.env` | Secrets Manager injected as environment variables |

`QUEUE_BACKEND=sqs` requires `STORAGE_BACKEND=s3` (API and worker do not share a disk); configuration validation refuses
the combination otherwise.

## Why Qdrant is on EC2, not Fargate

Qdrant needs a real block device; network file systems such as EFS are not supported for its storage. A single
instance with an encrypted EBS volume and daily snapshots is the smallest correct design. It is also the weakest part:
one node, no replication, no TLS (API key plus network isolation). See [limitations](limitations.md).

## Repository map

| Path | Purpose |
|---|---|
| `infra/terraform/` | All AWS resources; plain `aws_*` resources, no third-party modules |
| `docker/Dockerfile` | Multi-stage, `--target api` and `--target worker` |
| `requirements.lock` | Exact dependency set the images install |
| `.github/workflows/` | `ci.yml` (code, containers, infrastructure) and `deploy.yml` (manual, gated) |
| `app/services/blobs/`, `app/services/queueing/` | Storage and queue abstractions (local and AWS) |
| `app/services/ingestion/runner.py`, `enqueue.py` | Queue-driven ingestion and its API side |
| `app/worker/` | Worker loop, probe server, entry point (`python -m app.worker`) |
| `app/core/logging_config.py`, `app/core/url_safety.py` | Redacting JSON logging; SSRF guard |
