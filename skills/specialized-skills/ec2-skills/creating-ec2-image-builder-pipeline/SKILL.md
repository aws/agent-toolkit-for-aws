---
name: creating-ec2-image-builder-pipeline
description: Creates a complete EC2 Image Builder pipeline that builds a custom AMI with pre-installed software, distributes it to target regions, executes the pipeline, and creates a launch template. Use when setting up automated AMI creation with IAM roles, build components, image recipes, and infrastructure configuration.
version: 1
metadata:
  service: [ec2, imagebuilder, iam]
  task: [create, deploy, configure]
  persona: [developer, devops]
  workload: [compute]
---

# Creating an EC2 Image Builder Pipeline

## Overview

Domain expertise for creating and managing EC2 Image Builder pipelines that automate
custom AMI creation. Covers the full lifecycle: IAM role setup, build component
definition, image recipe creation, infrastructure and distribution configuration,
pipeline execution, and launch template creation.

## Create an Image Builder pipeline

To create a complete EC2 Image Builder pipeline with custom AMI builds and
cross-region distribution, follow the procedure exactly.
See [EC2 Image Builder pipeline procedure](references/ec2-image-builder-pipeline.md).

## Troubleshooting

### InvalidParameterValueException on pipeline operations
Use the exact ARN returned by API calls — do not construct ARNs manually. Pipeline
ARNs must follow `arn:<partition>:imagebuilder:<region>:<account>:image-pipeline/<name>`.

### InstanceProfileNotFoundException
Wait 10–15 seconds after creating the instance profile before using it. IAM changes
are eventually consistent.

### ResourceAlreadyExistsException
Delete the existing resource first or use a different name/version.

### Build instance fails to launch
Verify the instance profile exists, all three IAM policies are attached, and the
instance type is available in the region.
