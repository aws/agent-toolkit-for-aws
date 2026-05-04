# Mounting EFS on EC2

Mount an EFS file system on an EC2 instance using the EFS mount helper with TLS and IAM authorization.

## Prerequisites

- EFS file system with mount targets in `available` state in the instance's AZ
- Security group on mount target allows inbound TCP 2049 from instance SG
- Instance has IAM role with `elasticfilesystem:ClientMount` (and `ClientWrite` if read-write)

## Step 1: Install amazon-efs-utils

```bash
sudo yum -y install amazon-efs-utils   # AL2/AL2023
# Or for Ubuntu: sudo apt-get -y install amazon-efs-utils
```

> **Note:** `amazon-efs-utils` provides the `mount.efs` helper which handles TLS, IAM auth, and connection watchdog. Do NOT use raw `mount -t nfs4` — it lacks encryption in transit.

## Step 2: Mount with TLS and IAM Auth

```bash
sudo mkdir -p /mnt/efs
sudo mount -t efs -o tls,iam fs-FILESYSTEM_ID:/ /mnt/efs
```

- `-o tls` — encrypts data in transit via stunnel
- `-o iam` — uses the instance's IAM role for authorization (required when file system policy enforces IAM)

To mount a specific access point:

```bash
sudo mount -t efs -o tls,iam,accesspoint=fsap-ACCESS_POINT_ID fs-FILESYSTEM_ID:/ /mnt/efs
```

## Step 3: Verify

```bash
df -h /mnt/efs
echo "test" | sudo tee /mnt/efs/test.txt
cat /mnt/efs/test.txt
```

## Step 4: Persist via /etc/fstab

```
fs-FILESYSTEM_ID:/ /mnt/efs efs _netdev,tls,iam 0 0
```

Test without rebooting:

```bash
sudo umount /mnt/efs
sudo mount -a
df -h /mnt/efs
```

## Troubleshooting

- **Connection timed out**: Mount target SG must allow inbound TCP 2049 from instance SG. Verify mount target exists in the instance's AZ.
- **mount.efs not found**: `amazon-efs-utils` not installed. Do NOT fall back to `mount -t nfs4`.
- **Access denied with -o iam**: Instance IAM role missing `elasticfilesystem:ClientMount`. Check with `aws sts get-caller-identity`.
- **Stunnel errors**: Ensure `stunnel5` is installed (included with `amazon-efs-utils` on AL2/AL2023).

## Security Considerations

- ALWAYS use `-o tls` for encryption in transit
- ALWAYS use `-o iam` when the file system has a policy requiring IAM auth
- Avoid mounting as root without access points — use access points to enforce POSIX identity
