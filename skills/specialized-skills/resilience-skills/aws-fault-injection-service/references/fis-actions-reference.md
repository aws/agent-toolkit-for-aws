# AWS FIS Actions, Action Selection & Scenario Library

Use this to **suggest** the right fault for a scenario and to build the `actions` block of a
template. Action IDs and parameters change over time — **verify with `aws fis list-actions` and
`aws fis get-action --id <action-id>`** (or the [FIS Actions reference](https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html))
before committing to a command. The tables below are illustrative, not a frozen source of truth.

## Contents

- Action structure
- Action selection map — match failure scenario → action
- Action catalog by namespace (illustrative)
- Targets — how to scope the blast radius
- Scenario library (console-only, AWS-owned)
- Prerequisites & gotchas by action

## Action structure

Each action in `actions` has:

| Field | Meaning |
|---|---|
| `actionId` | The pre-defined FIS action to run (e.g. `aws:ec2:stop-instances`). **Required.** |
| `parameters` | Key-value pairs for the action (durations use ISO 8601, e.g. `PT10M`). Required/optional per action. |
| `targets` | Maps the action's target role name → a target defined in the template's `targets` block. |
| `startAfter` | Names of actions that must finish before this one starts. Omit → runs in parallel. |

```json
"actions": {
  "StopInstances": {
    "actionId": "aws:ec2:stop-instances",
    "description": "Stop EC2 instances then restart after 10 minutes",
    "parameters": { "startInstancesAfterDuration": "PT10M" },
    "targets": { "Instances": "myInstanceTarget" },
    "startAfter": []
  }
}
```

### Action ID naming convention

`aws:<service-name>:<action-type>` — e.g. `aws:rds:failover-db-cluster`. Service-level fault
namespaces (`aws:ec2:*`, `aws:rds:*`, …) act on infrastructure; the `aws:fis:*` namespace injects
**API-level** faults and provides control actions (`wait`).

## Action selection map — match failure scenario → action

Models often pick a real but *wrong* action. Use this map, then verify the ID.

| If the scenario is… | Illustrative action ID (verify with `list-actions`) |
|---|---|
| Full AZ power interruption / "AZ goes dark" | Use the **AZ Availability: Power Interruption** scenario (multi-fault); it combines instance/subnet/EBS/RDS/ElastiCache faults |
| Single-AZ instance loss | `aws:ec2:stop-instances` or `aws:ec2:terminate-instances` (scope target to the AZ via filter) |
| Spot capacity reclaim | `aws:ec2:send-spot-instance-interruptions` |
| ECS task loss / capacity drain | `aws:ecs:stop-task`, `aws:ecs:drain-container-instances` |
| EKS pod failure | `aws:eks:pod-delete` |
| EKS node loss | `aws:eks:terminate-nodegroup-instances` |
| EKS pod latency / packet loss | `aws:eks:pod-network-latency`, `aws:eks:pod-network-packet-loss` |
| DB / Aurora / RDS failover | `aws:rds:failover-db-cluster` (cluster) or `aws:rds:reboot-db-instances` (instance) |
| ElastiCache node/AZ disruption | `aws:elasticache:replicationgroup-interrupt-az-power` |
| Region-level API unavailability | `aws:fis:inject-api-unavailable-error` |
| Service returns 5xx but is reachable | `aws:fis:inject-api-internal-error` |
| Throttling / 429 responses | `aws:fis:inject-api-throttle-error` |
| Lambda slow responses (latency) | `aws:lambda:invocation-add-delay` |
| Lambda forced errors | `aws:lambda:invocation-error` |
| Lambda altered HTTP integration response | `aws:lambda:invocation-http-integration-response` |
| Network partition / subnet isolation | `aws:network:disrupt-connectivity` |
| Route-table-level connectivity loss | `aws:network:route-table-disrupt-connectivity` |
| Cross-Region (transit gateway) isolation | `aws:network:transit-gateway-disrupt-cross-region-connectivity` |
| EBS volume I/O latency | `aws:ebs:pause-volume-io` (Nitro only) — or the EBS latency scenarios |
| Run a custom fault on a host | `aws:ssm:send-command`, `aws:ssm:start-automation-execution` |
| Assert a CloudWatch alarm's state mid-experiment | `aws:cloudwatch:assert-alarm-state` |
| Trigger ARC zonal autoshift | `aws:arc:start-zonal-autoshift` |
| Insert a pause between actions | `aws:fis:wait` |

**Rule of thumb:** a **service/API symptom** (unavailable, 5xx, throttle) → `aws:fis:inject-api-*`
(all three end in `-error`). An **infrastructure symptom** (instance, task, pod, DB, cache,
volume, network) → the resource-specific namespace.

## Action catalog by namespace (illustrative)

- **EC2** — `aws:ec2:stop-instances`, `aws:ec2:reboot-instances`, `aws:ec2:terminate-instances`,
  `aws:ec2:send-spot-instance-interruptions`, `aws:ec2:api-insufficient-instance-capacity-error`.
- **ECS** — `aws:ecs:stop-task`, `aws:ecs:drain-container-instances`, plus SSM-agent-based CPU/
  memory/IO/network stress task actions.
- **EKS** — `aws:eks:pod-delete`, `aws:eks:terminate-nodegroup-instances`,
  `aws:eks:pod-cpu-stress`, `aws:eks:pod-memory-stress`, `aws:eks:pod-io-stress`,
  `aws:eks:pod-network-latency`, `aws:eks:pod-network-packet-loss`,
  `aws:eks:pod-network-blackhole-port`.
- **RDS** — `aws:rds:reboot-db-instances`, `aws:rds:failover-db-cluster`.
- **ElastiCache** — `aws:elasticache:replicationgroup-interrupt-az-power`.
- **EBS** — `aws:ebs:pause-volume-io` (Nitro-based instances only).
- **Lambda** — `aws:lambda:invocation-add-delay`, `aws:lambda:invocation-error`,
  `aws:lambda:invocation-http-integration-response` (require the FIS Lambda extension layer).
- **Network** — `aws:network:disrupt-connectivity`,
  `aws:network:route-table-disrupt-connectivity`,
  `aws:network:transit-gateway-disrupt-cross-region-connectivity`.
- **FIS API faults / control** — `aws:fis:inject-api-internal-error`,
  `aws:fis:inject-api-throttle-error`, `aws:fis:inject-api-unavailable-error`, `aws:fis:wait`.
- **SSM (custom faults on hosts)** — `aws:ssm:send-command` (runs an SSM document, e.g. FIS
  public stress documents like `AWSFIS-Run-CPU-Stress`), `aws:ssm:start-automation-execution`.
  Requires the SSM Agent installed/running on targets.
- **CloudWatch** — `aws:cloudwatch:assert-alarm-state`.
- **ARC** — `aws:arc:start-zonal-autoshift`.

## Targets — how to scope the blast radius

A target defines `resourceType` (exactly one) plus one selector:

- `resourceArns` — specific resource ARNs (cannot combine with tags or filters).
- `resourceTags` — map of tag key→value; **all** listed tags must match (AND).
- `filters` — `path` (PascalCase, from the resource's Describe API output) + `values` (OR within
  a filter; AND across filters). Cannot combine with `resourceArns`.
- `parameters` — attribute-based selectors for certain resource types (see below).
- `selectionMode` — `ALL`, `COUNT(n)`, or `PERCENT(n)`; picks from the identified set at random.
  `COUNT(n)` selects exactly `n` resources — no rounding. `PERCENT(n)` resolves the percentage to a
  count and **rounds down**; if it resolves to fewer than 1 resource, nothing is selected and the
  experiment fails.

FIS resolves **all** targets at experiment start. If a target resolves to zero resources, the
experiment fails (unless `emptyTargetResolutionMode` is `skip`).

### Resource parameters (attribute selectors) — examples

- `aws:ec2:ebs-volume` → `availabilityZoneIdentifier`.
- `aws:ec2:subnet` → `availabilityZoneIdentifier`, `vpc` (one VPC per account).
- `aws:ecs:task` → `cluster`, `service`.
- `aws:eks:pod` → `clusterIdentifier` (req), `namespace` (req), `selectorType`
  (`labelSelector`|`deploymentName`|`podName`, req), `selectorValue` (req),
  `availabilityZoneIdentifier` (opt), `targetContainerName` (opt).
- `aws:lambda:function` → `functionQualifier`.
- `aws:rds:cluster` → `writerAvailabilityZoneIdentifiers`; `aws:rds:db` → `availabilityZoneIdentifiers`.
- `aws:elasticache:replicationgroup` → `availabilityZoneIdentifier` (req).

**Multi-account / cross-AZ tip:** when targeting by AZ, use the **AZ ID** (e.g. `use1-az1`), not
the AZ name (`us-east-1a`) — AZ IDs are consistent across accounts.

### Example target

```json
"targets": {
  "randomInstance": {
    "resourceType": "aws:ec2:instance",
    "resourceTags": { "env": "prod" },
    "filters": [
      { "path": "Placement.AvailabilityZone", "values": ["us-east-1a"] },
      { "path": "State.Name", "values": ["running"] }
    ],
    "selectionMode": "COUNT(1)"
  }
}
```

## Scenario library (console-only, AWS-owned)

Scenarios are pre-built target+action patterns for common impairments. They are a **console-only**
experience: select one in the FIS console → **Create template with scenario** → fill in
parameters, role, stop conditions, logging → save as an experiment template. To automate, either
export the created template, or copy the scenario's **Content** tab and complete missing
parameters manually. Prefer a scenario over a hand-built template when one fits — less
undifferentiated heavy lifting and AWS-maintained.

Common scenarios (verify current library in the console):

**EC2 (target by tag):**

- **EC2 stress: instance failure** — stop instances, restart after the action duration (default 5 min).
- **EC2 stress: CPU / Memory / Disk / Network Latency** — inject increasing resource pressure.

**EKS (target pods by Kubernetes app label):**

- **EKS stress: Pod Delete** — delete matched pods (recovery per k8s config).
- **EKS stress: CPU / Memory / Disk / Network latency**.

**Single-AZ / multi-AZ / multi-Region (multiple resource types):**

- **AZ Availability: Power Interruption** — simulate a complete power interruption in one AZ.
- **AZ: Application Slowdown** — add latency between resources within one AZ.
- **Cross-AZ: Traffic Slowdown** — inject packet loss between AZs.
- **Cross-Region: Connectivity** — block traffic from the experiment Region to a destination
  Region and pause cross-Region data replication.

**EBS (target volumes by tag; volumes must be in the same AZ):**

- **EBS: Sustained / Increasing / Intermittent / Decreasing Latency** — I/O latency patterns.

## Prerequisites & gotchas by action

- **SSM-based actions** (host stress, custom faults): SSM Agent must be installed and running on
  targets; the experiment role needs SSM permissions.
- **Lambda actions**: require the FIS Lambda extension layer configured on the function.
- **EBS `pause-volume-io`**: target volumes must be attached to Nitro-based instances.
- **EKS pod actions**: require the target EKS cluster to be prepared for FIS (see EKS Pod actions docs).
- **Network faults**: verify VPC/subnet/route-table prerequisites; connectivity disruption acts
  at the network layer, not the API layer.
