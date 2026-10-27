# Reviewing Detective Configuration

## Overview

Audits Amazon Detective configuration across single accounts and organizations. Checks behavior graph existence, data source enablement, member account coverage, and invitation status. Results are presented as a configuration state summary.

Detective ingests CloudTrail management events, VPC Flow Logs, EKS Audit Logs, and Security Hub findings to build behavior graphs for investigation. Detective does NOT support S3 data events.

Works from both standalone accounts and delegated administrator accounts.

GuardDuty is not a Detective prerequisite: the documented prerequisites are IAM permissions
for Detective and, for CLI use, a recent AWS CLI version (confirm the current minimum from the Detective prerequisites documentation). What the
two services do share is administrator-account alignment. Align the administrator account across
GuardDuty, Security Hub CSPM and Detective so the finding pivot and the archive-from-Detective
integration work, and report misalignment as a finding of this review. Never recommend enabling
GuardDuty solely to satisfy a prerequisite gate.

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

2. For each graph, check data source packages:

   ```bash
   aws detective list-datasource-packages --graph-arn <graph-arn>
   ```

   Expected packages:

   - DETECTIVE_CORE (CloudTrail management events)
   - EKS_AUDIT (EKS Audit Logs)
   - ASFF_SECURITYHUB_FINDING (Security Hub findings)

   For each: STARTED = Configured, STOPPED/DISABLED = Not Configured.

3. List members:

   ```bash
   aws detective list-members --graph-arn <graph-arn>
   ```

   Report observed member status, such as ENABLED, VERIFICATION_FAILED or VERIFICATION_IN_PROGRESS. The current [ListMembers contract](https://docs.aws.amazon.com/boto3/latest/reference/services/detective/client/list_members.html) defines ENABLED as contributing data to the graph at query time. Report this as service-reported contribution; it does not establish completeness, freshness or coverage of every required source.

4. Check pending invitations (from member perspective):

   ```bash
   aws detective list-invitations
   ```

   **Security check:** Verify CloudTrail is enabled and logging Detective API calls (`detective:*` events) for audit purposes.

5. Present results:

   | Check | Status |
   |---|---|
   | Behavior Graph Exists | Configured / Not Configured |
   | CloudTrail Logs | Enabled / Disabled / Not Configured |
   | EKS Audit Logs | Enabled / Disabled / Not Configured |
   | Security Hub Findings | Enabled / Disabled / Not Configured |
   | Member Count | X members |
   | Member status | X/Y observed member records have ENABLED status; ingestion separate |

## Workflow B: Review Organization Coverage

1. Identify admin:

   ```bash
   aws detective list-organization-admin-accounts
   ```

2. Get the administrator's graph ARN for each Region in scope, then check organization configuration:

   ```bash
   aws detective list-graphs --region <region>
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
   | Member Accounts | Observed membership/status, or UNKNOWN; details only on request |
   | Data Sources | Observed states across all returned packages; name the denominator and any documented subset |

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
| AccessDeniedException on list-graphs | Caller may lack `detective:ListGraphs` or may not be a Detective administrator. Enablement is UNKNOWN. Report the denied read, not NOT_CONFIGURED |
| ValidationException on list-members | Invalid graph ARN — re-fetch from list-graphs |
| Empty list-graphs response | The caller administers no behavior graph in this region. A member account of an active graph also returns empty. From this response alone, enablement is UNKNOWN, not NOT_CONFIGURED; it is NOT_CONFIGURED only when the caller is also verified as the Detective delegated administrator |
| AccessDeniedException on describe-organization-configuration | The caller may not be the Detective administrator or may lack permission, so organization configuration is UNKNOWN from this account. Report that, then use Workflow A for this account |

## Output Sensitivity

Configuration output reveals behavior graph ARNs, member account IDs and invitation status, enabled data source packages, and organization auto-enable settings. Present configuration summary first; offer raw API responses on request.
