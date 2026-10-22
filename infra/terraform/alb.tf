#trivy:ignore:AWS-0053 The API is the public product surface; it is protected by TLS, auth and the app-level rate limits.
resource "aws_lb" "main" {
  name                       = substr(local.name, 0, 32)
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = local.is_prod
  idle_timeout               = 120 # SSE chat streams outlive the 60 s default
}

resource "aws_lb_target_group" "api" {
  name_prefix          = "api-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  # Liveness only: a PostgreSQL or Qdrant outage must not make the ALB drain every healthy task.
  health_check {
    path                = "/api/v1/health/live"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  lifecycle { create_before_destroy = true }
}

locals {
  has_cert = var.acm_certificate_arn != ""
}

resource "aws_lb_listener" "https" {
  count             = local.has_cert ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

#trivy:ignore:AWS-0054 With a certificate this listener only redirects to HTTPS; the precondition below refuses plaintext in prod.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.has_cert ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = local.has_cert ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.api.arn
    }
  }

  lifecycle {
    precondition {
      condition     = local.has_cert || !local.is_prod
      error_message = "prod requires acm_certificate_arn: plaintext HTTP is not allowed in production."
    }
  }
}

locals {
  primary_listener_arn = local.has_cert ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

# /metrics is for in-VPC Prometheus scraping only. The bearer token is a second layer, not the first.
resource "aws_lb_listener_rule" "block_metrics" {
  listener_arn = local.primary_listener_arn
  priority     = 1

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }

  condition {
    path_pattern {
      values = ["/api/v1/metrics", "/api/v1/metrics/*"]
    }
  }
}
