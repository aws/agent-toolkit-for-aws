# EC2 Provisioning

## Overview
Defining reusable instance configuration with launch templates, plus user data, key pairs/SSH access, IMDSv2, placement groups, and Elastic IPs.

## Launch templates (use these, not launch configurations)
A launch template captures AMI, instance type, network interfaces, user data, security groups, instance profile, block device mappings, metadata options, and tags — versioned and reusable by Auto Scaling groups, Spot fleets, and one-off launches.

**Launch configurations are deprecated:** they do not support current EC2 instance types, and new accounts cannot create them — see the [AWS launch-configurations docs](https://docs.aws.amazon.com/autoscaling/ec2/userguide/launch-configurations.html). Always use launch templates.

```bash
aws ec2 create-launch-template \
  --launch-template-name my-app \
  --version-description v1 \
  --launch-template-data '{
    "ImageId": "ami-xxxxxxxx",
    "InstanceType": "m7g.large",
    "IamInstanceProfile": {"Name": "my-app-instance-profile"},
    "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 2},
    "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"Encrypted": true}}],
    "Monitoring": {"Enabled": true},
    "TagSpecifications": [{"ResourceType":"instance","Tags":[{"Key":"managed_by","Value":"aws-skills"},{"Key":"skill","Value":"aws-compute"}]}]
  }'
```

Before hardcoding an instance type like `m7g.large` in production, verify it is current-generation for the target Region: `aws ec2 describe-instance-types --filters Name=current-generation,Values=true --query 'InstanceTypes[].InstanceType'`. The `current-generation` filter (values `true`|`false`) returns whether a type is the latest generation of its instance family, and filter names/values are case-sensitive. Note the command is Region-scoped, so a type may be current-generation but not offered in every Region — cross-check availability with `aws ec2 describe-instance-type-offerings --location-type region --filters Name=instance-type,Values=m7g.large`.

`"Monitoring": {"Enabled": true}` turns on detailed (1-minute) CloudWatch metrics — a production-ready default that also improves ASG scaling responsiveness (omit it only to save cost on non-critical fleets, which falls back to 5-minute metrics).

When the template sets `SecurityGroupIds`, scope those rules to least privilege — reference another security group for internal/tier-to-tier access, or a specific CIDR for known callers, rather than `0.0.0.0/0` (justify any open ingress). Instances inherit these rules at launch, so an over-permissive template propagates to the whole fleet.

**Versioning:** reference a version by number, `$Latest`, or `$Default` (the unspecified default is `$Default`). For instance refresh and rollback, **pin a numeric version** — rollback is unsupported when the ASG uses `$Latest`/`$Default` or an SSM-parameter AMI. Create a new version with `create-launch-template-version`; changing a template does not touch running instances (do an instance refresh — see [auto-scaling.md](auto-scaling.md)).

## IMDSv2
IMDSv2 requires a session token (PUT to `/latest/api/token`, then the token in each metadata GET), defeating SSRF credential theft. Enforce it:

- **`HttpTokens=required` is what enforces IMDSv2** — it blocks IMDSv1 (a tokenless/invalid-token GET then returns `401 Unauthorized`); also set `HttpEndpoint=enabled`.
- **`HttpPutResponseHopLimit` defaults to 1 (range 1–64) and does NOT enforce IMDSv2. Set it to 2 for containers on EC2** — the default hop limit of 1 makes the IMDSv2 token PUT response fail to reach a containerized process (the extra hop exceeds the response TTL), so the token request times out; the extra hop covers container → bridge → IMDS. (If IMDSv2 is *required*, a subsequent tokenless GET returns 401; if optional, it silently falls back to IMDSv1. Host-networked containers are unaffected.)
- Account-level (per Region) default: `aws ec2 modify-instance-metadata-defaults --http-tokens required --http-put-response-hop-limit 2` (org-wide enforcement is a separate Organizations declarative policy). **Applies only to new launches** — existing instances are unchanged; fix each with `modify-instance-metadata-options`. Launch-time settings override the account default.

## User data
Bootstrap scripts run by cloud-init (Linux) / EC2Launch (Windows). **Runs once at first boot by default.** On Linux, cloud-init runs user data as root; for every-boot, use a cloud-init `#cloud-config` with `[scripts-user, always]` (these are Linux-specific — Windows uses EC2Launch v2, which runs as Local System and re-runs with `frequency: always`). Shell scripts start with `#!`; 16 KB limit before base64 (gzip to fit). Output goes to `/var/log/cloud-init-output.log` — check it when bootstrap "didn't run."

**Never put secrets in user data.** It is stored unencrypted, is readable via IMDS by any process on the instance (`http://169.254.169.254/latest/user-data`), is echoed to `/var/log/cloud-init-output.log`, and appears in the `requestParameters` of the `RunInstances` CloudTrail event. Fetch secrets at boot from AWS Secrets Manager or SSM Parameter Store (SecureString) using the instance-profile role.

## Key pairs and SSH access

- Types: RSA (Linux + Windows) or ED25519 (**Linux only**). `chmod 400 key.pem`.
- Default users by AMI: `ec2-user` (Amazon Linux/RHEL/SUSE), `ubuntu` (Ubuntu), `admin` (Debian), `centos` (CentOS), `bitnami` (Bitnami); RHEL/SUSE also accept `root`. For other AMIs the default is typically `ec2-user` — confirm with the AMI provider rather than assuming `root`.
- **EC2 Instance Connect** pushes a temporary key valid **60 seconds** (`aws ec2-instance-connect send-ssh-public-key …`) — connect immediately or you get `Permission denied (publickey)`.
- Prefer **Session Manager** (no keys, no open port 22) — see [systems-manager.md](systems-manager.md).
- Lost key: create a new key pair and reattach the public key via Instance Connect, Session Manager, or by editing `authorized_keys` on the detached root volume.

## Placement groups

| Strategy | Placement | Limit | Use for |
|----------|-----------|-------|---------|
| Cluster | Packed in one AZ, high bandwidth | Capacity risk if grown incrementally | Tightly coupled HPC/low-latency |
| Spread | Distinct hardware (one instance per rack) | **Max 7 running instances per AZ per group** | Small set of critical instances |
| Partition | Isolated racks per partition | **Max 7 partitions per AZ** (instances per partition limited only by account limits) | HDFS/HBase/Cassandra/Kafka |

Cluster: launch all instances of the **same type in one request**; on `InsufficientInstanceCapacity`, stop/start all group members to re-place them. Reference a shared placement group by ID (not name) in the CLI. The spread and partition per-AZ maximums above are firm documented hard limits (not raisable Service Quota defaults) and apply even for shared placement groups.

## Elastic IPs

- **All public IPv4 is billed per hour** — including idle Elastic IPs and EIPs on stopped instances (check current rates on the EC2 pricing page or via `aws pricing get-products`). Release unused ones: `aws ec2 release-address --allocation-id <id>` (EIPs keep billing after the instance is terminated until released). The per-Region EIP quota is low by default (check the current value with `aws service-quotas get-service-quota --service-code ec2 --quota-code L-0263D0A3`).
- An auto-assigned public IP **changes on stop/start**; attach an Elastic IP for a stable address (common cause of "SSH broke after restart").
- Remap on failover by disassociating/reassociating the EIP (no release needed).

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Container gets `401` from IMDS, host works | Hop limit 1 | Set `HttpPutResponseHopLimit=2` |
| Account IMDSv2 default didn't affect existing instances | Default is new-launch + per-Region only | `modify-instance-metadata-options` per instance |
| `Permission denied (publickey)` | Wrong user/key/permissions, or Instance Connect key expired (60s) | Correct username, `chmod 400`, re-run send-ssh-public-key |
| SSH broke after stop/start | Public IP changed | Attach an Elastic IP or use the new IP / DNS name |
| Charged for an unattached Elastic IP | Public IPv4 billed even when idle | Release it |

## Security Considerations

- **Enforce IMDSv2** in the launch template (`HttpTokens=required`, and hop limit 2 for containers) to block SSRF-based credential theft.
- **Never embed secrets in user data** — it's stored unencrypted, readable via IMDS, logged to cloud-init output, and recorded in the `requestParameters` of the `RunInstances` CloudTrail event; fetch them at boot from Secrets Manager / SSM Parameter Store (SecureString) via the instance profile.
- **Scope security groups to least privilege** — reference another security group or a specific CIDR rather than `0.0.0.0/0`; the template's rules propagate to every launched instance.
- **Encrypt EBS volumes** in the block device mappings, and **prefer Session Manager over SSH** (no open port 22, no key sprawl).

## Related

- [instance-selection.md](instance-selection.md) — what to put in the template
- [auto-scaling.md](auto-scaling.md) — use the template in an ASG
- [systems-manager.md](systems-manager.md) — keyless access
