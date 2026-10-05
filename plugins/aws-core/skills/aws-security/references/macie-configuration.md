# Reviewing Macie Configuration

## Overview

Audits Amazon Macie configuration across single accounts and organizations. Checks enablement status, automated discovery, classification jobs, publication settings, allow lists, and member coverage. Results are presented as a configuration state summary.

Works from both standalone accounts and delegated administrator accounts.

**A complete Macie configuration review MUST cover all of these; do not stop early, mark UNKNOWN rather than omit:**

1. Enablement status — `get-macie-session`
2. Automated sensitive-data discovery — `get-automated-discovery-configuration`
3. Classification jobs — `list-classification-jobs`
4. Publication / export settings — `get-findings-publication-configuration`, `get-classification-export-configuration`
5. Allow lists — `list-allow-lists`
6. Organization / member coverage — `describe-organization-configuration`, `list-members`

## Classify the Request

| User intent | Workflow |
|---|---|
| Single account, no org context | A: Review Single Account |
| Org admin, multi-account coverage | B: Review Organization Coverage |
| "Is Macie set up correctly?" | A then B if org |

## Workflow A: Review Single Account

1. Check Macie enablement:

   ```bash
   aws macie2 get-macie-session
   ```

   Configured: status is ENABLED. Not Configured: an `AccessDeniedException` whose message states
   that Macie is not enabled, or that the account has not been onboarded. Match on the substring,
   because the wording varies by operation: `get-macie-session` and `get-administrator-account`
   return `Macie is not enabled`, `list-findings` returns it with a trailing period, and
   `get-automated-discovery-configuration` returns `Account Id: [<id>] has not been onboarded`.
   An `AccessDeniedException` carrying none of those is UNKNOWN, not Not Configured: no AWS source
   fixes what a permissions denial says, so only presence of a not-enabled message resolves
   anything and absence resolves nothing.

2. Check automated discovery:

   ```bash
   aws macie2 get-automated-discovery-configuration
   ```

3. Review classification jobs:

   ```bash
   aws macie2 list-classification-jobs --sort-criteria '{"attributeName":"createdAt","orderBy":"DESC"}'
   ```

   For each job:

   ```bash
   aws macie2 describe-classification-job --job-id <job-id>
   ```

4. Check findings publication:

   ```bash
   aws macie2 get-findings-publication-configuration
   ```

   Report BOTH settings:

   - `publishClassificationFindings`: sensitive data → Security Hub
   - `publishPolicyFindings`: policy findings → Security Hub

5. Check classification export configuration:

   ```bash
   aws macie2 get-classification-export-configuration
   ```

   **Security check:** Verify the export destination S3 bucket uses SSE-KMS encryption (`kmsKeyArn` is present in the `s3Destination` response) and TLS in transit for delivery and consumer access. Flag missing KMS or transport protection. Verify retention and successful delivery separately; destination configuration alone proves neither.

6. Review allow lists:

   ```bash
   aws macie2 list-allow-lists
   ```

7. Check reveal configuration:

   ```bash
   aws macie2 get-reveal-configuration
   ```

8. Check usage:

   ```bash
   aws macie2 get-usage-totals
   ```

9. Present results:

   **Security check:** Verify CloudTrail is enabled and logging Macie API calls (`macie2:*` events) for audit purposes.

   | Check | Status |
   |---|---|
   | Macie Enabled | Enabled / Not Enabled |
   | Automated Discovery | Configured / Not Configured |
   | Classification Jobs | Observed job states and counts; result production not established |
   | Findings Publication (classification) | Enabled / Not Enabled |
   | Findings Publication (policy) | Enabled / Not Enabled |
   | Export Destination Encryption | SSE-KMS / Not Configured |
   | Allow Lists | Count |
   | Reveal Configuration | ENABLED / DISABLED |

## Workflow B: Review Organization Coverage

1. Identify admin:

   ```bash
   aws macie2 list-organization-admin-accounts
   ```

2. Check organization configuration:

   ```bash
   aws macie2 describe-organization-configuration
   ```

   Report ALL auto-enable settings from the response.

3. Quick member check:

   ```bash
   aws macie2 list-members --max-items 1
   ```

4. (ONLY if user explicitly requests per-account detail):

   ```bash
   aws macie2 list-members --only-associated false
   ```

   Check `relationshipStatus` for each: Enabled, Paused, Removed, EmailVerificationFailed.

5. Run Workflow A checks from admin account context.

6. Present results:

   | Check | Status |
   |---|---|
   | Delegated Admin Configured | Enabled / Not Enabled |
   | Auto-Enable New Accounts | Enabled / Not Enabled |
   | Auto-Enable Automated Discovery | Enabled / Not Enabled |
   | Member relationships | Observed enrollment/status counts, or UNKNOWN; discovery coverage separate |
   | Automated Discovery (admin) | Configured / Not Configured |
   | Findings Publication (classification) | Enabled / Not Enabled |
   | Findings Publication (policy) | Enabled / Not Enabled |

Running jobs do not establish result production; publication settings do not establish delivery; membership does not establish effective discovery coverage. Preserve these as separate observations, with absent outcome evidence NOT ASSESSED or UNKNOWN as appropriate.

## Constraints

- MUST NOT modify any Macie configuration
- MUST NOT perform finding investigation or remediation
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member status if user explicitly requests it

## Troubleshooting

| Symptom | Resolution |
|---|---|
| AccessDeniedException on any macie2 call | Message states Macie is not enabled, or the account has not been onboarded: report NOT_CONFIGURED. Any other message: report the denied read, enablement stays UNKNOWN |
| AccessDeniedException on list-members | Not a Macie admin — switch to Workflow A |
| ValidationException on describe-organization-configuration | Not an org admin |

## Output Sensitivity

Configuration output reveals S3 bucket targets for classification jobs, publication destinations, allow list patterns, organization member account IDs, and reveal configuration status. Present configuration summary first; offer raw API responses on request.
