output "valkey_endpoint" {
  description = "Private Valkey endpoint address handed to compute as a non-secret setting."
  value       = aws_elasticache_serverless_cache.valkey.endpoint[0].address
}

output "valkey_port" {
  description = "Valkey port handed to compute as a non-secret setting."
  value       = aws_elasticache_serverless_cache.valkey.endpoint[0].port
}

output "valkey_app_user_id" {
  description = "ElastiCache user ID that compute uses for IAM authentication; no static password exists."
  value       = aws_elasticache_user.app.user_id
}

output "valkey_serverless_cache_arn" {
  description = "ARN of the serverless cache, for scoping elasticache:Connect on the task role."
  value       = aws_elasticache_serverless_cache.valkey.arn
}
