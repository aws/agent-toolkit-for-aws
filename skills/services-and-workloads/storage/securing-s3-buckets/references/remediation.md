# S3 Security Remediation

## Public Bucket Detected

```bash
aws s3api put-public-access-block \
  --bucket <bucket-name> \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
# WARNING: Do NOT delete the entire bucket policy — it may contain critical controls (HTTPS enforcement, VPC restrictions, etc.).
# Instead, surgically remove only the offending public-grant statement(s):
# 1. Review the current policy:
aws s3api get-bucket-policy --bucket <bucket-name> --output text | jq .
# 2. Back up existing policy before modification:
aws s3api get-bucket-policy --bucket <bucket-name> --output text > backup-policy-$(date +%s).json
# 3. Remove only statements with "Principal": "*" or "AWS": "*" that grant public access.
# 4. Re-apply the scoped-down policy:
aws s3api put-bucket-policy --bucket <bucket-name> --policy file://scoped-down-policy.json
# Verify
aws s3api get-public-access-block --bucket <bucket-name>
```

## Unencrypted Objects / Missing Default Encryption

```bash
# Set default encryption
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true,"BlockedEncryptionTypes":{"EncryptionType":["SSE-C"]}}]}'
# Re-encrypt existing objects
# ⚠️ WARNING: --metadata-directive REPLACE without --metadata drops all user-defined metadata.
#    Before running, verify no objects carry custom metadata:
#      aws s3api head-object --bucket <bucket-name> --key <sample-key>
#    If objects have custom metadata, use a per-object script that reads
#    metadata via head-object and re-supplies it with --metadata on copy.
aws s3 cp s3://<bucket-name>/ s3://<bucket-name>/ \
  --recursive --sse AES256 --metadata-directive REPLACE
```

## S3 Bucket Keys Not Enabled (high KMS costs)

```bash
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"<key-arn>"},"BucketKeyEnabled":true,"BlockedEncryptionTypes":{"EncryptionType":["SSE-C"]}}]}'
```

## Using AWS Managed Key (aws/s3)

You MUST apply a least-privilege key policy — do NOT create a key without `--policy file://key-policy.json`. See [encryption.md § Least-Privilege KMS Key Policy Template](encryption.md#least-privilege-kms-key-policy-template) for the full template.

```bash
# 1. Save the key-policy.json template from encryption.md (replace placeholders)
# 2. Create customer managed key with least-privilege policy
aws kms create-key --description "S3 encryption key" --policy file://key-policy.json
# 3. Update bucket encryption to use the new key (full ARN, not alias)
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"arn:aws:kms:<region>:<account>:key/<key-id>"},"BucketKeyEnabled":true,"BlockedEncryptionTypes":{"EncryptionType":["SSE-C"]}}]}'
```

## SSE-C Not Blocked

```bash
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true,"BlockedEncryptionTypes":{"EncryptionType":["SSE-C"]}}]}'
```

## Missing Logging

Enable either S3 server access logging or CloudTrail data events — one is sufficient.

**Option A — S3 Server Access Logging** (no per-request charge; you pay only for log file storage in S3):

```bash
aws s3api put-bucket-logging \
  --bucket <bucket-name> \
  --bucket-logging-status \
  '{"LoggingEnabled":{"TargetBucket":"<logging-bucket>","TargetPrefix":"<bucket-name>/"}}'
```

**Option B — CloudTrail Data Events** (per-event charge applies; provides full IAM principal attribution, logs anonymous requests and AccessDenied failures, and supports real-time alerting):

```bash
# IMPORTANT: use the trail's home region, not the bucket's region
aws cloudtrail describe-trails --query 'trailList[*].[Name,HomeRegion]'

aws cloudtrail put-event-selectors \
  --trail-name <trail-name> \
  --region <trail-home-region> \
  --event-selectors '[{"ReadWriteType":"All","IncludeManagementEvents":true,"DataResources":[{"Type":"AWS::S3::Object","Values":["arn:aws:s3:::<bucket-name>/*"]}]}]'
```

## Overly Permissive Bucket Policy

1. Run IAM Access Analyzer to identify external access paths
2. Scope down `Action` to minimum required
3. Add `Condition` blocks to restrict by IP, VPC, or MFA

```bash
# Simulate effective permissions before changing
aws iam simulate-principal-policy \
  --policy-source-arn <role-arn> \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::<bucket-name>/key
```

## Access Denied Errors

Diagnosis order:

1. IAM user/role policy — `simulate-principal-policy`
2. Bucket policy — `get-bucket-policy`
3. Block Public Access — `get-public-access-block`
4. VPC endpoint policy (if applicable)
5. SCPs/RCPs (if AWS Organizations)
6. CloudTrail logs for detailed error context
