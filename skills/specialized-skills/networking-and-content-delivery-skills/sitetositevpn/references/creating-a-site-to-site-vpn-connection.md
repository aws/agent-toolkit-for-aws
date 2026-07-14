# Creating a Site-to-Site VPN Connection

## Overview

Domain expertise for building an AWS Site-to-Site VPN connection: an encrypted IP Security (IPsec)
tunnel between an on-premises network and a VPC. Covers the target gateway decision (virtual private
gateway, transit gateway, or AWS Cloud WAN), the fixed order of the dependent resources, the
customer gateway as metadata only, the distinct-ASN rule for a virtual private gateway, and
choosing tunnel options at create time.

Does not cover the routing-type decision (the choosing-static-or-dynamic-routing reference), tunnel
bandwidth sizing (the choosing-tunnel-bandwidth reference), the VPN Concentrator (its own
reference), or applying the device configuration (the applying-the-customer-gateway-device-configuration
reference). Settle routing type before running this procedure.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Site-to-Site VPN is regional; pass
`--region {region}` matching the VPC or transit gateway the connection terminates on.

## Table of Contents

- Overview
- Workflow
- Decision: target gateway
- Creation order
- The customer gateway is metadata only
- Distinct ASNs for a virtual private gateway
- Tunnel options at create time
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To build the connection end to end, follow the procedure exactly. See the Procedure section below.

The procedure covers:

- Choosing the target gateway based on how many VPCs and how much throughput the customer needs
- Creating the customer gateway resource that describes the on-premises device
- Creating or selecting the target gateway and attaching it to the VPC
- Enabling route propagation or adding routes, and updating the security group
- Creating the VPN connection with the chosen routing and tunnel options
- Surfacing the console link to verify status and download the device configuration

## Decision: target gateway

| Choice | Use when |
| --- | --- |
| Virtual private gateway (VGW) | The VPN terminates at a single VPC and the customer needs no more than 1.25 Gbps per tunnel |
| Transit gateway | The VPN fronts many VPCs, needs Large (5 Gbps) tunnels, needs ECMP bandwidth aggregation, or will use a VPN Concentrator |
| AWS Cloud WAN core network | The VPN attaches to a Cloud WAN core network |

**Constraints:**

- You MUST establish the target gateway first, tied to how many VPCs the customer must reach and
  how much throughput they need. It is the most consequential choice and gates bandwidth and Concentrator options
- You MUST tell the customer that a virtual private gateway cannot later be upgraded in place to
  Large tunnels or a Concentrator; reaching those means rebuilding on a transit gateway
- You SHOULD recommend a transit gateway when the customer needs more than one VPC or any feature a virtual private gateway does not support

## Creation order

The connection only works after several resources are in place in the right order. Creating the VPN
connection first and stopping there leaves traffic with nowhere to flow, and no single error points
at the missing piece.

**Constraints:**

- You MUST create the resources in this order: customer gateway, target gateway attached to the
  VPC, route propagation or routes, security group rule, then the VPN connection
- You MUST confirm each resource before moving to the next
- You MUST confirm route propagation (or static routes) and the security group rule before declaring the connection ready

## The customer gateway is metadata only

The customer gateway resource in AWS is only metadata: it gives AWS the device's public IP address
and routing details. Customers read "gateway" and assume creating it configures their device. It
does not; the device configuration is a separate step the customer owns.

**Constraints:**

- You MUST make clear that the customer gateway resource does not configure the on-premises device
- You SHOULD point the customer at the applying-the-customer-gateway-device-configuration reference for the device-side work

## Distinct ASNs for a virtual private gateway

When the target gateway is a virtual private gateway, the Autonomous System Number (ASN) on the AWS
side must differ from the customer gateway ASN, and the gateway must be attached to the VPC before
anything routes.

**Constraints:**

- You MUST set distinct ASNs on the AWS side and the customer gateway side for a virtual private gateway target
- You MUST confirm the gateway is attached to the VPC before expecting routes to flow

## Tunnel options at create time

Customers accept the default tunnel options at creation, then later need stronger algorithms and
discover that modifying tunnel or connection options replaces the tunnel endpoints and interrupts
connectivity.

**Constraints:**

- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) at create time, when changing them is free, rather than after the customer is in production
- You MUST warn that modifying tunnel options later replaces the tunnel endpoints and briefly interrupts the connection

## Troubleshooting

### Connection created but traffic does not flow
Route propagation or the security group rule is missing. Confirm both (Creation order).

### Connection never establishes on a virtual private gateway
The AWS-side and customer gateway ASNs match, or the gateway is not attached. Set distinct ASNs and attach (Distinct ASNs).

### Customer waits for AWS to configure their device
The customer gateway resource is metadata only. The device configuration is the customer's separate step (The customer gateway is metadata only).

### Customer needs more than 1.25 Gbps but built on a virtual private gateway
Large tunnels need a transit gateway. Rebuild the target gateway on a transit gateway (Decision).

## Procedure

### Overview

This procedure creates the customer gateway, the target gateway, the routing and security group
configuration, and the VPN connection in the required order, then surfaces the console link to
verify status and download the device configuration.

### Parameters

- **region** (required): The AWS Region of the VPC or transit gateway.
- **target_gateway_type** (required): `vpn-gateway`, `transit-gateway`, `core-network`, or `vpn-concentrator`. If the customer says `vpn-concentrator`, redirect to the connecting-many-sites-with-a-vpn-concentrator reference.
- **vpc_id** (required for a virtual private gateway or transit gateway target): The VPC the gateway attaches to.
- **transit_gateway_id** (required if using an existing transit gateway): The transit gateway the connection terminates on. If creating a new transit gateway, this is captured from the `create-transit-gateway` response in Step 3.
- **customer_gateway_ip** (required): The public IP address of the on-premises device.
- **routing_type** (required): `static` or `dynamic`, settled in the choosing-static-or-dynamic-routing reference.
- **customer_gateway_asn** (required): The BGP ASN of the customer gateway. `create-customer-gateway` always requires `--bgp-asn`. For dynamic routing, use the real ASN of the on-premises device. For static routing, supply a placeholder (for example, `65000`).
- **aws_side_asn** (required when creating a new virtual private gateway or transit gateway): The BGP ASN for the AWS side, which must differ from `customer_gateway_asn`. If the customer does not specify one, use the AWS default `64512`.
- **subnet_ids** (required for a transit gateway target): One subnet ID per Availability Zone for the transit gateway VPC attachment. Note: if the transit gateway VPC attachment already exists (managed by the transitgateway skill or another team), skip creating it in Step 3 and use the existing attachment.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the routing type is already decided before building

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST confirm the VPC (or transit gateway) and the on-premises device public IP exist before building

#### 2. Create the customer gateway

**Constraints:**

- You MUST create the customer gateway describing the on-premises device:

  ```
  aws ec2 create-customer-gateway --type ipsec.1 --public-ip {customer_gateway_ip} \
    --bgp-asn {customer_gateway_asn} --region {region}
  ```

- If the customer's BGP ASN is larger than 2,147,483,647 (a 32-bit ASN), you MUST use `--bgp-asn-extended` instead of `--bgp-asn`:

  ```
  aws ec2 create-customer-gateway --type ipsec.1 --public-ip {customer_gateway_ip} \
    --bgp-asn-extended {customer_gateway_asn} --region {region}
  ```

  `--bgp-asn` accepts values 1 to 2,147,483,647; `--bgp-asn-extended` accepts 2,147,483,648 to 4,294,967,295.
- You MUST capture the `CustomerGatewayId` from the response

#### 3. Create or select the target gateway and attach it

**Constraints:**

- You MUST create the chosen target gateway. For a virtual private gateway, create it and attach it to the VPC:

  ```
  aws ec2 create-vpn-gateway --type ipsec.1 --amazon-side-asn {aws_side_asn} --region {region}
  aws ec2 attach-vpn-gateway --vpn-gateway-id {vpn_gateway_id} --vpc-id {vpc_id} --region {region}
  ```

- For a transit gateway, create it (or select an existing one) and attach it to the VPC. The VPN connection is associated with the transit gateway in Step 5; the VPC attachment carries VPN traffic into the VPC:

  ```
  aws ec2 create-transit-gateway --options AmazonSideAsn={aws_side_asn} --region {region}
  aws ec2 create-transit-gateway-vpc-attachment --transit-gateway-id {transit_gateway_id} \
    --vpc-id {vpc_id} --subnet-ids {subnet_ids} --region {region}
  ```

- You MUST set an AWS-side ASN distinct from the customer gateway ASN for a virtual private gateway

#### 4. Enable routing and update the security group

**Constraints:**

- You MUST enable route propagation on the subnet route table (or add static routes) so the subnet can reach the on-premises network
- You MUST update the security group to permit the on-premises traffic

#### 5. Create the VPN connection

**Constraints:**

- You MUST create the connection against the target gateway and customer gateway, with the chosen routing type and tunnel options. For a virtual private gateway target, pass `--vpn-gateway-id`; for a transit gateway target, pass `--transit-gateway-id` instead:

  ```
  # Virtual private gateway target
  aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id {customer_gateway_id} \
    --vpn-gateway-id {vpn_gateway_id} \
    --pre-shared-key-storage SecretsManager \
    --options "StaticRoutesOnly={true_if_static},TunnelOptions=[{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]},{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]}]" \
    --region {region}

  # Transit gateway target
  aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id {customer_gateway_id} \
    --transit-gateway-id {transit_gateway_id} \
    --pre-shared-key-storage SecretsManager \
    --options "StaticRoutesOnly={true_if_static},TunnelOptions=[{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]},{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]}]" \
    --region {region}
  ```

- You MUST use `--pre-shared-key-storage SecretsManager` to store PSKs in AWS Secrets Manager so they are not returned as plain text in APIs like `describe-vpn-connections`; this incurs a small additional Secrets Manager cost per secret
- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You MUST supply two `TunnelOptions` objects, one per tunnel, since every connection has two tunnels; a single-element array leaves Tunnel 2 on the weak AES-128 / SHA-1 / DH group 2 defaults
- You SHOULD enable Site-to-Site VPN logs at create time so tunnel establishment and BGP events are captured from the start; see the monitoring-and-troubleshooting-tunnels reference for setup

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST confirm the connection and its tunnels reach the expected state:

  ```
  aws ec2 describe-vpn-connections --vpn-connection-ids {vpn_connection_id} --region {region}
  ```

- You MUST present the VPN connection console link, filling `{region}` and `{vpnConnectionId}` from
  the API response, and tell the customer to open it, confirm the connection, and download the
  device configuration:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#VpnConnectionDetails:VpnConnectionId={vpnConnectionId}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "target_gateway_type": "transit-gateway",
  "vpc_id": "vpc-0abc1234def567890",
  "subnet_ids": ["subnet-0abc1234def567890", "subnet-0fed9876cba543210"],
  "aws_side_asn": 64512,
  "customer_gateway_ip": "203.0.113.10",
  "routing_type": "dynamic",
  "customer_gateway_asn": 65010
}
```

#### Example output

```
Created customer gateway (203.0.113.10, ASN 65010) and the VPN connection on the transit gateway,
dynamic routing. Route propagation enabled and the security group updated.
Open the VPN connection in the console, confirm both tunnels, and download the device configuration:
https://console.aws.amazon.com/vpc/home?region=us-east-1#VpnConnectionDetails:VpnConnectionId=vpn-0abc1234def567890
```

### Troubleshooting

#### Traffic does not flow after creation
Route propagation or the security group rule is missing. Confirm both (Step 4).

#### Connection never establishes on a virtual private gateway
ASNs match or the gateway is not attached. Set distinct ASNs and attach (Step 3).

#### Customer expects AWS to configure their device
The customer gateway is metadata. Hand off to the applying-the-customer-gateway-device-configuration reference.

## Security Considerations

Creating the connection sets the authentication and encryption posture the tunnels run with, so the
security choices belong at create time, when changing them is free.

**Constraints:**

- You MUST treat tunnel pre-shared keys (PSKs) as secrets: never pass them on the command line or store them in plaintext, store them in AWS Secrets Manager, and rotate them periodically; where the device supports it, recommend certificate-based authentication with AWS Private Certificate Authority instead of a static PSK
- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You MUST scope the security group rule to the specific on-premises CIDR blocks and protocols the
  workload needs, not `0.0.0.0/0`
- You SHOULD set up monitoring by following the monitoring-and-troubleshooting-tunnels reference, which covers CloudWatch tunnel-state alarms, VPN logs, and CloudTrail audit logging
- You MUST enable encryption at rest on all log destinations (KMS on the CloudWatch Logs log groups holding the VPN/tunnel logs, and SSE-S3 or SSE-KMS on the S3 bucket holding the CloudTrail logs) since these logs can carry sensitive tunnel and connection details

## Additional Resources

- [Get started with AWS Site-to-Site VPN (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/SetUpVPNConnections.html)
- [Create an AWS Site-to-Site VPN connection (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/create-vpn-connection.html)
- [AWS Site-to-Site VPN single and multiple VPN connection examples (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/Examples.html)
- [AWS Site-to-Site VPN customer gateway devices (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/your-cgw.html)
- [Tunnel options for your AWS Site-to-Site VPN connection (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/VPNTunnels.html)
