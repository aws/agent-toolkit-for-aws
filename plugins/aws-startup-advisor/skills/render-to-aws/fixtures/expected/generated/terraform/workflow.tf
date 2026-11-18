variable "workflow_log_retention_days" {
  description = "CloudWatch retention in days for Workflow execution logs and task logs."
  type        = number
  default     = 30
  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.workflow_log_retention_days)
    error_message = "workflow_log_retention_days must be a CloudWatch Logs retention value."
  }
}
variable "workflow_tracing_enabled" {
  description = "Enable AWS X-Ray tracing on the state machines."
  type        = bool
  default     = false
}
variable "workflow_alarm_actions" {
  description = "ARNs notified when a Workflow alarm changes state; empty keeps alarms visible in CloudWatch only."
  type        = list(string)
  default     = []
}
variable "rr_workflow_task_package_path" {
  description = "Path to the reviewed deployment package for Render source resource rr-workflow-task; this pack contains no function source."
  type        = string
  validation {
    condition     = length(var.rr_workflow_task_package_path) > 0
    error_message = "rr_workflow_task_package_path must be a non-empty path."
  }
}
variable "rr_workflow_task_runtime" {
  description = "Lambda runtime for Render source resource rr-workflow-task."
  type        = string
  validation {
    condition     = length(var.rr_workflow_task_runtime) > 0
    error_message = "rr_workflow_task_runtime must be a non-empty Lambda runtime identifier."
  }
}
variable "rr_workflow_task_handler" {
  description = "Lambda handler for Render source resource rr-workflow-task."
  type        = string
  validation {
    condition     = length(var.rr_workflow_task_handler) > 0
    error_message = "rr_workflow_task_handler must be a non-empty handler."
  }
}
variable "rr_workflow_task_memory_mb" {
  description = "Lambda memory in MB for Render source resource rr-workflow-task; Render compute plans are not converted."
  type        = number
  validation {
    condition     = var.rr_workflow_task_memory_mb >= 128 && var.rr_workflow_task_memory_mb <= 10240 && floor(var.rr_workflow_task_memory_mb) == var.rr_workflow_task_memory_mb
    error_message = "rr_workflow_task_memory_mb must be a whole number from 128 to 10240."
  }
}
resource "aws_cloudwatch_log_group" "rr_workflow_task" {
  name              = "/aws/lambda/${local.name_prefix}-rr-workflow-task"
  retention_in_days = var.workflow_log_retention_days
  tags = {
    SourceResourceId = "rr-workflow-task"
  }
}
resource "aws_iam_role" "rr_workflow_task" {
  name = "${local.name_prefix}-rr-workflow-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
  tags = {
    SourceResourceId = "rr-workflow-task"
  }
}
resource "aws_iam_role_policy" "rr_workflow_task" {
  name = "write-own-logs"
  role = aws_iam_role.rr_workflow_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.rr_workflow_task.arn}:*"]
      },
    ]
  })
}
resource "aws_lambda_function" "rr_workflow_task" {
  function_name    = "${local.name_prefix}-rr-workflow-task"
  role             = aws_iam_role.rr_workflow_task.arn
  runtime          = var.rr_workflow_task_runtime
  handler          = var.rr_workflow_task_handler
  filename         = var.rr_workflow_task_package_path
  source_code_hash = filebase64sha256(var.rr_workflow_task_package_path)
  memory_size      = var.rr_workflow_task_memory_mb
  timeout          = 300
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.rr_workflow_task.name
  }
  tags = {
    SourceResourceId = "rr-workflow-task"
  }
  depends_on = [aws_iam_role_policy.rr_workflow_task]
}
resource "aws_cloudwatch_log_group" "rr_workflow" {
  name              = "/aws/vendedlogs/states/${local.name_prefix}-rr-workflow"
  retention_in_days = var.workflow_log_retention_days
  tags = {
    SourceResourceId = "rr-workflow"
  }
}
resource "aws_iam_role" "rr_workflow" {
  name = "${local.name_prefix}-rr-workflow"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
  tags = {
    SourceResourceId = "rr-workflow"
  }
}
resource "aws_iam_role_policy" "rr_workflow_tasks" {
  name = "invoke-declared-tasks"
  role = aws_iam_role.rr_workflow.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.rr_workflow_task.arn]
      },
    ]
  })
}
data "aws_iam_policy_document" "rr_workflow_service" {
  statement {
    sid       = "DeliverExecutionLogs"
    actions   = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
    resources = ["*"]
  }
  dynamic "statement" {
    for_each = var.workflow_tracing_enabled ? [1] : []
    content {
      sid       = "WriteXRayTraces"
      actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
      resources = ["*"]
    }
  }
}
resource "aws_iam_role_policy" "rr_workflow_service" {
  name   = "service-integration-requirements"
  role   = aws_iam_role.rr_workflow.id
  policy = data.aws_iam_policy_document.rr_workflow_service.json
}
resource "aws_sfn_state_machine" "rr_workflow" {
  name     = "${local.name_prefix}-rr-workflow"
  role_arn = aws_iam_role.rr_workflow.arn
  type     = "STANDARD"
  definition = jsonencode({
    Comment = "Generated from Render Workflow rr-workflow"
    StartAt = "rr_workflow_task"
    States = {
      rr_workflow_task = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = aws_lambda_function.rr_workflow_task.arn
          Payload = {
            "input.$"     = "$"
            "TaskToken.$" = "$$.Task.Token"
          }
        }
        TimeoutSeconds = 3600
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2.0
          },
        ]
        End = true
      }
    }
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.rr_workflow.arn}:*"
    include_execution_data = false
    level                  = "ALL"
  }
  tracing_configuration {
    enabled = var.workflow_tracing_enabled
  }
  tags = {
    SourceResourceId = "rr-workflow"
  }
  depends_on = [aws_iam_role_policy.rr_workflow_tasks, aws_iam_role_policy.rr_workflow_service]
}
resource "aws_cloudwatch_metric_alarm" "rr_workflow_executionsfailed" {
  alarm_name  = "${local.name_prefix}-rr-workflow-ExecutionsFailed"
  namespace   = "AWS/States"
  metric_name = "ExecutionsFailed"
  dimensions = {
    StateMachineArn = aws_sfn_state_machine.rr_workflow.arn
  }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.workflow_alarm_actions
  tags = {
    SourceResourceId = "rr-workflow"
  }
}
resource "aws_cloudwatch_metric_alarm" "rr_workflow_executionstimedout" {
  alarm_name  = "${local.name_prefix}-rr-workflow-ExecutionsTimedOut"
  namespace   = "AWS/States"
  metric_name = "ExecutionsTimedOut"
  dimensions = {
    StateMachineArn = aws_sfn_state_machine.rr_workflow.arn
  }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.workflow_alarm_actions
  tags = {
    SourceResourceId = "rr-workflow"
  }
}
resource "aws_cloudwatch_metric_alarm" "rr_workflow_executionsaborted" {
  alarm_name  = "${local.name_prefix}-rr-workflow-ExecutionsAborted"
  namespace   = "AWS/States"
  metric_name = "ExecutionsAborted"
  dimensions = {
    StateMachineArn = aws_sfn_state_machine.rr_workflow.arn
  }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.workflow_alarm_actions
  tags = {
    SourceResourceId = "rr-workflow"
  }
}
