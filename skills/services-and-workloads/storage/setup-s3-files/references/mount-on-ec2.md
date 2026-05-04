# Mounting S3 Files on EC2

Mount an S3 file system on an EC2 instance using the S3 Files mount helper.

## Prerequisites

- S3 file system with mount targets in `available` state in the instance's AZ
- Security group on mount target allows inbound TCP 2049 from instance SG
- Instance has IAM role with `s3files:ClientMount` (and `s3files:ClientWrite` if read-write)

## Step 1: Install amazon-efs-utils

```bash
sudo yum -y install amazon-efs-utils   # AL2/AL2023
# Or for Ubuntu: sudo apt-get -y install amazon-efs-utils
```

> **Note:** Requires `amazon-efs-utils` ≥ 3.0.0 which includes the `mount.s3files` helper.

## Step 2: Mount

```bash
sudo mkdir -p /mnt/s3files
sudo mount -t s3files fs-FILESYSTEM_ID:/ /mnt/s3files
```

- S3 Files enforces TLS automatically on all connections — no `-o tls` flag needed
- Use `-o iam` for IAM-authenticated mounts when a file system policy is in place

To mount a specific access point:

```bash
sudo mount -t s3files -o iam,accesspoint=fsap-ACCESS_POINT_ID fs-FILESYSTEM_ID:/ /mnt/s3files
```

## Step 3: Verify

```bash
df -h /mnt/s3files
echo "test" | sudo tee /mnt/s3files/test.txt
cat /mnt/s3files/test.txt
```

## Step 4: Persist via /etc/fstab

```
fs-FILESYSTEM_ID:/ /mnt/s3files s3files _netdev 0 0
```

Test without rebooting:

```bash
sudo umount /mnt/s3files
sudo mount -a
df -h /mnt/s3files
```

## Troubleshooting

- **mount.s3files not found**: `amazon-efs-utils` not installed or < 3.0.0.
- **Connection timed out**: Mount target SG must allow inbound TCP 2049 from instance SG. Verify mount target exists in the instance's AZ.
- **Access denied with -o iam**: Instance IAM role missing `s3files:ClientMount`. Check with `aws sts get-caller-identity`.

## Security Considerations

- Use `-o iam` when the file system has a policy requiring IAM auth
- Avoid `AmazonS3FilesClientFullAccess` in production — scope to specific file system ARN
- Use access points to enforce POSIX identity per application
