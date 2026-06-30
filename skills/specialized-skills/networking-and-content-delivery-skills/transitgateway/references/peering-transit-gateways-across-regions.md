# Peering Transit Gateways Across Regions

## Overview

Domain expertise for connecting two transit gateways, one per Region, so VPCs in different Regions
communicate over the AWS network instead of the public internet. Covers the accept step that
creation alone does not complete, the static-routes-only nature of peering, the overlapping-CIDR
check, the region-pair-dependent bandwidth, and the routing asymmetry that appears when peering and
a Site-to-Site VPN reach the same Regions.

Does not cover creating the hub, attaching VPCs, segmentation, egress, hybrid connectivity, or
multicast. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Peering spans two Regions; run requester-side
commands in the requester Region and accepter-side commands in the accepter Region.

## Table of Contents

- Overview
- Workflow
- The accept step
- Peering uses static routes only
- Encryption in transit
- Overlapping CIDR check
- Region-pair-dependent bandwidth
- Routing asymmetry with VPN
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To peer transit gateways across Regions end to end, follow the procedure exactly. See the Procedure
section below. It covers creating the peering attachment from the requester transit gateway,
accepting it on the accepter side, adding static routes in each transit gateway route table, and
surfacing the console link to verify.

## The accept step

A peering attachment stays pending until the owner of the accepter transit gateway accepts it.
Creating the attachment does not establish the peer; it is not usable until it reaches the available
state.

**Constraints:**

- You MUST treat the accept step as part of the workflow, not an external follow-up
- You MUST tell the customer the attachment is not usable until it reaches `available`

## Peering uses static routes only

Peering does not support dynamic routing, so routes do not propagate across the peer the way they do
for VPC attachments. Each transit gateway route table needs a static route pointing at the peering
attachment.

**Constraints:**

- You MUST add a static route in each transit gateway route table pointing at the peering attachment
  for the remote Region's ranges
- You MUST NOT wait for propagation across a peering attachment, since it never happens

## Encryption in transit

Inter-Region transit gateway peering traffic travels over the AWS backbone and is automatically
encrypted by AWS; the customer does not configure or manage this encryption.

**Constraints:**

- You SHOULD confirm to the customer that inter-Region peering traffic is automatically encrypted by
  AWS on the backbone, so they can weigh peering against a Site-to-Site VPN for inter-Region
  connectivity

## Overlapping CIDR check

A transit gateway cannot route between overlapping ranges, so peering Regions whose VPC CIDR blocks
overlap does not work. Overlap is harder to fix after workloads are deployed.

**Constraints:**

- You MUST check for CIDR overlap across both Regions before creating the peering attachment
- You MUST stop and tell the customer when an overlap exists, since the fix is re-addressing, not a
  routing change

## Region-pair-dependent bandwidth

Peering bandwidth depends on the Region pair and is not guaranteed to match VPC attachment
bandwidth. Customers who design for sustained inter-Region throughput assuming symmetric,
VPC-equivalent bandwidth hit throttling.

**Constraints:**

- You SHOULD set this expectation when the customer designs for sustained inter-Region throughput
- You SHOULD have capacity planning account for the per-Region-pair limit, not assume
  VPC-attachment-equivalent bandwidth

## Routing asymmetry with VPN

A customer who runs both inter-Region peering and a Site-to-Site VPN into the same Regions can get
an asymmetric path, where traffic leaves over peering and returns over the VPN (or the reverse),
unless route preferences are explicit. Because peering uses static routes, the customer also has to
keep those static routes in sync by hand with the remote Region's CIDRs as VPCs are added there.

**Constraints:**

- You MUST make the path preference explicit when both peering and VPN reach the same Regions, so
  traffic does not split paths
- You MUST flag the manual static-route maintenance as the remote side grows, since static peering
  routes do not track new CIDRs

## Security considerations

Inter-Region peering joins two Regional hubs into one routing fabric, so a static route into the
wrong table or an asymmetric path with a parallel VPN exposes or splits traffic across Regions. The
controls are embedded in the procedure; this section consolidates them.

**Constraints:**

- You MUST add static routes only into the route tables that should reach the remote Region, since
  peering does not propagate and a route in the wrong table opens an unintended cross-Region path
- You MUST make the path preference explicit when both peering and a Site-to-Site VPN reach the same
  Regions, so traffic does not split paths, and MUST keep the static peering routes in sync as the
  remote side grows
- Inter-Region peering traffic is automatically encrypted by AWS on the backbone; the customer does
  not configure or manage this encryption
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail (encrypted) to
  detect unauthorized changes to attachments, route tables, associations, and propagations
- You MUST, when a KMS key encrypts a flow log or CloudTrail destination, scope the KMS key policy
  with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`) so only the specific
  log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### The peering attachment stays pending
The accepter has not accepted it. Accept it on the accepter side; wait for `available`.

### No traffic flows after peering
Static routes pointing at the peering attachment are missing. Add them in each route table.

### Connectivity does not work between peered Regions
The VPC CIDRs overlap. Check both Regions; re-address.

### Throughput is throttled below expectations
Peering bandwidth is region-pair-dependent. Plan capacity for the per-pair limit.

### Sessions drop when peering and VPN both reach a Region
The path is asymmetric. Make route preference explicit and keep peering static routes in sync.

## Procedure

### Overview

This procedure creates the peering attachment, accepts it, adds the static routes in each route
table on both sides for bidirectional traffic flow, and surfaces the console link to verify.

### Parameters

- **requester_region** (required): The Region of the requester transit gateway.
- **requester_tgw_id** (required): The requester transit gateway.
- **accepter_region** (required): The Region of the accepter transit gateway.
- **accepter_tgw_id** (required): The accepter transit gateway.
- **accepter_account_id** (required): The account that owns the accepter transit gateway.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST check CIDR overlap across both Regions before creating the attachment

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST list the VPC CIDRs in both Regions and confirm no overlap
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

#### 2. Create the peering attachment

**Constraints:**

- You MUST create the peering attachment from the requester transit gateway:

  ```
  aws ec2 create-transit-gateway-peering-attachment \
    --transit-gateway-id {requester_tgw_id} \
    --peer-transit-gateway-id {accepter_tgw_id} \
    --peer-account-id {accepter_account_id} \
    --peer-region {accepter_region} --region {requester_region}
  ```

- You MUST capture the `TransitGatewayAttachmentId` as `{peering_attachment_id}`
- You MUST poll until the attachment reaches `pendingAcceptance`:

  ```
  aws ec2 describe-transit-gateway-peering-attachments \
    --transit-gateway-attachment-ids {peering_attachment_id} --region {requester_region}
  ```

#### 3. Accept the peering attachment

**Constraints:**

- You MUST accept it on the accepter side:

  ```
  aws ec2 accept-transit-gateway-peering-attachment \
    --transit-gateway-attachment-id {peering_attachment_id} --region {accepter_region}
  ```

- You MUST poll until the attachment reaches `available`:

  ```
  aws ec2 describe-transit-gateway-peering-attachments \
    --transit-gateway-attachment-ids {peering_attachment_id} --region {requester_region}
  ```

#### 4. Add static routes on the requester side

**Constraints:**

- You MUST discover the requester-side route table from the peering attachment's existing
  association, which is unambiguous even when the requester transit gateway has multiple route
  tables in a segmented design. Do not take the first route table blindly:

  ```
  aws ec2 describe-transit-gateway-attachments \
    --transit-gateway-attachment-ids {peering_attachment_id} \
    --query 'TransitGatewayAttachments[0].Association.TransitGatewayRouteTableId' \
    --output text --region {requester_region}
  ```

- You MUST add a static route in the requester transit gateway route table pointing at the peering
  attachment for the accepter Region's ranges:

  ```
  aws ec2 create-transit-gateway-route \
    --transit-gateway-route-table-id {requester_route_table_id} \
    --destination-cidr-block {accepter_cidr} \
    --transit-gateway-attachment-id {peering_attachment_id} --region {requester_region}
  ```

#### 5. Add static routes on the accepter side

**Constraints:**

- You MUST discover the accepter-side route table from the peering attachment's existing
  association, which is unambiguous even when the accepter transit gateway has multiple route
  tables in a segmented design. Do not take the first route table blindly:

  ```
  aws ec2 describe-transit-gateway-attachments \
    --transit-gateway-attachment-ids {peering_attachment_id} \
    --query 'TransitGatewayAttachments[0].Association.TransitGatewayRouteTableId' \
    --output text --region {accepter_region}
  ```

- You MUST add a static route in the accepter transit gateway route table pointing at the peering
  attachment for the requester Region's ranges:

  ```
  aws ec2 create-transit-gateway-route \
    --transit-gateway-route-table-id {accepter_route_table_id} \
    --destination-cidr-block {requester_cidr} \
    --transit-gateway-attachment-id {peering_attachment_id} --region {accepter_region}
  ```

- You MUST add routes on both sides for bidirectional traffic flow.

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST confirm the peering attachment is `available`:

  ```
  aws ec2 describe-transit-gateway-peering-attachments \
    --transit-gateway-attachment-ids {peering_attachment_id} --region {requester_region}
  ```

- You MUST present the transit gateway console link for each Region, filling `{requester_tgw_id}`/`{accepter_tgw_id}`
  and `{requester_region}`/`{accepter_region}`, and tell the customer to open it and confirm the peering attachment and routes:

  ```
  https://{requester_region}.console.aws.amazon.com/vpc/home?region={requester_region}#TransitGatewayAttachments:
  https://{accepter_region}.console.aws.amazon.com/vpc/home?region={accepter_region}#TransitGatewayAttachments:
  ```

### Example

#### Example input

```json
{
  "requester_region": "us-east-1",
  "requester_tgw_id": "tgw-east",
  "accepter_region": "eu-west-1",
  "accepter_tgw_id": "tgw-eu",
  "accepter_account_id": "111122223333"
}
```

#### Example output

```
Checked CIDRs across us-east-1 and eu-west-1: no overlap.
Created the peering attachment from tgw-east; waited for pendingAcceptance.
Accepted it on tgw-eu; polled until available.
Added static routes on both sides: requester route table points accepter CIDRs at the peering
attachment; accepter route table points requester CIDRs at the peering attachment. Bidirectional
traffic flow confirmed.
Flagged: peering bandwidth is region-pair-dependent; if a VPN also reaches these Regions, set path
preference explicitly and keep the static routes in sync.
Open the transit gateway attachments in each Region and confirm:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayAttachments:
https://eu-west-1.console.aws.amazon.com/vpc/home?region=eu-west-1#TransitGatewayAttachments:
```

### Troubleshooting

#### Attachment stuck in pending
Not accepted. Accept on the accepter side (Step 3).

#### No traffic after peering
Static routes missing. Add them in each route table on both sides (Steps 4 and 5).

#### Connectivity fails between Regions
CIDRs overlap. Re-check and re-address (Step 1).

## Additional Resources

- [Create a peering attachment in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-peering-create.html)
- [How AWS Transit Gateway works: Example: Peered transit gateways (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/how-transit-gateways-work.html)
- [Transit gateway peering attachments in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-peering.html)
- [Using the AWS CDK and AWS Transit Gateway Inter-Region peering to build a global network (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/using-the-aws-cdk-and-aws-transit-gateway-inter-region-peering-to-build-a-global-network/)
