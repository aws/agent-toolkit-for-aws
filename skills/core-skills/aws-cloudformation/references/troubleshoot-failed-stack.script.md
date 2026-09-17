# Troubleshoot a Failed CloudFormation Stack

## Overview

Deterministic initial-triage procedure for a failed CloudFormation stack. Retrieve failed events, distinguish actionable failures from rollback cascade cancellations, identify parallel or shared root causes, enumerate every visible permission gap, and classify each fix as template-level or environment-level.

Use this script for failed-event diagnosis. Use the broader [troubleshoot deployment SOP](troubleshoot-deployment.script.md) when deeper CloudTrail correlation or stack recovery guidance is needed.

## Parameters

- **stack_name** (required): Name or ARN of the failed CloudFormation stack. Use the ARN when the stack was deleted but its historical events remain available.
- **region** (required): AWS Region where the stack operation ran, for example `us-east-1`.

**Constraints for parameter acquisition:**

- If all required parameters are already provided, You MUST proceed to the Steps
- If any required parameters are missing, You MUST ask for them before proceeding
- When asking for parameters, You MUST request all parameters in a single prompt
- When asking for parameters, You MUST use the exact parameter names as defined
- You MUST confirm `region` before calling CloudFormation because stack names are Region-scoped

## Steps

### 1. Verify Read Access

Confirm that a read-only AWS API mechanism and valid credentials are available.

**Constraints:**

- You SHOULD use the AWS MCP server `call_aws` tool when available for sandboxed execution and audit logging, but it is not required; every step in this procedure also works with the AWS CLI
- When using the AWS CLI, You MUST verify it is available and confirm the caller identity for `region`
- You MUST use read-only or least-privilege credentials because this procedure requires only diagnostic access
- You MUST NOT install software or change credentials during this step because those actions modify the user's environment
- If no API mechanism or valid credentials are available, You MUST report the specific blocker and stop

### 2. Retrieve Failed Events

Retrieve the stack's failed-event evidence without the noise of successful lifecycle events.

**Constraints:**

- You MUST call the CloudFormation `DescribeEvents` operation with `stack_name`, `region`, and the `FailedEvents=true` filter
- With the AWS CLI, You MUST use `aws cloudformation describe-events --stack-name <stack_name> --filters FailedEvents=true --region <region>`
- You MUST NOT use `describe-stack-events` because it does not support the failed-event filter
- You MUST NOT substitute a JMESPath `--query` expression for `--filters FailedEvents=true` because client-side projection does not provide the service's failed-event semantics
- For every returned event, You MUST capture `LogicalResourceId`, `PhysicalResourceId`, `ResourceType`, `ResourceStatus`, `ResourceStatusReason`, `Timestamp`, and `EventType`
- If a failed event represents a nested `AWS::CloudFormation::Stack`, You MUST retrieve that nested stack's failed events using its `PhysicalResourceId` because the child event usually contains the actionable reason
- If the filtered call returns no events, You MUST call `DescribeEvents` without the filter and report the earliest non-success or stalled status; if no diagnostic event exists, You MUST state that the available event history is insufficient and stop

### 3. Classify Every Failed Event

Classify each failed event before selecting root-cause candidates.

**Constraints:**

- You MUST inspect every event's `ResourceStatusReason`; You MUST NOT stop after the first failure because CloudFormation can create resources in parallel
- You MUST classify an event with a specific service error, such as an authorization denial, invalid property, name conflict, missing resource, quota error, or dependency error, as an **actionable failure**
- You MUST classify an event whose only reason is `Resource creation cancelled` or an equivalent cancellation with no specific service error as a **cascade cancellation**
- You MUST NOT treat a cascade cancellation as evidence that the cancelled resource's own configuration is valid because its provisioning may not have progressed far enough to expose another defect
- If a cancellation reason also contains a specific service error, You MUST classify it as an actionable failure rather than a cascade cancellation

### 4. Identify Root-Cause Groups

Determine whether actionable failures are independent, parallel symptoms of one cause, or downstream effects.

**Constraints:**

- You MUST sort events chronologically for context, but You MUST NOT assume the earliest timestamp is the only root cause because parallel provisioning can produce independent failures
- You MUST preserve every actionable failure in the diagnosis, even when several failures appear related
- When multiple resources fail with authorization errors, You MUST enumerate every denied action and affected resource or resource pattern; You MUST NOT report only the first permission gap because incomplete permission reporting forces repeated deployment attempts
- You SHOULD group failures under a shared root cause only when the evidence supports the relationship, such as the same deployment role missing permissions for several services
- You MUST label independent actionable failures separately so the developer can fix them in one pass
- You MUST label cascade cancellations as downstream effects and keep them separate from actionable failures

### 5. Classify Each Fix

Map each actionable failure to the location where remediation belongs.

**Constraints:**

- You MUST classify a fix as **template-level** when the template must change, such as an invalid property, missing required value, resource-name conflict, or dependency definition error
- You MUST classify a fix as **environment-level** when the account or deployment environment must change, such as an IAM permission gap, quota, missing external resource, deletion protection, or existing resource state
- You MUST NOT propose a template change for an environment-level failure because it does not resolve the underlying account condition
- If the available event reason does not support either classification, You MUST mark the failure **unresolved** rather than guessing and recommend the [troubleshoot deployment SOP](troubleshoot-deployment.script.md) for CloudTrail correlation

### 6. Present the Diagnosis

Report the complete triage result in a form that supports one-pass remediation.

**Constraints:**

- You MUST report all actionable failures before cascade cancellations
- For every actionable failure, You MUST include the logical resource, resource type, status reason, root-cause group, fix classification, and concrete next action
- For permission failures, You MUST include the complete set of visible missing actions and affected resources or resource patterns
- You MUST list cascade cancellations separately and explain that they are rollback effects rather than confirmed root causes
- You MUST warn that cancelled resources can reveal additional failures on the next deployment attempt after visible root causes are fixed
- You MUST NOT claim the stack is ready to redeploy while actionable failures remain because unresolved failures will block or roll back the next operation
- You SHOULD offer the broader [troubleshoot deployment SOP](troubleshoot-deployment.script.md) when the user needs CloudTrail evidence, recovery sequencing, or help with a stuck rollback

## Security Considerations

Follow the [shared security guidance](security-considerations.md) when handling templates, outputs, secrets, tools, and installation artifacts.

## Examples

### Parallel permission failures

**Input:**

- **stack_name**: `orders-dev`
- **region**: `us-east-1`

**Expected behavior:**
The agent retrieves all failed events and finds `dynamodb:CreateTable` denied for `OrdersTable`, `sqs:CreateQueue` denied for `OrdersQueue`, and several resources with only `Resource creation cancelled`. It reports both denied actions under a shared deployment-role root cause, classifies the fix as environment-level, and lists the cancellations separately without treating them as additional root causes.

### Template failure plus cascade cancellations

**Input:**

- **stack_name**: `analytics-test`
- **region**: `eu-west-1`

**Expected behavior:**
The agent identifies a bucket name conflict as the actionable template-level failure, marks the cancelled resources as cascade cancellations, proposes the smallest template correction for the name, and warns that cancelled resources may expose further failures after retry.

## Troubleshooting

### No filtered events are returned

Use `DescribeEvents` without the failed-event filter to identify a stalled or non-success status. Do not switch to `describe-stack-events`.

### The first event is not the root cause

Review all actionable failures and prefer specific service errors over generic dependency or cancellation messages. Parallel operations can produce more than one root cause.

### Event reasons are too generic

Do not guess. Run the [troubleshoot deployment SOP](troubleshoot-deployment.script.md) to correlate the failure window with CloudTrail and service-specific evidence.
