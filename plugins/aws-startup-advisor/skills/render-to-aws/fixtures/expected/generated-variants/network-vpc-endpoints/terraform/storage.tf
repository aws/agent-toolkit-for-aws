resource "aws_security_group" "efs" {
  name        = "${local.name_prefix}-efs"
  description = "NFS access from the owning application tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "efs_from_task" {
  security_group_id            = aws_security_group.efs.id
  description                  = "NFS from application tasks"
  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.task.id
}

resource "aws_efs_file_system" "application" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  lifecycle_policy {
    transition_to_primary_storage_class = "AFTER_1_ACCESS"
  }
  tags = { Name = local.name_prefix }
}

resource "aws_efs_backup_policy" "application" {
  file_system_id = aws_efs_file_system.application.id
  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_file_system_policy" "application" {
  file_system_id = aws_efs_file_system.application.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = { AWS = "*" }
      Action    = "*"
      Resource  = aws_efs_file_system.application.arn
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

# One mount target per private subnet, so every Availability Zone can mount.
resource "aws_efs_mount_target" "application" {
  count           = length(aws_subnet.private)
  file_system_id  = aws_efs_file_system.application.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "application" {
  file_system_id = aws_efs_file_system.application.id
  posix_user {
    gid = 1000
    uid = 1000
  }
  root_directory {
    path = "/var/data"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "0750"
    }
  }
  depends_on = [aws_efs_mount_target.application]
}
