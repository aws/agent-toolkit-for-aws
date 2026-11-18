resource "aws_db_subnet_group" "main" {
  name       = local.name_prefix
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_parameter_group" "postgres" {
  name        = "${local.name_prefix}-postgres16"
  family      = "postgres16"
  description = "PostgreSQL 16 parameters for the Render migration"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }
}
resource "aws_db_instance" "postgres" {
  identifier                      = "${local.name_prefix}-postgres"
  allocated_storage               = 100
  max_allocated_storage           = 200
  storage_type                    = "gp3"
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = "db.m6g.large"
  db_name                         = "application"
  username                        = "migration_admin"
  manage_master_user_password     = true
  parameter_group_name            = aws_db_parameter_group.postgres.name
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.data.id]
  multi_az                        = true
  publicly_accessible             = false
  storage_encrypted               = true
  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  backup_retention_period         = 7
  backup_window                   = "03:00-04:00"
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name_prefix}-postgres-final"
  auto_minor_version_upgrade      = true
  maintenance_window              = "sun:05:00-sun:06:00"
  apply_immediately               = false
}
resource "aws_elasticache_subnet_group" "main" {
  name       = local.name_prefix
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_elasticache_parameter_group" "valkey" {
  name        = "${local.name_prefix}-valkey8"
  family      = "valkey8"
  description = "Valkey 8 parameters for the Render migration"
  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
}
resource "aws_elasticache_user" "default" {
  user_id              = "${local.name_prefix}-default"
  user_name            = "default"
  engine               = "VALKEY"
  access_string        = "off -@all"
  no_password_required = true
}
resource "aws_elasticache_user" "app" {
  user_id       = "${local.name_prefix}-app"
  user_name     = "${local.name_prefix}-app"
  engine        = "VALKEY"
  access_string = "on ~* +@all -@dangerous"
  authentication_mode {
    type = "iam"
  }
}
resource "aws_elasticache_user_group" "app" {
  user_group_id = "${local.name_prefix}-app"
  engine        = "VALKEY"
  user_ids      = [aws_elasticache_user.default.user_id, aws_elasticache_user.app.user_id]
}
resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id       = "${local.name_prefix}-valkey"
  description                = "Render Key Value replacement"
  engine                     = "valkey"
  engine_version             = "8.0"
  node_type                  = "cache.m6g.large"
  num_cache_clusters         = 2
  port                       = 6379
  parameter_group_name       = aws_elasticache_parameter_group.valkey.name
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
  user_group_ids             = [aws_elasticache_user_group.app.user_group_id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = true
  multi_az_enabled           = true
  snapshot_retention_limit   = 1
  snapshot_window            = "05:00-06:00"
  final_snapshot_identifier  = "${local.name_prefix}-valkey-final"
  auto_minor_version_upgrade = true
  maintenance_window         = "sun:07:00-sun:08:00"
  apply_immediately          = false
}
