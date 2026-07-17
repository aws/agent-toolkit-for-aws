# EC2 Operations with Systems Manager

## Overview
Operating EC2 fleets without SSH keys or open ports: registering managed nodes, Session Manager access, Run Command, Patch Manager, and State Manager.

## Make an instance a managed node
An EC2 instance becomes a Systems Manager managed node when the SSM Agent (running, with a network path to the service) has SSM credentials, via **either**:

1. An attached IAM instance profile with the `AmazonSSMManagedInstanceCore` managed policy (or an equivalent custom policy). A missing instance profile is the single most common reason an instance is "not managed."
2. Account + Region-level **Default Host Management Configuration (DHMC)**, which needs **no per-instance profile** — it uses the `AWSSystemsManagerDefaultEC2InstanceManagementRole` role with the `AmazonSSMManagedEC2InstanceDefaultPolicy` policy, and requires IMDSv2 and a current SSM Agent version (see the [DHMC prerequisites](https://docs.aws.amazon.com/systems-manager/latest/userguide/fleet-manager-default-host-management-configuration.html)). Note: if an instance profile is already attached, SSM Agent uses it before DHMC — remove any `ssm:UpdateInstanceInformation` permission from the profile for DHMC to take over.

The SSM Agent is preinstalled on many current AWS-provided AMIs — Amazon Linux 2/2023, Ubuntu, Windows Server among them; check the [SSM Agent preinstalled-AMI list](https://docs.aws.amazon.com/systems-manager/latest/userguide/ami-preinstalled-agent.html) or confirm the `amazon-ssm-agent` package is present.

Check Fleet Manager for node status (`PingStatus` is `Online`, `ConnectionLost`, or `Inactive`). An Organizations SCP that denies SSM actions also blocks managed status.

## Session Manager (keyless shell access)
Session Manager gives a browser/CLI shell with **no inbound ports, no bastion, and no SSH keys** — the agent connects outbound to the service.

```bash
aws ssm start-session --target <instance-id>
```

**Encrypt session logging.** Session output can contain sensitive command results. Encrypt the destination yourself first: KMS on the CloudWatch Logs log group (`aws logs associate-kms-key --log-group-name <name> --kms-key-id <arn>`) or SSE-KMS on the S3 bucket. Then set `cloudWatchEncryptionEnabled` / `s3EncryptionEnabled` = true — these flags do **not** enable encryption; when true they require the destination to already be encrypted and SSM refuses to stream logs to an unencrypted destination (an enforcement gate). Separately, `kmsKeyId` encrypts the data channel between the client and the managed node (on top of default TLS).

**Audit SSM API usage with CloudTrail.** Session logging captures *what* ran inside a session; CloudTrail records *who* called SSM and from where — enable it in all Regions to log `StartSession`, `SendCommand`, and `GetParameter`, and alarm on unexpected callers or principals. It is the API-level audit trail for fleet operations.

For an instance in a **private subnet with no NAT/internet gateway**, the agent can't reach the service, so create the following VPC endpoints (interface endpoints with private DNS enabled, except S3 which uses a free gateway endpoint) — `ssm` and `ssmmessages` are always required:

| Endpoint | Purpose |
|----------|---------|
| `com.amazonaws.<region>.ssm` | Core Systems Manager API |
| `com.amazonaws.<region>.ssmmessages` | **Session Manager data channel**; also carries Run Command with current agents |
| `com.amazonaws.<region>.ec2messages` | Legacy — superseded by `ssmmessages`; not required with a current SSM Agent |
| `com.amazonaws.<region>.s3` | Patch downloads, Run Command document content, and S3 output capture — use a **gateway endpoint** (free, no per-hour charge). Required for Patch Manager / `AWS-RunPatchBaseline` and S3 output in a no-NAT subnet |
| `com.amazonaws.<region>.kms` | Session encryption — required only when `kmsKeyId` (above) is configured; without it the encrypted channel can't be established |

Alternatively allow HTTPS (443) egress to those service endpoints (add `kms.<region>.amazonaws.com` when session encryption is enabled). `TargetNotConnected` means prerequisites are unmet, the node isn't managed, or you're in the wrong Region.

## Fleet operations

- **Run Command** — one-off fleet execution; `aws ssm send-command --document-name AWS-RunShellScript --targets "Key=tag:Role,Values=web-tier" --parameters 'commands=[...]'`. Target by instance IDs or tags. Command output can contain sensitive data — when capturing it to S3 (`--output-s3-bucket-name`) or CloudWatch Logs (`--cloud-watch-output-config`), enable KMS encryption (SSE-KMS bucket / KMS-encrypted log group) on the destination. Secure the S3 output bucket by granting `s3:PutObject` (and `s3:GetObject`, `s3:PutObjectAcl` as needed) to the managed node's **instance-profile IAM role** as the bucket-policy `Principal` (`arn:aws:iam::<account>:role/<InstanceProfileRole>`), scoped to the key prefix via `Resource`. Run Command output is written by the instance role directly, not by the SSM service principal — so do **not** use `aws:SourceArn`/`aws:SourceAccount` here (those apply only when a service principal writes on your behalf). When you build `--targets` tag values or `--parameters` commands from external or user-supplied input, validate and escape them first — unsanitized values flow into shell execution on the fleet and are a command-injection path.
- **Patch Manager** — patch at scale with patch baselines + maintenance windows + tag-based patch groups; core document `AWS-RunPatchBaseline` (`Scan`/`Install`).
- **State Manager** — associations that re-apply desired state on a schedule (vs Run Command's one-shot).

## Common Errors

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| Instance not a managed node | No instance profile with `AmazonSSMManagedInstanceCore` | Attach a role with that policy via an instance profile |
| `TargetNotConnected` on start-session | No network path (private subnet, no endpoints) or node not Online | Add ssm/ssmmessages/ec2messages endpoints or NAT egress; confirm Online |
| Managed but Session Manager fails | `ssmmessages` endpoint missing | Add the ssmmessages interface endpoint |
| Node managed but SCP blocks actions | Org SCP denies SSM permissions | Update the SCP to allow required SSM actions |
| Maintenance window runs nothing | Target tag mismatch or nodes not managed | Fix the tag match; ensure nodes are managed and running in the window |

## Security Considerations

- **Sanitize any external input** built into `--targets` tag values or `--parameters` commands before calling Run Command or State Manager — unsanitized values flow into shell execution on the fleet and are a command-injection vector.
- **Encrypt session and command output** (KMS on the Session Manager S3/CloudWatch sinks, SSE-KMS on Run Command output destinations) — it can contain sensitive results.
- **Audit with CloudTrail** in all Regions (`StartSession`, `SendCommand`, `GetParameter`) and alarm on unexpected callers; prefer Session Manager over inbound SSH for its keyless, fully-audited access.
- **Scope SSM access with IAM** — the instance profile needs only `AmazonSSMManagedInstanceCore`; grant human operators least-privilege session/command permissions.

## Related

- [provisioning.md](provisioning.md) for key pairs (when you do need SSH)
- The `setting-up-ec2-instance-profiles` skill for creating the instance profile itself
- [troubleshooting.md](troubleshooting.md) for connectivity issues
