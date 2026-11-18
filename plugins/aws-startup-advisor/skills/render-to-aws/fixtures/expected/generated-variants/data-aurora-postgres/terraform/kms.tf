resource "aws_kms_key" "stack" {
  description             = "Encryption key for ${local.name_prefix} stack data stores, Performance Insights, and managed secrets"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_kms_alias" "stack" {
  name          = "alias/${local.name_prefix}-stack"
  target_key_id = aws_kms_key.stack.key_id
}
output "kms_key_arn" {
  description = "ARN of the stack key that encrypts the data tier; compute grants kms:Decrypt on it to the task execution role."
  value       = aws_kms_key.stack.arn
}
