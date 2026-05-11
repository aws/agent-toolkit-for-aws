# IAM Permissions by Workflow

Minimum IAM permissions required for each workflow. Use `aws iam simulate-principal-policy` to validate effective permissions before write operations.

| Workflow | Minimum permissions needed |
|---|---|
| A — Secure New Bucket | `s3:CreateBucket`, `s3:PutBucketVersioning`, `s3:PutEncryptionConfiguration`, `s3:PutBucketLogging`, `s3:PutBucketPolicy`, `s3:GetBucketPolicy`, `s3:PutBucketAbacStatus`, `cloudtrail:DescribeTrails`, `cloudtrail:PutEventSelectors` |
| B — Audit | `s3:GetBucketPublicAccessBlock`, `s3:GetBucketAcl`, `s3:GetBucketOwnershipControls`, `s3:GetEncryptionConfiguration`, `s3:GetBucketVersioning`, `s3:GetBucketLogging`, `s3:GetBucketPolicy`, `s3:GetBucketObjectLockConfiguration`, `accessanalyzer:ListAnalyzers`, `accessanalyzer:ListFindings`, `cloudtrail:GetEventSelectors`, `cloudtrail:DescribeTrails`, `guardduty:ListDetectors`, `guardduty:GetDetector` |
| C — Remediate | `s3:PutBucketPublicAccessBlock`, `s3:GetBucketPolicy`, `s3:PutBucketPolicy`, `s3:PutEncryptionConfiguration`, `kms:CreateKey`, `kms:PutKeyPolicy`, `kms:DescribeKey`, `iam:SimulatePrincipalPolicy` |
| D — Encryption | `s3:PutEncryptionConfiguration`, `kms:CreateKey`, `kms:PutKeyPolicy`, `kms:DescribeKey` |
| E — Monitoring | `cloudtrail:DescribeTrails`, `cloudtrail:PutEventSelectors`, `guardduty:ListDetectors`, `guardduty:CreateDetector`, `config:PutConfigRule` |
