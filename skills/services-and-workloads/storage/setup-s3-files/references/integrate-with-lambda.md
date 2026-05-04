# Integrating S3 Files with Lambda

Attach an S3 file system to a Lambda function for persistent, shared file storage with NFS access to S3 data.

## Prerequisites

- S3 file system with mount targets in `available` state
- Lambda function in the same VPC as the file system

## Steps

### 1. Create S3 Files Access Point

S3 Files access points use different parameter names than EFS:

```bash
aws s3files create-access-point \
  --file-system-id fs-FILESYSTEM_ID \
  --posix-user '{"uid":1000,"gid":1000}' \
  --root-directory '{"path":"/lambda","creationPermissions":{"ownerUid":1000,"ownerGid":1000,"permissions":"750"}}' \
  --region REGION
```

**Constraints:**

- You MUST use lowercase `uid/gid` and `creationPermissions` — S3 Files API differs from EFS (`Uid/Gid/CreationInfo`)
- You MUST use permissions `750` (not 755) for least-privilege
- Note the `AccessPointId` (format: `fsap-xxxxxxxx`)

### 2. Configure Lambda VPC

```bash
aws lambda update-function-configuration \
  --function-name FUNCTION_NAME \
  --vpc-config SubnetIds=subnet-1,subnet-2,SecurityGroupIds=sg-LAMBDA_SG
```

- Lambda SG MUST allow outbound TCP 2049 to mount target SG
- Mount target SG MUST allow inbound TCP 2049 from Lambda SG
- Subnets MUST have NAT gateway if the function calls other AWS services

### 3. Create Security Groups (if needed)

```bash
aws ec2 create-security-group --group-name s3files-lambda-sg \
  --description "Lambda SG for S3 Files access" --vpc-id vpc-ID --region REGION

aws ec2 authorize-security-group-egress --group-id sg-LAMBDA_SG \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":2049,"ToPort":2049,"UserIdGroupPairs":[{"GroupId":"sg-MOUNT_TARGET_SG"}]}]' --region REGION
```

### 4. Update Lambda Execution Role

```bash
# Scoped S3 Files permissions (production)
aws iam put-role-policy --role-name LAMBDA_ROLE_NAME \
  --policy-name S3FilesAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3files:ClientMount","s3files:ClientWrite"],"Resource":"arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID"}]}'

# VPC execution role (required for ENI creation)
aws iam attach-role-policy --role-name LAMBDA_ROLE_NAME \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole

# S3 read for intelligent routing (recommended)
aws iam put-role-policy --role-name LAMBDA_ROLE_NAME \
  --policy-name S3ReadForRouting \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":"arn:aws:s3:::BUCKET_NAME/*"},{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::BUCKET_NAME"}]}'
```

You MUST attach the first two policies (S3FilesAccess and VPC execution role). The third (S3ReadForRouting) is RECOMMENDED for intelligent read routing from the linked S3 bucket. For dev/test only: `AmazonS3FilesClientFullAccess` can replace the inline policy.

### 5. Attach S3 File System to Lambda

```bash
aws lambda update-function-configuration \
  --function-name FUNCTION_NAME \
  --file-system-configs Arn=arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID/access-point/fsap-ID,LocalMountPath=/mnt/s3files
```

**Constraints:**

- `LocalMountPath` MUST start with `/mnt/`
- You MUST use the S3 Files access point ARN format: `arn:aws:s3files:...:file-system/fs-ID/access-point/fsap-ID`
- Lambda takes 2-3 minutes to go from Pending to Active

## Cleanup

1. Remove file system: `aws lambda update-function-configuration --function-name NAME --file-system-configs []`
2. Delete access point: `aws s3files delete-access-point --access-point-id fsap-ID`

## Troubleshooting

- **Lambda stuck in Pending**: VPC + S3 Files ENI creation takes 2-3 min. Wait for `Active`.
- **Mount target not available**: S3 Files mount targets take 5–7 min. Verify state before attaching.
- **Permission denied on files**: Lambda role needs `s3files:ClientWrite`.
- **Intelligent read routing not working**: Lambda role needs `s3:GetObject` on the linked bucket.

## Security Considerations

- Use scoped inline policies (`s3files:ClientMount` on specific FS) — avoid FullAccess in production
- Use access points with restrictive POSIX permissions (750)
- Scope S3 read permissions to the specific linked bucket

## Additional Resources

- [S3 Files with Lambda](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-lambda.html)
