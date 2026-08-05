# Reviewing Detective Configuration

## Overview

Audits Amazon Detective configuration across single accounts and organizations. Checks behavior graph existence, data source enablement, member account coverage, and invitation status. Results are presented as a configuration state summary.

Detective ingests CloudTrail management events, VPC Flow Logs, EKS Audit Logs, and Security Hub findings to build behavior graphs for investigation. Detective does NOT support S3 data events.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| Signal | Workflow |
|--------|----------|
| Single account, no org context | A: Review Single Account |
| Org admin, multi-account coverage | B: Review Organization Coverage |
| "Is Detective set up correctly?" | A then B if org |

## Workflow A: Review Single Account

1. List behavior graphs:

   ```bash
   aws detective list-graphs
   ```

   Configured: at least one graph. Not Configured: no graphs.

2. Check behavior graph encryption — verify `EncryptionType` from `list-graphs` response indicates customer-managed KMS key (CMK). If `EncryptionType` is `SERVICE_DEFAULT`, the graph uses AWS-owned keys rather than customer-managed encryption.

3. For each graph, check data source packages:

   ```bash
   aws detective list-datasource-packages --graph-arn <graph-arn>
   ```

   Expected packages:

   - DETECTIVE_CORE (CloudTrail management events)
   - EKS_AUDIT (EKS Audit Logs)
   - ASFF_SECURITYHUB_FINDING (Security Hub findings)

   For each: STARTED = Configured, STOPPED/DISABLED = Not Configured.

4. List members:

   ```bash
   aws detective list-members --graph-arn <graph-arn>
   ```

   Check each member status: ENABLED, VERIFICATION_FAILED, VERIFICATION_IN_PROGRESS.

5. Check pending invitations (from member perspective):

   ```bash
   aws detective list-invitations
   ```

   **Security check:** Verify CloudTrail is enabled and logging Detective API calls (`detective:*` events) for audit purposes.

6. Present results:

   | Check | Status |
   |---|---|
   | Behavior Graph Exists | Configured / Not Configured |
   | Behavior Graph Encryption | Customer-managed KMS / AWS-owned |
   | CloudTrail Logs | Enabled / Disabled / Not Configured |
   | EKS Audit Logs | Enabled / Disabled / Not Configured |
   | Security Hub Findings | Enabled / Disabled / Not Configured |
   | Member Count | X members |
   | Members Enabled | X/Y enabled |

## Workflow B: Review Organization Coverage

1. Identify admin:

   ```bash
   aws detective list-organization-admin-accounts
   ```

2. Check organization configuration:

   ```bash
   aws detective describe-organization-configuration --graph-arn <graph-arn>
   ```

   Configured: autoEnable is true.

3. For quick membership signal, `describe-organization-configuration` confirms auto-enable for new accounts. Full member enumeration requires `list-members` pagination — expensive for large organizations.

4. (ONLY if user explicitly requests per-account detail):

   ```bash
   aws detective list-members --graph-arn <graph-arn>
   ```

   Evaluate: ENABLED, VERIFICATION_FAILED, INVITED (not accepted), DISABLED.

5. Check data source packages on admin graph (step 3 from Workflow A).

6. Present results:

   | Check | Status |
   |---|---|
   | Delegated Admin Configured | Configured / Not Configured |
   | Auto-Enable New Accounts | Enabled / Not Enabled |
   | Member Accounts | Enrolled (details on request) |
   | Data Sources Enabled | X/Y packages |

## Constraints

- MUST NOT modify any Detective configuration
- MUST NOT perform entity investigation or finding analysis
- MUST NOT paginate through all member accounts by default
- MUST only enumerate individual member status if user explicitly requests it
- SHOULD check all available data source packages
- MAY report graph creation date for context

## Troubleshooting

| Error | Resolution |
|-------|------------|
| AccessDeniedException on list-graphs | Detective not enabled — report as NOT_CONFIGURED |
| ValidationException on list-members | Invalid graph ARN — re-fetch from list-graphs |
| Empty list-graphs response | Detective not enabled in region |
| AccessDeniedException on describe-organization-configuration | Not an org admin — switch to Workflow A |

## Output Sensitivity

Configuration output reveals behavior graph ARNs, member account IDs and invitation status, enabled data source packages, and organization auto-enable settings. Present configuration summary first; offer raw API responses on request.
