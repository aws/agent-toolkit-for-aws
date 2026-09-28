# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: db_sg_no_public_ingress must still fire when from_port / to_port are
# written as QUOTED integers (valid HCL: "5432" converts to 5432). Reading only
# bare integers made this world-open database report POLICY_OK.
resource "aws_security_group" "bad" {
  name   = "bad-db-sg-quoted"
  vpc_id = "vpc-123"

  ingress {
    from_port   = "5432"
    to_port     = "5432"
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
