# Troubleshoot CloudFormation Deployment

## Overview

Deterministic procedure for diagnosing a CloudFormation stack deployment failure. Pulls the stack status, failed events, and a filtered CloudTrail time window, then matches evidence against known failure patterns to produce a prioritized root cause and template-level fix.

## Parameters

- **stack_name** (required): The name or ARN of the failed CloudFormation stack. Accept the ARN if the stack has been deleted so the user can still investigate via `StackId`.
- **region** (required): AWS region where the stack was deployed (e.g., `us-east-1`).
- **include_cloudtrail** (optional, default: "true"): Whether to correlate with CloudTrail events. Set to "false" to skip CloudTrail lookup (faster but less context).

**Constraints for parameter acquisition:**
- You MUST ask for all required parameters upfront in a single prompt
- You MUST support multiple input methods for the stack identifier:
  - Stack name (if the stack still exists)
  - Stack ARN (if the stack has been deleted and the user has the ARN)
- You MUST confirm the region before any API calls because CloudFormation is a regional service and calling the wrong region returns "Stack not found"

## Steps

### 1. Verify Dependencies

Check that AWS CLI and credentials are usable, and that the principal has required read permissions.

**Constraints:**
- You MUST check in this order of preference:
  1. `call_aws` tool from the AWS MCP Server (preferred for sandboxed execution, audit logging, and observability)
  2. AWS CLI (`aws`) available on the user's system (verify with `which aws` or `aws --version`)
- You MUST verify the user has valid AWS credentials configured for the target region (e.g., `aws sts get-caller-identity --region <region>`). This read-only call is acceptable because it does not modify anything
- You MUST ONLY check for availability and credential validity. You MUST NOT install missing dependencies during this step because installation modifies the user's environment
- If the AWS CLI is missing, You MUST ask the user explicitly before running any install command, using a prompt like: "I can install the AWS CLI via `<platform-specific command>`. Do you want me to install it, or would you prefer to install it manually?"
- You MUST NOT run install commands without explicit user approval because this changes the user's environment
- If credentials are missing or invalid, You MUST ask the user to configure credentials and MUST NOT proceed until credentials are confirmed
- The caller MUST have at minimum: `cloudformation:DescribeStacks`, `cloudformation:DescribeEvents`, `cloudtrail:LookupEvents`. You SHOULD warn the user if `iam:SimulatePrincipalPolicy` is also unavailable because it limits how deeply you can diagnose permission-related failures

### 2. Get Stack Status

Fetch the current stack state.

**Constraints:**
- You MUST call `aws cloudformation describe-stacks --stack-name <name_or_arn> --region <region>`
- You MUST capture the `StackStatus`, `StackStatusReason`, `LastUpdatedTime`, and `StackId` fields
- If the stack is not found and the user provided a name, You MUST ask whether the stack may have been deleted (in which case the user needs to provide the Stack ARN)
- If the stack is in a success state (`CREATE_COMPLETE`, `UPDATE_COMPLETE`), You MUST inform the user the stack is healthy and ask whether they want to investigate a different stack or a past failure (which requires reviewing historical events)

### 3. Fetch Failed Events

Retrieve only the failed events using the `FailedEvents` filter.

**Constraints:**
- You MUST call `aws cloudformation describe-events --stack-name <name_or_arn> --filters FailedEvents=true --region <region>` because the filter returns only `PROVISIONING_ERROR` and `VALIDATION_ERROR` event types which are the relevant signals for root-cause analysis
- You MUST NOT use `aws cloudformation describe-stack-events` for root-cause analysis because it returns every event without filtering and buries the actual failures in noise
- You MUST capture for each failed event: `LogicalResourceId`, `PhysicalResourceId`, `ResourceType`, `ResourceStatus`, `ResourceStatusReason`, `Timestamp`, `EventType`
- If no failed events are returned, You MUST fall back to `describe-events` without the filter to find the earliest status change, because some failures surface as non-FAIL events (e.g., stuck in `IN_PROGRESS`)
- You MUST sort events chronologically and identify the FIRST failure, because subsequent failures are often cascading consequences of the first
- If a failed event has `ResourceType: AWS::CloudFormation::Stack`, You MUST recursively call `describe-events --stack-name <PhysicalResourceId> --filters FailedEvents=true --region <region>` to retrieve the nested stack's failed events, because the parent stack's `ResourceStatusReason` is generic and the actionable error is only visible in the nested stack

### 4. Match Failure Patterns

Compare the failure message against known patterns to propose a diagnosis.

**Constraints:**
- You MUST evaluate each failure message against these common patterns:
  - `is not authorized to perform` → IAM permission gap
  - `already exists` → resource name conflict
  - `Invalid` / `does not match pattern` → property validation failure
  - `Rate exceeded` / `Throttling` → API throttling
  - `timed out` → resource creation took too long; possibly quota or dependency issue
  - `DELETE_FAILED` with `is not empty` → stateful resource has data
  - `Requested resource not found` → referenced resource (AMI, KMS key, IAM role) does not exist in this region/account
  - `cannot be deleted` → resource has deletion protection enabled or is in use by another resource/service
- If the message matches none of the above, You SHOULD categorize it as "service-specific" and inspect `ResourceType` to consult the relevant service's documentation
- You SHOULD identify the FIRST failed event as the root cause candidate, because later failures are typically cascading

### 5. Correlate CloudTrail (Optional but Recommended)

Pull CloudTrail events in a ±60 second window around the first failure to find the underlying AWS API error.

**Constraints:**
- You MUST skip this step if the user set `include_cloudtrail=false` or if `cloudtrail:LookupEvents` permission is missing
- You MUST compute the time window as `Timestamp - 60s` to `Timestamp + 60s` using the first failed event's timestamp, because CloudFormation issues API calls within seconds of recording the failure
- You MUST call `aws cloudtrail lookup-events --start-time <start> --end-time <end> --region <region> --max-results 50`
- You MUST filter the returned events client-side to those where:
  - `CloudTrailEvent.errorCode` is non-empty OR `CloudTrailEvent.errorMessage` is non-empty
- For each matching event, You MUST extract: `EventName`, `EventTime`, `errorCode`, `errorMessage`, `Username`
- You SHOULD provide a CloudTrail console deeplink scoped to the failure window so the user can browse additional context:
  - Format: `https://console.aws.amazon.com/cloudtrailv2/home?region=<region>#/events?StartTime=<start>&EndTime=<end>&ReadOnly=false`
  - Note: Console domain varies by partition (e.g., `console.amazonaws.cn` for China regions, `console.amazonaws-us-gov.com` for GovCloud)
- If no matching CloudTrail events are found, You MUST note this and continue — not all failures produce CloudTrail-visible errors

### 6. Present Root Cause and Fix

Synthesize the stack event, pattern match, and CloudTrail correlation into a prioritized diagnosis.

**Constraints:**
- You MUST lead with the root cause of the FIRST failed event, because cascading failures often disappear once the first is fixed
- You MUST classify each fix as either:
  - **Template-level** (change the template, redeploy): missing required property, invalid enum, name conflict, cyclic `DependsOn`
  - **Environment-level** (fix outside the template): IAM permission, service quota, resource state
- For template-level fixes, You MUST provide the specific YAML/JSON change showing the corrected property
- For environment-level fixes, You MUST provide the specific AWS CLI command or IAM statement to apply
- You MUST NOT propose template changes for environment-level issues because that wastes cycles and does not resolve the underlying problem
- You MUST show the CloudTrail console deeplink when CloudTrail events were retrieved
- You SHOULD surface all failed events (not just the first) so the user can see cascading consequences, but clearly mark which is the root cause vs. downstream effects

### 7. Recommend Next Steps

Guide the user toward recovery.

**Constraints:**
- If the fix is template-level, You SHOULD recommend running a pre-deployment validation pipeline (cfn-lint → cfn-guard → change set validation) on the corrected template before redeploying, because re-deploying a broken template reruns the failure cycle
- If the fix is environment-level, You MUST NOT recommend redeploying until the environment issue is confirmed resolved
- If the stack is in `UPDATE_ROLLBACK_FAILED`, You MUST warn before recommending `continue-update-rollback` that it is a one-way operation and resources listed in `--resources-to-skip` will desynchronize from the template
- If the stack is `DELETE_FAILED`, You SHOULD recommend inspecting the specific resource(s) blocking deletion before re-issuing delete
- You SHOULD offer to help draft the corrected template or the environment fix on request

## Examples

### Example: IAM permission failure (environment-level)

```
Stack: my-api-stack (UPDATE_ROLLBACK_COMPLETE)
Region: us-east-1

Root cause (environment-level):
  Resource: OrdersTable (AWS::DynamoDB::Table)
  Status: CREATE_FAILED
  Reason: User: arn:aws:iam::123456789012:role/CFNDeployRole is not authorized
  to perform: dynamodb:CreateTable on resource: arn:aws:dynamodb:us-east-1:...

CloudTrail evidence:
  2026-04-21T14:23:05Z — CreateTable — AccessDenied
  Deeplink: https://console.aws.amazon.com/cloudtrailv2/...

Fix (no template change needed):
  Attach this statement to role CFNDeployRole:
    {
      "Effect": "Allow",
      "Action": ["dynamodb:CreateTable", "dynamodb:DescribeTable"],
      "Resource": "arn:aws:dynamodb:us-east-1:123456789012:table/*"
    }

Next steps:
  1. Apply the IAM policy change
  2. Redeploy the stack (no template changes required)
```

### Example: Resource name conflict (template-level)

```
Stack: analytics-stack (CREATE_FAILED)
Region: eu-west-1

Root cause (template-level):
  Resource: ReportBucket (AWS::S3::Bucket)
  Status: CREATE_FAILED
  Reason: acme-reports already exists

Fix (template change):
  Make the bucket name unique per stack:
    ReportBucket:
      Type: AWS::S3::Bucket
      Properties:
        BucketName: !Sub "${AWS::StackName}-reports"  # was: acme-reports

Next steps:
  1. Apply the template fix
  2. Run pre-deployment validation (cfn-lint, cfn-guard, change set) on the
     corrected template before redeploying
  3. Delete the failed stack, then re-create with the corrected template
```

## Troubleshooting

### "Stack not found" but I know the stack existed
The stack was likely deleted after failure. If you have the Stack ARN (format: `arn:aws:cloudformation:<region>:<account>:stack/<name>/<uuid>`), pass it as `stack_name`. CloudFormation retains historical events for deleted stacks for ~90 days via `describe-events` with the ARN.

### `describe-events` with `--filters FailedEvents=true` is not recognized
The `--filters` parameter requires a recent AWS CLI version. Upgrade with `pip install --upgrade awscli` or `brew upgrade awscli`. As a fallback, use `describe-events` without the filter and manually filter for `EventType` in `[PROVISIONING_ERROR, VALIDATION_ERROR]`.

### CloudTrail lookup returns nothing for a known failure
Causes:
- The failure was older than 90 days (CloudTrail Events history limit)
- The CloudTrail trail is in a different region than the stack
- The failing API call was made from a service that does not source from `cloudformation.amazonaws.com` (e.g., a Lambda-backed custom resource calls AWS APIs from its own execution role, so `sourceIPAddress` will differ)

For older failures, check the S3 bucket configured for CloudTrail logging, if any.

### The first failed event is a downstream effect, not the root cause
Sometimes CloudFormation creates resources in parallel and the first reported failure is a dependency rather than the cause. Inspect all failed events; the root cause is often the one with the most specific `ResourceStatusReason` (e.g., "Property value is invalid" is more specific than "Dependency resource failed to create").
