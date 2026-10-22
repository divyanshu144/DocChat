# Customer-managed key for the document bucket: rotation on, auditable in CloudTrail, usable only
# through S3 by the two task roles (granted in iam.tf).
resource "aws_kms_key" "documents" {
  description         = "${local.name} document bucket"
  enable_key_rotation = true
  # Default key policy: the account root delegates access to IAM policies. Nothing here grants users access.
}

resource "aws_kms_alias" "documents" {
  name          = "alias/${local.name}-documents"
  target_key_id = aws_kms_key.documents.key_id
}
