# Deploying a Firewall and Routing Traffic Through It

## Overview

Domain expertise for placing an AWS Network Firewall in the traffic path of a VPC so that rules can
see packets. Covers reserving a dedicated firewall subnet in each Availability Zone, creating the
firewall and attaching a firewall policy, and editing the VPC route tables so traffic between
protected subnets and outside locations is forced through the firewall endpoint in both directions.

A firewall is inert until the route tables redirect traffic to its endpoints, and nothing reports an
error when that routing is missing. This is the most common reason a newly created firewall sees no
traffic. Treat the route table edits as a required step, not an afterthought.

Does not cover writing stateful or domain rules, centralized transit gateway inspection, logging, or
TLS inspection. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every `aws network-firewall` and `aws ec2` command.

## Table of Contents

- Overview
- Workflow
- Reserve a dedicated firewall subnet per Availability Zone
- Route both directions through the firewall endpoint
- Match an endpoint to each Availability Zone you protect
- Firewall creation is asynchronous
- Set rule group capacity at creation
- Encrypt firewall data at rest
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To put traffic through the firewall end to end, follow the procedure. It reserves a dedicated
firewall subnet in each Availability Zone, creates the firewall pointed at those subnets, attaches a
firewall policy, retrieves the firewall endpoint IDs, and edits the VPC route tables so traffic is
inspected symmetrically.

## Reserve a dedicated firewall subnet per Availability Zone

A firewall endpoint cannot filter traffic coming into or going out of the subnet it lives in, so the
firewall subnet must hold nothing but the firewall endpoint.

**Constraints:**

- You MUST reserve each firewall subnet for the firewall endpoint alone and keep application
  workloads out of it
- You MUST NOT place workloads in the firewall subnet to save address space; that traffic silently
  bypasses inspection and the workload runs unprotected with no error

## Route both directions through the firewall endpoint

Network Firewall does not support asymmetric routing. Request and response traffic must traverse the
same firewall endpoint, or stateful inspection breaks.

**Constraints:**

- You MUST edit the VPC route tables so traffic between protected subnets and outside locations is
  forced through the firewall endpoint; the firewall is inert until this is done
- You MUST route the return path through the firewall too. For an internet-facing VPC, set up the
  internet gateway route table (edge association) and the protected subnet route table together so
  traffic is inspected symmetrically

## Match an endpoint to each Availability Zone you protect

**Constraints:**

- You MUST place a firewall endpoint in each Availability Zone that has protected subnets; a
  single-zone deployment leaves workloads in other zones with no inspection path
- You MUST route each Availability Zone's protected subnet to its own zone's firewall endpoint

## Firewall creation is asynchronous

**Constraints:**

- You MUST poll `describe-firewall` until the firewall status is `READY` before creating routes that
  depend on the endpoint
- You MUST read the firewall endpoint IDs (`vpce-...`) from the `SyncStates` in `describe-firewall`;
  these are the route targets, not the firewall ARN or an ENI ID

## Set rule group capacity at creation

Rule group capacity (the maximum number of capacity units) is fixed when the rule group is created
and cannot be raised. A firewall built at the default capacity that later needs complex Suricata
rules or a large domain list forces the rule group to be torn down and recreated.

**Constraints:**

- You MUST ask the customer about expected rule complexity (Suricata rule count, domain list size, IP
  set references) before creating rule groups, and size capacity for that plus headroom
- You MUST state that the capacity decision is irreversible: raising it later means recreating the
  rule group, which drops its rules during the replacement

## Encrypt firewall data at rest

By default Network Firewall encrypts firewall resources with an AWS owned key. A customer-managed
AWS KMS key gives you control over the key policy and its rotation and revocation.

**Constraints:**

- You MUST specify a customer-managed AWS KMS key (`--encryption-configuration`) when creating the
  firewall to encrypt firewall data at rest
- You MUST note that deleting or revoking this key puts the firewall into a non-recoverable failed
  state, so the key must be retained for the life of the firewall

## Troubleshooting

### Firewall created but no traffic hits it
The VPC route tables were never changed to send traffic through the firewall endpoint. Add the route
table entries (Route both directions through the firewall endpoint).

### Some workloads are never inspected
Workloads sit in the firewall subnet, or in an Availability Zone with no firewall endpoint. Move
workloads out of the firewall subnet and add an endpoint per protected zone.

### Stateful inspection behaves erratically
Return traffic is taking a different path than the request. Route both directions through the same
firewall endpoint.

## Procedure

### Overview

This procedure reserves dedicated firewall subnets, creates the firewall and attaches a policy,
waits for `READY`, reads the endpoint IDs, and edits the route tables for symmetric inspection.

### Parameters

- **firewall_name** (required): Name for the firewall.
- **vpc_id** (required): The VPC to protect.
- **firewall_subnet_ids** (required): One dedicated firewall subnet per Availability Zone.
- **firewall_policy_arn** (required): The policy to attach.
- **protected_route_table_ids** (required): Route tables for the protected subnets, one per zone.
- **firewall_subnet_route_table_ids** (required): Route tables for the dedicated firewall subnets,
  one per zone, that need a default route to the next hop.
- **igw_route_table_id** (optional): The internet gateway edge route table, for an internet-facing VPC.
- **igw_id** (optional): The internet gateway ID — the next hop for the firewall subnets' default
  route in an internet-facing VPC (used with `--gateway-id`).
- **nat_gateway_id** (optional): The NAT gateway ID — the next hop for the firewall subnets' default
  route for private workloads instead of an internet gateway (used with `--nat-gateway-id`).
- **kms_key_id** (required): A customer-managed AWS KMS key to encrypt firewall data at rest.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm each firewall subnet is dedicated and contains no workloads

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm a firewall policy exists at `firewall_policy_arn`
- You MUST confirm one dedicated firewall subnet exists per protected Availability Zone

#### 2. Create the firewall

**Constraints:**

- You MUST create the firewall pointed at the dedicated subnets:

  ```
  aws network-firewall create-firewall --firewall-name {firewall_name} \
    --firewall-policy-arn {firewall_policy_arn} --vpc-id {vpc_id} \
    --subnet-mappings SubnetId={firewall_subnet_az1} SubnetId={firewall_subnet_az2} \
    --encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id} \
    --region {region}
  ```

- You MUST encrypt firewall data at rest with a customer-managed AWS KMS key by adding
  `--encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id}`, and retain that key for the
  life of the firewall (deleting or revoking it puts the firewall into a non-recoverable failed state)

#### 3. Wait for READY and read the endpoint IDs

**Constraints:**

- You MUST poll until the status is `READY`:

  ```
  aws network-firewall describe-firewall --firewall-name {firewall_name} \
    --query 'FirewallStatus.Status' --region {region}
  ```

- You MUST read the per-zone `vpce-...` endpoint IDs from `SyncStates`:

  ```
  aws network-firewall describe-firewall --firewall-name {firewall_name} \
    --query 'FirewallStatus.SyncStates' --region {region}
  ```

#### 4. Route traffic through the endpoints in both directions

**Constraints:**

- You MUST point each protected subnet's route table at its own zone's firewall endpoint:

  ```
  aws ec2 create-route --route-table-id {protected_route_table_az1} \
    --destination-cidr-block 0.0.0.0/0 --vpc-endpoint-id {vpce_az1} --region {region}
  ```

- You MUST give each firewall subnet's own route table a default route to the next hop; a newly
  dedicated firewall subnet has only the VPC local route, so without this the firewall inspects the
  traffic and then black-holes it with no error. For an internet-facing VPC the next hop is the
  internet gateway (`--gateway-id`):

  ```
  aws ec2 create-route --route-table-id {firewall_subnet_route_table_az1} \
    --destination-cidr-block 0.0.0.0/0 --gateway-id {igw_id} --region {region}
  ```

  For private workloads the next hop is a NAT gateway (`--nat-gateway-id`):

  ```
  aws ec2 create-route --route-table-id {firewall_subnet_route_table_az1} \
    --destination-cidr-block 0.0.0.0/0 --nat-gateway-id {nat_gateway_id} --region {region}
  ```

- You MUST, for an internet-facing VPC, associate the internet gateway edge route table and point
  per-subnet CIDRs at the firewall endpoints so the return path is inspected too

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm traffic is being inspected (for example with flow logging or a test connection)
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`,
  and tell the customer to open it and confirm the firewall and its endpoints:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "protected-vpc-fw",
  "vpc_id": "vpc-0123456789abcdef0",
  "firewall_subnet_ids": ["subnet-az1fw", "subnet-az2fw"],
  "firewall_policy_arn": "arn:aws:network-firewall:us-east-1:111122223333:firewall-policy/my-policy",
  "protected_route_table_ids": ["rtb-az1", "rtb-az2"],
  "firewall_subnet_route_table_ids": ["rtb-fwsub-az1", "rtb-fwsub-az2"],
  "igw_route_table_id": "rtb-igw-edge",
  "igw_id": "igw-0123456789abcdef0",
  "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/mrk-example"
}
```

#### Example output

```
Created firewall protected-vpc-fw, status READY.
Endpoints: vpce-aaa (us-east-1a), vpce-bbb (us-east-1b).
Routed rtb-az1 -> vpce-aaa, rtb-az2 -> vpce-bbb, and the IGW edge route table back through the endpoints.
Open the console and confirm the firewall and endpoints:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=protected-vpc-fw
```

### Troubleshooting

#### No traffic hits the firewall
Route tables were not updated. Add the routes (Step 4).

#### A workload is not inspected
It sits in the firewall subnet or an unprotected zone. Move it out and add a per-zone endpoint and route (Steps 2–4).

## Security Considerations

A firewall protects nothing until traffic is forced through it and a rule set inspects that traffic.

- You MUST route both directions through the firewall endpoint; missing or asymmetric routing
  silently bypasses inspection with no error, leaving workloads unprotected.
- You MUST configure a stateful default action of drop (an allow list of permitted traffic) rather
  than default-allow, so traffic that matches no rule is blocked rather than passed uninspected;
  fail-closed is a fundamental security control for a network firewall, not an option.
- You MUST encrypt the firewall's data at rest with a customer-managed AWS KMS key, and retain that
  key for the life of the firewall, since deleting or revoking it puts the firewall into a
  non-recoverable failed state.
- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access, since these control what traffic is inspected.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to monitor firewall endpoint status, rule group capacity
  utilization, and sudden drops in processed traffic volume, so issues are detected and escalated
  promptly. You MUST encrypt any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key and restrict alarm notification recipients to authorized operations and
  security personnel, since alarm messages can expose sensitive firewall metadata (endpoint status,
  traffic patterns, and capacity).

## Additional Resources

- [High-level steps for implementing AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/firewall-high-level-steps.html)
- [VPC subnet configuration for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/vpc-config-subnets.html)
- [Route table configurations for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/route-tables.html)
- [Simple single zone architecture with an internet gateway using AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/arch-single-zone-igw.html)
- [Deployment models for AWS Network Firewall (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/deployment-models-for-aws-network-firewall/)
- [Rule group capacity in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/rule-group-capacity.html)
