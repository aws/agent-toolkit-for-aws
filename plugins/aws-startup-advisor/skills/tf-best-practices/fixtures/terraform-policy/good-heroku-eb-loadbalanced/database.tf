# RDS as heroku-to-aws emits: private, encrypted, scoped SG (Postgres plan -> RDS).

resource "aws_db_instance" "postgres" {
  identifier          = "${var.project_name}-postgres"
  engine              = "postgres"
  engine_version      = var.db_engine_version
  instance_class      = var.db_instance_class
  allocated_storage   = var.db_storage_gb
  storage_encrypted   = true
  publicly_accessible = false
  db_subnet_group_name = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  deletion_protection = true
  skip_final_snapshot = false
}

resource "aws_security_group" "db" {
  name   = "${var.project_name}-db"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.eb_instances.id]
  }
}
