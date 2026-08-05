# Reviewing Inspector Configuration

## Overview

Assesses Amazon Inspector configuration completeness by checking scan type enablement, coverage, suppression rules, and organization member status. Results are presented as a configuration state summary.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| Check Inspector config in this account | A: Review Single Account |
| Audit Inspector scanning enabled | A: Review Single Account |
| Review organization coverage | B: Review Organization Coverage |
| Check which members have Inspector | B: Review Organization Coverage |

## Workflow A: Review Single Account

1. Get account status for all scan types:

   ```bash
   aws inspector2 batch-get-account-status
   ```

2. Report ALL scan types and their status (ENABLED/DISABLED/SUSPENDED). Do not hardcode a scan type list; report whatever the API returns.

   For reference on available scan types, see: https://docs.aws.amazon.com/inspector/latest/user/scanning-resources.html

3. Check coverage statistics:

   ```bash
   aws inspector2 list-coverage-statistics --filter-criteria {} --group-by RESOURCE_TYPE
   ```

4. List coverage to identify unscanned resources:

   ```bash
   aws inspector2 list-coverage --filter-criteria '{"scanStatusCode":[{"comparison":"EQUALS","value":"INACTIVE"}]}'
   ```

5. Check suppression rules:

   ```bash
   aws inspector2 list-filters
   ```

6. Check CIS scan configurations:

   ```bash
   aws inspector2 list-cis-scan-configurations
   ```

7. Check EC2 deep inspection:

   ```bash
   aws inspector2 get-ec2-deep-inspection-configuration
   ```

8. Present results:

   **Security check:** Verify CloudTrail is enabled and logging Inspector API calls (`inspector2:*` events) for audit purposes.

   | Check | Status |
   |---|---|
   | Each scan type from API response | Enabled / Disabled / Suspended |
   | EC2 deep inspection configured | Configured / Not Configured |
   | CIS benchmarks configured | Configured / Not Configured |
   | Coverage status (inactive resources) | None / Count |
   | Suppression rules present | Count |

## Workflow B: Review Organization Coverage

1. Identify delegated admin:

   ```bash
   aws inspector2 list-delegated-admin-accounts
   ```

2. Check organization configuration:

   ```bash
   aws inspector2 get-configuration
   ```

   Report ALL scan types and their auto-enable status.

   > For organization-level Inspector policies (INSPECTOR_POLICY), see `references/organization-policies.md`.

3. Get org-wide coverage statistics:

   ```bash
   aws inspector2 list-coverage-statistics --filter-criteria {} --group-by RESOURCE_TYPE
   ```

4. (ONLY if user explicitly requests per-account detail):

   ```bash
   aws inspector2 list-members
   aws inspector2 batch-get-account-status --account-ids <ACCOUNT_IDS>
   ```

   MAY batch up to 100 account IDs per call.

5. Present results:

   | Check | Status |
   |---|---|
   | Delegated admin configured | Enabled / Not Enabled |
   | Auto-enable per scan type | Enabled / Not Enabled |
   | Member accounts | Enrolled (details on request) |
   | Coverage statistics by resource type | See details |

## Constraints

- MUST check ALL scan types, not a subset
- MUST report inactive/failed scan status distinctly from disabled
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member status if user explicitly requests it

## Troubleshooting

| Symptom | Resolution |
|---|---|
| batch-get-account-status returns DISABLED | Inspector not enabled — report as not configured |
| Access denied on list-members | Not a delegated admin — run Workflow A instead |
| list-coverage returns empty | No supported resources in account |
| SUSPENDED status | Account suspended from Inspector — report with note |

## Output Sensitivity

Configuration output reveals account structure (member account IDs), scan type enablement, resource coverage details (EC2 instance IDs, Lambda ARNs, ECR repositories), and suppression rules. Present configuration summary first; offer raw API responses on request.
