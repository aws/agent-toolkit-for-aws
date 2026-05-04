# CloudFormation Pre-Deploy Validation

## Overview

Deterministic procedure for running CloudFormation's pre-deployment validation feature. When a change set is created, CloudFormation automatically validates the template against three common failure causes before any resources are provisioned:

1. **Property syntax validation** (FAIL) — Validates resource properties against AWS resource schemas (required properties, valid values, deprecated properties).
2. **Resource name conflict validation** (FAIL) — Detects naming conflicts with existing resources in the account.
3. **S3 bucket emptiness validation** (WARN) — Warns when deleting S3 buckets that contain objects.

Validation errors are exposed through the **new `describe-events` API** scoped to the change set. This procedure uses `call_aws` (preferred) or the AWS CLI to invoke these APIs directly.

**Important:** The legacy `describe-stack-events` API does NOT return validation errors. You MUST use `describe-events --change-set-id <arn>` to retrieve validation results.

## Parameters

- **stack_name** (required): The CloudFormation stack name to create or update.
- **template_source** (required): The template to deploy. One of:
  - File path to a local template
  - S3 URL of an uploaded template
  - Template content provided directly
- **change_set_type** (required): Either `CREATE` (new stack) or `UPDATE` (existing stack).
- **region** (required): AWS region for deployment.
- **parameters** (optional): Stack parameters as key-value pairs.
- **capabilities** (optional): CloudFormation capabilities (e.g., `CAPABILITY_IAM`, `CAPABILITY_NAMED_IAM`) if the template creates IAM resources.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST support multiple input methods for the template (direct input, file path, S3 URL)
- You MUST confirm successful acquisition of all parameters before proceeding

## Steps

### 1. Verify Dependencies

Check which mechanism is available to invoke AWS APIs.

**Constraints:**

- You MUST check in this order of preference:
  1. `call_aws` tool from the AWS MCP Server (preferred for sandboxed execution, audit logging, and observability)
  2. AWS CLI (`aws`) available on the user's system (verify with `which aws` or `aws --version`)
- You MUST verify the user has valid AWS credentials configured for the target account/region (e.g., `aws sts get-caller-identity --region <region>`). This read-only call is acceptable during verification because it does not modify any resources
- You MUST ONLY check for availability and credential validity. You MUST NOT create change sets, execute change sets, or install missing dependencies during this step because creating a change set triggers actual CloudFormation operations and installation modifies the user's environment
- If the AWS CLI is missing, You MUST ask the user explicitly before running any install command, using a prompt like: "I can install the AWS CLI via `<platform-specific command>`. Do you want me to install it, or would you prefer to install it manually?"
- You MUST NOT run install commands without the user's explicit approval because this changes the user's environment
- If credentials are missing or invalid, You MUST ask the user to configure credentials (e.g., via `aws configure`, environment variables, or their preferred credential provider) and MUST NOT proceed until credentials are confirmed
- You MUST respect the user's decision to proceed, install, or abort

### 2. Recommend Template-Level Pre-Validation

Catch issues locally before consuming CloudFormation API quota.

**Constraints:**

- You SHOULD recommend running the `validate-cloudformation-template` SOP first to catch cfn-lint syntax and schema errors locally
- You SHOULD recommend running the `check-cloudformation-template-compliance` SOP to catch security violations locally
- If the user has already run these checks or explicitly skips them, You MUST proceed to the next step

### 3. Upload Template (if needed)

Prepare the template for the change set.

**Constraints:**

- If the template is small (≤ 51,200 bytes) and provided as content or a local file, You MAY pass it inline via `--template-body`
- If the template exceeds 51,200 bytes, You MUST upload it to S3 and use `--template-url` because `--template-body` has a size limit
- If the template is already at an S3 URL, You MUST use `--template-url` directly

### 4. Create Change Set

Create the change set to trigger pre-deployment validation. Validation runs automatically during change set creation — no opt-in is required.

**Constraints:**

- You MUST use a unique, descriptive change set name (e.g., `pre-deploy-validation-<timestamp>`)
- You MUST use the appropriate `--change-set-type` (`CREATE` for new stacks, `UPDATE` for existing)
- You MUST include `--capabilities` if the template creates IAM resources (e.g., `CAPABILITY_IAM`, `CAPABILITY_NAMED_IAM`)
- You MUST invoke via `call_aws` (preferred) or the AWS CLI. Example CLI form:

  ```
  aws cloudformation create-change-set \
    --stack-name <stack_name> \
    --template-body file://<path> \
    --change-set-name pre-deploy-validation-$(date +%s) \
    --change-set-type CREATE \
    --region <region> \
    --capabilities CAPABILITY_IAM
  ```

  > **Notes:** Use `--template-url s3://...` instead of `--template-body` for templates exceeding 51,200 bytes. Include `--capabilities` only if the template creates IAM resources.
- You MUST capture the returned change set ARN (Id) for the next step
- You MUST explain to the user that creating a change set does NOT modify any resources because it only plans the changes and runs validation
- You MUST wait for change set creation to reach a terminal status (`CREATE_COMPLETE`, `FAILED`) before checking validation results. Use `describe-change-set` to poll status.

### 5. Retrieve Validation Results via describe-events

Fetch validation results from the **new `describe-events` API**.

**Constraints:**

- You MUST use `aws cloudformation describe-events --change-set-id <arn> --region <region>` (via `call_aws` or CLI)
- You MUST NOT use `describe-stack-events` because the legacy stack events API does NOT return validation errors — it only surfaces resource provisioning events after execution
- You MUST filter events where `EventType` equals `VALIDATION_ERROR` because these are the validation findings
- For each validation event, You MUST extract:
  - `ValidationName` — one of `PROPERTY_VALIDATION`, `RESOURCE_NAME_CONFLICT`, `S3_BUCKET_EMPTINESS`
  - `ValidationStatus` — `FAILED` or `PASSED`
  - `ValidationStatusReason` — detailed error message
  - `ValidationPath` — property path in the template where the error occurred
  - `ValidationFailureMode` — `FAIL` (blocks execution) or `WARN` (allows execution)
- If no `VALIDATION_ERROR` events are returned, You MUST treat the change set as having passed all validations

### 6. Present Results and Guide Remediation

Report validation findings grouped by type and help the user fix issues.

**Constraints:**

- You MUST present results grouped by `ValidationName`:
  - **Property syntax validation** — invalid property values or formats
  - **Resource name conflict validation** — resources that conflict with existing resources
  - **S3 emptiness validation** — S3 buckets that must be empty before deletion
- For each failure, You MUST include the `ValidationPath` so the user can pinpoint the exact location in their template
- For each failure, You MUST provide the specific template fix showing the corrected property or resource
- You MUST clearly distinguish `FAIL` (execution blocked) from `WARN` (execution allowed) so the user knows what MUST be fixed versus what SHOULD be considered
- If any `FAIL`-mode failures exist, You MUST recommend fixing the template and creating a new change set
- You MUST NOT recommend executing a change set that has `FAIL`-mode validation failures because CloudFormation will block execution and the change set cannot succeed
- If only `WARN`-mode issues exist, You SHOULD explain the warning and let the user decide

### 7. Execute or Clean Up

Guide the user on next steps after validation.

**Constraints:**

- If all validations passed (or only `WARN`-mode issues that the user accepts), You MUST ask the user for explicit approval before executing the change set
- You MUST NOT execute the change set without explicit user approval because this will modify live infrastructure
- You MUST NOT delete a stack without explicit user approval. Before deleting, You MUST verify the stack status is `REVIEW_IN_PROGRESS` by calling `describe-stacks`
- To execute: `aws cloudformation execute-change-set --change-set-name <arn> --region <region>`
- If the user does not want to execute:
  - For `UPDATE`-type change sets: recommend deleting the change set to keep the stack clean: `aws cloudformation delete-change-set --change-set-name <arn> --region <region>`
  - For `CREATE`-type change sets: You MUST recommend also deleting the stack (after user approval), because it remains in `REVIEW_IN_PROGRESS` state and will block future creates: `aws cloudformation delete-change-set --change-set-name <arn> --region <region>` followed by `aws cloudformation delete-stack --stack-name <stack_name> --region <region>`
- If validation failed, You MUST recommend fixing the template and re-running from Step 4, since validation results are tied to a specific change set and modifying the template requires creating a new one
- If the original change set used `--change-set-type CREATE`, You MUST warn the user that the stack now exists in `REVIEW_IN_PROGRESS` state. Before retrying with `--change-set-type CREATE`, the user MUST first delete the stack (with user approval). Alternatively, the user can delete only the failed change set and create a new `CREATE` change set against the same stack.

## Examples

### Example: Successful Validation

```
Change set "pre-deploy-validation-1713580000" created for stack "my-app-stack".

Retrieved via: aws cloudformation describe-events --change-set-id arn:aws:cloudformation:...

Validation results:
  ✓ PROPERTY_VALIDATION: PASSED
  ✓ RESOURCE_NAME_CONFLICT: PASSED
  ✓ S3_BUCKET_EMPTINESS: PASSED

The change set is ready to execute. Would you like to execute it now?
```

### Example: Failed Validation

```
Change set "pre-deploy-validation-1713580000" created for stack "my-app-stack".

Retrieved via: aws cloudformation describe-events --change-set-id arn:aws:cloudformation:...

✗ PROPERTY_VALIDATION (FAIL):
  ValidationPath: /Resources/MyBucket/Properties/NotificationConfiguration/QueueConfigurations/0
  ValidationStatusReason: required key [Event] not found

  Fix (Resources/MyBucket/Properties/NotificationConfiguration/QueueConfigurations):
    QueueConfigurations:
      - Queue: !GetAtt MyQueue.Arn
        Event: s3:ObjectCreated:*   # Required property was missing

✗ RESOURCE_NAME_CONFLICT (FAIL):
  ValidationPath: /Resources/MyDynamoDBTable/Properties/TableName
  ValidationStatusReason: A table named "users-table" already exists in this account/region.

  Fix: Make the name unique per stack:
    TableName: !Sub "${AWS::StackName}-users-table"

⚠ S3_BUCKET_EMPTINESS (WARN):
  ValidationPath: /Resources/DataBucket
  ValidationStatusReason: Bucket is not empty. Delete may fail.

  Options:
    - Empty the bucket before stack deletion
    - Or set DeletionPolicy: Retain on the bucket resource

2 FAIL-mode issues must be fixed before execution.
Fix the template and create a new change set.
```

## Troubleshooting

### describe-events returns empty or unknown command
The `describe-events` API (scoped to change sets with validation errors) is the newer API. If the installed AWS CLI is outdated, update it: `pip install --upgrade awscli` or `brew upgrade awscli`. If the command still returns nothing, confirm the change set ARN is correct and the change set has finished creating.

### User calls describe-stack-events instead
`describe-stack-events` returns events after the stack begins provisioning. It does NOT include pre-deployment validation errors. You MUST redirect the user to `describe-events --change-set-id <arn>`.

### Change set stuck in CREATE_IN_PROGRESS
Use `aws cloudformation describe-change-set --change-set-name <arn>` to check the status. Wait until it reaches `CREATE_COMPLETE` or `FAILED` before calling `describe-events`.

### Change set status FAILED but no validation events
If `describe-change-set` shows `Status: FAILED` with a `StatusReason` unrelated to validation (e.g., "No updates are to be performed"), the failure is not a pre-deployment validation issue. Investigate the `StatusReason` directly.

### Missing s3:ListBucket permission
S3 bucket emptiness validation requires `s3:ListBucket` permission on the buckets being deleted. If this validation is skipped or errors, verify the deploying role has this permission.

### Validation passed but deployment still fails
Pre-deployment validation catches three common classes of issues but cannot detect all runtime failures (resource limits, service constraints, IAM permissions, invalid AMI IDs). If deployment fails after validation passes, use the `troubleshoot-cloudformation-deployment` tool or SOP to diagnose the runtime failure.
