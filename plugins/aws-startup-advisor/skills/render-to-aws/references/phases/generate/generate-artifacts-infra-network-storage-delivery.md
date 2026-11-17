---
_fragment: artifacts-infra-network-storage-delivery
_of_phase: generate
_contributes:
  - terraform/network.tf
  - terraform/storage.tf
  - terraform/delivery.tf
---
# Generate network, storage and delivery Terraform
This fragment refines the rows of `generate-artifacts-infra.md` for `network.tf`, `storage.tf` and `delivery.tf`. It adds no compute or data guidance: ECS services, task definitions, RDS and ElastiCache belong to their own fragments. Fixtures that show the endpoint-based and static-site shapes live under `fixtures/expected/generated-variants/`.
## network.tf
### Required resources

- VPC with `enable_dns_support` and `enable_dns_hostnames` both `true` (interface endpoint private DNS needs both). The CIDR comes from a validated variable or local. Never look up the default VPC.
- At least two Availability Zones from `data.aws_availability_zones` with `state = "available"`. Public subnets hold only the ALB. Private subnets hold tasks. Use one route table per tier. Only the public table has the internet gateway default route.
- Egress, NAT mode: one `aws_eip` and `aws_nat_gateway` per the HA choice in `aws-design.json`, `depends_on` the internet gateway, and a private default route to the NAT.
- Egress, endpoint mode: no `aws_nat_gateway`, no `aws_eip`, and no `0.0.0.0/0` route on private tables. Attach an S3 gateway endpoint to the private route tables. Add interface endpoints with `private_dns_enabled = true` in the private subnets, behind an endpoint security group, for `ecr.api`, `ecr.dkr`, `logs`, `secretsmanager` and `sts`. ECR image layers are served from S3, so the S3 gateway endpoint is mandatory. Add an `ssm` endpoint only when the design reads Parameter Store values at task start.
- Name lengths: ALB and target group names are limited to 32 characters and `bucket_prefix` to 37. With `local.name_prefix` as `<project_name>-<environment>`, the suffixes are `-alb-logs-` (10, so `name_prefix` of 27 or fewer), `-web` (4, so 28 or fewer) and `-static-` (8, so 29 or fewer). Validate `project_name` and `environment` with length limits that fit the longest suffix the stack uses (for example 16 and 10 with an ALB, 18 and 10 for a static site) so an over-long value fails at plan with a clear message. Never let derived names exceed the limits.
- Choosing the mode: use NAT when `aws-design.json` or the inventory records an outbound internet need (third-party APIs, package downloads at runtime). Use the endpoint set when the design records none. When the evidence is absent or ambiguous, keep NAT. Never ask a new question and never fail on this choice.
- Security groups, one per tier: edge (ALB), web tasks, private tasks, worker tasks, endpoints, EFS, data. `network.tf` also declares `aws_security_group.data` for the data tier (the only declaration in the pack); `data.tf` references it and never declares it. Prefer standalone `aws_vpc_security_group_ingress_rule` and `aws_vpc_security_group_egress_rule` on groups with no inline rules. Never mix inline and standalone rules on one group.
- ALB: `internal = false` only for the public web service, `drop_invalid_header_fields = true`, `enable_deletion_protection` from a variable. HTTPS 443 listener with `ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"` and a forward action. HTTP 80 listener that only redirects (`HTTP_301` to 443).
- Target group: `target_type = "ip"` for Fargate, a full `health_check` (path, matcher, interval, timeout, healthy and unhealthy thresholds), and `deregistration_delay` matching the shutdown behavior in the design.
- ALB access logs: an S3 bucket with SSE-S3 (ALB logs do not support SSE-KMS), a public-access block, lifecycle expiration, and a bucket policy that allows `logdelivery.elasticloadbalancing.amazonaws.com` `s3:PutObject` on `AWSLogs/<account-id>/*` only.
- ACM with external DNS: `certificate_arn = var.issued_certificate_arn`. The variable has no default and validates an ACM ARN. Only the ARN of a certificate already `Issued` is accepted. Record the request, DNS validation and wait-for-`Issued` steps in `MIGRATION_GUIDE.md`. For CloudFront the certificate must be in `us-east-1`.
- Private services: `aws_service_discovery_private_dns_namespace` plus `aws_service_discovery_service` (DNS `A`, `MULTIVALUE`), or ECS Service Connect when the design selects it. Use an internal ALB or NLB only when Design selected one. Compute owns the service wiring. Network exposes the namespace id and service ARN as outputs.

### Least-privilege

- Ingress rules use `referenced_security_group_id` or `security_groups`. The only CIDR ingress is the ALB on 80 and 443 from `0.0.0.0/0` (or `::/0`).
- Edge egress reaches only the web task security group on the application port.
- Endpoint security group allows 443 from the task security groups only: every group that holds tasks, including a private-service group.
- In endpoint mode, task egress replaces only the internet and AWS API paths: 443 to the endpoint security group, 443 to the S3 prefix list (`aws_vpc_endpoint.s3.prefix_list_id`), and 2049 to the EFS security group when EFS is selected. This applies to every group that holds tasks, a private-service group included: Terraform removes the default allow-all egress from a group it creates, so a private-service group with no egress rules cannot pull images, write logs or read secrets, and its tasks fail to start. Give it the same 443 egress to the endpoint security group and the S3 prefix list, and add the matching 443 ingress on the endpoint security group from it. Also emit security-group-referenced egress for every selected internal flow: task groups to the data security group on the database and cache ports (for example 5432, 6379), and callers to the private-service security group on its port. Stateful return traffic does not replace the initiating egress rule. No `-1` protocol egress and no CIDR egress.

### Anti-patterns

- Attaching a pending certificate, or creating `aws_acm_certificate` and `aws_acm_certificate_validation` for a listener.
- Inventing Route 53 zones or records for external DNS.
- Choosing NAT with no outbound need when endpoints would do.
- Missing `ecr.dkr` or the S3 gateway endpoint, which leaves tasks unable to pull images.
- Interface endpoints in a VPC without DNS hostnames.
- Open `0.0.0.0/0` or `-1` task egress in endpoint mode.
- Endpoint mode that drops the task egress to the data tier or private service, which leaves connections to them timing out.
- One shared security group for every tier.
- An HTTP listener that forwards.
- A public listener or `0.0.0.0/0` ingress for a private service.

### Ordering
VPC, subnets, internet gateway, route tables, endpoints or NAT, security groups, ALB, target group, listeners. NAT and EIP `depends_on` the internet gateway. Listeners reference the certificate variable, never a certificate resource.
## storage.tf
### Required resources

- EFS, when selected for a `service_to_disk` edge: `encrypted = true`. `performance_mode = "generalPurpose"` unless the design records a latency need (do not use `maxIO`). `throughput_mode = "elastic"` unless the design records a steady throughput, then `provisioned` with a validated variable (`bursting` is accepted where the existing golden uses it).
- `lifecycle_policy` with `transition_to_ia = "AFTER_30_DAYS"` and `transition_to_primary_storage_class = "AFTER_1_ACCESS"`.
- `aws_efs_backup_policy` with status `ENABLED`.
- `aws_efs_file_system_policy` that denies requests with `aws:SecureTransport = false`.
- One `aws_efs_mount_target` per private subnet (`count` equals the private subnet count), in the EFS security group.
- `aws_efs_access_point` with `posix_user` and `root_directory.creation_info` owner uid, gid and permissions from the disk row. The path is the selected mount path. Never default ownership to root (0/0).
- Compute-side contract (do not write compute here): the task definition mounts through the access point with `transit_encryption = "ENABLED"`, and the service depends on the mount targets.
- S3 buckets in general: `bucket_prefix`, `aws_s3_bucket_ownership_controls` with `BucketOwnerEnforced`, versioning, SSE (`AES256`, or KMS only when the design says so), a public-access block with all four flags, a bucket policy denying `aws:SecureTransport = false`, and lifecycle rules with `abort_incomplete_multipart_upload` and noncurrent-version expiry. Give each lifecycle rule an explicit `filter {}`. Keep `force_destroy = false`.

### Least-privilege

- EFS security group ingress is 2049 from the owning task security group only.
- Bucket policies never use an `Allow` with a wildcard principal.

### Anti-patterns

- Public ACLs or S3 website hosting.
- EFS without an access point.
- Mount targets in one AZ only.
- A root-owned access point.
- NFS ingress from a CIDR.
- S3 chosen for POSIX locking or rename semantics.

### Ordering
File system, security group, mount targets, access point, file system policy. Outputs expose the file system id and access point id.
## delivery.tf
### Required resources

- Static or SPA site: a private bucket (S3 list above), an origin access control with `origin_access_control_origin_type = "s3"`, `signing_behavior = "always"` and `signing_protocol = "sigv4"` (OAC), and a bucket policy that allows `cloudfront.amazonaws.com` `s3:GetObject` on `bucket/*` conditioned on `AWS:SourceArn` equal to the distribution ARN, plus the TLS-only deny.
- Distribution: `cache_policy_id` and `response_headers_policy_id` instead of `forwarded_values`, `viewer_protocol_policy = "redirect-to-https"`, `compress = true`, `http_version = "http2and3"`, `price_class` from a variable, `default_root_object = "index.html"`.
- `aws_cloudfront_response_headers_policy` with HSTS, `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy`. Add a Content-Security-Policy only when the source records headers. Never invent one.
- Cache split: an `ordered_cache_behavior` for the hashed-asset path using the managed `Managed-CachingOptimized` policy (via `data "aws_cloudfront_cache_policy"`), and a custom short-TTL `aws_cloudfront_cache_policy` for the default behavior that serves `index.html`.
- SPA error handling: `custom_error_response` mapping 403 and 404 to `/index.html` with response code 200 and a short `error_caching_min_ttl`. Add it only when the source route table shows a catch-all rewrite.
- Custom domains: `aliases` from `custom_domain_names` and `acm_certificate_arn` from an Issued `us-east-1` certificate variable, with `ssl_support_method = "sni-only"` and `minimum_protocol_version = "TLSv1.2_2021"`. Add a `lifecycle.precondition` that aliases require the certificate. Otherwise use `cloudfront_default_certificate = true`.
- Render rewrites that are not the SPA fallback become an `aws_cloudfront_function` only when the source records them. Otherwise document the limitation.
- ECR: `image_tag_mutability = "IMMUTABLE"`, `scan_on_push = true`, an encryption configuration, `force_delete = false`, and an `aws_ecr_lifecycle_policy` (priority 1 expires untagged images after 14 days, the last rule uses `tagStatus = "any"` with `imageCountMoreThan` from a validated variable so promoted digests are not expired early).
- Image-digest promotion outputs: `ecr_repository_url`, `ecr_repository_arn`, and one image variable per service validated as an ECR digest reference. No environment rebuilds source.
- Secrets Manager and SSM environment-group references: names and ARNs only. Declare `aws_secretsmanager_secret` without any `aws_secretsmanager_secret_version`. SSM `SecureString` values arrive through `sensitive` variables and never have defaults. Emit ARN outputs so the task role can be scoped to exact ARNs.
- Preview-environment CI/CD hand-off: emit no pipeline and no CI role. Emit outputs (`ecr_repository_url`, `ecr_repository_arn`, bucket name, distribution id, secret ARNs). `MIGRATION_GUIDE.md` records the ephemeral-stack trigger, lifetime, isolation, cost guard and cleanup that Design captured. Where automatic recreation is unsupported, keep the existing warning.

### Least-privilege

- The CloudFront bucket policy grants `s3:GetObject` only, never `s3:ListBucket` or `s3:*`.
- Secret access is scoped to exact ARNs, never a wildcard secret policy.

### Anti-patterns

- Public S3 website hosting.
- A bucket policy `Allow` with `Principal = "*"`.
- Origin access identity instead of OAC.
- `s3:*` granted to CloudFront.
- An SPA fallback on a non-SPA site.
- Mutable ECR tags.
- A per-environment rebuild.
- Secret values in Terraform defaults, or a `secret_version` that puts values in state.

### Ordering
Bucket and controls, OAC, cache and response headers policies, distribution, bucket policy (needs the distribution ARN), ECR and lifecycle, secrets and parameters, outputs.
## Self-check before returning

- [ ] The VPC has DNS support and hostnames, two or more AZs, one route table per tier.
- [ ] Endpoint mode has no NAT, no EIP, no private default route, the S3 gateway endpoint and all five interface endpoints.
- [ ] Endpoint mode keeps security-group-referenced task egress for the selected database, cache and private-service flows, with no `-1` or CIDR egress.
- [ ] Every group that holds tasks in endpoint mode, a private-service group included, has 443 egress to the endpoint security group and the S3 prefix list, and the endpoint security group admits 443 from it.
- [ ] `project_name` and `environment` have length validation so ALB and target group names fit 32 characters and `bucket_prefix` fits 37.
- [ ] Every ingress rule references a security group, except the ALB 80 and 443.
- [ ] The HTTPS listener uses `var.issued_certificate_arn` and the HTTP listener only redirects.
- [ ] No `aws_acm_certificate` is attached to a listener.
- [ ] EFS is encrypted, has a backup policy, a mount target per AZ and a non-root access point.
- [ ] Buckets are private, TLS-only, versioned and encrypted.
- [ ] CloudFront uses OAC with an `AWS:SourceArn`-scoped `s3:GetObject` policy.
- [ ] ECR is immutable with scan-on-push and a lifecycle policy.
- [ ] No secret value appears in any default, output or `secret_version`.
