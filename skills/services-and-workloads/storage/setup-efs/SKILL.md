---
name: setup-efs
description: >
  Creates and configures Amazon EFS file systems with encryption, throughput
  modes, lifecycle policies, mount targets, security groups, and access points.
  Integrates EFS with EC2, Lambda, ECS, and EKS compute. Use when the user wants
  to create an EFS file system, mount EFS on any compute type, configure access
  points, or set up shared NFS storage.
version: 1
metadata:
  service: [efs, ec2, iam]
  task: [deploy, configure, integrate]
  persona: [developer, devops, security-engineer]
  workload: [storage, containers, serverless]
---

# Setting Up EFS

## Overview

Creates and configures Amazon EFS file systems and integrates them with compute.

For authoritative guidance, see the [EFS User Guide](https://docs.aws.amazon.com/efs/latest/ug/whatisefs.html).

## Parameters

- **region** (required): AWS region
- **vpc_id** (required): VPC ID for mount targets (format: `vpc-xxxxxxxx`)
- **subnet_ids** (required): Subnet IDs for mount targets (format: `subnet-xxxxxxxx`)
- **filesystem_name** (optional): Name tag for the file system
- **throughput_mode** (optional, recommended: `elastic`): `elastic`, `provisioned`, or `bursting`
- **compute_type** (optional, default: EC2): EC2, Lambda, ECS, or EKS

**Constraints:** You MUST ask for all required parameters upfront in a single prompt.

**Note:** If the user doesn't know their VPC or subnet IDs, discover with `aws ec2 describe-vpcs` and `aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-ID`.

## Common Tasks

### 0. Verify Dependencies

- You MUST verify `aws` CLI is available and credentials are valid (`aws sts get-caller-identity`)
- You MUST ONLY check for tool existence and version — MUST NOT execute destructive or mutating commands during verification
- You MUST inform the user if any required tools are missing
- You MUST respect the user's decision to abort if tools are unavailable
- You SHOULD explain what each step does and why before executing it
- You SHOULD display write commands and wait for user confirmation before executing

### 1. Classify the Request

| User intent | Workflow |
|---|---|
| Quick setup with defaults | A: Quick Create |
| Custom configuration (throughput, lifecycle, KMS) | B: Custom Create |
| Mount on EC2 | [Mount on EC2](references/mount-on-ec2.md) |
| Mount on Lambda | C: Lambda Integration |
| Mount on ECS containers | D: ECS Integration |
| Mount on EKS pods | E: EKS Integration |
| Configure access points for isolation | F: Access Points |

### 2. Workflow A — Quick Create

```bash
aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode elastic \
  --encrypted \
  --tags Key=Name,Value=FILESYSTEM_NAME \
  --region REGION
```

**Constraints:**

- You MUST note the `FileSystemId` from the response
- You MUST warn: encryption and performance mode are IMMUTABLE after creation
- You MUST create security group and mount targets (next step)

### 3. Create Security Group and Mount Targets

> **Note:** If the user already has a security group allowing inbound TCP 2049, reuse it instead of creating a new one.

```bash
aws ec2 create-security-group --group-name efs-mount-target-sg \
  --description "EFS mount target - NFS access" --vpc-id vpc-VPC_ID --region REGION

aws ec2 authorize-security-group-ingress --group-id sg-MOUNT_TARGET_SG \
  --protocol tcp --port 2049 --source-group sg-COMPUTE_SG --region REGION
```

One mount target per AZ:

```bash
aws efs create-mount-target \
  --file-system-id fs-ID \
  --subnet-id subnet-SUBNET_ID \
  --security-groups sg-MOUNT_TARGET_SG \
  --region REGION
```

Wait for `LifeCycleState` to be `available`.

### 3a. Create File System Policy (Recommended)

Enforce IAM auth and TLS to prevent anonymous mounts:

```bash
aws efs put-file-system-policy --file-system-id fs-ID --policy '{
  "Version":"2012-10-17",
  "Statement":[{
    "Effect":"Allow",
    "Principal":{"AWS":"arn:aws:iam::ACCOUNT_ID:root"},
    "Action":["elasticfilesystem:ClientMount","elasticfilesystem:ClientWrite"],
    "Resource":"arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:file-system/fs-ID",
    "Condition":{
      "Bool":{"elasticfilesystem:AccessedViaMountTarget":"true","aws:SecureTransport":"true"}
    }
  }]
}'
```

> **Note:** After applying this policy, all mounts MUST use `-o tls,iam`. Mounts without IAM auth will be denied.

### 4. Workflow B — Custom Create

**Constraints:** You MUST ask about immutable settings upfront: encryption, performance mode, KMS key.

Throughput modes: **Elastic** (recommended, variable workloads), **Provisioned** (steady-state known throughput), **Bursting** (small, bursty).

Lifecycle policies and backup:

```bash
aws efs put-lifecycle-configuration --file-system-id fs-ID \
  --lifecycle-policies TransitionToIA=AFTER_30_DAYS TransitionToArchive=AFTER_90_DAYS TransitionToPrimaryStorageClass=AFTER_1_ACCESS

aws efs put-backup-policy --file-system-id fs-ID --backup-policy Status=ENABLED
```

### 5. Workflow C — Lambda Integration

See [Lambda integration guide](references/integrate-with-lambda.md).

**Constraints:**

- Lambda MUST be in the same VPC as EFS mount targets
- Lambda requires an EFS access point (cannot mount root directly)
- Lambda takes 2-3 minutes to go Active after adding VPC + EFS config

### 6. Workflow D — ECS Integration

See [ECS integration guide](references/integrate-with-ecs.md).

**Constraints:**

- MUST enable transit encryption and IAM authorization
- Fargate: MUST use platform version 1.4.0 or later
- Task SG MUST allow outbound TCP 2049 to mount target SG

### 7. Workflow E — EKS Integration

See [EKS integration guide](references/integrate-with-eks.md).

**Constraints:**

- Install EFS CSI driver via Helm
- volumeHandle format: `fs-ID::fsap-ID` (double colon separator)
- Node SG MUST allow outbound TCP 2049

### 8. Workflow F — Access Points

See [access points guide](references/configure-access-points.md).

Use access points for multi-tenant isolation or POSIX identity enforcement.

## Troubleshooting

### Cannot change encryption or performance mode after creation
Both immutable. Create a new file system and migrate with DataSync.

### Mount target creation fails
Subnet must be in same VPC. One mount target per AZ.

### Connection timed out
Security group on mount target must allow inbound TCP 2049 from compute SG.

## Cleanup

Delete in order: unmount → access points (if created) → mount targets → file system → security groups (if created) → IAM roles.

## Security Considerations

- Enable encryption at rest (`--encrypted`, immutable) and in transit (`-o tls` on every mount)
- Create a file system policy enforcing IAM auth and `aws:SecureTransport` — without one, any VPC client on port 2049 can mount anonymously
- Avoid `elasticfilesystem:*` wildcards in IAM policies
- Recommend enabling AWS Backup and CloudTrail data events for EFS

## Additional Resources

- [references/mount-on-ec2.md](references/mount-on-ec2.md) — Mounting EFS on EC2
- [references/integrate-with-lambda.md](references/integrate-with-lambda.md) — Lambda integration
- [references/integrate-with-ecs.md](references/integrate-with-ecs.md) — ECS integration
- [references/integrate-with-eks.md](references/integrate-with-eks.md) — EKS CSI driver integration
- [references/configure-access-points.md](references/configure-access-points.md) — Access point configuration
- [EFS User Guide](https://docs.aws.amazon.com/efs/latest/ug/whatisefs.html)
- [EFS Performance](https://docs.aws.amazon.com/efs/latest/ug/performance.html)
