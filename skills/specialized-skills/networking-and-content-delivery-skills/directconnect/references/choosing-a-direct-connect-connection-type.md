# Choosing a Direct Connect Connection Type and Completing the Cross Connect

## Overview

Domain expertise for the first Direct Connect decision: which connection model to order, and how
the physical cross connect gets completed. Covers dedicated connections, hosted connections, and
link aggregation groups as a third model, the location-support check for higher speeds, the
difference between a hosted connection and a hosted virtual interface, the Letter of Authorization
and Connecting Facility Assignment (LOA-CFA) handoff to the network provider, and the fact that the
connection carries no traffic until a virtual interface is created on it.

Does not cover creating the virtual interface itself or BGP setup (a separate reference), reaching
many VPCs through a Direct Connect gateway, encryption, or ongoing link aggregation group member
management. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- Decision: dedicated, hosted, or link aggregation group
- Hosted connection vs hosted virtual interface
- Location support and immutable port speed
- Connection states
- Troubleshooting
- Procedure
- Additional Resources

## Decision: dedicated, hosted, or link aggregation group

| Model | Use when |
| --- | --- |
| Dedicated connection | The customer wants a physical port for their sole use at 1, 10, 100, or 400 Gbps, needs multiple virtual interfaces, or needs MACsec. Requested directly in the console |
| Hosted connection | The customer needs sub-1 Gbps, or a speed from 50 Mbps up to 25 Gbps (range varies by partner), or wants partner-managed provisioning. Ordered through an AWS Direct Connect Partner, then accepted in the console |
| Link aggregation group (LAG) | The customer wants more aggregate bandwidth or link-level redundancy by bundling several same-speed dedicated connections at one location into one logical link. A single 100 Gbps port versus four bundled 10 Gbps connections is a real cost and resiliency tradeoff, not just a speed pick |

**Constraints:**

- You MUST settle the connection model and the required bandwidth before any request is submitted,
  because port speed is fixed once the connection is created.
- You SHOULD present the link aggregation group as a real third option when the customer cares about
  aggregate bandwidth or link redundancy, not only dedicated vs hosted.
- You MUST route hosted connections to the partner ordering path and reserve the console request flow
  for dedicated connections.

## Hosted connection vs hosted virtual interface

Customers confuse these constantly, and the model the customer actually has changes what they can do
next.

| Term | What it is |
| --- | --- |
| Hosted connection | The partner provisions a whole connection for the customer's sole use. The customer can create one virtual interface on it |
| Hosted virtual interface | The partner provisions a single virtual interface on a connection the partner already owns and shares. The virtual interface is the unit the partner hands over |

**Constraints:**

- You MUST establish which of the two the customer has before planning next steps, because a hosted
  connection lets the customer create a virtual interface while a hosted virtual interface is itself
  the provisioned unit.

## Location support and immutable port speed

**Constraints:**

- You MUST check that the chosen speed is offered at the customer's Direct Connect location before
  the request, since 400 Gbps and the higher speeds are available only at select locations and an
  unsupported pick is a dead end.
- You MUST NOT attempt to change port speed after the connection is created; the only path is to
  delete and recreate, so confirm bandwidth while the choice is still free.

## Connection states

`requested` and `ordering` are not the same, and reading them wrong wastes days.

| State | Meaning |
| --- | --- |
| `requested` (dedicated) | AWS has opened a support case asking the customer for more information. The customer must answer it, not wait |
| `ordering` (hosted only) | A hosted-connection state. It does not apply to dedicated connections |

**Constraints:**

- You MUST read the connection state correctly and, on `requested`, prompt the customer to answer the
  AWS support case rather than wait in a queue.

## Troubleshooting

### Connection sits in `requested` and nothing happens
For a dedicated connection, `requested` means AWS opened a support case for more information. Answer
the case.

### Cannot find the option to order a hosted connection in the console
Hosted connections are created by an AWS Direct Connect Partner and only accepted in the console. Go
through the partner.

### Connection is live but no traffic flows
A connection carries no traffic until a virtual interface is created on it. Create the virtual
interface (separate reference).

### Chosen speed is not available at the location
400 Gbps and higher speeds are offered only at select locations. Check location support and pick a
supported speed or location.

## Procedure

### Overview

This procedure confirms the connection model and speed, requests a dedicated connection, creates a
link aggregation group, or routes a hosted connection to the partner path, hands the LOA-CFA to the
network provider, and surfaces the console link to track state.

### Parameters

- **connection_model** (required): `dedicated`, `hosted`, or `lag`.
- **bandwidth** (required): The port speed (e.g., `1Gbps`, `10Gbps`, `100Gbps`, `400Gbps` for
  dedicated; partner-defined for hosted).
- **location** (required for dedicated and LAG): The Direct Connect location code.
- **connection_name** (required): A name for the connection.
- **number_of_connections** (required for LAG): How many member connections to bundle.

**Constraints for parameter acquisition:**

- You MUST ask for the model, bandwidth, and location upfront in a single prompt.
- You MUST confirm location support for the chosen speed before submitting.

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST list available locations and confirm the chosen speed is supported there:

  ```
  aws directconnect describe-locations --region {region}
  ```

#### 2. Request the connection (dedicated), create the LAG, or route to the partner (hosted)

**Constraints:**

- For a dedicated connection, you MUST create the request with the confirmed location and bandwidth.
  If the customer wants MACsec, request it at creation time rather than adding it later:

  ```
  aws directconnect create-connection --location {location} \
    --bandwidth {bandwidth} --connection-name {connection_name} --region {region}
  ```

- For a link aggregation group (`lag` model), you MUST create the LAG directly with `create-lag`
  rather than `create-connection`, supplying the member count and the per-connection bandwidth (all
  members are the same speed, at one location):

  ```
  aws directconnect create-lag --location {location} \
    --number-of-connections {number_of_connections} \
    --connections-bandwidth {bandwidth} \
    --lag-name {connection_name} --region {region}
  ```

- For a hosted connection, you MUST direct the customer to order through an AWS Direct Connect
  Partner, then accept it in the console once it appears:

  ```
  aws directconnect confirm-connection --connection-id {connection_id} --region {region}
  ```

#### 3. Download and hand off the LOA-CFA

**Constraints:**

- For a dedicated connection, you MUST retrieve the LOA-CFA and tell the customer to give it to their
  network provider to order the physical cross connect:

  ```
  aws directconnect describe-loa --connection-id {connection_id} \
    --query loaContent --output text --region {region}
  ```

  The response is base64-encoded. Decode it locally to a PDF, e.g.:

  ```
  aws directconnect describe-loa --connection-id {connection_id} \
    --query loaContent --output text --region {region} | base64 --decode > loa.pdf
  ```

- You SHOULD warn the customer to treat the LOA-CFA as sensitive — it carries facility assignment
  details (cage, rack, panel, and port identifiers) — restrict access to the decoded PDF, do not
  transmit it over unencrypted email, and delete local copies after handoff to the network provider.
- You MUST explain that a customer without equipment at the Direct Connect location has to engage a
  partner before the cross connect can be ordered.

#### 4. Confirm state and surface the console link

**Constraints:**

- You MUST check the connection state and read it correctly (`requested` on a dedicated connection
  means answer the AWS support case):

  ```
  aws directconnect describe-connections --connection-id {connection_id} --region {region}
  ```

- You MUST present the Direct Connect console link, filling `{connectionId}` and `{region}` from the
  request, and tell the customer the connection carries no traffic until a virtual interface is
  created on it:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/connections/{connectionId}
  ```

- You SHOULD recommend CloudWatch alarms on connection state, and confirm CloudTrail is capturing
  `directconnect` API calls with log file validation enabled and the trail encrypted with a KMS key,
  and any CloudWatch Logs log groups receiving these events or alarm state data encrypted with a KMS
  key, so state changes trigger alerts and configuration changes are audited with assured log integrity
  and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel, so sensitive
  connection-state information does not reach unintended recipients.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the link. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Dedicated Direct Connect connections (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/dedicated_connection.html)
- [Direct Connect connection options (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/connection_options.html)
- [AWS Direct Connect link aggregation groups (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/lags.html)
- [Direct Connect virtual interfaces and hosted virtual interfaces (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/WorkingWithVirtualInterfaces.html)
- [Getting started with AWS Direct Connect](https://aws.amazon.com/directconnect/getting-started/)
