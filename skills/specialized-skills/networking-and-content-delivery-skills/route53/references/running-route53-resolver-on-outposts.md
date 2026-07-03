# Running Route 53 Resolver on AWS Outposts

## Overview

Domain expertise for running a VPC Resolver (also known as Route 53 Resolver) locally on an AWS
Outposts rack so DNS queries from on-Outpost workloads resolve without round-tripping to the
parent Region, including when the Outpost loses its connection back to the Region. Covers the
compute capacity the local Resolver reserves, the security group rules outbound endpoints need,
and the feature parity gaps versus the Region.

Does not cover in-Region resolver endpoints for hybrid networks, or hosted zone and record
management, which stay in the Region. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- The capacity reservation
- The security group trap
- The parity gaps
- Decision: reserve Resolver capacity at order time vs later
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To run the Resolver locally on an Outpost, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Reserving capacity and enabling the local Resolver on the rack
- Connecting the local Resolver to on-premises DNS through an outbound endpoint and forwarding rule
- Designing around the Region-only feature gaps
- Surfacing the console link to verify

## The capacity reservation

The local Resolver reserves compute on the rack before any workload runs.

**Constraints:**

- You MUST surface the capacity reservation before the customer lays out workloads, not after.
  The local Resolver consumes at least 4 EC2 instances, and each Resolver endpoint adds 2 more
- You MUST tell the customer that capacity can be reserved at order time or on an existing rack,
  and that enabling the Resolver later requires freeing instances first if it was not reserved at
  order time

## The security group trap

**Constraints:**

- You MUST ensure an outbound endpoint's security group allows both TCP and UDP outbound for DNS.
  With only one, the endpoint comes up healthy but cannot forward queries, which surfaces as
  silent resolution failures rather than a clear error

## The parity gaps

**Constraints:**

- You MUST flag the Region-only features before the customer commits to a design that depends on
  one. Health checks, DNS Firewall, and Traffic Flow do not run on the Outpost. Hosted zones and
  record management stay in the parent Region. Only the IPv4 endpoint type is available for
  Resolver endpoints on Outposts

## Decision: reserve Resolver capacity at order time vs later

| Choice | Use when |
| --- | --- |
| At order time | The customer knows they want local DNS, so the instance reservation is planned into the rack from the start |
| Later | The rack has free capacity; otherwise instances must be freed before the Resolver can be enabled |

## Troubleshooting

### Less workload capacity than expected on the rack
The local Resolver reserved 4+ instances, plus 2 per endpoint. Account for the reservation in
capacity planning; reserve at order time.

### Outbound endpoint healthy but queries fail
The security group is missing TCP or UDP outbound for DNS. Allow both.

### A feature works in-Region but not on the Outpost
Health checks, DNS Firewall, and Traffic Flow do not run locally. Keep those in the Region.

### Stale DNS responses during or after a Service Link disconnection
When the Outpost loses connectivity to the parent Region, the local Resolver continues serving
cached responses for up to 7 days. After 7 days without a refresh from the Region, cached entries
expire and queries return SERVFAIL. Control plane changes and health-check-based failover are
unavailable until connectivity is restored.

## Procedure

### Overview

This procedure runs a VPC Resolver locally on an AWS Outposts rack so on-Outpost workloads
resolve DNS without round-tripping to the parent Region. It reserves capacity and enables the
local Resolver, connects it to on-premises DNS through endpoints, designs around the Region-only
feature gaps, and surfaces the console link to verify.

### Parameters

- **outpost_arn** (required): The Outpost ARN (e.g.,
  `arn:aws:outposts:us-east-1:123456789012:outpost/op-0abc123def456789a`).
- **region** (required): The Outpost's home Region (e.g., `us-east-1`).
- **connect_on_prem** (optional, default: false): Whether to create an outbound endpoint to
  on-premises DNS.
- **on_prem_domains** (required when connect_on_prem is true): The on-premises domain(s) to forward
  (e.g., `corp.example.com`). A conditional forwarding rule is created per domain.
- **on_prem_dns_ips** (required when connect_on_prem is true): The on-premises DNS server IPs to
  forward queries to.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST surface the capacity reservation before enabling the Resolver

### Steps

#### 1. Verify dependencies and capacity

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST tell the customer the local Resolver reserves at least 4 EC2 instances on the rack,
  and each Resolver endpoint adds 2 more, before enabling it
- If capacity was not reserved at order time, you MUST confirm there are free instances or have
  the customer free some first

#### 2. Enable the local Resolver

**Constraints:**

- You MUST enable the Resolver on the Outpost so on-Outpost workloads resolve locally:

  ```
  aws route53resolver create-outpost-resolver \
    --creator-request-id {unique_id} \
    --name {name} --outpost-arn {outpost_arn} \
    --preferred-instance-type {instance_type} --region {region}
  ```

#### 3. Connect to on-premises DNS (optional)

**Constraints:**

- If `connect_on_prem` is true, create an outbound endpoint on the Outpost. You MUST allow both
  TCP and UDP outbound for DNS on the endpoint's security group, or it comes up healthy but
  forwards nothing. You MUST scope those port-53 outbound rules to the on-premises DNS server IPs
  supplied in `on_prem_dns_ips`, never `0.0.0.0/0`:

  ```
  aws route53resolver create-resolver-endpoint \
    --creator-request-id {unique_id} \
    --name {name} --direction OUTBOUND \
    --security-group-ids {sg_id_with_tcp_and_udp} \
    --ip-addresses SubnetId={outpost_subnet_1} SubnetId={outpost_subnet_2} \
    --outpost-arn {outpost_arn} \
    --preferred-instance-type {instance_type} \
    --region {region}
  ```

- You MUST also create a conditional forwarding rule and associate it with the VPC. The outbound
  endpoint alone forwards nothing; the rule names which domains forward to which on-premises DNS
  IPs. Create one rule per entry in `on_prem_domains`:

  ```
  aws route53resolver create-resolver-rule \
    --creator-request-id {unique_id} \
    --name {name} --rule-type FORWARD \
    --domain-name {on_prem_domain} \
    --resolver-endpoint-id {outbound_endpoint_id} \
    --target-ips Ip={on_prem_dns_ip},Port=53 \
    --region {region}

  aws route53resolver associate-resolver-rule \
    --resolver-rule-id {rule_id} \
    --vpc-id {vpc_id} \
    --region {region}
  ```

#### 4. Design around the parity gaps

**Constraints:**

- You MUST flag that health checks, DNS Firewall, and Traffic Flow do not run on the Outpost, and
  that hosted zones and record management stay in the parent Region, before the customer commits
  to a design that depends on a Region-only feature. Only the IPv4 endpoint type is available for
  Resolver endpoints on Outposts

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST present the Outpost Resolvers console view for the Outpost's home Region, filling
  `{region}`:

  ```
  https://console.aws.amazon.com/route53resolver/home?region={region}#/resolveroutposts
  ```

### Example

#### Example input

```json
{
  "outpost_arn": "arn:aws:outposts:us-east-1:123456789012:outpost/op-0abc123def456789a",
  "region": "us-east-1",
  "connect_on_prem": true,
  "on_prem_domains": ["corp.example.com"],
  "on_prem_dns_ips": ["10.0.0.2"]
}
```

#### Example output

```
Enabled local Resolver on op-0abc123 (reserved 4 instances). Created outbound endpoint
(TCP+UDP) plus a forwarding rule for corp.example.com -> 10.0.0.2:53, associated with the VPC.
Verify in the console:
https://console.aws.amazon.com/route53resolver/home?region=us-east-1#/resolveroutposts
```

### Troubleshooting

#### Less workload capacity than expected on the rack
The local Resolver reserved 4+ instances, plus 2 per endpoint. Account for it; reserve at order
time (Step 1).

#### Outbound endpoint healthy but queries fail
Security group missing TCP or UDP outbound for DNS. Allow both (Step 3).

#### A feature works in-Region but not on the Outpost
Health checks, DNS Firewall, and Traffic Flow do not run locally. Keep those in the Region (Step 4).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST scope the outbound endpoint's port-53 security group rules to the on-premises DNS server
  IPs, never `0.0.0.0/0`, because an open rule exposes the resolver to unauthorized queries.
- You MUST enable Resolver query logging on the Outpost VPC to an encrypted destination (KMS on
  CloudWatch Logs, SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and
  ensure CloudTrail is enabled to audit resolver and endpoint changes, because query logs can
  reveal the infrastructure topology of the workloads on the rack.

## Additional Resources

- [What is Amazon Route 53 on Outposts? (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/outpost-resolver.html)
- [Creating outbound endpoints (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/outpost-resolver-add-outbound-endpoints.html)
- [Route 53 Local Resolver on Outposts (AWS Outposts High Availability whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/aws-outposts-high-availability-design/route53-local-resolver.html)
