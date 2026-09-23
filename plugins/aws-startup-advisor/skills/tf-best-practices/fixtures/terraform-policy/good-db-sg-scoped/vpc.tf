# Compliant fixture — DB ingress scoped to an app SG. MUST pass (POLICY_OK).
resource "aws_security_group" "app" {
  name   = "app-sg"
  vpc_id = "vpc-123"
}

resource "aws_security_group" "good" {
  name   = "good-db-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  # A non-DB port open to the internet (e.g. HTTPS) must NOT trip the DB-port rule.
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Separate ingress-rule resource opening 5432 to the world: fail-open by design
# (this static reader cannot correlate it to its SG), so it must NOT be flagged.
resource "aws_vpc_security_group_ingress_rule" "separate" {
  security_group_id = aws_security_group.good.id
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}
