# Integrating S3 Files with ECS

Mount an S3 file system as a persistent volume in ECS tasks on Fargate or Managed Instances.

## Prerequisites

- S3 file system with mount targets in `available` state
- ECS cluster (Fargate or Managed Instances — EC2 launch type NOT supported)

## Security Group

- Task SG MUST allow outbound TCP 2049 to mount target SG
- Mount target SG MUST allow inbound TCP 2049 from task SG

```bash
aws ec2 authorize-security-group-egress --group-id sg-TASK_SG \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":2049,"ToPort":2049,"UserIdGroupPairs":[{"GroupId":"sg-MOUNT_TARGET_SG"}]}]' \
  --region REGION
```

## Task Definition

S3 Files uses `s3filesVolumeConfiguration` — NOT `efsVolumeConfiguration`:

```json
{
  "family": "TASK_FAMILY",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::ACCOUNT_ID:role/EXECUTION_ROLE",
  "taskRoleArn": "arn:aws:iam::ACCOUNT_ID:role/TASK_ROLE",
  "volumes": [{
    "name": "s3files-vol",
    "s3filesVolumeConfiguration": {
      "fileSystemArn": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID",
      "accessPointArn": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID/access-point/fsap-ID"
    }
  }],
  "containerDefinitions": [{
    "name": "app",
    "image": "IMAGE",
    "essential": true,
    "mountPoints": [{
      "sourceVolume": "s3files-vol",
      "containerPath": "/mnt/s3files"
    }]
  }]
}
```

**Constraints:**

- You MUST use `s3filesVolumeConfiguration`, NOT `efsVolumeConfiguration`
- You MUST use `fileSystemArn` (full ARN), NOT `fileSystemId`
- Transit encryption is mandatory and always on — no opt-out
- Task IAM Role is mandatory — no opt-out

**Note:** If using `awslogs-create-group: true`, the execution role needs `logs:CreateLogGroup` which is NOT in `AmazonECSTaskExecutionRolePolicy`. Pre-create the log group or add the permission.

## Task IAM Role

```bash
# Scoped S3 Files permissions (production)
aws iam put-role-policy --role-name TASK_ROLE \
  --policy-name S3FilesAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3files:ClientMount","s3files:ClientWrite"],"Resource":"arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID"}]}'

# S3 object read for intelligent routing
aws iam put-role-policy --role-name TASK_ROLE \
  --policy-name S3ReadForRouting \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":"arn:aws:s3:::BUCKET_NAME/*"},{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::BUCKET_NAME"}]}'
```

For dev/test only: `AmazonS3FilesClientFullAccess` can replace the inline policy.

## Register and Run

```bash
aws ecs register-task-definition --cli-input-json "$(cat task-def.json)"
aws ecs run-task --cluster CLUSTER --launch-type FARGATE \
  --task-definition TASK_FAMILY \
  --network-configuration '{"awsvpcConfiguration":{"subnets":["subnet-ID"],"securityGroups":["sg-ID"],"assignPublicIp":"DISABLED"}}'
```

> **Note:** Tasks in private subnets need a NAT gateway or VPC endpoints for outbound access. Use `ENABLED` only in public subnets for dev/test.

## Troubleshooting

- **ResourceInitializationError DNS resolution**: Used `efsVolumeConfiguration` instead of `s3filesVolumeConfiguration`.
- **Mount target not available**: S3 Files mount targets take 5–7 min. Verify state.
- **Permission denied in container**: Task role needs `s3files:ClientWrite`.
- **EC2 launch type fails**: Not supported — use Fargate or Managed Instances only.

## Security Considerations

- Use scoped task role policies (`s3files:ClientMount` on specific FS) — avoid FullAccess in production
- Use access points to enforce POSIX identity per container
- Task SG should restrict outbound to mount target SG on TCP 2049

## Additional Resources

- [S3 Files with ECS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-ecs.html)
