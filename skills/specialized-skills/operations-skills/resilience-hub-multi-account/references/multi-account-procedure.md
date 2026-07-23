# Multi-Account Resilience Hub v2 Setup

## Overview

This SOP guides you through configuring Resilience Hub v2 to assess a service whose resources span multiple AWS accounts, using the per-service **permission model** (cross-account IAM roles assumed by an invoker role). Note: for *organization-wide* governance (centralized policies + visibility), Resilience Hub v2 also offers an **AWS Organizations integration** with a **delegated administrator**, configured from the management account via Organizations trusted access + the Resilience Hub console (not a `resiliencehubv2` CLI operation). This SOP covers the per-service cross-account path; the two are complementary. Use when the customer has multiple AWS accounts and wants a central account to run assessments against workloads in member accounts.

## Parameters

**central_account_id** (required): AWS account ID that runs assessments centrally
**member_account_id** (optional): A member account ID hosting workloads. The Steps below configure a single member account; for each additional member account in scope, repeat Steps 3–4 **and** extend Step 2's `sts:AssumeRole` permissions policy so its `Resource` array lists the cross-account role ARN in every member account (the central invoker role needs assume permission for all of them, or discovery for the later accounts fails with `AccessDenied`).
**org_id** (optional): AWS Organizations ID (e.g., "o-abc123") for trust policy conditions
**invoker_role_name** (optional, default: "ResilienceHubAssessmentRole"): IAM role in the central account that Resilience Hub assumes
**cross_account_role_name** (optional, default: "ResilienceHubAccess"): IAM role in member accounts
**external_id** (optional): External ID for cross-account role assumption
**service_name** (required for Step 4): Name for the service to register in Resilience Hub
**regions** (required for Step 4): JSON array of the regions the service spans (e.g. `'["us-east-1"]'`)
**service_arn** (derived): The service ARN returned by `create-service` in Step 4 — capture it from that response for use in Step 5 (not supplied as an input)

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify that either the AWS CLI (e.g., `aws --version`) or the AWS MCP server's `call_aws` tool is available
- You MUST NOT run any AWS API calls or mutating commands during this verification — a lightweight availability check such as `aws --version` is acceptable, but do not invoke any `resiliencehubv2` or `iam` operations
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools

### 2. Create the Invoker Role in the Central Account

Set up the IAM role Resilience Hub assumes in the central account.

**Constraints:**

- You MUST inform the customer that the central account needs an invoker IAM role that Resilience Hub assumes to perform assessments
- You MUST recommend the role trust the `resiliencehub.amazonaws.com` service principal
- You MUST inform the customer this role needs `sts:AssumeRole` permission for the member-account cross-account roles
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws iam create-role --role-name {invoker_role_name} --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"resiliencehub.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"{central_account_id}"}}}]}'`
- The invoker role's trust policy **MUST be emitted exactly as written in the `create-role` command above — do not reconstruct, summarize, or simplify it.** The `"Condition":{"StringEquals":{"aws:SourceAccount":"{central_account_id}"}}` block is the confused-deputy guard and is **REQUIRED**: it MUST appear verbatim in the trust policy you submit, scoping trust so only the central account's Resilience Hub service principal can assume the role. **Never drop the `Condition` block from the invoker role's trust policy**, even when the user does not explicitly ask for hardening.
- The `create-role` command above only sets the **trust policy** (who may assume the invoker role). You MUST ALSO attach a **permissions policy** that lets the invoker role assume each cross-account role — without it, cross-account discovery fails with `AccessDenied`. The `Resource` array MUST list the cross-account role ARN for **every** member account in scope (add an entry per account; scope to the specific ARNs, never `*`) — a single-account `Resource` will cause `AccessDenied` for the other accounts. Run: `aws iam put-role-policy --role-name {invoker_role_name} --policy-name AssumeCrossAccountResilienceRoles --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Resource":["arn:aws:iam::{member_account_id}:role/{cross_account_role_name}"]}]}'`

### 3. Configure Cross-Account IAM Roles in Member Accounts

Set up IAM roles in member accounts that the central invoker role can assume.

**Constraints:**

- You MUST inform the customer that each member account needs an IAM role with a trust policy allowing the central account's invoker role to assume it
- You MUST recommend using the `aws:PrincipalOrgID` condition to restrict access to the organization
- You MUST recommend an `externalId` condition for defense in depth
- You SHOULD recommend generating the `externalId` with a secure random generator (e.g. `aws secretsmanager get-random-password --password-length 32 --exclude-punctuation`) and storing it in AWS Secrets Manager / SSM Parameter Store, referenced dynamically at deploy time rather than hardcoded
- You MUST inform the customer that the cross-account role only needs READ-ONLY permissions for resource discovery (e.g. `cloudformation:Describe*`, `ec2:Describe*`, `rds:Describe*`); recommend it not include any write/mutate permissions
- You SHOULD recommend deploying the role via CloudFormation StackSets for consistency across accounts
- You MUST run the following AWS CLI command in each member account (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws iam create-role --role-name {cross_account_role_name} --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::{central_account_id}:role/{invoker_role_name}"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"sts:ExternalId":"{external_id}","aws:PrincipalOrgID":"{org_id}"}}}]}'`, then attach an explicit least-privilege read-only discovery policy with `aws iam put-role-policy` (the AWS docs attach the broad `ReadOnlyAccess` managed policy for simplicity, but we recommend a tighter least-privilege policy instead — avoid `ReadOnlyAccess`): `aws iam put-role-policy --role-name {cross_account_role_name} --policy-name ResilienceHubDiscovery --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["cloudformation:DescribeStacks","cloudformation:ListStackResources","ec2:DescribeInstances","rds:DescribeDBInstances","elasticloadbalancing:DescribeLoadBalancers"],"Resource":"*"}]}'` (this action list is illustrative, not exhaustive — Resilience Hub's required discovery permissions grow as it adds support for new resource types, so consult the current [Resilience Hub IAM permissions reference](https://docs.aws.amazon.com/resilience-hub/latest/userguide/security-iam.html) and extend the action list to cover the resource types actually in scope rather than treating the list above as complete)
- You MUST omit the `sts:ExternalId` condition key from the trust policy if `external_id` is not provided, and omit `aws:PrincipalOrgID` if `org_id` is not provided; if neither is provided, omit the `Condition` block entirely — leaving an empty `""` placeholder makes the role unassumable. You SHOULD warn the customer that omitting **both** conditions removes the confused-deputy guard entirely (any principal the trust policy names could assume the role), and you SHOULD NOT proceed without at least one of `aws:PrincipalOrgID` or `sts:ExternalId` — treat supplying one as the secure default, and recommend both together for defense in depth.

### 4. Create Services with the Cross-Account Permission Model

Register services that span member accounts using the permission model.

**Constraints:**

- You MUST inform the customer that this is run from the central account
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 create-service --name {service_name} --regions '{regions}' --permission-model '{"invokerRoleName":"{invoker_role_name}","crossAccountRoles":[{"crossAccountRoleArn":"arn:aws:iam::{member_account_id}:role/{cross_account_role_name}","externalId":"{external_id}"}]}'`
- You MUST include the permission model with cross-account role ARNs for each member account
- You MUST omit the `externalId` field from each `crossAccountRoles` entry if `external_id` is not provided — this MUST match Step 3, where the trust policy omits the `sts:ExternalId` condition in that case. Passing a placeholder/empty `externalId` that the member-account trust policy does not expect will cause the cross-account `AssumeRole` to fail.
- You SHOULD recommend using an external ID for additional security
- You MUST NOT invent a `register-delegated-administrator` **`resiliencehubv2` CLI operation** — there is none. Organization-wide delegated-administrator registration is done via AWS Organizations trusted access + the Resilience Hub console, separately from this per-service `create-service` flow (do not conflate the two)
- You MUST capture the `serviceArn` from the `create-service` response (`{service_arn}`) and reuse it in Step 5's verification commands

### 5. Verify Cross-Account Visibility

Confirm the central account can assess resources across accounts.

**Constraints:**

- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-services` to verify the cross-account services were created
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws resiliencehubv2 list-input-sources --service-arn {service_arn}` to confirm resources in member accounts were discovered
- You MUST inform the customer that if discovery fails, the most likely cause is the member-account IAM role trust policy or missing resource-discovery permissions

## Security Considerations

See [SKILL.md](../SKILL.md) for the full Security Considerations. When executing only from this procedure, surface these controls to the customer:

- **Scope cross-account trust narrowly:** the cross-account role should trust only the specific central invoker-role ARN (not the whole account), gated with `aws:PrincipalOrgID` and an `externalId` condition, and grant read-only discovery permissions only — never write/mutate actions. For read-only `Describe*` discovery actions that do not support resource-level permissions, `"Resource": "*"` is acceptable (as in Step 3); for any actions that do support resource-level ARNs, scope `Resource` to the specific ARNs in scope rather than `*`.
- **Rotate the `externalId` periodically:** treat it as a shared secret — generate it randomly, store it in AWS Secrets Manager / SSM Parameter Store, reference it dynamically, rotate on a schedule, and never hardcode it or emit it in plaintext (CI/CD logs, IaC output).
- **Avoid leaking the `externalId` to shell history:** because it is a shared secret, avoid passing the `externalId` — or any policy document / permission-model payload containing it — where it is captured in shell history (`~/.bash_history`) and process listings. **When using the AWS CLI directly,** prefer a `file://…` payload reference (or `--cli-input-json file://…`), or disable history for the session (`set +o history`). **When using the AWS MCP server's `call_aws` tool,** pass the payload as inline JSON — the tool does not access the local filesystem, so `file://` references do not apply — and source the `externalId` from a secret store (Secrets Manager / SSM SecureString) at call time rather than hardcoding it. Either way, do not commit or log the real secret.
- **Monitor for unauthorized access:** enable AWS CloudTrail in both the central and member accounts to log cross-account `sts:AssumeRole` calls, and alarm on failed or unexpected AssumeRole attempts against the cross-account roles.

## Examples

```bash
# Create a cross-account service from the central account
aws resiliencehubv2 create-service --name "payment-api" --regions '["us-east-1"]' \
  --permission-model '{"invokerRoleName":"ResilienceHubAssessmentRole","crossAccountRoles":[{"crossAccountRoleArn":"arn:aws:iam::222222222222:role/ResilienceHubAccess","externalId":"{external_id}"}]}'

# The externalId is a shared secret that defends against confused-deputy attacks —
# generate a cryptographically random value and store it in Secrets Manager rather than
# hardcoding a static value, then reference the secret at deploy time:
#   aws secretsmanager create-secret --name resilience-hub/cross-account-external-id \
#     --generate-random-password --password-length 32

# Verify the service and its discovered resources
aws resiliencehubv2 list-services
aws resiliencehubv2 list-input-sources --service-arn {service_arn}
```

## Troubleshooting

**Cross-account assessment fails with AccessDenied**
The IAM role in the member account either doesn't exist, has an incorrect trust policy, or lacks resource discovery permissions. Verify: (1) the cross-account role ARN matches exactly, (2) the trust policy allows the central account's invoker role to assume it, (3) the externalId matches if configured.

**No resources discovered in a member account**
Confirm the cross-account role has read permissions for the resource types in scope (CloudFormation, EC2, RDS, etc.) and that the input source points to valid resources in that account's region.

**Looking for a delegated-administrator setup**
Resilience Hub v2 **does** support an AWS Organizations integration with a delegated administrator for organization-wide policy management and visibility — set it up from the **management account** via Organizations trusted access + the Resilience Hub console (create the service-linked role, then register the delegated administrator). It is not a `resiliencehubv2` CLI operation. To assess a single service whose resources span accounts, use the per-service cross-account permission model in this SOP; the two are complementary.
