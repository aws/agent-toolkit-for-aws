# Summarizing Detective Investigations

## Overview

Produces structured summaries of Amazon Detective investigations and finding groups. Aggregates investigation status, severity distributions, and indicator types to give operators a rapid understanding of their investigation landscape.

Detective builds behavior graphs from CloudTrail management events, VPC Flow Logs, EKS Audit Logs, and Security Hub findings. Detective does NOT support S3 data events.

Works from both standalone and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| "Show me Detective investigations" | A: Active Investigations Summary |
| "Details on a specific investigation" | B: Investigation Detail |

## Workflow A: Active Investigations Summary

1. Obtain the graph ARN:

   ```bash
   aws detective list-graphs
   ```

   If no graphs, report Detective not configured and stop.

2. List investigations:

   ```bash
   aws detective list-investigations --graph-arn <graph-arn> --filter-criteria '{}'
   ```

3. Group results by `Status` (RUNNING, SUCCESSFUL, FAILED) and `Severity` (CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL).

4. Present results:

   | Status | Severity | Count | Most Recent |
   |---|---|---|---|
   | RUNNING | HIGH | 3 | inv-abc123 (2024-01-15) |

5. MUST include total counts per status category.

6. SHOULD note if any investigations are in FAILED state.

7. MAY paginate using NextToken if results exceed page size.

## Workflow B: Investigation Detail

1. Get investigation details:

   ```bash
   aws detective get-investigation --graph-arn <graph-arn> --investigation-id <id>
   ```

2. List indicators:

   ```bash
   aws detective list-indicators --graph-arn <graph-arn> --investigation-id <id>
   ```

3. Group indicators by whatever `IndicatorType` values the API returns. Do not validate against a fixed list — report all types present in the response.

   For reference on indicator types, see: https://docs.aws.amazon.com/detective/latest/userguide/investigations-report-understand.html

4. Present summary:

   | Indicator Type | Count |
   |---|---|
   | TTP_OBSERVED | 5 |
   | FLAGGED_IP_ADDRESS | 2 |
   | RELATED_FINDING_GROUP | 1 |

5. MUST include `EntityType` and `EntityArn` from investigation detail.

6. MUST NOT perform follow-up investigation on flagged entities.

## Constraints

- MUST NOT perform investigation actions (e.g., start-investigation)
- MUST NOT make threat assessments or attribution claims
- MUST NOT include raw IP addresses unless user explicitly requests IOC data
- SHOULD present data as-is without interpretation beyond grouping
- MUST handle AccessDeniedException gracefully

## Troubleshooting

| Issue | Resolution |
|---|---|
| GraphArn not known | Use `list-graphs` to discover available graphs |
| Empty investigation list | Confirm Detective is enabled and has processed data |
| AccessDeniedException | Verify caller is Detective administrator |
| FAILED investigations | Note in summary — may indicate entity resolution issues |

## Output Sensitivity

Investigation details contain AWS account IDs, IAM principal ARNs under investigation, flagged IP addresses, geolocation data, user agent strings, and related finding references. Present investigation status/severity summary first. Display full indicator details only when the caller explicitly requests raw output.
