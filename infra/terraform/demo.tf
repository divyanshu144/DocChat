# Cost-lean "demo" profile. OFF by default. Turn it on for a short-lived environment you will tear down
# (docs/aws/teardown.md). It never changes the security posture: same private subnets, NAT, encryption, IAM.
#
#   worker on Fargate Spot, scaling from zero, smallest single-AZ database, 7-day logs.
#
# Deliberately NOT part of it: removing the NAT gateway (see docs/aws/cost.md for why).
locals {
  worker_min = var.demo ? 0 : var.worker_min_count

  # Scale out as soon as one message waits when the worker may be at zero; otherwise wait for a small backlog.
  scale_out_threshold      = var.demo ? 1 : 10
  scale_out_evaluation_min = var.demo ? 1 : 2

  db_instance_class = var.demo ? "db.t4g.micro" : var.db_instance_class
  db_multi_az       = var.demo ? false : var.db_multi_az
  log_retention     = var.demo ? 7 : var.log_retention_days

  # Spot can reclaim a worker mid-job, and an interrupted job still uses one delivery attempt, so allow more.
  ingest_max_attempts = var.demo ? max(var.ingest_max_attempts, 5) : var.ingest_max_attempts
}

# ---------- budget alert (created whenever an email is given, demo or not) ----------
resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
