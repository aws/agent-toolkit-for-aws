# Inspector

- **Docs**: https://docs.aws.amazon.com/inspector/latest/user/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/inspector/latest/user/llms.txt

Amazon Inspector is a vulnerability management service that automatically scans EC2 instances, ECR container images, and Lambda functions for software vulnerabilities, code weaknesses, and network exposure. It uses CVSS scoring and incorporates exploitability context. Findings are in Inspector's proprietary JSON format and are also sent to Security Hub in OCSF format.

## Data Sources

Inspector automatically discovers and scans:

- EC2 instances (via SSM agent) — OS package vulnerabilities, network reachability
- ECR container images — image layer vulnerabilities, mapped to running containers
- Lambda functions — code vulnerabilities, package vulnerabilities

## Read-Only APIs

| API | Purpose |
|-----|---------|
| `inspector2:BatchGetAccountStatus` | Get scan type enablement per account |
| `inspector2:ListCoverageStatistics` | Get coverage summary by resource type |
| `inspector2:ListCoverage` | List resource coverage details |
| `inspector2:ListFilters` | List suppression rules |
| `inspector2:ListCisScanConfigurations` | List CIS benchmark scan configs |
| `inspector2:GetEc2DeepInspectionConfiguration` | Get EC2 deep inspection settings |
| `inspector2:ListDelegatedAdminAccounts` | Identify delegated admin |
| `inspector2:GetConfiguration` | Get org auto-enable settings |
| `inspector2:ListMembers` | List member accounts |
| `inspector2:ListFindings` | List finding IDs with filters |
| `inspector2:BatchGetFindingDetails` | Get finding details for one or more findings by ARN |
| `inspector2:ListFindingAggregations` | Get aggregated finding counts |

## Severity Scoring

Inspector uses CVSS (Common Vulnerability Scoring System) for package vulnerabilities and a severity mapping for other finding types:

### Package Vulnerabilities (CVSS-based)

| Level | CVSS Score | Description |
|-------|-----------|-------------|
| Informational | 0.0 | No exploitable vulnerability |
| Low | 0.1 – 3.9 | Low-impact vulnerability |
| Medium | 4.0 – 6.9 | Moderate-impact vulnerability |
| High | 7.0 – 8.9 | High-impact vulnerability |
| Critical | 9.0 – 10.0 | Critical-impact vulnerability |

### Other Finding Types

| Finding Type | Severity Basis |
|-------------|---------------|
| Code Vulnerability | CWE severity + exploitability context |
| Network Reachability | Exposed port risk + service type |

**Key notes:**

- Inspector uses the highest available CVSS score (NVD or vendor-provided)
- Inspector Score may differ from raw CVSS — it incorporates exploitability and fix availability
- ECR findings include both CVSS v2 and v3 scores when available

**Documentation:** https://docs.aws.amazon.com/inspector/latest/user/findings-understanding-severity.html

## Service Notes

No service-specific notes.

## Output Sensitivity

Inspector finding details (`ListFindings`, `BatchGetFindingDetails`, coverage APIs) contain:

- EC2 instance IDs and AMI IDs
- ECR repository names and image digests
- Lambda function names and ARNs
- Package names and installed versions with CVE identifiers
- Network configuration details (ports, protocols, paths)
- Code file paths and line numbers (code vulnerabilities)

Present severity/type aggregation first. Offer full finding details on request.
