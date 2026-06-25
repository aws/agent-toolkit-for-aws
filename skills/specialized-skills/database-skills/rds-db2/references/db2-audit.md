# RDS for Db2 — Db2 Audit to S3

> **Source**
>
> - `04-db2-client/db2-audit/AWS-Blog-Post-DB2-Audit.md` — "Simplifying DB2 Audit Configuration on Amazon RDS: Three Easy Ways to Get Started"
> - Bundled script: `scripts/create-db2-audit-role.sh`
> - AWS docs: DB2_AUDIT option — https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Db2.Options.Audit.html
>
> Commands and option/setting names are reproduced verbatim from the source script and blog. All identifiers are placeholders (`<account-id>`, `<region>`, `<audit-bucket>`, `<instance-id>`, `<dbname>`).

## What audit enables

On RDS for Db2 the **DB2_AUDIT** option makes RDS automatically upload Db2 audit logs to an S3 bucket you own. Four moving parts:

- Db2 generates audit records from the audit policies you create in-database.
- RDS uploads those logs to your S3 bucket.
- An IAM role grants RDS permission to write to the bucket.
- The `DB2_AUDIT` option on an RDS option group ties the role and bucket to the instance.

> **Unverified:** the v1 `rdsadmin.enable_audit(...)` procedure is **not found in source**. Enable audit with the option-group method below instead — it is the sourced, supported path.

**Prerequisites:** an existing S3 bucket, AWS CLI configured, an RDS for Db2 instance (version 11.5 or later), and IAM permission to create policies, roles, and option groups.

## 1. Create the IAM policy and role

The bundled `scripts/create-db2-audit-role.sh` creates a policy granting the audit role S3 write access plus KMS data-key access:

```bash
# create-policy returns the ARN; capture it (aws iam get-policy needs --policy-arn, not --policy-name)
IAM_POLICY_ARN=$(aws iam create-policy --policy-name db2-audit-policy \
  --policy-document file://db2-audit-policy.json \
  --query 'Policy.Arn' --output text)
```

Policy actions (verbatim from source): `s3:ListBucket`, `s3:GetBucketAcl`, `s3:GetBucketLocation` on `arn:aws:s3:::<audit-bucket>`; `s3:PutObject`, `s3:ListMultipartUploadParts`, `s3:AbortMultipartUpload` on `arn:aws:s3:::<audit-bucket>/*`; `s3:ListAllMyBuckets`; and `kms:GenerateDataKey`, `kms:Decrypt` (required when the bucket uses SSE-KMS).

Create the role trusting `rds.amazonaws.com`. Add the **confused-deputy** condition keys so only your account and instance can make RDS assume the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "rds.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "<account-id>" },
      "ArnLike": { "aws:SourceArn": "arn:aws:rds:<region>:<account-id>:db:<instance-id>" }
    }
  }]
}
```

```bash
aws iam create-role --role-name db2-audit-role --assume-role-policy-document file://trust-policy.json
# $IAM_POLICY_ARN was captured from create-policy above. If the policy already exists, look it up:
#   IAM_POLICY_ARN=$(aws iam list-policies \
#     --query "Policies[?PolicyName=='db2-audit-policy'].Arn" --output text)
aws iam attach-role-policy --policy-arn $IAM_POLICY_ARN --role-name db2-audit-role
```

## 2. Create the option group and add the DB2_AUDIT option

```bash
aws rds create-option-group \
  --engine-name db2 \
  --major-engine-version 11.5 \
  --option-group-description "Option group for DB2 audit" \
  --option-group-name db2-audit-option-group

aws rds add-option-to-option-group \
  --option-group-name db2-audit-option-group \
  --options '[{
    "OptionName": "DB2_AUDIT",
    "OptionSettings": [
      {"Name": "IAM_ROLE_ARN", "Value": "arn:aws:iam::<account-id>:role/db2-audit-role"},
      {"Name": "S3_BUCKET_NAME", "Value": "<audit-bucket>"}
    ]
  }]' \
  --apply-immediately
```

Preserve the setting names exactly: **`IAM_ROLE_ARN`** and **`S3_BUCKET_NAME`**.

## 3. Apply the option group to the instance

```bash
aws rds modify-db-instance \
  --db-instance-identifier <instance-id> \
  --option-group-name db2-audit-option-group \
  --apply-immediately

aws rds describe-db-instances --db-instance-identifier <instance-id> \
  --query 'DBInstances[0].OptionGroupMemberships'
```

## 4. Configure audit policies in-database

```sql
db2 connect to <dbname>

db2 "CREATE AUDIT POLICY FAILED_LOGINS CATEGORIES VALIDATE STATUS FAILURE ERROR TYPE AUDIT"
db2 "CREATE AUDIT POLICY DDL_OPERATIONS CATEGORIES OBJMAINT STATUS SUCCESS ERROR TYPE AUDIT"

db2 "AUDIT DATABASE USING POLICY FAILED_LOGINS, DDL_OPERATIONS"

db2 "SELECT * FROM SYSCAT.AUDITPOLICIES"
```

## S3 log layout

```
<audit-bucket>/AWSLogs/<account-id>/RDS/<region>/db2/<instance-id>/audit/YYYY/MM/DD/audit_<timestamp>.log
```

## Optional: stream to CloudWatch

Deploy a Lambda (triggered by EventBridge on a `rate(5 minutes)` schedule, or by S3 events) to forward audit logs from S3 to CloudWatch Logs, then add CloudWatch alarms — for example on failed logins — and CloudWatch Logs Insights queries for analysis.

## S3 security and lifecycle

- **Enforce TLS:** bucket policy that denies `s3:*` when `aws:SecureTransport` is `false`.
- **Encrypt at rest (required):** Db2 audit logs are sensitive data and MUST be encrypted at rest. Enable bucket encryption with `aws s3api put-bucket-encryption` (SSE-S3 `AES256` or SSE-KMS) and add a bucket policy that **denies `s3:PutObject` when `s3:x-amz-server-side-encryption` is absent or not your chosen algorithm**, so unencrypted uploads are rejected. When using SSE-KMS, the audit role needs `kms:GenerateDataKey`/`kms:Decrypt` on that key.
- **Retention:** `aws s3api put-bucket-lifecycle-configuration` to transition logs to `STANDARD_IA` (30 days) and `GLACIER` (90 days) and expire per your compliance window.

## Troubleshooting

- **S3 bucket access denied (logs not appearing):** check the bucket and role policies — `aws s3api get-bucket-policy --bucket <audit-bucket>`, and for the managed policy attached in Section 1 use `aws iam list-attached-role-policies --role-name db2-audit-role` then `aws iam get-policy-version --policy-arn arn:aws:iam::<account-id>:policy/db2-audit-policy --version-id $(aws iam get-policy --policy-arn arn:aws:iam::<account-id>:policy/db2-audit-policy --query 'Policy.DefaultVersionId' --output text)`. (`aws iam get-role-policy` only returns inline policies, so it returns `NoSuchEntity` here.) Confirm `kms:GenerateDataKey`/`kms:Decrypt` if the bucket uses SSE-KMS.
- **Option not applied (DB2_AUDIT not visible):** `aws rds describe-option-groups --option-group-name db2-audit-option-group`, then re-check `OptionGroupMemberships` on the instance; `modify-db-instance` may still be pending.
- **Audit policy not active (no logs despite policies):** verify with `SELECT * FROM SYSCAT.AUDITUSE`; run `db2 "FLUSH AUDIT CONFIGURATION"` if needed.
