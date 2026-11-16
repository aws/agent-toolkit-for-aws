output "static_bucket_name" {
  description = "Private S3 bucket that receives the built static assets."
  value       = aws_s3_bucket.static.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID used for cache invalidation after a release."
  value       = aws_cloudfront_distribution.static.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name used to validate the site before DNS cutover."
  value       = aws_cloudfront_distribution.static.domain_name
}
