# Setup AWS Resilience Hub v2

## Overview

This SOP guides you through first-time Resilience Hub v2 setup: creating a resilience policy with SLO targets, registering a system and user journey, onboarding a service with input sources, and running your first failure mode assessment.

## Parameters

**service_name** (required): Name for the service to onboard (e.g., "checkout-api")
**policy_name** (required): Name for the resilience policy (e.g., "tier-1-critical")
**system_name** (required): Name for the top-level system (e.g., "payment-platform")
**journey_name** (required): Name for the user journey (e.g., "customer-checkout")
**availability_target** (required): Availability SLO percentage — any value between 0 and 100 (e.g., 99.99). Common tiers are 99.9 / 99.95 / 99.99, but `create-policy` accepts any value in that range — do NOT reject other values (e.g., 99.5 or 99.999 are valid).
**multi_az_rto** (required): Multi-AZ RTO in minutes (e.g., 5)
**multi_az_rpo** (required): Multi-AZ RPO in minutes (e.g., 1)
**multi_region_rto** (optional): Multi-Region RTO in minutes (e.g., 30)
**multi_region_rpo** (optional): Multi-Region RPO in minutes (e.g., 5)
**multi_az_dr_approach** (optional, default: "ACTIVE_ACTIVE"): DR approach for multi-AZ — ACTIVE_ACTIVE, HOT_STANDBY, WARM_STANDBY, PILOT_LIGHT, or BACKUP_AND_RESTORE
**multi_region_dr_approach** (optional, default: "HOT_STANDBY"): DR approach for multi-Region — ACTIVE_ACTIVE, HOT_STANDBY, WARM_STANDBY, PILOT_LIGHT, or BACKUP_AND_RESTORE
> The `disasterRecoveryApproach` values listed above are the valid enum values. If `create-policy` rejects a value, confirm the current set with `aws resiliencehubv2 create-policy help` rather than assuming this list is exhaustive.
**invoker_role_name** (required): IAM role name Resilience Hub v2 assumes for resource discovery (trust principal `resiliencehub.amazonaws.com` + managed policy `AWSResilienceHubAsssessmentExecutionPolicy`).
**regions** (required): JSON array of AWS regions (e.g., '["us-east-1","us-west-2"]')
**input_source_type** (required): One of cfn_stack, resource_tags, terraform, eks
**input_source_identifier** (required): Stack ARN, tag key/value pair, TF state URI, or EKS cluster ARN
**system_description** (optional): Description for the system (e.g., "Platform handling all payment services")
**journey_description** (optional): Description for the user journey (e.g., "End-to-end checkout flow")
**aws_region** (optional, default: "us-east-1"): Primary AWS region

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify that either the AWS CLI (e.g., `aws --version`) or the AWS MCP server's `call_aws` tool is available
- You SHOULD recommend the customer use IAM roles (instance profiles, SSO session credentials, or `aws sts assume-role`) rather than long-lived IAM access keys, and never store such keys in shell history, scripts, or environment variables without time-bound session tokens
- You MUST NOT call any AWS service APIs (e.g., `aws resiliencehubv2 ...`) during verification — only local checks such as `aws --version` are permitted, since running AWS service operations during verification could create or mutate resources
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort
- The command templates in Steps 2–10 omit `--region` for brevity; you MUST either add `--region {aws_region}` to each command or confirm the caller's default region is `{aws_region}` before running, so resources are created in the intended region (parameter defaults to `us-east-1`)

### 2. Create Resilience Policy

Create a policy defining SLO targets that drive all subsequent assessments.

**Constraints:**

- You MUST inform the customer that you are creating a resilience policy with their specified targets
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-policy --name {policy_name} --availability-slo target={availability_target} --multi-az rtoInMinutes={multi_az_rto},rpoInMinutes={multi_az_rpo},disasterRecoveryApproach={multi_az_dr_approach} --multi-region rtoInMinutes={multi_region_rto},rpoInMinutes={multi_region_rpo},disasterRecoveryApproach={multi_region_dr_approach}`
- You MUST omit the `--multi-region` flag entirely if `multi_region_rto` / `multi_region_rpo` are not provided (never emit empty `rtoInMinutes=`)
- You MUST capture the policyArn from the response for use in subsequent steps
- You MUST NOT set a DR approach that contradicts the customer's actual architecture (e.g., ACTIVE_ACTIVE when they have BACKUP_AND_RESTORE)
- You SHOULD recommend starting with availability SLO as the primary driver — it determines everything else
- You SHOULD advise that multi-AZ targets should be aggressive (minutes) while multi-region targets can be more relaxed

### 3. Create System

Create the top-level organizational unit that groups related services.

**Constraints:**

- You MUST inform the customer that you are creating a system
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-system --name {system_name} --description "{system_description}"`
- You MUST capture the systemArn from the response
- You MUST NOT pass --dependency-discovery to create-system (no such parameter); dependency discovery is enabled on create-service in Step 5
- You MUST inform the customer that dependency discovery automatically maps cross-service dependencies

### 4. Create User Journey

Map a business-critical path to the system with an associated policy.

**Constraints:**

- You MUST inform the customer that you are creating a user journey
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-user-journey --system-arn {system_arn} --name {journey_name} --policy-arn {policy_arn} --description "{journey_description}"`
- You MUST associate the journey with the policy created in Step 2
- You MUST capture the userJourneyId from the response

### 5. Create Service

Register the service that will be assessed.

**Constraints:**

- You MUST inform the customer that you are registering their service
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-service --name {service_name} --regions {regions} --associated-systems '[{"systemArn":"{system_arn}","userJourneyIds":["{journey_id}"]}]' --policy-arn {policy_arn} --permission-model invokerRoleName={invoker_role_name} --dependency-discovery ENABLED`
- You MUST include --permission-model (REQUIRED); ensure the invoker role exists first and allow ~60-90s for it to become assumable — retry on `Cannot assume invoker role`
- You MUST capture the serviceArn from the response
- You MUST associate the service with the system and user journey created in previous steps

### 6. Add Input Sources

Tell Resilience Hub v2 where to discover resources for this service.

**Constraints:**

- You MUST inform the customer that you are adding input sources for resource discovery
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-input-source --service-arn {service_arn} --resource-configuration {config}`
- You MUST map input_source_type to the correct resource-configuration format:
  - cfn_stack → `{"cfnStackArn":"arn:aws:cloudformation:..."}`
  - resource_tags → `{"resourceTags":[{"key":"{tag_key}","values":["{tag_value}"]}]}`
  - terraform → `{"tfStateFileUrl":"s3://..."}` (recommend the S3 bucket hosting Terraform state use server-side encryption — SSE-KMS — a bucket policy requiring `aws:SecureTransport` for TLS, and S3 server access logging for an access audit trail)
  - eks → `{"eks":{"clusterArn":"...","namespaces":["..."]}}`
- You MUST add at least one input source before running an assessment

### 7. Run Failure Mode Assessment

Start the asynchronous assessment that analyzes the service against policy targets.

**Constraints:**

- You MUST inform the customer that you are starting a failure mode assessment
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 start-failure-mode-assessment --service-arn {service_arn}`
- You MUST poll with `aws resiliencehubv2 list-failure-mode-assessments --service-arn {service_arn}` until status is SUCCESS or FAILED
- You MUST NOT proceed to findings review until assessment completes
- You SHOULD inform the customer that assessments run asynchronously and typically take several minutes to tens of minutes (often ~10 min, longer for large services) — poll for completion rather than expecting a fixed time

### 8. Review Findings

Retrieve and present assessment results grouped by severity.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-failure-mode-findings --service-arn {service_arn}` (returns a summary per finding); call `aws resiliencehubv2 get-failure-mode-finding --service-arn {service_arn} --finding-id {finding_id}` for full detail
- You MUST present findings grouped by severity (High, Medium, Low) — there is no Critical severity
- You MUST include the recommendations from get-failure-mode-finding (infrastructureAndCodeRecommendations, observabilityRecommendations, testingRecommendations) — these are NOT returned by list-failure-mode-findings
- You MUST read achievability from the service/assessment (`get-service` / `list-failure-mode-assessments`), per policy component — if NOT_ACHIEVABLE, architecture changes are needed before testing (achievability is not a per-finding field)
- You SHOULD suggest next steps based on the finding's failureCategory (the SEEMS framework):
  - SINGLE_POINT_OF_FAILURE / SHARED_FATE → add redundancy or isolate fate domains, then validate with FIS
  - EXCESSIVE_LOAD / EXCESSIVE_LATENCY → add capacity/scaling or reduce latency
  - MISCONFIGURATION_AND_BUGS → fix config/code, add validation and safer deployments

### 9. Document Assertions (Optional)

Record resilience assertions that inform the assessment.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-assertion --service-arn {service_arn} --text "{assertion_text}"`
- You SHOULD suggest documenting assertions about DR approach, scaling behavior, and operational procedures
- You MUST inform the customer that assertions have a `source` field (AI_GENERATED or USER); manually created ones are USER

### 10. Generate Report (Optional)

Generate an exportable report and save to S3.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-report --service-arn {service_arn} --report-type FAILURE_MODE`
- You MUST use the only supported report type: FAILURE_MODE
- You MUST poll with `aws resiliencehubv2 list-reports --service-arn {service_arn}` until status is a terminal state (SUCCEEDED or FAILED)
- You MUST NOT report success on a FAILED status — surface the failure to the customer and investigate/retry the report generation
- You MUST inform the customer that the report output location is configured via the service's reportConfiguration (S3 bucket path)
- You SHOULD recommend the reportConfiguration S3 bucket use SSE-KMS encryption, a bucket policy enforcing TLS (`aws:SecureTransport`), S3 server access logging for an access audit trail, and access restricted to authorized personnel — assessment reports can contain sensitive architecture detail (resource ARNs, topology, failure modes)

## Examples

```bash
# Create the invoker role first (trust policy per AWS Resilience Hub v2 docs)
aws iam create-role --role-name rh-invoker \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"resiliencehub.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"123456789012"},"ArnLike":{"aws:SourceArn":"arn:aws:resiliencehub:*:123456789012:*"}}}]}'
aws iam attach-role-policy --role-name rh-invoker --policy-arn arn:aws:iam::aws:policy/AWSResilienceHubAsssessmentExecutionPolicy

# Create a Tier-1 policy
aws resiliencehubv2 create-policy \
  --name "tier-1-critical" \
  --availability-slo target=99.99 \
  --multi-az rtoInMinutes=5,rpoInMinutes=1,disasterRecoveryApproach=ACTIVE_ACTIVE \
  --multi-region rtoInMinutes=30,rpoInMinutes=5,disasterRecoveryApproach=HOT_STANDBY

# Create system and journey
aws resiliencehubv2 create-system --name "payment-platform"
aws resiliencehubv2 create-user-journey --system-arn {system_arn} --name "customer-checkout" --policy-arn {policy_arn}

# Register service with CFN input source
aws resiliencehubv2 create-service --name "checkout-api" --regions '["us-east-1","us-west-2"]' --associated-systems '[{"systemArn":"{system_arn}","userJourneyIds":["{journey_id}"]}]' --policy-arn {policy_arn} --permission-model invokerRoleName=rh-invoker --dependency-discovery ENABLED
aws resiliencehubv2 create-input-source --service-arn {service_arn} \
  --resource-configuration '{"cfnStackArn":"arn:aws:cloudformation:us-east-1:123456789012:stack/checkout-stack/abc"}'

# Run assessment and check findings
aws resiliencehubv2 start-failure-mode-assessment --service-arn {service_arn}
aws resiliencehubv2 list-failure-mode-findings --service-arn {service_arn}
```

## Troubleshooting

**Assessment stuck in IN_PROGRESS**
Assessments run asynchronously and typically take several minutes to tens of minutes (often ~10 min). If it runs much longer (e.g. >30 min), check that input sources point to valid resources and that the service has appropriate IAM permissions for resource discovery.

**No resources discovered**
Verify input sources point to valid CloudFormation stacks or tagged resources in the correct region. Use `aws resiliencehubv2 list-input-sources --service-arn {service_arn}` to confirm sources are configured.

**Achievability says NOT_ACHIEVABLE**
The current architecture cannot meet the policy targets. This requires infrastructure changes (adding redundancy, multi-region deployment) before testing can validate resilience.
