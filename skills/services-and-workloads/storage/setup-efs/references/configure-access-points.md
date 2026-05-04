# Configuring EFS Access Points

Access points are application-specific entry points that enforce POSIX user identity
and restrict access to specific directories. Use for multi-tenant isolation, Lambda
integration, or per-application directory scoping.

## Create an Access Point

```bash
aws efs create-access-point \
  --file-system-id fs-ID \
  --posix-user Uid=1000,Gid=1000 \
  --root-directory "Path=/app-data,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=750}" \
  --tags Key=Name,Value=ACCESS_POINT_NAME \
  --region REGION
```

**Constraints:**

- You MUST specify `PosixUser` to enforce identity on all operations
- You MUST specify `RootDirectory.Path` to restrict access to a subdirectory
- You MUST include `CreationInfo` if the root directory doesn't exist yet
- `Permissions` uses standard POSIX octal notation

## Multi-Tenant Pattern

Create one access point per tenant/application:

```bash
# Tenant A
aws efs create-access-point --file-system-id fs-ID \
  --posix-user Uid=1001,Gid=1001 \
  --root-directory "Path=/tenants/a,CreationInfo={OwnerUid=1001,OwnerGid=1001,Permissions=750}"

# Tenant B
aws efs create-access-point --file-system-id fs-ID \
  --posix-user Uid=1002,Gid=1002 \
  --root-directory "Path=/tenants/b,CreationInfo={OwnerUid=1002,OwnerGid=1002,Permissions=750}"
```

Each tenant sees only their directory as root.

## IAM Condition for Access Point Enforcement

Add this statement to the existing file system resource policy's `Statement` array:

> **Constraints:** `put-file-system-policy` **replaces** the entire policy. You MUST merge this statement into the existing policy from SKILL.md step 3a — do NOT use it standalone or you will drop the TLS and IAM enforcement conditions.

```json
{
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME" },
  "Action": ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"],
  "Resource": "arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:file-system/fs-ID",
  "Condition": {
    "StringEquals": {
      "elasticfilesystem:AccessPointArn": "arn:aws:elasticfilesystem:REGION:ACCOUNT_ID:access-point/fsap-ID"
    }
  }
}
```

## Mount with Access Point

```bash
# EFS
sudo mount -t efs -o tls,iam,accesspoint=fsap-ID fs-ID:/ /mnt/app
```

## Troubleshooting

- **Wrong permissions on root directory**: `CreationInfo` only applies when the directory is first created. Existing directories keep their permissions.
- **Wrong permissions on files**: Check `PosixUser` Uid/Gid configuration — all file operations through the access point use this identity.
- **Cannot see files outside root**: By design — access points restrict view to the root directory path.
- **Lambda "invalid file system config"**: Lambda requires access point ARN, not file system ARN.

## Security Considerations

- Use IAM condition keys (`elasticfilesystem:AccessPointArn`) in file system policies
- Set restrictive POSIX permissions (750 or 700) on root directories
- Each tenant should have a unique UID/GID to prevent cross-tenant access
