variable "project" {
  type    = string
  default = "docchat"
}

variable "environment" {
  type        = string
  description = "dev | staging | prod"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "aws_region" {
  type        = string
  description = "Region to deploy into. No default on purpose."
}

# ---- network ----
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  type    = number
  default = 2
  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "single_nat_gateway" {
  type        = bool
  default     = true
  description = "One shared NAT gateway (cheap, single-AZ egress) vs one per AZ (resilient)."
}

variable "enable_flow_logs" {
  type    = bool
  default = true
}

# ---- edge ----
variable "alb_ingress_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "acm_certificate_arn" {
  type        = string
  default     = ""
  description = "Certificate for the HTTPS listener. Required for prod; empty gives an HTTP-only listener (dev/staging)."
}

# ---- images / sizing ----
variable "api_image_tag" {
  type        = string
  default     = "bootstrap"
  description = "Tag in the API ECR repository. Normally set by the deploy workflow, not by hand."
}

variable "worker_image_tag" {
  type    = string
  default = "bootstrap"
}

variable "cpu_architecture" {
  type        = string
  default     = "X86_64"
  description = "Must match how CI builds the images (CI builds linux/amd64)."
  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "api_min_count" {
  type    = number
  default = 2
}

variable "api_max_count" {
  type    = number
  default = 4
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 4096
}

variable "worker_min_count" {
  type    = number
  default = 1
}

variable "worker_max_count" {
  type    = number
  default = 4
}

variable "worker_concurrency" {
  type    = number
  default = 2
}

# ---- ingestion queue ----
variable "ingest_max_attempts" {
  type        = number
  default     = 3
  description = "SQS maxReceiveCount and the worker's INGEST_MAX_ATTEMPTS (kept equal on purpose)."
}

variable "queue_visibility_timeout_s" {
  type    = number
  default = 300
}

variable "upload_retention_days" {
  type        = number
  default     = 30
  description = "Uploaded originals expire after this many days. S3 is a hand-off and redrive store, not an archive."
}

# ---- database ----
variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_max_allocated_storage" {
  type    = number
  default = 100
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  type    = bool
  default = true
}

variable "db_skip_final_snapshot" {
  type    = bool
  default = false
}

# ---- Qdrant ----
variable "qdrant_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "qdrant_volume_gb" {
  type    = number
  default = 50
}

variable "qdrant_image_digest" {
  type        = string
  default     = ""
  description = "sha256:... digest of the Qdrant image in the ECR mirror repository (see docs/aws/deployment.md, Qdrant image mirror). Required when the instance is planned; empty is fine for the phase-one targeted apply."
}

variable "qdrant_snapshot_retention" {
  type    = number
  default = 14
}

# ---- observability ----
variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Optional email subscribed to the alarm topic (must be confirmed by the recipient)."
}

variable "langsmith_tracing" {
  type        = bool
  default     = false
  description = "Off by default: traces contain prompts and document text and leave AWS."
}

# ---- CI/CD ----
variable "github_repository" {
  type        = string
  default     = ""
  description = "owner/name. When set, creates an OIDC-assumable deploy role limited to the GitHub environment named like var.environment."
}

variable "github_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Existing account-wide GitHub OIDC provider. If empty and github_repository is set, one is created (only one may exist per account)."
}

# ---- cost ----
variable "demo" {
  type        = bool
  default     = false
  description = "Cost-lean profile for short-lived environments: worker on Fargate Spot scaling from zero, db.t4g.micro single-AZ, 7-day logs, more ingest attempts. Same security posture. See docs/aws/cost.md and teardown.md."
}

variable "budget_limit_usd" {
  type        = number
  default     = 50
  description = "Monthly AWS Budget limit in USD (AWS Budgets bill in the account's currency unit; USD here)."
}

variable "budget_email" {
  type        = string
  default     = ""
  description = "Email for budget alerts at 50% and 80% of actual spend and 100% of forecast. Empty creates no budget."
}
