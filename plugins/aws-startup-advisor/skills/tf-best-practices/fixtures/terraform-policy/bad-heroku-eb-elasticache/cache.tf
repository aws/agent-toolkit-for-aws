# Intentionally-bad Heroku-shaped output: Redis plan -> ElastiCache WITHOUT encryption,
# and the ALB forwards plaintext HTTP instead of redirecting. MUST POLICY_FAIL.
# (Test data only — never deployed.)

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.project_name}-redis"
  description                = "Heroku Redis -> ElastiCache"
  node_type                  = var.cache_node_type
  at_rest_encryption_enabled = false
}

resource "aws_lb" "web" {
  name               = "${var.project_name}-web"
  load_balancer_type = "application"
}

resource "aws_lb_listener" "http_forward" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
