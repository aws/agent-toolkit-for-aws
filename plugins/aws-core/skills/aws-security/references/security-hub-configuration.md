# Reviewing Security Hub Configuration

## Overview

Reviews AWS Security Hub configuration — the unified security platform using OCSF format. Covers integrations, cross-region aggregation, connectors, automation rules, and organization-wide enrollment.

This skill works from both standalone accounts and delegated administrator accounts.

**API constraint:** MUST use V2 APIs (suffixed with `-v2`) only. MUST NOT use V1 APIs (`describe-hub`, `get-findings`, `list-finding-aggregators`, `get-enabled-standards`).

**Membership:** Security Hub V2 uses Organizations exclusively — no invitation-based membership.

## Operator prerequisites

**Prerequisite:** Operator must assume an IAM role with least-privilege read-only permissions. Scope permissions to the V2 and Organizations actions listed in `references/security-hub.md`; avoid FullAccess managed policies and `securityhub:*` wildcards. Do not use long-lived IAM user access keys.

## Classify the Request

| Signal | Workflow |
|--------|----------|
| Single account setup, integrations, connectors, automation rules | A: Review Single Account |
| Organization-wide coverage, member enrollment, configuration policies | B: Review Organization Coverage |

## Workflow A: Review Single Account

1. Check hub status:

   ```bash
   aws securityhub describe-security-hub-v2
   ```

2. List third-party product integrations (internal services flow automatically when enabled):

   ```bash
   aws securityhub describe-products-v2
   ```

3. Check cross-region aggregation:

   ```bash
   aws securityhub list-aggregators-v2
   ```

   Use the returned `AggregatorV2Arn` values to identify configured aggregators. If empty, note prominently: no home region aggregator configured — findings from other regions not visible.

4. If an aggregator exists and you need detailed configuration such as aggregation Region, region-linking mode, or linked Regions:

   ```bash
   aws securityhub get-aggregator-v2 --aggregator-v2-arn <arn-from-list>
   ```

5. Check connectors:

   ```bash
   aws securityhub list-connectors-v2
   ```

6. Check automation rules:

   ```bash
   aws securityhub list-automation-rules-v2
   ```

7. If this account is an Organizations management account or delegated administrator account, check organization policies:

   ```bash
   aws organizations list-policies --filter SECURITYHUB_POLICY
   ```

   > For the complete Organization policies pattern including all supported policy types, see `references/organization-policies.md`.

   If this call returns `AccessDeniedException`, skip steps 7-8 and report organization policy status as `Not checked - Organizations access unavailable`.

8. If policies exist, get details:

   ```bash
   aws organizations describe-policy --policy-id <id>
   ```

9. Present results:

   | Check | Status |
   |---|---|
   | Hub enabled | Enabled / Not Enabled |
   | Cross-region aggregator | Configured / Not Configured |
   | Third-party integrations | List enabled |
   | Connectors | Configured / Not Configured |
   | Automation rules | Configured / Not Configured |
   | Organization policies | Configured / Not Configured |

   **Security check:** See SKILL.md Security considerations for CloudTrail audit logging, CloudWatch anomaly alarms, KMS/TLS encryption, SNS recipient validation, and current AWS security best-practice references.

## Workflow B: Review Organization Coverage

1. Check organization policies:

   ```bash
   aws organizations list-policies --filter SECURITYHUB_POLICY
   ```

   > For the complete Organization policies pattern including all supported policy types, see `references/organization-policies.md`.

   If this call returns `AccessDeniedException`, skip steps 1-3, report organization policy status as `Not checked - Organizations access unavailable`, and continue with step 4 aggregation checks.

2. If policies exist, get details:

   ```bash
   aws organizations describe-policy --policy-id <id>
   ```

3. List targets for each policy to verify which roots, OUs, or accounts receive the configuration:

   ```bash
   aws organizations list-targets-for-policy --policy-id <id>
   ```

   If this call returns `AccessDeniedException`, report policy target status as `Not checked - Organizations access unavailable` and continue with aggregation checks that do not require policy-target access.

4. Verify aggregation:

   ```bash
   aws securityhub list-aggregators-v2
   ```

5. If an aggregator exists, inspect region configuration to confirm the aggregation Region, region-linking mode, and linked Regions cover all active Regions where the customer operates:

   ```bash
   aws securityhub get-aggregator-v2 --aggregator-v2-arn <arn-from-list>
   ```

6. (ONLY if user explicitly requests per-account detail):

   ```bash
   aws organizations list-accounts
   ```

   **Security check:** See SKILL.md Security considerations for CloudTrail audit logging, CloudWatch anomaly alarms, KMS/TLS encryption, SNS recipient validation, and current AWS security best-practice references.

## Constraints

- MUST check organization policies via list-policies --filter SECURITYHUB_POLICY when running from an Organizations management or delegated administrator account; otherwise skip and report as unavailable
- SHOULD verify aggregator regions cover all active regions where the customer operates
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member account status if user explicitly requests it
- SHOULD note integrations available but not enabled

## Troubleshooting

| Symptom | Check |
|---------|-------|
| No findings flowing | Verify source service is enabled (GuardDuty, Inspector). For third-party, check describe-products-v2 |
| Missing cross-region findings | Confirm aggregator covers all regions |
| Member not receiving policies | Check policy targets via `list-targets-for-policy --policy-id <id>` |
| Hub returns AccessDenied | Confirm delegated admin designation |
| Connectors not syncing | Check connector status via list-connectors-v2 |

## Output Sensitivity

Configuration output reveals aggregator regions, third-party product integration details, connector configurations (ITSM endpoints), automation rule logic, and organization enrollment status. Present configuration summary first; offer raw API responses on request. Avoid logging raw API responses in plaintext, store exported configuration data only in downstream destinations encrypted at rest, and transmit exported data only over encrypted channels such as TLS. If logging to CloudWatch Logs, verify the log group is encrypted with a KMS key. If using SNS topics as downstream destinations, verify those topics are encrypted with a KMS key. Verify resource policies for any S3 buckets or SNS topics used as downstream destinations include `aws:SourceArn` and `aws:SourceAccount` condition keys.
