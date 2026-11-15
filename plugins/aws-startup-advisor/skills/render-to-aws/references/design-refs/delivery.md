# Static, configuration, build, domain, preview, and observability mappings

## Static sites

Select `Amazon S3 + Amazon CloudFront` deterministically. Use a private S3 origin with origin access control, not public website hosting. Add ACM for custom TLS and Route 53 only when AWS owns DNS. Preserve build command, publish directory, redirects/rewrites, headers, cache policy, invalidation, and immutable asset behavior. Reject EC2, ECS/Fargate, and Lambda runtime targets because the source has no serving compute.

## Environment groups

Select `AWS Secrets Manager + AWS Systems Manager Parameter Store`. Classify names only: secret material belongs in Secrets Manager and non-secret configuration in Parameter Store. Never infer or request values. Environment-group membership is topology; it does not create a separate runtime.

## Build Sources and artifacts

Select `Amazon ECR + CI/CD immutable digest promotion` for a shared Build Source/artifact. Build once, scan, push, and promote the same digest across environments; do not rebuild per environment. A source-only Build Source first produces one immutable image artifact. Separate build-time and runtime variable-name scopes and keep values out of artifacts. Reject independent per-service builds because they break the discovered promotion relationship.

## Projects and environments

Select the VPC/account/environment strategy from the networking reference. Each project/environment resource is accounted as consumed topology with the concrete selected boundary service or stack strategy. Protection and network isolation become deployment controls, not ignored metadata.

## Custom domains

Select ACM plus the already selected serving endpoint. Add Route 53 only with confirmed DNS ownership. The Render subdomain is an interim/source endpoint, not a custom-domain resource.

## Preview environments

Select `CI/CD ephemeral AWS stack` as delivery behavior. Preserve trigger, lifetime, isolation, safe data seeding, domain pattern, cost guard, and cleanup. Automatic preview recreation may be unsupported by Generate, but Design still records one delivery target and the generation limitation explicitly.

## Logs, metrics, and alarms

Select `Amazon CloudWatch Logs, Metrics, and Alarms` deterministically. Derive retention, alarms, dashboards, and optional tracing from preferences and observed availability. Successful-empty or plan-gated source metrics are evidence absence, not zero. Do not ingest broad application log bodies.
