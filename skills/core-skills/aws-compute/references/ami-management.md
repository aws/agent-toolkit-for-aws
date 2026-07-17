# AMI Management

## Overview
Creating, sharing, and retiring Amazon Machine Images. For building AMIs with an automated pipeline (recipes, components, distribution), use the `creating-ec2-image-builder-pipeline` skill — this reference covers the AMI lifecycle and sharing that a domain skill owns.

## Create a custom AMI

```bash
aws ec2 create-image --instance-id <id> --name "my-app-v1" --description "..."
```

`NoReboot` defaults to `false`, so EC2 reboots the instance to guarantee a consistent file system. **Setting `--no-reboot` skips that, and AWS cannot guarantee file-system integrity** — only use it if you've quiesced/flushed the disk yourself.

The AMI's snapshots inherit the source volumes' encryption. Image from encrypted EBS volumes so the AMI is encrypted at rest; if the source is unencrypted, `copy-image --encrypted --kms-key-id <customer-managed-key>` produces an encrypted copy (also the prerequisite for cross-account sharing — see below).

## Retire an AMI: deprecate vs disable vs deregister
These are three distinct actions with different reversibility — choosing the wrong one either fails to block launches or destroys the image.

| Action | Effect | Still launchable? | Reversible? |
|--------|--------|-------------------|-------------|
| **Deprecate** (`enable-image-deprecation`) | Hides the AMI from `describe-images` listings and the console wizard for other accounts after a date | **Yes** — anyone with the AMI ID can still launch; ASGs/launch templates keep using it | Yes (`disable-image-deprecation`) |
| **Disable** (`disable-image`) | Sets state to `disabled`, **blocks all new launches**, and revokes launch permissions/sharing | No | **Partially** — `enable-image` restores launchability, visibility, and shareability, but accounts/orgs/OUs that lost access when the AMI was disabled do NOT regain it automatically; you must re-grant launch permissions (re-share) via `modify-image-attribute`. (AMI tags are unaffected by disable/enable.) |
| **Deregister** (`deregister-image`) | Permanently removes the AMI | No | Only if a Recycle Bin retention rule was set beforehand |

**To block new launches while keeping the ability to restore, use `disable-image`** — deprecate does not actually stop launch-by-ID, and deregister is effectively permanent.

## Share an AMI cross-account / cross-region
Grant launch permission with `modify-image-attribute` (specific account IDs, an Organization/OU, or public).

**Encrypted AMIs have a KMS catch:** an AMI whose snapshots are encrypted with the **default AWS-managed EBS key (`aws/ebs`) cannot be shared across accounts** — the default service key is usable only within the owning account, so grantees can't decrypt the snapshots even with launch permission. To share an encrypted AMI:

1. Re-encrypt the snapshots under a **customer-managed KMS key** (e.g., copy the AMI/snapshot specifying that key).
2. Grant the target account permission on that customer-managed KMS key via the key policy: `kms:DescribeKey`, `kms:Decrypt`, `kms:CreateGrant`, `kms:ReEncrypt*`, `kms:GenerateDataKey*`.
3. Add the account to the AMI's launch permissions.

KMS keys are Region-scoped, so copying/sharing an encrypted AMI to a different Region or account needs a customer-managed KMS key in each Region. To prevent accidental public exposure, enable **AMI block public access** at the account level (per Region; it doesn't retroactively unshare existing public AMIs).

## Common Errors

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| Target account can't launch a shared encrypted AMI | Snapshots use the default `aws/ebs` key | Re-encrypt under a customer-managed key and grant the account key access |
| Users still launch an AMI you "removed" | Deprecation only hides; still launchable by ID | Use `disable-image` to block launches (or deregister to delete) |
| Deregistered AMI can't be recovered | Deregister is permanent without Recycle Bin | Prefer `disable-image` to block reversibly; set Recycle Bin rules for critical AMIs |
| New AMI has a corrupt filesystem | `--no-reboot` skipped the consistency reboot | Recreate without `--no-reboot`, or flush/quiesce before imaging |

## Security Considerations

- **Cross-account sharing requires a customer-managed KMS key** — snapshots under the default `aws/ebs` key can't be shared. Re-encrypt under a customer-managed key and grant the target account access to it in the key policy. See the "Share an AMI cross-account" section above for the full set of required KMS actions (`kms:DescribeKey`, `kms:Decrypt`, `kms:CreateGrant`, `kms:ReEncrypt*`, `kms:GenerateDataKey*`).
- **Enable AMI block public access** at the account/Region level to prevent accidental public exposure of an image.
- **Scrub secrets before imaging** — an AMI captures the source instance's disk, so remove anything sensitive first: shell history (`~/.bash_history`), long-lived credentials/API keys, SSH host keys and `authorized_keys`, and any secrets injected via user data or configuration management. Otherwise they are baked into every instance launched from the AMI (and into anyone you share it with).
- **Prefer reversible retirement** — `disable-image` blocks launches and revokes sharing but is reversible; `deregister-image` is effectively permanent (only recoverable via a pre-set Recycle Bin rule). Reversible retirement matters for security investigations: if an image is later implicated in a discovered security event, a disabled AMI can be retained and restored for forensic analysis, whereas a deregistered one may be gone.
- **Audit AMI operations with CloudTrail** — enable CloudTrail in all Regions and alarm on sensitive AMI actions (`ModifyImageAttribute` for sharing changes, `DeregisterImage`, `DisableImage`) to detect unauthorized cross-account sharing or destructive deregistration.

## Related

- The `creating-ec2-image-builder-pipeline` skill for automated AMI build pipelines
- [provisioning.md](provisioning.md) to reference the AMI in a launch template
