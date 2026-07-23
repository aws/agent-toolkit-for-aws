# Failure Mode Assessment Workflow

## Overview

This SOP guides you through running Resilience Hub v2 failure mode assessments, interpreting findings, triaging by severity, working with service functions, resolving findings, and generating reports. Use after initial setup is complete and a service has input sources configured.

## Parameters

**service_arn** (required): ARN of the service to assess
**finding_id** (optional): Specific finding ID to resolve or investigate
**report_type** (optional, default: "FAILURE_MODE"): Report type — use FAILURE_MODE for this workflow (check `aws resiliencehubv2 create-report help` for any other report types)

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify that either the AWS CLI (e.g., `command -v aws`) or the AWS MCP server's `call_aws` tool is available
- You MUST NOT run any AWS service or mutation commands (e.g., `start-failure-mode-assessment`) during verification — only check that the tooling is present
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools

### 2. Check Assessment Cost

Verify the estimated cost before running an assessment.

**Constraints:**

- You SHOULD point the user to the official AWS Resilience Hub pricing page (https://aws.amazon.com/resilience-hub/pricing/) for current costs — do not summarize or quote specific pricing details (base fees, resource thresholds, per-resource overage, or add-ons) as they may change.
- You SHOULD retrieve the service's own pre-assessment estimate from `aws resiliencehubv2 get-service --service-arn {service_arn}`, which returns an `estimatedAssessmentCost` object (`amount` + `currency`) — present that to the user as the API's estimate. If it is absent (e.g., resource discovery has not run yet), fall back to the pricing page above.
- You MUST ask for explicit confirmation before running the (billable) assessment

### 3. Start Failure Mode Assessment

Run the asynchronous assessment.

**Constraints:**

- You MUST inform the user that you are starting a failure mode assessment
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 start-failure-mode-assessment --service-arn {service_arn}`
- You MUST inform the user that the assessment performs: resource discovery, topology mapping, service function identification, failure mode analysis, and finding generation

### 4. Poll Assessment Status

Wait for the assessment to complete.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-failure-mode-assessments --service-arn {service_arn}`
- You MUST poll until status is SUCCESS or FAILED
- You MUST NOT proceed to findings review until status is SUCCESS
- You MUST inform the user if the assessment fails and suggest checking input source validity
- You SHOULD inform the user that assessments run asynchronously and typically take several minutes to tens of minutes (often ~10 min, longer for large services) — poll for completion rather than expecting a fixed time
- You SHOULD wait at least 30 seconds between polling attempts to avoid throttling the API, and stop polling and inform the user if no terminal status (SUCCESS or FAILED) is reached after roughly 60 minutes

### 5. Retrieve and Triage Findings

Get findings and present them organized by severity and action required.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-failure-mode-findings --service-arn {service_arn}` — this returns a SUMMARY per finding: findingId, name, description, failureCategory, severity, status, policyComponent
- You MUST present findings grouped by severity, highest first (HIGH, then MEDIUM, then LOW)
- For full detail, You MUST call `aws resiliencehubv2 get-failure-mode-finding --service-arn {service_arn} --finding-id {finding_id}` per finding; only this returns `reasoning` plus `infrastructureAndCodeRecommendations`, `observabilityRecommendations`, and `testingRecommendations` (list-failure-mode-findings does NOT return these)
- You MUST read achievability from the service/assessment (`get-service` or `list-failure-mode-assessments`), per policyComponent as returned by the API (illustratively `AVAILABILITY_SLO`, `MULTI_AZ_DISASTER_RECOVERY`, `MULTI_REGION_DISASTER_RECOVERY`, `DATA_RECOVERY` — verify the full set from the `get-service` response rather than assuming a fixed list) — achievability (ACHIEVABLE / NOT_ACHIEVABLE) is NOT a per-finding field
- You MUST apply the priority matrix:
  - HIGH severity + relevant policy component NOT_ACHIEVABLE → Fix architecture immediately
  - HIGH severity + ACHIEVABLE → Design FIS experiment to validate
  - MEDIUM → Plan remediation this sprint
  - LOW → Track but don't block
- If `get-service` / `list-failure-mode-assessments` reports a `policyComponent` not listed above (the service may add components over time), do NOT ignore it: consult the current AWS Resilience Hub v2 documentation or the `get-service` response for the full set of supported policy components, and triage it by its achievability and severity like any other.
- You MUST map the finding's failureCategory (the SEEMS framework) to next actions:
  - SINGLE_POINT_OF_FAILURE → add redundancy / eliminate the SPOF (multi-AZ or multi-region), then validate with FIS
  - SHARED_FATE → reduce shared dependencies / isolate fate domains (cell-based, bulkheads)
  - EXCESSIVE_LOAD → add capacity / autoscaling / load shedding or throttling
  - EXCESSIVE_LATENCY → reduce latency (caching, timeouts, connection pooling, dependency tuning)
  - MISCONFIGURATION_AND_BUGS → fix the config/code defect; add validation/tests and safer deployments
  - If a finding's `failureCategory` is not one of the values above (the service may add categories over time), do NOT ignore the finding: consult the current AWS Resilience Hub v2 documentation (e.g., `aws resiliencehubv2 get-failure-mode-finding help` or the service docs) for how to address it, and triage it by severity and achievability like any other finding.

### 6. Review Service Functions

Examine AI-generated service functions and refine if needed.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-service-functions --service-arn {service_arn}`
- You MUST present the AI-generated service functions to the user for review
- If the user wants to update a service function, You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 update-service-function --service-arn {service_arn} --service-function-id {id} --name {name} --criticality {criticality}`
- You MUST inform the user that updating a service function changes its source field from AI_GENERATED to USER
- You SHOULD explain that criticality is set from the API's current criticality enum — **verify the valid values via `aws resiliencehubv2 update-service-function help` or the service docs** rather than assuming a fixed set (illustratively `PRIMARY`/`SUPPLEMENTAL`). Note there is no service-function "type" parameter
- To reassign which resources a service function owns, You MAY call `aws resiliencehubv2 create-service-function-resources --service-arn {service_arn} --service-function-id {id} --resources '["resource-id-1","resource-id-2"]'` (and `delete-service-function-resources` to remove); these adjust only the service function's resource set — there is still no `type` parameter

### 7. Explore Topology

View resource connectivity to understand blast radius.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-service-topology-edges --service-arn {service_arn}`
- You MUST present the topology as source → destination edges
- You SHOULD explain how topology helps understand cascading failure impact

### 8. Resolve Findings

Mark findings as resolved after remediation is complete.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 update-failure-mode-finding --service-arn {service_arn} --finding-id {finding_id} --status {status} --comment "{resolution_comment}"` (typically `RESOLVED` after remediation; choose `{status}` per the status guidance below)
- You MUST include a meaningful comment describing what was fixed and how it was validated
- Finding status is set from the API's current status enum — **confirm the valid values via `aws resiliencehubv2 update-failure-mode-finding help` or the service docs** rather than relying on a hardcoded list (illustratively `OPEN`/`RESOLVED`/`IRRELEVANT`). If a finding does not apply to the user's use case (rather than being fixed), they SHOULD mark it not-applicable (e.g. `IRRELEVANT`) with a comment explaining why, instead of `RESOLVED`.
- You SHOULD reference the FIS experiment ID if the fix was validated through chaos testing

### 9. Generate Report

Create an exportable report from assessment results.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-report --service-arn {service_arn} --report-type {report_type}`
- You MUST set the report type to FAILURE_MODE for this workflow (check `aws resiliencehubv2 create-report help` for any other supported report types)
- You MUST poll with `aws resiliencehubv2 list-reports --service-arn {service_arn}` until status is SUCCEEDED or FAILED
- You SHOULD wait at least 30 seconds between polling attempts to avoid throttling the API, and stop polling and inform the user if no terminal status is reached after roughly 60 minutes
- You MUST inform the user that report output location is configured via the service's reportConfiguration (S3 bucket path)
- You SHOULD recommend the S3 bucket used for report output has server-side encryption enabled (SSE-S3 or SSE-KMS) and blocks public access — assessment reports may contain sensitive architectural details — and a bucket policy requiring `aws:SecureTransport` (TLS) to enforce encryption in transit for all access, scoped with `aws:SourceArn` / `aws:SourceAccount` condition keys so only this service's Resilience Hub principal can write, and S3 server access logging for an access audit trail.
- You SHOULD recommend encrypting any CloudWatch Logs log groups that capture Resilience Hub assessment data with a KMS key (`aws logs associate-kms-key`), since findings and topology can reveal sensitive architectural detail
- You MUST check for `reportOutput.s3ReportOutput.s3ObjectKey` on success or `failedReportOutput.errorCode` on failure; surface the returned `errorCode` to the user (illustratively `INSUFFICIENT_PERMISSIONS`/`CONFIGURATION_ERROR`/`INTERNAL_ERROR`) and consult the `create-report`/`list-reports` documentation for the full set — handle any unrecognized code gracefully rather than assuming a fixed list

## Examples

```bash
# Run assessment
aws resiliencehubv2 start-failure-mode-assessment --service-arn arn:aws:resiliencehub:us-east-1:123456789012:service/checkout-api

# Check status
aws resiliencehubv2 list-failure-mode-assessments --service-arn arn:aws:resiliencehub:us-east-1:123456789012:service/checkout-api

# Get findings
aws resiliencehubv2 list-failure-mode-findings --service-arn arn:aws:resiliencehub:us-east-1:123456789012:service/checkout-api

# Resolve a finding
aws resiliencehubv2 update-failure-mode-finding \
  --service-arn arn:aws:resiliencehub:us-east-1:123456789012:service/checkout-api \
  --finding-id finding-abc123 --status RESOLVED \
  --comment "Fixed: added multi-AZ Aurora replica. Validated with FIS experiment EXP-xyz on 2026-05-20."

# Generate report
aws resiliencehubv2 create-report --service-arn arn:aws:resiliencehub:us-east-1:123456789012:service/checkout-api --report-type FAILURE_MODE
```

## Troubleshooting

**Assessment fails immediately**
Check that input sources are valid and the service has at least one configured. Use `aws resiliencehubv2 list-input-sources --service-arn {service_arn}`.

**No findings generated**
The service may have no discoverable resources, or the architecture already meets all policy targets. Verify input sources point to deployed infrastructure.

**Report generation fails with INSUFFICIENT_PERMISSIONS**
The service's reportConfiguration references an S3 bucket that the invoker role cannot write to. Update the bucket policy or the service's IAM configuration.
