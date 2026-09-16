# CloudFormation Validation Workflow

## Purpose

Use this guide to choose and sequence CloudFormation validation. Run the applicable layers in this order:

1. One local validator for syntax, schema, and resource-property checks.
2. cfn-guard for security and compliance checks.
3. CloudFormation service pre-deployment validation when account-aware checks are needed.

Each layer has different coverage. Report the outcome of each layer separately rather than treating one successful check as proof that the template is deployment-ready.

**AWS MCP server:** For steps that call AWS APIs, the AWS MCP server (`call_aws`) is recommended for sandboxed execution and audit logging, but it is not required. Every account-aware step also works with the AWS CLI; local validator steps require neither mechanism.

## Select one local validator

Use exactly one local validation tool unless the user explicitly requests a comparison. Honor an explicit tool request first. Otherwise, reuse the tool configured by the project. If the project configures neither tool, use `cfn-lint` when it is installed; if it is not installed but the `cfn-validate` CLI is installed, use cloudformation-validate. If neither tool is installed, propose an exact-version cfn-lint installation as the deterministic default and follow the cfn-lint SOP approval flow. Do not propose installing both tools.

- **cfn-lint:** Follow the [validate with cfn-lint SOP](validate-with-cfn-lint.script.md).
- **cloudformation-validate:** Follow the [validate with cloudformation-validate SOP](validate-with-cloudformation-validate.script.md).

Follow the selected SOP's dependency and approval flow if its tool is unavailable. Do not install or download a tool without explicit user approval because those actions change the user's environment.

For validation embedded in code or another process, use a published cloudformation-validate library for the application's language. Follow the in-process and CDK integration guidance in the [cloudformation-validate SOP](validate-with-cloudformation-validate.script.md).

## Run security and compliance checks by default

After local validation has no blocking findings, run the [cfn-guard security and compliance SOP](check-cloudformation-template-compliance.script.md) by default. Do not require the user to opt in.

Skip this layer only when the user explicitly requests a skip or confirms that an equivalent project security and compliance check already passed. If cfn-guard, its binding, or applicable rules are unavailable, follow the SOP's dependency and approval flow rather than silently omitting the check. If the layer is skipped or cannot run, state that security and compliance were not evaluated.

## Add account-aware pre-deployment validation

When account-aware checks are needed before deployment, follow the [CloudFormation service pre-deployment validation SOP](cloudformation-pre-deploy-validation.script.md).

Before using CloudFormation service operations, confirm that the CloudTrail controls in the Security Considerations section are satisfied. If required audit logging is unavailable, state the reduced auditability.

Pre-deployment validation is enabled by default on Create Stack, Update Stack, and change-set creation. A `FAIL`-mode finding halts the operation before any resource is provisioned. Retrieve validation results with `describe-events` using the scoping guidance in the pre-deployment SOP; do not use `describe-stack-events` because it does not return these validation results.

## Security Considerations

Follow the [shared security guidance](security-considerations.md).

Report local, security and compliance, and service pre-deployment validation as separate outcomes; one successful layer does not prove another passed.
