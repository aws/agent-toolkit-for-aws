# Pure Elastic Beanstalk LoadBalanced env, exactly as heroku-to-aws generate-terraform.md emits
# it: NO standalone aws_lb / aws_lb_listener — EB provisions the ALB from the setting blocks
# below (LoadBalancerType=application). The static policy checker (validate-terraform-policy.py)
# only inspects standalone aws_lb_listener blocks, so it cannot see EB's ALB. This fixture MUST
# be POLICY_OK — and it passes the ALB TLS/redirect rules VACUOUSLY (there is no listener to
# inspect). It documents that EB-managed ALB posture is authoring-only, not gate-checked.

resource "aws_elastic_beanstalk_application" "web" {
  name = "${var.project_name}-web"
}

resource "aws_elastic_beanstalk_environment" "web" {
  name                = "${var.project_name}-web"
  application         = aws_elastic_beanstalk_application.web.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.web.name
  tier                = "WebServer"

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
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.instance_type_web
  }
}

data "aws_elastic_beanstalk_solution_stack" "web" {
  most_recent = true
  name_regex  = "64bit Amazon Linux 2023 (.*) running Python 3.12"
}
