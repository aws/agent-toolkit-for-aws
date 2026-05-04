# Integrating EFS with ECS

Mount an EFS file system as a persistent volume in ECS tasks. Enables shared storage across containers with encryption in transit and IAM authorization.

## Task IAM Role

```bash
aws iam put-role-policy --role-name TASK_ROLE \
  --policy-name EfsAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["elasticfilesystem:ClientMount","elasticfilesystem:ClientWrite"],"Resource":"arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:file-system/fs-ID"}]}'
```

For dev/test only: `AmazonElasticFileSystemClientReadWriteAccess` can replace the inline policy (grants access to ALL EFS file systems in the account — not appropriate for production).

## Security Group

- Task SG MUST allow outbound TCP 2049 to mount target SG
- Mount target SG MUST allow inbound TCP 2049 from task SG

```bash
aws ec2 authorize-security-group-egress --group-id sg-TASK_SG \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":2049,"ToPort":2049,"UserIdGroupPairs":[{"GroupId":"sg-MOUNT_TARGET_SG"}]}]' \
  --region REGION
```

> **Note:** If tasks call other AWS services, subnets must have a NAT gateway or VPC endpoints.

## Task Definition

Add EFS volume to task definition:

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
    "name": "efs-volume",
    "efsVolumeConfiguration": {
      "fileSystemId": "fs-ID",
      "transitEncryption": "ENABLED",
      "authorizationConfig": {
        "accessPointId": "fsap-ACCESS_POINT_ID",
        "iam": "ENABLED"
      }
    }
  }],
  "containerDefinitions": [{
    "name": "app",
    "image": "IMAGE",
    "mountPoints": [{
      "sourceVolume": "efs-volume",
      "containerPath": "/mnt/efs"
    }]
  }]
}
```

**Constraints:**

- You MUST enable transit encryption and IAM authorization
- Task role MUST have `elasticfilesystem:ClientMount` and `ClientWrite`
- Fargate: MUST use platform version 1.4.0 or later
- Task SG MUST allow outbound TCP 2049 to mount target SG

**Note:** If using `awslogs-create-group: true`, the execution role needs `logs:CreateLogGroup` which is NOT in `AmazonECSTaskExecutionRolePolicy`. Pre-create the log group or add the permission.

## Troubleshooting

- **ECS task fails to start**: Check SGs, mount target availability, IAM, platform version (Fargate ≥ 1.4.0).
- **Permission denied in container**: Check access point POSIX user config matches container user.

## Security Considerations

- Always enable transit encryption and IAM authorization in task definitions
- Use scoped task role policies — avoid FullAccess in production

## Additional Resources

- [ECS + EFS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/efs-volumes.html)
