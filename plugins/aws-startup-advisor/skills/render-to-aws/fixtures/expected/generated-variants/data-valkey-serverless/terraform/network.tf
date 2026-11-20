data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]
}

resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app"
  description = "Application tasks that consume the data tier"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "data" {
  name        = "${local.name_prefix}-data"
  description = "Valkey access from application tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Valkey from application tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}
