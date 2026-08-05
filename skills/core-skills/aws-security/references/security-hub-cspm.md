# Security Hub CSPM

- **Docs**: https://docs.aws.amazon.com/securityhub/latest/userguide/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/securityhub/latest/userguide/llms.txt

AWS Security Hub CSPM (Cloud Security Posture Management) evaluates AWS resource configurations against AWS and industry compliance standards. It uses ASFF format and provides automation rules, custom actions, and organization-wide configuration policies. It also receives findings from GuardDuty, Inspector, and Macie in ASFF format.

## Data Sources

Security Hub CSPM receives:

- AWS Config evaluations (compliance checks against standards)
- GuardDuty findings (in ASFF format)
- Inspector findings (in ASFF format)
- Macie findings (in ASFF format)
- Third-party findings (via `BatchImportFindings` API, ASFF format)

CSPM generates its own compliance findings by evaluating resources against enabled standards.

## Operator prerequisites

**Prerequisite:** Operator must assume an IAM role with least-privilege read-only permissions. Scope permissions to the actions listed in the Read-Only APIs table; avoid FullAccess managed policies and `securityhub:*` wildcards. Do not use long-lived IAM user access keys.

## Available Standards

Discover enabled and available standards dynamically:

```bash
# List currently enabled standards
aws securityhub get-enabled-standards

# List all available standard definitions
aws securityhub describe-standards
```

Do not rely on a static standards list in this reference. Use `describe-standards` output as the authoritative source for current names, versions, ARNs, and regional availability.

Always use `describe-standards` to discover the current standards list before naming specific standard versions or ARNs.

## API Convention

Security Hub CSPM APIs share the `aws securityhub` CLI namespace with Security Hub V2 but do NOT have a `-v2` suffix. All APIs in this file are unsuffixed. V2 APIs (with `-v2` suffix) are in `references/security-hub.md`. Shared APIs (used by both) are listed separately below.

## Read-Only APIs

### CSPM APIs (V1 — ASFF)

| API | Purpose |
|-----|---------|
| `securityhub:DescribeHub` | Check if Security Hub CSPM is enabled and get hub details |
| `securityhub:GetEnabledStandards` | List enabled compliance standards |
| `securityhub:DescribeStandards` | List all available standard definitions |
| `securityhub:DescribeStandardsControls` | List controls for a standard |
| `securityhub:ListSecurityControlDefinitions` | Get security control definitions |
| `securityhub:BatchGetSecurityControls` | Batch check specific controls |
| `securityhub:DescribeActionTargets` | List custom actions |
| `securityhub:ListAutomationRules` | List V1 automation rules |
| `securityhub:BatchGetAutomationRules` | Get automation rule details |
| `securityhub:GetFindings` | Get ASFF findings with filters |
| `securityhub:ListMembers` | List member accounts (org + invitation) |
| `securityhub:ListInvitations` | List pending invitations |

### Shared APIs (used by both V1 and V2)

| API | Purpose |
|-----|---------|
| `securityhub:DescribeOrganizationConfiguration` | Get org enrollment settings |
| `securityhub:ListConfigurationPolicies` | List configuration policies |
| `securityhub:GetConfigurationPolicy` | Get specific policy details |
| `securityhub:ListConfigurationPolicyAssociations` | Check policy target associations |

## Severity Scoring

CSPM compliance findings use the same normalized severity as Security Hub:

| Label | Meaning for Compliance |
|-------|----------------------|
| INFORMATIONAL | Control passed or not applicable |
| LOW | Non-critical control failed |
| MEDIUM | Moderate-risk control failed |
| HIGH | High-risk control failed |
| CRITICAL | Critical control failed (e.g., root account without MFA) |

**Key notes:**

- Severity is assigned per control definition, not per resource
- The same control failure has the same severity regardless of which account it appears in
- Enabled standards define severity per control; use `describe-standards-controls` for the current control metadata

## Security Check

See SKILL.md Security considerations for CloudTrail audit logging, CloudWatch anomaly alarms, KMS/TLS encryption, SNS recipient validation, and current AWS security best-practice references.

## Service Notes

No service-specific notes.

## Output Sensitivity

Security Hub CSPM findings (`GetFindings` ASFF) contain:

- AWS account IDs and resource ARNs across the organization
- Resource configuration details (security group rules, IAM policies, encryption settings)
- Compliance standard and control identifiers
- Third-party integration findings (GuardDuty, Inspector, Macie in ASFF format)
- Automation rule configurations and suppression logic

Present compliance pass/fail rates and severity distribution first. Offer full ASFF finding bodies on request. Avoid logging raw ASFF finding or configuration responses in plaintext, store exported CSPM data only in downstream destinations encrypted at rest, and transmit exported data only over encrypted channels such as TLS. If logging to CloudWatch Logs, verify the log group is encrypted with a KMS key. If CSPM findings or automation outputs are forwarded to SNS topics or S3 buckets, verify those destinations use KMS encryption and resource policies include `aws:SourceArn` and `aws:SourceAccount` condition keys.
