# CloudFormation Pre-Deploy Validation

## Overview

Deterministic procedure for running CloudFormation's **pre-deployment validation** feature. Pre-deployment validation catches common deployment errors before any resources are provisioned, surfacing structured error details (including the logical resource ID and property path) so you can fix problems before a provision-and-rollback cycle.

Pre-deployment validation runs automatically and is **enabled by default** on all stack operations:

- **Create Stack** and **Update Stack** operations — validation runs before resource provisioning begins. If a `FAIL`-mode check fails, the operation stops before any resource is provisioned.
- **Change set creation** — validation runs when the change set is created, with no resources provisioned at all.

Validation checks:

1. **Property syntax validation** (FAIL) — Validates resource properties against AWS resource schemas (required properties, valid values, deprecated properties).
2. **Resource name conflict validation** (FAIL) — Detects naming conflicts with existing resources in the account.
3. **S3 bucket emptiness validation** (WARN) — Warns when deleting S3 buckets that contain objects.
4. **Service quota limit validation** (WARN, change set creation only) — Warns when an operation would exceed an account service quota.
5. **AWS Config Recorder conflict validation** (WARN, change set creation only) — Warns when the operation conflicts with an existing AWS Config configuration recorder.
6. **ECR repository delete readiness validation** (WARN, change set creation only) — Warns when an ECR repository targeted for deletion is not empty or otherwise not ready for deletion.

Validation results are exposed through the `describe-events` API. This procedure uses `call_aws` (preferred) or the AWS CLI to invoke these APIs directly. Note: The AWS MCP server is recommended for streamlined API invocation, but all steps can be performed using the AWS CLI alone.

**Important:** The legacy `describe-stack-events` API does NOT return validation results. You MUST use `describe-events` (scoped by `--change-set-name`, `--operation-id`, or `--stack-name`) to retrieve validation results.

### Choosing a validation path

- **To validate WITHOUT provisioning any resources (recommended pre-flight):** create a change set. Change set creation runs all validation checks (including the three `WARN`-only checks) and provisions nothing. This is the safest way to validate an arbitrary template before committing to a deployment.
- **To validate as part of an actual deployment:** run `create-stack` or `update-stack` directly. Validation runs automatically before provisioning; a `FAIL`-mode result halts the operation before any resource is created or modified.

## Parameters

- **stack_name** (required): The CloudFormation stack name to create or update.
- **template_source** (required): The template to deploy. One of:
  - File path to a local template
  - S3 URL of an uploaded template
  - Template content provided directly
- **validation_path** (required): Either `CHANGE_SET` (validate without provisioning — recommended pre-flight) or `STACK_OPERATION` (validate as part of a direct create/update).
- **change_set_type** (required when validation_path is `CHANGE_SET`): Either `CREATE` (new stack) or `UPDATE` (existing stack).
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
- You MUST ONLY check for availability and credential validity. You MUST NOT create change sets, create or update stacks, execute change sets, or install missing dependencies during this step because these trigger actual CloudFormation operations and installation modifies the user's environment
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

Prepare the template for the operation.

**Constraints:**

- If the template is small (≤ 51,200 bytes) and provided as content or a local file, You MAY pass it inline via `--template-body`
- If the template exceeds 51,200 bytes, You MUST upload it to S3 and use `--template-url` because `--template-body` has a size limit
- If the template is already at an S3 URL, You MUST use `--template-url` directly

### 4. Trigger Validation

Trigger pre-deployment validation. Validation runs automatically — no opt-in is required because it is enabled by default on all stack operations.

**Constraints:**

- You MUST NOT pass `--disable-validation` (or the `DisableValidation` API parameter) unless the user explicitly requests skipping validation, because validation is what this procedure exists to run. If the user does request it, You MUST warn that disabling validation removes the safety check that catches preventable failures before provisioning.

**Path A — Change set creation (recommended pre-flight, provisions nothing):**

- You MUST use a unique, descriptive change set name (e.g., `pre-deploy-validation-<timestamp>`)
- You MUST use the appropriate `--change-set-type` (`CREATE` for new stacks, `UPDATE` for existing)
- You MUST include `--capabilities` if the template creates IAM resources
- Example CLI form:

  ```
  aws cloudformation create-change-set \
    --stack-name <stack_name> \
    --template-body file://<path> \
    --change-set-name pre-deploy-validation-$(date +%s) \
    --change-set-type CREATE \
    --region <region> \
    --capabilities CAPABILITY_IAM
  ```

  > **Notes:** Use `--template-url s3://...` instead of `--template-body` for templates exceeding 51,200 bytes. Include `--capabilities` only if the template creates IAM resources. When using `call_aws`, pass the template content inline in the `TemplateBody` parameter — the `file://` syntax is AWS CLI-specific and does not work with `call_aws`.
- You MUST capture the returned change set ARN (Id) for the next step
- You MUST explain to the user that creating a change set does NOT modify any resources because it only plans the changes and runs validation
- You MUST wait for change set creation to reach a terminal status (`CREATE_COMPLETE`, `FAILED`) before checking validation results. Use `describe-change-set` to poll status.
- This path surfaces ALL validation checks, including the three `WARN`-only checks (service quota, AWS Config Recorder conflict, ECR delete readiness).

**Path B — Direct create/update stack (validates as part of a real deployment):**

- You MUST obtain explicit user approval before running `create-stack` or `update-stack`, because these operations provision or modify live infrastructure once validation passes.
- Validation runs automatically before provisioning. If a `FAIL`-mode check fails, the operation stops before any resource is provisioned.
- You MUST capture the operation ID returned by the operation for the next step.
- Example CLI form:

  ```
  aws cloudformation create-stack \
    --stack-name <stack_name> \
    --template-body file://<path> \
    --region <region> \
    --capabilities CAPABILITY_IAM
  ```

  > **Note:** When using `call_aws`, pass the template content inline in the `TemplateBody` parameter — the `file://` syntax is AWS CLI-specific and does not work with `call_aws`.

### 5. Retrieve Validation Results via describe-events

Fetch validation results from the `describe-events` API.

**Constraints:**

- You MUST use `aws cloudformation describe-events` (via `call_aws` or CLI) scoped to the operation you triggered:
  - For Path A (change set): `describe-events --change-set-name <arn> --region <region>`
  - For Path B (direct operation): `describe-events --operation-id <operation-id> --region <region>` (or `--stack-name <stack_name>` to scope by stack)
- You MUST NOT use `describe-stack-events` because the legacy stack events API does NOT return validation results — it only surfaces resource provisioning events after execution
- You MUST filter events where `EventType` equals `VALIDATION_ERROR` because these are the validation results
- For each validation event, You MUST extract:
  - `ValidationName` — known values include `PROPERTY_VALIDATION`, `RESOURCE_NAME_CONFLICT`, `S3_BUCKET_EMPTINESS`, `SERVICE_QUOTA`, `CONFIG_RECORDER_CONFLICT`, `ECR_REPOSITORY_DELETE_READINESS`. CloudFormation may add new validation checks over time; handle any unknown `ValidationName` by presenting it with its `ValidationStatusReason`
  - `ValidationStatus` — `FAILED` or `PASSED`
  - `ValidationStatusReason` — detailed error message
  - `ValidationPath` — property path in the template where the error occurred (may be absent for account-level checks such as service quotas)
  - `LogicalResourceId` — the logical ID of the affected resource
  - `ValidationFailureMode` — `FAIL` (blocks the operation) or `WARN` (allows the operation)
- If no `VALIDATION_ERROR` events are returned, You MUST treat the operation as having passed all validations

### 6. Present Results and Guide Remediation

Report validation results grouped by type and help the user fix issues.

**Constraints:**

- You MUST present results grouped by `ValidationName`:
  - **Property syntax validation** (FAIL) — invalid property values or formats
  - **Resource name conflict validation** (FAIL) — resources that conflict with existing resources
  - **S3 emptiness validation** (WARN) — S3 buckets that must be empty before deletion
  - **Service quota validation** (WARN) — operations that would exceed an account quota
  - **AWS Config Recorder conflict validation** (WARN) — conflicts with an existing configuration recorder
  - **ECR repository delete readiness validation** (WARN) — ECR repositories not ready for deletion
- For any `ValidationName` not listed above, You MUST still present the result with its `LogicalResourceId`, `ValidationPath`, `ValidationStatus`, and `ValidationStatusReason` so the user can evaluate it
- For each result, You MUST include the `LogicalResourceId` and `ValidationPath` (if present) so the user can pinpoint the exact location in their template
- For each `FAIL` result, You MUST provide the specific template fix showing the corrected property or resource
- You MUST clearly distinguish `FAIL` (operation blocked) from `WARN` (operation allowed) so the user knows what MUST be fixed versus what SHOULD be considered
- If any `FAIL`-mode results exist, You MUST recommend fixing the template before deploying
- You MUST NOT recommend executing a change set or proceeding with a deployment that has `FAIL`-mode validation results because CloudFormation will block it
- If only `WARN`-mode results exist, You SHOULD explain each warning and let the user decide

### 7. Execute or Clean Up

Guide the user on next steps after validation.

**Constraints:**

- If all validations passed (or only `WARN`-mode results that the user accepts) and validation was done via a change set, You MUST ask the user for explicit approval before executing the change set
- You MUST NOT execute a change set or run a stack operation without explicit user approval because this will modify live infrastructure
- You MUST NOT delete a stack without explicit user approval. Before deleting, You MUST verify the stack status is `REVIEW_IN_PROGRESS` by calling `describe-stacks`
- To execute a validated change set: `aws cloudformation execute-change-set --change-set-name <arn> --region <region>`
- If the user does not want to execute a change set:
  - For `UPDATE`-type change sets: recommend deleting the change set to keep the stack clean: `aws cloudformation delete-change-set --change-set-name <arn> --region <region>`
  - For `CREATE`-type change sets: You MUST recommend also deleting the stack (after user approval), because it remains in `REVIEW_IN_PROGRESS` state and will block future creates: `aws cloudformation delete-change-set --change-set-name <arn> --region <region>` followed by `aws cloudformation delete-stack --stack-name <stack_name> --region <region>`
- If validation failed, You MUST recommend fixing the template and re-running validation. For change sets, validation results are tied to a specific change set, so modifying the template requires creating a new one.
- If a `CREATE`-type change set was used, You MUST warn the user that the stack now exists in `REVIEW_IN_PROGRESS` state. Before retrying with `--change-set-type CREATE`, the user MUST first delete the stack (with user approval), or delete only the failed change set and create a new `CREATE` change set against the same stack.

## CDK Pre-Deployment Validation

When the user is deploying with the AWS CDK rather than raw CloudFormation, pre-deployment validation surfaces through CDK directly.

**Constraints:**

- You SHOULD inform the user that both `cdk deploy` and `cdk validate` surface pre-deployment validation results in a unified report with construct-level tracing, mapping each result back to the originating CDK construct
- You SHOULD prefer `cdk validate` when the user wants to validate without deploying
- You MUST treat the structured CDK validation report the same way as `describe-events` results: enumerate every `FAIL` result before recommending a deploy, and surface `WARN` results for the user to evaluate

## Examples

### Example: Successful Validation (change set path)

```
Change set "pre-deploy-validation-1713580000" created for stack "my-app-stack".

Retrieved via: aws cloudformation describe-events --change-set-name arn:aws:cloudformation:...

Validation results:
  ✓ PROPERTY_VALIDATION: PASSED
  ✓ RESOURCE_NAME_CONFLICT: PASSED
  ✓ S3_BUCKET_EMPTINESS: PASSED
  ✓ SERVICE_QUOTA: PASSED

The change set is ready to execute. Would you like to execute it now?
```

### Example: Failed Validation

```
Change set "pre-deploy-validation-1713580000" created for stack "my-app-stack".

Retrieved via: aws cloudformation describe-events --change-set-name arn:aws:cloudformation:...

✗ PROPERTY_VALIDATION (FAIL):
  LogicalResourceId: MyBucket
  ValidationPath: /Resources/MyBucket/Properties/NotificationConfiguration/QueueConfigurations/0
  ValidationStatusReason: required key [Event] not found

  Fix (Resources/MyBucket/Properties/NotificationConfiguration/QueueConfigurations):
    QueueConfigurations:
      - Queue: !GetAtt MyQueue.Arn
        Event: s3:ObjectCreated:*   # Required property was missing

✗ RESOURCE_NAME_CONFLICT (FAIL):
  LogicalResourceId: MyDynamoDBTable
  ValidationPath: /Resources/MyDynamoDBTable/Properties/TableName
  ValidationStatusReason: A table named "users-table" already exists in this account/region.

  Fix: Make the name unique per stack:
    TableName: !Sub "${AWS::StackName}-users-table"

⚠ SERVICE_QUOTA (WARN):
  LogicalResourceId: MyVpc
  ValidationPath: /Resources/MyVpc
  ValidationStatusReason: This operation would exceed the VPCs-per-Region quota.

  Options:
    - Request a quota increase before deploying
    - Or reduce the number of VPCs in the template

2 FAIL-mode issues must be fixed before deployment.
Fix the template and re-run validation.
```

## Troubleshooting

### describe-events returns empty or unknown command
The `describe-events` API requires AWS CLI support for the command. If it is not recognized, update the AWS CLI: `pip install --upgrade awscli` or `brew upgrade awscli`. If the command still returns nothing, confirm the change set ARN, operation ID, or stack name is correct and the operation has finished its validation phase.

### User calls describe-stack-events instead
`describe-stack-events` returns events after the stack begins provisioning. It does NOT include pre-deployment validation results. You MUST redirect the user to `describe-events` scoped by `--change-set-name`, `--operation-id`, or `--stack-name`.

### Change set stuck in CREATE_IN_PROGRESS
Use `aws cloudformation describe-change-set --change-set-name <arn>` to check the status. Wait until it reaches `CREATE_COMPLETE` or `FAILED` before calling `describe-events`.

### Change set status FAILED but no validation events
If `describe-change-set` shows `Status: FAILED` with a `StatusReason` unrelated to validation (e.g., "No updates are to be performed"), the failure is not a pre-deployment validation issue. Investigate the `StatusReason` directly.

### Validation appears to be skipped
Pre-deployment validation is enabled by default. If no validation events appear and the deployment provisioned without them, confirm the operation did not pass `--disable-validation` (CLI) or `DisableValidation` (API). You MUST NOT add `--disable-validation` unless the user explicitly asked to skip validation.

### Missing s3:ListBucket permission
S3 bucket emptiness validation requires `s3:ListBucket` permission on the buckets being deleted. If this validation is skipped or errors, verify the deploying role has this permission.

### Validation passed but deployment still fails
Pre-deployment validation catches common classes of issues but cannot detect all runtime failures (resource limits not covered by quota checks, service constraints, IAM permissions at provisioning time, invalid AMI IDs). If deployment fails after validation passes, use the `troubleshoot-cloudformation-deployment` tool or SOP to diagnose the runtime failure.
