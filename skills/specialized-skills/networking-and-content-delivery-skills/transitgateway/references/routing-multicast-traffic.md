# Routing Multicast Traffic on a Transit Gateway

## Overview

Domain expertise for distributing IP multicast from one sender to many receivers across attached
VPCs through a transit gateway multicast domain. Covers the subnet associations that delivery
depends on, the choice between Internet Group Management Protocol (IGMP) and static group
membership, and verifying that membership actually forms when IGMP is used.

Does not cover creating the hub for unicast, segmentation, egress, hybrid connectivity, or peering.
Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. A transit gateway is Regional; run every command
in the Region that holds the hub.

## Table of Contents

- Overview
- Workflow
- Decision: IGMP vs static membership
- Subnet associations
- Verifying IGMP membership
- Security considerations
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To route multicast end to end, follow the procedure exactly. See the Procedure section below. It
covers creating a transit gateway with multicast enabled, creating a multicast domain, associating
the source and receiver subnets, establishing group membership (IGMP or static), and surfacing the
console link to verify.

## Decision: IGMP vs static membership

| Membership | Behavior |
| --- | --- |
| IGMP | Receivers join by sending IGMPv2 join messages; the domain tracks membership dynamically |
| Static | The customer registers each group member by hand; membership is fixed |

**Constraints:**

- You MUST set the membership model based on whether the customer needs dynamic join (IGMP) or fixed
  membership (static)
- You MUST configure the domain to match: a static domain will not honor IGMP joins, and a customer
  expecting dynamic membership on a static domain sees members that never update

## Subnet associations

Multicast delivery depends on the subnets holding sources and receivers being associated with the
multicast domain. Association is a separate step from creating the domain, and an unassociated
subnet produces no error: the multicast just does not arrive.

**Constraints:**

- You MUST associate every subnet that holds a source or a receiver with the multicast domain
- You MUST NOT assume domain creation alone delivers traffic; the associations carry it

## Verifying IGMP membership

With IGMP, group membership depends on the right subnet associations and on receivers actually
sending join messages from associated subnets. A misconfigured source subnet means joins are not
seen, and the domain can look correct while membership never forms.

**Constraints:**

- You MUST verify the source and receiver subnet associations together with the IGMP configuration
- You SHOULD confirm receivers are sending IGMPv2 joins from associated subnets before concluding
  the setup is correct

## Security considerations

Multicast distributes one sender's traffic to many receivers across attached VPCs, so the subnet
associations that carry delivery also define who can receive a group's traffic, alongside the
standard hub-wide logging controls. The controls are embedded in the procedure; this section
consolidates them.

**Constraints:**

- You MUST associate only the subnets that should send or receive a group's traffic with the
  multicast domain, since an unneeded association silently extends delivery to that subnet
- You MUST match the membership model (IGMP vs static) to intent, since a misconfigured domain can
  leave membership stale or unverified
- You MUST enable VPC Flow Logs on the attached VPC subnets and Transit Gateway Flow Logs on the hub
  with encryption at rest on the destination, and you SHOULD enable AWS CloudTrail (encrypted) to
  detect unauthorized changes to attachments, route tables, associations, and propagations
- You MUST, when a KMS key encrypts a flow log or CloudTrail destination, scope the KMS key policy
  with condition keys (`aws:SourceArn`, `aws:SourceAccount`, `kms:ViaService`) so only the specific
  log group, bucket, or trail in the expected account and service can use the key
- You SHOULD apply least-privilege IAM for transit gateway administration, avoiding service wildcards
  and FullAccess policies

## Troubleshooting

### Receivers get no multicast traffic
The source or receiver subnets are not associated with the domain. Associate every source and
receiver subnet.

### Receivers never join (IGMP expected)
The domain is static, or joins come from unassociated subnets. Use an IGMP domain and confirm subnet
associations.

### Membership does not update as instances change (static expected dynamic)
The domain is static; static membership is fixed. Use IGMP for dynamic join.

### Domain looks correct but no delivery
IGMP joins are not seen, often a source subnet misconfiguration. Verify associations and that
receivers send joins from associated subnets.

## Procedure

### Overview

This procedure creates a multicast-enabled transit gateway, creates the multicast domain, associates
the source and receiver subnets, establishes group membership, and surfaces the console link to
verify.

### Parameters

- **region** (required): The Region that holds the hub.
- **transit_gateway_id** (required, or create one): The multicast-enabled transit gateway.
- **membership_model** (required): `igmp` or `static`.
- **source_subnets** (required): Subnets holding multicast sources.
- **receiver_subnets** (required): Subnets holding receivers.
- **group_members** (required for static): The receiver network interfaces to register per group.
- **attachment_id** (required): The transit gateway attachment ID for the VPC(s) containing multicast sources and receivers.
- **multicast_group_ip** (required): The multicast group IP address (e.g. 239.1.1.1).
- **source_eni_id** (required for static sources): The network interface ID of the multicast source.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm whether the customer needs dynamic join (IGMP) or fixed membership (static)

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use short-lived,
  ephemeral credentials scoped to least privilege for transit gateway administration, never
  long-lived access keys or broad service wildcard or FullAccess policies
- You MUST confirm the transit gateway has multicast support enabled, or create one with
  `MulticastSupport=enable`
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

#### 2. Create the multicast domain

**Constraints:**

- You MUST create the multicast domain with the correct settings for the chosen membership model.
- For IGMP membership:

  ```
  aws ec2 create-transit-gateway-multicast-domain \
    --transit-gateway-id {transit_gateway_id} \
    --options Igmpv2Support=enable,StaticSourcesSupport=disable --region {region}
  ```

- For static membership:

  ```
  aws ec2 create-transit-gateway-multicast-domain \
    --transit-gateway-id {transit_gateway_id} \
    --options Igmpv2Support=disable,StaticSourcesSupport=enable --region {region}
  ```

- You MUST capture the `TransitGatewayMulticastDomainId` as `{multicast_domain_id}`

#### 3. Associate the source and receiver subnets

**Constraints:**

- You MUST associate every source and receiver subnet (via its VPC attachment) with the domain:

  ```
  aws ec2 associate-transit-gateway-multicast-domain \
    --transit-gateway-multicast-domain-id {multicast_domain_id} \
    --transit-gateway-attachment-id {attachment_id} \
    --subnet-ids {subnet_ids} --region {region}
  ```

#### 4. Establish group membership

**Constraints:**

- For static membership, you MUST register multicast group sources:

  ```
  aws ec2 register-transit-gateway-multicast-group-sources \
    --transit-gateway-multicast-domain-id {multicast_domain_id} \
    --group-ip-address {multicast_group_ip} \
    --network-interface-ids {source_eni_id} --region {region}
  ```

- For static membership, you MUST register each group member:

  ```
  aws ec2 register-transit-gateway-multicast-group-members \
    --transit-gateway-multicast-domain-id {multicast_domain_id} \
    --group-ip-address {multicast_group_ip} \
    --network-interface-ids {group_members} --region {region}
  ```

- For IGMP, you MUST confirm receivers send IGMPv2 joins from associated subnets (no manual
  registration needed)

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST review the registered group members or sources to confirm membership:

  ```
  aws ec2 search-transit-gateway-multicast-groups \
    --transit-gateway-multicast-domain-id {multicast_domain_id} --region {region}
  ```

- You MUST present the transit gateway console link, filling `{transit_gateway_id}` and `{region}`,
  and tell the customer to open it and review the multicast domain:

  ```
  https://{region}.console.aws.amazon.com/vpc/home?region={region}#TransitGatewayMulticastDomains:
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "transit_gateway_id": "tgw-mcast",
  "membership_model": "igmp",
  "source_subnets": ["subnet-src-1a"],
  "receiver_subnets": ["subnet-rcv-1a", "subnet-rcv-1b"],
  "attachment_id": "tgw-attach-mcast",
  "multicast_group_ip": "239.1.1.1"
}
```

#### Example output

```
Confirmed multicast support on tgw-mcast.
Created an IGMP multicast domain.
Associated the source subnet and both receiver subnets with the domain.
IGMP membership: receivers join by sending IGMPv2 joins from the associated subnets (no manual
registration). Verified joins are seen.
Open the multicast domain in the console and review membership:
https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#TransitGatewayMulticastDomains:
```

### Troubleshooting

#### No multicast arrives
Source or receiver subnets are not associated. Associate them (Step 3).

#### Receivers never join on an IGMP domain
Joins come from unassociated subnets or the domain is static. Confirm associations and the IGMP
setting (Steps 2 and 3).

#### Static membership does not update
Static membership is fixed by design. Recreate the domain with IGMP for dynamic join (Step 2).

## Additional Resources

- [Multicast on transit gateways in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-multicast-overview.html)
- [Managing IGMP configurations for a multicast domain in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/manage-domain-igmp.html)
- [Create an IGMP multicast domain in AWS Transit Gateway (AWS Transit Gateway Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/multicast-domain-igmp.html)
