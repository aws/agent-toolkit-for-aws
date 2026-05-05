# App Runner Guide

> **⚠️ App Runner was sunset April 30, 2026. No new customers. No new features. Existing customers should migrate to ECS Express Mode.** See: [App Runner Availability Change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)

This reference file is for **existing App Runner customers** who need to operate their current services or migrate to ECS Express Mode. Do NOT recommend App Runner for new projects.

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Critical: App Runner Sunset Notice](#critical-app-runner-sunset-notice)
- [ECS Express Mode as Replacement](#ecs-express-mode-as-replacement)
- [Comparison: App Runner vs ECS Express Mode vs ECS Fargate](#comparison-app-runner-vs-ecs-express-mode-vs-ecs-fargate)
- [Auto Scaling Behavior](#auto-scaling-behavior)
- [VPC Connector Gotchas](#vpc-connector-gotchas)
- [Migration Guide: App Runner to ECS Express Mode](#migration-guide-app-runner-to-ecs-express-mode)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Operators MUST confirm the following before proceeding:

| Dependency | Check Command |
|---|---|
| Correct account/region | `aws sts get-caller-identity --output json` |
| Sufficient IAM permissions | Caller MUST have permissions for the target service (App Runner or ECS). Use least-privilege scoped policies — avoid `AdministratorAccess` or `*FullAccess` managed policies. |

---

## Critical: App Runner Sunset Notice

> **App Runner is no longer accepting new customers after April 30, 2026.**
> Existing customers MAY continue using the service, but SHOULD plan migration.
> See: <https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html>

Key implications:

- New AWS accounts created on or after April 30, 2026 are not expected to have access to create App Runner services. AWS documentation states the service will be "closed to new customers" but does not document the specific API-level behavior.
- Existing services continue to run but SHOULD be migrated to ECS Express Mode or ECS Fargate.
- AWS has not announced an end-of-life date for existing services, but operators SHOULD NOT start new projects on App Runner.

---

## ECS Express Mode as Replacement

ECS Express Mode (announced November 2025) provisions a complete ECS stack with a single API call:

- ECS cluster + Fargate service
- Application Load Balancer
- Auto scaling policy
- Security groups and networking

```bash
# Create an ECS Express Mode service
aws ecs create-express-gateway-service \
  --service-name $SERVICE_NAME \
  --execution-role-arn $EXECUTION_ROLE_ARN \
  --infrastructure-role-arn $INFRA_ROLE_ARN \
  --primary-container "{\"image\":\"$IMAGE_URI\",\"containerPort\":$CONTAINER_PORT,\"secrets\":[{\"name\":\"DB_PASSWORD\",\"valueFrom\":\"$SECRET_ARN\"}]}" \
  --region $REGION \
  --output json
```

> **Security note:** Use the `secrets` field (referencing AWS Secrets Manager or SSM Parameter Store ARNs) for sensitive values. Do NOT pass secrets via the `environment` field — environment variables are visible in plaintext in the ECS task definition. See: [ExpressGatewayContainer API](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ExpressGatewayContainer.html)
>
> This example shows minimum required parameters. For production deployments, operators SHOULD also configure: a task role with least-privilege permissions (`--task-role-arn`), private subnets for internal services (`--network-configuration`), WAF association on the ALB, and ALB access logging.

ECS Express Mode is designed as the direct migration path for App Runner workloads. It preserves the simplicity of App Runner while providing full ECS capabilities when needed.

---

## Comparison: App Runner vs ECS Express Mode vs ECS Fargate

| Feature | App Runner | ECS Express Mode | ECS Fargate (Standard) |
|---|---|---|---|
| **Setup complexity** | Minimal — single API/console action | Minimal — single API call provisions full stack | Full control — multiple resources to configure |
| **Networking** | Automatic public endpoint; optional VPC connector for outbound | ALB provisioned automatically; VPC-native | Full VPC control; ALB/NLB configured separately |
| **Scaling** | Concurrency-based auto scaling | Target-tracking auto scaling (CPU/memory/ALB requests) | Target-tracking, step, scheduled, or predictive scaling |
| **Min instances** | 1 (cannot scale to zero) | 0 (MAY scale to zero with configuration; not explicitly documented for Express Mode — underlying ECS Application Auto Scaling supports min capacity 0) | 0 (MAY scale to zero) |
| **Custom domain / TLS** | Built-in custom domain + auto TLS | Default service URL: automatic TLS via ACM certificate auto-provisioned by Express Mode. Custom domain: operator supplies ACM certificate and attaches it to the ALB HTTPS listener | Via ALB/NLB — operator manages certificate |
| **VPC integration** | VPC connector (outbound only) | Full VPC-native | Full VPC-native |
| **ECS Exec / SSH** | Not supported | Supported | Supported |
| **Sidecar containers** | Not supported | Supported | Supported |
| **Use case** | Simple web apps, APIs (existing customers only) | Simple web apps, APIs — App Runner replacement | Complex architectures, multi-container, full control |
| **Limitations** | Sunsetting; no new customers; no sidecars; no ECS Exec | Newer service — feature set expanding | Requires more configuration and operational knowledge |

---

## Auto Scaling Behavior

App Runner uses concurrency-based auto scaling:

- **Metric**: Number of concurrent requests per instance.
- **Default concurrency target**: 100 concurrent requests per instance.
- **Minimum instances**: 1 — App Runner MUST NOT scale to zero. At least one instance is always running and billed.
- **Maximum instances**: Configurable (default 25).

```bash
# Describe current auto scaling configuration
aws apprunner describe-auto-scaling-configuration \
  --auto-scaling-configuration-arn $AUTO_SCALING_ARN \
  --region $REGION \
  --output json
```

Operators SHOULD note:

- Because App Runner cannot scale to zero, idle services still incur cost for the minimum instance.
- Concurrency-based scaling differs from CPU/memory-based scaling in ECS — workloads with high CPU but low concurrency MAY not scale correctly.

---

## VPC Connector Gotchas

When a VPC connector is attached to an App Runner service, operators MUST understand these behaviors:

### 1. Routes ALL Outbound Traffic Through VPC

The VPC connector routes **all** outbound traffic from the service through the specified subnets. There is no split-tunneling — public internet access is lost unless the VPC has a NAT gateway.

### 2. No Static Outbound IP

App Runner with a VPC connector does NOT provide a static outbound IP address. If downstream services require IP allowlisting, operators MUST place a NAT gateway with an Elastic IP in the VPC.

### 3. Boot-Time Dependency Failures

If **your application code** depends on AWS APIs or external endpoints during startup (e.g., fetching configuration from DynamoDB, calling an external API), and the VPC lacks proper routing, the service WILL fail to start with timeout errors.

> **Important:** App Runner's own managed actions — pulling source code and container images, pushing logs, and retrieving secrets referenced in the service configuration — are NOT routed through your VPC connector. This traffic traverses AWS-managed networking. You do NOT need VPC endpoints for ECR, CloudWatch Logs, or Secrets Manager to support App Runner's internal operations.
>
> Source: [Enabling VPC access for outgoing traffic](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html): *"App Runner traffic — App Runner manages several actions on your behalf, such as pulling source code and images, pushing logs, and retrieving secrets. The traffic that these actions generate isn't routed through your VPC."*

VPC endpoints or a NAT gateway are required ONLY for traffic originating from **your application code at runtime**. The following apply only if your container code calls these services:

| Requirement | Purpose (applies only to application-code traffic) |
|---|---|
| NAT gateway in public subnet | Outbound access to the public internet from your application code |
| VPC endpoint for an AWS service (e.g., DynamoDB, SQS, S3) | Private access to an AWS service your application code calls at runtime |
| VPC endpoint for Secrets Manager | Only if your application code calls Secrets Manager directly at runtime (NOT needed for App Runner's managed secret injection) |
| VPC endpoint for SSM Parameter Store | Only if your application code calls Parameter Store directly at runtime |

### 4. AWS Services Need VPC Endpoints or NAT

With a VPC connector, calls to AWS services (DynamoDB, SQS, S3, etc.) MUST route through either:

- A VPC endpoint for that service, OR
- A NAT gateway

Without one of these, API calls to AWS services WILL time out.

---

## Migration Guide: App Runner to ECS Express Mode

### Overview

The recommended migration strategy uses DNS weighted routing to shift traffic gradually from App Runner to ECS Express Mode.

### High-Level Steps

1. **Deploy ECS Express Mode service** with the same container image and environment variables.
2. **Validate** the ECS Express Mode service independently (health checks, functional tests).
3. **Configure Route 53 weighted routing**:
   - Create a weighted record for the App Runner custom domain endpoint (weight: 100).
   - Create a weighted record for the ECS Express Mode ALB endpoint (weight: 0).
4. **Gradually shift traffic** by adjusting weights (e.g., 90/10 → 70/30 → 50/50 → 0/100).
5. **Monitor** error rates, latency, and logs at each step before increasing ECS weight.
6. **Decommission** the App Runner service once 100% traffic is on ECS Express Mode.

```bash
# Example: Update Route 53 weighted record to shift 20% traffic to ECS
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "'"$DOMAIN_NAME"'",
          "Type": "A",
          "SetIdentifier": "ecs-express",
          "Weight": 20,
          "AliasTarget": {
            "HostedZoneId": "'"$ALB_HOSTED_ZONE_ID"'",
            "DNSName": "'"$ALB_DNS_NAME"'",
            "EvaluateTargetHealth": true
          }
        }
      }
    ]
  }' \
  --region $REGION \
  --output json
```

Operators SHOULD:

- Run both services in parallel for at least one full traffic cycle before completing cutover.
- Compare App Runner and ECS Express Mode metrics side-by-side during migration.
- Keep the App Runner service running (but at minimum scale) as a rollback target until confident.

---

## Security Considerations

Both App Runner and ECS Express Mode expose **public HTTPS endpoints by default** with no built-in authentication. Operators MUST address the following security controls.

> Source: [App Runner security](https://docs.aws.amazon.com/apprunner/latest/dg/security.html), [ECS security best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/security.html), [Express Mode best practices](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html)

### Authentication and Authorization

- App Runner and ECS Express Mode provide **no built-in authentication**. Services are publicly accessible by default. Source: [Enabling Private endpoint for incoming traffic](https://docs.aws.amazon.com/apprunner/latest/dg/network-pl.html): *"By default when you create an AWS App Runner service, the service is accessible over the internet."*
- Operators MUST implement authentication at the application layer (e.g., JWT validation, OAuth 2.0) or place an API Gateway with authorizers in front of the service.
- For internal-only services, use private subnets with an internal ALB. ECS Express Mode provisions an internal ALB when private subnets are provided via `--network-configuration`. Source: [Express Mode network configuration defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html): *"If you provide private subnets (subnets without an internet gateway in their route table), Express Mode will provision an internal ALB."*

### Secret Management

- **MUST NOT** pass secrets via the `environment` field in container definitions — environment variables are visible in plaintext in ECS task definitions.
- **MUST** use the `secrets` field in `primaryContainer`, referencing AWS Secrets Manager or SSM Parameter Store:

```json
"secrets": [{"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret"}]
```

- Source: [ExpressGatewayContainer API — `secrets` field](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ExpressGatewayContainer.html): *"The secrets to pass to the container. Type: Array of Secret objects."*
- App Runner supports managed secret injection via service configuration — these secrets are retrieved by App Runner's managed infrastructure, not through your VPC. Source: [Enabling VPC access for outgoing traffic](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html)
- Operators SHOULD enable automatic secret rotation in Secrets Manager. Source: [Express Mode best practices — Secrets management](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html)

### IAM Least Privilege

- The task execution role SHOULD use the AWS-managed `AmazonECSTaskExecutionRolePolicy`. Avoid broader policies.
- The infrastructure role SHOULD use the AWS-managed `AmazonECSInfrastructureRoleforExpressGatewayServices` policy.
- The task role (`--task-role-arn`) MUST follow least privilege — grant only the specific actions and resources the application requires. Avoid `*FullAccess` policies and `service:*` wildcards.
- Source: [Express Mode IAM role defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)

### Encryption

- **In transit**: Both App Runner and ECS Express Mode enforce HTTPS/TLS by default. Express Mode auto-provisions an ACM certificate and configures an HTTPS listener on port 443. Source: [Express Mode ALB defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html): *"listener-configurations.protocol: https"*
- **At rest**: Operators SHOULD enable KMS encryption on CloudWatch Logs log groups, ECR repositories, and any data stores the application uses. Secrets Manager encrypts secrets at rest by default using either an AWS-managed or customer-provided KMS key.

### Network Security

- ECS Express Mode auto-creates security groups scoped to ALB → task traffic. The LB Security Group allows inbound HTTPS (443) and outbound to the task on the container port only. Source: [Express Mode network configuration defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)
- When providing custom security groups via `--network-configuration`, operators MUST NOT use `0.0.0.0/0` for inbound rules on non-public services. Scope inbound to specific CIDR ranges or security group references.
- Operators SHOULD enable VPC Flow Logs for network traffic monitoring. Source: [Express Mode best practices — Network security](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html)

### AWS WAF

- Operators SHOULD attach an AWS WAF WebACL for defense in depth against common web exploits:
  - **App Runner**: Supports direct WAF web ACL association. Source: [Associating an AWS WAF web ACL with your service](https://docs.aws.amazon.com/apprunner/latest/dg/waf.html)
  - **ECS Express Mode**: Associate a WAF WebACL to the ALB via `aws wafv2 associate-web-acl --resource-arn <alb-arn>`. Source: [Express Mode best practices — Network security](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html)

### Security Headers

- Applications SHOULD return standard security headers in HTTP responses:
  - `Strict-Transport-Security` (HSTS) — prevents protocol downgrade attacks
  - `Content-Security-Policy` (CSP) — mitigates XSS attacks
  - `X-Frame-Options` — prevents clickjacking
  - `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing
- These headers are set at the application level. Neither App Runner nor the Express Mode ALB adds them automatically.

### Input Validation and Rate Limiting

- Operators SHOULD implement input validation and rate limiting at the application layer.
- App Runner's `MaxConcurrency` setting (default: 100) provides per-instance request throttling but is not a substitute for application-level rate limiting.
- For stricter controls, operators MAY place API Gateway in front of the service for managed throttling, or use AWS WAF rate-based rules.

### Logging and Monitoring

- **ALB access logs**: Disabled by default in Express Mode (`access-logs.enabled: false`). Operators SHOULD enable access logs on the ALB and direct them to an S3 bucket with encryption. Source: [Express Mode ALB defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)
- **CloudWatch alarms**: Operators SHOULD create alarms for 5XX error rates, latency P99, and unhealthy host count. Express Mode auto-creates a metric alarm for detecting faulty deployments.
- **CloudTrail**: Verify CloudTrail is enabled for API-level audit logging in the target account and region.
- **Sensitive data**: Operators MUST NOT log sensitive data (credentials, PII, tokens) in application logs. SHOULD enable KMS encryption on CloudWatch Logs log groups.
- Source: [Express Mode best practices — Monitoring and logging](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html)
