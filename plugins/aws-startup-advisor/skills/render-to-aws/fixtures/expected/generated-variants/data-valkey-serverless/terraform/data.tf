

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

resource "aws_elasticache_serverless_cache" "valkey" {
  name                     = "${local.name_prefix}-valkey"
  description              = "Render Key Value replacement"
  engine                   = "valkey"
  major_engine_version     = var.valkey_major_version
  subnet_ids               = aws_subnet.private[*].id
  security_group_ids       = [aws_security_group.data.id]
  kms_key_id               = aws_kms_key.stack.arn
  user_group_id            = aws_elasticache_user_group.app.user_group_id
  snapshot_retention_limit = var.snapshot_retention_days
  daily_snapshot_time      = "07:00"

  cache_usage_limits {
    data_storage {
      maximum = var.valkey_max_data_gb
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = var.valkey_max_ecpu_per_second
    }
  }
}
