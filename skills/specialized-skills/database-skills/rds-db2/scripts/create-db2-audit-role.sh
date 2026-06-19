#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# create-db2-audit-role.sh — Create the IAM policy/role and RDS option group
# that let RDS for Db2 upload audit logs to your S3 bucket.
#
# Configurable via environment variables (all optional except where noted):
#   REGION              AWS region for the option group / ARNs (default: us-east-1)
#   AUDIT_BUCKET_NAME   S3 bucket that receives audit logs (default: rds-db2-enablement)
#   AUDIT_KMS_KEY_ARN   CMK ARN for the bucket's SSE-KMS encryption. REQUIRED if the
#                       bucket uses SSE-KMS; leave unset only for SSE-S3 (AES256) buckets.
#   DB_INSTANCE_ID      Scope the role's trust to a single instance (default: * = any
#                       Db2 instance in this account/region)
#   MAJOR_ENGINE_VERSION  Db2 major engine version for the option group (default: 11.5)
# =============================================================================

policy_name="db2-audit-policy"
role_name="db2-audit-role"
audit_bucket_name="${AUDIT_BUCKET_NAME:-rds-db2-enablement}"
region="${REGION:-${AWS_REGION:-us-east-1}}"
major_engine_version="${MAJOR_ENGINE_VERSION:-11.5}"
instance_id="${DB_INSTANCE_ID:-*}"

# Account ID is computed once, up front, so it can be interpolated safely
# (command substitution does NOT expand inside single-quoted strings).
account_id="$(aws sts get-caller-identity --query Account --output text)"

# KMS key used for the audit bucket's SSE-KMS encryption. Scope kms:Decrypt /
# kms:GenerateDataKey to THIS key only (least privilege) rather than "*".
# Replace the placeholder, or export AUDIT_KMS_KEY_ARN before running.
audit_kms_key_arn="${AUDIT_KMS_KEY_ARN:-arn:aws:kms:${region}:${account_id}:key/REPLACE-WITH-AUDIT-BUCKET-KMS-KEY-ID}"

# --- Permissions policy (heredoc → variables expand) ---
policy_document=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Statement1",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketAcl", "s3:GetBucketLocation"],
      "Resource": ["arn:aws:s3:::${audit_bucket_name}"]
    },
    {
      "Sid": "Statement2",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"],
      "Resource": ["arn:aws:s3:::${audit_bucket_name}/*"]
    },
    {
      "Sid": "Statement3",
      "Effect": "Allow",
      "Action": ["s3:ListAllMyBuckets"],
      "Resource": ["*"]
    },
    {
      "Sid": "Statement4KmsScopedToAuditBucketKey",
      "Effect": "Allow",
      "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
      "Resource": ["${audit_kms_key_arn}"]
    }
  ]
}
EOF
)

# --- Trust policy with confused-deputy protection (aws:SourceAccount / aws:SourceArn) ---
trust_policy=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "rds.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "${account_id}" },
        "ArnLike": { "aws:SourceArn": "arn:aws:rds:${region}:${account_id}:db:${instance_id}" }
      }
    }
  ]
}
EOF
)

# --- Create the IAM policy and capture its ARN directly from the create call ---
# (aws iam get-policy requires --policy-arn, not --policy-name, so we capture the
#  ARN from create-policy output instead of a follow-up get-policy.)
IAM_POLICY_ARN=$(aws iam create-policy \
  --policy-name "$policy_name" \
  --policy-document "$policy_document" \
  --query 'Policy.Arn' --output text)

# --- Create the IAM role with the confused-deputy-protected trust policy ---
aws iam create-role \
  --role-name "$role_name" \
  --assume-role-policy-document "$trust_policy"

# --- Attach the policy to the role ---
aws iam attach-role-policy \
  --policy-arn "$IAM_POLICY_ARN" \
  --role-name "$role_name"

# --- Create the option group for DB2 audit ---
aws rds create-option-group \
  --engine-name db2 \
  --major-engine-version "$major_engine_version" \
  --option-group-description "Option group for DB2 audit" \
  --option-group-name "db2-audit-option-group"

# --- Add the DB2_AUDIT option (account_id expanded via heredoc, not single quotes) ---
option_settings=$(cat <<EOF
[{
  "OptionName": "DB2_AUDIT",
  "OptionSettings": [
    {"Name": "IAM_ROLE_ARN", "Value": "arn:aws:iam::${account_id}:role/${role_name}"},
    {"Name": "S3_BUCKET_NAME", "Value": "${audit_bucket_name}"}
  ]
}]
EOF
)

aws rds add-option-to-option-group \
  --option-group-name "db2-audit-option-group" \
  --options "$option_settings" \
  --apply-immediately
