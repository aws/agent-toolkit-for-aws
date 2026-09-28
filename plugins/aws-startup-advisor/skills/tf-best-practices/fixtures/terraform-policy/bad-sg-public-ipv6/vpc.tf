# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises the IPv6 public-ingress paths for BOTH security-group rules:
#   - sg_no_public_admin_ingress via ipv6_cidr_blocks = ["::/0"] on SSH
#   - db_sg_no_public_ingress    via ipv6_cidr_blocks = ["::/0"] on 5432
# Regression shape: ipv6_cidr_blocks is declared BEFORE cidr_blocks and the IPv4
# list is benign. The old r'cidr_blocks\s*=\s*\[' regex matched the tail of
# `ipv6_cidr_blocks` first, so the checker read the IPv6 list while believing it
# was reading IPv4, found no 0.0.0.0/0, and returned POLICY_OK.
resource "aws_security_group" "bad_ipv6_admin" {
  name   = "bad-ipv6-admin-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
    cidr_blocks      = ["10.0.0.0/8"]
  }
}

resource "aws_security_group" "bad_ipv6_db" {
  name   = "bad-ipv6-db-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port        = 5432
    to_port          = 5432
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
    cidr_blocks      = ["10.0.0.0/8"]
  }
}
