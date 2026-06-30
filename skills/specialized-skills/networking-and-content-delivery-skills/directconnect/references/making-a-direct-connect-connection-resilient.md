# Making a Direct Connect Connection Resilient

## Overview

Domain expertise for making a Direct Connect connection survive a failure and meet an uptime target,
and for tuning how fast failover actually happens. Covers the AWS Direct Connect Resiliency Toolkit
and its resiliency models, the single-device trap, the failover test, the VPN backup option, and the
difference between the resiliency model (topology and service level target) and failover speed (BGP
convergence, hold-timer tuning, and Bidirectional Forwarding Detection).

Does not cover choosing the connection model, virtual interface and BGP setup, reaching many VPCs,
or encryption. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- Decision: resiliency model
- The single-device trap
- Resiliency model vs failover speed
- Failover test and VPN backup
- Troubleshooting
- Procedure
- Additional Resources

## Decision: resiliency model

| Model | Service level target | Layout |
| --- | --- | --- |
| Maximum Resiliency | 99.99% | Separate connections on separate devices in more than one location |
| High Resiliency | 99.9% | One connection at each of two locations |
| Development and Test | No service level agreement | Separate connections on separate devices in a single location, for non-critical workloads |
| Single connection | 95% | One connection, no redundancy |

**Constraints:**

- You MUST match the customer's uptime target to the resiliency model that delivers it before any
  connections are ordered, because the higher targets require a specific multi-location layout that
  cannot be retrofitted cheaply.
- You MUST use the Resiliency Toolkit wizard for Maximum and High Resiliency, since it prevents
  terminating redundant connections on the same device.

## The single-device trap

**Constraints:**

- You MUST NOT let the customer order two connections and assume they are redundant; terminating both
  on the same Direct Connect device leaves a single point of failure. The toolkit prevents this.

## Resiliency model vs failover speed

These are two different questions. The toolkit sets the topology; it does not set how fast failover
converges.

**Constraints:**

- You MUST set the convergence-time expectation: with default BGP timers, failover can take around 90
  seconds, while enabling Bidirectional Forwarding Detection (BFD) and tuning the BGP hold timer
  brings it under a second.
- You SHOULD offer BFD and hold-timer tuning when the customer needs fast failover, rather than
  implying the resiliency model alone determines failover speed. When the customer asks "is my
  failover 3 seconds or 90 seconds," this is the answer.

## Failover test and VPN backup

**Constraints:**

- You MUST close with the toolkit's failover test, which brings down the BGP session to confirm
  traffic routes to the redundant virtual interface, so the first real test is not an incident.
- You SHOULD offer a Site-to-Site VPN as a backup path for customers who need resilience beyond what
  the connections alone provide; note the MTU drops to 1500 during VPN failover.

## Troubleshooting

### Production is on a single connection and an outage took it all down
A single connection carries a 95% service level agreement with no redundancy. Move to High or Maximum
Resiliency using the toolkit.

### Two connections did not protect against a device failure
Both terminated on the same Direct Connect device. Use the Resiliency Toolkit, which prevents this.

### Failover is much slower than expected
Default BGP timers leave convergence around 90 seconds. Enable BFD and tune the hold timer for
sub-second failover.

### Failover was never tested before an incident
Run the toolkit failover test, which brings down the BGP session to verify rerouting, before the next
maintenance event.

## Procedure

### Overview

This procedure matches the uptime target to a resiliency model, builds it through the toolkit, tunes
failover speed when needed, runs the failover test, and surfaces the console link.

### Parameters

- **uptime_target** (required): The service level the customer needs (maps to a resiliency model).
- **location_count** (required): How many Direct Connect locations are available.
- **fast_failover** (optional): Whether sub-second failover (BFD) is needed.
- **vpn_backup** (optional): Whether a Site-to-Site VPN backup path is wanted.

**Constraints for parameter acquisition:**

- You MUST establish the uptime target and available locations before choosing a model.

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm how many Direct Connect locations the customer can use, since Maximum Resiliency
  needs more than one.

#### 2. Build the resiliency model through the toolkit

**Constraints:**

- You MUST use the Resiliency Toolkit connection wizard for Maximum and High Resiliency so redundant
  connections do not land on the same device.
- You MUST NOT mix bandwidths within one Resiliency Toolkit configuration.

#### 3. Tune failover speed when needed

**Constraints:**

- When the customer needs fast failover, you MUST enable BFD and tune the BGP hold timer, and set the
  expectation that default timers leave convergence around 90 seconds.

#### 4. Run the failover test

**Constraints:**

- You MUST discover the virtual interfaces and BGP peer addresses on the connection before starting
  the test:

  ```
  aws directconnect describe-virtual-interfaces --connection-id {connection_id} \
    --query 'virtualInterfaces[].{Id:virtualInterfaceId,PeerAddress:bgpPeers[0].customerAddress}' \
    --output table --region {region}
  ```

  Capture the `virtualInterfaceId` and `customerAddress` from the response.
- You MUST run the BGP failover test and confirm traffic moves to the redundant path:

  ```
  aws directconnect start-bgp-failover-test --virtual-interface-id {virtual_interface_id} \
    --bgp-peers {peer_address} --test-duration-in-minutes 180 --region {region}
  ```

- You MUST poll for test completion:

  ```
  aws directconnect list-virtual-interface-test-history \
    --virtual-interface-id {virtual_interface_id} \
    --query "virtualInterfaceTestHistory[0].status" --output text --region {region}
  ```

- For early termination (if the customer needs to abort):

  ```
  aws directconnect stop-bgp-failover-test \
    --virtual-interface-id {virtual_interface_id} --region {region}
  ```

- You SHOULD recommend CloudWatch alarms on Direct Connect connection state and virtual interface BGP
  status metrics, and confirm CloudTrail is capturing `directconnect` API calls with log file
  validation enabled and the trail encrypted with a KMS key, and any CloudWatch Logs log groups
  receiving these events or alarm state data encrypted with a KMS key, so state changes trigger alerts
  and configuration changes are audited with assured log integrity and confidentiality rather than
  relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.
- You SHOULD remind the customer that the redundant Direct Connect connections are not encrypted in
  transit by default, and point them to the encrypting-traffic reference if the workload requires
  encryption.

#### 5. Surface the console link

**Constraints:**

- You MUST present the Direct Connect connections console link, filling `{region}`, and tell the
  customer to confirm the redundant connections and their states:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/connections
  ```

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the redundant connections. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [Direct Connect connection options (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/connection_options.html)
- [AWS Direct Connect Resiliency Toolkit (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/resiliency_toolkit.html)
- [Resilience in AWS Direct Connect (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/disaster-recovery-resiliency.html)
- [Enabling BFD for a Direct Connect connection (AWS re:Post)](https://repost.aws/knowledge-center/enable-bfd-direct-connect)
- [AWS Direct Connect Service Level Agreement](https://aws.amazon.com/directconnect/sla/)
