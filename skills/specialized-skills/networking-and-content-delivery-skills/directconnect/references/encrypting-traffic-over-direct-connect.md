# Encrypting Traffic Over Direct Connect

## Overview

Domain expertise for encrypting traffic in transit over Direct Connect, which is not encrypted by
default. Covers the two main options (MAC Security and a Site-to-Site VPN over the connection),
the recommended private IP Site-to-Site VPN over a transit virtual interface, the MACsec
prerequisites and the boundary of what it actually protects, and the fact that MACsec is also
available on partner connections.

Does not cover choosing the connection model, creating the virtual interface and BGP (a separate
reference), reaching many VPCs, or resiliency. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- Direct Connect is not encrypted by default
- Decision: MACsec vs Site-to-Site VPN
- Private IP VPN over a transit virtual interface
- MACsec prerequisites and boundary
- Troubleshooting
- Procedure
- Additional Resources

## Direct Connect is not encrypted by default

**Constraints:**

- You MUST state plainly that Direct Connect does not encrypt traffic in transit on its own, and
  require the customer to choose an encryption option before the path carries regulated data.

## Decision: MACsec vs Site-to-Site VPN

| Option | Layer | Where it applies | Use when |
| --- | --- | --- | --- |
| MAC Security (MACsec) | Layer 2 | Point-to-point over the cross connect, between the customer edge device and the Direct Connect edge device | 10/100 Gbps dedicated (at select locations), or a partner connection where the partner sources it; the customer has a MACsec-capable router |
| Site-to-Site VPN | Layer 3 (IPsec) | An encrypted tunnel over the connection | The customer wants IPsec encryption, especially a private IP VPN to a transit gateway |

**Constraints:**

- You MUST compare the two options against the customer's connection type and requirements rather
  than defaulting to one; they differ in layer, supported speeds, and where they apply.

## Private IP VPN over a transit virtual interface

**Constraints:**

- You SHOULD present a private IP Site-to-Site VPN over a transit virtual interface to a transit
  gateway as the recommended encrypted path for customers heading to a transit gateway. It keeps the
  tunnel on private addressing, unlike the older pattern of a VPN over a public virtual interface.
- You SHOULD NOT present "VPN over Direct Connect" only generically when the customer is reaching a
  transit gateway; name the private IP path.

## MACsec prerequisites and boundary

**Constraints:**

- You MUST check the connection speed (10 or 100 Gbps dedicated), location support, and that the
  customer's router has a MACsec-capable interface before proposing MACsec.
- You MUST enable MACsec at connection creation; it cannot be added to an existing non-MACsec
  connection without deleting and recreating it.
- You SHOULD note that MACsec is also available on partner connections, sourced by the partner on the
  interconnect that hosts the customer connection, so a hosted-connection customer should not rule it
  out.
- You MUST set the correct boundary: MACsec is point-to-point Layer 2 protection over the cross
  connect, not end-to-end encryption across multiple network segments, so the customer does not
  over-trust it.
- You SHOULD confirm the supported MACsec cipher-suite mode for the connection speed, since the mode
  depends on the speed.
- You MUST store the CKN/CAK pair in AWS Secrets Manager and reference it by `--secret-arn`, never
  passing the values inline or storing them in plaintext config. You SHOULD scope a resource policy on
  that secret to only the principals that need to manage the MACsec key, and include `aws:SourceArn` or
  `aws:SourceAccount` condition keys to restrict access to only the Direct Connect connection(s) that
  need the key and prevent confused-deputy scenarios.

## Troubleshooting

### Sensitive data is already flowing and the customer assumed it was encrypted
Direct Connect is not encrypted by default. Stop and choose MACsec or a Site-to-Site VPN.

### MACsec cannot be added to a running connection
MACsec must be enabled at connection creation. Delete and recreate the connection with MACsec, or use
a Site-to-Site VPN instead.

### Customer on a hosted connection thinks MACsec is unavailable
MACsec is available on partner connections too, sourced on the partner interconnect. Engage the
partner.

### MACsec is on but the customer expects full end-to-end coverage
MACsec protects only the point-to-point cross connect at Layer 2. For end-to-end, layer a Site-to-Site
VPN on top.

## Procedure

### Overview

This procedure confirms encryption is needed, picks MACsec or a Site-to-Site VPN against the
customer's connection, and sets it up, surfacing the console link to verify.

### Parameters

- **encryption_option** (required): `macsec` or `vpn`.
- **connection_id** (required for MACsec): The dedicated connection (MACsec enabled at creation).
- **secret_arn** (required for MACsec): The AWS Secrets Manager secret holding the CKN/CAK pair.
- **vpn_target** (required for VPN): The transit gateway (for the private IP path) or other endpoint.

**Constraints for parameter acquisition:**

- You MUST establish the customer's connection type and speed before recommending an option.

### Steps

#### 1. Confirm the encryption need and connection facts

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm the connection speed, location support, and edge-device capability when MACsec is
  on the table.

#### 2a. Associate a MACsec key (MACsec path)

**Constraints:**

- You MUST associate the MACsec key from Secrets Manager with the connection (the connection must
  have been created with MACsec enabled):

  ```
  aws directconnect associate-mac-sec-key --connection-id {connection_id} \
    --secret-arn {secret_arn} --region {region}
  ```

- You MUST verify MACsec status:

  ```
  aws directconnect describe-connections --connection-id {connection_id} --region {region}
  ```

#### 2b. Set up the Site-to-Site VPN (VPN path)

**Constraints:**

- You MUST set up the Site-to-Site VPN over the connection, preferring the private IP VPN over a
  transit virtual interface to a transit gateway when the customer is reaching a transit gateway. For
  the private IP path, create the VPN connection against the transit gateway and customer gateway with
  private outside addressing (delegate the full Site-to-Site VPN setup to the sitetositevpn skill for
  customer/transit gateway creation and tunnel options):

  ```
  aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id {cgw_id} \
    --transit-gateway-id {tgw_id} \
    --options '{"TunnelInsideIpVersion":"ipv4","OutsideIpAddressType":"PrivateIpv4","TransportTransitGatewayAttachmentId":"{transit_vif_attachment_id}"}' \
    --region {region}
  ```

- You MUST confirm BGP preference so the VPN behaves as intended (backup or primary) for the
  customer's design.

#### 3. Surface the console link

**Constraints:**

- You MUST present the relevant Direct Connect console link to verify. For the virtual interface
  carrying the VPN, fill `{virtual_interface_id}` and `{region}`:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/virtual-interfaces/{virtual_interface_id}
  ```

- You SHOULD recommend CloudWatch alarms on MACsec key status or VPN tunnel status, and confirm
  CloudTrail is capturing `directconnect` API calls with log file validation enabled and the trail
  encrypted with a KMS key, and any CloudWatch Logs log groups receiving these events or alarm state
  data encrypted with a KMS key, so state changes trigger alerts and configuration changes are audited
  with assured log integrity and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the link; this reference covers both options.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Encryption in AWS Direct Connect (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/encryption-in-transit.html)
- [MAC Security in Direct Connect (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/MACsec.html)
- [Private IP VPN with AWS Direct Connect (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/private-ip-dx.html)
- [Adding MACsec security to AWS Direct Connect connections (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/adding-macsec-security-to-aws-direct-connect-connections/)
