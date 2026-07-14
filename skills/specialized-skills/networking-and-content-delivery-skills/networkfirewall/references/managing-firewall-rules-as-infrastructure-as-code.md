# Managing Firewall Rules as Infrastructure as Code

## Overview

Domain expertise for managing AWS Network Firewall through CloudFormation or the AWS CDK so rules
change often and safely without redeploying the firewall or risking a wide outage. Covers decoupling
the rule groups from the firewall and policy so a rule change has a small blast radius, sizing rule
group capacity for growth because it is immutable, keeping the rule order consistent across template
resources, and holding frequently-changing rule content in Systems Manager Parameter Store so a list
change is not a template edit.

The key design choice is separation. Put the firewall and policy in one place and the rule groups in
another, so a routine rule change updates a small rule group stack and leaves the firewall endpoints
untouched. Several Network Firewall properties are immutable, so the wrong structure makes a routine
change a replacement.

Does not cover the firewall's traffic routing, Suricata rule syntax itself, logging, or TLS
inspection. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the deployment Region on
every command.

## Table of Contents

- Overview
- Workflow
- Separate rule groups from the firewall and policy
- Size capacity for growth: it is immutable
- Keep rule order consistent across resources
- Externalize frequently-changing rule content
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To manage firewall rules as infrastructure as code end to end, follow the procedure. It defines the
firewall and policy in one stack and the rule groups in a separate stack, sizes rule group capacity
for expected growth, sets a consistent rule order across the rule group and policy resources, and
reads frequently-changing rule content from Systems Manager Parameter Store so a list change does not
require a template edit.

## Separate rule groups from the firewall and policy

**Constraints:**

- You MUST place the rule groups in a separate stack or template from the firewall and policy, so a
  rule change updates a small rule group stack and leaves the firewall endpoints untouched
- You MUST avoid putting the firewall, policy, and rule groups in one stack where a routine rule
  change can force a replacement of the firewall or its endpoints and cause an outage on every deploy

## Size capacity for growth: it is immutable

**Constraints:**

- You MUST size each rule group's capacity for expected growth at creation; capacity is immutable, so
  a later increase replaces the rule group and drops its rules during the replacement window
- You MUST call out a capacity change as a replacement, not an in-place update, so the team plans for
  it rather than discovering it in production

## Keep rule order consistent across resources

**Constraints:**

- You MUST set the rule order (`STRICT_ORDER` or `DEFAULT_ACTION_ORDER`) consistently across the rule
  group and the policy resources; the two must match and the setting is immutable
- You MUST treat a change to the rule order as a replacement of the affected resources

## Externalize frequently-changing rule content

**Constraints:**

- You SHOULD keep frequently-changing rule content (allow lists, block lists, IP set values) in
  Systems Manager Parameter Store and have the template read it, so a list change does not require a
  template edit and a full pipeline run
- You SHOULD prefer IP set references for address lists that change, so the set updates without a
  rule group change
- You MUST confirm a CloudFormation `{{resolve:ssm-secure:...}}` dynamic reference is supported for
  the target `AWS::NetworkFirewall::RuleGroup` property before relying on it — SecureString dynamic
  references are only honored on the resource properties CloudFormation lists as supported; consult
  the current CloudFormation dynamic references documentation for the properties in scope. Where it is
  not supported, use a regular String parameter resolved with `{{resolve:ssm:...}}` (Parameter Store
  String values are encrypted at rest with the AWS-managed SSM key), or have the deployment pipeline
  read the SecureString value and inject it as a template parameter at deploy time; CDK users can
  read a SecureString via a context lookup or custom resource

## Troubleshooting

### Every rule change triggers a firewall replacement
The firewall, policy, and rule groups are in one stack. Split the rule groups into their own stack
(Separate rule groups from the firewall and policy).

### A capacity bump dropped rules in production
Capacity is immutable, so the change replaced the rule group. Size for growth at creation and plan
capacity changes as replacements (Size capacity for growth: it is immutable).

### Deploy fails on a rule order property
The rule order differs between the rule group and the policy, or a change to it was attempted in
place. Match the order across resources and treat a change as a replacement (Keep rule order
consistent across resources).

## Procedure

### Overview

This procedure defines the firewall and policy in one stack and the rule groups in a separate stack,
sizes capacity for growth, sets a consistent rule order, and reads changing rule content from
Parameter Store.

### Parameters

- **tool** (required): `cloudformation` or `cdk`.
- **firewall_stack** (required): The stack holding the firewall and policy.
- **rule_group_stack** (required): The separate stack holding the rule groups.
- **rule_order** (required): `STRICT_ORDER` or `DEFAULT_ACTION_ORDER`, consistent across resources.
- **capacity** (required): Capacity units per rule group, sized for growth (immutable).
- **firewall_name** (required): The deployed firewall's name, for the console link in the final step.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the rule groups are in a separate stack from the firewall and policy

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the target deployment tool and the stack separation before generating templates

#### 2. Define the firewall and policy stack

**Constraints:**

- You MUST define `AWS::NetworkFirewall::Firewall` and `AWS::NetworkFirewall::FirewallPolicy` in the
  firewall stack, with the rule order set in `StatefulEngineOptions`
- You MUST set the `EncryptionConfiguration` property on the `AWS::NetworkFirewall::Firewall` resource
  with `Type: CUSTOMER_KMS` and a customer-managed AWS KMS key so the firewall's data is encrypted at
  rest; without it the firewall defaults to an AWS-owned key
- You MUST reference the rule groups by ARN exported from the rule group stack, not inline

#### 3. Define the rule group stack

**Constraints:**

- You MUST define `AWS::NetworkFirewall::RuleGroup` resources in the separate stack, with capacity
  sized for growth and the rule order matching the policy
- You MUST set the `EncryptionConfiguration` property on each `AWS::NetworkFirewall::RuleGroup`
  resource with `Type: CUSTOMER_KMS` and a customer-managed AWS KMS key so the rule logic is encrypted
  at rest, consistent with the firewall resource; without it the rule group defaults to an AWS-owned key
- You SHOULD read frequently-changing rule content from Systems Manager Parameter Store rather than
  hardcoding it

#### 4. Deploy and confirm no firewall replacement on rule changes

**Constraints:**

- You MUST deploy the rule group stack first so it creates the rule groups and exports their ARNs,
  then deploy the firewall stack second so its policy can import those ARNs; deploying the firewall
  stack first fails on the first deployment because the exported ARNs do not yet exist
- You MUST confirm a subsequent rule change updates only the rule group stack and leaves the firewall
  stack untouched
- You SHOULD run a change set (CloudFormation) or `cdk diff` to confirm a rule change does not show
  the firewall or its endpoints as replaced

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm the firewall and rule groups deployed and the policy references the rule groups
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "tool": "cdk",
  "firewall_stack": "nfw-firewall",
  "rule_group_stack": "nfw-rule-groups",
  "rule_order": "STRICT_ORDER",
  "capacity": 1000,
  "firewall_name": "nfw-firewall"
}
```

#### Example output

```
Firewall and policy in nfw-firewall; rule groups in nfw-rule-groups, capacity 1000, STRICT_ORDER on both.
Block list read from SSM Parameter Store. cdk diff on a list change shows only the rule group stack updated, firewall unchanged.
Open the console and confirm:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=nfw-firewall
```

### Troubleshooting

#### Rule change wants to replace the firewall
The stacks are not separated. Split them (Step 3).

#### Capacity change replaces the rule group
Expected: capacity is immutable. Size for growth at creation (Step 3).

## Security Considerations

Templates make rule content and its deployment auditable, but they also persist sensitive data and
control what the firewall enforces.

- You SHOULD hold rule content that contains sensitive indicators (internal IP ranges, threat
  intelligence) in Parameter Store rather than committing it into the template source. Confirm from
  the current CloudFormation dynamic references documentation whether a `{{resolve:ssm-secure:...}}`
  reference is supported for the target `AWS::NetworkFirewall::RuleGroup` property; where it is not,
  either use a String parameter resolved with `{{resolve:ssm:...}}` (encrypted at rest with the
  AWS-managed SSM key) or inject a SecureString value at deploy time through the pipeline.
- You MUST encrypt the firewall's data at rest with a customer-managed AWS KMS key, and retain that
  key for the life of the firewall, since deleting or revoking it puts the firewall into a
  non-recoverable failed state.
- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access; scope the deployment role to the specific AWS Network
  Firewall, AWS Systems Manager Parameter Store, and AWS KMS resources the stacks manage, and deny
  any policy statement that grants a service wildcard (`network-firewall:*`, `ssm:*`, or `kms:*`).
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, rule group capacity
  warnings, and stack drift or deployment failures, so issues introduced by a template change are
  detected and escalated promptly. You MUST encrypt any SNS topic used for these alarm
  notifications with a customer-managed AWS KMS key and restrict alarm notification recipients to
  authorized operations and security personnel, since alarm messages can expose sensitive firewall
  metadata (endpoint status, traffic patterns, and capacity).
- You SHOULD review a change set or `cdk diff` before applying, so a rule change does not silently
  weaken the policy or replace the firewall and its endpoints.

## Additional Resources

- [AWS::NetworkFirewall::Firewall (AWS CloudFormation User Guide)](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-networkfirewall-firewall.html)
- [AWS::NetworkFirewall::FirewallPolicy (AWS CloudFormation User Guide)](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-networkfirewall-firewallpolicy.html)
- [AWS::NetworkFirewall::RuleGroup (AWS CloudFormation User Guide)](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-networkfirewall-rulegroup.html)
- [aws-cdk-lib.aws_networkfirewall module (AWS CDK API Reference)](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_networkfirewall-readme.html)
- [What is AWS Systems Manager Parameter Store? (AWS Systems Manager User Guide)](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
