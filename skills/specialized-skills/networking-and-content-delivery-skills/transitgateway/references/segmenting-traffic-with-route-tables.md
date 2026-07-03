# Segmenting Traffic with Transit Gateway Route Tables

## Overview

Domain expertise for controlling which attachments on a transit gateway can reach which, so some
groups of VPCs talk to each other while others stay isolated (keeping production separate from
development while both reach shared services). Covers the open default that defeats segmentation,
the association-versus-propagation distinction that decides direction, the small number of route
tables a real design needs, and the blackhole routes that keep isolation from leaking.

Does not cover creating the transit gateway or attaching VPCs (a separate reference), centralized
egress, hybrid connectivity, peering, or multicast. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every
command in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Decision: association vs propagation
- The open default defeats segmentation
- How many route tables
- Blackhole routes
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To segment traffic end to end, follow the procedure exactly. See the Procedure section below. It
covers creating one route table per routing domain, associating each attachment with the table that
defines what it can reach, propagating attachment routes only into the tables allowed to reach them,
adding blackhole routes for ranges that must stay blocked, and surfacing the console link to verify.

## Decision: association vs propagation

The two controls do different jobs and are easy to confuse.

| Control | What it sets |
| --- | --- |
| Association | Which route table an attachment uses for its own outbound lookups (where its traffic can go) |
| Propagation | Which route tables learn this attachment as a reachable destination (who can reach it) |

**Constraints:**

- You MUST set association and propagation deliberately for each attachment, not leave them on the
  default
- You MUST explain that association controls the outbound direction and propagation controls
  reachability, since wiring one when the other was meant either opens or blocks the wrong path

## The open default defeats segmentation

With default association and propagation on, every attachment lands on one route table and can
reach every other. The isolation the customer assumed is not there. Segmentation comes from
association and propagation choices, not from creating the transit gateway.

**Constraints:**

- You MUST confirm default route table association and propagation are off before building a
  segmented design
- You MUST make the segmentation model explicit rather than rely on an open default

## How many route tables

A workable segmented design uses a small number of route tables, such as one per environment plus a
shared services table, not a separate transit gateway per environment and not a route table per VPC.

**Constraints:**

- You SHOULD reach for route table segmentation before extra transit gateways
- You SHOULD use a table per routing domain (for example: production, development, shared services),
  not one per VPC

## Blackhole routes

Controlling association and propagation is not enough on its own. If a more specific route for a
range exists in another table (for example propagated into a shared-services table), traffic to a
range the customer meant to block can still find a path. A blackhole route drops traffic for a
range explicitly.

**Constraints:**

- You MUST add blackhole routes for the ranges the customer wants to deny, as part of the
  segmentation recipe
- You MUST NOT rely on the mere absence of a route for isolation, since another table's propagation
  can add one

## Security considerations

Segmentation is itself a security control, so a misconfiguration silently weakens isolation rather
than failing loudly. Propagating an attachment into the wrong table leaks routes between environments
the customer meant to keep separate, and the gap is invisible until traffic crosses a boundary.

**Constraints:**

- You MUST treat a misconfigured propagation as a security risk, since it can leak routes between
  isolated environments without any error
- You SHOULD recommend regular route table audits (review associations, propagations, and routes
  against the intended segmentation model)
- You SHOULD recommend enabling AWS CloudTrail to detect unauthorized
  `associate-transit-gateway-route-table` and `enable-transit-gateway-route-table-propagation` calls
- You SHOULD recommend AWS Config rules to detect drift from the intended segmentation model

## Troubleshooting

### Everything reaches everything despite separate tables
Default association and propagation are still on, or attachments are still on the default table.
Move each attachment to its domain's table and turn the defaults off.

### A path is open that should be closed
Propagation is enabled into a table that should not learn that attachment, or a blackhole route is
missing. Remove the propagation or add a blackhole route for the range.

### A path is closed that should be open
The attachment is associated with the wrong table, or the destination is not propagated into the
source's table. Fix the association or enable propagation.

### Traffic leaks to a blocked range
A more specific route exists in another table. Add an explicit blackhole route for the range.

## Procedure

### Overview

This procedure creates the route tables, associates each attachment with its domain's table,
propagates destinations only where allowed, adds blackhole routes for blocked ranges, and surfaces
the console link to verify.

### Parameters

- **region** (required): The Region that holds the transit gateway.
- **transit_gateway_id** (required): The transit gateway to segment.
- **domains** (required): The routing domains and which attachments belong to each (for example
  production, development, shared services).
- **blocked_ranges** (optional): Ranges that must be denied even if a route exists elsewhere.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm default route table association and propagation are off

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST confirm default route table association and propagation are off before building a
  segmented design
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

#### 2. Create a route table per domain

**Constraints:**

- You MUST create one transit gateway route table per routing domain:

  ```
  aws ec2 create-transit-gateway-route-table \
    --transit-gateway-id {transit_gateway_id} --region {region}
  ```

- You MUST capture each `TransitGatewayRouteTableId`
- You MUST poll until each route table reaches `available`:

  ```
  aws ec2 describe-transit-gateway-route-tables \
    --transit-gateway-route-table-ids {route_table_id} --region {region}
  ```

#### 3. Associate each attachment with its domain's table

**Constraints:**

- You MUST first disassociate the attachment from any existing route table if it is already
  associated (an attachment can only be associated with one route table at a time):

  ```
  aws ec2 disassociate-transit-gateway-route-table \
    --transit-gateway-route-table-id {old_route_table_id} \
    --transit-gateway-attachment-id {attachment_id} --region {region}
  ```

- You MUST associate each attachment with the route table that defines what it can reach:

  ```
  aws ec2 associate-transit-gateway-route-table \
    --transit-gateway-route-table-id {route_table_id} \
    --transit-gateway-attachment-id {attachment_id} --region {region}
  ```

- You MUST poll until the association reaches `associated`:

  ```
  aws ec2 get-transit-gateway-route-table-associations \
    --transit-gateway-route-table-id {route_table_id} --region {region}
  ```

#### 4. Propagate destinations only where allowed

**Constraints:**

- You MUST enable propagation of an attachment into a route table only when that domain is allowed
  to reach the attachment:

  ```
  aws ec2 enable-transit-gateway-route-table-propagation \
    --transit-gateway-route-table-id {route_table_id} \
    --transit-gateway-attachment-id {attachment_id} --region {region}
  ```

- You MUST NOT propagate an attachment into a table whose domain should not reach it

#### 5. Add blackhole routes for blocked ranges

**Constraints:**

- You MUST add a blackhole route for each range that must stay blocked:

  ```
  aws ec2 create-transit-gateway-route \
    --transit-gateway-route-table-id {route_table_id} \
    --destination-cidr-block {blocked_range} --blackhole --region {region}
  ```

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST review the routes in each table to confirm the intended reachability:

  ```
  aws ec2 search-transit-gateway-routes \
    --transit-gateway-route-table-id {route_table_id} \
    --filters Name=state,Values=active,blackhole --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`
  from the API response, and tell the customer to open it and review the route tables:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayRouteTables:
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-0abc",
  "domains": {
    "domain-alpha": ["tgw-attach-alpha"],
    "domain-beta": ["tgw-attach-beta"],
    "shared": ["tgw-attach-shared"]
  },
  "blocked_ranges": ["10.20.0.0/16"]
}
```

#### Example output

```
Created three route tables: domain-alpha, domain-beta, shared.
Associated each attachment with its domain's table.
Propagated shared into domain-alpha and domain-beta (both reach shared services); did not propagate
domain-alpha and domain-beta into each other (kept isolated).
Added a blackhole route for 10.20.0.0/16 in the domain-alpha and domain-beta tables.
Open the transit gateway route tables and review reachability:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayRouteTables:
```

### Troubleshooting

#### Two isolated domains can still reach each other
They are propagated into each other's tables, or still on the default table. Remove the propagation
and confirm each is on its own domain table (Steps 3 and 4).

#### Traffic reaches a range that should be blocked
A more specific route exists elsewhere. Add a blackhole route for the range (Step 5).

#### A domain cannot reach shared services
Shared is not propagated into that domain's table. Enable propagation of the shared attachment
(Step 4).

## Additional Resources

- [Transit gateway route tables in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-route-tables.html)
- [Associate a transit gateway route table in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/associate-tgw-route-table.html)
- [Enable route propagation to a transit gateway route table in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/enable-tgw-route-propagation.html)
- [Field Notes: Working with Route Tables in AWS Transit Gateway (AWS Architecture Blog)](https://aws.amazon.com/blogs/architecture/field-notes-working-with-route-tables-in-aws-transit-gateway/)
