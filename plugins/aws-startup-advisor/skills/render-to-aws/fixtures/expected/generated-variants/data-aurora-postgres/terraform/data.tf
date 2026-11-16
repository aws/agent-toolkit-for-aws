

resource "aws_db_subnet_group" "main" {
  name       = local.name_prefix
  subnet_ids = aws_subnet.private[*].id
}


resource "aws_rds_cluster_parameter_group" "postgres" {
  name        = "${local.name_prefix}-aurora-pg16"
  family      = "aurora-postgresql16"
  description = "Aurora PostgreSQL 16 cluster parameters for the Render migration"

  parameter {
    name         = "rds.logical_replication"
    value        = "1"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }

  parameter {
    name         = "max_replication_slots"
    value        = "10"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "max_wal_senders"
    value        = "10"
    apply_method = "pending-reboot"
  }
}

resource "aws_rds_cluster" "postgres" {
  cluster_identifier                  = "${local.name_prefix}-postgres"
  engine                              = "aurora-postgresql"
  engine_version                      = var.postgres_engine_version
  database_name                       = "application"
  master_username                     = "migration_admin"
  manage_master_user_password         = true
  master_user_secret_kms_key_id       = aws_kms_key.stack.arn
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.data.id]
  db_cluster_parameter_group_name     = aws_rds_cluster_parameter_group.postgres.name
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.stack.arn
  iam_database_authentication_enabled = true
  backup_retention_period             = var.backup_retention_days
  preferred_backup_window             = "07:00-08:00"
  copy_tags_to_snapshot               = true
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${local.name_prefix}-postgres-final"
  enabled_cloudwatch_logs_exports     = ["postgresql"]
  apply_immediately                   = false
  lifecycle {
    ignore_changes = [engine_version]
  }
}

resource "aws_rds_cluster_instance" "postgres" {
  count                           = var.postgres_instance_count
  identifier                      = "${local.name_prefix}-postgres-${count.index + 1}"
  cluster_identifier              = aws_rds_cluster.postgres.id
  engine                          = aws_rds_cluster.postgres.engine
  engine_version                  = aws_rds_cluster.postgres.engine_version
  instance_class                  = var.postgres_instance_class
  db_subnet_group_name            = aws_db_subnet_group.main.name
  publicly_accessible             = false
  auto_minor_version_upgrade      = true
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.stack.arn
  promotion_tier                  = count.index
  lifecycle {
    ignore_changes = [engine_version]
  }
}
