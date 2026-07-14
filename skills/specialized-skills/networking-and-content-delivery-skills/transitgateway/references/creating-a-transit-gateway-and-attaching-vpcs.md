# Creating a Transit Gateway and Attaching VPCs

## Overview

Domain expertise for building a Regional transit gateway hub and connecting VPCs to it, so many
VPCs reach each other through one router instead of a peering mesh. Covers the default route table
behavior that decides whether the hub starts open or segmented, the one-subnet-per-Availability-Zone
rule, the dedicated attachment subnet best practice, the overlapping-CIDR check, and the VPC-side
routes that attaching alone does not create.

Does not cover route table segmentation in depth (a separate reference), centralized egress or
inspection, hybrid connectivity, peering, or multicast. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every
command in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Decision: segmentation intent and default route tables
- Attachment subnets, one per Availability Zone
- Dedicated attachment subnet
- Overlapping CIDR check
- VPC-side routes
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To build the hub and attach VPCs end to end, follow the procedure exactly. See the Procedure
section below. It covers deciding segmentation intent before creation, creating the transit gateway
with the right default-route-table settings, creating one VPC attachment per VPC with a dedicated
subnet in every Availability Zone that holds workloads, checking for overlapping CIDRs, adding the
VPC-side routes, and surfacing the console link to verify.

## Decision: segmentation intent and default route tables

When a transit gateway is created, "Default route table association" and "Default route table
propagation" are both on by default. Every new attachment then associates with and propagates into
the one default route table, so all VPCs can reach all VPCs: an open mesh.

| Customer intent | Default settings |
| --- | --- |
| All VPCs should reach each other (flat network) | Leave both defaults on |
| Some VPCs must stay isolated (segmentation now or later) | Disable both defaults at creation, then build route tables per the segmenting reference |

**Constraints:**

- You MUST ask whether the customer plans to isolate any environments before creating the transit
  gateway
- You MUST disable default route table association and default route table propagation at creation
  when the customer plans segmentation, so isolation is designed in rather than retrofitted
- You SHOULD warn that turning an open hub into a segmented one later means re-associating every
  attachment and reworking routes

## Attachment subnets, one per Availability Zone

A transit gateway routes traffic in an Availability Zone only where its VPC attachment has a subnet
in that zone. An attachment that lists subnets in only some zones leaves instances in the other
zones unable to reach anything across the hub.

**Constraints:**

- You MUST specify an attachment subnet in every Availability Zone that holds workloads, not just
  one
- You MUST confirm which zones hold workloads before creating the attachment

## Dedicated attachment subnet

Putting the transit gateway network interfaces in the same subnet as EC2 instances makes one subnet
route table serve both the attachment and the workloads, where entries can conflict. A dedicated
small subnet avoids it.

**Constraints:**

- You SHOULD use a dedicated subnet for each transit gateway attachment, not a subnet shared with
  workloads
- You SHOULD size the attachment subnet small; a /28 holds the transit gateway network interface
  with room to spare
- You SHOULD treat this as a Day 1 choice, since moving an attachment off a shared subnet after
  instances are running is disruptive

## Overlapping CIDR check

A transit gateway does not route between overlapping CIDRs and will not propagate a new CIDR when an
identical route already exists. Attaching a VPC that overlaps an attached one fails silently: no
error, just missing routes.

**Constraints:**

- You MUST check the new VPC's CIDR against every already-attached VPC before creating the
  attachment
- You MUST stop and tell the customer when an overlap exists, since the fix is re-addressing a VPC,
  not a routing change

## VPC-side routes

Creating the attachment connects the VPC to the transit gateway but does not add the routes that
send traffic to it. Each VPC subnet route table still needs an entry pointing the other VPCs' ranges
at the transit gateway.

**Constraints:**

- You MUST add a route in each participating VPC subnet route table that targets the transit gateway
  for the ranges of the other VPCs
- You MUST treat the VPC-side routes as a required step, not an optional follow-up

## Security considerations

A transit gateway becomes the central routing point for every VPC attached to it, so a
misconfiguration here has blast radius across every attached network, and an overlapping-CIDR
attachment fails silently rather than loudly. The controls are embedded in the procedure; this
section consolidates them.

**Constraints:**

- You MUST check for overlapping CIDRs across all VPCs before attaching, since a transit gateway does
  not route between overlapping ranges and the attachment fails silently with missing routes rather
  than an error, leaving a connectivity and visibility gap
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  (once it exists) with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail
  (encrypted) to detect unauthorized changes to attachments, route tables, associations, and
  propagations
- You MUST, when a KMS key encrypts a flow log or CloudTrail destination, scope the KMS key policy
  with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`) so only the specific
  log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### Instances in one Availability Zone cannot reach the hub
The attachment has no subnet in that zone. Add an attachment subnet for every zone with workloads.

### Connectivity silently fails after attaching a VPC
The VPC's CIDR overlaps an already-attached VPC. Check all attachments for overlap; re-address one.

### Attachment created but no traffic flows
The VPC subnet route tables have no route to the transit gateway. Add the VPC-side routes.

### Everything can reach everything when isolation was wanted
Default route table association and propagation were left on. Disable them and segment per the
segmenting reference.

## Procedure

### Overview

This procedure decides segmentation intent, creates the transit gateway with the matching default
settings, attaches each VPC with a dedicated subnet per Availability Zone after checking for CIDR
overlap, adds the VPC-side routes, and surfaces the console link to verify.

### Parameters

- **region** (required): The Region for the hub and attachments.
- **segmentation_intent** (required): Whether any VPCs must stay isolated (`yes` or `no`).
- **vpc_ids** (required): The VPCs to attach.
- **attachment_subnets** (required): Per VPC, one dedicated subnet ID per Availability Zone that
  holds workloads.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm which Availability Zones hold workloads for each VPC

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST list the CIDR of every VPC to attach and check for overlap before creating anything:

  ```
  aws ec2 describe-vpcs --vpc-ids {vpc_ids} --region {region}
  ```

- You MUST enable VPC Flow Logs on the attached VPC subnets (the VPCs already exist) for traffic
  visibility, audit, and incident response. These logs carry sensitive traffic data, so you MUST
  enable encryption at rest on the destination (a KMS key on the CloudWatch log group, or SSE-KMS on
  the S3 bucket). Transit Gateway Flow Logs are enabled in Step 2, once the hub exists
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

#### 2. Create the transit gateway with the right defaults

**Constraints:**

- You MUST disable the defaults when segmentation is intended:

  ```
  aws ec2 create-transit-gateway --description "{description}" \
    --options DefaultRouteTableAssociation=disable,DefaultRouteTablePropagation=disable \
    --region {region}
  ```

- You MUST leave the defaults enabled only when the customer wants a flat network
- You MUST capture the `TransitGatewayId` and poll until it reports `available`:

  ```
  aws ec2 describe-transit-gateways \
    --transit-gateway-ids {transit_gateway_id} --region {region}
  ```

- You MUST enable Transit Gateway Flow Logs on the hub once it exists, for traffic visibility and
  audit across every attached network. These logs carry sensitive traffic data, so you MUST enable
  encryption at rest on the destination (a KMS key on the CloudWatch log group, or SSE-KMS on the S3
  bucket)

#### 3. Create one VPC attachment per VPC

**Constraints:**

- You MUST create the attachment with a subnet in every Availability Zone that holds workloads,
  using dedicated subnets:

  ```
  aws ec2 create-transit-gateway-vpc-attachment \
    --transit-gateway-id {transit_gateway_id} --vpc-id {vpc_id} \
    --subnet-ids {attachment_subnets} --region {region}
  ```

- You MUST capture each `TransitGatewayAttachmentId` and poll until it reaches `available`:

  ```
  aws ec2 describe-transit-gateway-vpc-attachments \
    --transit-gateway-attachment-ids {attachment_id} --region {region}
  ```

#### 4. Add the VPC-side routes

**Constraints:**

- You MUST discover all route tables for each VPC:

  ```
  aws ec2 describe-route-tables \
    --filters Name=vpc-id,Values={vpc_id} \
    --query 'RouteTables[*].RouteTableId' --output json --region {region}
  ```

- Capture all route table IDs. You MUST add a route to the transit gateway in each returned route table.
- You MUST add a route to the transit gateway in each VPC route table for the other VPCs'
  ranges:

  ```
  aws ec2 create-route --route-table-id {vpc_route_table_id} \
    --destination-cidr-block {other_vpc_cidr} \
    --transit-gateway-id {transit_gateway_id} --region {region}
  ```

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm the attachments are `available`:

  ```
  aws ec2 describe-transit-gateway-attachments \
    --filters Name=transit-gateway-id,Values={transit_gateway_id} --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`
  from the API response, and tell the customer to open it and confirm the attachments:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayDetails:transitGatewayId={transit_gateway_id}
  ```

- **Note:** If defaults were disabled at creation (segmentation intended), you MUST refer the customer to the segmenting-traffic-with-route-tables reference to complete their route table design.

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "segmentation_intent": "yes",
  "vpc_ids": ["vpc-team1", "vpc-team2", "vpc-shared"],
  "attachment_subnets": {
    "vpc-team1": ["subnet-team1-1a", "subnet-team1-1b"],
    "vpc-team2": ["subnet-team2-1a", "subnet-team2-1b"],
    "vpc-shared": ["subnet-shared-1a", "subnet-shared-1b"]
  }
}
```

#### Example output

```
Checked CIDRs: no overlap.
Created transit gateway tgw-0abc with default association and propagation disabled (segmentation planned).
Attached vpc-team1, vpc-team2, vpc-shared, each with a dedicated /28 subnet in us-east-1a and us-east-1b.
Added VPC-side routes to the transit gateway in each VPC's subnet route tables.
Open the transit gateway console and confirm the attachments:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayDetails:transitGatewayId=tgw-0abc
Next, build route tables per the segmenting reference to enforce isolation.
```

### Troubleshooting

#### Instances in one Availability Zone cannot reach the hub
The attachment lacks a subnet in that zone. Recreate or modify the attachment to include it
(Step 3).

#### Connectivity silently fails after attaching
A CIDR overlaps an attached VPC. Re-check overlap and re-address before retrying (Step 1).

#### Traffic does not flow after attaching
VPC-side routes are missing. Add the routes to the transit gateway (Step 4).

## Additional Resources

- [Tutorial: Create an AWS Transit Gateway using the Amazon VPC Console (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-getting-started-console.html)
- [Amazon VPC attachments in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-vpc-attachments.html)
- [Transit gateway route tables in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-route-tables.html)
- [How AWS Transit Gateway works (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/how-transit-gateways-work.html)
