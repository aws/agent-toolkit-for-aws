# Connecting Many Sites Through a Site-to-Site VPN Concentrator

## Overview

Domain expertise for consolidating multi-site connectivity with an AWS Site-to-Site VPN
Concentrator: a transit gateway attachment that gives 5 Gbps of aggregate bandwidth shared across
many remote sites, with endpoints in two Availability Zones. Covers the deployment profile the
Concentrator fits, the transit-gateway-only and BGP-only constraints, the per-site work that remains,
and the cost comparison against per-site connections.

Does not cover sizing one connection's throughput (the choosing-tunnel-bandwidth reference) or the
general connection build (the creating-a-site-to-site-vpn-connection reference), though each site's
connection follows that build. Use this reference when the customer has many low-bandwidth sites,
not one high-throughput site.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region {region}` matching the transit gateway.

## Table of Contents

- Overview
- Workflow
- Decision: is a Concentrator the right fit
- Transit-gateway-only and BGP-only constraints
- Per-site work remains
- Cost comparison
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To consolidate many sites, confirm the deployment fits the Concentrator profile, create the
Concentrator on a transit gateway, then create one VPN connection per site against it. See the
Procedure section below.

The procedure covers:

- Checking the site count and per-site bandwidth against the Concentrator profile
- Creating the Concentrator on an existing transit gateway
- Creating one BGP VPN connection per site, each with a unique CIDR block
- Surfacing the console link to verify

## Decision: is a Concentrator the right fit

| Choice | Use when |
| --- | --- |
| VPN Concentrator | 25 or more remote sites, each needing roughly 50 to 100 Mbps, sharing 5 Gbps aggregate bandwidth (retail chains, restaurant franchises, hotels, multi-site healthcare) |
| Individual VPN connections | A handful of sites, or a single site that needs high throughput on its own |
| Large (5 Gbps) tunnels | One site that needs high per-tunnel throughput (the choosing-tunnel-bandwidth reference) |

**Constraints:**

- You MUST check the site count and per-site bandwidth against the profile (25+ sites, 50 to 100 Mbps each) before recommending a Concentrator
- You SHOULD recommend individual connections or Large tunnels when the customer has few sites or a single high-throughput site

## Transit-gateway-only and BGP-only constraints

The Concentrator is a transit gateway attachment only, so it does not work with a virtual private
gateway, and connections on it must use BGP routing; static routing is not an option.

**Constraints:**

- You MUST confirm the customer has (or will create) a transit gateway; the Concentrator cannot attach to a virtual private gateway
- You MUST state that connections on the Concentrator require BGP routing, so the customer's devices must support BGP
- You SHOULD surface both constraints before the customer starts, so the gateway and routing decisions are made correctly the first time

## Per-site work remains

The Concentrator shares one attachment, but each remote site still needs its own VPN connection and
its own customer gateway, and every site must use a unique CIDR block to avoid routing conflicts
across the shared attachment.

**Constraints:**

- You MUST make clear the consolidation is at the attachment and bandwidth level, not "one connection to configure"
- You MUST enforce a unique CIDR block per site to avoid routing conflicts
- You SHOULD track which sites have been provisioned and confirm each site's connection is created, so no site is accidentally omitted from the rollout

## Cost comparison

A Concentrator bills per hour for the attachment plus a smaller per-connection charge. It is cheaper
than a full 1.25 Gbps connection per site only when there are enough low-bandwidth sites to amortize
the attachment cost.

**Constraints:**

- You MUST walk the customer through the comparison against per-site connections, based on their actual site count
- You SHOULD NOT assume consolidation is always cheaper; below the break-even site count, per-site connections cost less

## Troubleshooting

### Customer asks to use a Concentrator without a transit gateway
The Concentrator requires a transit gateway. If the customer only has a virtual private gateway, they must create a transit gateway first (Transit-gateway-only constraints).

### A site's connection rejects static routing
Concentrator connections require BGP. The device must support BGP (Transit-gateway-only and BGP-only constraints).

### Routing breaks across sites
Two sites use overlapping CIDR blocks. Give each site a unique CIDR block (Per-site work remains).

### Concentrator costs more than expected for few sites
Below the break-even site count, per-site connections are cheaper. Reconsider the fit (Cost comparison).

### Monitoring the Concentrator and its connections
Use the monitoring-and-troubleshooting-tunnels reference for setting up CloudWatch alarms and VPN logs on the Concentrator's connections.

## Procedure

### Overview

This procedure confirms the deployment fits the Concentrator profile, creates the Concentrator on a
transit gateway, creates one BGP VPN connection per site with a unique CIDR block, then surfaces the
console link to verify.

### Parameters

- **region** (required): The AWS Region of the transit gateway.
- **transit_gateway_id** (required): The existing transit gateway to attach the Concentrator to.
- **site_count** (required): The number of remote sites.
- **per_site_bandwidth** (required): The bandwidth each site needs.
- **sites** (required): Per site, the customer gateway IP, the customer gateway BGP ASN, and the unique CIDR block.

**Constraints for parameter acquisition:**

- You MUST ask for the site count and per-site bandwidth upfront to confirm the fit
- You MUST confirm a transit gateway exists or will be created

### Steps

#### 1. Confirm the fit

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST check site count and per-site bandwidth against the profile (25+ sites, 50 to 100 Mbps each)
- You SHOULD recommend individual connections or Large tunnels instead if the deployment does not fit

#### 2. Create the Concentrator

**Constraints:**

- You MUST create the Concentrator on the existing transit gateway. It provisions two endpoints, one per Availability Zone:

  ```
  aws ec2 create-vpn-concentrator --transit-gateway-id {transit_gateway_id} --region {region}
  ```

- You MUST capture the concentrator ID from the response

#### 3. Create one VPN connection per site

**Constraints:**

- You MUST create each site's customer gateway and a BGP VPN connection against the Concentrator, with a unique CIDR block per site. Per site, create the customer gateway, then the connection against the transit gateway the Concentrator is on, supplying two `TunnelOptions` objects so both tunnels use strong options:

  ```
  aws ec2 create-customer-gateway --type ipsec.1 --public-ip {site_customer_gateway_ip} \
    --bgp-asn {site_customer_gateway_asn} --region {region}
  aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id {site_customer_gateway_id} \
    --transit-gateway-id {transit_gateway_id} \
    --pre-shared-key-storage SecretsManager \
    --options "StaticRoutesOnly=false,TunnelOptions=[{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]},{Phase1EncryptionAlgorithms=[{Value=AES256}],Phase2EncryptionAlgorithms=[{Value=AES256}],Phase1IntegrityAlgorithms=[{Value=SHA2-256}],Phase2IntegrityAlgorithms=[{Value=SHA2-256}],Phase1DHGroupNumbers=[{Value=14}],Phase2DHGroupNumbers=[{Value=14}]}]" \
    --region {region}
  ```

- You MUST use `--pre-shared-key-storage SecretsManager` on all `create-vpn-connection` calls to store PSKs in AWS Secrets Manager so they are not returned as plain text in APIs like `describe-vpn-connections`; this incurs a small additional Secrets Manager cost per secret
- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You MUST supply two `TunnelOptions` objects, one per tunnel, since every connection has two tunnels; a single-element array leaves Tunnel 2 on the weak AES-128 / SHA-1 / DH group 2 defaults
- You MUST NOT use static routing; Concentrator connections require BGP
- You MUST confirm no two sites share a CIDR block

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST confirm the Concentrator and each site's connection report the expected state
- You MUST present the VPN Concentrators console link, filling `{region}` from the request, and tell the customer to open it and confirm the Concentrator and attached connections:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#SiteToSiteVpnConcentrators:
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-0abc1234",
  "site_count": 40,
  "per_site_bandwidth": "75 Mbps",
  "sites": [
    {"customer_gateway_ip": "203.0.113.10", "customer_gateway_asn": 65010, "ip_range": "10.20.1.0/24"},
    {"customer_gateway_ip": "203.0.113.11", "customer_gateway_asn": 65011, "ip_range": "10.20.2.0/24"}
  ]
}
```

#### Example output

```
Fit confirmed: 40 sites at ~75 Mbps each share 5 Gbps aggregate, within the Concentrator profile.
Created the Concentrator on tgw-0abc1234 (endpoints in two AZs) and one BGP VPN connection per site,
each with a unique CIDR block. Open the Concentrators view to confirm:
https://console.aws.amazon.com/vpc/home?region=us-east-1#SiteToSiteVpnConcentrators:
```

### Troubleshooting

See the Troubleshooting section above for common issues (attachment failures, static routing rejection, overlapping CIDRs, cost).

## Security Considerations

A Concentrator multiplies the number of tunnels and secrets the customer manages on one shared
attachment, so per-site authentication and isolation matter more than for a single connection.

**Constraints:**

- You MUST treat tunnel pre-shared keys (PSKs) as secrets: never pass them on the command line or store them in plaintext, store them in AWS Secrets Manager, and rotate them periodically; where the device supports it, recommend certificate-based authentication with AWS Private Certificate Authority instead of a static PSK. Use a distinct key per site rather than reusing one key across sites
- You MUST enforce a unique, non-overlapping CIDR block per site, since overlapping CIDR blocks across the
  shared attachment both break routing and let one site reach another's prefixes
- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You SHOULD set up monitoring by following the monitoring-and-troubleshooting-tunnels reference, which covers CloudWatch tunnel-state alarms, VPN logs, and CloudTrail audit logging
- You MUST enable encryption at rest on all log destinations (KMS on the CloudWatch Logs log groups holding the VPN/tunnel logs, and SSE-S3 or SSE-KMS on the S3 bucket holding the CloudTrail logs) since these logs can carry sensitive tunnel and connection details

## Additional Resources

- [Introducing AWS Site-to-Site VPN Concentrator for multi-site connectivity (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-aws-site-to-site-vpn-concentrator-for-multi-site-connectivity/)
- [AWS Site-to-Site VPN quotas (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/vpn-limits.html)
- [AWS VPN Pricing](https://aws.amazon.com/vpn/pricing/)
