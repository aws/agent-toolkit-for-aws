# Monitoring Tunnel State and Troubleshooting a Down Tunnel

## Overview

Domain expertise for detecting and diagnosing AWS Site-to-Site VPN tunnel failures with Amazon
CloudWatch. Covers the `TunnelState` metric and how it reads differently for static versus BGP
connections, building alarms that notify an Amazon Simple Notification Service (SNS) topic, enabling
and reading Site-to-Site VPN logs to find the cause, why the data metrics are not a liveness signal,
and the CloudWatch cost consideration. This reference covers tunnel state and VPN logs; AWS CloudTrail
captures the API-level events such as connection creation and modification.

Does not cover building the connection or its high availability (other references). Assumes a
connection exists (the creating-a-site-to-site-vpn-connection reference).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region {region}` matching the connection.

## Table of Contents

- Overview
- Workflow
- TunnelState reads differently by routing type
- Wiring a working alarm
- VPN logs name the cause
- Data metrics are not liveness
- CloudWatch cost
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To detect and diagnose tunnel failures, set the right alarm against the connection's routing type,
wire it to an SNS topic, and enable VPN logs to find the cause when a tunnel drops. See the
Procedure section below.

The procedure covers:

- Determining the routing type so the `TunnelState` threshold is correct
- Creating the alarm with the right metric, statistic, threshold, and SNS topic
- Enabling Site-to-Site VPN logs to CloudWatch Logs
- Reading the logs for the IKE or BGP detail that names the cause

## TunnelState reads differently by routing type

The `TunnelState` metric does not read the same way for both routing types. For static VPNs, 0 is
DOWN and 1 is UP. For BGP VPNs, 1 means ESTABLISHED and values between 0 and 1 mean at least one
tunnel is not up. An alarm threshold set without knowing this misfires or stays silent during a real
outage.

**Constraints:**

- You MUST set the alarm threshold against the customer's actual routing type
- You SHOULD confirm whether the connection is static or BGP before configuring the alarm

## Wiring a working alarm

A working alarm needs the right metric, statistic, threshold, and an SNS topic wired together, and
the statistic depends on the alarm scope: alarming when any tunnel drops versus only when all
tunnels are down versus watching one specific tunnel.

**Constraints:**

- You MUST sequence the alarm setup: metric, statistic, threshold, then SNS topic
- You MUST pick the statistic that matches the scope: `Minimum` for any-tunnel-down, `Maximum` for all-tunnels-down, or the `TunnelIpAddress` dimension for a single tunnel
- You SHOULD confirm the SNS topic has a confirmed subscription so the notification actually reaches someone
- You MUST encrypt the CloudWatch Logs group that receives Site-to-Site VPN logs with an AWS KMS key and enable server-side encryption on the SNS topic, and MUST verify that all SNS topic subscribers are authorized operations personnel

## VPN logs name the cause

When a tunnel is down the metric says it is down but not why, and customers spend time guessing at
IKE, dead peer detection, or BGP causes. Site-to-Site VPN logs published to CloudWatch Logs carry
the tunnel establishment and BGP detail that names the cause, but they must be enabled first.

**Constraints:**

- You MUST enable the VPN logs and point the customer at the fields that explain the failure, rather than leaving them to guess
- You SHOULD enable logs before an incident where possible, since they only capture events after they are turned on

## Data metrics are not liveness

The `TunnelDataIn` and `TunnelDataOut` metrics can report traffic even when a tunnel is down,
because of periodic status checks and background BGP and ARP requests. Customers who watch data
volume as a health signal conclude the tunnel is fine when it is not.

**Constraints:**

- You MUST rely on `TunnelState` for health and treat the data metrics as usage, not liveness
- You SHOULD correct the customer if they propose alarming on data volume as a health signal

## CloudWatch cost

Site-to-Site VPN does not charge for metrics or logs, but the CloudWatch metrics, alarms, and logs
themselves bill at standard CloudWatch rates. Turning on detailed monitoring and log delivery across
every connection adds up.

**Constraints:**

- You MUST note the CloudWatch cost so the customer makes the tradeoff knowingly
- You SHOULD suggest enabling full metrics, alarms, and logs for production VPNs while trimming them for test and development workloads

## Troubleshooting

### Alarm never fires during an outage, or fires constantly
The threshold does not match the routing type. Set it against static (0/1) or BGP (1 = established) (TunnelState reads differently by routing type).

### Alarm fires but no one is notified
The SNS topic has no confirmed subscription. Confirm the subscription (Wiring a working alarm).

### Tunnel is down and the cause is unknown
VPN logs are not enabled. Enable them and read the IKE and BGP detail (VPN logs name the cause).

### Tunnel looks healthy by data volume but is actually down
Data metrics report background traffic. Use `TunnelState` for health (Data metrics are not liveness).

## Procedure

### Overview

This procedure determines the routing type, creates a correctly-thresholded alarm wired to an SNS
topic, and enables VPN logs, then surfaces the connection console link to verify tunnel status.

### Parameters

- **region** (required): The AWS Region of the connection.
- **vpn_connection_id** (required): The connection to monitor.
- **routing_type** (required): `static` or `dynamic` (BGP), to set the threshold correctly.
- **scope** (required): one of `any-tunnel-down`, `all-tunnels-down`, or `single-tunnel`, to pick
  the statistic and dimension (see Step 2). `any-tunnel-down` pages when either tunnel of the
  connection drops (redundancy health); `all-tunnels-down` pages only when the whole connection is
  lost; `single-tunnel` watches one specific tunnel by its outside IP.
- **sns_topic_arn** (required): The SNS topic to notify.
- **kms_key_arn** (required): The AWS KMS key ARN used to encrypt the CloudWatch Logs group that receives VPN logs.
- **tunnel_outside_ips** (required): The outside IP addresses of the VPN tunnels (one per tunnel, obtained from `describe-vpn-connections`).
- **environment** (optional): `staging` or `test`, to weigh the CloudWatch cost.

**Constraints for parameter acquisition:**

- You MUST establish the routing type and alarm scope upfront
- You MUST verify that all SNS topic subscribers are authorized operations personnel
- You SHOULD confirm the SNS topic exists and has a confirmed subscription

### Steps

#### 1. Determine routing type and threshold

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST set the `TunnelState` threshold against the routing type: static is 0 DOWN / 1 UP; BGP is 1 ESTABLISHED, 0 to 1 means a tunnel is not up

#### 2. Create the alarm

**Constraints:**

- You MUST create the alarm with the right metric, statistic for the scope, threshold, and SNS topic:

  ```
  aws cloudwatch put-metric-alarm --alarm-name s2s-vpn-tunnel-down-{vpn_connection_id}-{scope} \
    --namespace AWS/VPN --metric-name TunnelState --dimensions Name=VpnId,Value={vpn_connection_id} \
    --statistic Maximum --threshold 1 --comparison-operator LessThanThreshold \
    --period 300 --evaluation-periods 1 --treat-missing-data breaching \
    --alarm-actions {sns_topic_arn} --region {region}
  ```

- You MUST verify that all SNS topic subscribers are authorized operations personnel before wiring the topic to the alarm
- You MUST verify the SNS topic has server-side encryption enabled before wiring it to the alarm, checking that `KmsMasterKeyId` is set on the topic:

  ```
  aws sns get-topic-attributes --topic-arn {sns_topic_arn} --region {region}
  ```

- You MUST set `--treat-missing-data breaching` so the alarm fires rather than going to INSUFFICIENT_DATA when a down tunnel stops reporting metrics
- You MUST include both `{vpn_connection_id}` and `{scope}` in the alarm name so each
  connection-and-scope alarm is unique; `put-metric-alarm` is an upsert, so a name without the scope
  would let a second alarm on the same connection (for example an `any-tunnel-down` alarm added
  alongside an `all-tunnels-down` alarm) silently overwrite the first, and a name without the
  connection id would collide across connections (for example the second leg of an HA pair)
- You MUST pick the statistic and dimension that match the requested `scope`. With the `Name=VpnId`
  dimension, `TunnelState` aggregates across both tunnels of the connection, so the statistic
  selects which aggregate you alarm on:

  | `scope` | Intent | Statistic | Dimension |
  | --- | --- | --- | --- |
  | `any-tunnel-down` | Page when either tunnel drops (redundancy health) | `Minimum` (falls below 1 as soon as one tunnel is down) | `Name=VpnId` |
  | `all-tunnels-down` | Page only when the whole connection is lost | `Maximum` (falls below 1 only when no tunnel is up) | `Name=VpnId` |
  | `single-tunnel` | Watch one specific tunnel | statistic does not matter (already one tunnel) | `Name=VpnId` plus `Name=TunnelIpAddress,Value={tunnel_outside_ip}` |

  The example below uses `Maximum` (the `all-tunnels-down` scope), which alarms only on full
  connection loss; switch to `Minimum` for `any-tunnel-down` to be paged the moment either tunnel
  drops, or add the `TunnelIpAddress` dimension for `single-tunnel`

#### 3. Enable VPN logs

**Constraints:**

- You MUST create the CloudWatch Logs group with AWS KMS encryption, then enable log delivery to it on each tunnel so a future down tunnel can be diagnosed. `create-log-group` does not return an ARN, so construct the log group ARN as `arn:aws:logs:{region}:{account_id}:log-group:/aws/vpn/{vpn_connection_id}:*` (or retrieve it with `describe-log-groups`), and run `modify-vpn-tunnel-options` once per tunnel outside IP, since each connection has two tunnels:

  ```
  aws logs create-log-group --log-group-name /aws/vpn/{vpn_connection_id} \
    --kms-key-id {kms_key_arn} --region {region}
  # Repeat for each address in {tunnel_outside_ips}
  aws ec2 modify-vpn-tunnel-options --vpn-connection-id {vpn_connection_id} \
    --vpn-tunnel-outside-ip-address {tunnel_outside_ip} \
    --tunnel-options "LogOptions={CloudwatchLogOptions={LogEnabled=true,LogGroupArn={log_group_arn},LogOutputFormat=json}}" \
    --region {region}
  ```

- You MUST warn the customer that `modify-vpn-tunnel-options` briefly renegotiates and interrupts the affected tunnel while the change is applied; on a production connection, enable logs one tunnel at a time and confirm the first tunnel is back up before modifying the second, so the connection is never fully down
- You SHOULD point the customer at the IKE and BGP fields that name the cause

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST present the VPN connection console link, filling `{region}` and `{vpnConnectionId}` from the request, and tell the customer to open it and confirm tunnel status:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#VpnConnectionDetails:VpnConnectionId={vpnConnectionId}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "vpn_connection_id": "vpn-0abc1234def567890",
  "routing_type": "dynamic",
  "scope": "all-tunnels-down",
  "sns_topic_arn": "arn:aws:sns:us-east-1:111122223333:vpn-alerts",
  "kms_key_arn": "arn:aws:kms:us-east-1:111122223333:key/abcd1234-ef56-7890-abcd-1234567890ab",
  "tunnel_outside_ips": ["198.51.100.10", "198.51.100.11"],
  "environment": "staging"
}
```

#### Example output

```
BGP connection: TunnelState threshold set to alarm below 1 (established). all-tunnels-down alarm
(Maximum statistic, VpnId dimension) wired to the vpn-alerts SNS topic. VPN logs enabled to a KMS-encrypted CloudWatch Logs group on both
tunnels (198.51.100.10, 198.51.100.11) for cause diagnosis. Noted CloudWatch cost is justified for
the staging workload. Open the connection to confirm tunnel status:
https://console.aws.amazon.com/vpc/home?region=us-east-1#VpnConnectionDetails:VpnConnectionId=vpn-0abc1234def567890
```

### Troubleshooting

#### Alarm misfires or stays silent
Threshold does not match routing type. Set it against static or BGP (Step 1).

#### No notification on alarm
SNS topic has no confirmed subscription. Confirm it (Step 2).

#### Cause of a down tunnel is unknown
Enable VPN logs and read the IKE and BGP fields (Step 3).

#### Healthy by data volume but down
Use `TunnelState`, not data metrics, for health (Data metrics are not liveness).

## Security Considerations

VPN logs and tunnel state changes expose infrastructure detail (peer IPs, BGP and IKE events), so the
monitoring path is itself sensitive and must be access-controlled.

**Constraints:**

- You MUST encrypt the CloudWatch Logs group that receives Site-to-Site VPN logs with an AWS KMS key and enable server-side encryption on the SNS topic, and MUST verify that all SNS topic subscribers are authorized operations personnel
- You SHOULD apply a least-privilege retention and access policy to the log group so only authorized
  personnel can read tunnel and BGP detail

## Additional Resources

- [Monitor AWS Site-to-Site VPN tunnels using Amazon CloudWatch (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/monitoring-cloudwatch-vpn.html)
- [Create Amazon CloudWatch alarms to monitor AWS Site-to-Site VPN tunnels (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/creating-alarms-vpn.html)
- [AWS Site-to-Site VPN logs (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/monitoring-logs.html)
- [AWS VPN Pricing](https://aws.amazon.com/vpn/pricing/)
- [Setting up of AWS Site-to-Site VPN automated monitoring solution (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/setting-up-of-aws-site-to-site-vpn-automated-monitoring-solution/)
