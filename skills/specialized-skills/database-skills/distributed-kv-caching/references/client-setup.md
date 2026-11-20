# GPU Server Prerequisites and Setup

## Table of contents

- Overview
- Instance type requirements
- EFA driver stack
- Memlock limits
- Security group
- Same-AZ placement
- Instance role permission for the cache secret
- Verify EFA readiness

## Overview

The GPU server runs vLLM or SGLang and the LMCache MP server. Requirements depend on the transport ([SKILL.md](SKILL.md#transports)):

- **`rdma`:** EFA hardware with RDMA write, the EFA driver stack, unlimited memlock for the LMCache service, and the cache security group on every interface. Every section applies.
- **`tcp` and `blob-tcp`:** no EFA. The server needs a route to the cluster endpoint on port 6379, the cache security group, TLS (`tls_enable: true`), and the same Availability Zone (required, see [Same-AZ placement](#same-az-placement)). Skip the EFA sections.

Commands use the full path `/opt/amazon/efa/bin` (a non-login shell can lack it in `PATH`), and the variables of [elasticache-setup.md](references/elasticache-setup.md#shell-setup-and-helpers).

## Instance type requirements

For `rdma`, the instance type MUST support **RDMA write**: see the RDMA write column of the [EFA supported instance types table](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa.html#efa-instance-types). On a running instance, the `fi_info` checks in [Verify EFA readiness](#verify-efa-readiness) are the authority. Before launch, check EFA support and the number of EFA interfaces:

```bash
aws ec2 describe-instance-types --region <region> --instance-types <instance-type> \
    --query 'InstanceTypes[0].NetworkInfo.[EfaSupported,EfaInfo.MaximumEfaInterfaces]'
```

## EFA driver stack

The `rdma` transport needs libfabric 2.4 or later (valkey-glide-sync requires it). GPU AMIs such as the Deep Learning AMIs usually have the EFA software. Check first; skip the install when checks 1 to 3 in [Verify EFA readiness](#verify-efa-readiness) pass (`cat /opt/amazon/efa_installed_packages` shows the installer version).

To install or upgrade, follow the [EFA installation steps](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-enable). Use the latest version number from the [EFA release notes](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-changelog.html), not the `latest` tarball, so that every server gets the same version.

- **Source.** Stage `aws-efa-installer-<version>.tar.gz`, its `.sig` file, and `aws-efa-installer.key` in S3 (through an S3 gateway endpoint) or a private mirror (network isolation rule in [SKILL.md](SKILL.md#security-considerations)).
- **Verify.** Check the GPG signature of the tarball as the EFA guide shows, and pass `--check-signatures`. Stop if a check fails.
- **Approval.** The installer can replace the kernel module and libfabric under running jobs: on a serving server, get approval and drain it first.
- **Reboot.** If the installer asks for a reboot, reboot before you continue. Else log out and in again.

```bash
tar -xf aws-efa-installer-<version>.tar.gz && cd aws-efa-installer
export EFA_INSTALLER_KEY=<path>/aws-efa-installer.key
sudo -E ./efa_installer.sh -y --check-signatures
```

## Memlock limits

EFA registers memory regions with the NIC, so the LMCache process MUST have an unlimited memlock limit. If it does not, registration fails with `fi_mr_reg: Cannot allocate memory`.

- **systemd service (recommended).** `LimitMEMLOCK=infinity` in the [unit](references/lmcache-setup.md#systemd-unit). `limits.conf` and `ulimit -l` in an agent shell do not show or set it.
- **Interactive test.** Give the limit to the LMCache user only, in `/etc/security/limits.d/90-lmcache.conf`: `lmcache - memlock unlimited`. Log in again. Do not give it to every user (`*`).
- **Containers.** Set it in the runtime (a `ulimit` inside cannot raise it). Docker: `--ulimit memlock=-1:-1 --device /dev/infiniband/uverbs<N>` per EFA device. Amazon EKS: the EFA device plugin and a node AMI whose runtime sets `LimitMEMLOCK=infinity`. Check `grep 'Max locked memory' /proc/<pid>/limits`.

Registered-memory and hugepage rules: [lmcache-setup.md](references/lmcache-setup.md#registered-memory-and-hugepages).

## Security group

Attach the self-referencing group from [elasticache-setup.md](references/elasticache-setup.md#security-group) to the **primary interface** (device index 0, which carries the TLS connection to port 6379) and to every `efa` and `efa-only` interface. Without it, `BLOB.RDMA_HELLO` succeeds but the first RDMA transfer fails ([troubleshooting.md](references/troubleshooting.md#rdma-transfer-fails-after-successful-hello)).

`modify-network-interface-attribute --groups` replaces the whole list, and interfaces differ. Per interface: read its groups, add `$SG_ID` only if missing, show old and new lists, and get approval (at most 5 groups by default). Keep the old lists for teardown.

```bash
for ENI_ID in $(aws ec2 describe-instances --region $AWS_REGION --instance-ids <gpu-instance-id> \
    --query 'Reservations[0].Instances[0].NetworkInterfaces[*].NetworkInterfaceId' --output text); do
  OLD=$(aws ec2 describe-network-interfaces --region $AWS_REGION --network-interface-ids $ENI_ID \
        --query 'NetworkInterfaces[0].Groups[].GroupId' --output text | tr '\t' ' ')
  case " $OLD " in *" $SG_ID "*) echo "$ENI_ID: already has $SG_ID"; continue ;; esac
  echo "$ENI_ID: old [$OLD] new [$OLD $SG_ID]"
  # After the builder approves this interface:
  # aws ec2 modify-network-interface-attribute --region $AWS_REGION \
  #     --network-interface-id $ENI_ID --groups $OLD $SG_ID
done
```

At launch: `run-instances --security-group-ids $SG_ID --subnet-id $SUBNET_AZ`, or the group on each interface in `--network-interfaces`.

## Same-AZ placement

The GPU servers, the LMCache servers, and the cluster MUST be in the same Availability Zone and subnet (rule in [SKILL.md](SKILL.md#rules)). On `tcp` and `blob-tcp`, another Availability Zone adds a cross-AZ round trip to each L2 operation. Both commands MUST return the same Availability Zone, and the instance subnet MUST be in the cache subnet group:

```bash
CLUSTER_AZS=$(aws elasticache describe-replication-groups --region $AWS_REGION --replication-group-id $CLUSTER_NAME \
    --query 'ReplicationGroups[0].NodeGroups[].NodeGroupMembers[].PreferredAvailabilityZone' \
    --output text | tr '\t' '\n' | sort -u)
[ -n "$CLUSTER_AZS" ] && [ "$(echo "$CLUSTER_AZS" | wc -l)" -eq 1 ] || echo "STOP: cluster AZs empty or multi: $CLUSTER_AZS"
echo "Cluster AZ: $CLUSTER_AZS"
aws ec2 describe-instances --region $AWS_REGION --instance-ids <gpu-instance-id> \
    --query 'Reservations[0].Instances[0].[Placement.AvailabilityZone,SubnetId]'
```

## Instance role permission for the cache secret

The GPU servers' instance role reads only the cache secret. This changes IAM: show the policy to the builder and get approval first. A customer managed key (`KMS_KEY` not `None` and not the `aws/secretsmanager` alias) also needs `kms:Decrypt` on the key ARN through Secrets Manager; without it, the launcher cannot read the secret and LMCache does not start. If the key policy does not allow IAM policies, also add the role to the key policy.

```bash
read SECRET_ARN KMS_KEY < <(aws secretsmanager describe-secret --region $AWS_REGION \
  --secret-id "$SECRET_ID" --query '[ARN,KmsKeyId]' --output text); test -n "$SECRET_ARN" || echo "STOP: no secret"
case "$KMS_KEY" in None|*alias/aws/secretsmanager) KEY_ARN= ;;
  *) KEY_ARN=$(aws kms describe-key --region $AWS_REGION --key-id "$KMS_KEY" --query KeyMetadata.Arn \
       --output text) || echo "STOP: cannot resolve $KMS_KEY" ;; esac
POLICY=$(jq -n --arg s "$SECRET_ARN" --arg k "$KEY_ARN" --arg v "secretsmanager.$AWS_REGION.amazonaws.com" \
  '{Version:"2012-10-17",Statement:([{Effect:"Allow",Action:"secretsmanager:GetSecretValue",Resource:$s}]
    + (if $k == "" then [] else [{Effect:"Allow",Action:"kms:Decrypt",Resource:$k,
         Condition:{StringEquals:{"kms:ViaService":$v}}}] end))}')
echo "$POLICY"
# After the builder approves this policy:
# aws iam put-role-policy --region $AWS_REGION --role-name <gpu-instance-role> \
#   --policy-name ${CLUSTER_NAME}-read-secret --policy-document "$POLICY"
```

## Verify EFA readiness

This section is the one home for the EFA checks. Run them on the GPU server before you start LMCache with `rdma`, and record `max_mr_size`, the device names, and the NUMA node of each device: they set `num_workers`, `rdma_interface`, and the hugepage node ([lmcache-setup.md](references/lmcache-setup.md#registered-memory-and-hugepages)).

```bash
# 1. libfabric 2.4 or later
/opt/amazon/efa/bin/fi_info --version
# 2. MUST list "fabric: efa-direct" with one domain line per EFA device.
#    efa-direct is a fabric under the efa provider, so query with -p efa.
/opt/amazon/efa/bin/fi_info -p efa -f efa-direct
# 3. RDMA write. -c keeps only interfaces with all listed capabilities (fi_info without -v
#    prints no capabilities). "No data available" or empty output: no rdma on this instance.
/opt/amazon/efa/bin/fi_info -p efa -f efa-direct -c 'FI_RMA|FI_WRITE'
# 4. Devices: count MUST equal the efa and efa-only interfaces; max_mr_size and NUMA node per device.
ibv_devinfo -v | grep -E 'hca_id|max_mr_size'
for d in /sys/class/infiniband/*; do echo "$(basename $d) numa_node=$(cat $d/device/numa_node)"; done
# 5. Self-referencing ingress and egress rules (missing egress is the most frequent RDMA failure)
for p in IpPermissions IpPermissionsEgress; do aws ec2 describe-security-groups --region $AWS_REGION \
  --group-ids $SG_ID --query "SecurityGroups[0].$p[?UserIdGroupPairs[?GroupId=='$SG_ID']]"; done
# 6. Same Availability Zone and subnet (see Same-AZ placement)
# 7. valkey-glide RDMA: the glide check in lmcache-setup.md, "Software requirements" (True True)
# 8. After LMCache starts: unlimited memlock for the service
systemctl show lmcache -p LimitMEMLOCK                                                # MUST be infinity
grep 'Max locked memory' /proc/$(systemctl show -p MainPID --value lmcache)/limits    # MUST be unlimited
```

A failure of valkey-glide-sync, libfabric, or registration stops LMCache at start with a message. A missing group rule or another Availability Zone does not: the first RDMA transfer fails.
