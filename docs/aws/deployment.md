# Deployment

Nothing in this repository creates AWS resources on its own. A person runs Terraform; CI only formats, validates and
scans it. These steps have **not** been executed against a real account (see [limitations](limitations.md)); treat the
first run in a throwaway `dev` environment as the test of this document.

## Prerequisites

- An AWS account and a principal allowed to create the resources in `infra/terraform` (this is separate from, and
  broader than, the CI deploy role).
- Terraform >= 1.6 (CI uses the `hashicorp/terraform:1.9` image), AWS CLI v2, Docker.
- A remote state backend you create yourself (S3 bucket + lock). Copy `infra/terraform/backend.tf.example` to `backend.tf`.
- An ACM certificate in the target region for any `staging`/`prod` environment (`prod` refuses to plan without one).
- A GitHub repository with an environment named exactly like the Terraform environment (`dev`, `staging`, `prod`).

## First deployment of an environment

Order matters: tasks cannot start until images and secret values exist.

```bash
cd infra/terraform
cp environments/dev.tfvars.example dev.tfvars     # edit; dev.tfvars is git-ignored; no secrets in it
terraform init                                     # with your backend.tf
# 1. Phase one: only the image repositories (app images and the Qdrant mirror) and the (empty) secret containers.
terraform plan  -var-file=dev.tfvars -target=aws_ecr_repository.service -target=aws_ecr_repository.qdrant -target=aws_secretsmanager_secret.app -out=phase1.tfplan
terraform apply phase1.tfplan
```

2. **Push the first images** (any commit; tags are immutable, use the git SHA):

```bash
SHA=$(git rev-parse HEAD)
for svc in api worker; do
  uri=$(aws ecr describe-repositories --repository-names docchat/dev/$svc --query 'repositories[0].repositoryUri' --output text)
  aws ecr get-login-password | docker login --username AWS --password-stdin "${uri%%/*}"
  docker build --file docker/Dockerfile --target $svc --tag "$uri:$SHA" .
  docker image push "$uri:$SHA"
done
```

3. **Set secret values out of band** (the containers exist from phase one). Values never enter Terraform state or CI logs;
   tasks cannot start until each has one.

```bash
aws secretsmanager put-secret-value --secret-id docchat/dev/jwt-secret-key       --secret-string "$(openssl rand -base64 48)"
aws secretsmanager put-secret-value --secret-id docchat/dev/metrics-bearer-token --secret-string "$(openssl rand -base64 32)"
aws secretsmanager put-secret-value --secret-id docchat/dev/groq-api-key         --secret-string "<paste from your provider>"
aws secretsmanager put-secret-value --secret-id docchat/dev/qdrant-api-key       --secret-string "$(openssl rand -base64 36)"
```

   The database password is created and rotated by RDS in its own managed secret (`rds_master_secret_arn` output). Do not copy it
   anywhere: the tasks read it from Secrets Manager each time they open a connection (see [security](security.md)).

4. **Full apply**, pointing the task definitions at the pushed tags:

```bash
terraform plan  -var-file=dev.tfvars -var api_image_tag=$SHA -var worker_image_tag=$SHA -out=dev.tfplan
# Review the plan. Then, as a person:
terraform apply dev.tfplan
```

5. **Point DNS** at the `alb_dns_name` output, then verify (below).

6. **Wire up CI/CD (optional).** Set `github_repository = "owner/name"` in your tfvars and re-apply to create the OIDC deploy
   role. In the GitHub environment, set variables `AWS_DEPLOY_ROLE_ARN` (output `deploy_role_arn`) and `AWS_REGION`, and
   add required reviewers. After that, deploys are `Actions > Deploy > Run workflow`.

## Qdrant image mirror

The Qdrant host pulls its image from your own ECR repository (`docchat/<env>/qdrant-mirror`) **by digest**, so it never
reaches a public registry at boot and always runs the exact image you reviewed. Do this once per Qdrant version, after
phase one and before the full apply. These commands have **not** been run here.

```bash
VERSION=v1.20.0     # keep within one minor version of qdrant-client in requirements.lock
REPO=$(aws ecr describe-repositories --repository-names docchat/dev/qdrant-mirror --query 'repositories[0].repositoryUri' --output text)

# 1. Resolve the upstream tag to its digest and review it (release notes, vulnerability scan).
UPSTREAM_DIGEST=$(docker buildx imagetools inspect docker.io/qdrant/qdrant:$VERSION --format '{{json .Manifest.Digest}}' | tr -d '"')

# 2. Copy registry-to-registry. This keeps the manifest, so the digest does not change.
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}"
docker buildx imagetools create --tag "$REPO:$VERSION" "docker.io/qdrant/qdrant@$UPSTREAM_DIGEST"

# 3. Read back the digest ECR holds, and confirm it equals the upstream one.
MIRROR_DIGEST=$(aws ecr describe-images --repository-name docchat/dev/qdrant-mirror --image-ids imageTag=$VERSION --query 'imageDetails[0].imageDigest' --output text)
[ "$MIRROR_DIGEST" = "$UPSTREAM_DIGEST" ] && echo "digests match" || echo "MISMATCH: do not use"
```

Put the digest in your tfvars as `qdrant_image_digest = "sha256:..."`. The instance plan fails with a clear message if it is
missing or malformed. The ECR repository scans on push; read the findings before applying. To upgrade Qdrant, mirror the new
version, change the digest and restart the service on the instance (Terraform ignores `user_data` changes on the running node
on purpose, so the node is not replaced; update `qdrant-prestart.sh` and the unit over Session Manager, or replace the node
from a snapshot as described in [backups-and-recovery](backups-and-recovery.md)).

If `imagetools create` changes the digest in your environment (some setups re-encode), use `skopeo copy --all` or `crane copy`,
which copy manifests byte for byte, and keep the digest check.

## Routine deployment (CI/CD)

`deploy.yml` (manual, environment-gated) calls the full CI first. **The images are built once**, inside that CI run, and
scanned there with Trivy. CI keeps the exact scanned images as short-lived artifacts (1 day) and records each image id.
The deploy job loads them, **fails if the id differs from the one that was scanned**, pushes them to ECR under the commit
SHA (immutable tag), reads back the registry **digest**, and registers a new task-definition revision per service that points
at `repository@sha256:...`, so what runs is exactly what was scanned. It updates the **API first** (it owns schema changes),
then the worker, waits for stability, and **fails if ECS rolled the deployment back** (`wait` alone still succeeds after a
rollback, so it checks which revision is primary).

If the SHA tag already exists in ECR (a re-run of the same commit), nothing is pushed and the existing digest is used.

Because the services ignore task-definition drift (`ignore_changes`), a Terraform change to environment variables or sizing
is applied to the *family* but only reaches running tasks on the next deploy. After `terraform apply`, run the deploy
workflow for the SHA currently running to roll the new configuration out.

## Verify a deployment

```bash
curl -fsS https://<host>/api/v1/health/live          # {"status":"ok"} - process is up
curl -fsS https://<host>/api/v1/health               # 200 only if PostgreSQL and Qdrant answer
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/v1/metrics   # 403: blocked at the load balancer
```

Then sign up, submit a small web page through `POST /api/v1/ingest/web/jobs`, poll `GET /api/v1/ingest/jobs/<id>` until
`done`, and ask a question about it. In CloudWatch Logs the same `request_id` appears in the API line that enqueued the
job and the worker lines that ran it.

## Configuration reference (environment variables)

All are read through `app.core.config.settings`; none are required locally.

| Variable | Default | Meaning |
|---|---|---|
| `ENVIRONMENT` | `local` | `staging`/`prod` refuse `DEBUG=true` and a disabled SSRF guard |
| `LOG_FORMAT` | `text` | `json` for CloudWatch (set by the image) |
| `DATABASE_HOST` `_PORT` `_NAME` `_USER` `_PASSWORD` `DATABASE_SSL` | unset | When `DATABASE_HOST` is set the URL is assembled (and the password escaped); setting `DATABASE_URL` too is an error |
| `STORAGE_BACKEND` | `local` | `s3` needs `S3_BUCKET` (`S3_PREFIX`, `AWS_REGION`) |
| `QUEUE_BACKEND` | `local` | `sqs` needs `SQS_QUEUE_URL` and `STORAGE_BACKEND=s3` |
| `INGEST_MAX_ATTEMPTS` | `3` | Must equal the queue's `maxReceiveCount` (Terraform sets both from `ingest_max_attempts`) |
| `INGEST_RETRY_BASE_DELAY_S` / `_MAX_DELAY_S` | `15` / `600` | Exponential backoff bounds |
| `INGEST_JOB_TIMEOUT_S` | `1800` | Hard cap per attempt; timeout is a retryable failure |
| `INGEST_DEDUPE_WINDOW_S` | `3600` | Identical active jobs younger than this are reused |
| `INGEST_BLOCK_PRIVATE_URLS` | `false` | SSRF guard; required in `staging`/`prod` |
| `WEB_MAX_BYTES` / `WEB_FETCH_TIMEOUT_S` | `5242880` / `30` | Largest page body (after decompression) and total fetch time including redirects; apply when the guard is on |
| `INGEST_QUEUED_STALE_S` | `600` | A job still `queued` and untouched this long is ignored by deduplication |
| `SQS_VISIBILITY_TIMEOUT_S` | `300` | Lease = 2/3 of this; heartbeat every 1/3 |
| `RETAIN_UPLOADS` | `false` | Keep S3 originals after success (needed for redrive; Terraform sets `true`) |
| `QDRANT_API_KEY` | unset | Sent as the `api-key` header on every Qdrant call when set (injected from Secrets Manager in AWS) |
| `DATABASE_PASSWORD_SECRET_ARN` | unset | AWS: read the rotating database password from this secret when a connection is opened (instead of `DATABASE_PASSWORD`) |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | API only; serialised by an advisory lock |
| `WORKER_CONCURRENCY` `WORKER_SHUTDOWN_TIMEOUT_S` `WORKER_HTTP_PORT` | `2` `90` `8080` | Worker loop |
| `FORWARDED_ALLOW_IPS` | uvicorn default | Set to the VPC CIDR (never `*`) so rate limits see real client IPs |

## Updating dependencies

`requirements.txt` stays the human-edited, unpinned source (with dev tools). The images install **only** `requirements.lock`.

```bash
# Resolve the runtime closure in a clean venv (the images contain no pip, so freeze from here).
grep -ivE '^(pytest|pytest-asyncio|aiosqlite|ruff)([=<>~ ]|$)' requirements.txt > /tmp/runtime.txt
python3.13 -m venv /tmp/lockvenv && /tmp/lockvenv/bin/pip install -r /tmp/runtime.txt
/tmp/lockvenv/bin/pip freeze > /tmp/new.lock        # replace the body of requirements.lock, keep its 3-line header

# Then prove it: tests on exactly that set, audit, and a build.
python3.13 -m venv /tmp/testvenv && /tmp/testvenv/bin/pip install --no-deps -r requirements.lock
/tmp/testvenv/bin/pip install pytest pytest-asyncio aiosqlite ruff pip-audit
/tmp/testvenv/bin/python -m pytest -m "not eval" -q
/tmp/testvenv/bin/pip-audit -r requirements.lock --no-deps --disable-pip   # see ignores in .github/workflows/ci.yml
docker build --file docker/Dockerfile --target api --tag docchat-api:lock .
```

The Dockerfile fails the build on any `pip check` conflict other than the two named in [security](security.md), and CI
fails on any fixable HIGH/CRITICAL finding in either image.

## Validation commands used here

```bash
docker run --rm -v "$PWD/infra/terraform:/tf" -w /tf hashicorp/terraform:1.9 fmt -check -recursive
docker run --rm -v "$PWD/infra/terraform:/tf" -w /tf hashicorp/terraform:1.9 init -backend=false
docker run --rm -v "$PWD/infra/terraform:/tf" -w /tf hashicorp/terraform:1.9 validate
docker run --rm -v "$PWD/infra/terraform:/work:ro" aquasec/trivy:0.76.1 config --severity HIGH,CRITICAL /work
```

`terraform validate` checks syntax and types only. `terraform plan` needs credentials and has not been run.
