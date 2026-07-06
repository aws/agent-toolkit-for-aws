# Choosing Static or Dynamic (BGP) Routing for a Site-to-Site VPN Connection

## Overview

Decision expertise for picking how routes are exchanged between an on-premises network and a VPC
before creating an AWS Site-to-Site VPN connection. Covers the two routing types (static, where the
customer enters on-premises prefixes by hand, and dynamic, where the customer gateway and the AWS
gateway exchange routes over Border Gateway Protocol), the device capability that gates the choice,
the failover difference, the deliberate use of static routing for route control, and the
Autonomous System Number (ASN) that dynamic routing requires.

This reference makes and explains a recommendation. It does not create the connection. Once the
routing type is settled, the creating-a-site-to-site-vpn-connection reference covers the build. It
does not cover tunnel bandwidth sizing or the customer gateway device configuration; those are
separate references.

## Table of Contents

- Overview
- Workflow
- Decision: static or dynamic routing
- BGP support gates the choice
- Static routing as deliberate route control
- Failover difference
- ASN for dynamic routing
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To recommend a routing type, gather the customer's device capability and route-control needs, match
them against the decision table, and explain the recommendation. See the Procedure section below.

The procedure covers:

- Confirming whether the on-premises device supports BGP
- Establishing whether the customer needs to control which routes enter their network
- Matching the requirements to static or dynamic routing
- Explaining the failover and ASN consequences of the choice

## Decision: static or dynamic routing

| Choice | Use when |
| --- | --- |
| Dynamic (BGP) | The on-premises device supports BGP and the customer wants automatic route exchange and BGP-assisted failover between tunnels |
| Static | The device does not support BGP, or the customer deliberately wants to control which on-premises routes enter the AWS network. On a BGP-capable device, dynamic routing with BGP prefix filtering is the other way to control which routes are admitted |

**Constraints:**

- You MUST confirm whether the on-premises device supports BGP before recommending a routing type.
  The right answer depends on the customer's device and intent, not a fixed rule
- You MUST NOT recommend dynamic routing for a device that does not support BGP
- You SHOULD default to dynamic routing for a BGP-capable device unless the customer has a route-control reason to choose static

## BGP support gates the choice

Dynamic routing requires a BGP-capable customer gateway device. Recommending it for a device that
does not support BGP leaves the customer stuck at the customer gateway step.

**Constraints:**

- You MUST verify BGP support on the on-premises device before offering dynamic routing
- You SHOULD ask the customer for the device make and model if BGP support is unknown, rather than assuming

## Static routing as deliberate route control

Some customers choose static routing on a BGP-capable device on purpose. When connecting to a
partner network, static routing lets the customer write only the specific partner prefixes they
approve, rather than accepting everything the partner advertises over BGP. This is common in
regulated industries such as banking and financial services.

On a BGP-capable device, static routing is not the only way to control which routes are admitted:
dynamic routing with BGP prefix filtering lets the customer accept only approved partner prefixes
while keeping the automatic route exchange and BGP-assisted failover that dynamic routing provides.
Static routing gives the simplest, most explicit control; BGP prefix filtering gives route control
without giving up dynamic failover.

**Constraints:**

- You MUST treat static routing as a valid deliberate choice when the customer wants to control
  which routes enter their network, not only as a fallback for devices without BGP
- You MUST present dynamic routing with BGP prefix filtering as the alternative route-control option
  on a BGP-capable device, so the customer chooses route control without necessarily giving up
  dynamic failover
- You SHOULD surface the route-control benefit when the customer is connecting to a partner or third-party network

## Failover difference

BGP offers liveness detection that assists failover to the second tunnel when the first goes down.
Static routing does not get that, so a customer on static routing gives up the automatic failover
benefit without always realizing it.

**Constraints:**

- You MUST name the failover difference so the customer makes the resilience tradeoff knowingly
- You SHOULD pair this with the making-a-connection-highly-available reference when the customer depends on the connection for production

## ASN for dynamic routing

Dynamic routing requires a BGP ASN for the customer gateway. When the customer has no public ASN,
they can use a private ASN.

**Constraints:**

- You MUST supply the private ASN ranges when the customer has no public ASN, so they are not
  blocked at the customer gateway step. The 16-bit private range is 64512 to 65534 and the 32-bit
  private range is 4200000000 to 4294967294
- You SHOULD confirm the AWS-side ASN differs from the customer gateway ASN for a virtual private gateway target

## Troubleshooting

### Customer picked dynamic routing but the device has no BGP
The device cannot run BGP. Recommend static routing and enter the on-premises prefixes by hand (Decision).

### Partner routes the customer did not approve appear in the AWS route table
BGP advertised everything from the partner. On a BGP-capable device, present both route-control options: dynamic routing with BGP prefix filtering (accept only approved prefixes, keeping automatic failover) or static routing (enter approved prefixes by hand). Recommend BGP prefix filtering when the customer wants to keep dynamic failover (Static routing as deliberate route control).

### Customer is blocked creating the customer gateway because they have no ASN
Dynamic routing needs a BGP ASN. Supply a private ASN from the allowed range (ASN for dynamic routing).

## Procedure

### Overview

This procedure gathers the customer's device capability and route-control needs, matches them to a
routing type, and explains the consequences. It is a decision procedure: there is no console-write
step, because the output is a recommendation, not a deployed resource.

### Parameters

- **device_supports_bgp** (required): Whether the on-premises customer gateway device supports BGP.
- **needs_route_control** (required): Whether the customer must control which on-premises routes
  enter the AWS network (common for partner or regulated connections).
- **has_public_asn** (optional): Whether the customer has a public BGP ASN, relevant only for dynamic routing.

**Constraints for parameter acquisition:**

- You MUST establish BGP support and route-control need upfront in a single prompt
- You MUST NOT recommend a routing type before both are known

### Steps

#### 1. Establish device capability and intent

**Constraints:**

- You MUST confirm whether the on-premises device supports BGP
- You MUST establish whether the customer needs to control which routes enter their network

#### 2. Match to a routing type

**Constraints:**

- You MUST recommend static routing if the device does not support BGP
- You MUST recommend static routing or dynamic routing with BGP prefix filtering if the customer needs to control which routes enter, even on a BGP-capable device
- You SHOULD recommend dynamic routing otherwise, for automatic route exchange and BGP-assisted failover

#### 3. Explain the consequences

**Constraints:**

- You MUST state the failover difference: dynamic routing gets BGP liveness detection that assists
  tunnel failover; static routing does not
- You MUST supply a private ASN range if the customer chooses dynamic routing and has no public ASN
- You MUST NOT proceed to build; hand off to the creating-a-site-to-site-vpn-connection reference once the customer commits

### Example

#### Example input

```json
{
  "device_supports_bgp": true,
  "needs_route_control": true,
  "has_public_asn": false
}
```

#### Example output

```
The device supports BGP, so there are two ways to get the route control the customer wants:
- Dynamic routing with BGP prefix filtering: advertise and accept only the approved partner
  prefixes (filter the rest at the customer gateway). This keeps BGP liveness detection and
  automatic tunnel failover while still controlling which routes enter the AWS route table.
- Static routing: enter the approved prefixes by hand for the simplest, most explicit control.
  Tradeoff: static routing does not get BGP liveness detection, so tunnel failover is not automatic.
Recommendation: prefer dynamic routing with BGP prefix filtering here, since the device is
BGP-capable and the customer keeps automatic failover; choose static routing only if they want the
simplest explicit control and accept manual failover. Next: build it with the
creating-a-site-to-site-vpn-connection reference.
```

### Troubleshooting

#### Customer picked dynamic but the device cannot run BGP
Recommend static routing and enter prefixes by hand (Step 2).

#### Unwanted partner routes appear after choosing BGP
On a BGP-capable device, present both route-control options: dynamic routing with BGP prefix filtering (accept only approved prefixes, keeping automatic failover) or static routing (enter approved prefixes by hand). Recommend BGP prefix filtering when the customer wants to keep dynamic failover (Step 2).

#### Customer has no ASN for dynamic routing
Supply a private ASN range (Step 3).

## Security Considerations

The routing choice is also a security boundary: it decides which on-premises prefixes can enter the
AWS network and which AWS prefixes are advertised back.

**Constraints:**

- You MUST surface that static routing lets the customer admit only explicitly approved prefixes,
  while dynamic (BGP) routing accepts whatever the peer advertises; recommend static routing or BGP
  prefix filtering when connecting to a partner or untrusted network so unintended routes are not admitted
- You SHOULD remind the customer that regardless of routing type, the security group and route table
  still gate actual reachability, so they must be scoped to the intended CIDR blocks
- You SHOULD note that the routing type does not change the tunnel's encryption posture; encryption
  and authentication are set in the tunnel and device configuration

## Additional Resources

- [Static and dynamic routing in AWS Site-to-Site VPN (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/vpn-static-dynamic.html)
- [AWS Site-to-Site VPN routing options (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/VPNRoutingTypes.html)
- [Customer gateway options for your AWS Site-to-Site VPN connection (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/cgw-options.html)
