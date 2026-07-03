# Connecting On-Premises Networks Over VPN or Direct Connect

## Overview

Domain expertise for the transit gateway side of reaching on-premises data centers through one hub,
over a Site-to-Site VPN or AWS Direct Connect, instead of a separate tunnel into each VPC. Covers
the static-versus-dynamic VPN routing difference, equal-cost multi-path (ECMP) across multiple
tunnels and what it requires, the accelerated Site-to-Site VPN option, and the association and
propagation wiring that decides where on-premises routes land.

Does not cover the Direct Connect gateway and virtual interface setup, which belongs to the
`directconnect` skill. This reference covers the transit-gateway-side configuration only. Creating
the hub, segmentation, egress, peering, and multicast are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every command
in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Decision: static vs dynamic VPN routing
- ECMP across multiple tunnels
- Accelerated Site-to-Site VPN
- Association and propagation wiring
- Direct Connect side belongs to the directconnect skill
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To connect on-premises over the transit gateway end to end, follow the procedure exactly. See the
Procedure section below. It covers creating the VPN attachment (or, for Direct Connect, associating
the Direct Connect gateway after the directconnect skill has set it up), choosing the routing model,
deciding on ECMP and accelerated VPN, wiring association and propagation, and surfacing the console
link to verify.

## Decision: static vs dynamic VPN routing

| Routing | Behavior |
| --- | --- |
| Dynamic (BGP) | The Site-to-Site VPN learns and filters routes via BGP. Supports ECMP across tunnels |
| Static | The customer adds routes by hand. Static routes that target a VPN attachment are not filtered by the Site-to-Site VPN, which can allow unintended outbound traffic |

**Constraints:**

- You MUST call out that static routes targeting a VPN attachment are not filtered, when the
  customer picks static
- You MUST add the static routes to the transit gateway route table as a required step when static
  is chosen
- You SHOULD prefer dynamic (BGP) routing where the customer gateway device supports it

## ECMP across multiple tunnels

Customers attach multiple Site-to-Site VPN tunnels to aggregate bandwidth and expect the traffic to
spread, then find it pins to one tunnel. Equal-cost multi-path (ECMP) routing is only supported with
dynamic (BGP) routing, not static, and only when the tunnels terminate on the same transit gateway.

**Constraints:**

- You MUST confirm BGP is in use before promising bandwidth aggregation across tunnels
- You MUST confirm the tunnels terminate on the same transit gateway for ECMP to apply
- You MUST NOT promise aggregation for static tunnels, since they will not spread load

## Accelerated Site-to-Site VPN

When a customer chooses VPN over Direct Connect for cost or simplicity, the accelerated
Site-to-Site VPN option routes the tunnel over the AWS global network through Global Accelerator
edge locations and materially improves latency and jitter. It is set at VPN creation and is not
discoverable in the standard flow.

**Constraints:**

- You SHOULD surface accelerated VPN as a decision point when the customer chooses VPN, so they can
  weigh the performance gain before the connection is built
- You MUST set the accelerated option at VPN creation, since it cannot be toggled on an existing VPN

## Association and propagation wiring

After the attachment, on-premises prefixes only reach the VPCs whose attachments share a route table
with the path. Finishing the attachment does not make on-premises routes appear everywhere.

**Constraints:**

- You MUST confirm the association and propagation wiring so the hybrid routes land where the
  customer expects
- You MUST verify the on-premises prefixes reach the intended VPC attachments, not assume they
  propagate everywhere

## Direct Connect side belongs to the directconnect skill

Associating a Direct Connect gateway with the transit gateway, assigning a unique Autonomous System
Number per transit gateway, and checking the Direct Connect gateway is free of conflicting virtual
private gateway or private virtual interface bindings are Direct Connect concerns.

**Constraints:**

- You MUST route the Direct Connect gateway and virtual interface setup to the `directconnect`
  skill, specifically the "connecting many VPCs through a Direct Connect gateway" reference
- You MUST NOT restate the Direct Connect side here; cover only the transit gateway association once
  the Direct Connect gateway exists

## Security considerations

Hybrid connectivity extends the trust boundary to an on-premises network over a tunnel that carries
sensitive traffic and connection state, so encryption, credential handling, and route hygiene matter
here. The controls are embedded in the procedure; this section consolidates them.

**Constraints:**

- You MUST set Site-to-Site VPN tunnel options that enforce strong encryption (IKEv2 with AES-256 and
  AES256-GCM-16) rather than relying on AWS defaults, which may permit weaker ciphers
- You MUST, when a customer-specified pre-shared key (PSK) is used (via `TunnelOptions[].PreSharedKey`),
  store and retrieve it from AWS Secrets Manager, never hardcoding it in scripts or configuration
  files; prefer the AWS-generated PSK when no specific value is required
- You MUST call out that static routes targeting a VPN attachment are not filtered and can allow
  unintended outbound traffic, and SHOULD prefer dynamic (BGP) routing where the customer gateway
  device supports it
- You SHOULD enable Site-to-Site VPN tunnel logging to CloudWatch Logs with encryption enabled, since
  the logs carry connection state and IKE negotiation detail
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail (encrypted) to
  detect unauthorized changes to attachments, route tables, associations, and propagations
- You MUST, when a KMS key encrypts a flow log, tunnel log, or CloudTrail destination, scope the KMS
  key policy with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`) so only the
  specific log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### Unintended outbound traffic over a static VPN
Static routes to a VPN attachment are not filtered. Tighten the routes or move to dynamic (BGP).

### Multiple VPN tunnels do not aggregate bandwidth
ECMP needs BGP and tunnels on the same transit gateway. Confirm both; static will not aggregate.

### VPN performance is poor over the public internet
The accelerated VPN option was not chosen. It must be set at creation; recreate the VPN to enable it.

### On-premises routes do not reach a VPC
The attachment does not share a route table with the path. Fix the association and propagation.

## Procedure

### Overview

This procedure creates the VPN attachment with the right routing model, decides ECMP and
accelerated VPN, wires association and propagation, and surfaces the console link to verify. For
Direct Connect, it assumes the directconnect skill has set up the Direct Connect gateway.

### Parameters

- **region** (required): The Region that holds the hub.
- **transit_gateway_id** (required): The transit gateway.
- **connection_type** (required): `vpn` or `directconnect`.
- **vpn_routing** (required for VPN): `dynamic` or `static`.
- **customer_gateway_id** (required for VPN): The customer gateway device.
- **accelerated** (optional for VPN): Whether to use the accelerated VPN option.
- **dx_gateway_id** (required for Direct Connect): The Direct Connect gateway ID created by the directconnect skill.
- **allowed_prefix** (required for Direct Connect): The CIDR prefix to allow through the Direct Connect gateway association.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST ask whether bandwidth aggregation across tunnels is needed (decides BGP and ECMP)

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST, for Direct Connect, confirm the directconnect skill has created the Direct Connect
  gateway before associating it
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  for traffic visibility, audit, and incident response across every attached network. These logs
  carry sensitive traffic data, so you MUST enable encryption at rest on the destination (a KMS key
  on the CloudWatch log group, or SSE-KMS on the S3 bucket)
- You SHOULD enable AWS CloudTrail to record transit gateway attachment, route table, association,
  and propagation changes for audit and unauthorized-change detection, and you MUST enable encryption
  at rest on the CloudTrail destination (a KMS key)
- You MUST, when a KMS key encrypts a flow log destination (CloudWatch log group or S3 bucket) or the
  CloudTrail destination, scope the KMS key policy with condition keys (`aws:SourceArn`,
  `aws:SourceAccount`, and `kms:ViaService`) so only the specific log group, bucket, or trail in the
  expected account and service can use the key, preventing cross-account or cross-service misuse
- You SHOULD create CloudWatch alarms for transit gateway attachment creation and deletion, route
  table changes, and failed or blocked attachment states, so that unexpected or unauthorized changes
  and failure conditions are surfaced for investigation rather than discovered after impact

#### 2. Create the VPN attachment (VPN path)

**Constraints:**

- You MUST create the Site-to-Site VPN attached to the transit gateway, with the chosen routing and
  accelerated option (a single call creates both the VPN connection and the transit gateway VPN
  attachment). You MUST set tunnel options that enforce strong encryption (IKEv2 with AES-256 and
  AES256-GCM-16) rather than relying on AWS defaults, which may permit weaker ciphers. Phase 1 uses
  AES-256-CBC, which is not AEAD, so you MUST also pin `Phase1IntegrityAlgorithms` and
  `Phase1DHGroupNumbers` (otherwise AWS fills them in and may permit SHA-1 or weak Diffie-Hellman
  groups such as Group 2); Phase 2's AES256-GCM-16 is AEAD and needs no separate integrity
  algorithm, but pin `Phase2DHGroupNumbers` for forward secrecy:

  ```
  aws ec2 create-vpn-connection --type ipsec.1 \
    --customer-gateway-id {customer_gateway_id} \
    --transit-gateway-id {transit_gateway_id} \
    --options "EnableAcceleration={accelerated},StaticRoutesOnly={static_only},TunnelOptions=[{IKEVersions=[{Value=ikev2}],Phase1EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-512}],Phase1DHGroupNumbers=[{Value=20}],Phase2EncryptionAlgorithms=[{Value=AES256-GCM-16}],Phase2DHGroupNumbers=[{Value=20}]},{IKEVersions=[{Value=ikev2}],Phase1EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-512}],Phase1DHGroupNumbers=[{Value=20}],Phase2EncryptionAlgorithms=[{Value=AES256-GCM-16}],Phase2DHGroupNumbers=[{Value=20}]}]" \
    --region {region}
  ```

- You MUST capture the `VpnConnectionId` from the response
- You MUST poll until the VPN connection reaches `available`:

  ```
  aws ec2 describe-vpn-connections \
    --vpn-connection-ids {vpn_connection_id} --region {region}
  ```

- You MUST add static routes to the transit gateway route table when `vpn_routing` is static
- You MUST, when a customer-specified pre-shared key (PSK) is used for an IPsec tunnel (via
  `TunnelOptions[].PreSharedKey`), store and retrieve it from AWS Secrets Manager, never hardcoding
  it in scripts or configuration files. Prefer the AWS-generated PSK when the customer has no
  requirement for a specific value
- You SHOULD enable Site-to-Site VPN tunnel logging to CloudWatch Logs for visibility into tunnel
  state changes, IKE negotiation failures, and dead peer detection events, which are critical for
  troubleshooting connectivity and detecting unauthorized connection attempts. These logs carry
  connection state and IKE negotiation detail, so you MUST enable encryption (a KMS key) on the
  destination CloudWatch log group

#### 3. Associate the Direct Connect gateway (Direct Connect path)

**Constraints:**

- You MUST create the association from the transit gateway to the Direct Connect gateway the
  directconnect skill set up:

  ```
  aws directconnect create-direct-connect-gateway-association \
    --direct-connect-gateway-id {dx_gateway_id} \
    --gateway-id {transit_gateway_id} \
    --add-allowed-prefixes-to-direct-connect-gateway cidr={allowed_prefix} --region {region}
  ```

- You MUST poll the association state until it reaches `associated` (this is an async operation that can take several minutes):

  ```
  aws directconnect describe-direct-connect-gateway-associations \
    --direct-connect-gateway-id {dx_gateway_id} --region {region}
  ```

- You MUST NOT configure the Direct Connect gateway or virtual interface here

#### 4. Wire association and propagation

**Constraints:**

- You MUST associate the attachment with the route table whose VPCs should reach on-premises, and
  propagate on-premises routes into the tables that need them
- You MUST verify the on-premises prefixes reach the intended attachments

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm the attachment is `available`:

  ```
  aws ec2 describe-transit-gateway-attachments \
    --filters Name=transit-gateway-id,Values={transit_gateway_id} --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`
  from the API response, and tell the customer to open it and verify the attachment and routes:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayDetails:transitGatewayId={transit_gateway_id}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-0abc",
  "connection_type": "vpn",
  "vpn_routing": "dynamic",
  "customer_gateway_id": "cgw-0def",
  "accelerated": true
}
```

#### Example output

```
Created an accelerated Site-to-Site VPN with dynamic (BGP) routing and attached it to tgw-0abc.
ECMP available: BGP in use and tunnels terminate on the same transit gateway.
Associated the attachment with the route table whose VPCs reach on-premises; propagated on-premises
routes into it.
Open the transit gateway console and verify the attachment and routes:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayDetails:transitGatewayId=tgw-0abc
```

### Troubleshooting

#### Tunnels do not aggregate bandwidth
ECMP needs BGP and tunnels on one transit gateway. Confirm both (ECMP across multiple tunnels).

#### Poor VPN performance
Accelerated VPN was not enabled at creation. Recreate with the accelerated option (Step 2).

#### On-premises routes missing from a VPC
Association or propagation is wrong. Fix the wiring (Step 4).

## Additional Resources

- [AWS Site-to-Site VPN attachments in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-vpn-attachments.html)
- [Create a transit gateway attachment to a VPN in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/create-vpn-attachment.html)
- [Accelerated Site-to-Site VPN connections (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/accelerated-vpn.html)
- [Transit gateway attachments to a Direct Connect gateway in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-dcg-attachments.html)
