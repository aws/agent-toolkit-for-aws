# Summarizing Security Hub Findings

## Overview

Summarizes AWS Security Hub V2 (OCSF) findings to provide a high-level security posture overview. Uses V2 statistics and trends APIs for aggregated views.

This skill works from both standalone accounts and delegated administrator accounts.

**API constraint:** MUST use V2 APIs (suffixed with `-v2`) only. MUST NOT use V1 finding APIs (`get-findings`, `get-insights`, `get-insight-results`).

## Operator prerequisites

**Prerequisite:** Operator must assume an IAM role with least-privilege read-only permissions. Scope permissions to the V2 actions listed in `references/security-hub.md`; avoid FullAccess managed policies and `securityhub:*` wildcards. Do not use long-lived IAM user access keys.

## Classify the Request

| Signal | Workflow |
|--------|----------|
| Single account findings, top risks, resource breakdown | A: Account Findings Summary |
| Cross-account view, org-wide risk, hotspot accounts | B: Organization Findings Overview |

## Exposure filter template

For CLI syntax questions, explain this template without querying an account.
Replace both placeholders with a supported string field and an exact,
case-sensitive value verified from current documentation or authorized OCSF
evidence. The example does not establish which discriminator identifies Exposure
findings in the customer's data. If that remains unknown, leave the template
unfilled and state the limitation instead of guessing or repeatedly searching for
a universal `class_name=Exposure` value.

Pass this filter to `--filters` as an inline JSON string. Do not read it from a local
file: `file://` inputs do not work through the AWS MCP server's `call_aws`.

```json
{
  "CompositeFilters": [
    {
      "StringFilters": [
        {
          "FieldName": "<verified-string-field>",
          "Filter": {
            "Value": "<verified-exposure-value>",
            "Comparison": "EQUALS"
          }
        }
      ],
      "Operator": "AND"
    }
  ],
  "CompositeOperator": "AND"
}
```

After verification, retain the authorized account/resource constraints in the
filter and use the selected profile and region:

```bash
aws securityhub get-findings-v2 \
  --profile <profile> --region <region> \
  --filters '{"CompositeFilters":[{"StringFilters":[{"FieldName":"<verified-string-field>","Filter":{"Value":"<verified-exposure-value>","Comparison":"EQUALS"}}],"Operator":"AND"}],"CompositeOperator":"AND"}' \
  --page-size 100 --max-items 100
```

`--page-size` controls the service page size; `--max-items` caps the total returned
by the CLI paginator. A limited result is a sample, not complete findings coverage.
The API's `MaxResults` is a per-page limit, not a total-result cap.
See the [current CLI contract](https://docs.aws.amazon.com/cli/latest/reference/securityhub/get-findings-v2.html).

## Workflow A: Account Findings Summary

1. Get finding statistics. Interpret returned OCSF severity IDs using the mapping in
   [Security Hub](references/security-hub.md). Preserve reported IDs and unknown/unmapped
   values rather than applying CSPM/ASFF or GuardDuty severity scales:

   ```bash
   aws securityhub get-finding-statistics-v2 --group-by-rules '[{"GroupByField":"severity"}]'
   ```

   Valid GroupByField values (examples — see [API reference](https://docs.aws.amazon.com/securityhub/latest/userguide/llms.txt) for the current set): `severity`, `status`, `resources.type`, `cloud.account.uid`, `cloud.region`, `metadata.product.name`, `finding_info.types`, `class_name`

2. Query for Exposure findings (cross-service resource exposure — prioritize these first):

   ```bash
   aws securityhub get-finding-statistics-v2 --group-by-rules '[{"GroupByField":"class_name"}]'
   ```

   If Exposure findings exist, retrieve them with the server-side
   [Exposure filter template](#exposure-filter-template):

   Verify the Exposure discriminator and exact case-sensitive value from the observed
   schema/product/type data and current API documentation, then apply a supported
   server-side filter within the authorized scope. Do not assume `class_name=Exposure`.
   An empty result from an unvalidated discriminator does not establish absence;
   retain unresolved Exposure coverage as UNKNOWN without expanding collection.

   Present Exposure findings first in summary.

3. Get findings trends:

   ```bash
   aws securityhub get-findings-trends-v2 --start-time <ISO-8601> --end-time <ISO-8601>
   ```

   Default to last 30 days.

4. Get active findings:

   ```bash
   aws securityhub get-findings-v2 --page-size 100 --max-items 100
   ```

5. Get resource-centric view:

   ```bash
   aws securityhub get-resources-v2 --page-size 100 --max-items 100
   ```

6. Get resource statistics:

   ```bash
   aws securityhub get-resources-statistics-v2 --group-by-rules '[{"GroupByField":"ResourceType"}]'
   ```

   Valid GroupByField values (examples — see [API reference](https://docs.aws.amazon.com/securityhub/latest/userguide/llms.txt) for the current set): `AccountId`, `Region`, `ResourceType`, `ResourceCategory`

7. Get resource trends:

   ```bash
   aws securityhub get-resources-trends-v2 --start-time <ISO-8601> --end-time <ISO-8601>
   ```

## Workflow B: Organization Findings Overview

1. Get org-wide finding statistics:

   ```bash
   aws securityhub get-finding-statistics-v2 --group-by-rules '[{"GroupByField":"severity"}]'
   ```

2. Query for Exposure findings across the org (prioritize these first):

   ```bash
   aws securityhub get-finding-statistics-v2 --group-by-rules '[{"GroupByField":"class_name"}]'
   ```

   If Exposure findings exist, retrieve with the
   [Exposure filter template](#exposure-filter-template) and present first:

   Verify the Exposure discriminator and exact case-sensitive value from the observed
   schema/product/type data and current API documentation, then apply a supported
   server-side filter within the authorized scope. Do not assume `class_name=Exposure`.
   An empty result from an unvalidated discriminator does not establish absence;
   retain unresolved Exposure coverage as UNKNOWN without expanding collection.

3. Get org-wide trends:

   ```bash
   aws securityhub get-findings-trends-v2 --start-time <ISO-8601> --end-time <ISO-8601>
   ```

4. Get resource statistics across org:

   ```bash
   aws securityhub get-resources-statistics-v2 --group-by-rules '[{"GroupByField":"ResourceType"}]'
   ```

5. For drill-down:

   ```bash
   aws securityhub get-findings-v2 --page-size 100 --max-items 100
   ```

6. Get resource trends:

   ```bash
   aws securityhub get-resources-trends-v2 --start-time <ISO-8601> --end-time <ISO-8601>
   ```

   **Security check:** See SKILL.md Security considerations for CloudTrail audit logging, CloudWatch anomaly alarms, KMS/TLS encryption, SNS recipient validation, and current AWS security best-practice references.

## Constraints

- Name the count unit and scope: finding records, deduplicated findings or resource occurrences. Do not sum overlapping type/class buckets as unique findings; deduplicate stable identifiers in matching account/region scope first.
- Attribute severity/counts to a product only from matching product-scoped evidence. A detection-class total is not a GuardDuty total, and overall severity counts are not Inspector-specific counts. Reconcile breakdown sums and label samples separately from totals.

- MUST use get-finding-statistics-v2 for aggregated summaries (not paginating all findings)
- MUST prioritize Exposure findings (attack paths, resource exposure) first in output
- MUST prioritize critical and high severity findings
- SHOULD include finding count per category
- SHOULD use get-findings-trends-v2 to show posture improvement/degradation
- V2 filters use OCSF field paths — check API reference for filter syntax
- MUST run from delegated admin for cross-account visibility (Workflow B)

## Troubleshooting

| Symptom | Check |
|---------|-------|
| No findings returned | Verify hub is enabled via describe-security-hub-v2 |
| Only single account findings | Confirm delegated admin; check aggregation via list-aggregators-v2 |
| Pagination incomplete | Use NextToken to retrieve all pages |
| Filter syntax errors | V2 uses OCSF field paths, not ASFF |

## Output Sensitivity

OCSF findings contain aggregated data from source services including IP addresses, resource ARNs, network exposure paths, account IDs, vulnerability details, and threat correlation details. Present finding statistics and severity distribution first. Display full OCSF finding bodies only when the caller explicitly requests raw output. Avoid logging raw finding or resource responses in plaintext, store exported findings data only in downstream destinations encrypted at rest, and transmit exported data only over encrypted channels such as TLS. If logging to CloudWatch Logs, verify the log group is encrypted with a KMS key. If findings are forwarded to SNS topics via automation rules or connectors, verify those topics are encrypted with a KMS key, verify SNS topic resource policies include `aws:SourceArn` and `aws:SourceAccount` condition keys, and verify periodic audits confirm subscription endpoints deliver findings notifications only to authorized security personnel.
