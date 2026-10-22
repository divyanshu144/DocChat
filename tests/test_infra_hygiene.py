"""Static guardrails over infra/, docker/ and .github/. No AWS, no Terraform binary needed.

These encode promises made in docs/aws/security.md so an innocent-looking edit cannot quietly break them.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TF = ROOT / "infra" / "terraform"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def tf_files():
    return sorted(TF.glob("*.tf"))


def infra_text_files():
    files = [*TF.glob("*.tf"), *TF.glob("*.example"), *TF.glob("environments/*"),
             *(ROOT / ".github").rglob("*.y*ml"), ROOT / "docker" / "Dockerfile"]
    return [f for f in files if f.is_file()]


def code(path: Path) -> str:
    """File content without `#` comments (explanations may mention the very words we forbid)."""
    return re.sub(r"(?m)#.*$", "", read(path))


def block(text: str, header: str) -> str:
    """Return the body of the first top-level HCL block that starts with `header`."""
    start = text.index(header)
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    raise AssertionError(f"unbalanced block {header}")


def test_the_files_exist():
    assert len(tf_files()) >= 10
    assert (ROOT / "docker" / "Dockerfile").exists()


@pytest.mark.parametrize("path", infra_text_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_account_ids_keys_or_secrets_committed(path):
    text = read(path)
    assert not re.search(r"\b\d{12}\b", text), "12-digit AWS account id"
    assert not re.search(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", text), "AWS access key id"
    assert "-----BEGIN" not in text, "private key material"
    assert not re.search(r"(?i)\b(password|secret|token|api_key)\s*=\s*\"[^\"$]{6,}\"", text), "literal credential"


def test_nothing_in_the_repo_applies_infrastructure():
    for path in infra_text_files():
        text = code(path)
        # `terraform apply` is a human action; CI/CD only formats, validates and scans.
        assert not re.search(r"terraform\s+apply|\bapply\s+-auto-approve|-auto-approve", text), path


def test_forwarded_ips_trusts_the_vpc_cidr_never_a_wildcard():
    ecs = read(TF / "ecs.tf")
    assert re.search(r'name\s*=\s*"FORWARDED_ALLOW_IPS",\s*value\s*=\s*var\.vpc_cidr', ecs)
    assert "FORWARDED_ALLOW_IPS\", value = \"*\"" not in ecs and '"*"' not in block(ecs, "api_env")
    assert "forwarded-allow-ips" not in read(ROOT / "docker" / "Dockerfile")


def test_uvicorn_wildcard_trust_is_spoofable_but_cidr_is_not():
    """Documents WHY the previous test matters; fails if uvicorn changes semantics."""
    from uvicorn.middleware.proxy_headers import _TrustedHosts

    spoofed = "6.6.6.6, 203.0.113.9"  # client sent 6.6.6.6; the ALB appended the real address
    assert _TrustedHosts("*").get_trusted_client_address(spoofed)[0] == "6.6.6.6"
    assert _TrustedHosts("10.20.0.0/16").get_trusted_client_address(spoofed)[0] == "203.0.113.9"


def test_task_definitions_are_hardened():
    ecs = read(TF / "ecs.tf")
    for needle in ('readonlyRootFilesystem = true', 'drop = ["ALL"]', "initProcessEnabled = true",
                   'name = "tmp"'):
        assert needle.replace(" ", "") in ecs.replace(" ", ""), needle
    assert "privileged" not in ecs
    assert 'INGEST_BLOCK_PRIVATE_URLS", value = "true"' in ecs
    assert 'LANGSMITH_TRACING", value = tostring(var.langsmith_tracing)' in ecs
    assert 'default     = false' in block(read(TF / "variables.tf"), 'variable "langsmith_tracing"')


def test_services_roll_back_on_failure_and_are_independent():
    ecs = read(TF / "ecs.tf")
    for svc in ('resource "aws_ecs_service" "api"', 'resource "aws_ecs_service" "worker"'):
        body = block(ecs, svc)
        assert "enable   = true" in body.replace("  ", " ").replace(" = ", "   = ") or "enable" in body
        assert "rollback = true" in body
        assert "ignore_changes = [task_definition, desired_count]" in body
    assert "load_balancer" in block(ecs, 'resource "aws_ecs_service" "api"')
    assert "load_balancer" not in block(ecs, 'resource "aws_ecs_service" "worker"')
    families = re.findall(r'family\s*=\s*"\$\{local\.name\}-\$\{each\.key\}"', ecs)
    assert families, "one task definition family per service"


def test_iam_is_separated_per_service():
    iam = read(TF / "iam.tf")
    api = block(iam, 'data "aws_iam_policy_document" "task_api"')
    worker = block(iam, 'data "aws_iam_policy_document" "task_worker"')

    assert "sqs:SendMessage" in api and "s3:PutObject" in api
    for forbidden in ("sqs:ReceiveMessage", "sqs:DeleteMessage", "s3:GetObject", "s3:DeleteObject"):
        assert forbidden not in api, f"API role must not have {forbidden}"

    assert "sqs:ReceiveMessage" in worker and "sqs:DeleteMessage" in worker and "s3:GetObject" in worker
    for forbidden in ("sqs:SendMessage", "s3:PutObject", "kms:GenerateDataKey"):
        assert forbidden not in worker, f"worker role must not have {forbidden}"

    # Neither task role may touch the dead-letter queue; redrive is an operator action.
    assert "ingest_dlq" not in api and "ingest_dlq" not in worker

    # The worker execution role is injected with the Qdrant key only; the DB secret is read by the task roles,
    # and nothing for the worker may name the JWT / LLM / metrics secrets.
    assert re.search(r'worker\s*=\s*\[aws_secretsmanager_secret\.app\["qdrant-api-key"\]\.arn\]', iam)
    assert "jwt-secret-key" not in iam and "groq-api-key" not in iam
    db_secret = block(iam, 'data "aws_iam_policy_document" "task_db_secret"')
    assert "master_user_secret" in db_secret and "aws_secretsmanager_secret.app" not in db_secret
    assert "secretsmanager" not in api and "secretsmanager" not in worker
    assert 'for_each = local.services' in block(iam, 'resource "aws_iam_role_policy" "task_db_secret"')

    for text in (iam,):
        assert not re.search(r'actions\s*=\s*\["\*"\]', text)
        assert not re.search(r'Action\s*=\s*"\*"', text)


def test_no_wildcard_resources_except_documented_aws_limitations():
    iam = read(TF / "iam.tf")
    allowed_comments = ("does not support resource-level", "do not support resource-level")
    for match in re.finditer(r'resources\s*=\s*\["\*"\][^\n]*', iam):
        assert any(c in match.group(0) for c in allowed_comments), match.group(0)


def test_deploy_role_is_scoped_to_the_github_environment():
    iam = read(TF / "iam.tf")
    assert 'token.actions.githubusercontent.com:sub' in iam
    assert "environment:${var.environment}" in iam
    assert 'iam:PassedToService' in iam


def test_data_stores_are_private_encrypted_and_not_publicly_reachable():
    rds, s3, qd = read(TF / "rds.tf"), read(TF / "s3.tf"), read(TF / "qdrant.tf")
    assert "publicly_accessible    = false" in rds and "storage_encrypted     = true" in rds
    rds_code = code(TF / "rds.tf")
    assert "manage_master_user_password = true" in rds_code
    assert "password" not in re.sub(r"manage_master_user_password", "", rds_code)
    assert 'value = "1"' in rds and "rds.force_ssl" in rds
    for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        assert re.search(rf"{flag}\s*=\s*true", s3)
    assert "aws:SecureTransport" in s3 and "aws:kms" in s3
    assert 'http_tokens                 = "required"' in qd and "encrypted" in qd
    assert "ignore_changes = [ami, user_data]" in qd
    # The Qdrant image comes from our own ECR mirror, by digest, never from a public registry or a moving tag.
    qd_code = code(TF / "qdrant.tf")
    assert "${aws_ecr_repository.qdrant.repository_url}@${var.qdrant_image_digest}" in qd_code
    assert "docker.io" not in qd_code and ":latest" not in qd_code
    assert "sha256:[0-9a-f]{64}" in qd_code
    assert "--env-file /run/qdrant.env" in qd_code and "umask 077" in qd_code


def test_qdrant_api_key_is_a_secret_container_and_reaches_only_what_needs_it():
    secrets, iam, qd = code(TF / "secrets.tf"), code(TF / "iam.tf"), code(TF / "qdrant.tf")
    assert '"qdrant-api-key"' in secrets and "secret_version" not in secrets
    boot = block(qd, 'data "aws_iam_policy_document" "qdrant_boot"')
    assert boot.count("secretsmanager:GetSecretValue") == 1 and 'app["qdrant-api-key"]' in boot
    for allowed in ("ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"):
        assert allowed in boot
    for forbidden in ("ecr:PutImage", "ecr:InitiateLayerUpload", "s3:", "sqs:"):
        assert forbidden not in boot
    assert "aws_ecr_repository.qdrant.arn" in boot
    ecs = code(TF / "ecs.tf")
    assert 'name = "QDRANT_API_KEY"' in ecs and "QDRANT_API_KEY" not in iam


def test_security_groups_follow_the_documented_flow():
    net = read(TF / "network.tf")
    # Data stores accept traffic only from the task security groups.
    for sg in ("rds", "qdrant"):
        ingress = re.findall(rf'resource "aws_vpc_security_group_ingress_rule" "{sg}_from_tasks" \{{(.*?)\n\}}', net, re.S)
        assert ingress and "referenced_security_group_id" in ingress[0] and "cidr_ipv4" not in ingress[0]
    assert "worker_http_out" not in net, "plain-HTTP egress was deliberately removed"


def test_metrics_endpoint_is_blocked_at_the_load_balancer():
    alb = read(TF / "alb.tf")
    rule = block(alb, 'resource "aws_lb_listener_rule" "block_metrics"')
    assert "/api/v1/metrics" in rule and "403" in rule
    assert "local.is_prod" in alb and "acm_certificate_arn" in alb


def test_health_checks_use_liveness_not_dependency_readiness():
    alb = read(TF / "alb.tf")
    assert '/api/v1/health/live' in block(alb, 'resource "aws_lb_target_group" "api"')


def test_queue_retries_match_the_worker_and_use_a_dlq():
    sqs, ecs = read(TF / "sqs.tf"), read(TF / "ecs.tf")
    assert "maxReceiveCount     = local.ingest_max_attempts" in sqs
    assert 'name = "INGEST_MAX_ATTEMPTS", value = tostring(local.ingest_max_attempts)' in ecs
    assert "sqs_managed_sse_enabled   = true" in sqs and "redrive_policy" in sqs
    assert "dlq_not_empty" in read(TF / "cloudwatch.tf")


def test_dockerfile_is_production_shaped():
    df = read(ROOT / "docker" / "Dockerfile")
    assert "USER 10001:10001" in df
    assert "COPY . " not in df and "COPY app ./app" in df
    assert "FROM runtime AS api" in df and "FROM runtime AS worker" in df
    assert df.count("HEALTHCHECK") == 2
    assert "pip uninstall -y pip" in df
    assert "requirements.lock" in df and "requirements.txt" not in re.sub(r"#.*", "", df)
    assert "latest" not in re.sub(r"#.*", "", df)


def test_lock_file_excludes_dev_tools_and_pins_everything():
    lock = [ln for ln in read(ROOT / "requirements.lock").splitlines() if ln and not ln.startswith("#")]
    names = {ln.split("==")[0].lower() for ln in lock}
    assert all("==" in ln for ln in lock)
    assert not names & {"pytest", "pytest-asyncio", "aiosqlite", "ruff"}
    assert {"boto3", "fastapi", "uvicorn", "qdrant-client", "asyncpg"} <= names


def test_workflows_pin_third_party_actions_by_sha_and_run_least_privilege():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = read(wf)
        assert re.search(r"^permissions:\n\s+contents: read", text, re.M), wf
        for action in re.findall(r"uses:\s*([^\s@]+)@(\S+)", text):
            name, ref = action
            if name.startswith("./"):
                continue
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{wf.name}: {name} is not pinned to a commit SHA"
    deploy = read(ROOT / ".github" / "workflows" / "deploy.yml")
    assert "id-token: write" in deploy and "environment: ${{ inputs.environment }}" in deploy
    assert "AWS_SECRET_ACCESS_KEY" not in deploy and "AWS_ACCESS_KEY_ID" not in deploy


def test_ci_covers_code_containers_and_infrastructure():
    ci = read(ROOT / ".github" / "workflows" / "ci.yml")
    for needle in ("ruff check", "pytest", "pip-audit", "docker build", "trivy", "TRIVY_IMAGE", "fmt -check",
                   "validate", "gitleaks", "--target"):
        assert needle in ci or needle.lower() in ci.lower(), needle


def test_example_tfvars_contain_no_real_values():
    for example in (TF / "environments").glob("*.example"):
        text = read(example)
        assert "REPLACE_WITH" in text or "dev" in example.name
        assert "@" not in re.sub(r"REPLACE_WITH_ONCALL_EMAIL", "", text)


def test_scale_in_counts_in_flight_messages_not_only_visible_ones():
    ecs = read(TF / "ecs.tf")
    alarm = block(ecs, 'resource "aws_cloudwatch_metric_alarm" "worker_backlog_clear"')
    assert "ApproximateNumberOfMessagesNotVisible" in alarm and "ApproximateNumberOfMessagesVisible" in alarm
    assert 'expression  = "visible + inflight"' in alarm


def test_only_the_worker_may_protect_its_task_and_only_within_this_cluster():
    iam = read(TF / "iam.tf")
    api = block(iam, 'data "aws_iam_policy_document" "task_api"')
    worker = block(iam, 'data "aws_iam_policy_document" "task_worker"')
    assert "ecs:UpdateTaskProtection" in worker and "ecs:UpdateTaskProtection" not in api
    assert ":task/${local.name}/*" in worker


def test_database_password_is_read_at_connect_time_not_injected_as_an_env_secret():
    ecs = read(TF / "ecs.tf")
    assert 'name = "DATABASE_PASSWORD_SECRET_ARN"' in ecs
    assert '"DATABASE_PASSWORD"' not in ecs.replace("DATABASE_PASSWORD_SECRET_ARN", "")
    assert "worker_secrets = [local.qdrant_key_secret]" in ecs


def test_ci_runs_the_postgres_tests_against_a_real_service_and_cannot_skip_them():
    ci = read(ROOT / ".github" / "workflows" / "ci.yml")
    assert "image: postgres:16" in ci and "pytest -m pg" in ci
    assert 'REQUIRE_PG: "1"' in ci and "TEST_DATABASE_URL" in ci


def test_deploy_pushes_the_scanned_image_and_rolls_out_by_digest():
    deploy = read(ROOT / ".github" / "workflows" / "deploy.yml")
    ci = read(ROOT / ".github" / "workflows" / "ci.yml")
    assert "docker build" not in deploy, "deploy must not rebuild; it pushes what CI scanned"
    assert "export_images: true" in deploy and "needs: checks" in deploy
    assert "docker load" in deploy and "image id differs from the scanned image" in deploy
    assert '"$uri@$digest"' in deploy and "$SHA" in deploy
    # CI keeps the image only when asked, and records the id it scanned.
    assert "inputs.export_images" in ci and "image.id" in ci and "upload-artifact" in ci


def test_demo_profile_is_off_by_default_and_only_changes_cost_settings():
    variables, demo = code(TF / "variables.tf"), code(TF / "demo.tf")
    assert re.search(r'variable "demo"\s*\{[^}]*default\s*=\s*false', variables, re.S)
    # It must never reach networking, IAM, encryption, storage or secrets.
    for name in ("network.tf", "iam.tf", "s3.tf", "kms.tf", "secrets.tf", "alb.tf", "qdrant.tf"):
        assert "var.demo" not in code(TF / name) and "local.worker_min" not in code(TF / name), name
    assert "assign_public_ip = false" in code(TF / "ecs.tf") and "assign_public_ip = true" not in code(TF / "ecs.tf")
    assert "aws_nat_gateway" in code(TF / "network.tf")  # the NAT-less variant was deliberately not built
    assert 'var.demo ? "db.t4g.micro" : var.db_instance_class' in demo
    assert "var.demo ? false : var.db_multi_az" in demo and "var.demo ? 7 : var.log_retention_days" in demo
    assert "var.demo ? max(var.ingest_max_attempts, 5)" in demo


def test_demo_worker_uses_spot_and_scales_from_a_single_message():
    ecs, demo, cw = code(TF / "ecs.tf"), code(TF / "demo.tf"), code(TF / "cloudwatch.tf")
    svc = block(ecs, 'resource "aws_ecs_service" "worker"')
    assert "FARGATE_SPOT" in svc and "var.demo ? [1] : []" in svc and 'var.demo ? null : "FARGATE"' in svc
    assert "FARGATE_SPOT" not in block(ecs, 'resource "aws_ecs_service" "api"')
    assert "var.demo ? 0 : var.worker_min_count" in demo and "var.demo ? 1 : 10" in demo
    out = block(ecs, 'resource "aws_cloudwatch_metric_alarm" "worker_backlog_high"')
    assert "local.scale_out_threshold" in out
    # scaled-to-zero must not page: the running-tasks alarm skips services whose minimum is 0
    assert "if v > 0" in cw


def test_budget_alert_is_created_only_with_an_email_and_has_forecast_and_actual_notifications():
    demo = code(TF / "demo.tf")
    budget = block(demo, 'resource "aws_budgets_budget" "monthly"')
    assert 'var.budget_email == "" ? 0 : 1' in budget
    assert budget.count("notification {") == 3 and "FORECASTED" in budget and "ACTUAL" in budget


def test_every_log_metric_filter_has_an_alarm():
    cw = code(TF / "cloudwatch.tf")
    for metric in re.findall(r'metric_transformation \{\s*name\s*=\s*"(\w+)"', cw):
        assert re.search(rf'metric_name\s*=\s*("{metric}"|aws_cloudwatch_log_metric_filter\.\w+\.metric_transformation\[0\]\.name)', cw), metric
    alarm = block(cw, 'resource "aws_cloudwatch_metric_alarm" "ingest_dead_lettered"')
    assert "ingest_dead_letter.metric_transformation[0].name" in alarm and "alarm_actions" in alarm
