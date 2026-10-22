# Secret CONTAINERS only. Values are set out of band (see docs/aws/deployment.md) so they never
# pass through Terraform state, CI logs or this repository. Tasks will not start until each has a value.
locals {
  app_secrets = ["jwt-secret-key", "groq-api-key", "metrics-bearer-token", "qdrant-api-key"]
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(local.app_secrets)
  name                    = "${var.project}/${var.environment}/${each.key}"
  description             = "DocChat ${each.key}; value set out of band"
  recovery_window_in_days = local.is_prod ? 30 : 7
}
