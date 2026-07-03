# Deploy with Express Mode

## Overview

Deterministic procedure for deploying CloudFormation stacks using **Express mode** — a deployment mode that completes stack operations as soon as resource configuration is applied, giving immediate confirmation to proceed to the next iteration. Resources continue becoming ready to serve traffic in the background.

Express mode works with all existing CloudFormation templates and requires no template changes. It is recommended for development workflows where you iterate frequently and need fast deployment confirmation.

**When to use Express mode:**
- Iterating on infrastructure configurations during development
- Deploying individual components of your application
- Deploying dependent stacks that only need resource outputs (VPC IDs, endpoints, ARNs) to proceed
- Building with AI agents that need fast feedback loops to validate and refine infrastructure
- Prototyping and experimenting with new architectures

**When NOT to use Express mode:**
- Production workflows that require resources to serve traffic immediately after stack completion
- Deployments where downstream consumers immediately hit endpoints (load balancers, CloudFront distributions, ECS services) after the operation completes

**What Express mode skips:**
1. Traffic readiness (e.g., EC2 instance reaching `running` state)
2. Region propagation (e.g., CloudFront propagating to all edge locations, 5-10 minutes)
3. Cleanup (e.g., network interface removal before Lambda function deletion)

**What does NOT change:**
- CloudFormation still processes all resources in dependency order
- CloudFormation still retries dependent resources that encounter transient failures
- CloudFormation still handles dependent resource failures

## Parameters

- **stack_name** (required): The CloudFormation stack name.
- **template_source** (required): The template to deploy. One of:
  - File path to a local template
  - S3 URL of an uploaded template
  - Template content provided directly
- **operation** (required): One of `CREATE`, `UPDATE`, or `DELETE`.
- **region** (required): AWS region for deployment.
- **enable_rollback** (optional): Whether to enable rollback. Express mode disables rollback by default for fastest iteration. Set to `true` if the user wants rollback on failure.
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
- You MUST ONLY check for availability and credential validity. You MUST NOT create or modify stacks or install missing dependencies during this step
- If the AWS CLI is missing, You MUST ask the user explicitly before running any install command
- You MUST NOT run install commands without the user's explicit approval
- If credentials are missing or invalid, You MUST ask the user to configure credentials and MUST NOT proceed until credentials are confirmed

### 2. Confirm Express Mode is Appropriate

Verify with the user that Express mode is the right choice for their use case.

**Constraints:**
- You MUST inform the user that Express mode completes when resource configuration is applied, and resources continue stabilizing in the background
- You MUST ask whether the user's workflow requires resources to serve traffic immediately after the stack operation completes
- If the user's workflow DOES require immediate traffic readiness (production serving, endpoint availability), You MUST recommend using the default deployment behavior instead
- If the user is in a development/iteration workflow, You SHOULD proceed with Express mode
- You MUST inform the user that rollback is disabled by default with Express mode. If the user wants rollback protection, You MUST include `"disableRollback": false` in the deployment configuration

### 3. Upload Template (if needed)

Prepare the template for the operation.

**Constraints:**
- If the template is small (≤ 51,200 bytes) and provided as content or a local file, You MAY pass it inline via `--template-body`
- If the template exceeds 51,200 bytes, You MUST upload it to S3 and use `--template-url` because `--template-body` has a size limit
- If the template is already at an S3 URL, You MUST use `--template-url` directly
- This step does not apply to `DELETE` operations

### 4. Execute Stack Operation with Express Mode

Run the stack operation with the `--deployment-config` parameter set to Express mode.

**Constraints:**
- You MUST obtain explicit user approval before executing the operation because it creates, modifies, or deletes live infrastructure
- You MUST use `--deployment-config '{"mode": "EXPRESS"}'` on the stack operation
- If the user requested rollback, You MUST use `--deployment-config '{"mode": "EXPRESS", "disableRollback": false}'`
- You MUST include `--capabilities` if the template creates IAM resources
- You MUST NOT use `aws cloudformation deploy` because it does not support `--deployment-config`. Use `create-stack`, `update-stack`, or `delete-stack` instead.

> **Note:** When using `call_aws`, pass the template content inline in the `TemplateBody` parameter — the `file://` syntax is AWS CLI-specific and does not work with `call_aws`.

**Create a stack:**
```
aws cloudformation create-stack \
  --stack-name <stack_name> \
  --template-body file://<path> \
  --region <region> \
  --deployment-config '{"mode": "EXPRESS"}' \
  --capabilities CAPABILITY_IAM
```

**Update a stack:**
```
aws cloudformation update-stack \
  --stack-name <stack_name> \
  --template-body file://<path> \
  --region <region> \
  --deployment-config '{"mode": "EXPRESS"}' \
  --capabilities CAPABILITY_IAM
```

**Delete a stack:**
```
aws cloudformation delete-stack \
  --stack-name <stack_name> \
  --region <region> \
  --deployment-config '{"mode": "EXPRESS"}'
```

**With rollback enabled:**
```
aws cloudformation create-stack \
  --stack-name <stack_name> \
  --template-body file://<path> \
  --region <region> \
  --deployment-config '{"mode": "EXPRESS", "disableRollback": false}' \
  --capabilities CAPABILITY_IAM
```

### 5. Express Mode with Change Sets

Express mode also works with change sets. The deployment configuration is stored with the change set and applied when executed.

**Constraints:**
- To use Express mode with a change set, supply `--deployment-config` at `create-change-set` time:
  ```
  aws cloudformation create-change-set \
    --stack-name <stack_name> \
    --template-body file://<path> \
    --change-set-name <change_set_name> \
    --deployment-config '{"mode": "EXPRESS"}' \
    --region <region> \
    --capabilities CAPABILITY_IAM
  ```
- You MUST NOT specify `--deployment-config` again at `execute-change-set` time because it is already stored with the change set
- You SHOULD recommend the change set path when the user also wants pre-deployment validation before deploying with Express mode (change set creation runs all validation checks before execution)

### 6. CDK Express Mode

When the user is deploying with the AWS CDK, Express mode is activated with the `--express` flag.

**Constraints:**
- You MUST use `cdk deploy --express` to deploy with Express mode
- To re-enable rollback: `cdk deploy --express --rollback`
- Express mode applies to all CloudFormation deployments triggered by CDK, including multi-stack deployments
- You MUST NOT recommend `cdk deploy --hotswap` as a substitute for Express mode — they are different capabilities:
  - Express mode: full infrastructure changes through CloudFormation, no drift introduced
  - CDK hotswap: code-only changes via direct service APIs, introduces drift (bypasses CloudFormation)

### 7. Monitor Resource Readiness After Completion

Guide the user on what to expect after Express mode completes.

**Constraints:**
- You MUST inform the user that resources continue stabilizing in the background after the operation reports complete
- You SHOULD provide guidance on typical background stabilization timelines:
  - CloudFront distribution: propagation to all edge locations (5-10 minutes)
  - EC2 instance: health checks, reaching `running` state
  - Lambda function delete: network interface cleanup
  - ECS service: containers reaching desired capacity
- You SHOULD recommend monitoring resource readiness through existing mechanisms: CloudWatch alarms, health checks, or service-specific dashboards
- If a resource does not stabilize as expected, You SHOULD recommend redeploying the stack to retry the affected resources

## Unsupported Features

The following are NOT supported with Express mode. You MUST inform the user if their scenario involves any of these:

- **Custom resources** (`AWS::CloudFormation::CustomResource` and `Custom::*`) — these follow default completion behavior even when Express mode is active
- **StackSets** — Express mode is not supported for StackSet operations
- **AWS SAM** — not supported
- **`aws cloudformation deploy` CLI command** — does not support `--deployment-config`; use `create-stack` or `update-stack` instead
- **Account-level default** — Express mode is activated per stack operation; there is no account-wide setting

## Examples

### Example: Create a stack with Express mode
```
$ aws cloudformation create-stack \
    --stack-name my-dev-vpc \
    --template-body file://vpc.yaml \
    --region us-west-2 \
    --deployment-config '{"mode": "EXPRESS"}'

{
  "StackId": "arn:aws:cloudformation:us-west-2:123456789012:stack/my-dev-vpc/abc123"
}

Stack "my-dev-vpc" creation completed (Express mode).
Resources are configured. VPC ID, subnet IDs, and other outputs are available.
Background stabilization (route propagation, NAT gateway activation) continues.
```

### Example: CDK deploy with Express mode
```
$ cdk deploy --express

 ✅  MyDevStack

Express mode: stack completed when resource configuration was applied.
Outputs:
  MyDevStack.VpcId = vpc-0abc123def456
  MyDevStack.ApiEndpoint = https://abc123.execute-api.us-west-2.amazonaws.com

Resources continue stabilizing in the background.
```

### Example: Express mode with rollback enabled
```
$ aws cloudformation update-stack \
    --stack-name my-dev-vpc \
    --template-body file://vpc-v2.yaml \
    --region us-west-2 \
    --deployment-config '{"mode": "EXPRESS", "disableRollback": false}'
```

## Troubleshooting

### Resources not ready to serve traffic after stack completes
This is expected behavior with Express mode. Resources receive their configuration immediately but may still be starting up, propagating, or cleaning up. Monitor resource-specific readiness through CloudWatch, health checks, or service dashboards. If a resource does not stabilize, redeploy the stack to retry.

### `--deployment-config` not recognized
The `--deployment-config` parameter requires a CLI version that supports Express mode. Update the AWS CLI to the latest version. If using CDK, use `--express` instead.

### `deploy` command does not accept `--deployment-config`
The `aws cloudformation deploy` command does not support `--deployment-config`. Use `create-stack` or `update-stack` directly. In CDK, use `cdk deploy --express`.

### Custom resources do not complete faster
Custom resources always follow default completion behavior regardless of Express mode. This is by design — custom resources define their own completion logic.

### StackSets error with Express mode
Express mode is not supported for StackSet operations. Remove `--deployment-config` when working with StackSets.

### Rollback not happening on failure
Express mode disables rollback by default. To re-enable, add `"disableRollback": false` to the deployment configuration JSON, or use `cdk deploy --express --rollback` in CDK.
