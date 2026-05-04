# Integrating S3 Files with EKS

Mount an S3 file system as a persistent volume in EKS pods using the EFS CSI driver (≥ 3.0.0).

## Prerequisites

- S3 file system with mount targets in `available` state
- EKS cluster with EFS CSI driver ≥ 3.0.0. Helm install requires the `helm` CLI.
- NOT supported on EKS Fargate

## IAM Roles

Two IAM roles required:

- **Controller role**: Attach `AmazonS3FilesCSIDriverPolicy`
- **Node role**: Attach `AmazonS3ReadOnlyAccess` + `AmazonElasticFileSystemsUtils` (dev/test — for production, scope S3 read to specific bucket)

Use Pod Identities or IRSA for authentication.

## Install EFS CSI Driver

```bash
helm repo add aws-efs-csi-driver https://kubernetes-sigs.github.io/aws-efs-csi-driver/
helm install aws-efs-csi-driver aws-efs-csi-driver/aws-efs-csi-driver \
  --namespace kube-system \
  --version <PINNED_VERSION> \
  --set controller.serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=CONTROLLER_ROLE_ARN
```

## StorageClass + PV + PVC

> **Note:** This YAML is inline — no canonical hosted version. Copy and customize for your cluster.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: s3files-sc
provisioner: efs.csi.aws.com
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: s3files-pv
spec:
  capacity: { storage: 5Gi }
  accessModes: [ReadWriteMany]
  storageClassName: s3files-sc
  csi:
    driver: efs.csi.aws.com
    volumeHandle: fs-ID::fsap-ACCESS_POINT_ID
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3files-pvc
spec:
  accessModes: [ReadWriteMany]
  storageClassName: s3files-sc
  resources:
    requests: { storage: 5Gi }
```

## Mount in Pod

```yaml
spec:
  containers:
  - name: app
    volumeMounts:
    - name: s3files-storage
      mountPath: /mnt/s3files
  volumes:
  - name: s3files-storage
    persistentVolumeClaim:
      claimName: s3files-pvc
```

**Constraints:**

- volumeHandle format: `fs-ID::fsap-ID` (double colon separator)
- Node SG MUST allow outbound TCP 2049 to mount target SG
- Mount target SG MUST allow inbound TCP 2049 from node SG

> **Note:** If pods call other AWS services, node subnets must have a NAT gateway or VPC endpoints.

## Troubleshooting

- **Pod stuck in ContainerCreating**: Check CSI driver installed, volumeHandle format, node SG.
- **EKS Fargate**: NOT supported for S3 Files.

## Additional Resources

- [S3 Files EKS CSI Driver](https://docs.aws.amazon.com/eks/latest/userguide/s3files-csi.html)

## Security Considerations

- Node IAM role should use scoped `s3files:ClientMount` — avoid FullAccess
- Use access points to enforce POSIX identity per pod
