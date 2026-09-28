# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: sg_no_public_admin_ingress failure path (SSH open to the internet).
resource "aws_security_group" "bad_admin" {
  name   = "bad-admin-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Redis also exposed via a port range covering 6379.
  ingress {
    from_port   = 6000
    to_port     = 7000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
