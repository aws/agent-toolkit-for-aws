# Creating a Direct Connect Virtual Interface and Configuring BGP

## Overview

Domain expertise for turning a live Direct Connect connection into something that carries traffic: a
virtual interface (VIF) and a Border Gateway Protocol (BGP) session. Covers choosing the right
virtual interface type for what the customer needs to reach, the jumbo-frame maximum transmission
unit (MTU) decision, the BGP parameters that must match on both ends, and
a troubleshooting branch for when the BGP session does not come up.

Does not cover choosing the connection model, reaching many VPCs through a Direct Connect gateway
(a separate reference), encryption, or resiliency. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- Decision: virtual interface type
- Jumbo-frame MTU
- BGP parameters
- What the agent cannot see
- Troubleshooting: BGP not coming up
- Procedure
- Additional Resources

## Decision: virtual interface type

The type decides what the connection can reach and cannot be changed after creation.

| Type | Reaches | Use when |
| --- | --- | --- |
| Private virtual interface | An Amazon VPC over private IP addresses (via a virtual private gateway or a Direct Connect gateway) | The customer needs to reach VPC resources |
| Public virtual interface | Public AWS services over public IP addresses | The customer needs to reach public AWS service endpoints |
| Transit virtual interface | One or more transit gateways associated with a Direct Connect gateway | The customer needs to reach many VPCs or a hub-and-spoke transit gateway |

**Constraints:**

- You MUST map the customer's target (a VPC, public AWS services, or transit gateways) to the
  matching virtual interface type before creating it, because the types are not interchangeable.
- You SHOULD steer a customer with a multi-VPC goal to a transit virtual interface rather than
  stacking one private virtual interface per VPC.
- For a public virtual interface, you MUST confirm the customer owns and advertises registered public
  prefixes, because AWS performs inbound filtering to confirm traffic originates from the advertised
  prefix and an unregistered or wrong prefix silently fails.

## Jumbo-frame MTU

| Virtual interface type | MTU options |
| --- | --- |
| Private | 1500 or 9001 |
| Transit | 1500 or 8500 |
| Public | 1500 only |

**Constraints:**

- You SHOULD settle the MTU before creating the virtual interface. MTU can be changed on a live
  private or transit virtual interface using `update-virtual-interface-attributes`, but this causes a
  brief connectivity disruption (~30 seconds) for all VIFs on the underlying connection:

  ```
  aws directconnect update-virtual-interface-attributes \
    --virtual-interface-id {virtual_interface_id} --mtu {mtu} --region {region}
  ```

- You SHOULD confirm the per-type ceiling (9001 private, 8500 transit, 1500 public) when the customer
  wants jumbo frames.

## BGP parameters

Every virtual interface runs BGP. The session needs matching configuration on both ends.

**Constraints:**

- You MUST collect the VLAN ID and the BGP Autonomous System Number for the customer's on-premises
  router upfront.
- You SHOULD collect the BGP peering addresses (`amazonAddress`/`customerAddress`) if the customer has
  a preference; for IPv4, AWS auto-assigns them from a /30 if they are omitted.
- You MUST configure the BGP MD5 authentication key to match exactly on both sides; MD5 is always
  enabled by AWS and a trailing space is enough to break the session.
- You SHOULD treat the BGP MD5 key as a shared secret: do not echo it in CLI output or shell history,
  store it in AWS Secrets Manager or SSM Parameter Store (SecureString type) rather than in plaintext
  configuration files, and rotate it periodically. When the key is held in a Secrets Manager secret,
  you SHOULD scope a resource policy on that secret to only the principals that need to manage the BGP
  key, and include `aws:SourceArn` or `aws:SourceAccount` condition keys to restrict access to only the
  Direct Connect virtual interface that needs the key and prevent confused-deputy scenarios.
- You MUST NOT specify custom IPv6 peer addresses; AWS auto-allocates a /125.
- You MUST walk the customer to verifying the BGP session state rather than stopping at virtual
  interface creation.

## What the agent cannot see

**Constraints:**

- You MUST NOT tell the customer you can read the advertised or received BGP routes from a describe
  call. Direct Connect does not expose advertised and received routes through the API. Show
  the customer what the API does return (virtual interface state and BGP status) and be explicit that
  the route lists are not visible to the agent.

## Troubleshooting: BGP not coming up

The session staying down is the real support driver. The cause is one of several, not just MD5. Work
them in order.

### BGP session never establishes

- **MD5 authentication key mismatch** (most common): re-enter the key carefully on both sides; a
  trailing space breaks it.
- **VLAN tag mismatch**: confirm the VLAN ID matches the LOA-CFA and is trunked on every intermediate
  device.
- **Wrong Autonomous System Number or peer IP**: verify the Amazon-side ASN and peer addresses from
  `describe-virtual-interfaces`.
- **Layer 2 problem**: 802.1Q VLAN not trunked on an intermediate device, so the peer IP is
  unreachable and ARP does not resolve.
- **Layer 1 problem**: no light or a transceiver/auto-negotiation mismatch on the physical link.

### BGP establishes then drops
The per-virtual-interface prefix limit was exceeded. Reduce advertised prefixes or request a higher
allocation.

## Procedure

### Overview

This procedure picks the virtual interface type, settles the MTU, creates the virtual interface with
the BGP parameters, and verifies the session, with a fallback into the BGP troubleshooting branch if
the session does not come up.

### Parameters

- **connection_id** (required): The live connection or LAG ID.
- **vif_type** (required): `private`, `public`, or `transit`.
- **vlan** (required): The VLAN ID.
- **customer_asn** (required): The on-premises BGP Autonomous System Number.
- **mtu** (optional): `1500` (default), `9001` (private), or `8500` (transit). Can be changed post-creation with a brief disruption (~30s).
- **target** (required): The virtual private gateway, Direct Connect gateway, or public prefixes the
  virtual interface points at.
- **amazon_address** / **customer_address** (optional): The BGP peering addresses. For IPv4, AWS
  auto-assigns them from a /30 if omitted; supply them only if the customer has a preference.

**Constraints for parameter acquisition:**

- You MUST ask for the type, target, VLAN, ASN, and MTU upfront in a single prompt.
- You MUST confirm the MTU choice before creation, since changing it afterward causes a brief connectivity disruption (~30 s) for all VIFs on the underlying connection.

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm the connection is live and the target (virtual private gateway, Direct Connect
  gateway, or registered public prefixes) exists.

#### 2. Create the virtual interface with the MTU set

**Constraints:**

- You MUST create the matching virtual interface type with the MTU set at creation. For a private
  virtual interface, target either a Direct Connect gateway (many VPCs, cross-Region, or
  cross-account) or a virtual private gateway (a single VPC) — use the parameter that matches the
  customer's target, not both.

  Via a Direct Connect gateway:

  ```
  aws directconnect create-private-virtual-interface --connection-id {connection_id} \
    --new-private-virtual-interface virtualInterfaceName={name},vlan={vlan},asn={customer_asn},mtu={mtu},directConnectGatewayId={dx_gw_id},addressFamily=ipv4 \
    --region {region}
  ```

  Via a virtual private gateway (single VPC):

  ```
  aws directconnect create-private-virtual-interface --connection-id {connection_id} \
    --new-private-virtual-interface virtualInterfaceName={name},vlan={vlan},asn={customer_asn},mtu={mtu},virtualGatewayId={vgw_id},addressFamily=ipv4 \
    --region {region}
  ```

- For a transit virtual interface, you MUST cap the MTU at 8500 (not 9001):

  ```
  aws directconnect create-transit-virtual-interface --connection-id {connection_id} \
    --new-transit-virtual-interface virtualInterfaceName={name},vlan={vlan},asn={customer_asn},mtu={mtu},directConnectGatewayId={dx_gw_id},addressFamily=ipv4 \
    --region {region}
  ```

- You MUST capture the `virtualInterfaceId` from the response.

#### 3. Bring up and verify the BGP session

**Constraints:**

- You MUST give the customer the downloadable router configuration and confirm the MD5 key matches
  exactly on both ends.
- You MUST check the virtual interface state and BGP status:

  ```
  aws directconnect describe-virtual-interfaces --virtual-interface-id {virtual_interface_id} --region {region}
  ```

- If the session does not come up, you MUST work the BGP-not-coming-up branch (MD5, VLAN, ASN/peer
  IP, Layer 2, Layer 1) rather than stopping.

#### 4. Surface the console link

**Constraints:**

- You MUST present the Direct Connect console link, filling `{virtual_interface_id}` and `{region}` from
  the response, and tell the customer to confirm the virtual interface and BGP status there:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/virtual-interfaces/{virtual_interface_id}
  ```

- You SHOULD recommend CloudWatch alarms on the virtual interface state and BGP status metrics, and
  confirm CloudTrail is capturing `directconnect` API calls with log file validation enabled and the
  trail encrypted with a KMS key, and any CloudWatch Logs log groups receiving these events or alarm
  state data encrypted with a KMS key, so state changes trigger alerts and configuration changes are
  audited with assured log integrity and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the virtual interface. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Direct Connect virtual interfaces and hosted virtual interfaces (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/WorkingWithVirtualInterfaces.html)
- [Direct Connect routing policies and BGP communities (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/routing-and-bgp.html)
- [Create a transit virtual interface to the Direct Connect gateway (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/create-transit-vif-dx.html)
- [Troubleshooting AWS Direct Connect (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/Troubleshooting.html)
