# Reviewing Security Hub CSPM Configuration

## Overview

Reviews Security Hub CSPM configuration — standards, controls, and compliance posture management using ASFF format. Covers enabled standards (FSBP, CIS, PCI-DSS, NIST 800-53, NIST 800-171, AI Best Practices, Resource Tagging), control status, automation rules, and organization-wide policy enforcement.

Security Hub CSPM provides two categories of functionality:

- **Compliance management** — standards, controls, compliance findings
- **ASFF hub features** — finding aggregation, automation rules, custom actions, cross-region aggregation

This skill works from both standalone accounts and delegated administrator accounts.

**API constraint:** MUST use V1 APIs (no `-v2` suffix) only. MUST NOT use V2 APIs.

**Membership:** Supports both Organizations (Central Configuration) and legacy invitation-based membership.

## Classify the Request

| Signal | Workflow |
|--------|----------|
| Standards enabled, control status, disabled controls | A: Review Standards & Controls |
| Automation rules, org-wide policies, standard enforcement | B: Review Automation & Policies |

## Workflow A: Review Standards & Controls

1. List enabled standards:

   ```bash
   aws securityhub get-enabled-standards
   ```

2. For each enabled standard, list controls:

   ```bash
   aws securityhub describe-standards-controls --standards-subscription-arn <arn>
   ```

3. Get security control definitions:

   ```bash
   aws securityhub list-security-control-definitions
   ```

4. Batch check specific controls:

   ```bash
   aws securityhub batch-get-security-controls --security-control-ids '["EC2.1","S3.1","IAM.1"]'
   ```

5. Identify disabled controls:

   ```bash
   aws securityhub describe-standards-controls --standards-subscription-arn <arn> --query "Controls[?ControlStatus=='DISABLED']"
   ```

6. Check custom actions:

   ```bash
   aws securityhub describe-action-targets
   ```

   **Constraints:**

   - MUST enumerate all enabled standards
   - MUST report disabled controls with their DisabledReason
   - SHOULD flag standards available but not enabled
   - SHOULD note control count per standard (enabled vs total)

## Workflow B: Review Automation & Policies

0. Determine membership model:

   ```bash
   aws securityhub describe-organization-configuration
   ```

   If succeeds: Organizations (Central Configuration). If fails: may use invitation-based or not an admin.

1. List automation rules:

   ```bash
   aws securityhub list-automation-rules
   ```

2. Get rule details:

   ```bash
   aws securityhub batch-get-automation-rules --automation-rules-arns '["<arn>"]'
   ```

3. List configuration policies:

   ```bash
   aws securityhub list-configuration-policies
   ```

4. Get policy details:

   ```bash
   aws securityhub get-configuration-policy --identifier <policy-id>
   ```

5. Check policy associations:

   ```bash
   aws securityhub list-configuration-policy-associations --filters '{"ConfigurationPolicyId":"<policy-id>"}'
   ```

6. Check org configuration:

   ```bash
   aws securityhub describe-organization-configuration
   ```

   **Security check:** Verify CloudTrail is enabled and logging Security Hub CSPM API calls (`securityhub:*` events without `-v2` suffix) for audit purposes.

## Constraints

- MUST run from delegated admin for policy management
- MUST report automation rules that suppress or archive findings
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member status if user explicitly requests it
- SHOULD verify configuration policies enforce required standards across OUs

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Standard shows enabled but no controls | describe-standards-controls — may be pending initial evaluation |
| Control status NOT_AVAILABLE | Resource type not present in account |
| Automation rule not triggering | Check rule criteria and RuleStatus=ENABLED |
| Configuration policy not applying | Verify association target and policy status |

## Output Sensitivity

Configuration output reveals enabled compliance standards, disabled controls with reasons, automation rule logic, configuration policy definitions, and organization enrollment structure. Present configuration summary first; offer raw API responses on request.
