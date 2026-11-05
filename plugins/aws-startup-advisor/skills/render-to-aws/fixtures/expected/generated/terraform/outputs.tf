output "alb_dns_name" {
  description = "Public web endpoint used for staged traffic validation."
  value       = aws_lb.web.dns_name
}

output "database_endpoint" {
  description = "Private PostgreSQL endpoint."
  value       = aws_db_instance.postgres.address
  sensitive   = true
}

output "ecr_repository_url" {
  description = "Build-once immutable image repository URL."
  value       = aws_ecr_repository.application.repository_url
}

output "efs_access_point_id" {
  description = "Access point mounted at the migrated /var/data path."
  value       = aws_efs_access_point.application.id
}

output "static_distribution_domain" {
  description = "CloudFront domain used before external DNS cutover."
  value       = aws_cloudfront_distribution.static.domain_name
}

output "migration_summary" {
  description = "Machine-readable accounting summary for the generated infrastructure."
  value = {
    accounted_count          = 15
    generated_count          = 11
    unsupported_count        = 2
    estimate_alignment       = "balanced"
    workflow_artifacts_state = "conditional_workflow_generation_unsupported"
    ai_track_state           = "deferred_shared_ai_engine"
  }
}
