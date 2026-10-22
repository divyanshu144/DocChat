# Single-node Qdrant on EC2 with a dedicated encrypted EBS data volume and daily snapshots.
# Why not Fargate: Qdrant needs a block device (network file systems such as EFS are not supported
# for its storage). Why not replace it: it is the retrieval store the whole app is built around.
# Limitation: one node, no replication, no TLS. Access needs an API key plus network isolation. See docs/aws/security.md.

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.cpu_architecture == "ARM64" ? "arm64" : "x86_64"}"
}

resource "aws_iam_role" "qdrant" {
  name_prefix        = "${local.name}-qdrant-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# Session Manager instead of SSH: no inbound ports, no keys, every session auditable.
resource "aws_iam_role_policy_attachment" "qdrant_ssm" {
  role       = aws_iam_role.qdrant.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Only what boot needs: pull from the mirror repository, and read the one Qdrant key secret.
data "aws_iam_policy_document" "qdrant_boot" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level permissions
  }
  statement {
    sid       = "PullMirror"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.qdrant.arn]
  }
  statement {
    sid       = "ReadApiKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app["qdrant-api-key"].arn]
  }
}

resource "aws_iam_role_policy" "qdrant_boot" {
  name   = "boot"
  role   = aws_iam_role.qdrant.id
  policy = data.aws_iam_policy_document.qdrant_boot.json
}

resource "aws_iam_instance_profile" "qdrant" {
  name_prefix = "${local.name}-qdrant-"
  role        = aws_iam_role.qdrant.name
}

resource "aws_instance" "qdrant" {
  ami                    = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type          = var.qdrant_instance_type
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.qdrant.id]
  iam_instance_profile   = aws_iam_instance_profile.qdrant.name
  ebs_optimized          = true
  monitoring             = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # containers on the host cannot reach instance credentials
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 12
  }

  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker

    DEV=/dev/sdf
    # Wait for the data volume, create a filesystem only if it has none, mount by label.
    for i in $(seq 1 60); do [ -b "$DEV" ] || [ -b /dev/nvme1n1 ] && break; sleep 2; done
    [ -b "$DEV" ] || DEV=/dev/nvme1n1
    blkid "$DEV" >/dev/null 2>&1 || mkfs.xfs -L qdrantdata "$DEV"
    mkdir -p /data/qdrant
    grep -q qdrantdata /etc/fstab || echo "LABEL=qdrantdata /data/qdrant xfs defaults,nofail 0 2" >> /etc/fstab
    mount -a

    # Runs before every start: sign in to ECR, pull the pinned image, and write the API key (read from Secrets
    # Manager) to a root-only file on tmpfs. The key is never on the command line or in the image.
    cat > /usr/local/bin/qdrant-prestart.sh <<'SCRIPT'
    #!/bin/bash
    set -euo pipefail
    aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${split("/", aws_ecr_repository.qdrant.repository_url)[0]} > /dev/null
    docker pull ${aws_ecr_repository.qdrant.repository_url}@${var.qdrant_image_digest}
    umask 077
    printf 'QDRANT__SERVICE__API_KEY=%s\n' "$(aws secretsmanager get-secret-value --region ${var.aws_region} --secret-id ${aws_secretsmanager_secret.app["qdrant-api-key"].arn} --query SecretString --output text)" > /run/qdrant.env
    SCRIPT
    chmod 700 /usr/local/bin/qdrant-prestart.sh

    cat > /etc/systemd/system/qdrant.service <<'UNIT'
    [Unit]
    Description=Qdrant
    After=docker.service data-qdrant.mount
    Requires=docker.service

    [Service]
    Restart=always
    RestartSec=5
    ExecStartPre=/usr/local/bin/qdrant-prestart.sh
    ExecStartPre=-/usr/bin/docker rm -f qdrant
    ExecStart=/usr/bin/docker run --name qdrant --rm -p 6333:6333 --env-file /run/qdrant.env -v /data/qdrant:/qdrant/storage ${aws_ecr_repository.qdrant.repository_url}@${var.qdrant_image_digest}
    ExecStop=/usr/bin/docker stop -t 30 qdrant

    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload
    systemctl enable --now qdrant
  EOT

  lifecycle {
    precondition {
      condition     = can(regex("^sha256:[0-9a-f]{64}$", var.qdrant_image_digest))
      error_message = "qdrant_image_digest must be set to the sha256 digest of the mirrored Qdrant image (docs/aws/deployment.md)."
    }
    # Editing user_data or a newer AMI must never silently replace the node that holds the index.
    # Upgrade deliberately; see docs/aws/deployment.md.
    ignore_changes = [ami, user_data]
  }

  tags = { Name = "${local.name}-qdrant" }
}

resource "aws_ebs_volume" "qdrant" {
  availability_zone = aws_instance.qdrant.availability_zone
  size              = var.qdrant_volume_gb
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "${local.name}-qdrant-data", Backup = "qdrant-${local.name}" }
}

resource "aws_volume_attachment" "qdrant" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.qdrant.id
  instance_id = aws_instance.qdrant.id
}

# Stable name so tasks do not need redeploying if the node is replaced.
resource "aws_route53_zone" "internal" {
  name = "${var.environment}.${var.project}.internal"
  vpc {
    vpc_id = aws_vpc.main.id
  }
}

resource "aws_route53_record" "qdrant" {
  zone_id = aws_route53_zone.internal.zone_id
  name    = "qdrant.${aws_route53_zone.internal.name}"
  type    = "A"
  ttl     = 30
  records = [aws_instance.qdrant.private_ip]
}

# Daily crash-consistent EBS snapshots.
resource "aws_iam_role" "dlm" {
  name_prefix = "${local.name}-dlm-"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "dlm.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "qdrant" {
  description        = "Daily snapshots of the Qdrant data volume"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags    = { Backup = "qdrant-${local.name}" }

    schedule {
      name = "daily"
      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["02:00"]
      }
      retain_rule { count = var.qdrant_snapshot_retention }
      copy_tags = true
    }
  }
}
