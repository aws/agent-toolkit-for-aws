# Resolving Private DNS for Hybrid Networks with Route 53

## Overview

Domain expertise for private DNS resolution in both directions across a hybrid network: AWS
workloads resolving on-premises hostnames, and on-premises workloads resolving AWS private hosted
zones. Spans private hosted zones and VPC Resolver (also known as Route 53 Resolver) inbound and
outbound endpoints with conditional forwarding. Covers the connectivity precondition, the
endpoint-direction confusion, the forwarding-rule step, and multi-account rule sharing.

Does not cover the connectivity layer itself (AWS Direct Connect or VPN setup) beyond treating it
as a prerequisite, or VPC Resolver on AWS Outposts. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Critical precondition: a network path must exist
- The endpoint-direction rule
- Decision: per-account rules vs shared rules
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To build hybrid DNS resolution, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Confirming a network path (Direct Connect or VPN) exists before building any DNS resource
- Creating inbound and outbound endpoints for each direction of resolution
- Adding the conditional forwarding rule that makes outbound resolution work
- Sharing resolver rules across accounts through AWS Resource Access Manager (RAM)
- Surfacing the console links to verify

## Critical precondition: a network path must exist

None of the DNS components resolve anything without a working AWS Direct Connect or VPN
connection between the VPC and on-premises.

**Constraints:**

- You MUST check for a usable network path before creating any DNS resource
- If no path exists, you MUST tell the customer plainly. You MAY still offer to set up the
  Route 53 components when the customer is deliberately building ahead of a planned connection,
  but only after stating explicitly that resolution will not work until the path is in place, so
  the customer is not left with a half-finished setup they believe is broken

## The endpoint-direction rule

This is the most common point of confusion. The direction names which way queries flow.

| Endpoint | Direction | Enables |
| --- | --- | --- |
| Inbound | On-premises to AWS | On-premises clients resolve AWS private hosted zone records |
| Outbound | AWS to on-premises | AWS clients resolve on-premises hostnames (needs a forwarding rule) |

**Constraints:**

- You MUST create the endpoint type that matches the direction of resolution the customer needs,
  and walk through both directions explicitly when both are needed. A first-time hybrid setup
  commonly ends with one direction working and the other broken
- You MUST add a conditional forwarding rule for outbound resolution. An outbound endpoint alone
  does nothing until a rule names the on-premises domains and the DNS server IPs to forward to
- You MUST scope the endpoint security group's port-53 rules to the on-premises CIDR ranges or known
  DNS server IPs, never `0.0.0.0/0`: inbound TCP/UDP 53 from the on-premises ranges on an inbound
  endpoint, outbound TCP/UDP 53 to the on-premises DNS server IPs on an outbound endpoint. An
  open `0.0.0.0/0` rule exposes the resolver to unauthorized queries

## Decision: per-account rules vs shared rules

| Choice | Use when |
| --- | --- |
| Shared rules from a hub VPC via RAM | Multi-account setups, to avoid the drift of recreating rules per account |
| Per-account rules | A single isolated account |

## Troubleshooting

### Nothing resolves across the hybrid boundary
No Direct Connect or VPN path is carrying queries. Confirm connectivity first; build DNS only
once a path exists.

### One direction resolves, the other does not
Wrong endpoint type for the needed direction. Inbound for on-premises-to-AWS, outbound for
AWS-to-on-premises.

### Outbound endpoint exists but on-premises names fail
No conditional forwarding rule. Add a rule naming the on-premises domains and DNS server IPs.

### Resolver rules drift across accounts
Rules were recreated per account. Share rules from a hub VPC through AWS RAM.

### Queries dropped or throughput lower than expected
The security group attached to the endpoint may have incorrect or connection-tracking rules.
Check that:

- Inbound endpoint: security group has **inbound** rules allowing TCP and UDP on port 53.
- Outbound endpoint: security group has **outbound** rules allowing TCP and UDP on port 53
  (or the port your on-premises DNS server uses).

Certain security group rules cause connection tracking, which can reduce max queries per second
significantly. See [Values for inbound endpoints](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries-values.html) and [Values for outbound endpoints](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-outbound-queries-endpoint-values.html) for guidance on avoiding this.

## Procedure

### Overview

This procedure builds private DNS resolution in both directions across a hybrid network. It
confirms a network path exists, creates VPC Resolver inbound and outbound endpoints for the
needed directions, adds the conditional forwarding rule that makes outbound resolution work,
shares resolver rules across accounts, and surfaces the console links to verify.

### Parameters

- **vpc_id** (required): The VPC that holds the endpoints (e.g., `vpc-0abc123`).
- **region** (required): The AWS Region (e.g., `us-east-1`).
- **direction** (required): `inbound`, `outbound`, or `both`.
- **on_prem_domains** (required for outbound): The on-premises domains to forward (e.g., `corp.example.com`).
- **on_prem_dns_servers** (required for outbound): On-premises DNS server addresses as `IP` or
  `IP:PORT`. Port defaults to 53 if omitted. Specify multiple entries for redundancy
  (e.g., `["10.0.0.2", "10.0.0.3:5353"]`).
- **security_group_ids** (required): IDs of one or more security groups to attach to the endpoints.
  Their port-53 rules MUST be scoped to the on-premises CIDR ranges or known DNS server IPs (see the
  Step 2/3 constraint), not `0.0.0.0/0`.
- **subnet_ids** (required): At least two subnet IDs in different Availability Zones (the API minimum, and the redundancy recommendation).
- **share_principals** (optional): Account IDs or OU ARNs to share resolver rules with.
- **creator_request_id** (agent-generated): A unique string the API requires for idempotency.
  The agent generates this automatically using `uuidgen`; do not ask the customer for it.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the VPC and direction before writing

### Steps

#### 1. Verify dependencies and the network path

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.
- You MUST confirm a working Direct Connect or VPN path exists between the VPC and on-premises
  before creating any DNS resource. If none exists, state it plainly. You MAY proceed to build
  ahead only after telling the customer resolution will not work until the path is live

#### 2. Create the inbound endpoint (on-premises to AWS)

**Constraints:**

- If `direction` is `inbound` or `both`, create an inbound endpoint so on-premises clients can
  resolve AWS private hosted zone records:

  ```
  aws route53resolver create-resolver-endpoint \
    --creator-request-id $(uuidgen) \
    --name {name} --direction INBOUND \
    --security-group-ids {sg_id} \
    --ip-addresses SubnetId={subnet_a} SubnetId={subnet_b} \
    --region {region}
  ```

- You SHOULD recommend that on-premises clients connect to the inbound endpoint over DoT (DNS over
  TLS) or DoH (DNS over HTTPS) rather than plaintext Do53, because Do53 exposes queried domain names
  to on-path observers on the hybrid link

#### 3. Create the outbound endpoint (AWS to on-premises)

**Constraints:**

- If `direction` is `outbound` or `both`, create an outbound endpoint:

  ```
  aws route53resolver create-resolver-endpoint \
    --creator-request-id $(uuidgen) \
    --name {name} --direction OUTBOUND \
    --security-group-ids {sg_id} \
    --ip-addresses SubnetId={subnet_a} SubnetId={subnet_b} \
    --region {region}
  ```

#### 4. Add the conditional forwarding rule for outbound

**Constraints:**

- If `direction` is `outbound` or `both`, you MUST create a forwarding rule for outbound resolution
  (skip this step entirely when `direction` is `inbound` only — `on_prem_domains` and
  `on_prem_dns_servers` are not provided in that case). The outbound endpoint does nothing
  until a rule names the on-premises domains and DNS server IPs:

  ```
  aws route53resolver create-resolver-rule \
    --creator-request-id $(uuidgen) \
    --name {name} --rule-type FORWARD \
    --domain-name {on_prem_domain} \
    --resolver-endpoint-id {outbound_endpoint_id} \
    {target_ips_flags} \
    --region {region}
  ```

- Parse each entry in `on_prem_dns_servers` as `IP` or `IP:PORT`, defaulting port to 53 if
  omitted. Build `{target_ips_flags}` as a single `--target-ips` flag followed by one
  `Ip={ip},Port={port}` argument per entry
  (e.g., `--target-ips Ip=10.0.0.2,Port=53 Ip=10.0.0.3,Port=5353`).
- You MUST associate the rule with the VPC:

  ```
  aws route53resolver associate-resolver-rule \
    --resolver-rule-id {rule_id} --vpc-id {vpc_id} --region {region}
  ```

#### 5. Share resolver rules across accounts (optional)

**Constraints:**

- If `share_principals` is set, you SHOULD share the rules from a hub VPC through RAM rather than
  recreating them per account:

  ```
  aws ram create-resource-share \
    --name {share_name} --resource-arns {rule_arn} \
    --principals {share_principals} --region {region}
  ```

- The receiving account must accept the RAM resource share invitation before the rule is usable:

  ```
  aws ram accept-resource-share-invitation \
    --resource-share-invitation-arn {invitation_arn} --region {region}
  ```

- After accepting, the receiving account must associate the shared rule with its VPC:

  ```
  aws route53resolver associate-resolver-rule \
    --resolver-rule-id {rule_id} --vpc-id {consumer_vpc_id} --region {region}
  ```

#### 6. Verify and surface the console links

**Constraints:**

- You MUST verify resolution works in each configured direction
- You MUST enable Resolver query logging on the VPC to monitor forwarded queries and detect
  anomalous resolution patterns, with encryption at rest on the log destination
- You MUST present the console links, filling `{region}`:
  - Inbound endpoints:

    ```
    https://console.aws.amazon.com/route53resolver/home?region={region}#/inbound-endpoints
    ```

  - Outbound endpoints:

    ```
    https://console.aws.amazon.com/route53resolver/home?region={region}#/outbound-endpoints
    ```

  - Forwarding rules:

    ```
    https://console.aws.amazon.com/route53resolver/home?region={region}#/rules
    ```

### Example

#### Example input

```json
{
  "vpc_id": "vpc-0abc123",
  "region": "us-east-1",
  "direction": "both",
  "security_group_ids": ["sg-0abc123"],
  "subnet_ids": ["subnet-0aaa111", "subnet-0bbb222"],
  "on_prem_domains": ["corp.example.com"],
  "on_prem_dns_servers": ["10.0.0.2", "10.0.0.3:5353"]
}
```

#### Example output

```
Created inbound and outbound endpoints in vpc-0abc123, plus a forwarding rule for
corp.example.com -> 10.0.0.2:53, 10.0.0.3:5353.
Verify in the console:
Inbound:  https://console.aws.amazon.com/route53resolver/home?region=us-east-1#/inbound-endpoints
Outbound: https://console.aws.amazon.com/route53resolver/home?region=us-east-1#/outbound-endpoints
Rules:    https://console.aws.amazon.com/route53resolver/home?region=us-east-1#/rules
```

### Troubleshooting

#### Nothing resolves across the hybrid boundary
No Direct Connect or VPN path. Confirm connectivity first (Step 1).

#### One direction resolves, the other does not
Wrong endpoint type for the needed direction (Steps 2 and 3).

#### Outbound endpoint exists but on-premises names fail
No conditional forwarding rule. Add one naming the on-premises domains and DNS server IPs (Step 4).

#### Resolver rules drift across accounts
Rules recreated per account. Share from a hub VPC through RAM (Step 5).

#### Queries dropped or throughput lower than expected
Check the security group rules for the endpoint:

- Inbound endpoint: needs **inbound** rules allowing TCP and UDP on port 53.
- Outbound endpoint: needs **outbound** rules allowing TCP and UDP on port 53
  (or the port your on-premises DNS server uses).

Certain rules cause connection tracking and reduce max queries per second. See
[Values for inbound endpoints](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries-values.html) and [Values for outbound endpoints](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-outbound-queries-endpoint-values.html).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST scope the resolver endpoint's port-53 security group rules to the on-premises CIDR
  ranges or known DNS server IPs, never `0.0.0.0/0`, because an open rule exposes the resolver to
  unauthorized queries from anywhere on the hybrid link.
- You SHOULD recommend that clients use DoT or DoH over the inbound endpoint rather than plaintext
  Do53, since Do53 exposes queried domain names to on-path observers on the hybrid link.
- You MUST enable Resolver query logging to an encrypted destination (KMS on CloudWatch Logs,
  SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and ensure CloudTrail
  is enabled to audit endpoint and rule changes, because query logs reveal the domains the network
  resolves.

## Additional Resources

- [Set up DNS resolution for hybrid networks in a single-account AWS environment (AWS Prescriptive Guidance)](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/set-up-dns-resolution-for-hybrid-networks-in-a-single-account-aws-environment.html)
- [DNS Query Resolution - Amazon Route 53 Resolver](https://aws.amazon.com/route53/resolver/)
- [Automating DNS infrastructure using Route 53 Resolver endpoints (Networking & Content Delivery blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/automating-dns-infrastructure-using-route-53-resolver-endpoints/)
- [Values that you specify when you create or edit inbound endpoints (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries-values.html)
- [Values that you specify when you create or edit outbound endpoints (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-outbound-queries-endpoint-values.html)
