resource "aws_vpc" "main" {
  cidr_block           = "10.43.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${local.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = { Name = "${local.name_prefix}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = { Name = "${local.name_prefix}-private-${count.index + 1}" }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = { Name = "${local.name_prefix}-nat" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags       = { Name = "${local.name_prefix}-nat" }
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name_prefix}-public" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = { Name = "${local.name_prefix}-private" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-eb-alb"
  description = "Public HTTPS entry for the Elastic Beanstalk load balancer."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-eb-alb" }
}

resource "aws_security_group" "instances" {
  name        = "${local.name_prefix}-eb-instances"
  description = "Elastic Beanstalk instances reachable only from the load balancer."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-eb-instances" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from the internet"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_instances" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Application traffic to the instances"
  referenced_security_group_id = aws_security_group.instances.id
  from_port                    = var.eb_application_port
  to_port                      = var.eb_application_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "instances_from_alb" {
  security_group_id            = aws_security_group.instances.id
  description                  = "Application traffic from the load balancer only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.eb_application_port
  to_port                      = var.eb_application_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "instances_https" {
  security_group_id = aws_security_group.instances.id
  description       = "HTTPS to AWS APIs and package sources through NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
