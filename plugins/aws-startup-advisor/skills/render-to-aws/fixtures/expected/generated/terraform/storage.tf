resource "aws_security_group" "efs" {
  name        = "${local.name_prefix}-efs"
  description = "NFS access from selected application tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "NFS from application tasks"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.private.id]
  }
}

resource "aws_efs_file_system" "application" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
}

resource "aws_efs_mount_target" "application" {
  count           = 2
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
}
