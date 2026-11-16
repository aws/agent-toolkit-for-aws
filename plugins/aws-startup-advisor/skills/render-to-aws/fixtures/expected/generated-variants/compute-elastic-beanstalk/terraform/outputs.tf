output "eb_environment_cname" {
  description = "Load balancer CNAME of the Elastic Beanstalk environment."
  value       = aws_elastic_beanstalk_environment.web.cname
}

output "eb_application_name" {
  description = "Name of the Elastic Beanstalk application."
  value       = aws_elastic_beanstalk_application.web.name
}
