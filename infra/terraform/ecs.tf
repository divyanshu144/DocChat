resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.services
  name              = "/${var.project}/${var.environment}/${each.key}"
  retention_in_days = local.log_retention
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

locals {
  qdrant_host = trimsuffix(aws_route53_record.qdrant.fqdn, ".")

  # Settings both services need. Names match app/core/config.py (pydantic-settings, case-insensitive).
  common_env = [
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LOG_FORMAT", value = "json" },
    { name = "DEBUG", value = "false" },
    { name = "DATABASE_HOST", value = aws_db_instance.main.address },
    { name = "DATABASE_PORT", value = tostring(aws_db_instance.main.port) },
    { name = "DATABASE_NAME", value = aws_db_instance.main.db_name },
    { name = "DATABASE_USER", value = aws_db_instance.main.username },
    { name = "DATABASE_SSL", value = "require" },
    # The password is read from Secrets Manager when a connection is opened (RDS rotates it in place every
    # 7 days), by the task role. It is deliberately not injected as an environment variable.
    { name = "DATABASE_PASSWORD_SECRET_ARN", value = aws_db_instance.main.master_user_secret[0].secret_arn },
    { name = "QDRANT_HOST", value = local.qdrant_host },
    { name = "QDRANT_PORT", value = "6333" },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = aws_s3_bucket.documents.bucket },
    { name = "S3_PREFIX", value = "uploads/" },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "RETAIN_UPLOADS", value = "true" }, # needed for DLQ redrive; the bucket lifecycle expires them
    { name = "QUEUE_BACKEND", value = "sqs" },
    { name = "SQS_QUEUE_URL", value = aws_sqs_queue.ingest.url },
    { name = "SQS_VISIBILITY_TIMEOUT_S", value = tostring(var.queue_visibility_timeout_s) },
    { name = "INGEST_MAX_ATTEMPTS", value = tostring(local.ingest_max_attempts) },
    { name = "INGEST_BLOCK_PRIVATE_URLS", value = "true" }, # SSRF guard; the app refuses to start in prod without it
    { name = "LANGSMITH_TRACING", value = tostring(var.langsmith_tracing) },
  ]

  api_env = concat(local.common_env, [
    { name = "RUN_MIGRATIONS_ON_STARTUP", value = "true" }, # serialised by a Postgres advisory lock
    # Trust X-Forwarded-For only from inside the VPC (the ALB). Never "*": that trusts the client-supplied
    # left-most entry and lets anyone spoof their IP past the per-IP rate limits.
    { name = "FORWARDED_ALLOW_IPS", value = var.vpc_cidr },
  ])

  worker_env = concat(local.common_env, [
    { name = "RUN_MIGRATIONS_ON_STARTUP", value = "false" },
    { name = "WORKER_CONCURRENCY", value = tostring(var.worker_concurrency) },
    { name = "WORKER_HTTP_PORT", value = "8080" },
  ])

  qdrant_key_secret = { name = "QDRANT_API_KEY", valueFrom = aws_secretsmanager_secret.app["qdrant-api-key"].arn }

  api_secrets = [
    { name = "JWT_SECRET_KEY", valueFrom = aws_secretsmanager_secret.app["jwt-secret-key"].arn },
    { name = "GROQ_API_KEY", valueFrom = aws_secretsmanager_secret.app["groq-api-key"].arn },
    { name = "METRICS_BEARER_TOKEN", valueFrom = aws_secretsmanager_secret.app["metrics-bearer-token"].arn },
    local.qdrant_key_secret,
  ]
  worker_secrets = [local.qdrant_key_secret]

  probe = {
    api    = "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).status == 200 else 1)"
    worker = "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=2).status == 200 else 1)"
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.key == "api" ? var.api_cpu : var.worker_cpu
  memory                   = each.key == "api" ? var.api_memory : var.worker_memory
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  volume {
    name = "tmp" # the only writable path; the root filesystem is read-only
  }

  container_definitions = jsonencode([{
    name      = each.key
    image     = "${aws_ecr_repository.service[each.key].repository_url}:${each.key == "api" ? var.api_image_tag : var.worker_image_tag}"
    essential = true

    portMappings = [{ containerPort = each.key == "api" ? 8000 : 8080, protocol = "tcp" }]

    environment = each.key == "api" ? local.api_env : local.worker_env
    secrets     = each.key == "api" ? local.api_secrets : local.worker_secrets

    readonlyRootFilesystem = true
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    linuxParameters = {
      initProcessEnabled = true # reaps zombies and forwards SIGTERM
      capabilities       = { drop = ["ALL"] }
    }
    # Grace period before SIGKILL. API: uvicorn drains for 30 s. Worker: 90 s drain + 15 s cancel + a 20 s poll.
    stopTimeout = each.key == "api" ? 60 : 120

    healthCheck = {
      command     = ["CMD", "python", "-c", local.probe[each.key]]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = each.key == "api" ? 60 : 90 # ONNX model load
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.service[each.key].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = each.key
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name                               = "api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.service["api"].arn
  desired_count                      = var.api_min_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 90
  propagate_tags                     = "SERVICE"

  # A failing rollout stops and reverts to the last steady task definition on its own.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  lifecycle {
    # The deploy workflow registers new revisions and updates the service; autoscaling owns the count.
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name                               = "worker"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.service["worker"].arn
  desired_count                      = local.worker_min
  launch_type                        = var.demo ? null : "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  propagate_tags                     = "SERVICE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Demo: Spot capacity (about 70% cheaper; can be reclaimed, which the queue's retries absorb).
  dynamic "capacity_provider_strategy" {
    for_each = var.demo ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
    }
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_ecs_cluster_capacity_providers.main]
}

# ---------- autoscaling ----------
resource "aws_appautoscaling_target" "service" {
  for_each           = local.services
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${each.key == "api" ? aws_ecs_service.api.name : aws_ecs_service.worker.name}"
  min_capacity       = each.key == "api" ? var.api_min_count : local.worker_min
  max_capacity       = each.key == "api" ? var.api_max_count : var.worker_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.service["api"].service_namespace
  scalable_dimension = aws_appautoscaling_target.service["api"].scalable_dimension
  resource_id        = aws_appautoscaling_target.service["api"].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# Worker scales on queue backlog, not CPU: idle workers are cheap, a backlog is what users feel.
resource "aws_appautoscaling_policy" "worker_out" {
  name               = "${local.name}-worker-out"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.service["worker"].service_namespace
  scalable_dimension = aws_appautoscaling_target.service["worker"].scalable_dimension
  resource_id        = aws_appautoscaling_target.service["worker"].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 120
    metric_aggregation_type = "Maximum"
    step_adjustment {
      metric_interval_lower_bound = 0
      metric_interval_upper_bound = 90
      scaling_adjustment          = 1
    }
    step_adjustment {
      metric_interval_lower_bound = 90
      scaling_adjustment          = 3
    }
  }
}

resource "aws_appautoscaling_policy" "worker_in" {
  name               = "${local.name}-worker-in"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.service["worker"].service_namespace
  scalable_dimension = aws_appautoscaling_target.service["worker"].scalable_dimension
  resource_id        = aws_appautoscaling_target.service["worker"].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 600
    metric_aggregation_type = "Maximum"
    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_backlog_high" {
  alarm_name          = "${local.name}-worker-backlog-high"
  alarm_description   = "Ingest backlog is building; scale workers out"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.ingest.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = local.scale_out_evaluation_min
  threshold           = local.scale_out_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_appautoscaling_policy.worker_out.arn]
}

resource "aws_cloudwatch_metric_alarm" "worker_backlog_clear" {
  alarm_name          = "${local.name}-worker-backlog-clear"
  alarm_description   = "No queued AND no in-flight messages for 15 minutes; scale workers in"
  evaluation_periods  = 15
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_appautoscaling_policy.worker_in.arn]

  # In-flight (not visible) messages are jobs being worked on. Counting only visible messages would let
  # scale-in stop a worker mid-job, and every redelivery uses up one of the job's attempts.
  metric_query {
    id          = "total"
    expression  = "visible + inflight"
    label       = "Queued plus in-flight messages"
    return_data = true
  }

  metric_query {
    id = "visible"
    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      dimensions  = { QueueName = aws_sqs_queue.ingest.name }
      period      = 60
      stat        = "Maximum"
    }
  }

  metric_query {
    id = "inflight"
    metric {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesNotVisible"
      dimensions  = { QueueName = aws_sqs_queue.ingest.name }
      period      = 60
      stat        = "Maximum"
    }
  }
}
