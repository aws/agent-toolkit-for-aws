# Integrating EFS with EKS

Mount an EFS file system as a persistent volume in EKS pods using the EFS CSI driver.

## Prerequisites

- EFS file system with mount targets in node subnets
- EFS CSI driver installed (via Helm or as an EKS managed add-on). Helm install requires the `helm` CLI.

## Install EFS CSI Driver

```bash
helm repo add aws-efs-csi-driver https://kubernetes-sigs.github.io/aws-efs-csi-driver/
helm install aws-efs-csi-driver aws-efs-csi-driver/aws-efs-csi-driver \
  --namespace kube-system \
  --version <PINNED_VERSION>
```

## StorageClass + PV + PVC

> **Note:** This YAML is inline — no canonical hosted version. Copy and customize for your cluster.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: efs-pv
spec:
  capacity: { storage: 5Gi }
  accessModes: [ReadWriteMany]
  storageClassName: efs-sc
  mountOptions:
    - tls
    - iam
  csi:
    driver: efs.csi.aws.com
    volumeHandle: fs-ID::fsap-ACCESS_POINT_ID
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: efs-pvc
spec:
  accessModes: [ReadWriteMany]
  storageClassName: efs-sc
  resources:
    requests: { storage: 5Gi }
```

## Mount in Pod

```yaml
spec:
  containers:
  - name: app
    volumeMounts:
    - name: efs-storage
      mountPath: /mnt/efs
  volumes:
  - name: efs-storage
    persistentVolumeClaim:
      claimName: efs-pvc
```

**Constraints:**

- volumeHandle format: `fs-ID::fsap-ID` (double colon separator)
- Node IAM role MUST have `elasticfilesystem:ClientMount`
- Node SG MUST allow outbound TCP 2049
- Mount target SG MUST allow inbound TCP 2049 from node SG

> **Note:** If pods call other AWS services, node subnets must have a NAT gateway or VPC endpoints.

## Troubleshooting

- **Pod stuck in ContainerCreating**: Check CSI driver installed, volumeHandle format, node SG.
- **Permission denied**: Check access point POSIX user config matches pod user.

## Security Considerations

- Node IAM role should use scoped `elasticfilesystem:ClientMount` — avoid FullAccess
- Use access points to enforce POSIX identity per pod

## Additional Resources

- [EKS + EFS CSI Driver](https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html)
