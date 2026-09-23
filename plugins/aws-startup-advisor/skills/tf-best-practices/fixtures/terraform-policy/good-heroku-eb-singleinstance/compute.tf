# heroku-to-aws EB SingleInstance shape (generate-terraform.md): no ALB, instance in a PUBLIC
# subnet with AssociatePublicIpAddress=true so it is reachable. MUST be POLICY_OK — the policy
# gate flags only admin/datastore ports open to the world (22/3389/5432/6379/…), never web
# 80/443, so serving web traffic directly from a public instance is not a violation.

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
    value     = "SingleInstance"
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.instance_type_web
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "SecurityGroups"
    value     = aws_security_group.eb_instances.id
  }
  setting {
    namespace = "aws:ec2:vpc"
    name      = "AssociatePublicIpAddress"
    value     = "true"
  }
}

data "aws_elastic_beanstalk_solution_stack" "web" {
  most_recent = true
  name_regex  = "64bit Amazon Linux 2023 (.*) running Python 3.12"
}

resource "aws_security_group" "eb_instances" {
  name   = "${var.project_name}-eb"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
