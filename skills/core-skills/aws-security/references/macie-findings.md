# Summarizing Macie Findings

## Overview

Produces structured summaries of Amazon Macie findings across severity, type, bucket, and sensitive data categories. Provides statistics and overview tables without performing investigation or remediation.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| "How many findings do I have?" | A: Account Findings Summary |
| "What types of sensitive data were found?" | A then B |
| "Show findings by bucket/severity" | A: Account Findings Summary |
| "Summarize data classification results" | A then B |

## Workflow A: Account Findings Summary

Use only steps needed for the request, within its authorized account, region, filters and time window. Aggregate questions use statistics; they do not authorize retrieving individual finding bodies. A request for specific finding IDs authorizes only those details, even when discovery returns additional IDs.

1. For a requested severity breakdown, get statistics by severity:

   ```bash
   aws macie2 get-finding-statistics --group-by severity.description
   ```

2. For a requested type breakdown, get statistics by type:

   ```bash
   aws macie2 get-finding-statistics --group-by type
   ```

3. For a requested bucket breakdown, get statistics by bucket:

   ```bash
   aws macie2 get-finding-statistics --group-by "resourcesAffected.s3Bucket.name"
   ```

4. List findings only when needed to identify the requested details. Preserve requested filters and limits; returned IDs do not expand the authorized detail scope:

   ```bash
   aws macie2 list-findings --sort-criteria '{"attributeName":"severity.score","orderBy":"DESC"}' --max-items 50
   ```

5. Get only requested finding details, in batches of at most 50 authorized IDs. For a named finding, request that ID alone; do not fetch other discovered findings:

   ```bash
   aws macie2 get-findings --finding-ids <id1> <id2> ...
   ```

6. Check usage only if the user asks about usage:

   ```bash
   aws macie2 get-usage-totals
   ```

7. Present summary:

   | Severity | Count |
   |---|---|
   | High | X |
   | Medium | Y |
   | Low | Z |

   | Finding Type | Count |
   |---|---|
   | SensitiveData:S3Object/... | X |

   | Top Affected Buckets | Finding Count |
   |---|---|
   | bucket-name | X |

## Workflow B: Sensitive Data Overview

If a successful, complete Workflow A check returns zero findings for the validated scope, filters and time window, skip and report that scoped observation. Zero findings does not establish absence of sensitive data or clean posture. For denied, partial or unexplained empty results, preserve observed data and report the remaining state as UNKNOWN.

1. To investigate a specific resource from Workflow A results, use the `resourcesAffected.s3Bucket.arn` or `resourcesAffected.s3Object.key` from the finding detail.

2. List resource profile detections:

   ```bash
   aws macie2 list-resource-profile-detections --resource-arn <arn>
   ```

3. Check sensitive data availability:

   ```bash
   aws macie2 get-sensitive-data-occurrences-availability --finding-id <finding-id>
   ```

4. Summarize categories:

   - Financial (credit cards, bank accounts)
   - PII (names, addresses, SSNs)
   - Credentials (API keys, passwords)
   - Custom identifiers

5. Present overview:

   | Category | Buckets Affected | Detection Count |
   |---|---|---|
   | Financial | X | Y |
   | PII | X | Y |
   | Credentials | X | Y |

## Constraints

- MUST NOT perform investigation or root cause analysis
- MUST NOT perform remediation or suggest bucket policy changes
- MUST NOT retrieve actual sensitive data samples (only metadata/statistics)
- MUST present results as structured tables
- MUST use scoped statistics for aggregate requests rather than iterating finding bodies
- MUST restrict detail retrieval to requested IDs and batch at most 50 per request

## Troubleshooting

| Symptom | Resolution |
|---|---|
| AccessDeniedException | Message states Macie is not enabled: Macie is not enabled in this account and region. Any other message: report the denied read, its cause and enablement remain UNKNOWN |
| ValidationException on list-findings | Use attributeName "severity.score" with orderBy "DESC" |
| Empty get-finding-statistics | Report zero observed findings only for a successful, complete check with validated scope, filters and time window; otherwise report UNKNOWN. Do not infer clean posture or absence of sensitive data |

## Output Sensitivity

Finding details contain S3 bucket names, object keys where sensitive data was detected, sensitive data category counts (PII types, financial data, credentials), and bucket access permissions. Present the severity/type summary and affected bucket counts first. Display full finding details only when the caller explicitly requests raw output. Never include actual sensitive data samples.
