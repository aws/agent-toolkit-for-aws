# S3 Security Workflows

## Workflow A: Secure New Bucket

Run all steps in order. Do not skip.

```bash
# 1. Create in account regional namespace (REQUIRED — not global namespace)
# Pattern: <your-prefix>-<account-id>-<region>-an
aws s3api create-bucket \
  --bucket <your-prefix>-111122223333-us-east-1-an \
  --bucket-namespace account-regional \
  --region us-east-1
# Non-us-east-1: add --create-bucket-configuration LocationConstraint=<region>

# NOTE: Do NOT configure Block Public Access or ACL ownership controls.
# S3 enables Block Public Access and disables ACLs (BucketOwnerEnforced) by default on new buckets.
# Changing these defaults is unnecessary and risks misconfiguration.

# 2. Enable versioning
aws s3api put-bucket-versioning \
  --bucket <bucket-name> \
  --versioning-configuration Status=Enabled

# 3. Enable default encryption (SSE-S3 + Bucket Keys + SSE-C blocked)
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true,"BlockedEncryptionTypes":{"EncryptionType":["SSE-C"]}}]}'

# 4. Enable logging (CONDITIONAL — choose one option)
#
# Ask the user which option they prefer before proceeding.
# Present the trade-offs:
#
#   Option A — S3 Server Access Logging
#     - No per-request charge; you pay only for the storage of the log files in S3
#     - Captures all HTTP requests including unauthenticated/presigned URL access
#     - No IAM principal ARN attribution; limited identity context
#     - No real-time alerting capability
#     - Good default for cost-sensitive workloads
#
#   Option B — CloudTrail Data Events
#     - Per-event charge applies (see CloudTrail pricing)
#     - Full IAM principal ARN on every event — best for security investigations
#     - Integrates with EventBridge and CloudWatch for real-time alerting
#     - Logs anonymous (unauthenticated) requests and AccessDenied failures
#     - Does NOT log requests that fail authentication (invalid/malformed credentials)
#     - Recommended when security attribution or automated response is required
#
# SKIP THIS STEP if the user has already chosen and configured their preferred option.

# --- Option A: S3 Server Access Logging ---
# SKIP THIS STEP if <bucket-name> is itself the logging bucket.
# WARNING: put-bucket-policy replaces the entire existing policy.
# Attempt to retrieve existing policy first:
aws s3api get-bucket-policy --bucket <logging-bucket> --output text
# If NoSuchBucketPolicy is returned, no backup needed — proceed with a new policy containing only the S3LogDelivery statement.
# If a policy exists, back it up before modification:
aws s3api get-bucket-policy --bucket <logging-bucket> --output text > backup-policy-$(date +%s).json
# Add S3LogDelivery statement to existing policy's Statement array, then apply:
aws s3api put-bucket-policy --bucket <logging-bucket> --policy \
  '{"Version":"2012-10-17","Statement":[<...existing statements...>,{"Sid":"S3LogDelivery","Effect":"Allow","Principal":{"Service":"logging.s3.amazonaws.com"},"Action":["s3:PutObject"],"Resource":"arn:aws:s3:::<logging-bucket>/*","Condition":{"StringEquals":{"aws:SourceAccount":"<account-id>"},"ArnLike":{"aws:SourceArn":"arn:aws:s3:::<bucket-name>"}}}]}'

aws s3api put-bucket-logging \
  --bucket <bucket-name> \
  --bucket-logging-status \
  '{"LoggingEnabled":{"TargetBucket":"<logging-bucket>","TargetPrefix":"<bucket-name>/"}}'

# --- Option B: CloudTrail Data Events ---
# IMPORTANT: use the trail's home region, not the bucket's region.
# Find trail home region first:
aws cloudtrail describe-trails --query 'trailList[*].[Name,HomeRegion]'

aws cloudtrail put-event-selectors \
  --trail-name <trail-name> \
  --region <trail-home-region> \
  --event-selectors '[{"ReadWriteType":"All","IncludeManagementEvents":true,"DataResources":[{"Type":"AWS::S3::Object","Values":["arn:aws:s3:::<bucket-name>/*"]}]}]'

# 5. Enforce HTTPS-only
# WARNING: put-bucket-policy replaces the entire existing policy.
# Attempt to retrieve existing policy first:
aws s3api get-bucket-policy --bucket <bucket-name> --output text
# If a policy exists, back it up before modification:
aws s3api get-bucket-policy --bucket <bucket-name> --output text > backup-policy-$(date +%s).json
# If NoSuchBucketPolicy is returned, no backup needed — proceed with a new policy.
# Add DenyInsecureTransport statement to existing policy's Statement array (or create new), then apply:
aws s3api put-bucket-policy --bucket <bucket-name> --policy \
  '{"Version":"2012-10-17","Statement":[<...existing statements...>,{"Sid":"DenyInsecureTransport","Effect":"Deny","Principal":"*","Action":"s3:*","Resource":["arn:aws:s3:::<bucket-name>/*","arn:aws:s3:::<bucket-name>"],"Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}'

# 6. Enable ABAC (Attribute-Based Access Control)
aws s3api put-bucket-abac \
  --bucket <bucket-name> \
  --abac-status Status=Enabled
```

## Workflow E: Enable Monitoring

```bash
# GuardDuty — check if detector already exists before creating
aws guardduty list-detectors --region <region>
# Only run create-detector if list-detectors returns empty:
aws guardduty create-detector --enable --region <region>
```

Enable these core AWS Config rules (requires a configuration recorder in the region):

- `s3-bucket-public-read-prohibited`
- `s3-bucket-ssl-requests-only`
- `s3-bucket-versioning-enabled`
- `s3-bucket-logging-enabled`

Optional (enable if compliance requires):

- `s3-bucket-public-write-prohibited`
- `s3-account-level-public-access-blocks`
- `s3-bucket-replication-enabled`
- `cloudtrail-s3-dataevents-enabled`

Note: CloudTrail data event configuration is covered in Workflow A step 4 (logging choice). If the user chose S3 server access logging in Workflow A and later wants to add CloudTrail, use the command below:

```bash
# IMPORTANT: use the trail's home region, not the bucket's region
aws cloudtrail describe-trails --query 'trailList[*].[Name,HomeRegion]'

aws cloudtrail put-event-selectors \
  --trail-name <trail-name> \
  --region <trail-home-region> \
  --event-selectors '[{"ReadWriteType":"All","IncludeManagementEvents":true,"DataResources":[{"Type":"AWS::S3::Object","Values":["arn:aws:s3:::<bucket-name>/*"]}]}]'
```

## Workflow B: Audit Commands

```bash
aws s3api get-public-access-block --bucket <bucket-name>
aws s3api get-bucket-acl --bucket <bucket-name>
aws s3api get-bucket-ownership-controls --bucket <bucket-name>
aws s3api get-bucket-encryption --bucket <bucket-name>
aws s3api get-bucket-versioning --bucket <bucket-name>
aws s3api get-bucket-logging --bucket <bucket-name>
aws s3api get-object-lock-configuration --bucket <bucket-name>
# ObjectLockConfigurationNotFoundError = NOT CONFIGURED (not a failure)

# Policy checks (Critical: public policy + HTTPS enforcement)
aws s3api get-bucket-policy --bucket <bucket-name> --output text

# Logging — CloudTrail data events (Medium)
aws cloudtrail describe-trails --query 'trailList[*].[Name,HomeRegion]'
aws cloudtrail get-event-selectors \
  --trail-name <trail-name> \
  --region <trail-home-region>

# GuardDuty S3 Protection (Medium)
aws guardduty list-detectors --region <region>
# If a detector exists:
aws guardduty get-detector --detector-id <detector-id> --region <region>

# Check if an analyzer exists
aws accessanalyzer list-analyzers --region <region>
# If empty, report as finding: "No IAM Access Analyzer configured in <region>"
# Do NOT create an analyzer during audit — remediate separately via Workflow C.
# If an analyzer exists, list S3 findings:
aws accessanalyzer list-findings \
  --analyzer-arn <analyzer-arn> \
  --filter '{"resourceType":{"eq":["AWS::S3::Bucket"]}}' \
  --region <region>
```
