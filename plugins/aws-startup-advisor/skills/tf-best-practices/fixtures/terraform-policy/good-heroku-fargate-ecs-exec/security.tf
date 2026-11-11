# Compliant fixture — the ECS Exec task-role grant heroku-to-aws emits in security.tf
# (the `heroku run bash` equivalent). MUST pass (POLICY_OK): AWS defines no resource-level
# permissions for the four ssmmessages channel actions, so Resource "*" is the only
# possible shape and no_wildcard_iam exempts a statement that lists ONLY those actions.
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-${var.environment}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_exec" {
  name = "${var.project_name}-${var.environment}-ecs-exec"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ]
      Resource = "*"
    }]
  })
}

# A scoped statement next to it must not be disturbed by the exemption.
resource "aws_iam_role_policy" "ecs_task_queue" {
  name = "${var.project_name}-${var.environment}-ecs-queue"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage", "sqs:ReceiveMessage"]
      Resource = "arn:aws:sqs:us-east-1:123456789012:${var.project_name}-jobs"
    }]
  })
}
