# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: db_sg_no_public_ingress failure path (5432 open to the internet).
resource "aws_security_group" "bad" {
  name   = "bad-db-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
