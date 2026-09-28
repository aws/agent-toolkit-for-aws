# Compliant fixture — MUST pass (POLICY_OK).
# Proves the IPv6 checks do NOT false-positive:
#   - public web on 443 over both ::/0 and 0.0.0.0/0 (not a sensitive port)
#   - SSH reachable over a scoped IPv6 prefix, not ::/0
#   - Postgres reachable over a scoped IPv6 prefix, not ::/0
# Also guards the reverse of the old regex bug: a benign ipv6_cidr_blocks list
# declared before a benign cidr_blocks list must not be misread either way.
resource "aws_security_group" "web_dualstack" {
  name   = "web-dualstack-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    ipv6_cidr_blocks = ["2001:db8:1234::/48"]
    cidr_blocks      = ["10.0.0.0/8"]
  }

  ingress {
    from_port        = 5432
    to_port          = 5432
    protocol         = "tcp"
    ipv6_cidr_blocks = ["2001:db8:1234::/48"]
  }
}
