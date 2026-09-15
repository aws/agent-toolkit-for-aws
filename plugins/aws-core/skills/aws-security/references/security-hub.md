# Security Hub

- **Docs**: https://docs.aws.amazon.com/securityhub/latest/userguide/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/securityhub/latest/userguide/llms.txt

AWS Security Hub (V2) is the unified security dashboard that ingests findings from GuardDuty, Inspector, Macie, and third-party tools in OCSF format. It correlates findings into exposure analysis and attack paths, providing a single pane of glass for security posture across accounts and regions. This is the preferred hub for bringing AWS security services together.

## Data Sources

Security Hub V2 ingests findings from:

- GuardDuty (threat detection)
- Inspector (vulnerability management)
- Macie (sensitive data discovery)
- Security Hub CSPM (compliance findings)
- AWS Config (resource configuration)
- Third-party products (via integration connectors)

All findings are normalized to OCSF format.

## API Convention

Security Hub V2 APIs share the `aws securityhub` CLI namespace with CSPM but are distinguished by the `-v2` suffix. All Security Hub APIs in this file use the `-v2` suffix. CSPM APIs (without suffix) are in `references/security-hub-cspm.md`. Organization management APIs listed below use the `aws organizations` namespace.

## Operator prerequisites

**Prerequisite:** Operator must assume an IAM role with least-privilege read-only permissions. Scope permissions to the V2 and Organizations actions listed in the Common Read-Only APIs table; avoid FullAccess managed policies and `securityhub:*` or `organizations:*` wildcards. Do not use long-lived IAM user access keys.

## Common Read-Only APIs

| API | Purpose |
|-----|---------|
| `securityhub:DescribeSecurityHubV2` | Check hub status and configuration |
| `securityhub:DescribeProductsV2` | List third-party product integrations |
| `securityhub:ListAggregatorsV2` | Check cross-region aggregation |
| `securityhub:GetAggregatorV2` | Get aggregator details |
| `securityhub:ListConnectorsV2` | List ITSM and external connectors |
| `securityhub:ListAutomationRulesV2` | List V2 automation rules |
| `securityhub:GetFindingStatisticsV2` | Get aggregated finding statistics |
| `securityhub:GetFindingsV2` | Get OCSF findings |
| `securityhub:GetFindingsTrendsV2` | Get finding trends over time |
| `securityhub:GetResourcesV2` | Get resource-centric view |
| `securityhub:GetResourcesStatisticsV2` | Get resource statistics |
| `securityhub:GetResourcesTrendsV2` | Get resource trends over time |
| `organizations:ListPolicies` | List organization-level policies (org management) |
| `organizations:DescribePolicy` | Get organization policy details (org management) |
| `organizations:ListTargetsForPolicy` | List targets for a policy (org management) |

## Severity Scoring

Security Hub V2 uses the OCSF severity model (integer enum):

| Severity ID | Label | Description |
|-------------|-------|-------------|
| 0 | Unknown | Severity not determined |
| 1 | Informational | No immediate threat; for awareness |
| 2 | Low | Minor issue; limited impact if exploited |
| 3 | Medium | Moderate impact; should be addressed |
| 4 | High | Significant impact; prompt action required |
| 5 | Critical | Severe impact; immediate action required |
| 6 | Fatal | Defined in OCSF schema; Security Hub does not populate this value |
| 99 | Other | Unmapped severity from source |

Findings from integrated services (GuardDuty, Inspector, Macie) are normalized to this scale upon ingestion into the V2 hub.

**Key notes:**

- Exposure findings (attack paths) carry their own severity based on resource exposure and blast radius
- The `severity_id` field in OCSF findings uses this integer enum

Ref: [OCSF Schema — Objects](https://schema.ocsf.io/objects)

## Security Check

See SKILL.md Security considerations for CloudTrail audit logging, CloudWatch anomaly alarms, KMS/TLS encryption, SNS recipient validation, and current AWS security best-practice references.

## Service Notes

- **Security Hub V2 internal findings**: Flow automatically when source services (GuardDuty, Inspector, Macie) are enabled. `describe-products-v2` is only relevant for third-party integration status, NOT for verifying internal service findings flow.

## Output Sensitivity

Security Hub OCSF findings (`GetFindingsV2`) contain:

- Aggregated finding data from multiple source services (GuardDuty, Inspector, Macie)
- AWS account IDs, resource ARNs, and region details
- IP addresses, network paths, and exposure details (attack path findings)
- Resource configuration state and compliance status
- Threat intelligence correlation data

Present finding statistics and severity distribution first. Offer full OCSF finding bodies on request. Avoid logging raw OCSF finding or resource responses in plaintext, store exported findings data only in downstream destinations encrypted at rest, and transmit exported data only over encrypted channels such as TLS. If logging to CloudWatch Logs, verify the log group is encrypted with a KMS key. If findings or automation outputs are forwarded to SNS topics or S3 buckets, verify those destinations use KMS encryption and resource policies include `aws:SourceArn` and `aws:SourceAccount` condition keys.
