# Reviewing GuardDuty Configuration

## Overview

Assesses GuardDuty configuration completeness by checking detector status, features, publishing destinations, and organization coverage. Results are presented as a configuration state summary.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| Check GuardDuty config in this account | A: Review Single Account |
| Audit GuardDuty features enabled | A: Review Single Account |
| Review organization coverage | B: Review Organization Coverage |
| Check member accounts have GuardDuty | B: Review Organization Coverage |
| Verify GuardDuty publishing destination | A: Review Single Account |

## Workflow A: Review Single Account

1. Get the detector ID:

   ```bash
   aws guardduty list-detectors
   ```

2. Get detector configuration:

   ```bash
   aws guardduty get-detector --detector-id <DETECTOR_ID>
   ```

3. Report ALL features from the `get-detector` response. The response includes a `features` array — enumerate each feature and its `status` (ENABLED/DISABLED). Do not hardcode a feature list; report whatever the API returns.

   For reference on available features, see: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty-features-activation-model.html

   Note: EKS_RUNTIME_MONITORING is a legacy feature name superseded by RUNTIME_MONITORING. If both appear, only report RUNTIME_MONITORING.

   For RUNTIME_MONITORING, the response includes `additionalConfiguration` items for agent management per resource type. Report all `additionalConfiguration` items present in the response.

   For Malware Protection for S3 (on-demand scanning):

   ```bash
   aws guardduty list-malware-protection-plans
   ```

4. Check publishing destination:

   ```bash
   aws guardduty list-publishing-destinations --detector-id <DETECTOR_ID>
   ```

   If destination exists:

   ```bash
   aws guardduty describe-publishing-destination --detector-id <DETECTOR_ID> --destination-id <DEST_ID>
   ```

   **Security check:** Verify publishing destination has SSE-KMS encryption configured — check for `KmsKeyArn` in the destination properties.

5. Check IP sets and threat intel sets:

   ```bash
   aws guardduty list-ip-sets --detector-id <DETECTOR_ID>
   aws guardduty list-threat-intel-sets --detector-id <DETECTOR_ID>
   ```

6. Check suppression filters:

   ```bash
   aws guardduty list-filters --detector-id <DETECTOR_ID>
   ```

7. Present results:

   **Security check:** Verify CloudTrail is enabled and logging GuardDuty API calls (`guardduty:*` events) for audit purposes.

   | Check | Status |
   |---|---|
   | Detector enabled | Enabled / Not Enabled |
   | Each feature from API response | Enabled / Disabled |
   | Runtime Monitoring agent management (per resource type) | Enabled / Disabled |
   | Malware Protection for S3 plans | Configured / Not Configured |
   | Publishing destination | Configured / Not Configured |
   | Trusted IP list | Configured / Not Configured |

## Workflow B: Review Organization Coverage

1. Identify the admin account:

   ```bash
   aws guardduty list-organization-admin-accounts
   ```

2. Get the detector ID:

   ```bash
   aws guardduty list-detectors
   ```

3. Check organization auto-enable settings:

   ```bash
   aws guardduty describe-organization-configuration --detector-id <DETECTOR_ID>
   ```

   Report ALL features and their auto-enable status. For features with `additionalConfiguration`, also report auto-enable for sub-features.

4. Get coverage statistics (summary without per-account enumeration):

   ```bash
   aws guardduty get-coverage-statistics --detector-id <DETECTOR_ID> --statistics-type COUNT_BY_COVERAGE_STATUS
   ```

5. (ONLY if user explicitly requests per-account detail) Enumerate members:

   ```bash
   aws guardduty list-members --detector-id <DETECTOR_ID>
   aws guardduty get-member-detectors --detector-id <DETECTOR_ID> --account-ids <ACCOUNT_IDS>
   ```

   MAY batch up to 50 account IDs per call.

6. Present results:

   | Check | Status |
   |---|---|
   | Delegated admin designated | Yes / No |
   | Auto-enable new members | Enabled / Not Enabled |
   | Auto-enable per feature (each from org config response) | Enabled / Not Enabled |
   | Member accounts | Enrolled (details on request) |
   | Coverage statistics | Healthy / Unhealthy / Count |

## Constraints

- MUST use the detector ID from list-detectors (do not hardcode)
- MUST check ALL features, not a subset
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member account status if user explicitly requests it

## Troubleshooting

| Symptom | Resolution |
|---|---|
| list-detectors returns empty | GuardDuty not enabled — report as not configured |
| Access denied on describe-organization-configuration | Not a delegated admin — run Workflow A instead |
| get-member-detectors fails | Account not a member — verify with list-members |
| list-organization-admin-accounts returns BadRequestException | Requires org management account — use describe-organization-configuration from DA |

## Output Sensitivity

Configuration output reveals account structure (member account IDs), enabled security features, publishing destinations (S3 bucket names, KMS key ARNs), and organization enrollment status. Present configuration summary first; offer raw API responses on request.
