# Centralizing Egress and Inspection Through a Transit Gateway

## Overview

Domain expertise for routing every spoke VPC's outbound traffic through one central VPC for egress,
inspection, or both, instead of a NAT gateway and firewall fleet in every VPC. Covers the choice
between raw appliances and a Gateway Load Balancer (GWLB) endpoint, appliance mode and its cross-Availability-Zone
failover tradeoff, the return-path routes that complete the round trip, keeping spokes isolated
while they share egress, the DNS plumbing that resolution needs across the hub, and the Regional
limit on a single inspection VPC.

Does not cover east-west inspection between VPCs (a separate reference), creating the hub,
segmentation in general, hybrid connectivity, peering, or multicast. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every
command in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Decision: appliance vs Gateway Load Balancer
- Appliance mode and the cross-Availability-Zone failover tradeoff
- The return path
- Isolation while sharing egress
- DNS plumbing across the hub
- One inspection VPC is Regional
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To centralize egress and inspection end to end, follow the procedure exactly. See the Procedure
section below. It covers working with the existing spoke and central VPC attachments, placing the
egress path (NAT and internet gateway) or the inspection path (appliances or a GWLB endpoint) in the
central VPC,
enabling appliance mode for stateful cross-Availability-Zone inspection, wiring both the forward and return
routes, keeping spokes isolated from each other, setting up DNS resolution across the hub, and
surfacing the console link to verify.

## Decision: appliance vs Gateway Load Balancer

| Path | Use when |
| --- | --- |
| Gateway Load Balancer (GWLB) endpoint | The recommended path for new designs. Inspection appliances sit behind a GWLB; spokes route to the GWLB endpoint in the central VPC |
| Raw third-party appliances | The customer runs appliances directly in the central VPC without a GWLB front end |

**Constraints:**

- You SHOULD default to the GWLB endpoint path for new inspection designs, since it scales the
  appliance fleet and is the recommended approach for new designs
- You MUST, for the GWLB path, point the central VPC route table entries at the GWLB endpoint for
  both the inbound and the return path, since missing one entry bypasses inspection or drops traffic

## Appliance mode and the cross-Availability-Zone failover tradeoff

By default a transit gateway keeps a flow in the Availability Zone it entered, so request and
response can hit different appliances and a stateful firewall drops the packets. Appliance mode on
the inspection VPC attachment keeps each flow on one appliance.

**Constraints:**

- You MUST enable appliance mode on the central VPC attachment whenever it does stateful inspection
  across Availability Zones
- You MUST tell the customer the tradeoff: appliance mode disables cross-Availability-Zone failover
  for that attachment, so a single-zone appliance failure does not automatically shift traffic
- You MUST recommend pairing appliance mode with health-check-based failover in the appliance design
  so a zone failure does not black-hole traffic

## The return path

A centralized inspection VPC needs routes in both directions. Spoke traffic reaching the appliances
or GWLB endpoint must be sent back to the transit gateway after inspection, or the round trip never
completes.

**Constraints:**

- You MUST configure the appliance (or GWLB endpoint) subnet route table and the transit gateway
  attachment subnet route table in the central VPC with entries for both directions
- You MUST verify inspected traffic returns to the transit gateway for delivery to the destination
  spoke

## Isolation while sharing egress

A single shared route table lets spokes route to each other through the hub even while they share
egress. Separate route tables send each spoke to the central VPC while blocking spoke-to-spoke
paths.

**Constraints:**

- You MUST build the route tables so spokes reach the central VPC but not each other, when the
  customer wants isolation alongside shared egress
- You SHOULD set up both goals at once rather than trade isolation for centralized egress

## DNS plumbing across the hub

When Route 53 Resolver endpoints or private hosted zones are centralized in the inspection or
egress VPC, the data path working does not mean names resolve. Resolution needs Resolver rules
forwarding queries to the central endpoints, shared to spoke accounts through AWS Resource Access
Manager (RAM), and associated with the spoke VPCs. This is the second most common support question
behind appliance mode.

**Constraints:**

- You MUST set up the Route 53 Resolver rule, the RAM share to the spoke accounts, and the VPC
  association when DNS is centralized in the hub
- You MUST treat DNS resolution as a separate concern from packet forwarding, since traffic can
  reach the right place while names fail to resolve

## One inspection VPC is Regional

A central VPC and its appliances are Regional. A multi-Region design needs an inspection VPC per
Region, tied together with inter-Region peering, not one shared inspection point.

**Constraints:**

- You MUST set this expectation before the customer commits to a single shared inspection VPC
  across Regions
- You SHOULD point a multi-Region customer at the peering reference for the inter-Region links

## Security considerations

A central egress and inspection VPC is the single chokepoint every spoke's outbound traffic crosses,
so a routing or inspection gap here exposes every attached network at once. The controls are embedded
in the procedure; this section consolidates them.

**Constraints:**

- You MUST point the central VPC route table entries at the GWLB endpoint (or the appliances) for
  both the inbound and the return path, since a missing entry bypasses inspection or drops traffic
- You MUST keep spokes on separate route tables so they reach the central VPC but not each other when
  isolation is required, since a shared route table lets spokes route to each other through the hub
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail (encrypted) to
  detect unauthorized changes to attachments, route tables, associations, and propagations
- You MUST, when a KMS key encrypts a flow log or CloudTrail destination, scope the KMS key policy
  with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`) so only the specific
  log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### Stateful firewall drops packets intermittently across zones
Appliance mode is off. Enable it on the central VPC attachment; pair with health-check failover.

### Traffic bypasses inspection or is dropped on the GWLB path
A central VPC route table entry to the GWLB endpoint is missing for one direction. Add both the
inbound and return entries.

### Inspected traffic never reaches the destination
The return path is missing. Add routes sending inspected traffic back to the transit gateway.

### Spokes can reach each other when they should be isolated
A shared route table lets them route through the hub. Use separate route tables per spoke.

### Traffic flows but names do not resolve
The DNS plumbing is missing. Set up the Resolver rule, RAM share, and VPC association.

## Procedure

### Overview

This procedure works with the existing spoke and central VPC attachments, builds the egress or
inspection path, enables appliance mode for stateful cross-Availability-Zone inspection, wires
forward and return routes, isolates spokes, sets up DNS resolution, and surfaces the console link to
verify.

**Prerequisite:** All VPC attachments this procedure uses (the central VPC attachment and every
spoke VPC attachment) MUST already exist on the transit gateway and be in the `available` state
before you run this procedure. This procedure discovers and modifies those attachments (Steps 2 and
3); it does not create them. If an attachment is missing, create it first with the creating a
transit gateway and attaching VPCs reference, since the discovery calls return nothing and the
procedure fails silently otherwise.

### Parameters

- **region** (required): The Region that holds the hub.
- **transit_gateway_id** (required): The transit gateway.
- **inspection_path** (required): `gwlb` or `appliance`.
- **central_vpc_id** (required): The egress/inspection VPC.
- **spoke_vpc_ids** (required): The spoke VPCs.
- **isolate_spokes** (required): Whether spokes must stay isolated from each other (`yes` or `no`).
- **centralized_dns** (optional): Whether Resolver endpoints or private hosted zones are
  centralized in the hub.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm whether inspection crosses Availability Zones (decides appliance mode)

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST confirm the central VPC has the egress path (NAT and internet gateway) or the inspection
  path (appliances or a GWLB endpoint) in place
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

#### 2. Attach the central VPC with appliance mode when needed

**Constraints:**

- You MUST discover the central VPC attachment ID:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --filters Name=transit-gateway-id,Values={transit_gateway_id} Name=vpc-id,Values={central_vpc_id} \
    --query 'TransitGatewayVpcAttachments[0].TransitGatewayAttachmentId' --output text --region {region}
  ```

- You MUST enable appliance mode on the central VPC attachment for stateful cross-Availability-Zone inspection:

  ```
  aws ec2 modify-transit-gateway-vpc-attachment \
    --transit-gateway-attachment-id {central_attachment_id} \
    --options ApplianceModeSupport=enable --region {region}
  ```

- You MUST poll until the modification completes and the attachment returns to `available`:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --transit-gateway-attachment-ids {central_attachment_id} --region {region}
  ```

#### 3. Route spoke traffic to the central VPC

**Constraints:**

- You MUST discover the spokes' transit gateway route table from a spoke attachment's existing
  association, which is unambiguous even in a segmented design with multiple route tables. First
  find a spoke VPC attachment:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --filters Name=transit-gateway-id,Values={transit_gateway_id} Name=vpc-id,Values={spoke_vpc_id} \
    --query 'TransitGatewayVpcAttachments[0].TransitGatewayAttachmentId' --output text --region {region}
  ```

  Then read the route table it is associated with:

  ```
  aws ec2 describe-transit-gateway-attachments \
    --transit-gateway-attachment-ids {spoke_attachment_id} \
    --query 'TransitGatewayAttachments[0].Association.TransitGatewayRouteTableId' \
    --output text --region {region}
  ```

- Capture the result as `{spoke_route_table_id}`. The spoke attachments must already be associated
  with this route table; do not assume a single non-default route table exists.
- You MUST add a default route (or the ranges to inspect) in the spokes' transit gateway route
  table pointing at the central VPC attachment:

  ```
  aws ec2 create-transit-gateway-route \
    --transit-gateway-route-table-id {spoke_route_table_id} \
    --destination-cidr-block 0.0.0.0/0 \
    --transit-gateway-attachment-id {central_attachment_id} --region {region}
  ```

#### 4. Wire the forward and return path in the central VPC

**Constraints:**

- You MUST point the central VPC subnet route tables at the GWLB endpoint (GWLB path) or the
  appliances (appliance path) for the inbound direction
- You MUST add the return route that sends inspected traffic back to the transit gateway
- You MUST verify both directions before moving on

#### 5. Isolate spokes when required

**Constraints:**

- You MUST keep spokes on separate route tables so they reach the central VPC but not each other,
  when `isolate_spokes` is yes (see the segmenting reference)

#### 6. Set up DNS resolution across the hub

**Constraints:**

- You MUST, when DNS is centralized, create the Resolver rule, share it with the spoke accounts via
  RAM, and associate it with the spoke VPCs

#### 7. Confirm and surface the console link

**Constraints:**

- You MUST confirm the central attachment and routes are in place:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --transit-gateway-attachment-ids {central_attachment_id} --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`
  from the API response, and tell the customer to open it and verify the egress/inspection wiring:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayDetails:transitGatewayId={transit_gateway_id}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-0abc",
  "inspection_path": "gwlb",
  "central_vpc_id": "vpc-inspection",
  "spoke_vpc_ids": ["vpc-app", "vpc-data"],
  "isolate_spokes": "yes",
  "centralized_dns": true
}
```

#### Example output

```
Attached the inspection VPC with appliance mode enabled (cross-Availability-Zone stateful inspection).
Flagged the tradeoff: appliance mode disables cross-Availability-Zone failover; paired with health-check failover.
Routed spoke default traffic to the inspection VPC; pointed the central VPC route tables at the GWLB
endpoint for both inbound and return.
Kept vpc-app and vpc-data on separate route tables (isolated from each other).
Set up the Resolver rule, RAM share, and VPC associations so names resolve across the hub.
Open the transit gateway console and verify the wiring:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayDetails:transitGatewayId=tgw-0abc
```

### Troubleshooting

#### Intermittent drops across zones
Appliance mode is off. Enable it (Step 2) and pair with health-check failover.

#### Traffic bypasses the firewall or is dropped (GWLB)
A central VPC route entry to the GWLB endpoint is missing. Add both directions (Step 4).

#### Names do not resolve from spokes
DNS plumbing is missing. Create the Resolver rule, RAM share, and VPC association (Step 6).

## Additional Resources

- [How AWS Transit Gateway works: Example: Centralized outbound routing to the internet (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/how-transit-gateways-work.html)
- [AWS Transit Gateway traffic flow and asymmetric routing (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/inline-traffic-inspection-third-party-appliances/transit-gateway-asymmetric-routing.html)
- [Creating a single internet exit point from multiple VPCs Using AWS Transit Gateway (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/creating-a-single-internet-exit-point-from-multiple-vpcs-using-aws-transit-gateway/)
- [Using Gateway Load Balancer with Transit Gateway for centralized network security (AWS Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/building-scalable-secure-multi-vpc-network-infrastructure/using-gwlb-with-tg-for-cns.html)
- [Centralized inspection architecture with AWS Gateway Load Balancer and AWS Transit Gateway (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/centralized-inspection-architecture-with-aws-gateway-load-balancer-and-aws-transit-gateway/)
- [Centralized DNS management of hybrid cloud with Amazon Route 53 and AWS Transit Gateway (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/centralized-dns-management-of-hybrid-cloud-with-amazon-route-53-and-aws-transit-gateway/)
