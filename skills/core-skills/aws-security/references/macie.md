# Macie

- **Docs**: https://docs.aws.amazon.com/macie/latest/user/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/macie/latest/user/llms.txt

Amazon Macie is a data security service that uses machine learning and pattern matching to discover and classify sensitive data stored in Amazon S3. It identifies PII, financial data, credentials, and other sensitive content, and assesses S3 bucket access configurations. Findings are in Macie's proprietary JSON format and are also sent to Security Hub in OCSF format.

## Data Sources

Macie analyzes:

- S3 bucket inventory and access configurations (automated)
- S3 object content via classification jobs or automated sensitive data discovery
- Supports all S3 storage classes except Glacier Deep Archive

## Read-Only APIs

| API | Purpose |
|-----|---------|
| `macie2:GetMacieSession` | Check Macie enablement status |
| `macie2:GetAutomatedDiscoveryConfiguration` | Check automated discovery settings |
| `macie2:ListClassificationJobs` | List classification jobs |
| `macie2:DescribeClassificationJob` | Get job details |
| `macie2:GetFindingsPublicationConfiguration` | Get finding publication settings |
| `macie2:GetClassificationExportConfiguration` | Get classification export destination (S3 bucket) |
| `macie2:ListAllowLists` | List allow lists |
| `macie2:GetRevealConfiguration` | Get reveal configuration status |
| `macie2:GetUsageTotals` | Get usage and cost estimates |
| `macie2:ListOrganizationAdminAccounts` | Identify delegated admin |
| `macie2:DescribeOrganizationConfiguration` | Get org auto-enable settings |
| `macie2:ListMembers` | List member accounts |
| `macie2:GetFindingStatistics` | Get aggregated finding statistics |
| `macie2:ListFindings` | List finding IDs |
| `macie2:GetFindings` | Get finding details (batch, max 50) |
| `macie2:ListResourceProfileDetections` | List resource profile detections |
| `macie2:GetSensitiveDataOccurrencesAvailability` | Check if sensitive data samples available |

## Severity Scoring

Macie assigns severity (1-3 scale) based on **sensitive data type** and context, not occurrence count alone:

| Severity | Score | Criteria |
|----------|-------|----------|
| High | 3 | Credentials (API keys, private keys, passwords), large volumes of financial/PII data, or multiple categories in one object |
| Medium | 2 | Financial data (credit cards, bank accounts), moderate PII exposure |
| Low | 1 | Small amounts of non-credential PII (names, addresses), single-category findings |

**Key rules:**

- Credentials are **always** High regardless of occurrence count
- Severity increases when multiple sensitive data categories appear in the same S3 object
- Custom data identifiers inherit the severity configured at creation time
- Policy findings (bucket-level) use a separate severity scale based on bucket exposure
- Automated discovery findings aggregate across objects — severity reflects bucket-level risk

Refer to [Macie severity scoring documentation](https://docs.aws.amazon.com/macie/latest/user/findings-severity.html) for complete per-finding-type breakdown.

## Service Notes

No service-specific notes.

## Output Sensitivity

Macie finding details (`GetFindings`) contain:

- S3 bucket names and object keys where sensitive data was detected
- Sensitive data categories and occurrence counts (PII, financial, credentials)
- AWS account IDs and resource ARNs
- Classification job configuration details
- Bucket access permissions and encryption status

Present finding severity/type summary and affected bucket counts first. Offer full finding details on request. Never include actual sensitive data samples in output.
