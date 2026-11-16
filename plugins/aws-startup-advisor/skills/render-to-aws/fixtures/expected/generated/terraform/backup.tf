# AWS Backup for the EFS file system (retention 35 days, compliance: none).
resource "aws_backup_vault" "efs" {
  name = "${local.name_prefix}-efs"
  tags = { Component = "backup" }
}
resource "aws_backup_plan" "efs" {
  name = "${local.name_prefix}-efs-daily"
  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.efs.name
    schedule          = "cron(0 5 * * ? *)"
    lifecycle {
      delete_after = 35
    }
  }
  tags = { Component = "backup" }
}
resource "aws_iam_role" "backup" {
  name = "${local.name_prefix}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}
resource "aws_backup_selection" "efs" {
  name         = "${local.name_prefix}-efs"
  plan_id      = aws_backup_plan.efs.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_efs_file_system.application.arn]
}
