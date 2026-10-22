resource "aws_ecr_repository" "service" {
  for_each             = toset(["api", "worker"])
  name                 = "${var.project}/${var.environment}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # a deployed tag can never silently change; rollback by tag is exact

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
        action       = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the most recent 30 tagged images (rollback window)"
        selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
        action       = { type = "expire" }
      }
    ]
  })
}

# Mirror of the upstream Qdrant image, so the instance never pulls from a public registry at boot and runs exactly
# the image you reviewed. Filled by a person (docs/aws/deployment.md); the instance pulls it by digest.
resource "aws_ecr_repository" "qdrant" {
  name                 = "${var.project}/${var.environment}/qdrant-mirror"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}
