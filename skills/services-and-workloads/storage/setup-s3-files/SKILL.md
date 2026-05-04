---
name: setup-s3-files
description: >
  Creates and configures Amazon S3 file systems providing cached NFS access to
  S3 buckets, and integrates them with EC2, Lambda, ECS, and EKS compute. Use
  when the user wants to create an S3 file system, mount S3 Files on any compute
  type, configure IAM roles, or set up access points. Not for Mountpoint for S3
  or S3 File Gateway.
version: 1
metadata:
  service: [s3, s3files, efs, ec2, lambda, ecs, eks, iam]
  task: [deploy, configure, integrate]
  persona: [developer, devops, data-engineer]
  workload: [storage, data-analytics, ai-ml, serverless, containers]
---

# Setting Up S3 Files

## Overview

Creates Amazon S3 file systems providing cached NFS access to S3 buckets and
integrates them with compute resources. Covers prerequisites, IAM roles, file
system setup, mount targets, and compute-specific mounting for EC2, Lambda, ECS,
and EKS.

S3 Files is built on EFS but uses different APIs (`s3files` namespace), ARN formats (`arn:aws:s3files:`), and IAM actions (`s3files:ClientMount`). Key differences: requires an S3 bucket with versioning, uses a service IAM role for sync, TLS is always-on, and uses `mount -t s3files`.

For authoritative guidance, see the [S3 Files Documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html).

## Parameters

- **bucket_name** (required): S3 bucket name
- **region** (required): AWS region
- **vpc_id** (required): VPC ID (format: `vpc-xxxxxxxx`)
- **subnet_ids** (required): Subnet IDs (format: `subnet-xxxxxxxx`)
- **compute_type** (optional, default: EC2): EC2, Lambda, ECS, or EKS

**Constraints:** You MUST ask for all required parameters upfront in a single prompt.

**Note:** If the user doesn't know their VPC or subnet IDs, discover with `aws ec2 describe-vpcs` and `aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-ID`.

## Common Tasks

### 0. Verify Dependencies

**Constraints:**

- You MUST verify `aws` CLI supports S3 Files — run `aws s3files help`. If the command fails, upgrade to AWS CLI v2: [Installing the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- You MUST confirm valid AWS credentials with `aws sts get-caller-identity`
- You MUST check that `amazon-efs-utils` ≥ 3.0.0 is installed for EC2 mounting (`rpm -q amazon-efs-utils` or `dpkg -l amazon-efs-utils`)
- You MUST ONLY check for tool existence and version — MUST NOT execute destructive or mutating commands during verification
- You MUST inform the user if any required tools are missing
- You MUST respect the user's decision to abort if tools are unavailable
- You SHOULD explain what each step does and why before executing it
- You SHOULD display write commands and wait for user confirmation before executing

**S3 Files is NOT** Mountpoint for S3, S3 File Gateway, or Amazon File Cache. It uses the `s3files` CLI namespace and `s3files:` IAM actions, but the trust policy principal is `elasticfilesystem.amazonaws.com` (built on EFS).

### 1. Classify the Request

| User intent | Workflow |
|---|---|
| Create S3 file system from scratch | A: Full Setup |
| Mount existing file system on EC2 | B: Mount Only |
| Mount on Lambda | C: Lambda Integration |
| Mount on ECS (Fargate/Managed Instances) | D: ECS Integration |
| Mount on EKS | E: EKS Integration |
| Configure access points for isolation | F: Access Points |

### 2. Workflow A — Full Setup

See [full setup procedure](references/setup-s3-file-system.md).

**Constraints:**

- You MUST verify bucket versioning is enabled and encryption is SSE-S3 or SSE-KMS
- You MUST create the IAM role before creating the file system
- You MUST wait for mount targets to reach `available` state (5–7 minutes) before mounting
- You MUST NOT skip the compute IAM role — intelligent read routing requires S3 GetObject
- You MUST use the `s3files` CLI namespace, not `efs`

### 2a. Create File System Policy (Recommended)

Restrict which principals can mount:

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

To also restrict to a specific access point, add a `Condition` with `"s3files:AccessPointArn"`.

> **Note:** Without a resource policy, any IAM principal with `s3files:ClientMount` in the account can mount. Scope to specific roles for production.

### 3. Workflow B — Mount Only

See [EC2 mounting guide](references/mount-on-ec2.md).

### 4. Workflow C — Lambda Integration

See [Lambda integration guide](references/integrate-with-lambda.md).

**Constraints:**

- Lambda MUST be in the same VPC as the file system
- Lambda requires an S3 Files access point (cannot mount root directly)
- Use `arn:aws:s3files:` ARN format (not `arn:aws:elasticfilesystem:`)
- Lambda takes 2-3 minutes to go Active after adding VPC + file system config

### 5. Workflow D — ECS Integration

See [ECS integration guide](references/integrate-with-ecs.md).

**Constraints:**

- You MUST use `s3filesVolumeConfiguration` (NOT `efsVolumeConfiguration`)
- You MUST use `fileSystemArn` (full ARN), NOT `fileSystemId`
- Transit encryption is mandatory, always on
- EC2 launch type is NOT supported — Fargate and Managed Instances only

### 6. Workflow E — EKS Integration

Supported via EFS CSI driver ≥ 3.0.0. NOT supported on EKS Fargate.
See [EKS integration guide](references/integrate-with-eks.md).

### 7. Workflow F — Access Points

See [access points guide](references/configure-access-points.md).

Use access points for multi-tenant isolation, Lambda integration, or enforcing POSIX identity.

## Troubleshooting

### mount.s3files: command not found
Install or upgrade `amazon-efs-utils` to ≥ 3.0.0.

### Connection timed out during mount
Mount target SG must allow inbound TCP 2049 from compute SG.

### Access denied during mount
Compute role needs `s3files:ClientMount`.

### Files not appearing in S3 after write
Writes sync within ~60 seconds. Check export status with `getfattr`.

### ECS ResourceInitializationError DNS resolution
Used `efsVolumeConfiguration` instead of `s3filesVolumeConfiguration`.

## Cleanup

Delete in order: unmount → access points (if created) → mount targets → file system → security groups (if created) → IAM roles.
## Security Considerations

- Use scoped IAM permissions (`s3files:ClientMount`, `s3files:ClientWrite`) — avoid FullAccess in production
- S3 Files enforces TLS automatically — no client-side flag needed
- Scope security groups to specific SG references — avoid 0.0.0.0/0
- Monitor `PendingExports` and `ExportFailures` CloudWatch metrics

## Additional Resources

- [references/setup-s3-file-system.md](references/setup-s3-file-system.md) — Complete setup procedure
- [references/integrate-with-lambda.md](references/integrate-with-lambda.md) — Lambda integration
- [references/integrate-with-ecs.md](references/integrate-with-ecs.md) — ECS Fargate integration
- [references/integrate-with-eks.md](references/integrate-with-eks.md) — EKS CSI driver integration
- [references/configure-access-points.md](references/configure-access-points.md) — Access point configuration
- [references/mount-on-ec2.md](references/mount-on-ec2.md) — EC2 mounting instructions
- [S3 Files Documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html)
