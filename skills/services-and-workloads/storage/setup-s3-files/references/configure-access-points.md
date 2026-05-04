# Configuring S3 Files Access Points

Access points are application-specific entry points that enforce POSIX user identity
and restrict access to specific directories. Use for multi-tenant isolation, Lambda
integration, or per-application directory scoping.

## Create an Access Point

S3 Files uses lowercase parameter names (different from EFS):

```bash
aws s3files create-access-point \
  --file-system-id fs-ID \
  --posix-user '{"uid":1000,"gid":1000}' \
  --root-directory '{"path":"/app-data","creationPermissions":{"ownerUid":1000,"ownerGid":1000,"permissions":"750"}}' \
  --tags Key=Name,Value=ACCESS_POINT_NAME \
  --region REGION
```

**Constraints:**

- You MUST use lowercase `uid/gid` and `creationPermissions` — S3 Files API differs from EFS (`Uid/Gid/CreationInfo`)
- You MUST specify `posixUser` to enforce identity on all operations
- You MUST specify `rootDirectory.path` to restrict access to a subdirectory
- You MUST include `creationPermissions` if the root directory doesn't exist yet

## Multi-Tenant Pattern

Create one access point per tenant/application:

```bash
# Tenant A
aws s3files create-access-point --file-system-id fs-ID \
  --posix-user '{"uid":1001,"gid":1001}' \
  --root-directory '{"path":"/tenants/a","creationPermissions":{"ownerUid":1001,"ownerGid":1001,"permissions":"750"}}'

# Tenant B
aws s3files create-access-point --file-system-id fs-ID \
  --posix-user '{"uid":1002,"gid":1002}' \
  --root-directory '{"path":"/tenants/b","creationPermissions":{"ownerUid":1002,"ownerGid":1002,"permissions":"750"}}'
```

Each tenant sees only their directory as root.

## IAM Condition for Access Point Enforcement

Add this statement to the existing file system resource policy's `Statement` array:

> **Constraints:** `put-file-system-policy` **replaces** the entire policy. You MUST merge this statement into the existing policy from SKILL.md step 2a — do NOT use it standalone or you will drop the base mount authorization.

```json
{
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME" },
  "Action": ["s3files:ClientMount", "s3files:ClientWrite"],
  "Resource": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID",
  "Condition": {
    "StringEquals": {
      "s3files:AccessPointArn": "arn:aws:s3files:REGION:ACCOUNT_ID:file-system/fs-ID/access-point/fsap-ID"
    }
  }
}
```

Note: S3 Files access point ARN format includes the file system ID: `arn:aws:s3files:...:file-system/fs-ID/access-point/fsap-ID`

## Mount with Access Point

```bash
sudo mount -t s3files -o accesspoint=fsap-ID fs-ID:/ /mnt/app
```

## Troubleshooting

- **Wrong permissions on root directory**: `creationPermissions` only applies when the directory is first created. Existing directories keep their permissions.
- **Wrong permissions on files**: Check `posixUser` `uid`/`gid` configuration — all file operations through the access point use this identity.
- **Cannot see files outside root**: By design — access points restrict view to the root directory path.
- **Lambda "invalid file system config"**: Lambda requires access point ARN, not file system ARN.

## Security Considerations

- Use IAM condition keys (`s3files:AccessPointArn`) in policies
- Set restrictive POSIX permissions (750 or 700) on root directories
- Each tenant should have a unique UID/GID to prevent cross-tenant access
