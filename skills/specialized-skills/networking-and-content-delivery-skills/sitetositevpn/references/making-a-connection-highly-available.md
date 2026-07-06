# Making a Site-to-Site VPN Connection Highly Available

## Overview

Domain expertise for keeping an AWS Site-to-Site VPN connection up through tunnel maintenance and
on-premises device failure. Covers configuring the on-premises device to use both tunnels (which is
free), the BGP attribute settings that let AWS steer traffic to the healthy tunnel during endpoint
updates, the second-connection-on-a-second-device pattern for surviving device failure (which adds
cost), and the matching-advertisement requirement for clean failover.

Does not cover the routing-type decision (the choosing-static-or-dynamic-routing reference) or
monitoring (the monitoring-and-troubleshooting-tunnels reference). Assumes a connection exists (the
creating-a-site-to-site-vpn-connection reference).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region {region}` matching the connection.

## Table of Contents

- Overview
- Workflow
- Both tunnels first, at no extra cost
- BGP attributes for tunnel-update steering
- Second device for device failure, at added cost
- Matching advertisements for clean failover
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To make the connection highly available, configure both tunnels on the device, set matching BGP
attributes, and decide whether a second connection on a second device is warranted. See the
Procedure section below.

The procedure covers:

- Confirming both tunnels are configured on the on-premises device
- Setting matching Weight and Local Preference so AWS steering is honored
- Deciding whether to add a second connection on a second device for device-failure resilience
- Configuring both devices to advertise the same prefixes over BGP

## Both tunnels first, at no extra cost

Each connection provides two tunnels in different Availability Zones, but the redundancy only works
if the device is configured to use both, and customers commonly configure only one. There is no
added charge for using both tunnels: the VPN connection price covers both.

**Constraints:**

- You MUST treat configuring both tunnels as required, not optional
- You SHOULD reassure the customer there is no extra cost for the second tunnel; the connection price covers both

## BGP attributes for tunnel-update steering (dynamic routing only)

This section applies only to connections using dynamic (BGP) routing. For static routing connections,
AWS failover during tunnel updates is automatic and does not depend on BGP attributes.

AWS applies tunnel endpoint updates one tunnel at a time and steers traffic to the healthy tunnel
using a lower multi-exit discriminator (MED) value. That steering only takes effect if the device
uses the same Weight and Local Preference for both tunnels; different values override the AWS
preference and send traffic into the tunnel being updated.

**Constraints:**

- You MUST confirm the connection uses BGP before applying these BGP attribute settings
- You MUST set matching Weight and Local Preference on both tunnels so the AWS failover signal is honored
- You SHOULD explain that mismatched attributes send traffic into the tunnel AWS is taking down for maintenance

## Second device for device failure, at added cost

Two tunnels protect against an AWS-side device failure, but not against the customer's own gateway
device failing. Surviving the loss of the on-premises device requires a second VPN connection on a
separate customer gateway device. This is a real added cost: each connection bills per
connection-hour, so a redundant pair roughly doubles the connection charge.

**Constraints:**

- You MUST explain what a single connection does and does not protect against before the customer relies on it for production
- You MUST name the added cost of a second connection, in contrast to the free second tunnel
- You SHOULD frame the second device as a deliberate cost-for-resilience tradeoff

## Matching advertisements for clean failover

A redundant pair only fails over cleanly when both devices advertise the same prefixes to the
target gateway, and BGP is what detects the failure and reroutes. Mismatched prefixes or static
routing produce a setup that does not fail over as expected.

**Constraints:**

- You MUST configure both devices to advertise the same prefixes to the target gateway
- You SHOULD steer the customer toward BGP for the failure detection that drives failover

## Troubleshooting

### Connection drops during AWS maintenance
Only one tunnel is configured. Configure both (Both tunnels first).

### Traffic goes into the tunnel being updated
Weight and Local Preference differ between tunnels. Set them equal (BGP attributes for tunnel-update steering).

### Connection still drops when the on-premises device fails
A single connection does not cover device failure. Add a second connection on a second device (Second device for device failure).

### Redundant pair does not fail over cleanly
The two devices advertise mismatched prefixes, or static routing is in use. Advertise the same prefixes over BGP (Matching advertisements).

## Procedure

### Overview

This procedure confirms both tunnels are used, sets matching BGP attributes, and optionally adds a
second connection on a second device with matching advertisements, then surfaces the console link to
verify tunnel status.

### Parameters

- **region** (required): The AWS Region of the connection.
- **vpn_connection_id** (required): The primary connection.
- **needs_device_failover** (required): Whether the customer must survive the loss of the on-premises device.
- **second_customer_gateway_ip** (required if needs_device_failover): The public IP of the second device.

**Constraints for parameter acquisition:**

- You MUST establish whether device-failure resilience is needed, since it changes the cost
- You SHOULD confirm the connection uses BGP, since clean failover depends on it

### Steps

#### 1. Confirm both tunnels are used

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST confirm the on-premises device is configured to use both tunnels, at no extra cost

#### 2. Set matching BGP attributes

**Constraints:**

- You MUST set the same Weight and Local Preference on both tunnels so AWS steering during endpoint updates is honored

#### 3. Decide on a second device

**Constraints:**

- You MUST explain that two tunnels do not cover device failure, and a second connection on a second device does, at roughly double the connection cost
- You SHOULD proceed to add the second connection only if the customer accepts the cost for device-failure resilience

#### 4. Configure matching advertisements and confirm

**Constraints:**

- You MUST configure both devices to advertise the same prefixes over BGP if a second connection is added
- You MUST present the VPN connections console link, filling `{region}` from the request, and tell the customer to open it and confirm both connections and all tunnels:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#VpnConnections:
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "vpn_connection_id": "vpn-0abc1234def567890",
  "needs_device_failover": true,
  "second_customer_gateway_ip": "203.0.113.20"
}
```

#### Example output

```
Both tunnels configured on the primary device (no extra cost), with matching Weight and Local
Preference so AWS steering is honored. Customer accepted the added cost for device-failure
resilience: added a second connection on 203.0.113.20, both devices advertising the same prefixes over
BGP. Open the connections list and confirm both connections and all tunnels:
https://console.aws.amazon.com/vpc/home?region=us-east-1#VpnConnections:
```

### Troubleshooting

#### Drops during maintenance
Only one tunnel configured. Configure both (Step 1).

#### Traffic enters the tunnel being updated
Mismatched Weight and Local Preference. Set them equal (Step 2).

#### Device failure takes the connection down
Add a second connection on a second device (Step 3).

#### Redundant pair fails over poorly
Advertise the same prefixes over BGP on both devices (Step 4).

## Security Considerations

High availability adds tunnels and, with a second device, a second connection, each with its own
authentication secrets, so the redundant path must hold the same security posture as the primary.

**Constraints:**

- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums. Apply them to both tunnels and, where a second connection is added, to that connection too, so failover never lands on a weaker tunnel
- You MUST treat tunnel pre-shared keys (PSKs) as secrets: never pass them on the command line or store them in plaintext, store them in AWS Secrets Manager, and rotate them periodically; where the device supports it, recommend certificate-based authentication with AWS Private Certificate Authority instead of a static PSK. Use a distinct key per tunnel and per connection rather than reusing one key across the redundant pair
- You SHOULD set up monitoring by following the monitoring-and-troubleshooting-tunnels reference, which covers CloudWatch tunnel-state alarms, VPN logs, and CloudTrail audit logging
- You MUST enable encryption at rest on all log destinations (KMS on the CloudWatch Logs log groups holding the VPN/tunnel logs, and SSE-S3 or SSE-KMS on the S3 bucket holding the CloudTrail logs) since these logs can carry sensitive tunnel and connection details
- You SHOULD confirm both devices advertise only the intended prefixes over BGP so a failover does not
  expose prefixes the primary path would not

## Additional Resources

- [Resilience in AWS Site-to-Site VPN (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/disaster-recovery-resiliency.html)
- [Redundant AWS Site-to-Site VPN connections for failover (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/vpn-redundant-connection.html)
- [Routing during VPN tunnel endpoint updates (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/routing-vpn-tunnel-updates.html)
- [AWS VPN Pricing](https://aws.amazon.com/vpn/pricing/)
