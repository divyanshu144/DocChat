terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70, < 6.0"
    }
  }

  # State: use a remote, encrypted, locked backend for anything real. See backend.tf.example.
  # Nothing in this repo creates or applies infrastructure; a human runs plan/apply.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  is_prod    = var.environment == "prod"
  azs        = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

data "aws_availability_zones" "available" {
  state = "available"
}
