# Compliant fixture — MUST pass (POLICY_OK).
# An internet-facing Network Load Balancer (L4) legitimately has no HTTPS:443
# listener — it fronts raw TCP/UDP. The ALB HTTPS rule must NOT fire on it.
resource "aws_lb" "game" {
  name               = "game-nlb"
  internal           = false
  load_balancer_type = "network"
  subnets            = ["subnet-1", "subnet-2"]
}

resource "aws_lb_listener" "game_tcp" {
  load_balancer_arn = aws_lb.game.arn
  port              = 7000
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.game.arn
  }
}
