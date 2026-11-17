output "cron_function_name" {
  description = "Name of the Lambda function that runs the cron job."
  value       = aws_lambda_function.cron.function_name
}

output "cron_schedule_name" {
  description = "Name of the EventBridge Scheduler schedule."
  value       = aws_scheduler_schedule.cron.name
}
