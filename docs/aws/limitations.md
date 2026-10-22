# Known limitations and what is unverified

Read this before trusting any of the other pages.

## Verification status

| Claim | Status | Evidence |
|---|---|---|
| Existing behaviour is preserved | **Verified** | Test counts, so nobody has to guess: **629** passed at git HEAD (the figure CLAUDE.md carried); **634** in the working tree when this work started, because uncommitted `llm.py` seam tests add 5 (not part of this work); **841** now (634 + 207 new). Without a database the 7 PostgreSQL tests skip, so a plain run shows 834 passed, 7 skipped. Local app boot, signup and a local-queue ingest job also ran with every `AWS_*` variable removed |
| Configuration, blob stores, queue, retries, idempotency, health, metrics, log redaction, SSRF guard | **Verified by tests** | `tests/test_platform_config.py`, `test_blob_store.py`, `test_ingest_queue.py`, `test_ingest_runner.py`, `test_ingest_enqueue.py`, `test_worker.py`, `test_logging_redaction.py`, `test_url_safety.py`; no test needs AWS credentials or network |
| Docker images build; run non-root, read-only, no capabilities, offline | **Verified** | Both targets built; run with `--read-only --cap-drop ALL`; embedding works with `--network none` |
| Dependency set that ships is the one that was tested | **Verified** | `requirements.lock`; the whole suite passes in a venv built from it; `pip-audit` clean except two named advisories; Trivy: no fixable HIGH/CRITICAL in either image |
| API to queue to worker to Qdrant/PostgreSQL, retries, DLQ, dedupe, PDF via object store | **Verified end to end, against a local FAKE of SQS and S3** | Real PostgreSQL 16 and Qdrant containers, real boto3 calls to a stand-in endpoint. A stand-in cannot prove IAM, KMS, VPC endpoints or real SQS timing |
| Advisory locks, job claiming, lease versus redelivery, concurrent startup DDL, password rotation on **real PostgreSQL 16** | **Verified locally** | `tests/test_pg_concurrency.py` (marker `pg`): 7 tests passed against a Docker Postgres. Disabling the locks makes the claim and lock tests fail, so they do bite. The CI `postgres` job that runs them on every change has **not** run on GitHub |
| Scale-in protection and the in-flight-aware scale-in alarm | **Unit-tested with a fake agent; alarm validated only** | `tests/test_worker.py`, hygiene tests. The real ECS agent endpoint, the `ecs:UpdateTaskProtection` permission and the metric-math alarm were never run |
| Rotating database password | **Verified against real PostgreSQL, not RDS** | Fake secrets client plus a real role whose password was changed under a live pool. RDS's own rotation was not exercised; the AWS behaviour is from its documentation (see [security](security.md)) |
| Send-then-insert job ordering, stale-queued dedupe | **Verified by tests** | `tests/test_ingest_enqueue.py` (crash between send and insert, conflict with a worker-created row, send failure creates no row, stale queued row ignored) |
| Fetch limits and IP-pinned connections | **Verified by tests, plus one live check** | `tests/test_url_safety.py`; a one-off fetch of a real HTTPS site over the pinned address succeeded. Hostile real-world servers were not tested |
| Qdrant API key, ECR mirror by digest, boot script | **Code and tests verified; Terraform validated only** | The key header is tested on every call path. The boot script, the mirror commands in [deployment](deployment.md) and the digest precondition were never run |
| Demo profile, budget, teardown steps | **Validated only** | `terraform validate` and static tests. Spot behaviour, scale-from-zero timing and the cleanup commands in [teardown](teardown.md) were not run |

| Terraform is formatted, valid, and has no HIGH/CRITICAL Trivy findings | **Verified** (re-run after this pass) | `fmt -check`, `init -backend=false`, `validate`, `trivy config` |
| CI workflows are syntactically valid and their scan steps pass locally | **Verified** | `actionlint`; the exact `pip-audit`, `gitleaks git`, Trivy commands were run locally |
| `terraform plan` / `apply` succeed in a real account | **NOT verified** | Never run: no credentials, by instruction. Expect first-run errors (quotas, names, AMI/instance availability, provider attribute changes) |
| IAM policies grant exactly what the code needs | **NOT verified** | Static tests assert separation; nothing exercised real IAM evaluation. Missing a KMS or SQS action would surface at runtime |
| ECS tasks start, pass health checks, and autoscale | **NOT verified** | The container health commands and read-only root were run locally, not on Fargate |
| Worker graceful drain on SIGTERM and recovery from a hard kill, in a container | **NOT verified live** | Covered by unit tests (drain, cancel-and-release, lease-versus-redelivery timing). Stopping or killing containers was not permitted in the session, so the live version was not run |
| Qdrant server v1.20.0 with client 1.20.0 | **NOT verified** | The end-to-end run used a local Qdrant 1.18 with client 1.20 (it warned about the version gap but worked); the client's in-memory mode is what the unit tests use |
| Deploy workflow (scanned image pushed by digest), OIDC role, rollback detection | **NOT verified** | Linted with `actionlint` only; the artifact hand-off between the CI and deploy jobs has not run |
| Backup, restore and redrive procedures | **NOT verified** | Written from AWS documentation; see the checklist in [backups-and-recovery](backups-and-recovery.md) |
| ARM64 images | **NOT verified** | CI builds amd64 |
| Cost figures | **Estimates** | See [cost](cost.md) |

## Design limitations

- **Qdrant is a single node.** No replication, one AZ, daily crash-consistent snapshots, no TLS (an API key and network
  isolation protect it; the key travels over plain HTTP inside private subnets). Replacing it with Qdrant Cloud or a clustered deployment is the first scaling step.
- **No bulk re-index.** Rebuilding Qdrant means re-submitting sources one at a time. A command that lists sources and
  enqueues each would complete the disaster-recovery story; it does not exist yet.
- **pgvector is not used.** This is deliberate (retrieval is Qdrant). If you later consolidate on PostgreSQL, that is a
  retrieval-layer rewrite, not an infrastructure toggle.
- **An interrupted job still uses a delivery attempt** (deploys, Spot reclaims, crashes). Scale-in no longer interrupts jobs, but
  see [operations](operations.md) for sizing `INGEST_MAX_ATTEMPTS`.
- **At-least-once delivery.** The queue is a standard SQS queue. Duplicates are handled by the claim and the advisory lock,
  not prevented. Ordering is not guaranteed.
- **Rate limits are per task** (in-process), so they scale with the number of API tasks. Redis was not added.
- **No WAF**, and `/metrics` collection is not included (see [operations](operations.md)).
- **HTTPS-only egress**, so plain `http://` pages cannot be ingested.
- **The fetch guard covers web pages only.** Size and time limits apply when `INGEST_BLOCK_PRIVATE_URLS` is on; YouTube ingestion
  goes through a library that is not covered (see [security](security.md)).
- **The app uses the RDS master user** and runs DDL at startup (serialised by an advisory lock). A separate migration role and
  a least-privilege runtime role are recommended.
- **JWT library.** `python-jose` is unmaintained and two advisories are accepted by ID; replacing it with PyJWT is recommended.
- **Single region.** There is no cross-region replication of any data store and no disaster-recovery region.
- **Uploaded PDFs are retained only 30 days** (`upload_retention_days`); after that a DLQ redrive of a PDF job fails permanently.
- **Image size is ~1.4 GB**, which slows first starts on a new Fargate host.
- **`terraform apply` changes to task definitions do not reach running tasks** until the next deploy (the services ignore
  task-definition drift so the deploy workflow owns the image). See [deployment](deployment.md).
- **Dependency pin exceptions.** `fastembed` and `python-jose` metadata conflicts are accepted explicitly in the Dockerfile.
- **Local files outside this task** were already modified or untracked before it began (`app/services/llm.py`,
  `tests/test_llm_provider_seam.py`, benchmark reports, `Claude outputs/`); they are not part of this change and should not
  be staged with it. `app/core/config.py` contains both an earlier uncommitted one-line change (`fallback_llm_provider`) and
  this work.
