# heroku-to-aws compute shape that also has a STANDALONE ALB (aws_lb + aws_lb_listener) —
# e.g. a Fargate-fronted web tier, or an EB env behind a caller-managed ALB. The standalone
# listener is what the policy gate inspects, so this fixture exercises the ALB TLS + redirect
# rules on real listener blocks. NOTE: a pure Elastic Beanstalk LoadBalanced env does NOT emit
# aws_lb/aws_lb_listener (EB provisions the ALB from setting blocks the static checker cannot
# read) — see good-heroku-eb-only/ for that case, which passes the ALB rules vacuously.

resource "aws_elastic_beanstalk_application" "web" {
  name = "${var.project_name}-web"
}

resource "aws_elastic_beanstalk_environment" "web" {
  name                = "${var.project_name}-web"
  application         = aws_elastic_beanstalk_application.web.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.web.name
  tier                = "WebServer"

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "IamInstanceProfile"
    value     = aws_iam_instance_profile.eb.name
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "SecurityGroups"
    value     = aws_security_group.eb_instances.id
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.instance_type_web
  }
  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "EnvironmentType"
    value     = "LoadBalanced"
  }
  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "LoadBalancerType"
    value     = "application"
  }
  setting {
    namespace = "aws:ec2:vpc"
    name      = "ELBScheme"
    value     = "public"
  }
}

data "aws_elastic_beanstalk_solution_stack" "web" {
  most_recent = true
  name_regex  = "64bit Amazon Linux 2023 (.*) running Python 3.12"
}

resource "aws_lb" "web" {
  name               = "${var.project_name}-web"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.web.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
