# Compliant fixture — MUST pass (POLICY_OK).
# Proves sg_no_public_admin_ingress does NOT false-positive on legitimately
# public ports: web (80/443) and a high app/game port range (7000-7100). None
# of these are in the sensitive never-public list, so nothing should fire.
resource "aws_security_group" "web" {
  name   = "web-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Real-time game/UDP fleet on high ports — legitimately public, must NOT fire.
  ingress {
    from_port   = 7000
    to_port     = 7100
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH present but scoped to a private admin CIDR — not public, must NOT fire.
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
