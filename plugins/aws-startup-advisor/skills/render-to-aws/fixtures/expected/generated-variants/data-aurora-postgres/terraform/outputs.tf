output "database_endpoint" {
  description = "Private Aurora writer endpoint handed to compute as a non-secret setting."
  value       = aws_rds_cluster.postgres.endpoint
}

output "database_reader_endpoint" {
  description = "Private Aurora reader endpoint for read-only clients."
  value       = aws_rds_cluster.postgres.reader_endpoint
}

output "database_port" {
  description = "PostgreSQL port handed to compute as a non-secret setting."
  value       = aws_rds_cluster.postgres.port
}

output "database_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials; compute injects it by reference."
  value       = aws_rds_cluster.postgres.master_user_secret[0].secret_arn
}

output "database_security_group_id" {
  description = "Data security group that the network domain references for application access."
  value       = aws_security_group.data.id
}
