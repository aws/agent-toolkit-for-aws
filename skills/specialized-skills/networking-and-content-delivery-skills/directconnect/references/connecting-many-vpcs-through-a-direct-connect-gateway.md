# Connecting Many VPCs Through a Direct Connect Gateway

## Overview

Domain expertise for reaching many VPCs over a single Direct Connect connection through a Direct
Connect gateway. Covers the virtual private gateway path versus the transit gateway path, the
per-gateway association limits that customers hit with a cryptic error, the allowed prefixes list a
transit gateway association needs, the unique Autonomous System Number requirement, and the
cross-account proposal-and-acceptance handshake that trips up multi-account customers.

Does not cover creating the connection, the virtual interface and BGP details (a separate
reference), encryption, or the virtual-private-gateway-to-transit-gateway migration (its own
reference). Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region`. A Direct Connect gateway is a global resource reached through a
regional view.

## Table of Contents

- Overview
- Decision: virtual private gateway vs transit gateway
- Association limits per Direct Connect gateway
- Allowed prefixes and unique ASN
- Cross-account proposal and acceptance
- VPC-to-VPC behavior
- Troubleshooting
- Procedure
- Additional Resources

## Decision: virtual private gateway vs transit gateway

| Path | Virtual interface | Use when |
| --- | --- | --- |
| Virtual private gateway | Private virtual interface | A single VPC, or a small fixed set, reached through the Direct Connect gateway |
| Transit gateway | Transit virtual interface | Many VPCs, hub-and-spoke, multiple accounts, or multiple Regions |

**Constraints:**

- You MUST NOT mix virtual private gateway and transit gateway associations on the same Direct
  Connect gateway; an attempt to attach a transit gateway when the gateway already has a virtual
  private gateway association (or a private virtual interface) is rejected.
- You MUST check the gateway's existing associations before proposing the transit gateway path.

## Association limits per Direct Connect gateway

Customers hit these, get a cryptic error, and do not know they need an increase or a second gateway.

| Limit | Value | Increasable |
| --- | --- | --- |
| Virtual private gateways per Direct Connect gateway | 20 | No |
| Transit gateways per Direct Connect gateway | 6 | No |

**Constraints:**

- You MUST check the current association count against the limit before adding another association.
- When the limit is the blocker, you MUST name the options: split across multiple Direct Connect
  gateways.

## Allowed prefixes and unique ASN

**Constraints:**

- For a transit gateway association, you MUST provision the allowed prefixes list on the Direct
  Connect gateway; left empty, on-premises traffic never reaches the VPCs and there is no error.
- You MUST use different Autonomous System Numbers for the transit gateway and the Direct Connect
  gateway; the same ASN (default 64512) causes the association to fail.
- When more than one Region is in play, you MUST confirm each transit gateway uses a unique
  Autonomous System Number.

## Cross-account proposal and acceptance

Associating a Direct Connect gateway to a transit gateway in another account is a two-account
handshake, not a single call. This is one of the most common multi-account Direct Connect
escalations.

**Constraints:**

- You MUST run the handshake in order: the transit gateway owner creates an association proposal, and
  the Direct Connect gateway owner accepts it. The Direct Connect gateway owner can override the
  allowed prefixes at acceptance.
- You MUST NOT attempt a single direct association call across accounts; it does not work.

## VPC-to-VPC behavior

**Constraints:**

- You SHOULD set the expectation up front that VPCs attached to the same Direct Connect gateway do
  not, by default, talk to each other through it.
- You SHOULD warn that advertising a supernet that overlaps VPC CIDRs can cause unintended VPC-to-VPC
  traffic, and mitigate with specific prefixes, separate Direct Connect gateways, or transit gateway
  blackhole routes.

## Troubleshooting

### On-premises traffic does not reach the VPCs after a transit gateway association
The allowed prefixes list on the Direct Connect gateway is empty. Add the prefixes.

### Transit gateway association fails
The transit gateway ASN and the Direct Connect gateway ASN are identical. Change one.

### Adding another association returns a cryptic error
The per-gateway association limit (20 virtual private gateways or 6 transit gateways) is reached.
Split across gateways.

### Cross-account association does not work as a single call
It requires the proposal-and-acceptance handshake. The transit gateway owner proposes; the Direct
Connect gateway owner accepts.

## Procedure

### Overview

This procedure picks the association path, checks the gateway's existing associations and the
per-gateway limit, creates the association with allowed prefixes (running the cross-account handshake
when accounts differ), and surfaces the console link.

### Parameters

- **direct_connect_gateway_id** (required): The Direct Connect gateway ID (create one if needed).
- **association_target** (required): `vgw` or `tgw`, with the gateway ID.
- **allowed_prefixes** (required for transit gateway): The CIDRs to advertise to on-premises.
- **cross_account** (required): Whether the target gateway is in a different account.
- **transit_gateway_asn** / **dx_gateway_asn** (required for transit gateway): Distinct ASNs.

**Constraints for parameter acquisition:**

- You MUST ask for the association target, allowed prefixes, and whether it is cross-account upfront.

### Steps

#### 1. Verify dependencies and existing associations

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST check the Direct Connect gateway's existing associations and confirm the count is below the
  per-gateway limit:

  ```
  aws directconnect describe-direct-connect-gateway-associations \
    --direct-connect-gateway-id {direct_connect_gateway_id} --region {region}
  ```

#### 2. Create the association (same account)

**Constraints:**

- For a transit gateway in the same account, you MUST set distinct ASNs and provide the allowed
  prefixes:

  ```
  aws directconnect create-direct-connect-gateway-association \
    --direct-connect-gateway-id {direct_connect_gateway_id} --gateway-id {tgw_id} \
    --add-allowed-prefixes-to-direct-connect-gateway cidr={prefix} --region {region}
  ```

- You SHOULD remind the customer that traffic over the Direct Connect gateway association is not
  encrypted in transit by default, and point them to the encrypting-traffic reference if the workload
  requires encryption.

#### 3. Run the cross-account handshake (different accounts)

**Constraints:**

- The transit gateway owner MUST create the proposal:

  ```
  aws directconnect create-direct-connect-gateway-association-proposal \
    --direct-connect-gateway-id {direct_connect_gateway_id} \
    --direct-connect-gateway-owner-account {dx_gw_owner} --gateway-id {tgw_id} \
    --add-allowed-prefixes-to-direct-connect-gateway cidr={prefix} --region {region}
  ```

- The Direct Connect gateway owner MUST accept it (and may override prefixes):

  ```
  aws directconnect accept-direct-connect-gateway-association-proposal \
    --direct-connect-gateway-id {direct_connect_gateway_id} --proposal-id {proposal_id} \
    --associated-gateway-owner-account {tgw_owner} --region {region}
  ```

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST confirm the association reaches `associated` state by polling:

  ```
  aws directconnect describe-direct-connect-gateway-associations \
    --direct-connect-gateway-id {direct_connect_gateway_id} \
    --query "directConnectGatewayAssociations[?associatedGateway.id=='{tgw_id}'].associationState" \
    --output text --region {region}
  ```

  Poll until state reports `associated`.

- You MUST present the Direct Connect gateway console link, filling `{direct_connect_gateway_id}` and `{region}`:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/dxgateways/{direct_connect_gateway_id}
  ```

- You SHOULD recommend CloudWatch alarms on the gateway association state, and confirm CloudTrail is
  capturing `directconnect` API calls with log file validation enabled and the trail encrypted with a
  KMS key, and any CloudWatch Logs log groups receiving these events or alarm state data encrypted with
  a KMS key, so state changes trigger alerts and configuration changes are audited with assured log
  integrity and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel, so sensitive
  gateway association state data does not reach unintended recipients.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the link. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Direct Connect gateways (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/direct-connect-gateways-intro.html)
- [Direct Connect gateways and transit gateway associations (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/direct-connect-transit-gateways.html)
- [Associating and disassociating Direct Connect gateways across accounts (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/multi-account-associate-tgw.html)
- [Direct Connect virtual interfaces and hosted virtual interfaces (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/WorkingWithVirtualInterfaces.html)
