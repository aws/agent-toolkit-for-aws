# Migrating Direct Connect from a Virtual Private Gateway to a Transit Gateway

## Overview

Domain expertise for moving a Direct Connect setup from the virtual private gateway model to the
transit gateway model without dropping production traffic. Covers why the two paths use different
virtual interface types, why a separate Direct Connect gateway is needed rather than an in-place
conversion, the cutover order that keeps traffic flowing, and the allowed prefixes and unique
Autonomous System Number requirements that block the new path silently if missed.

Does not cover the first-time connection or virtual interface setup, the general Direct Connect
gateway reference (which this builds on), encryption, or resiliency. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region`. A Direct Connect gateway is a global resource reached through a
regional view.

## Table of Contents

- Overview
- Why the migration is order-dependent
- Separate Direct Connect gateway, not an in-place swap
- Allowed prefixes and unique ASN
- Troubleshooting
- Procedure
- Additional Resources

## Why the migration is order-dependent

The virtual private gateway path uses a private virtual interface; the transit gateway path uses a
transit virtual interface to a Direct Connect gateway. The safe migration builds the transit path
alongside the existing one and removes the old path last.

**Constraints:**

- You MUST build and verify the new transit path end to end before removing the old virtual private
  gateway path. Tearing down the old path before the new one carries traffic drops production
  connectivity, and this ordering is the entire point of the use case.

## Separate Direct Connect gateway, not an in-place swap

**Constraints:**

- You MUST provision a separate Direct Connect gateway for the transit path rather than converting the
  existing one in place, because a single Direct Connect gateway cannot hold both virtual private
  gateway and transit gateway associations at the same time.

## Allowed prefixes and unique ASN

**Constraints:**

- You MUST set the allowed prefixes list on the transit gateway association; left empty, on-premises
  traffic never reaches the VPCs and there is no error.
- You MUST use different Autonomous System Numbers for the transit gateway and the Direct Connect
  gateway; the same ASN causes the association to fail.

## Troubleshooting

### Traffic dropped during the cutover
The old virtual private gateway path was removed before the transit path was advertising routes. Build
and verify the new path first; remove the old one last.

### Cannot convert the existing Direct Connect gateway to transit
One Direct Connect gateway cannot hold both association types. Provision a separate Direct Connect
gateway for the transit path.

### Transit gateway association fails
The transit gateway and Direct Connect gateway share an Autonomous System Number. Change one.

### New path is up but on-premises traffic does not reach the VPCs
The allowed prefixes list on the transit gateway association is empty. Add the prefixes.

## Procedure

### Overview

This procedure builds the transit path on a new Direct Connect gateway, verifies it end to end, shifts
traffic, and removes the old virtual private gateway path last, surfacing the console link.

### Parameters

- **existing_private_vif_id** (required): The current private virtual interface on the virtual private
  gateway path.
- **new_dx_gateway_id** (required): A new Direct Connect gateway for the transit path.
- **transit_gateway_id** (required): The transit gateway to associate.
- **transit_gateway_asn** / **dx_gateway_asn** (required): Distinct Autonomous System Numbers.
- **allowed_prefixes** (required): The CIDRs to advertise to on-premises over the transit path.
- **region** (required): The AWS Region for CLI commands.

**Constraints for parameter acquisition:**

- You MUST confirm distinct ASNs and the allowed prefixes before creating the transit association.

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm the existing virtual private gateway path is healthy so there is a known-good
  fallback during the migration.

#### 2. Build the transit path alongside the old one

**Constraints:**

- You MUST create a separate Direct Connect gateway and a transit virtual interface for the transit
  path, leaving the existing private virtual interface in place and carrying traffic.
- You MUST create the transit gateway association with distinct ASNs and the allowed prefixes:

  ```
  aws directconnect create-direct-connect-gateway-association \
    --direct-connect-gateway-id {new_dx_gateway_id} --gateway-id {transit_gateway_id} \
    --add-allowed-prefixes-to-direct-connect-gateway cidr={allowed_prefixes} --region {region}
  ```

  Capture the `associationId` from the response as `{association_id}`.
- You MUST poll until the association reaches `associated` state:

  ```
  aws directconnect describe-direct-connect-gateway-associations \
    --association-id {association_id} \
    --query 'directConnectGatewayAssociations[0].associationState' --output text --region {region}
  ```

#### 3. Verify the new path end to end

**Constraints:**

- You MUST confirm the transit virtual interface BGP session is up and the association reaches
  `associated` state, and confirm routes advertise both ways, before shifting traffic.
- You SHOULD recommend CloudWatch alarms on the new transit virtual interface and Direct Connect
  gateway association state, and confirm CloudTrail is capturing `directconnect` API calls with log
  file validation enabled and the trail encrypted with a KMS key, and any CloudWatch Logs log groups
  receiving these events or alarm state data encrypted with a KMS key, so state changes trigger alerts
  and configuration changes are audited with assured log integrity and confidentiality rather than
  relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.
- You SHOULD remind the customer that traffic over the new transit path is not encrypted in transit by
  default, and point them to the encrypting-traffic reference if the workload requires encryption.

#### 4. Shift traffic, then remove the old path last

**Constraints:**

- You MUST shift traffic to the transit path and confirm it carries production traffic before removing
  the old virtual private gateway path.
- You MUST remove the old private virtual interface and virtual private gateway association only after
  the transit path is confirmed carrying traffic.

#### 5. Surface the console link

**Constraints:**

- You MUST present the new Direct Connect gateway console link, filling `{new_dx_gateway_id}` and
  `{region}`:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/dxgateways/{new_dx_gateway_id}
  ```

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the new transit path. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Migrating from a virtual private gateway to AWS Transit Gateway on Amazon VPC (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/migrating-from-virtual-private-gateway-to-aws-transit-gateway-on-amazon-vpc/)
- [Direct Connect gateways (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/direct-connect-gateways-intro.html)
- [Direct Connect gateways and transit gateway associations (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/direct-connect-transit-gateways.html)
- [Direct Connect virtual interfaces and hosted virtual interfaces (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/WorkingWithVirtualInterfaces.html)
