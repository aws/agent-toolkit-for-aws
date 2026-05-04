# Setting Up an S3 File System

Complete procedure to create an S3 file system from an existing S3 bucket, including IAM roles, mount targets, and compute configuration.

## Step 1: Verify S3 Bucket Prerequisites

```bash
aws s3api get-bucket-versioning --bucket BUCKET_NAME
```

- You MUST verify `Status` is `Enabled`. If the response is empty or does not show `Status: Enabled`, versioning is not active.
- If not: `aws s3api put-bucket-versioning --bucket BUCKET_NAME --versioning-configuration Status=Enabled`
- Bucket encryption MUST be SSE-S3 or SSE-KMS (not SSE-C)

## Step 2: Create IAM Role for File System

Trust policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": { "Service": "elasticfilesystem.amazonaws.com" },
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": { "aws:SourceAccount": "ACCOUNT_ID" },
            "ArnLike": { "aws:SourceArn": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/*" }
        }
    }]
}
```

Inline policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3BucketPermissions",
            "Effect": "Allow",
            "Action": ["s3:ListBucket", "s3:ListBucketVersions"],
            "Resource": "arn:aws:s3:::BUCKET_NAME",
            "Condition": { "StringEquals": { "aws:ResourceAccount": "ACCOUNT_ID" } }
        },
        {
            "Sid": "S3ObjectPermissions",
            "Effect": "Allow",
            "Action": ["s3:AbortMultipartUpload", "s3:DeleteObject*", "s3:GetObject*", "s3:List*", "s3:PutObject*"],
            "Resource": "arn:aws:s3:::BUCKET_NAME/*",
            "Condition": { "StringEquals": { "aws:ResourceAccount": "ACCOUNT_ID" } }
        },
        {
            "Sid": "EventBridgeManage",
            "Effect": "Allow",
            "Action": ["events:DeleteRule", "events:DisableRule", "events:EnableRule", "events:PutRule", "events:PutTargets", "events:RemoveTargets"],
            "Condition": { "StringEquals": { "events:ManagedBy": "elasticfilesystem.amazonaws.com" } },
            "Resource": ["arn:aws:events:*:ACCOUNT_ID:rule/DO-NOT-DELETE-S3-Files*"]
        },
        {
            "Sid": "EventBridgeRead",
            "Effect": "Allow",
            "Action": ["events:DescribeRule", "events:ListRuleNamesByTarget", "events:ListRules", "events:ListTargetsByRule"],
            "Resource": ["arn:aws:events:REGION:ACCOUNT_ID:rule/*"]
        }
    ]
}
```

If using SSE-KMS, add:

```json
{
    "Sid": "UseKmsKeyWithS3Files",
    "Effect": "Allow",
    "Action": ["kms:GenerateDataKey", "kms:Encrypt", "kms:Decrypt", "kms:ReEncryptFrom", "kms:ReEncryptTo"],
    "Condition": {
        "StringLike": {
            "kms:ViaService": "s3.REGION.amazonaws.com",
            "kms:EncryptionContext:aws:s3:arn": ["arn:aws:s3:::BUCKET_NAME", "arn:aws:s3:::BUCKET_NAME/*"]
        }
    },
    "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID"
}
```

Save the trust and inline policy JSON above to files, then create the role using inline content:

```bash
aws iam create-role --role-name S3FilesRole-BUCKET_NAME \
  --assume-role-policy-document "$(cat trust-policy.json)"
aws iam put-role-policy --role-name S3FilesRole-BUCKET_NAME \
  --policy-name S3FilesSyncPolicy \
  --policy-document "$(cat inline-policy.json)"
```

## Step 3: Create the S3 File System

```bash
aws s3files create-file-system --region REGION --bucket arn:aws:s3:::BUCKET_NAME --role-arn arn:aws:iam::ACCOUNT_ID:role/S3FilesRole-BUCKET_NAME
```

Note the `FileSystemId` from the response.

## Step 4: Create Security Group and Mount Targets

> **Note:** If the user already has a security group allowing inbound TCP 2049, reuse it instead of creating a new one.

Create a dedicated security group for the mount target:

```bash
aws ec2 create-security-group --group-name s3files-mount-target-sg \
  --description "S3 Files mount target - NFS access" --vpc-id vpc-VPC_ID --region REGION

aws ec2 authorize-security-group-ingress --group-id sg-MOUNT_TARGET_SG \
  --protocol tcp --port 2049 --source-group sg-COMPUTE_SG --region REGION
```

Create mount target:

```bash
aws s3files create-mount-target --region REGION --file-system-id fs-FILESYSTEM_ID \
  --subnet-id subnet-SUBNET_ID --security-groups sg-MOUNT_TARGET_SG
```

- Mount target SG MUST allow inbound TCP 2049
- Wait for `LifeCycleState` to be `available` (5–7 minutes)
- Not all AZs support S3 Files. If you get `ValidationException`, try a different AZ subnet.
- `--security-groups` is optional — if omitted, uses the default VPC SG. For production, create a dedicated SG.

## Step 4a: Create File System Policy (Recommended)

Restrict which principals can mount. Without a resource policy, any IAM principal with `s3files:ClientMount` in the account can mount the file system.

```bash
aws s3files put-file-system-policy --file-system-id fs-ID --policy '{
  "Version":"2012-10-17",
  "Statement":[{
    "Effect":"Allow",
    "Principal":{"AWS":"arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME"},
    "Action":["s3files:ClientMount","s3files:ClientWrite"],
    "Resource":"arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID"
  }]
}'
```

## Step 5: Configure Compute IAM Role

For production, use a scoped inline policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": ["s3files:ClientMount", "s3files:ClientWrite"],
        "Resource": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-FILESYSTEM_ID"
    }]
}
```

For development/testing only, the managed policy is acceptable:

```bash
# DEV ONLY — grants access to ALL S3 file systems in the account
aws iam attach-role-policy --role-name EC2_ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FilesClientFullAccess
```

Add S3 inline policy for intelligent read routing:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        { "Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": "arn:aws:s3:::BUCKET_NAME/*" },
        { "Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::BUCKET_NAME" }
    ]
}
```

## Step 6: Mount on Compute

> ⚠️ **You MUST create a file system policy (Step 4a) before mounting in production.** Without one, any IAM principal with `s3files:ClientMount` in the account can mount this file system.

Continue with the guide matching the user's compute type:

- **EC2**: [mount-on-ec2.md](mount-on-ec2.md)
- **Lambda**: [integrate-with-lambda.md](integrate-with-lambda.md)
- **ECS**: [integrate-with-ecs.md](integrate-with-ecs.md)
- **EKS**: [integrate-with-eks.md](integrate-with-eks.md)
- **Access points**: [configure-access-points.md](configure-access-points.md)

## Security Considerations

- Create a file system policy (Step 4a) before mounting in production — without one, any principal with `s3files:ClientMount` can mount
- Use scoped IAM roles — avoid `AmazonS3FilesClientFullAccess` in production
- Scope S3 read routing permissions to the specific linked bucket
