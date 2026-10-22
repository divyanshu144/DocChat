resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false # only the ALB and NAT live here; they get addresses explicitly
  tags                    = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  tags              = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

locals {
  nat_count = var.single_nat_gateway ? 1 : var.az_count
}

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-${count.index}" }
}

resource "aws_nat_gateway" "main" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "${local.name}-${count.index}" }
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "private" {
  count  = var.az_count
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[var.single_nat_gateway ? 0 : count.index].id
  }
  tags = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# S3 traffic (uploads, ECR layer storage) stays on the AWS network and off the NAT gateway.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
  tags              = { Name = "${local.name}-s3" }
}

# Lock down the default security group so nothing accidentally inherits it.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_cloudwatch_log_group" "flow" {
  count             = var.enable_flow_logs ? 1 : 0
  name              = "/${var.project}/${var.environment}/vpc-flow"
  retention_in_days = local.log_retention
}

resource "aws_flow_log" "main" {
  count           = var.enable_flow_logs ? 1 : 0
  vpc_id          = aws_vpc.main.id
  traffic_type    = "REJECT" # accepted traffic is high-volume; rejects are what investigations need
  log_destination = aws_cloudwatch_log_group.flow[0].arn
  iam_role_arn    = aws_iam_role.flow_logs[0].arn
}

# ---- security groups: one per workload, no shared "allow all internal" ----
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "Public load balancer"
  vpc_id      = aws_vpc.main.id
  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  for_each          = toset(var.alb_ingress_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from allowed clients"
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each          = toset(var.alb_ingress_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "HTTP (redirected to HTTPS when a certificate is set)"
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to API tasks"
  referenced_security_group_id = aws_security_group.api.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "api" {
  name_prefix = "${local.name}-api-"
  description = "API tasks"
  vpc_id      = aws_vpc.main.id
  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "ALB only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "worker" {
  name_prefix = "${local.name}-worker-"
  description = "Ingestion worker tasks (no inbound from the internet or the ALB)"
  vpc_id      = aws_vpc.main.id
  lifecycle { create_before_destroy = true }
}

# Both task types: HTTPS out (Groq/OpenAI, AWS APIs, ECR), DNS, and the two data stores.
#trivy:ignore:AWS-0104 LLM providers, arbitrary user-supplied web pages and AWS service endpoints cannot be enumerated.
resource "aws_vpc_security_group_egress_rule" "https_out" {
  for_each          = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id = each.value
  description       = "HTTPS egress"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# HTTPS only. Plain http:// sources therefore cannot be ingested (documented limitation); the app-level SSRF
# guard (INGEST_BLOCK_PRIVATE_URLS) is what keeps fetches off private addresses, because security groups
# cannot block link-local ranges.

resource "aws_vpc_security_group_egress_rule" "dns_out" {
  for_each          = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id = each.value
  description       = "DNS to the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "udp"
}

resource "aws_vpc_security_group_egress_rule" "dns_tcp_out" {
  for_each          = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id = each.value
  description       = "DNS over TCP to the VPC resolver"
  cidr_ipv4         = var.vpc_cidr
  from_port         = 53
  to_port           = 53
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "to_rds" {
  for_each                     = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = each.value
  description                  = "PostgreSQL"
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "to_qdrant" {
  for_each                     = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = each.value
  description                  = "Qdrant"
  referenced_security_group_id = aws_security_group.qdrant.id
  from_port                    = 6333
  to_port                      = 6333
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "rds" {
  name_prefix = "${local.name}-rds-"
  description = "PostgreSQL"
  vpc_id      = aws_vpc.main.id
  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_tasks" {
  for_each                     = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = aws_security_group.rds.id
  description                  = "From ${each.key} tasks"
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "qdrant" {
  name_prefix = "${local.name}-qdrant-"
  description = "Qdrant vector store"
  vpc_id      = aws_vpc.main.id
  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_ingress_rule" "qdrant_from_tasks" {
  for_each                     = { api = aws_security_group.api.id, worker = aws_security_group.worker.id }
  security_group_id            = aws_security_group.qdrant.id
  description                  = "From ${each.key} tasks"
  referenced_security_group_id = each.value
  from_port                    = 6333
  to_port                      = 6333
  ip_protocol                  = "tcp"
}

#trivy:ignore:AWS-0104 Image pull, OS package repositories and SSM endpoints; no inbound path exists to this host from the internet.
resource "aws_vpc_security_group_egress_rule" "qdrant_https_out" {
  security_group_id = aws_security_group.qdrant.id
  description       = "Container image pull, package repos, SSM"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
