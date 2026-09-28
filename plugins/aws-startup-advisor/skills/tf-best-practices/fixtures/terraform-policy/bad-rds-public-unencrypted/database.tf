# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: rds_not_public + rds_encryption_at_rest failure paths.
resource "aws_db_instance" "bad" {
  identifier          = "bad-db"
  engine              = "postgres"
  instance_class      = "db.t4g.micro"
  allocated_storage   = 20
  publicly_accessible = true
  storage_encrypted   = false
}
