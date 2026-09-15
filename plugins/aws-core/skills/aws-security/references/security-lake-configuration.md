# Reviewing Security Lake Configuration

## Overview

Produces a configuration summary of Amazon Security Lake reporting current state. Verifies data lake enablement, AWS log source coverage, subscriber setup, and organization-level rollout.

Works from both standalone and delegated administrator accounts.

## Classify the Request

| Request Pattern | Workflow |
|---|---|
| "Is Security Lake configured correctly?" | A: Review Single Account |
| "Check org-wide Security Lake coverage" | B: Review Organization Coverage |

## Workflow A: Review Single Account

1. Check data lake status:

   ```bash
   aws securitylake list-data-lakes
   ```

   Verify each expected region has a data lake with `createStatus` = COMPLETED.

   **Security check:** Verify data lake has KMS encryption configured — check `encryptionConfiguration.kmsKeyId` in the `list-data-lakes` output.

2. Check configured AWS sources:

   ```bash
   aws securitylake get-data-lake-sources
   ```

   Verify these source types are present:

   - ROUTE53
   - VPC_FLOW
   - SH_FINDINGS
   - CLOUD_TRAIL_MGMT
   - LAMBDA_EXECUTION
   - S3_DATA
   - EKS_AUDIT

3. List log sources for detail:

   ```bash
   aws securitylake list-log-sources
   ```

4. Check subscribers:

   ```bash
   aws securitylake list-subscribers
   ```

   For each subscriber, note access type (S3, LAKEFORMATION) and status.

5. Present results:

   | Check | Status | Detail |
   |---|---|---|
   | Data lake enabled (region) | Configured | createStatus=COMPLETED |
   | CloudTrail Management | Configured / Not Configured | ... |
   | VPC Flow Logs | Configured / Not Configured | ... |
   | Route53 | Configured / Not Configured | ... |
   | S3 Data Events | Configured / Not Configured | ... |
   | Lambda Execution | Configured / Not Configured | ... |
   | EKS Audit | Configured / Not Configured | ... |
   | Subscribers | Configured | N subscribers active |

6. MUST check all standard AWS sources listed above.

7. SHOULD flag any source with a non-healthy status.

## Workflow B: Review Organization Coverage

1. Get organization configuration:

   ```bash
   aws securitylake get-data-lake-organization-configuration
   ```

   Check which sources have auto-enable configured.

2. List exceptions:

   ```bash
   aws securitylake list-data-lake-exceptions
   ```

   Identify accounts/regions with failures.

3. Present organization summary:

   | Check | Status | Detail |
   |---|---|---|
   | Org auto-enable (each source) | Configured / Not Configured | ... |
   | Exceptions | Count | ... |

4. For each exception:

   | Account | Region | Source | Exception Reason |
   |---|---|---|---|
   | 111122223333 | us-east-1 | VPC_FLOW | INTERNAL_ERROR |

5. MUST report all exceptions.

6. SHOULD compare auto-enable sources against full source list.

7. MUST NOT paginate through all member accounts by default.

8. MUST only enumerate individual member status if user explicitly requests it.

## Constraints

- MUST NOT modify Security Lake configuration
- MUST NOT query data stored in Security Lake
- SHOULD handle AccessDeniedException — indicate caller may not be delegated admin

## Troubleshooting

| Issue | Resolution |
|---|---|
| list-data-lakes returns empty | Security Lake not enabled in this account/region |
| AccessDeniedException | Caller is not the Security Lake delegated admin or not enabled. Note: may have empty error body |
| UnauthorizedException | Same as above |
| get-data-lake-organization-configuration fails | Organization features may not be enabled |
| Sources show FAILED status | Note in report — may indicate IAM or SLR issues |

## Output Sensitivity

Configuration output reveals data lake S3 bucket details, KMS key ARNs, subscriber identities and access types, log source coverage across accounts and regions, and organization exception details. Present source enablement and subscriber summary first; offer raw API responses on request.
