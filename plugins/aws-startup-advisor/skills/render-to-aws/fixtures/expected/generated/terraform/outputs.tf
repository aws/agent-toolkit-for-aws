output "alb_dns_name" {
  description = "Public web endpoint used for staged traffic validation."
  value       = aws_lb.web.dns_name
}

output "database_endpoint" {
  description = "Private PostgreSQL endpoint handed to compute as a non-secret setting."
  value       = aws_db_instance.postgres.address
}
output "database_port" {
  description = "PostgreSQL port handed to compute as a non-secret setting."
  value       = aws_db_instance.postgres.port
}
output "database_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials; compute injects it by reference."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}
output "database_security_group_id" {
  description = "Data security group that the network domain references for application access."
  value       = aws_security_group.data.id
}
output "valkey_endpoint" {
  description = "Private Valkey primary endpoint address handed to compute as a non-secret setting."
  value       = aws_elasticache_replication_group.valkey.primary_endpoint_address
}
output "valkey_app_user_id" {
  description = "ElastiCache user ID that compute uses for IAM authentication; no static password exists."
  value       = aws_elasticache_user.app.user_id
}
output "ecr_repository_url" {
  description = "Build-once immutable image repository URL."
  value       = aws_ecr_repository.application.repository_url
}

output "efs_access_point_id" {
  description = "Access point mounted at the migrated /var/data path."
  value       = aws_efs_access_point.application.id
}

output "service_discovery_namespace_id" {
  description = "Cloud Map private DNS namespace ID."
  value       = aws_service_discovery_private_dns_namespace.application.id
}
output "service_discovery_service_arn" {
  description = "Cloud Map service ARN that compute registers private ECS services against."
  value       = aws_service_discovery_service.private.arn
}
output "static_distribution_domain" {
  description = "CloudFront domain used before external DNS cutover."
  value       = aws_cloudfront_distribution.static.domain_name
}

output "migration_summary" {
  description = "Machine-readable accounting summary for the generated infrastructure."
  value = {
    accounted_count          = 15
    generated_count          = 13
    unsupported_count        = 0
    estimate_alignment       = "balanced"
    workflow_artifacts_state = "generated"
    ai_track_state           = "deferred_shared_ai_engine"
  }
}
