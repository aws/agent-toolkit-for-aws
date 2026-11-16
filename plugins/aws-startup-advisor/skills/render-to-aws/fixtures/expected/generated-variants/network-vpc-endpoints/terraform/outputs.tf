output "ecr_repository_url" {
  description = "ECR repository URL used by the build-once promotion pipeline."
  value       = aws_ecr_repository.application.repository_url
}

output "ecr_repository_arn" {
  description = "ECR repository ARN for scoping push and pull permissions."
  value       = aws_ecr_repository.application.arn
}

output "alb_dns_name" {
  description = "Public web endpoint used for staged traffic validation."
  value       = aws_lb.web.dns_name
}

output "target_group_arn" {
  description = "Target group that the compute service registers tasks with."
  value       = aws_lb_target_group.web.arn
}

output "private_subnet_ids" {
  description = "Private subnet IDs for task placement."
  value       = aws_subnet.private[*].id
}

output "task_security_group_id" {
  description = "Security group attached to application tasks."
  value       = aws_security_group.task.id
}

output "efs_access_point_id" {
  description = "EFS access point that tasks mount with transit encryption."
  value       = aws_efs_access_point.application.id
}

output "service_discovery_namespace_id" {
  description = "Cloud Map private DNS namespace ID."
  value       = aws_service_discovery_private_dns_namespace.internal.id
}

output "service_discovery_service_arn" {
  description = "Cloud Map service ARN for the private service."
  value       = aws_service_discovery_service.private.arn
}

output "secret_arn" {
  description = "Secrets Manager secret ARN for scoping task role read access."
  value       = aws_secretsmanager_secret.runtime.arn
}

output "vpc_endpoint_ids" {
  description = "Interface and gateway VPC endpoint IDs that replace the NAT gateway."
  value = concat(
    [aws_vpc_endpoint.s3.id],
    [for endpoint in aws_vpc_endpoint.interface : endpoint.id],
  )
}
