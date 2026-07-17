# EC2 Troubleshooting

## Overview
Diagnosing the common EC2 failures: connectivity, status checks, capacity/quota errors, Spot interruptions, credit exhaustion, and instances that die on launch. Match the exact error string first — several look similar but have opposite fixes.

## Can't SSH in: read the exact error
The error string tells you the layer.

| Error | Layer | Causes | Fix |
|-------|-------|--------|-----|
| **Connection timed out** | Network — packets never arrive | Security group missing inbound TCP 22 from your IP; NACL blocking; no route to internet gateway; instance has no/changed public IP; local firewall | Open 22 from your IP; verify route + public IP; note public IP changes on stop/start unless an Elastic IP is attached |
| **Connection refused** | Host — reachable, nothing on the port | sshd not running/listening on that port; instance still booting; sshd misconfigured | Wait for boot; check sshd via Session Manager or EC2 serial console |
| **Permission denied (publickey)** | Auth | Wrong username for the AMI; wrong key; key file perms; EC2 Instance Connect key expired (60s) | Use the AMI's default user (ec2-user/ubuntu/admin/root); `chmod 400 key.pem`; re-run send-ssh-public-key |

Keyless fallbacks: Session Manager, EC2 Instance Connect, or the serial console (Nitro instances). The serial console is **not on by default** — it needs account-level enablement plus IAM permissions, and on Linux requires a preconfigured password-based user (only the browser client itself is truly keyless). The `AWSSupport-TroubleshootSSH` runbook automates checks. Debug with `ssh -vvv -i key.pem user@host`. For "Connection timed out", enable VPC Flow Logs to confirm whether packets reach the ENI (ACCEPT/REJECT) — KMS-encrypt the flow-log destination (S3 bucket via SSE-KMS or CloudWatch Logs log group); add the CloudWatch agent for OS-level visibility.

## Status check failed: system vs instance

| Check | Monitors | Remedy |
|-------|----------|--------|
| **System** (`StatusCheckFailed_System`) | AWS host/hardware/power/network | **Stop/start** an EBS-backed instance to migrate to new hardware (a reboot stays on the same host); or set a CloudWatch instance-recovery action; or wait for AWS |
| **Instance** (`StatusCheckFailed_Instance`) | The instance's OS/network config | Reboot or fix the OS/network config yourself |
| Attached EBS | Attached EBS volumes | Investigate the volume; ASG replacement isn't automatic for this check — by default. Enabling the opt-in EBS health check on the ASG (Nitro instances) makes it detect attached-EBS impairment and replace the instance automatically |

## Capacity vs quota errors (opposite fixes)

| Error | Meaning | Fix |
|-------|---------|-----|
| **InsufficientInstanceCapacity** | AWS lacks spare capacity for that type in that AZ — NOT a quota | Try another AZ, another instance type/size, retry later, or request fewer per call. In a cluster placement group, stop/start all group instances to re-place them |
| **InstanceLimitExceeded** | You hit an On-Demand vCPU-based quota (grouped, e.g. the Standard family group A/C/D/H/I/M/R/T/Z; the vCPU-phrased variant is `VcpuLimitExceeded`) — this IS a quota | Raise it via Service Quotas for that quota and Region |

A quota increase does nothing for `InsufficientInstanceCapacity`.

## Spot interruptions
Spot instances get a **2-minute interruption notice** (via instance metadata `instance-action` and the EventBridge event `EC2 Spot Instance Interruption Warning`). An earlier, softer signal — the **rebalance recommendation** (`EC2 Instance Rebalance Recommendation`) — usually arrives earlier than (but is best-effort and can arrive together with) the two-minute interruption notice, giving more time to drain. In an ASG, enable Capacity Rebalancing to act on it automatically (see [auto-scaling.md](auto-scaling.md)). Test interruption handling with AWS Fault Injection Service.

## High CPU / sudden slowdown on burstable (T) instances
A T instance that suddenly and persistently drops to sluggish performance under sustained load has likely exhausted its CPU credits: in `standard` mode it throttles to baseline. Switch to `unlimited` (watch surplus charges) or move to a fixed-performance family. In `unlimited` mode the reverse symptom — a surprise bill — comes from `CPUSurplusCreditsCharged`. See [instance-selection.md](instance-selection.md).

## Instance immediately stops or terminates after launch

- **Encrypted root EBS volume the launch role can't decrypt** — the principal/role lacks KMS key permissions; grant key access. Check the system log to confirm the OS never booted.
- Hitting EBS volume quotas can block/impair launches.
- Remember instance store data is gone after any stop.

## Instance status check fails after changing to a Nitro type
Migrating to a Nitro-based instance type without the ENA and NVMe drivers installed causes instance status check failures — install the drivers before switching.

## Security Considerations

- **Prefer Session Manager over SSH for diagnosis** — keyless, IAM-scoped, and fully audited via CloudTrail (no key sprawl or open port 22).
- **Treat repeated connection failures as possible reconnaissance** — enable CloudTrail and VPC Flow Logs so failed access attempts are visible.
- **A status-check failure can be a security event, not just hardware** — before reflexively rebooting a suspect instance, review system logs and consider isolation/forensics (a reboot can destroy volatile evidence and instance-store data).

## Related

- [auto-scaling.md](auto-scaling.md) — ASG health, Spot, lifecycle hooks
- [provisioning.md](provisioning.md) — Elastic IPs, key pairs, IMDS
- [systems-manager.md](systems-manager.md) — keyless access as an SSH fallback
