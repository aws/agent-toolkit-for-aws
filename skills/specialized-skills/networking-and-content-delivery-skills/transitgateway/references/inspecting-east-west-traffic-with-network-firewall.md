# Inspecting East-West Traffic with AWS Network Firewall

## Overview

Domain expertise for forcing traffic between VPCs (east-west) through AWS Network Firewall using a
transit gateway as the hub, instead of letting spokes talk directly across the hub. Covers the
three-hop path the routing has to construct, appliance mode for stateful cross-Availability-Zone inspection, and
the distinction between this internal east-west design and the north-south centralized egress
design.

Does not cover north-south centralized egress to the internet (a separate reference), creating the
hub, segmentation in general, hybrid connectivity, peering, or multicast. Those are separate
references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every command
in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- The three-hop path
- Appliance mode for stateful inspection
- East-west vs north-south
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To inspect east-west traffic end to end, follow the procedure exactly. See the Procedure section
below. It covers creating a dedicated inspection VPC with AWS Network Firewall endpoints, attaching
it to the transit gateway with appliance mode, building the three-hop route path so spoke-to-spoke
traffic passes through the firewall and returns, and surfacing the console link to verify.

## The three-hop path

East-west inspection is not normal hub routing. The path is: the spoke transit gateway route table
sends spoke traffic to the inspection VPC attachment, the inspection VPC subnet route tables steer it
through the AWS Network Firewall endpoint, and a return route sends inspected traffic back to the
transit gateway for delivery to the destination spoke. Miss any hop and traffic either bypasses the
firewall or is dropped with no clear signal.

The transit gateway itself needs two route tables for this, not one. The spoke route table points the
spoke CIDRs at the inspection attachment; a separate inspection route table, associated with the
inspection attachment, points the same CIDRs back at the spoke attachments. If the inspection
attachment shares the spoke route table, the transit gateway re-matches the spoke CIDRs to the
inspection attachment and loops; with no association it black-holes the returning traffic.

**Constraints:**

- You MUST build all three hops: spoke-to-inspection routing on the transit gateway, firewall
  endpoint routing inside the inspection VPC, and the return route back to the transit gateway
- You MUST associate the inspection VPC attachment with a transit gateway route table separate from
  the spoke route table, since sharing the spoke route table loops traffic back to inspection and no
  association black-holes it
- You MUST verify each hop in order, since a missing hop fails silently rather than erroring
- You MUST route through the AWS Network Firewall endpoint in the inspection VPC, not a plain subnet

## Appliance mode for stateful inspection

By default the transit gateway keeps a flow in the Availability Zone it entered, so request and
response can land on firewall endpoints in different zones and break the firewall's connection
tracking. Appliance mode on the inspection VPC attachment keeps each flow on one zone's endpoint.

**Constraints:**

- You MUST enable appliance mode on the inspection VPC attachment whenever the firewall inspects
  across Availability Zones
- You MUST tell the customer appliance mode disables cross-Availability-Zone failover for that
  attachment, so the firewall design should pair it with health-check-based failover

## East-west vs north-south

This design and the centralized egress design look similar but differ. Centralized egress sends
spoke traffic out to the internet through a central VPC (north-south). East-west inspection keeps
traffic between spokes internal and forces it through the firewall on the way. Borrowing the egress
recipe for an internal-only flow builds the wrong route tables.

**Constraints:**

- You MUST confirm the traffic direction (between spokes, not out to the internet) before building
- You MUST use the east-west route recipe here, not the centralized egress recipe, for spoke-to-spoke
  inspection

## Security considerations

East-west inspection is itself a security control: it forces spoke-to-spoke traffic through AWS
Network Firewall, so a missing hop silently bypasses the firewall rather than failing loudly. The
controls are embedded in the procedure; this section consolidates them.

**Constraints:**

- You MUST build all three hops and verify each in order, since a missing hop lets traffic bypass the
  firewall or be dropped with no clear signal
- You MUST associate the inspection VPC attachment with a transit gateway route table separate from
  the spoke route table, since sharing it loops traffic back to inspection and no association
  black-holes it
- You MUST enable AWS Network Firewall logging (alert and flow logs to Amazon S3 or CloudWatch Logs)
  with encryption at rest, since without it there is no evidence trail of what traffic was inspected,
  allowed, or dropped
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail (encrypted) to
  detect unauthorized changes to attachments, route tables, associations, and propagations
- You MUST, when a KMS key encrypts a flow log, AWS Network Firewall log, or CloudTrail destination,
  scope the KMS key policy with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`)
  so only the specific log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### Traffic between spokes never reaches the firewall
A hop is missing. Build all three: spoke-to-inspection on the transit gateway, firewall endpoint
routing in the inspection VPC, and the return route.

### Stateful firewall drops packets across zones
Appliance mode is off on the inspection VPC attachment. Enable it; pair with health-check failover.

### Inspected traffic does not reach the destination spoke
The return route to the transit gateway is missing, or the inspection attachment lacks its own
transit gateway route table. Add the return route in the inspection VPC, and associate the inspection
attachment with a separate transit gateway route table that routes the spoke CIDRs back to the spoke
attachments. If the inspection attachment shares the spoke route table, the transit gateway loops the
traffic back to inspection.

### The egress recipe was applied and east-west traffic does not flow
The direction was misread. Use the east-west recipe for spoke-to-spoke inspection.

### A route cannot be added or overwrites the firewall hop
The transit gateway attachment subnet and the firewall endpoint subnet share one subnet (and so one
route table) in an Availability Zone, so the Hop 2 route to the firewall endpoint and the Hop 3
return route to the transit gateway collide on the same destination CIDR. Place the attachment ENIs
and the firewall endpoints in separate subnets per Availability Zone so each gets its own route table.

## Procedure

### Overview

This procedure creates the inspection VPC with AWS Network Firewall endpoints, attaches it with
appliance mode, gives the inspection attachment its own transit gateway route table so the return
path does not loop, builds the three-hop route path with per-Availability-Zone routing for multi-Availability-Zone correctness, and
surfaces the console link to verify.

### Parameters

- **region** (required): The Region that holds the hub.
- **transit_gateway_id** (required): The transit gateway.
- **inspection_vpc_id** (required): The VPC holding the AWS Network Firewall endpoints.
- **inspection_subnet_ids** (required): The subnet IDs in the inspection VPC for the transit gateway attachment (one per Availability Zone).
- **spoke_vpc_ids** (required): The spoke VPCs whose mutual traffic is inspected.
- **spoke_route_table_id** (required): The transit gateway route table used by spoke attachments.
- **inspection_route_table_id** (optional): A separate transit gateway route table for the inspection
  VPC attachment. If omitted, create one. The inspection attachment MUST NOT share the spoke route
  table, or the transit gateway re-matches the spoke CIDRs to the inspection attachment and loops.
- **spoke_attachment_ids** (required): The transit gateway attachment ID of each spoke VPC, used to
  route inspected traffic from the inspection route table back to the destination spoke.
- **other_spoke_cidr** (required): The CIDR range(s) of the other spoke VPCs to route through inspection.
- **firewall_name** (required): The name of the AWS Network Firewall in the inspection VPC.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the AWS Network Firewall endpoints exist in the inspection VPC before routing

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST confirm the AWS Network Firewall firewall and its endpoints are deployed in the
  inspection VPC
- You MUST place the transit gateway attachment ENIs and the AWS Network Firewall endpoints in
  **separate** subnets within each Availability Zone, so each subnet can have its own route table
  with non-conflicting next-hops for the spoke CIDRs. Hop 2 routes the spoke CIDRs to the firewall
  endpoint in the attachment subnet route table, and Hop 3 routes the same CIDRs back to the transit
  gateway in the firewall subnet route table; if both share one subnet they share one route table,
  and a route table cannot hold two different next-hops for the same destination CIDR
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  for traffic visibility, audit, and incident response across every attached network. These logs
  carry sensitive traffic data, so you MUST enable encryption at rest on the destination (a KMS key
  on the CloudWatch log group, or SSE-KMS on the S3 bucket)
- You MUST enable AWS Network Firewall logging (alert and flow logs to Amazon S3 or CloudWatch
  Logs), since east-west inspection is a security control and without these logs there is no
  evidence trail of what traffic was inspected, allowed, or dropped for audit and incident response.
  These logs reveal traffic patterns and firewall rules, so you MUST enable encryption at rest on
  the destination (a KMS key on the CloudWatch log group, or SSE-KMS on the S3 bucket)
- You SHOULD enable AWS CloudTrail to record transit gateway attachment, route table, association,
  and propagation changes for audit and unauthorized-change detection, and you MUST enable encryption
  at rest on the CloudTrail destination (a KMS key)
- You MUST, when a KMS key encrypts a flow log destination (CloudWatch log group or S3 bucket), an
  AWS Network Firewall log destination, or the CloudTrail destination, scope the KMS key policy with
  condition keys (`aws:SourceArn`, `aws:SourceAccount`, and `kms:ViaService`) so only the specific
  log group, bucket, or trail in the expected account and service can use the key, preventing
  cross-account or cross-service misuse
- You SHOULD create CloudWatch alarms for transit gateway attachment creation and deletion, route
  table changes, and failed or blocked attachment states, so that unexpected or unauthorized changes
  and failure conditions are surfaced for investigation rather than discovered after impact

#### 2. Attach the inspection VPC with appliance mode

**Constraints:**

- You MUST create the attachment with appliance mode enabled at creation time:

  ```
  aws ec2 create-transit-gateway-vpc-attachment \
    --transit-gateway-id {transit_gateway_id} --vpc-id {inspection_vpc_id} \
    --subnet-ids {inspection_subnet_ids} \
    --options ApplianceModeSupport=enable --region {region}
  ```

- You MUST capture the `TransitGatewayAttachmentId` and poll until it reaches `available`:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --transit-gateway-attachment-ids {inspection_attachment_id} --region {region}
  ```

#### 3. Hop 1: route spoke-to-spoke traffic to the inspection VPC

**Constraints:**

- You MUST add transit gateway routes so spoke-to-spoke ranges point at the inspection VPC
  attachment:

  ```
  aws ec2 create-transit-gateway-route \
    --transit-gateway-route-table-id {spoke_route_table_id} \
    --destination-cidr-block {other_spoke_cidr} \
    --transit-gateway-attachment-id {inspection_attachment_id} --region {region}
  ```

#### 3i. Give the inspection attachment its own transit gateway route table

When the inspected traffic returns to the transit gateway (Hop 3), the transit gateway needs its own
route to deliver it to the destination spoke. The inspection VPC attachment MUST be associated with a
**separate** transit gateway route table, not the spoke route table: if it shared the spoke route
table, the transit gateway would re-match the spoke CIDRs to the inspection attachment and create a
routing loop; with no association it would black-hole the traffic.

**Constraints:**

- You MUST associate the inspection VPC attachment with a transit gateway route table separate from
  the spoke route table, since sharing the spoke route table loops traffic back to inspection and no
  association black-holes it. Create one if `inspection_route_table_id` was not supplied, and you
  MUST capture the `TransitGatewayRouteTableId` from the `create-transit-gateway-route-table`
  response as `{inspection_route_table_id}` before using it in the association and propagation
  commands below:

  ```
  aws ec2 create-transit-gateway-route-table \
    --transit-gateway-id {transit_gateway_id} --region {region}
  # Capture TransitGatewayRouteTableId from the response as {inspection_route_table_id}
  aws ec2 associate-transit-gateway-route-table \
    --transit-gateway-route-table-id {inspection_route_table_id} \
    --transit-gateway-attachment-id {inspection_attachment_id} --region {region}
  ```

- You MUST give the inspection route table routes for the spoke CIDRs that point at the respective
  spoke attachments, by enabling propagation of each spoke attachment (or adding static routes), so
  inspected traffic reaches the destination spoke:

  ```
  aws ec2 enable-transit-gateway-route-table-propagation \
    --transit-gateway-route-table-id {inspection_route_table_id} \
    --transit-gateway-attachment-id {spoke_attachment_id} --region {region}
  ```

#### 3a. Discover firewall endpoints per Availability Zone

**Constraints:**

- You MUST discover all firewall endpoints and their Availability Zone placement:

  ```
  aws network-firewall describe-firewall \
    --firewall-name {firewall_name} \
    --query 'FirewallStatus.SyncStates' \
    --output json --region {region}
  ```

- For each Availability Zone in the response, capture the `EndpointId` and `SubnetId`. Match each firewall endpoint to the transit gateway attachment subnet in the same Availability Zone.

#### 3b. Discover route tables per subnet

**Constraints:**

- You MUST discover the route table for each transit gateway attachment subnet and each firewall subnet:

  ```
  aws ec2 describe-route-tables \
    --filters "Name=association.subnet-id,Values={subnet_id}" \
    --query 'RouteTables[0].RouteTableId' --output text --region {region}
  ```

- Run for each transit gateway attachment subnet and each firewall subnet.

#### 4. Hop 2: steer traffic through the firewall endpoint (per-Availability-Zone)

**Constraints:**

- You MUST create per-Availability-Zone routes to ensure symmetric traffic flow. Each transit gateway attachment subnet route table must route destination spoke CIDRs to the firewall endpoint in the same Availability Zone.
- You MUST set each transit gateway attachment subnet route table so traffic is sent to the AWS Network Firewall
  endpoint in the same Availability Zone:

  ```
  aws ec2 create-route --route-table-id {attachment_subnet_rtb} \
    --destination-cidr-block {other_spoke_cidr} \
    --vpc-endpoint-id {firewall_endpoint_id} --region {region}
  ```

#### 5. Hop 3: return inspected traffic to the transit gateway (per-Availability-Zone)

**Constraints:**

- You MUST add a route in each firewall subnet route table that sends inspected traffic back
  to the transit gateway for delivery to the destination spoke:

  ```
  aws ec2 create-route --route-table-id {firewall_subnet_rtb} \
    --destination-cidr-block {other_spoke_cidr} \
    --transit-gateway-id {transit_gateway_id} --region {region}
  ```

- You MUST create per-Availability-Zone routes to ensure symmetric traffic flow. Each firewall subnet route table must route destination spoke CIDRs back to the transit gateway.

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST confirm the inspection attachment is `available` with appliance mode on:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --transit-gateway-attachment-ids {inspection_attachment_id} --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`
  from the API response, and tell the customer to open it and verify the route tables:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayDetails:transitGatewayId={transit_gateway_id}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-0abc",
  "inspection_vpc_id": "vpc-anfw",
  "inspection_subnet_ids": ["subnet-anfw-1a", "subnet-anfw-1b"],
  "spoke_vpc_ids": ["vpc-app", "vpc-data"],
  "spoke_route_table_id": "tgw-rtb-spoke",
  "spoke_attachment_ids": ["tgw-attach-app", "tgw-attach-data"],
  "other_spoke_cidr": "10.0.0.0/8",
  "firewall_name": "east-west-fw"
}
```

#### Example output

```
Attached vpc-anfw with appliance mode enabled at creation (stateful cross-Availability-Zone inspection).
Hop 1: routed vpc-app <-> vpc-data ranges to the inspection VPC attachment on the transit gateway.
Gave the inspection attachment its own transit gateway route table (separate from the spoke route
table) and propagated the spoke attachments into it so inspected traffic returns to the right spoke.
Discovered firewall endpoints in us-east-1a and us-east-1b; matched to transit gateway attachment subnets.
Hop 2: steered traffic from each attachment subnet through the firewall endpoint in the same Availability Zone.
Hop 3: returned inspected traffic from each firewall subnet to the transit gateway.
Per-Availability-Zone routing ensures symmetric traffic flow.
Open the transit gateway console and verify the route tables:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayDetails:transitGatewayId=tgw-0abc
```

### Troubleshooting

#### East-west traffic never reaches the firewall
A hop is missing. Build all three hops in order (Steps 3 to 5).

#### Drops across zones
Appliance mode is off. Enable it on the inspection VPC attachment (Step 2).

#### Inspected traffic does not reach the destination
The return route is missing, or the inspection attachment has no separate transit gateway route
table. Add the return route in the firewall endpoint subnet (Step 5) and give the inspection
attachment its own transit gateway route table routing the spoke CIDRs back to the spoke attachments
(Step 3i).

## Additional Resources

- [Deployment models for AWS Network Firewall with VPC routing enhancements (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/deployment-models-for-aws-network-firewall-with-vpc-routing-enhancements/)
- [AWS Network Firewall Developer Guide](https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html)
- [AWS Transit Gateway traffic flow and asymmetric routing (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/inline-traffic-inspection-third-party-appliances/transit-gateway-asymmetric-routing.html)
- [Building a scalable and secure multi-VPC AWS network infrastructure (AWS Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/building-scalable-secure-multi-vpc-network-infrastructure/welcome.html)
