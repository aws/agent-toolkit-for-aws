# Choosing Standard (1.25 Gbps) or Large (5 Gbps) Tunnel Bandwidth

## Overview

Decision expertise for sizing the tunnel bandwidth of an AWS Site-to-Site VPN connection. Covers the
two options (Standard, up to 1.25 Gbps per tunnel and the default; Large, up to 5 Gbps per tunnel),
the target gateway that gates Large, the per-connection scope that covers both tunnels, the path
requirements on the device and circuit, the in-place-modification limits, and the cost tradeoff
versus equal-cost multi-path (ECMP) routing.

This reference first helps the customer decide between Standard and Large based on their throughput
needs and target gateway, then applies the chosen setting on a new or existing connection. It
assumes the connection exists or is being created (the creating-a-site-to-site-vpn-connection
reference). It does not cover the VPN Concentrator, which scales many small sites rather than one
connection's throughput.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region {region}` matching the connection.

## Table of Contents

- Overview
- Workflow
- Decision: Standard or Large
- The target gateway gates Large
- Per-connection scope
- Path must support the bandwidth
- Switching bandwidth later
- Cost and ECMP
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To size tunnel bandwidth, gather the throughput need and the target gateway, match them to Standard
or Large, confirm the path supports it, and apply the setting. See the Procedure section below.

The procedure covers:

- Establishing the throughput the workload needs
- Confirming the target gateway supports Large
- Confirming the on-premises device and circuit support the higher throughput
- Setting Standard or Large at create or modify time

## Decision: Standard or Large

| Choice | Use when |
| --- | --- |
| Standard (1.25 Gbps per tunnel) | The workload needs no more than 1.25 Gbps per tunnel, or the connection is on a virtual private gateway |
| Large (5 Gbps per tunnel) | The workload needs high throughput (bandwidth-intensive hybrid apps, big data migration, Direct Connect backup or overlay) and the connection is on a transit gateway or Cloud WAN |

**Constraints:**

- You MUST establish the throughput need before recommending, since Large carries a higher cost
- You SHOULD recommend Large only when the workload genuinely needs more than 1.25 Gbps per tunnel

## The target gateway gates Large

Large (5 Gbps) tunnels are supported only on transit gateway and AWS Cloud WAN connections, not on a
virtual private gateway. A customer who needs more than 1.25 Gbps but already built on a virtual
private gateway cannot flip the setting; they must move to a transit gateway first.

**Constraints:**

- You MUST check the target gateway before offering Large; rule it out on a virtual private gateway
- You MUST tell the customer that needing high throughput points them at a transit gateway

## Per-connection scope

The bandwidth setting is per connection, not per tunnel. Standard and Large cannot coexist in the
same connection, and Large applies to both tunnels at once.

**Constraints:**

- You MUST state that the setting covers both tunnels and that one connection cannot mix Standard and Large
- You SHOULD explain that a single traffic flow maps to one tunnel, so exceeding one tunnel's ceiling needs multiple flows

## Path must support the bandwidth

Large bandwidth only delivers if the on-premises customer gateway device and the internet circuit
can handle the higher throughput. Otherwise the customer pays for 5 Gbps and never sees it.

**Constraints:**

- You MUST prompt the customer to confirm the device and circuit capacity before selecting Large
- You SHOULD note that the throughput ceiling is the lowest-capacity hop on the path, not the tunnel setting alone

## Switching bandwidth later

Modifying the bandwidth is supported in place only in select Regions; elsewhere the customer must
delete and recreate the connection. Any modification briefly interrupts the connection while it
applies.

**Constraints:**

- You MUST surface the bandwidth decision at create time and warn that changing it later may mean a recreate
- You MUST warn that any bandwidth modification briefly interrupts the connection

## Cost and ECMP

Large tunnels cost noticeably more per hour than Standard, so the choice is a real cost tradeoff.
ECMP can be used with both Standard and Large tunnels on a transit gateway. Customers who need
more than 1.25 Gbps but want to avoid ECMP complexity can use Large tunnels (up to 5 Gbps per
tunnel) as a simpler single-connection option. Customers who need more than 5 Gbps can use ECMP
with Large tunnels to scale beyond 5 Gbps aggregate.

**Constraints:**

- You MUST frame Large as a higher-cost option that removes ECMP complexity, not a free upgrade
- You SHOULD point customers needing more than 5 Gbps per tunnel at ECMP across multiple tunnels on a transit gateway

## Troubleshooting

### Large is not selectable
Large tunnels are not available on a virtual private gateway, on a VPN Concentrator (which has its own 5 Gbps aggregate model), or in Regions that do not support the feature. Check the [Region availability table](https://docs.aws.amazon.com/vpn/latest/s2svpn/VPNTunnels.html) and confirm the connection is on a transit gateway or Cloud WAN in a supported Region (The target gateway gates Large).

### Customer expects 10 Gbps from two 5 Gbps tunnels
The setting is per connection and a single flow uses one tunnel. Aggregate across flows or use ECMP (Per-connection scope, Cost and ECMP).

### Paid for Large but throughput is capped lower
The device or circuit is the bottleneck. Confirm path capacity (Path must support the bandwidth).

### Changing bandwidth caused an outage
Any modification briefly interrupts the connection, and outside select Regions it requires recreate (Switching bandwidth later).

## Procedure

### Overview

This procedure establishes the throughput need, confirms the target gateway and path support Large,
and applies Standard or Large at create or modify time, then surfaces the console link to verify.

### Parameters

- **region** (required): The AWS Region of the connection.
- **vpn_connection_id** (required for modify): The connection to modify.
- **target_gateway_type** (required): `vpn-gateway`, `transit-gateway`, `core-network`, or `vpn-concentrator`. If the customer says `vpn-concentrator`, redirect to the connecting-many-sites-with-a-vpn-concentrator reference since the Concentrator has its own bandwidth model.
- **throughput_need** (required): The per-tunnel throughput the workload needs.
- **bandwidth** (required): `Standard` or `Large`.

**Constraints for parameter acquisition:**

- You MUST ask for the throughput need and target gateway upfront
- You MUST NOT offer Large on a virtual private gateway

### Steps

#### 1. Establish throughput and gateway

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST establish the per-tunnel throughput the workload needs
- You MUST confirm the target gateway is a transit gateway or Cloud WAN before offering Large

#### 2. Confirm the path

**Constraints:**

- You MUST confirm the on-premises device and internet circuit support the chosen bandwidth before selecting Large

#### 3. Apply the bandwidth setting

**Constraints:**

- You MUST set the bandwidth at create time on a new connection, alongside the strong tunnel options
  (two `TunnelOptions` objects, one per tunnel, with AES-256, SHA2-256, and DH group 14):

  ```
  aws ec2 create-vpn-connection --type ipsec.1 --transit-gateway-id {tgw_id} \
    --customer-gateway-id {cgw_id} \
    --pre-shared-key-storage SecretsManager \
    --options "TunnelBandwidth=Large,TunnelOptions=[{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]},{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]}]" \
    --region {region}
  ```

- You MUST warn before modifying an existing connection that it briefly interrupts connectivity and may require recreate outside select Regions:

  ```
  aws ec2 modify-vpn-connection-options --vpn-connection-id {vpn_connection_id} \
    --tunnel-bandwidth Large --region {region}
  ```

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST confirm the connection reports the chosen bandwidth:

  ```
  aws ec2 describe-vpn-connections --vpn-connection-ids {vpn_connection_id} --region {region}
  ```

- You MUST present the VPN connection console link, filling `{region}` and `{vpnConnectionId}` from the API response:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#VpnConnectionDetails:VpnConnectionId={vpnConnectionId}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "target_gateway_type": "transit-gateway",
  "throughput_need": "3 Gbps",
  "bandwidth": "Large"
}
```

#### Example output

```
Recommendation: Large (5 Gbps) tunnels. The workload needs 3 Gbps, above the 1.25 Gbps Standard
ceiling, and the connection is on a transit gateway, which supports Large. Confirmed the on-premises
device and circuit handle 3 Gbps+. Set TunnelBandwidth=Large at create time.
Open the connection in the console to confirm bandwidth:
https://console.aws.amazon.com/vpc/home?region=us-east-1#VpnConnectionDetails:VpnConnectionId=vpn-0abc1234def567890
```

### Troubleshooting

See the Troubleshooting section above for common issues (Large not available, throughput capped, modification interruptions).

## Security Considerations

The bandwidth setting does not change the connection's authentication or encryption, but it is set on
the same `create-vpn-connection` and `modify-vpn-connection-options` calls that carry the tunnel
security options, so the security posture must not be dropped when sizing bandwidth.

**Constraints:**

- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You MUST NOT let a bandwidth change reset tunnel options to weaker defaults; preserve them when modifying a connection
- You MUST treat tunnel pre-shared keys (PSKs) as secrets: never pass them on the command line or store them in plaintext, store them in AWS Secrets Manager, and rotate them periodically; where the device supports it, recommend certificate-based authentication with AWS Private Certificate Authority instead of a static PSK
- You SHOULD remind the customer that a bandwidth modification re-establishes the tunnels, so they
  must confirm the encryption and authentication settings still match policy afterward
- You SHOULD set up monitoring by following the monitoring-and-troubleshooting-tunnels reference, which covers CloudWatch tunnel-state alarms, VPN logs, and CloudTrail audit logging
- You MUST enable encryption at rest on all log destinations (KMS on the CloudWatch Logs log groups holding the VPN/tunnel logs, and SSE-S3 or SSE-KMS on the S3 bucket holding the CloudTrail logs) since these logs can carry sensitive tunnel and connection details

## Additional Resources

- [Tunnel options for your AWS Site-to-Site VPN connection (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/VPNTunnels.html)
- [Modify AWS Site-to-Site VPN connection options (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/modify-vpn-connection-options.html)
- [Introducing AWS Site-to-Site VPN 5 Gbps Tunnels to support high throughput workloads (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-aws-site-to-site-vpn-5-gbps-tunnels-to-support-high-throughput-workloads/)
- [Scaling VPN throughput using AWS Transit Gateway (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/scaling-vpn-throughput-using-aws-transit-gateway/)
- [AWS VPN Pricing](https://aws.amazon.com/vpn/pricing/)
