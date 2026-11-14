resource "aws_cloudwatch_log_group" "cron" {
  name              = "/aws/lambda/${local.name_prefix}-cron"
  retention_in_days = 30

  tags = { SourceResourceId = "rr-cron" }
}

resource "aws_sqs_queue" "cron_dlq" {
  name                    = "${local.name_prefix}-cron-dlq"
  sqs_managed_sse_enabled = true

  tags = { SourceResourceId = "rr-cron" }
}

resource "aws_sqs_queue" "schedule_dlq" {
  name                    = "${local.name_prefix}-cron-schedule-dlq"
  sqs_managed_sse_enabled = true

  tags = { SourceResourceId = "rr-cron" }
}

resource "aws_iam_role" "cron_lambda" {
  name = "${local.name_prefix}-cron-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { SourceResourceId = "rr-cron" }
}

resource "aws_iam_role_policy" "cron_lambda" {
  name = "write-logs-and-dead-letters"
  role = aws_iam_role.cron_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.cron.arn}:*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.cron_dlq.arn]
      },
    ]
  })
}

resource "aws_lambda_function" "cron" {
  function_name                  = "${local.name_prefix}-cron"
  role                           = aws_iam_role.cron_lambda.arn
  package_type                   = "Image"
  image_uri                      = var.cron_image
  architectures                  = ["x86_64"]
  timeout                        = var.cron_timeout_seconds
  memory_size                    = var.cron_memory_mb
  reserved_concurrent_executions = 1


  dead_letter_config {
    target_arn = aws_sqs_queue.cron_dlq.arn
  }

  tags       = { SourceResourceId = "rr-cron" }
  depends_on = [aws_cloudwatch_log_group.cron, aws_iam_role_policy.cron_lambda]
}

resource "aws_iam_role" "scheduler" {
  name = "${local.name_prefix}-cron-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { SourceResourceId = "rr-cron" }
}

resource "aws_iam_role_policy" "scheduler" {
  name = "invoke-cron-function"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.cron.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.schedule_dlq.arn]
      },
    ]
  })
}

resource "aws_scheduler_schedule" "cron" {
  name                         = "${local.name_prefix}-cron"
  schedule_expression          = var.cron_schedule_expression
  schedule_expression_timezone = var.cron_time_zone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.cron.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }

    dead_letter_config {
      arn = aws_sqs_queue.schedule_dlq.arn
    }
  }
}
