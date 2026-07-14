# Migrating From a VPC Peering Mesh to a Transit Gateway

## Overview

Domain expertise for moving off a full mesh of VPC peering connections onto a single transit gateway
hub, one VPC at a time, without interrupting live traffic. Covers the cutover order that keeps both
directions of every active pair reachable, the rollback that the old peering connections provide at
each step, and the overlapping-CIDR check that peering tolerates but a transit gateway does not.

Does not cover creating the hub from scratch in detail (see the creating reference for attachment
mechanics), segmentation, egress, hybrid connectivity, peering between transit gateways, or
multicast. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every command
in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Cutover order
- Keep peering as the rollback
- Overlapping CIDR check before migrating
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To migrate from a peering mesh end to end, follow the procedure exactly. See the Procedure section
below. It covers checking for CIDR overlap across the whole mesh, creating the transit gateway and
attaching every VPC, cutting each VPC over by replacing its subnet route tables in an order that
never strands a pair, verifying the transit gateway path before removing peering, and surfacing the
console link to verify.

## Cutover order

Cutting over VPC route tables in the wrong order breaks live traffic. While one VPC points a range
at the transit gateway and its peer still points the return range at the old peering connection, the
path is asymmetric and sessions drop. There is no error, only dropped traffic.

**Constraints:**

- You MUST sequence the route table edits so both directions of every active pair always have a
  working path
- You MUST make each step reversible before moving to the next
- You MUST cut over a pair's forward and return routes together, not one side at a time across a
  long gap

## Keep peering as the rollback

Removing the old peering connections before the transit gateway path is confirmed loses connectivity
with no quick way back. Peering is the fallback until the hub path is verified end to end for that
VPC.

**Constraints:**

- You MUST keep the peering connections in place until the transit gateway path is verified for that
  VPC
- You MUST remove peering only as the final step for a VPC, after verification
- You MUST treat each VPC's peering connections as its rollback at every stage of its cutover

## Overlapping CIDR check before migrating

VPC peering tolerates some CIDR overlap with specific routes, but a transit gateway does not route
between overlapping CIDRs. A pair that worked over peering can fail once moved to the hub. Overlap
discovered mid-cutover forces a re-address that is far more disruptive than catching it up front.

**Constraints:**

- You MUST check for overlapping CIDRs across all VPCs in the mesh before starting the migration
- You MUST resolve overlap (re-address) before migrating an affected VPC, not during cutover

## Security considerations

Migrating a live mesh reroutes production traffic one VPC at a time, so the risk here is dropped
connectivity from an asymmetric cutover and lost reachability from removing the rollback too early,
alongside the standard hub-wide logging controls. The controls are embedded in the procedure; this
section consolidates them.

**Constraints:**

- You MUST sequence the route table edits so both directions of every active pair always have a
  working path, and MUST cut over a pair's forward and return routes together
- You MUST keep the peering connections in place as the rollback until the transit gateway path is
  verified for that VPC, and remove peering only as the final step
- You MUST check for overlapping CIDRs across all VPCs before migrating, since a transit gateway does
  not route between overlapping ranges that peering tolerated
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

### Sessions drop during cutover
The forward and return routes were sequenced apart and the path went asymmetric. Cut over both
directions of a pair together; roll back to peering if needed.

### A pair that worked on peering fails on the hub
The CIDRs overlap. A transit gateway will not route between them. Re-address before migrating.

### Connectivity lost after removing peering
Peering was removed before the transit gateway path was verified. Recreate the peering connection
and verify the hub path before removing again.

## Procedure

### Overview

This procedure checks for overlap across the mesh, builds the transit gateway and attaches every
VPC, cuts each VPC over with both directions together while keeping peering as the rollback, verifies
the hub path, then removes peering, and surfaces the console link to verify.

### Parameters

- **region** (required): The Region of the mesh and the new hub.
- **vpc_ids** (required): Every VPC in the peering mesh.
- **peering_connection_ids** (required): The existing peering connections, for rollback and final
  removal.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST enumerate every VPC and peering connection in the mesh before starting

### Steps

#### 1. Check for overlap across the mesh

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST list the CIDRs of all VPCs and confirm no overlap before migrating:

  ```
  aws ec2 describe-vpcs --vpc-ids {vpc_ids} --region {region}
  ```

- You MUST resolve any overlap before migrating the affected VPC
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

#### 2. Create the hub and attach every VPC

**Constraints:**

- You MUST create the transit gateway and a VPC attachment for each VPC (see the creating reference
  for the one-subnet-per-Availability-Zone and dedicated-subnet rules):

  ```
  aws ec2 create-transit-gateway --region {region}
  aws ec2 create-transit-gateway-vpc-attachment \
    --transit-gateway-id {transit_gateway_id} --vpc-id {vpc_id} \
    --subnet-ids {attachment_subnets} --region {region}
  ```

- You MUST enable Transit Gateway Flow Logs on the hub once it exists, for traffic visibility and
  audit across every attached network. These logs carry sensitive traffic data, so you MUST enable
  encryption at rest on the destination (a KMS key on the CloudWatch log group, or SSE-KMS on the S3
  bucket)
- You MUST confirm every attachment reaches `available` before any cutover

#### 3. Cut each VPC over, both directions together

**Constraints:**

- You MUST, for each pair, replace the peering route with a transit gateway route in both VPCs'
  subnet route tables in immediate succession, so the path is asymmetric for the shortest possible
  window:

  ```
  aws ec2 replace-route --route-table-id {vpc_route_table_id} \
    --destination-cidr-block {peer_vpc_cidr} \
    --transit-gateway-id {transit_gateway_id} --region {region}
  ```

- You MUST verify connectivity for the pair over the hub after replacing the route, and roll back
  by replacing it back to the peering connection if verification fails.

#### 4. Verify the hub path, then remove peering

**Constraints:**

- You MUST confirm every range a VPC needs is reachable over the transit gateway before deleting any
  peering connection
- You MUST delete the peering connections only as the final step:

  ```
  aws ec2 delete-vpc-peering-connection \
    --vpc-peering-connection-id {peering_connection_id} --region {region}
  ```

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`,
  and tell the customer to open it and confirm all attachments and routes:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayDetails:transitGatewayId={transit_gateway_id}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "vpc_ids": ["vpc-a", "vpc-b", "vpc-c", "vpc-d", "vpc-e", "vpc-f"],
  "peering_connection_ids": ["pcx-ab", "pcx-ac", "pcx-bc", "pcx-..."]
}
```

#### Example output

```
Checked CIDRs across 6 VPCs: no overlap.
Created the transit gateway and attached all 6 VPCs (all available).
Cut each pair over by replacing the peering route with a transit gateway route in both directions
together; verified hub connectivity per pair after each replacement. Rolled back where needed by
replacing back to the peering connection.
Removed the peering connections only after the hub path was verified end to end.
Open the transit gateway console and confirm:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayDetails:transitGatewayId=tgw-0abc
```

### Troubleshooting

#### Sessions drop mid-migration
The route edits went asymmetric. Cut both directions of a pair together; roll back to peering
(Step 3).

#### A pair fails on the hub but worked on peering
CIDRs overlap. Re-address before migrating (Step 1).

#### Lost connectivity after deleting peering
Peering was removed too early. Recreate it and verify the hub path first (Step 4).

## Additional Resources

- [Migrate from VPC peering to AWS Transit Gateway (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/migration-vpc-peering-transit-gateway/welcome.html)
- [Amazon VPC attachments in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-vpc-attachments.html)
- [How AWS Transit Gateway works (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/how-transit-gateways-work.html)
