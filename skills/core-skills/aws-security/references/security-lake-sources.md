# Summarizing Security Lake Sources

## Overview

Produces structured summaries of Amazon Security Lake source configuration, subscriber status, and data lake exceptions. Gives operators a rapid view of data lake health without performing data queries.

Works from both standalone and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| "What sources are configured?" | A: Sources & Ingestion Summary |
| "Show subscribers" / "Any data lake issues?" | B: Subscriber & Exception Overview |

## Workflow A: Sources & Ingestion Summary

1. Get configured sources:

   ```bash
   aws securitylake get-data-lake-sources
   ```

2. List log sources for detail:

   ```bash
   aws securitylake list-log-sources
   ```

3. Check data lake regions:

   ```bash
   aws securitylake list-data-lakes
   ```

4. Present source summary per region:

   | Region | Source | Status | Account Count |
   |---|---|---|---|
   | us-east-1 | CLOUD_TRAIL_MGMT | ACTIVE | 12 |
   | us-east-1 | VPC_FLOW | ACTIVE | 12 |
   | us-east-1 | ROUTE53 | ACTIVE | 8 |

5. MUST list all regions where Security Lake is enabled.

6. SHOULD note any source with non-ACTIVE status.

7. MAY include custom sources if present.

8. (ONLY if user asks about volume or ingestion size) Query CloudWatch:

   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/SecurityLake --metric-name ProcessedSize --dimensions Name=Source,Value=<SOURCE_NAME> --start-time <7-days-ago> --end-time <now> --period 86400 --statistics Sum
   ```

   Repeat for each source. Shows total stored bytes per source per day — useful for identifying sources that stopped ingesting.

## Workflow B: Subscriber & Exception Overview

1. List subscribers:

   ```bash
   aws securitylake list-subscribers
   ```

2. For each subscriber:

   ```bash
   aws securitylake get-subscriber --subscriber-id <id>
   ```

3. List exceptions:

   ```bash
   aws securitylake list-data-lake-exceptions
   ```

4. Present subscriber summary:

   | Subscriber | Access Type | Status | Sources Subscribed |
   |---|---|---|---|
   | SIEM-Integration | S3 | ACTIVE | ALL |
   | Analytics-Team | LAKEFORMATION | ACTIVE | VPC_FLOW, CLOUD_TRAIL_MGMT |

5. Present exception summary:

   | Account | Region | Source | Exception |
   |---|---|---|---|
   | 111122223333 | eu-west-1 | VPC_FLOW | INTERNAL_ERROR |

6. MUST report total subscriber count and access type breakdown.

7. MUST report exception count — zero exceptions is healthy.

8. SHOULD note subscribers in non-ACTIVE status.

## Constraints

- MUST NOT perform data queries against Security Lake
- MUST NOT modify configuration, subscribers, or sources
- MUST NOT query CloudWatch metrics by default — only if user explicitly asks about volume
- MUST present data as-is in structured tables
- SHOULD handle AccessDeniedException gracefully

## Troubleshooting

| Symptom | Resolution |
|---|---|
| get-data-lake-sources returns empty | Security Lake not enabled or no sources configured |
| AccessDeniedException | Caller is not Security Lake delegated admin or not enabled |
| UnauthorizedException | Same as above |
| Subscriber DEACTIVATED | Note in summary — may have been disabled |
| High exception count | Summarize by account/region — may indicate rollout issues |

## Output Sensitivity

Source summary reveals data lake regions, per-source ingestion status across accounts, subscriber identities and access configurations, and exception details (account IDs, failure reasons). Present source status table and subscriber overview first. Display full configuration details only when the caller explicitly requests raw output.
