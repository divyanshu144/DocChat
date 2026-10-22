resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${local.name}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days to investigate and redrive
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${local.name}-ingest"
  visibility_timeout_seconds = var.queue_visibility_timeout_s
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 20     # long polling
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = local.ingest_max_attempts
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "ingest_dlq" {
  queue_url = aws_sqs_queue.ingest_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.ingest.arn]
  })
}

data "aws_iam_policy_document" "queue_tls" {
  for_each = { ingest = aws_sqs_queue.ingest.arn, dlq = aws_sqs_queue.ingest_dlq.arn }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [each.value]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "tls" {
  for_each  = { ingest = aws_sqs_queue.ingest.id, dlq = aws_sqs_queue.ingest_dlq.id }
  queue_url = each.value
  policy    = data.aws_iam_policy_document.queue_tls[each.key].json
}
