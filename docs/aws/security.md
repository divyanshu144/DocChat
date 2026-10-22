# Security

## Principles applied

- No secrets in the repository, Terraform state, task-definition JSON or CI. Secret *values* are set out of band and
  injected by ECS from Secrets Manager at container start. The database password is generated and rotated by RDS.
- No account IDs, ARNs or regions are hard-coded; they come from data sources and variables.
- Separate execution roles and task roles per service; the worker never receives the JWT key, LLM keys or the metrics token, and its only secret access is reading the database password.
- Private subnets for everything except the load balancer; security groups reference each other, not CIDRs.
- CI uses OIDC with a role scoped to one repository *environment*; there are no stored AWS keys.

## IAM matrix

| Principal | Allowed | Not allowed (and asserted by `tests/test_infra_hygiene.py`) |
|---|---|---|
| API task role | `s3:PutObject` on `uploads/*`; `kms:GenerateDataKey`/`Decrypt` via S3 only; `sqs:SendMessage` on the ingest queue; `GetSecretValue` on the DB secret only | Reading objects, receiving/deleting messages, the DLQ |
| Worker task role | `s3:GetObject`/`DeleteObject` on `uploads/*`; `kms:Decrypt` via S3 only; receive/delete/change-visibility on the ingest queue; `ecs:UpdateTaskProtection` for its own cluster's tasks; `GetSecretValue` on the DB secret only | Uploading, sending messages, the DLQ, `kms:GenerateDataKey` |
| API execution role | Pull the API image; write its own log group; read the JWT, LLM, metrics and Qdrant key secrets (injected at start) | Anything else |
| Worker execution role | Pull the worker image; write its own log group; reads **only the Qdrant key** secret | Any secret |
| Qdrant instance role | SSM Session Manager; ECR pull on the mirror repository; read the Qdrant API key secret | Everything else (no SSH, no keys, no other secrets, IMDSv2 only, hop limit 1) |
| GitHub deploy role | Push to the two ECR repos; register task definitions; update only this environment's services; `iam:PassRole` only for the four ECS roles to `ecs-tasks` | Terraform, IAM changes, data access |

Documented wildcard resources are limited to actions AWS does not allow to be scoped (`ecr:GetAuthorizationToken`,
`ecs:RegisterTaskDefinition`/`DescribeTaskDefinition`). A test fails on any other `resources = ["*"]`.

## Database password rotation

What the AWS documentation says (RDS User Guide, "Password management with Amazon RDS and AWS Secrets Manager"): with a managed
master password, RDS stores it in Secrets Manager and **rotates it every seven days by default**. Each rotation creates a new
secret version, and **RDS changes the master password in the database itself to match** (it is not a second credential). The
page does not describe connection behaviour. From how PostgreSQL works, sessions that are already open stay open, and any
**new** connection that presents the old password is rejected.

Consequence: a password copied into an environment variable when the task started works for up to seven days, then every
pool reconnect fails. Long-lived tasks therefore need to read the current value themselves.

What was built (AWS mode only, `DATABASE_PASSWORD_SECRET_ARN`):

- `app/core/db_secret.py` reads the secret when a connection is opened, with a 60 second cache.
- `app/core/db_connect.py` opens the asyncpg connection. If the database answers "password authentication failed", it
  forces one fresh read of the secret and tries **once** more, then gives up (no retry loop).
- The task roles (API and worker) can read this one secret. The password is no longer injected into the container
  environment. Neither the password, the secret id nor the AWS error text is ever logged or put in an exception message.
- `DATABASE_PASSWORD` still works for local use. Setting both is a configuration error.

Tested with a fake secrets client that rotates the value, and against a real PostgreSQL by changing the role's password
under a live pool (`tests/test_db_secret.py`, `tests/test_pg_concurrency.py`). Not tested against real RDS rotation.

Possible future step, not built: **RDS IAM authentication** (short-lived tokens signed by the task role, no stored password).
It would remove the secret from the application path but needs per-user database grants and a token refresh on every connect.

## Network

```
Internet -> ALB (80 redirect, 443) -> api tasks (8000) -> RDS 5432, Qdrant 6333, HTTPS out
                                      worker tasks (8080 probes, none from the ALB) -> RDS, Qdrant, HTTPS out
```

- RDS and Qdrant accept connections only from the API and worker security groups.
- Egress is allowed on 443 only (plus DNS to the VPC resolver and the two data-store ports). **Plain `http://` sources cannot be
  ingested**; this was a deliberate choice over opening port 80.
- Rejected traffic is logged by VPC flow logs.
- `/api/v1/metrics` returns 403 at the load balancer; scrape it from inside the VPC (and it also requires the bearer token).
- `ALB -> api` rate limiting: uvicorn trusts `X-Forwarded-For` **only from the VPC CIDR** (`FORWARDED_ALLOW_IPS`). A wildcard
  would trust the left-most, client-supplied entry and let anyone spoof their IP past the login limiter; this is tested
  against uvicorn's actual behaviour.

## Server-side request forgery (SSRF)

The worker fetches user-supplied URLs from inside the VPC, and a Fargate task has credentials reachable at a link-local
address that security groups cannot block. Fetched text is searchable, so an unguarded fetch of the task-metadata or
instance-metadata endpoint would hand a user the task role's credentials. `app/core/url_safety.py` therefore:

- allows only `http`/`https`, no embedded credentials, ports 80 and 443;
- resolves the host **once per hop** and rejects the fetch unless **every** address is globally routable (blocks loopback,
  private, link-local, multicast and IPv4-mapped IPv6);
- **connects to that validated IP address**, sending the original `Host` header and using the real host name for the TLS
  handshake and certificate check (httpx's `sni_hostname` request extension). There is no second DNS lookup, so DNS
  rebinding (a name that answers publicly for the check and privately for the connection) gains nothing;
- re-validates and re-pins on **every redirect hop** (redirects are followed manually, at most 5);
- streams the body and stops at `WEB_MAX_BYTES` (default 5 MiB) **counted after decompression**, so a compressed bomb is
  cut off; a declared `Content-Length` above the limit is refused without reading;
- applies **one deadline** (`WEB_FETCH_TIMEOUT_S`, default 30 s) to all redirects plus the whole body, so a server that
  trickles bytes cannot hold a worker.

It is off locally (people ingest `localhost` documentation) and **required** when `ENVIRONMENT` is `staging` or `prod`;
the application refuses to start otherwise. The size and time limits apply only when the guard is on. All errors are fixed
text and never contain the URL.

Verified: unit tests drive a real httpx client through a mock transport (pinned address, Host header, TLS server name, one
lookup per hop, oversize, compression bomb, slow body, redirect chains). A one-off run against a real HTTPS site confirmed the
pinned connection completes the TLS handshake and returns the page. Not verified: behaviour against hostile servers on the
real internet. IPv6-only targets and servers that need a different SNI than the URL host are not supported.

## Qdrant access and the image it runs

- Qdrant requires an **API key** (`QDRANT__SERVICE__API_KEY`). The key lives in Secrets Manager (`docchat/<env>/qdrant-api-key`,
  value set out of band). The API and worker are given it as `QDRANT_API_KEY`; the Qdrant host reads it at start and writes it
  to a root-only file on tmpfs, never to the command line or the image. The host's role can read that one secret and pull
  from the one mirror repository, nothing else.
- The image is mirrored into ECR and pulled **by digest**; there is no public registry pull at boot and no moving tag.
- **TLS is not used. Accepted risk.** The key travels over plain HTTP between the tasks and the Qdrant host, inside private
  subnets. What the key protects against: a compromised peer on the network, or an SSRF slip that reaches Qdrant's port,
  because a request without the key is refused. What it does **not** protect against: someone who can sniff traffic inside the
  VPC. Security groups already limit who can reach port 6333 to the two task groups.
- **When to revisit:** multi-tenant use, a compliance requirement for encryption in transit, or any change that lets other
  workloads share these subnets. The usual next step is TLS on Qdrant (certificate on the host) or moving to Qdrant Cloud.

## Logging and metrics hygiene

- `app/core/logging_config.py` emits one JSON object per line with `request_id`, and scrubs values and keys: bearer tokens,
  JWTs, AWS and provider key shapes, `password=`/`token=` pairs, URL userinfo and query strings, and any field named like
  `prompt`, `content`, `text`, `body`, `url`, `file_name`, `answer`, `question`, `transcript`, `email`. Numeric token
  *counts* are kept.
- Exception messages are never logged; only the type and `file:line:function`. Stored job errors are the exception class
  name (plus the text of our own `ValueError`s with URLs removed).
- `httpx`, `urllib3`, `botocore` and similar libraries are capped at WARNING because they log full request URLs at INFO.
  This was found by scanning real container logs and is covered by a test.
- uvicorn's access log is disabled (it records query strings).
- Metric labels are bounded (`route` is the route template; providers, source types and outcomes come from fixed sets), so
  nothing user-controlled becomes a label. Tests assert an unexpected `source_type` collapses to `other`.
- Container logs from the end-to-end run were searched for the submitted URLs, document text, passwords, tokens and bearer
  strings; after the fix none appear.
- LangSmith tracing is **off** in the task definitions (`langsmith_tracing = false`) because traces contain prompts and document text.

## Data protection

- RDS: encrypted, TLS required (`rds.force_ssl`), not publicly accessible, managed master password, deletion protection.
- S3: block public access, bucket owner enforced, TLS-only policy, versioning, SSE-KMS with a customer-managed key (rotation on).
- SQS: SSE-SQS, TLS-only policies, DLQ with a redrive-allow policy.
- EBS and the Qdrant root volume are encrypted; ECR repositories scan on push and use immutable tags.
- The alarm SNS topic is encrypted with its own key.

## Container hardening

Non-root (uid 10001), read-only root filesystem with a `/tmp` volume, all capabilities dropped, `init` process, no package
manager in the image, no build tools, the embedding model baked in (starts with `--network none`), HEALTHCHECK defined.
Verified by running both images with `--read-only --cap-drop ALL` against real PostgreSQL and Qdrant containers, with a
local fake standing in for the SQS and S3 HTTP APIs (real boto3 calls; AWS itself was not involved).

## Accepted dependency advisories

`pip-audit` and Trivy are CI gates. After upgrading everything that has a fix, these remain and are ignored by ID in
`ci.yml` **on purpose**:

| Advisory | Package | Why it does not apply here |
|---|---|---|
| PYSEC-2026-1325 (CVE-2024-23342) | `ecdsa` 0.19.2 | Timing attack on ECDSA *signing*. The app signs with HS256 only. No fixed release. |
| PYSEC-2026-4298 (CVE-2026-85394) | `python-jose` 3.4.0 | Needs a public key to be accepted as an HMAC secret *when algorithms are unrestricted*. The app calls `jwt.decode(..., algorithms=[settings.jwt_algorithm])` with a random symmetric secret. No fixed release. |

### Dependency overrides in `requirements.lock` (pip will refuse to resolve it on its own)

The lock deliberately installs two versions that other packages say they do not support. A normal resolver
(`pip install -r requirements.lock` without `--no-deps`) **fails on the lock**, which is why CI, the Dockerfile and the docs
all install it with `--no-deps`.

| Package in the lock | Package that objects | What it declares | Why we override | Why it is safe here |
|---|---|---|---|---|
| `pillow 13.0.0` | `fastembed 0.9.0` | `pillow<13` | Pillow 12 has 20 HIGH/CRITICAL advisories fixed only in 13 | The cap exists for fastembed's image-embedding models. This app embeds text only. The text model was loaded and run under Pillow 13 |
| `pyasn1 0.6.4` | `python-jose 3.4.0` | `pyasn1<0.5` (newer than 0.5 is "unsupported") | 0.6.x carries newer fixes; jose's cap is stale | Only jose's non-cryptography RSA backend uses pyasn1. The app signs HS256 with the cryptography backend |

How this is verified, and kept honest:

1. `pip install --no-deps -r requirements.lock` then `pip check`: the output must list **exactly** the two conflicts above and nothing
   else. The Dockerfile enforces this with an allow-list and fails the image build on any other conflict.
2. The whole test suite runs on the lock (CI installs the lock, not `requirements.txt`), including the auth tests for HS256
   tokens and the embedding path.
3. Trivy scans both built images and `pip-audit` scans the lock on every CI run.
4. Fresh resolution of `requirements.txt` would pick the older, vulnerable Pillow. If someone regenerates the lock that way,
   the Trivy job fails; follow the steps in [deployment](deployment.md) and re-apply these two overrides.

Remove an override when the package that objects catches up (fastembed allows Pillow 13; jose is replaced).

**Follow-up, a separate change (not done here): replace `python-jose` with PyJWT.** It removes both accepted advisories, the
`ecdsa` dependency and the `pyasn1` override. It is small but it is authentication code, so it deserves its own review:
1. swap `jwt.encode/decode` and `JWTError` in `app/core/security.py`, `app/core/deps.py`, `app/api/auth.py` (about ten lines);
2. check PyJWT's stricter claim handling (`sub` must be a string, `iat`/`exp` types) against the tokens already issued;
3. extend the existing auth tests with expiry, tampering, wrong algorithm (`none`, RS256 with the HMAC secret) and a token signed by the old library;
4. change `requirements.txt`, regenerate and re-verify the lock, remove the two `--ignore-vuln` lines from CI and the pyasn1 allow-list entry;
5. release with a short overlap in which both libraries can read the same tokens, so signed-in users are not logged out.

## Not covered (be aware)

- No WAF. The load balancer is internet-facing; protection is TLS, authentication, and per-task rate limits.
- Rate limits are per task (in-process), so effective limits scale with the number of API tasks. Only login, signup and chat
  are limited; the ingest endpoints are not (existing behaviour), so an authenticated user can enqueue many jobs. Uploads are
  capped at 50 MiB each.
- Ingested sources and job status are visible to every authenticated user (existing design: sources are global, not per-user).
  Job deduplication can therefore return another user's active job id for an identical source.
- Qdrant has an API key but no TLS (see above).
- The application connects to PostgreSQL as the RDS master user (it runs DDL at startup). A least-privilege application role
  plus a separate migration role is a worthwhile follow-up.
- Secrets are not rotated automatically except the database password.
- GuardDuty, Security Hub, CloudTrail data events and AWS Config are account-level controls this repository does not manage.
- Container images are scanned, not signed.
