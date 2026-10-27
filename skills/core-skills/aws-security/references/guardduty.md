# GuardDuty

- **Docs**: https://docs.aws.amazon.com/guardduty/latest/ug/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/guardduty/latest/ug/llms.txt

Amazon GuardDuty is a threat detection service that continuously monitors AWS accounts and workloads for malicious activity. On enablement it analyzes three foundational sources with nothing further to turn on: CloudTrail management events, VPC Flow Logs and Route 53 Resolver DNS query logs. Every other source reaches GuardDuty only through a protection plan, enabled separately and toggled individually: S3 data events, EKS audit logs, Lambda network activity, RDS login events and runtime activity (EC2, EKS, ECS containers). Confirm the current data sources and protection plans in the GuardDuty documentation. Lambda Protection and RDS Protection may auto-enable during a free trial on first enablement in a Region and can be disabled afterwards, so a plan being on now is not evidence it was always on; confirm current trial terms and duration from AWS documentation rather than assuming a fixed window. Together these identify threats ranging from reconnaissance to active compromise. Findings are in GuardDuty's proprietary JSON format and are also sent to Security Hub in OCSF format.

## Data Sources

```mermaid
graph LR
    CT[CloudTrail Mgmt Events] --> GD[GuardDuty]
    DNS[Route 53 Resolver<br/>DNS Query Logs] --> GD
    VPC[VPC Flow Logs] --> GD
    LAMBDA[Lambda Network Activity] --> PP
    S3[S3 Data Events] --> PP
    EKS[EKS Audit Logs] --> PP
    RDS[RDS Login Events] --> PP
    RT[Runtime Monitoring<br/>EC2, EKS, ECS] --> PP
    PP[Protection plan<br/>must be enabled] --> GD
    GD -->|generates| FIND[Threat Findings<br/>incl. Attack Sequences]
```

## Read-Only APIs

| API | Purpose |
|-----|---------|
| `guardduty:ListDetectors` | Discover detector IDs in the account |
| `guardduty:GetDetector` | Get detector configuration and feature status |
| `guardduty:ListMalwareProtectionPlans` | Check Malware Protection for S3 plans |
| `guardduty:ListPublishingDestinations` | List configured publishing destinations |
| `guardduty:DescribePublishingDestination` | Get publishing destination details |
| `guardduty:ListIPSets` | List trusted IP sets |
| `guardduty:ListThreatIntelSets` | List threat intelligence sets |
| `guardduty:ListFilters` | List suppression filters |
| `guardduty:ListOrganizationAdminAccounts` | Identify delegated admin accounts |
| `guardduty:DescribeOrganizationConfiguration` | Get org auto-enable settings |
| `guardduty:GetCoverageStatistics` | Get coverage summary by status |
| `guardduty:ListMembers` | List member accounts |
| `guardduty:GetMemberDetectors` | Get member detector feature status |
| `guardduty:GetFindingsStatistics` | Get finding counts by severity |
| `guardduty:ListFindings` | List finding IDs with filters |
| `guardduty:GetFindings` | Get finding details (batch, max 50) |

## Severity Scoring

GuardDuty uses a numeric 0–10 scale mapped to severity levels:

| Level | Score Range | Description |
|-------|------------|-------------|
| Low | 1.0 – 3.9 | Suspicious activity that did not compromise resources |
| Medium | 4.0 – 6.9 | Suspicious activity deviating from normal behavior |
| High | 7.0 – 8.9 | Resource compromised and actively used for unauthorized purposes |
| Critical | 9.0 – 10.0 | Attack Sequences — correlated multi-step attacks across multiple signals |

**Key notes:**

- Attack Sequence findings (type prefix `AttackSequence:`) are always Critical severity
- Severity is assigned by GuardDuty based on threat intelligence and behavior analysis
- Severity may differ for the same finding type depending on context (e.g., known malicious IP vs unknown)

**Documentation:** https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_findings-severity.html

## Service Notes

- **EKS_RUNTIME_MONITORING**: Legacy feature flag — only relevant for customers who enabled it before unified RUNTIME_MONITORING. Treat as edge case.
- **Runtime Monitoring support changes over time.** Before assessing or recommending it, read the current GuardDuty Runtime Monitoring documentation for supported compute services, launch types, node/platform prerequisites, agent-management options and Region eligibility. Compare that current support matrix with the observed workload inventory and `list-coverage` results. If documentation cannot be read or workload eligibility cannot be verified, report applicability as UNKNOWN rather than relying on a remembered compute list.
- **GuardDuty Malware Protection for S3**: Automatically scans newly uploaded objects in the selected buckets, and also supports on-demand scans of existing objects. It is separate from Malware Protection for EC2, which runs GuardDuty-initiated and on-demand scans of EBS volumes. Checked via `list-malware-protection-plans`. See [Malware Protection for S3](https://docs.aws.amazon.com/guardduty/latest/ug/gdu-malware-protection-s3.html).

## Output Sensitivity

GuardDuty finding details (`GetFindings`) contain:

- IP addresses (actor and target)
- Network connection details (ports, protocols, direction)
- AWS account IDs and resource ARNs
- Threat intelligence source details
- DNS query names
- S3 object keys and bucket names
- Process and container details (runtime findings)

Present severity/type summary first. Offer full finding body on request.
