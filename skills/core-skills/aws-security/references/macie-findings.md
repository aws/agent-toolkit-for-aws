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

1. Get statistics by severity:

   ```bash
   aws macie2 get-finding-statistics --group-by severity.description
   ```

2. Get statistics by type:

   ```bash
   aws macie2 get-finding-statistics --group-by type
   ```

3. Get statistics by bucket:

   ```bash
   aws macie2 get-finding-statistics --group-by "resourcesAffected.s3Bucket.name"
   ```

4. List findings sorted by severity:

   ```bash
   aws macie2 list-findings --sort-criteria '{"attributeName":"severity.score","orderBy":"DESC"}' --max-results 50
   ```

5. Get finding details (batch, max 50):

   ```bash
   aws macie2 get-findings --finding-ids <id1> <id2> ...
   ```

6. Check usage:

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

If Workflow A returns zero findings, skip and report no sensitive data detections.

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
- SHOULD use get-finding-statistics for aggregations (not iterating all findings)
- SHOULD batch get-findings calls (max 50 per request)

## Troubleshooting

| Symptom | Resolution |
|---|---|
| AccessDeniedException | Macie not enabled or insufficient permissions |
| ValidationException on list-findings | Use attributeName "severity.score" with orderBy "DESC" |
| Empty get-finding-statistics | No findings — report zero findings as clean posture |

## Output Sensitivity

Finding details contain S3 bucket names, object keys where sensitive data was detected, sensitive data category counts (PII types, financial data, credentials), and bucket access permissions. Present the severity/type summary and affected bucket counts first. Display full finding details only when the caller explicitly requests raw output. Never include actual sensitive data samples.
