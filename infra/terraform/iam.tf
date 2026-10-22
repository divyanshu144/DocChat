data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

locals {
  services = toset(["api", "worker"])
  # Secrets each service's EXECUTION role may read (injected as env vars at container start).
  # The worker never receives the JWT key, LLM keys or the metrics token.
  secret_arns = {
    api    = [for s in aws_secretsmanager_secret.app : s.arn]
    worker = [aws_secretsmanager_secret.app["qdrant-api-key"].arn] # the only secret the worker is injected with
  }
}

# ---------- execution roles (pull image, write logs, read ONLY this service's secrets) ----------
resource "aws_iam_role" "execution" {
  for_each           = local.services
  name_prefix        = "${local.name}-${each.key}-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.services

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level permissions
  }
  statement {
    sid       = "PullOwnImage"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.service[each.key].arn]
  }
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.service[each.key].arn}:*"]
  }
  dynamic "statement" {
    for_each = length(local.secret_arns[each.key]) > 0 ? [1] : []
    content {
      sid       = "ReadOwnSecrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secret_arns[each.key]
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.services
  name     = "execution"
  role     = aws_iam_role.execution[each.key].id
  policy   = data.aws_iam_policy_document.execution[each.key].json
}

# ---------- task roles (what the application code itself may do) ----------
resource "aws_iam_role" "task" {
  for_each           = local.services
  name_prefix        = "${local.name}-${each.key}-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# Both services read the rotating DB password themselves when they open a connection (and no other secret).
data "aws_iam_policy_document" "task_db_secret" {
  statement {
    sid       = "ReadDatabasePassword"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "task_db_secret" {
  for_each = local.services
  name     = "database-secret"
  role     = aws_iam_role.task[each.key].id
  policy   = data.aws_iam_policy_document.task_db_secret.json
}

# API: store an upload, enqueue a job reference. Cannot read objects or consume the queue.
data "aws_iam_policy_document" "task_api" {
  statement {
    sid       = "PutUploads"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/uploads/*"]
  }
  statement {
    sid       = "EncryptUploads"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"] # Decrypt is needed by multipart uploads
    resources = [aws_kms_key.documents.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
  }
  statement {
    sid       = "EnqueueIngest"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingest.arn]
  }
}

# Worker: read (and optionally delete) uploads, consume the queue. Cannot upload or send.
# Neither role can touch the dead-letter queue: redrive is a deliberate operator action.
data "aws_iam_policy_document" "task_worker" {
  statement {
    sid       = "ReadUploads"
    actions   = ["s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.documents.arn}/uploads/*"]
  }
  statement {
    # Scale-in protection while a job runs (the ECS agent endpoint uses the task role).
    sid       = "ProtectOwnTaskFromScaleIn"
    actions   = ["ecs:UpdateTaskProtection", "ecs:GetTaskProtection"]
    resources = ["arn:${local.partition}:ecs:${var.aws_region}:${local.account_id}:task/${local.name}/*"]
  }
  statement {
    # Without ListBucket, S3 answers 403 (not 404) for a missing key, so an expired upload would be retried
    # as a transient failure instead of failing fast as the permanent "Object not found" it is.
    sid       = "SeeWhichUploadsExist"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["uploads/*"]
    }
  }
  statement {
    sid       = "DecryptUploads"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.documents.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
  }
  statement {
    sid = "ConsumeIngest"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.ingest.arn]
  }
}

resource "aws_iam_role_policy" "task_api" {
  name   = "api"
  role   = aws_iam_role.task["api"].id
  policy = data.aws_iam_policy_document.task_api.json
}

resource "aws_iam_role_policy" "task_worker" {
  name   = "worker"
  role   = aws_iam_role.task["worker"].id
  policy = data.aws_iam_policy_document.task_worker.json
}

# ---------- VPC flow logs ----------
resource "aws_iam_role" "flow_logs" {
  count       = var.enable_flow_logs ? 1 : 0
  name_prefix = "${local.name}-flowlogs-"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "vpc-flow-logs.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0
  name  = "write"
  role  = aws_iam_role.flow_logs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow[0].arn}:*"
    }]
  })
}

# ---------- GitHub Actions deploy role (optional, OIDC, no long-lived keys) ----------
locals {
  create_github_oidc   = var.github_repository != ""
  create_oidc_provider = local.create_github_oidc && var.github_oidc_provider_arn == ""
  github_provider_arn  = local.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  count = local.create_github_oidc ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs that run in this repository's GitHub *environment* (which carries the required reviewers).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  count              = local.create_github_oidc ? 1 : 0
  name_prefix        = "${local.name}-deploy-"
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
}

data "aws_iam_policy_document" "deploy" {
  count = local.create_github_oidc ? 1 : 0

  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level permissions
  }
  statement {
    sid = "PushImages"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages", "ecr:DescribeRepositories",
    ]
    resources = [for r in aws_ecr_repository.service : r.arn]
  }
  statement {
    sid       = "ReadAndRegisterTaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
    resources = ["*"] # ECS does not support resource-level permissions for these actions
  }
  statement {
    sid       = "UpdateOnlyThisEnvironmentsServices"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = ["arn:${local.partition}:ecs:${var.aws_region}:${local.account_id}:service/${local.name}/*"]
  }
  statement {
    sid       = "PassOnlyTheTaskRoles"
    actions   = ["iam:PassRole"]
    resources = concat([for r in aws_iam_role.execution : r.arn], [for r in aws_iam_role.task : r.arn])
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  count  = local.create_github_oidc ? 1 : 0
  name   = "deploy"
  role   = aws_iam_role.deploy[0].id
  policy = data.aws_iam_policy_document.deploy[0].json
}
