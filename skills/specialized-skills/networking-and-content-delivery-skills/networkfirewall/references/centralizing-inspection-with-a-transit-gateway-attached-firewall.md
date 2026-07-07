# Centralizing Inspection with a Transit Gateway-Attached Firewall

## Overview

Domain expertise for inspecting traffic across many VPCs from one place using a transit
gateway-attached AWS Network Firewall. Covers attaching a firewall directly to a transit gateway as
a network function attachment so AWS provisions and manages the underlying inspection resources, and
the cross-account flow when the transit gateway and the firewall live in different accounts.

The native transit gateway-attached firewall removes the hand-built inspection VPC, its firewall
endpoint subnets, and its route tables. Steer customers here for multi-VPC or multi-account
inspection rather than building an inspection VPC by hand.

Does not cover single-VPC deployment and routing, rule authoring, logging, or TLS inspection. Those
are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every command.

## Table of Contents

- Overview
- Workflow
- Prefer the transit gateway-attached firewall over an inspection VPC
- Sequence the cross-account handoff in order
- The firewall owner cannot accept the attachment
- Appliance mode is always enabled for transit gateway-attached firewalls
- Override HOME_NET to cover the spoke VPCs
- Choose a stream exception policy for scaling events
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To centralize inspection end to end, follow the procedure. In a single account it attaches the
firewall to the transit gateway directly. Across accounts it sequences three steps in two accounts:
the transit gateway owner shares the transit gateway through AWS Resource Access Manager (AWS RAM),
the firewall owner creates the firewall from the shared transit gateway, and the transit gateway
owner accepts the resulting attachment unless auto-accept is enabled.

## Prefer the transit gateway-attached firewall over an inspection VPC

**Constraints:**

- You SHOULD use the transit gateway-attached firewall for multi-VPC or multi-account inspection;
  AWS provisions and manages the inspection resources, removing the inspection VPC and its routing
- You MUST NOT default to building an inspection VPC with attachment subnets, firewall endpoint
  subnets, and hand-managed route tables; that pattern is not the recommended approach where native
  transit gateway support is available

## Sequence the cross-account handoff in order

When the transit gateway and the firewall are in different accounts, the flow spans three steps in a
specific order, and a missed handoff leaves the attachment pending with no clear error.

**Constraints:**

- You MUST sequence the cross-account flow: (1) the transit gateway owner shares the transit gateway
  through AWS RAM, (2) the firewall owner accepts the share and creates the firewall from the shared
  transit gateway, (3) the transit gateway owner accepts the attachment unless auto-accept is on
- You MUST name which account performs each step so the customer does not run a step in the wrong
  account

## The firewall owner cannot accept the attachment

**Constraints:**

- You MUST tell the firewall owner that a newly created firewall stays in a pending state until the
  transit gateway owner accepts the attachment, because the final acceptance happens in the transit
  gateway owner's account
- You SHOULD make the ownership split explicit rather than letting the firewall owner wait on a
  state they cannot change

## Appliance mode is always enabled for transit gateway-attached firewalls

Network Firewall is a stateful appliance: request and response must traverse the same firewall
endpoint, or stateful inspection breaks. In a multi-AZ transit gateway design, the transit gateway
can otherwise pick a different Availability Zone's endpoint for the return path. Appliance mode
pins a flow to the same Availability Zone's endpoint for its lifetime, and for transit
gateway-attached firewalls AWS enables it on the underlying attachment automatically.

**Constraints:**

- You MUST tell the customer that appliance mode is always enabled for transit gateway-attached
  firewalls; AWS sets it on the underlying attachment and it cannot be disabled, so no manual
  enablement step is required
- You MUST NOT instruct the customer to run `modify-transit-gateway-vpc-attachment` to enable
  appliance mode on a transit gateway-attached firewall; the attachment is AWS-managed and the call
  does not apply
- You SHOULD still treat half-open or erratically failing connections as a routing-symmetry issue
  first, but in a transit gateway-attached deployment look for asymmetric paths outside the firewall
  (for example, return traffic bypassing the transit gateway) rather than a missing appliance-mode
  flag

## Override HOME_NET to cover the spoke VPCs

**Constraints:**

- You MUST override `HOME_NET` in the firewall policy to include every spoke VPC CIDR range; the
  default covers only the inspection VPC's CIDR, so stateful domain rules and directional Suricata
  rules silently fail to match spoke traffic
- You MUST set `HOME_NET` before concluding the rules are wrong; `EXTERNAL_NET` stays the negation of
  the `HOME_NET` you set

## Choose a stream exception policy for scaling events

The firewall scales horizontally under load. The stream exception policy decides what happens to
in-flight connections when capacity shifts mid-stream, and the default drops them with no alert log.

**Constraints:**

- You SHOULD set the stream exception policy from the customer's availability tolerance: `DROP`
  (fail-closed, most secure), `CONTINUE` (passes uninspected when context is lost, for
  availability-critical workloads), or `REJECT` (drop plus a TCP reset)
- You MUST warn that with `DROP` a scaling event can reset mid-stream TCP connections and write no
  alert log, so the drop looks like it came from nowhere; centralized deployments hit this more
  because they carry more traffic and scale more often

## Troubleshooting

### Attachment stuck pending
A handoff step was missed or the transit gateway owner has not accepted the attachment. Confirm the
AWS RAM share was accepted, the firewall was created from the shared transit gateway, and the
transit gateway owner accepted the attachment (Sequence the cross-account handoff in order).

### Firewall owner cannot find where to accept
The final acceptance is in the transit gateway owner's account, not the firewall owner's. The
firewall owner cannot complete it (The firewall owner cannot accept the attachment).

### Tempted to build an inspection VPC
The native transit gateway-attached firewall replaces that pattern. Use it instead (Prefer the
transit gateway-attached firewall over an inspection VPC).

### Connections half-open or fail erratically in a centralized deployment
Return traffic is taking a different path than the request. Appliance mode is already on for the
transit gateway-attached firewall, so look for asymmetry outside the firewall — return traffic
bypassing the transit gateway, a spoke route table that sends only one direction through inspection,
or NAT placement that breaks symmetry (Appliance mode is always enabled for transit gateway-attached
firewalls).

### Rules match nothing for spoke-VPC traffic
`HOME_NET` covers only the inspection VPC. Override it to include the spoke CIDRs (Override HOME_NET
to cover the spoke VPCs).

### Intermittent connection resets under load with no alert log
A scaling event reset in-flight connections under the `DROP` stream exception policy. Set the policy
from the availability tolerance (Choose a stream exception policy for scaling events).

## Procedure

### Overview

This procedure attaches a firewall to a transit gateway. For the cross-account case it sequences the
AWS RAM share, the firewall creation, and the attachment acceptance, naming the account for each.

### Parameters

- **firewall_name** (required): Name for the firewall.
- **transit_gateway_id** (required): The transit gateway to attach to.
- **firewall_policy_arn** (required): The policy to attach.
- **cross_account** (required): Whether the transit gateway and firewall are in different accounts.
- **kms_key_id** (required): A customer-managed AWS KMS key to encrypt firewall data at rest.
- **firewall_account_id** (optional): The firewall owner account, when cross-account.
- **tgw_owner_account_id** (optional): The transit gateway owner account, when cross-account; used to
  build the transit gateway ARN for the AWS RAM share. Obtain it from `aws sts get-caller-identity`
  in the transit gateway owner account in Step 1.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm whether the deployment is cross-account before starting, because it changes the
  steps

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity` in the account performing each step, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the transit gateway exists and is in a usable state
- You MUST confirm a firewall policy exists at `firewall_policy_arn`

#### 2. (Cross-account only) Share the transit gateway from the transit gateway owner account

**Constraints:**

- You MUST, in the transit gateway owner account, share the transit gateway to the firewall owner
  through AWS RAM. Build the transit gateway ARN from `{transit_gateway_id}` and the TGW owner
  account ID (from `aws sts get-caller-identity` in Step 1) as
  `arn:aws:ec2:{region}:{tgw_owner_account_id}:transit-gateway/{transit_gateway_id}`:

  ```
  aws ram create-resource-share --name shared-tgw \
    --resource-arns arn:aws:ec2:{region}:{tgw_owner_account_id}:transit-gateway/{transit_gateway_id} \
    --principals {firewall_account_id} --region {region}
  ```

- You MUST, in the firewall owner account, accept the AWS RAM invitation if the share is not
  auto-accepted

#### 3. Create the transit gateway-attached firewall from the firewall owner account

**Constraints:**

- You MUST, in the firewall owner account, create the firewall attached to the transit gateway,
  pointing at the shared transit gateway for the cross-account case (a transit gateway-attached
  firewall takes `--transit-gateway-id` instead of VPC and subnet mappings):

  ```
  aws network-firewall create-firewall --firewall-name {firewall_name} \
    --firewall-policy-arn {firewall_policy_arn} \
    --transit-gateway-id {transit_gateway_id} \
    --availability-zone-mappings AvailabilityZone={az} \
    --encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id} \
    --region {region}
  ```

- You MUST capture the resulting transit gateway attachment ID from the
  `Firewall.TransitGatewayAttachmentSyncStates` in the response

#### 4. (Cross-account only) Accept the attachment from the transit gateway owner account

**Constraints:**

- You MUST, in the transit gateway owner account, accept the transit gateway attachment unless
  auto-accept is enabled; the firewall stays pending until this is done:

  ```
  aws ec2 accept-transit-gateway-vpc-attachment \
    --transit-gateway-attachment-id {transit_gateway_attachment_id} --region {region}
  ```

#### 5. Configure for spoke coverage and scaling

**Constraints:**

- You MUST NOT run `modify-transit-gateway-vpc-attachment` to enable appliance mode; AWS already
  enables it on the transit gateway-attached firewall's underlying attachment and the call does not
  apply
- You MUST override `HOME_NET` in the firewall policy to include every spoke VPC CIDR range
- You SHOULD set the stream exception policy from the customer's availability tolerance (`DROP`,
  `CONTINUE`, or `REJECT`) and warn that `DROP` resets mid-stream connections on scaling events with
  no alert log

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST confirm the firewall reaches a ready state and the attachment is accepted
- You MUST enable alert logging on the firewall immediately after confirming it is active, to
  provide visibility into inspection decisions across spoke VPCs from the start
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "central-inspection-fw",
  "transit_gateway_id": "tgw-0123456789abcdef0",
  "firewall_policy_arn": "arn:aws:network-firewall:us-east-1:444455556666:firewall-policy/central-policy",
  "cross_account": true,
  "kms_key_id": "arn:aws:kms:us-east-1:444455556666:key/mrk-example",
  "firewall_account_id": "444455556666"
}
```

#### Example output

```
TGW owner shared tgw-0123456789abcdef0 via RAM to 444455556666.
Firewall owner accepted the share and created central-inspection-fw from the shared TGW.
TGW owner accepted the attachment; firewall is now active.
Open the console and confirm the firewall:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=central-inspection-fw
```

### Troubleshooting

#### Attachment pending
A handoff was missed. Confirm share acceptance, firewall creation, and attachment acceptance (Steps 2 to 4).

#### Firewall owner cannot accept
Acceptance happens in the transit gateway owner account (Step 4).

## Security Considerations

A centralized firewall is the single inspection point for many VPCs, so a gap here exposes every
spoke behind it.

- You MUST enable alert logging immediately after the firewall is active so inspection decisions
  across all spoke VPCs are visible from the start.
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
- You MUST override `HOME_NET` to cover every spoke CIDR; an incomplete `HOME_NET` leaves spoke
  traffic uninspected by stateful and directional rules with no error.
- You SHOULD set the stream exception policy to `DROP` (fail-closed) unless availability constraints
  require otherwise; `CONTINUE` passes uninspected traffic when capacity shifts mid-stream.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access, and scope the AWS RAM share and the cross-account permissions
  to the specific firewall owner account rather than sharing the transit gateway broadly.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on critical events such as transit gateway
  attachment acceptance failures, transit gateway sync state issues, and firewall endpoint failures,
  so problems are detected and escalated promptly. You MUST encrypt any SNS topic used for these
  alarm notifications with a customer-managed AWS KMS key and restrict alarm notification recipients to
  authorized operations and security personnel, since alarm messages can expose sensitive firewall
  metadata (endpoint status, traffic patterns, and capacity).

## Additional Resources

- [Transit gateway-attached firewalls in Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tgw-firewall.html)
- [Create a transit gateway-attached firewall from a shared transit gateway (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/create-tgw-firewall.html)
- [AWS Transit Gateway network function attachments (Amazon VPC Transit Gateways Guide)](https://docs.aws.amazon.com/vpc/latest/tgw/tgw-nf-fw.html)
- [Deploy centralized traffic filtering using AWS Network Firewall (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/deploy-centralized-traffic-filtering-using-aws-network-firewall/)
- [Transit gateway attachment configuration for AWS Network Firewall (appliance mode) (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/vpc-config-tgw-multi-az.html)
- [How AWS Network Firewall works (stream exception policy) (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/how-it-works.html)
