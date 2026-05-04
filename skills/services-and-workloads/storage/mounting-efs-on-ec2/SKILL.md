---
name: mounting-efs-on-ec2
description: Creates an encrypted Amazon EFS file system and mounts it on an EC2 instance using SSM Session Manager. Use when setting up shared NFS storage for EC2 workloads with encryption, security groups, and lifecycle management.
version: 1
metadata:
  service: [efs, ec2, iam, ssm, vpc]
  task: [deploy, configure]
  persona: [developer, devops]
  workload: [storage, networking]
---

# Mounting EFS on EC2

## Overview

Domain expertise for creating encrypted Amazon EFS file systems and mounting them on EC2 instances via SSM Session Manager. Covers VPC validation, IAM role creation, security group configuration, mount target setup, and NFS mount verification.

## Create and mount an EFS file system

To create an encrypted EFS file system and mount it on an EC2 instance, follow the procedure exactly.
See [EFS EC2 mount procedure](references/efs-ec2-mount.md).

## Troubleshooting

### VPC DNS issues

Verify both DNS hostnames and DNS support are enabled on the VPC — required for VPC endpoints.

### SSM agent not registering

For public subnets, check the instance has a public IP and HTTPS outbound is allowed. For private subnets, verify VPC endpoints for SSM are created and available. See the full procedure for detailed troubleshooting by subnet type.

### Mount failures

Ensure NFS utils are installed, the mount target is available, and the security group allows NFS traffic on port 2049.
