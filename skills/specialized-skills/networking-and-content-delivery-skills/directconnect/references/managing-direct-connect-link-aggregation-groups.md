# Managing Direct Connect Link Aggregation Groups

## Overview

Domain expertise for bundling Direct Connect connections into a link aggregation group (LAG) and
managing its members over time. Covers the same-speed and same-device requirement, the member-count
limits by speed, the minimum links threshold and the trap of removing a member below it, the
maintenance-window requirement for disruptive changes, and the MACsec key behavior on LAG join.

Does not cover choosing the connection model at first order (a separate reference introduces the LAG
as a model choice), virtual interface and BGP setup, or resiliency model selection. Those are
separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. The Direct Connect console is regional; pass the
customer's working `--region` on every `aws directconnect` command.

## Table of Contents

- Overview
- Member requirements and limits
- Minimum links and the removal trap
- Disruptive changes need a maintenance window
- MACsec on LAG join
- Troubleshooting
- Procedure
- Additional Resources

## Member requirements and limits

| Speed | Max member connections |
| --- | --- |
| 1 or 10 Gbps | 4 |
| 100 or 400 Gbps | 2 |

**Constraints:**

- You MUST confirm every member connection runs at the same bandwidth and terminates at the same
  Direct Connect device before proposing or modifying the LAG; mismatches are rejected.

## Minimum links and the removal trap

The minimum links value decides how many members must stay active before the whole LAG is declared
down.

| Minimum links | Behavior when active members drop below it |
| --- | --- |
| 0 (default) | LAG stays up even with 0 active members. No LAG-down signal on total failure |
| 1 | LAG goes down when all members fail |
| 2 | LAG goes down when fewer than 2 members are active |

**Constraints:**

- You MUST set minimum links to at least 1 for a production LAG, and explain the threshold behavior,
  so a total outage produces a LAG-down signal.
- You MUST check the current active member count against minimum links before removing a member, and
  warn the customer when the removal would drop the count below the threshold and take the whole LAG
  down.

## Disruptive changes need a maintenance window

**Constraints:**

- You MUST treat creating a LAG from an existing live connection, and adding or removing a member, as
  traffic-disrupting, and steer those changes into a maintenance window.

## MACsec on LAG join

**Constraints:**

- You MUST associate the MACsec key with the LAG after members are added, not rely on a per-connection
  key carrying over. A connection's individual MACsec key is disassociated when it joins a LAG; the
  LAG carries its own key that applies to all members, and only one key is active across the LAG at a
  time. When the LAG uses MACsec, you MUST store the CKN/CAK pair in AWS Secrets Manager and reference
  it by `--secret-arn`, never passing the values inline or storing them in plaintext config. You SHOULD
  scope a resource policy on that secret to only the principals that need to manage the MACsec key, and
  include `aws:SourceArn` or `aws:SourceAccount` condition keys to restrict access to only the Direct
  Connect LAG that needs the key and prevent confused-deputy scenarios.
- You SHOULD remind the customer that traffic over the LAG is not encrypted in transit by default,
  and point them to the encrypting-traffic reference if the workload requires encryption.

## Troubleshooting

### A total member failure produced no LAG-down alarm
Minimum links is at the default of 0, so the LAG reports up with no active members. Set it to at
least 1.

### Removing one member took the whole LAG down
The removal dropped the active count below minimum links. Check the count against the threshold before
removing a member.

### A connection will not join the LAG
It is a different bandwidth or on a different Direct Connect device. All members must match on both.

### MACsec stopped working after a connection joined the LAG
The per-connection key was disassociated on join. Associate the MACsec key with the LAG.

## Procedure

### Overview

This procedure confirms member compatibility, creates or modifies the LAG, sets minimum links safely,
schedules disruptive changes into a maintenance window, and surfaces the console link.

### Parameters

- **action** (required): `create`, `add-member`, or `remove-member`.
- **lag_id** (required for member changes): The LAG ID.
- **connection_id** (required for member changes): The member connection ID.
- **bandwidth** (required for create): The shared member bandwidth.
- **location** (required for create): The Direct Connect location.
- **minimum_links** (required): At least 1 for production.

**Constraints for parameter acquisition:**

- You MUST ask for the action, the member bandwidth/location (for create), and the minimum links value
  upfront.

### Steps

#### 1. Verify dependencies and member compatibility

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`.
- You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance profile, or `aws sts assume-role`)
  rather than long-lived IAM user access keys for Direct Connect management operations.
- You MUST confirm all members share one bandwidth and terminate at the same Direct Connect device.

#### 2. Create the LAG or change a member (in a maintenance window)

**Constraints:**

- You MUST create the LAG with the shared bandwidth, and warn that creating from an existing
  connection interrupts traffic:

  ```
  aws directconnect create-lag --location {location} --number-of-connections {number_of_connections} \
    --connections-bandwidth {bandwidth} --lag-name {lag_name} --region {region}
  ```

  To create from an existing connection (traffic-disrupting), add `--connection-id {connection_id}`.

- You MUST capture the `lagId` from the create-lag response as `{lag_id}`.

- You MUST poll until the LAG is available:

  ```
  aws directconnect describe-lags --lag-id {lag_id} \
    --query 'lags[0].lagState' --output text --region {region}
  ```

  Poll until `lagState` reports `available`.

- Before a member removal, you MUST check the active count against minimum links and warn if the
  removal would take the LAG down:

  ```
  aws directconnect describe-lags --lag-id {lag_id} --region {region}
  ```

- To add a member:

  ```
  aws directconnect associate-connection-with-lag \
    --connection-id {connection_id} --lag-id {lag_id} --region {region}
  ```

- To remove a member:

  ```
  aws directconnect disassociate-connection-from-lag \
    --connection-id {connection_id} --lag-id {lag_id} --region {region}
  ```

#### 3. Set minimum links

**Constraints:**

- You MUST set minimum links to at least 1 for a production LAG:

  ```
  aws directconnect update-lag --lag-id {lag_id} --minimum-links {minimum_links} --region {region}
  ```

#### 4. Surface the console link

**Constraints:**

- You MUST present the LAG console link, filling `{lag_id}` and `{region}`:

  ```
  https://console.aws.amazon.com/directconnect/v2/home?region={region}#/lags/{lag_id}
  ```

- You SHOULD recommend CloudWatch alarms on LAG state and member-count metrics, and confirm CloudTrail
  is capturing `directconnect` API calls with log file validation enabled and the trail encrypted with
  a KMS key, and any CloudWatch Logs log groups receiving these events or alarm state data encrypted
  with a KMS key, so state changes trigger alerts and configuration changes are audited with assured
  log integrity and confidentiality rather than relying on manual detection.
- You SHOULD ensure any SNS topics receiving Direct Connect alarm notifications are encrypted with a
  KMS key and that subscriptions are restricted to authorized operations personnel.

## Security Considerations

- **Not encrypted by default.** Direct Connect does not encrypt traffic in transit. You MUST treat
  encryption as a separate, deliberate step (MACsec or a private IP Site-to-Site VPN) before regulated
  or sensitive data crosses the LAG. See the encrypting-traffic reference.
- **Ephemeral credentials.** You MUST use ephemeral IAM credentials (e.g., AWS SSO, an instance
  profile, or `aws sts assume-role`) for Direct Connect management operations rather than long-lived
  IAM user access keys.
- **Least-privilege IAM.** You MUST scope IAM permissions for `directconnect` API actions to the
  specific actions and resource ARNs each principal needs, and MUST NOT grant `directconnect:*` on
  resource `*` or attach any `*FullAccess` managed policy.

## Additional Resources

- [AWS Direct Connect link aggregation groups (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/lags.html)
- [MAC Security in Direct Connect (AWS Direct Connect User Guide)](https://docs.aws.amazon.com/directconnect/latest/UserGuide/MACsec.html)
