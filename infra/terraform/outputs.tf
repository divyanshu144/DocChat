output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "Point your DNS (CNAME/ALIAS) at this."
}

output "ecr_repository_urls" {
  value = { for k, r in aws_ecr_repository.service : k => r.repository_url }
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_services" {
  value = { api = aws_ecs_service.api.name, worker = aws_ecs_service.worker.name }
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "ingest_queue_url" {
  value = aws_sqs_queue.ingest.url
}

output "ingest_dlq_url" {
  value = aws_sqs_queue.ingest_dlq.url
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "rds_master_secret_arn" {
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  description = "Managed by RDS; rotate or read it with Secrets Manager, never copy it into files."
}

output "app_secret_arns" {
  value       = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
  description = "Containers to fill with `aws secretsmanager put-secret-value` (docs/aws/deployment.md)."
}

output "qdrant_instance_id" {
  value = aws_instance.qdrant.id
}

output "qdrant_volume_id" {
  value = aws_ebs_volume.qdrant.id
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}

output "deploy_role_arn" {
  value       = try(aws_iam_role.deploy[0].arn, null)
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the matching GitHub environment."
}
