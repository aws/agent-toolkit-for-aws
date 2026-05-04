# Integrating EFS with Lambda

Attach an EFS file system to a Lambda function for persistent, shared file storage across invocations.

## Prerequisites

- EFS file system with mount targets in at least one AZ
- Lambda function in the same VPC as EFS mount targets
- EFS access point (required — Lambda cannot mount root directly)

## Steps

### 1. Create Access Point

```bash
aws efs create-access-point \
  --file-system-id fs-ID \
  --posix-user Uid=1000,Gid=1000 \
  --root-directory "Path=/lambda,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=750}" \
  --region REGION
```

Note the `AccessPointId` (format: `fsap-XXXXXXXXX`).

### 2. Configure Lambda VPC

```bash
aws lambda update-function-configuration \
  --function-name FUNCTION_NAME \
  --vpc-config SubnetIds=subnet-1,subnet-2,SecurityGroupIds=sg-LAMBDA_SG
```

- Lambda SG MUST allow outbound TCP 2049 to mount target SG
- Mount target SG MUST allow inbound TCP 2049 from Lambda SG
- Subnets MUST have NAT gateway if the function calls other AWS services

### 3. Update Lambda Execution Role

```bash
# Scoped EFS permissions (production)
aws iam put-role-policy --role-name LAMBDA_ROLE_NAME \
  --policy-name EfsAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["elasticfilesystem:ClientMount","elasticfilesystem:ClientWrite"],"Resource":"arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:file-system/fs-ID"}]}'

# VPC execution role (required for ENI creation)
aws iam attach-role-policy --role-name LAMBDA_ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole
```

You MUST attach both policies. For dev/test: `AmazonElasticFileSystemClientReadWriteAccess` can replace the inline policy (grants access to ALL file systems).

### 4. Attach EFS to Lambda

```bash
aws lambda update-function-configuration \
  --function-name FUNCTION_NAME \
  --file-system-configs Arn=arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:access-point/fsap-ACCESS_POINT_ID,LocalMountPath=/mnt/efs
```

**Constraints:**

- `LocalMountPath` MUST start with `/mnt/`
- You MUST use the access point ARN, not the file system ARN
- Lambda takes 2-3 minutes to go from Pending to Active

## Cleanup

1. Remove EFS: `aws lambda update-function-configuration --function-name NAME --file-system-configs []`
2. Delete access point: `aws efs delete-access-point --access-point-id fsap-ID`

## Troubleshooting

- **Lambda stuck in Pending**: VPC + EFS ENI creation takes 2-3 min. Wait for `Active`.
- **Permission denied writing to /mnt/efs**: Check access point POSIX user matches Lambda runtime (UID 1000). Verify role has `elasticfilesystem:ClientWrite`.
- **Cold start latency**: EFS mount adds latency. Use provisioned concurrency for latency-sensitive functions.

## Security Considerations

- Use scoped inline policies (`elasticfilesystem:ClientMount` on specific FS) — avoid FullAccess in production
- Use access points with restrictive POSIX permissions (750) to limit directory access

## Additional Resources

- [Using EFS with Lambda](https://docs.aws.amazon.com/lambda/latest/dg/configuration-filesystem.html)
