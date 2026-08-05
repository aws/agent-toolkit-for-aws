# Summarizing GuardDuty Findings

## Overview

Produces structured summaries of active GuardDuty findings — severity distribution, type breakdown, and affected resources. Does NOT perform triage, investigation, or remediation.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| Summarize my GuardDuty findings | A: Account Findings Summary |
| What threats is GuardDuty detecting | A: Account Findings Summary |
| Show findings across my org | B: Organization Findings Overview |
| Which accounts have the most findings | B: Organization Findings Overview |

## Workflow A: Account Findings Summary

1. Get the detector ID:

   ```bash
   aws guardduty list-detectors
   ```

2. Get finding statistics (active findings only):

   ```bash
   aws guardduty get-findings-statistics --detector-id <DETECTOR_ID> --finding-statistic-types COUNT_BY_SEVERITY --finding-criteria '{"Criterion":{"service.archived":{"Eq":["false"]}}}'
   ```

   **Severity mapping:** 9.0+ = Critical, 7.0–8.9 = High, 4.0–6.9 = Medium, 1.0–3.9 = Low

3. List findings sorted by severity (most severe first):

   ```bash
   aws guardduty list-findings --detector-id <DETECTOR_ID> --sort-criteria '{"AttributeName":"severity","OrderBy":"DESC"}' --finding-criteria '{"Criterion":{"service.archived":{"Eq":["false"]}}}'
   ```

4. Get finding details in batches (max 50 per call):

   ```bash
   aws guardduty get-findings --detector-id <DETECTOR_ID> --finding-ids <IDS>
   ```

5. Group findings by:

   - **Attack Sequences first** — findings with type prefix `AttackSequence:` MUST be surfaced in a separate section at the top. These represent correlated multi-step attacks and are the most actionable findings.
   - Severity (CRITICAL, HIGH, MEDIUM, LOW)
   - Type prefix (e.g., Recon:, UnauthorizedAccess:, CryptoCurrency:)
   - Resource type (Instance, AccessKey, S3Bucket, EKSCluster, Lambda, RDSDBInstance)

6. Present summary:

   **Attack Sequences** (always first):

   | Finding Type | Severity | Affected Resources |
   |---|---|---|
   | AttackSequence:... | CRITICAL | ... |

   **Severity Breakdown:**

   | Severity | Count |
   |---|---|
   | Critical | N |
   | High | N |
   | Medium | N |
   | Low | N |

   | Finding Type Prefix | Count | Highest Severity |
   |---|---|---|
   | UnauthorizedAccess: | N | HIGH |
   | Recon: | N | MEDIUM |

   | Resource Type | Count | Top Finding Types |
   |---|---|---|
   | Instance | N | ... |
   | AccessKey | N | ... |

## Workflow B: Organization Findings Overview

1. Get the detector ID:

   ```bash
   aws guardduty list-detectors
   ```

2. List findings across organization (delegated admin sees all member findings):

   ```bash
   aws guardduty list-findings --detector-id <DETECTOR_ID> --sort-criteria '{"AttributeName":"severity","OrderBy":"DESC"}' --finding-criteria '{"Criterion":{"service.archived":{"Eq":["false"]}}}'
   ```

3. Get finding details in batches:

   ```bash
   aws guardduty get-findings --detector-id <DETECTOR_ID> --finding-ids <IDS>
   ```

4. Group by account ID, then by severity and type.

5. Present summary:

   | Account ID | Critical | High | Medium | Low | Total |
   |---|---|---|---|---|---|
   | 111111111111 | N | N | N | N | N |

   MUST identify the top 5 accounts by critical+high findings count.

## Constraints

- MUST filter to non-archived (active) findings only
- MUST batch get-findings calls (max 50 IDs per request)
- MUST NOT perform triage, investigation, or root cause analysis
- MUST NOT make recommendations about suppression or remediation
- SHOULD limit detail retrieval to top 200 findings for performance

## Troubleshooting

| Symptom | Resolution |
|---|---|
| list-findings returns empty | No active findings or all archived — report zero active findings |
| get-findings-statistics unavailable | Use list-findings and count client-side |
| Only sees own account findings | Not a delegated admin — note: showing single-account view only |

## Output Sensitivity

Finding details contain IP addresses, network connections, DNS queries, process details, and resource identifiers. Present the severity/type summary table first. Display full finding JSON bodies only when the caller explicitly requests raw output.
