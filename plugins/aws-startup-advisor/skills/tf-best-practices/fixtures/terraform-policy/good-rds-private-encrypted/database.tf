# Compliant fixture — private, encrypted RDS. MUST pass (POLICY_OK).
resource "aws_db_instance" "good" {
  identifier          = "good-db"
  engine              = "postgres"
  instance_class      = "db.t4g.micro"
  allocated_storage   = 20
  publicly_accessible = false
  storage_encrypted   = true
}

# Variable-driven encryption must fail-open (not flagged) — proves fail-open path.
resource "aws_rds_cluster" "var_driven" {
  cluster_identifier = "var-db"
  engine             = "aurora-postgresql"
  storage_encrypted  = var.encrypt_db
}

variable "encrypt_db" {
  type    = bool
  default = true
}
