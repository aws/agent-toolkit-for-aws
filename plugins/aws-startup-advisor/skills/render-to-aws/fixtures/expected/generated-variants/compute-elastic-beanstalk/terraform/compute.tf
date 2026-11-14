data "aws_elastic_beanstalk_solution_stack" "node" {
  most_recent = true
  name_regex  = "^64bit Amazon Linux 2023 (.*) running Node.js 20$"
}

locals {
  partition = data.aws_partition.current.partition
}

resource "aws_iam_role" "eb_instance" {
  name = "${local.name_prefix}-eb-instance"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { SourceResourceId = "rr-web" }
}

resource "aws_iam_role_policy_attachment" "eb_web_tier" {
  role       = aws_iam_role.eb_instance.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSElasticBeanstalkWebTier"
}

resource "aws_iam_role_policy_attachment" "eb_ssm" {
  role       = aws_iam_role.eb_instance.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "eb_secret_read" {
  name = "read-application-secret"
  role = aws_iam_role.eb_instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.app_secret_arn]
    }]
  })
}

resource "aws_iam_instance_profile" "eb_instance" {
  name = "${local.name_prefix}-eb-instance"
  role = aws_iam_role.eb_instance.name
}

resource "aws_iam_role" "eb_service" {
  name = "${local.name_prefix}-eb-service"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "elasticbeanstalk.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "sts:ExternalId" = "elasticbeanstalk" } }
    }]
  })

  tags = { SourceResourceId = "rr-web" }
}

resource "aws_iam_role_policy_attachment" "eb_enhanced_health" {
  role       = aws_iam_role.eb_service.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSElasticBeanstalkEnhancedHealth"
}

resource "aws_iam_role_policy_attachment" "eb_managed_updates" {
  role       = aws_iam_role.eb_service.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSElasticBeanstalkManagedUpdatesCustomerRolePolicy"
}

resource "aws_elastic_beanstalk_application" "web" {
  name        = "${local.name_prefix}-web"
  description = "Render web service rr-web migrated to Elastic Beanstalk."

  tags = { SourceResourceId = "rr-web" }
}

resource "aws_elastic_beanstalk_environment" "web" {
  name                = "${local.name_prefix}-web"
  application         = aws_elastic_beanstalk_application.web.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.node.name

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "IamInstanceProfile"
    value     = aws_iam_instance_profile.eb_instance.name
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.eb_instance_type
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "SecurityGroups"
    value     = aws_security_group.instances.id
  }

  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MinSize"
    value     = "2"
  }

  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MaxSize"
    value     = "4"
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "VPCId"
    value     = aws_vpc.main.id
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "Subnets"
    value     = join(",", aws_subnet.private[*].id)
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "ELBSubnets"
    value     = join(",", aws_subnet.public[*].id)
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "ELBScheme"
    value     = "public"
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "AssociatePublicIpAddress"
    value     = "false"
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
    namespace = "aws:elasticbeanstalk:environment"
    name      = "ServiceRole"
    value     = aws_iam_role.eb_service.name
  }

  setting {
    namespace = "aws:elasticbeanstalk:environment:process:default"
    name      = "HealthCheckPath"
    value     = var.eb_health_check_path
  }

  setting {
    namespace = "aws:elasticbeanstalk:environment:process:default"
    name      = "Port"
    value     = tostring(var.eb_application_port)
  }

  setting {
    namespace = "aws:elasticbeanstalk:healthreporting:system"
    name      = "SystemType"
    value     = "enhanced"
  }

  setting {
    namespace = "aws:elasticbeanstalk:command"
    name      = "DeploymentPolicy"
    value     = "Rolling"
  }

  setting {
    namespace = "aws:elasticbeanstalk:cloudwatch:logs"
    name      = "StreamLogs"
    value     = "true"
  }

  setting {
    namespace = "aws:elasticbeanstalk:cloudwatch:logs"
    name      = "RetentionInDays"
    value     = "30"
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environmentsecrets"
    name      = "APP_CONFIG"
    value     = var.app_secret_arn
  }

  setting {
    namespace = "aws:elbv2:loadbalancer"
    name      = "SecurityGroups"
    value     = aws_security_group.alb.id
  }

  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "Protocol"
    value     = "HTTPS"
  }

  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "SSLCertificateArns"
    value     = var.issued_certificate_arn
  }

  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "SSLPolicy"
    value     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  }

  setting {
    namespace = "aws:elbv2:listener:default"
    name      = "ListenerEnabled"
    value     = "false"
  }

  tags = { SourceResourceId = "rr-web" }
}
