resource "aws_ecs_cluster" "main" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/render-migration/${local.name_prefix}"
  retention_in_days = 30
}

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name_prefix}-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name_prefix}-web"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name         = "web"
    image        = var.web_image
    essential    = true
    portMappings = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.application.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_service" "web" {
  name            = "${local.name_prefix}-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.web.id]
    subnets          = aws_subnet.private[*].id
  }

  load_balancer {
    container_name   = "web"
    container_port   = 8080
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_service_discovery_private_dns_namespace" "application" {
  name = "${var.environment}.render-migration.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "private" {
  name = "private"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.application.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

resource "aws_ecs_task_definition" "private" {
  family                   = "${local.name_prefix}-private"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name         = "private"
    image        = var.private_image
    essential    = true
    portMappings = [{ containerPort = 10000, hostPort = 10000, protocol = "tcp" }]
    mountPoints = [{
      sourceVolume  = "private-data"
      containerPath = "/var/data"
      readOnly      = false
    }]
  }])

  volume {
    name = "private-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.application.id
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.application.id
        iam             = "DISABLED"
      }
    }
  }
}

resource "aws_ecs_service" "private" {
  name            = "${local.name_prefix}-private"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.private.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.private.id]
    subnets          = aws_subnet.private[*].id
  }

  service_registries {
    registry_arn = aws_service_discovery_service.private.arn
  }

  depends_on = [aws_efs_mount_target.application]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.worker_image
    essential   = true
    stopTimeout = 30
  }])
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.worker.id]
    subnets          = aws_subnet.private[*].id
  }
}

resource "aws_ecs_task_definition" "cron" {
  family                   = "${local.name_prefix}-cron"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name      = "cron"
    image     = var.cron_image
    essential = true
  }])
}

resource "aws_iam_role" "scheduler" {
  name = "${local.name_prefix}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "run-selected-task"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = [aws_ecs_task_definition.cron.arn] },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_execution.arn]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_scheduler_schedule" "cron" {
  name                         = "${local.name_prefix}-cron"
  schedule_expression          = "cron(0 * * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      launch_type         = "FARGATE"
      task_count          = 1
      task_definition_arn = aws_ecs_task_definition.cron.arn

      network_configuration {
        assign_public_ip = false
        security_groups  = [aws_security_group.worker.id]
        subnets          = aws_subnet.private[*].id
      }
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }
}
