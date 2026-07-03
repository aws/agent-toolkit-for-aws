# Setting Up Direct Connect SiteLink

## Overview

Domain expertise for SiteLink, the Direct Connect feature that connects two or more Direct Connect
locations so on-premises sites attached to them can exchange traffic over the AWS backbone without
routing through a VPC or a Region. Covers when SiteLink fits, the per-virtual-interface enablement,
the single-partition requirement, the private/transit virtual interface requirement, and the
per-gigabyte billing the customer is opting into.

Does not cover choosing the connection model, virtual interface and BGP setup (a separate
reference), reaching VPCs through a Direct Connect gateway, or encryption. Those are separate
references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- When SiteLink fits
- Per-virtual-interface enablement
- Single partition and virtual interface type
- Per-gigabyte billing
- Troubleshooting
- Procedure
- Additional Resources

## When SiteLink fits

**Constraints:**

- You SHOULD reach for SiteLink when two or more on-premises sites, attached to different Direct
  Connect locations in the same AWS partition, need to communicate and routing through a Region is
  undesirable.
- You SHOULD remind the customer that traffic over SiteLink is not encrypted in transit by default,
  and point them to the encrypting-traffic reference if the workload requires encryption.

## Per-virtual-interface enablement

**Constraints:**

- You MUST enable SiteLink on each private or transit virtual interface that should participate.
  SiteLink is set per virtual interface, not once for the connection, so enabling it on one interface
  does not bring in the others.

## Single partition and virtual interface type

**Constraints:**

- You MUST confirm all participating sites are in the same AWS partition before proposing SiteLink; it
  cannot link a commercial Region site to an AWS GovCloud (US) site.
- You MUST confirm the virtual interface type is private or transit; SiteLink does not run on a public
  virtual interface.

## Per-gigabyte billing

**Constraints:**

- You MUST state the per-gigabyte SiteLink data transfer charge, which is separate from standard
  Direct Connect data transfer and applies as soon as the feature is on, before enabling SiteLink. The
  customer should be opting into metered transfer knowingly, not discovering it on the invoice.

## Troubleshooting

### Some sites still cannot reach each other after enabling SiteLink
SiteLink is per virtual interface. Enable it on every participating private or transit virtual
interface.

### SiteLink will not link two sites
They are in different AWS partitions (for example commercial and GovCloud). SiteLink works only within
one partition.

### SiteLink option is not available on a virtual interface
It is a public virtual interface. SiteLink runs only on private and transit virtual interfaces.

### Unexpected data transfer charges after turning on SiteLink
SiteLink carries a separate per-gigabyte charge. It applies as soon as the feature is enabled.

### Need to disable SiteLink on a virtual interface
Disable with:

```
aws directconnect update-virtual-interface-attributes \
  --virtual-interface-id {virtual_interface_id} --no-enable-site-link --region {region}
```

## Procedure

### Overview

This procedure confirms the partition and virtual interface type, states the billing, enables
SiteLink on each participating virtual interface, and surfaces the console link.

### Parameters

- **virtual_interface_ids** (required): The private or transit virtual interfaces to enable SiteLink
  on, one per participating site.
- **partition_confirmed** (required): Confirmation that all sites are in the same AWS partition.

**Constraints for parameter acquisition:**

- You MUST list every virtual interface that should participate, since each one must be enabled.

### Steps

#### 1. Verify dependencies and the billing acknowledgement

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm all sites are in the same AWS partition and that each target virtual interface is
  private or transit.
- You MUST surface the per-gigabyte billing and get the customer's acknowledgement before enabling.

#### 2. Enable SiteLink on each virtual interface

**Constraints:**

- You MUST confirm each virtual interface is attached to a Direct Connect gateway (DXGW), not a
  virtual private gateway (VGW). SiteLink requires a DXGW association.
- You MUST enable SiteLink on every participating virtual interface, not just one:

  ```
  aws directconnect update-virtual-interface-attributes \
    --virtual-interface-id {virtual_interface_id} --enable-site-link --region {region}
  ```

- You MUST verify SiteLink is active:

  ```
  aws directconnect describe-virtual-interfaces \
    --virtual-interface-id {virtual_interface_id} \
    --query 'virtualInterfaces[0].{State:virtualInterfaceState,SiteLink:siteLinkEnabled}' \
    --output table --region {region}
  ```

  Poll until siteLinkEnabled reports true.

#### 3. Confirm and surface the console link

**Constraints:**

- You MUST confirm SiteLink is enabled on each virtual interface and present the console link, filling
  `{virtual_interface_id}` and `{region}`:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/virtual-interfaces/{virtual_interface_id}
  ```

- You SHOULD recommend CloudWatch alarms on the virtual interface state and BGP status, and confirm
  CloudTrail is capturing `directconnect` API calls with log file validation enabled and the trail
  encrypted with a KMS key, and any CloudWatch Logs log groups receiving these events or alarm state
  data encrypted with a KMS key, so state changes trigger alerts and configuration changes are audited
  with assured log integrity and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses SiteLink. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [AWS Direct Connect SiteLink (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/sitelink.html)
- [Direct Connect virtual interfaces and hosted virtual interfaces (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/WorkingWithVirtualInterfaces.html)
- [AWS Direct Connect pricing](https://aws.amazon.com/directconnect/pricing/)
