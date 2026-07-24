# Recovery Controls with AWS Application Recovery Controller

## Overview

This SOP guides you through setting up operational recovery mechanisms: traffic routing controls with safety rules for cross-Region failover, and zonal shift / zonal autoshift for AZ impairment recovery. Use when operationalizing recovery — for example after validating a failure mode (with FIS or another test), or when NGRH findings indicate "no recovery mechanism."

## Scope

This SOP covers exactly two ARC capability families: routing controls (with safety rules) for cross-Region failover, and zonal shift / zonal autoshift for AZ-impairment recovery. If asked about readiness checks, recovery groups, cells, or resource sets, do NOT provide setup steps for them. You MAY briefly and factually acknowledge they exist, but redirect the customer to ARC Region switch for readiness/recovery-readiness orchestration (see the `arc-region-switch` skill) for those, and continue with routing controls and zonal shift / zonal autoshift for the operational pieces this SOP covers.

## Parameters

Parameters are grouped by capability — routing controls (cross-Region failover) and zonal shift / zonal autoshift (AZ recovery) use different ones.

**Routing controls (cross-Region failover):**
**service_name** (required): Name of the service (used for naming routing controls)
**cluster_arn** (required): ARC cluster ARN. NOTE: the routing-control **control plane** (`route53-recovery-control-config`) is a single global service hosted in **us-west-2 (PDX)** — create the cluster, control panel, and routing controls there regardless of where your application runs. The **data plane** (`route53-recovery-cluster`, used to flip states) is reached through the cluster's Regional data-plane endpoints (enumerated by `describe-cluster`).
**control_panel_arn** (required): Control panel ARN for the application
**primary_region** / **secondary_region** (required): The application Regions you fail between (e.g., "us-east-1" / "us-west-2"). These only name the routing controls — they are NOT where the control plane lives.

**Zonal shift / zonal autoshift (AZ recovery):**
**resource_identifier** (optional): ARN of a zonal-shift-supported resource. The set of supported resource types is managed by AWS — confirm support in the ARC zonal shift documentation, or check a specific resource with `aws arc-zonal-shift get-managed-resource --resource-identifier <arn>`.
**outcome_alarm_arn** (optional): CloudWatch outcome-alarm ARN for autoshift practice runs
**deployment_alarm_arn** (optional): CloudWatch alarm ARN that blocks practice runs during deployments
**blocked_window** (optional, default: "MON-08:00-MON-10:00"): Recurring window when a practice run must NOT start — set to the customer's actual deployment/peak window

**aws_region** (optional, default: "us-east-1"): Region for zonal-shift / data-plane calls (the routing-control control plane is always us-west-2 — see above)

## Steps

### 1. Verify Dependencies

Check for required tools and warn the customer if any are missing.

**Constraints:**

- You MUST verify that either the AWS CLI (e.g., `aws --version`) or the AWS MCP server's `call_aws` tool is available
- You MUST NOT attempt to run the tools during verification
- You MUST inform the customer about any missing tools with a clear message
- You MUST ask if the customer wants to proceed anyway despite missing tools
- You SHOULD recommend executing these operations with short-lived IAM role credentials (an EC2 instance profile, ECS task role, or `aws sts assume-role`) rather than long-lived IAM user access keys, since routing-control state changes and zonal shifts can move production traffic between Regions or AZs.

### 2. Create Routing Controls

Create one routing control per Region to serve as traffic switches.

**Constraints:**

- You MUST inform the customer that you are creating routing controls for cross-Region failover
- Routing controls require an existing ARC **cluster** and **control panel** (the `cluster_arn` / `control_panel_arn` parameters). If the customer does not already have a cluster, you MUST tell them that creating one (`aws route53-recovery-control-config create-cluster`) provisions a billed, always-on resource (an hourly per-cluster charge shown in the console at creation), and that they MUST record the cluster's **Regional data-plane endpoints** (from `describe-cluster`) and the routing control ARNs somewhere durable, since these are needed to fail over during an event when other APIs may be unavailable.
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws route53-recovery-control-config create-routing-control --cluster-arn {cluster_arn} --routing-control-name {service_name}-{primary_region} --control-panel-arn {control_panel_arn}`
- You MUST repeat for the secondary Region: `aws route53-recovery-control-config create-routing-control --cluster-arn {cluster_arn} --routing-control-name {service_name}-{secondary_region} --control-panel-arn {control_panel_arn}`
- You MUST capture the routing control ARNs from both responses
- You MUST inform the customer that routing controls must be wired to Route53 health checks and failover DNS records to affect traffic

### 3. Create Safety Rules

Add assertion rules to prevent unsafe states (e.g., all Regions off).

**Constraints:**

- You MUST inform the customer that you are creating safety rules to prevent turning off all traffic
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws route53-recovery-control-config create-safety-rule --assertion-rule '{"Name":"at-least-one-active","ControlPanelArn":"{control_panel_arn}","AssertedControls":["{primary_rc_arn}","{secondary_rc_arn}"],"RuleConfig":{"Type":"ATLEAST","Threshold":1,"Inverted":false},"WaitPeriodMs":5000}'`
- The `--assertion-rule` JSON uses PascalCase keys, and `Name` + `ControlPanelArn` are fields INSIDE the JSON — there are no separate `--name`/`--control-panel-arn` flags for this command
- You MUST explain `WaitPeriodMs` (here 5000 = 5s): the propagation/settling delay the data plane enforces before a routing-control state change takes effect, so concurrent updates are evaluated against a consistent rule state
- You MUST NOT create routing controls without safety rules — this risks turning off all traffic
- If the customer wants a gating rule, You MUST FIRST create a dedicated approval routing control and capture its ARN as `{approval_control_arn}`: `aws route53-recovery-control-config create-routing-control --cluster-arn {cluster_arn} --routing-control-name {service_name}-approval --control-panel-arn {control_panel_arn}`
- You SHOULD offer to create a gating rule if the customer wants approval-based failover: `aws route53-recovery-control-config create-safety-rule --gating-rule '{"Name":"require-approval","ControlPanelArn":"{control_panel_arn}","GatingControls":["{approval_control_arn}"],"TargetControls":["{primary_rc_arn}","{secondary_rc_arn}"],"RuleConfig":{"Type":"ATLEAST","Threshold":1,"Inverted":false},"WaitPeriodMs":0}'`

### 4. Test Failover

Demonstrate the failover operation using routing control state changes.

**Constraints:**

- You MUST inform the customer that failover is a safe, reversible operation protected by safety rules
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws route53-recovery-cluster update-routing-control-states --endpoint-url {cluster_endpoint} --region {endpoint_region} --update-routing-control-state-entries '[{"RoutingControlArn":"{primary_rc_arn}","RoutingControlState":"Off"},{"RoutingControlArn":"{secondary_rc_arn}","RoutingControlState":"On"}]'`
- You MUST explain that both state changes happen atomically in a single API call
- You MUST explain that the operation is immediately reversible (swap On/Off values to fail back)
- You MUST inform the customer that the data plane (`route53-recovery-cluster`) is reached through **one of** the cluster's **Regional data-plane endpoints** (distinct from the us-west-2 control-plane endpoint). For resilience during a Regional event, the customer MUST pick one of those endpoints **at random** and, on any failure (5xx/timeout), **retry against the other endpoints in turn** — retrying the same endpoint is not sufficient, since the endpoint they reach may itself be in the impaired Region. Recommend hard-coding/bookmarking the endpoints (from `describe-cluster`) so failover does not depend on a control-plane call that may be unavailable.

### 5. Configure Zonal Shift (Optional)

Set up manual zonal shift for AZ impairment scenarios.

**Constraints:**

- You MUST only proceed if the customer has a `resource_identifier` for a zonal-shift-supported resource (confirm support with `aws arc-zonal-shift get-managed-resource`)
- You MUST inform the customer that zonal shift moves traffic away from an impaired AZ
- You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws arc-zonal-shift start-zonal-shift --resource-identifier {resource_identifier} --away-from {availability_zone} --expires-in 1h --comment "{reason}"`
- You SHOULD confirm the resource is registered/managed by ARC first with `aws arc-zonal-shift get-managed-resource --resource-identifier {resource_identifier}` (a resource must be active and managed before traffic can be shifted)
- You MUST inform the customer that zonal shifts expire automatically and must be renewed if the issue persists

### 6. Configure Zonal Autoshift (Recommended)

Enable automatic traffic shifting when AWS detects AZ impairment.

**Constraints:**

- You MUST inform the customer that zonal autoshift lets AWS automatically shift traffic away from an AZ when AWS detects impairment, and that enabling it is a **two-step** flow: first create a practice-run configuration, then turn autoshift on.
- **Step 6a — create the practice-run configuration.** You MUST run the following AWS CLI command (use the AWS MCP server's `call_aws` tool when connected, otherwise the AWS CLI directly): `aws arc-zonal-shift create-practice-run-configuration --resource-identifier {resource_identifier} --outcome-alarms '[{"alarmIdentifier":"{outcome_alarm_arn}","type":"CLOUDWATCH"}]' --blocked-windows "{blocked_window}"`
  - `--outcome-alarms` is REQUIRED: AWS periodically runs a **practice run** (a real, brief zonal shift) to verify your application actually survives losing one AZ; the outcome alarm fires if the practice run causes problems and AWS rolls the shift back. Practice runs exist specifically to **continuously prove you have enough capacity to run on N-1 AZs** before a real impairment forces it.
  - `--blocked-windows` and `--blocking-alarms` govern the **practice runs** (not autoshift itself): blocked windows are recurring times when a practice run must NOT start (e.g., deployments, peak traffic), and blocking alarms suppress a practice run while in ALARM. A real, AWS-initiated autoshift during an actual AZ impairment is NOT blocked by these.
  - You MUST add `--blocking-alarms '[{"alarmIdentifier":"{deployment_alarm_arn}","type":"CLOUDWATCH"}]'` ONLY if the customer provides a `deployment_alarm_arn`; otherwise omit the flag entirely.
  - `{blocked_window}` defaults to `MON-08:00-MON-10:00`; You SHOULD confirm the customer's actual deployment/peak window(s) and substitute the real value(s) rather than assuming Monday morning.
- **Step 6b — enable autoshift.** You MUST run: `aws arc-zonal-shift update-zonal-autoshift-configuration --resource-identifier {resource_identifier} --zonal-autoshift-status ENABLED`
  - NOTE: there is NO `create-zonal-autoshift-configuration` operation — practice runs use the `*-practice-run-configuration` operations and autoshift is toggled with `update-zonal-autoshift-configuration`.
- You MUST verify the application can handle the loss of one AZ's worth of capacity — roughly 1/N of total, where N is the number of AZs the resource spans (commonly 3, but confirm with `aws ec2 describe-availability-zones` or the resource's subnet configuration) — before enabling autoshift; this is exactly what the practice runs validate on an ongoing basis.

## Examples

```bash
# Create routing controls
aws route53-recovery-control-config create-routing-control \
  --cluster-arn arn:aws:route53-recovery-control::123456789012:cluster/main \
  --routing-control-name checkout-us-east-1 \
  --control-panel-arn arn:aws:route53-recovery-control::123456789012:controlpanel/checkout

# Create safety rule (at least one Region active)
aws route53-recovery-control-config create-safety-rule \
  --assertion-rule '{"Name":"at-least-one-active","ControlPanelArn":"arn:aws:route53-recovery-control::123456789012:controlpanel/checkout","AssertedControls":["<east-arn>","<west-arn>"],"RuleConfig":{"Type":"ATLEAST","Threshold":1,"Inverted":false},"WaitPeriodMs":5000}'

# Fail over (atomic operation) — target one of the cluster's Regional data-plane endpoints
aws route53-recovery-cluster update-routing-control-states \
  --endpoint-url https://<one-of-the-cluster-endpoints> \
  --region <endpoint-region> \
  --update-routing-control-state-entries '[{"RoutingControlArn":"<east-arn>","RoutingControlState":"Off"},{"RoutingControlArn":"<west-arn>","RoutingControlState":"On"}]'

# Enable zonal autoshift (two steps: practice-run config, then turn autoshift on)
aws arc-zonal-shift create-practice-run-configuration \
  --resource-identifier arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/checkout/abc \
  --outcome-alarms '[{"alarmIdentifier":"arn:aws:cloudwatch:...","type":"CLOUDWATCH"}]' \
  --blocked-windows "MON-08:00-MON-10:00"
aws arc-zonal-shift update-zonal-autoshift-configuration \
  --resource-identifier arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/checkout/abc \
  --zonal-autoshift-status ENABLED
```

## Troubleshooting

**Safety rule blocks routing control update**
A safety rule is preventing the state change. You cannot turn off the last active routing control. Turn ON another routing control FIRST, then turn off the one you want. List rules with: `aws route53-recovery-control-config list-safety-rules --control-panel-arn {control_panel_arn}`

**Zonal autoshift practice run fails**
The outcome alarm fired — the application couldn't handle capacity reduction from losing one AZ. Fix: increase ASG minimum capacity (must handle N-1 AZs), verify cross-zone load balancing is enabled, check for AZ-pinned resources (EBS volumes, placement groups).

**Routing control state doesn't affect traffic**
Routing controls must be wired to Route53 health checks. Verify: (1) each routing control has an associated health check, (2) Route53 hosted zone has failover records pointing to those health checks. Use `aws route53-recovery-control-config describe-routing-control --routing-control-arn {arn}` to find the associated health check.
