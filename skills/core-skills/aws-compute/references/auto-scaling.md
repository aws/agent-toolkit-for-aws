# EC2 Auto Scaling

## Overview
Running a self-healing, elastic fleet with Auto Scaling groups (ASGs): health checks, scaling policies, rolling updates via instance refresh, mixed instances/Spot, warm pools, lifecycle hooks, and load-balancer attachment.

## Create an ASG
Creating an ASG requires only a name, `MinSize`, and `MaxSize`, plus a launch source (a **launch template** — recommended, see [provisioning.md](provisioning.md) — or a MixedInstancesPolicy). `DesiredCapacity` is optional (defaults to `MinSize`). Specifying subnets (`VPCZoneIdentifier`) across multiple AZs is optional at the API level but a strongly recommended resilience practice.

```bash
aws autoscaling create-auto-scaling-group \
  --auto-scaling-group-name my-asg \
  --launch-template LaunchTemplateName=my-app,Version='3' \
  --min-size 2 --max-size 6 --desired-capacity 2 \
  --vpc-zone-identifier "subnet-aaa,subnet-bbb" \
  --health-check-type ELB --health-check-grace-period 300
```

## Health checks (the #1 gotcha)
EC2 status checks are always on. **ELB health checks are ignored unless you set `--health-check-type ELB`** — otherwise an instance that fails the target group's health check but passes EC2 checks stays in service and is never replaced. Fix an existing group:

```bash
aws autoscaling update-auto-scaling-group --auto-scaling-group-name my-asg \
  --health-check-type ELB --health-check-grace-period 300
```

**Grace period:** console default 300s, CLI/SDK default 0 (off). Too short → new instances are killed before they finish booting (symptom: ASG "keeps replacing instances"). If an instance leaves the `running` state, it's replaced immediately regardless of grace period.

## Scaling policies

| Policy | When |
|--------|------|
| **Target tracking** (recommended default) | Keep a metric at a target (e.g., `ASGAverageCPUUtilization` 50%, or `ALBRequestCountPerTarget`) |
| Step scaling | Different-sized responses based on alarm breach magnitude |
| Simple scaling (legacy) | Avoid for new work |
| Predictive scaling | ML forecast that provisions ahead of predictable cycles — **complements**, not replaces, dynamic scaling |

Target tracking uses **instance warmup** (`DefaultInstanceWarmup`), not the ASG cooldown (cooldown applies to simple scaling). Set warmup so not-yet-ready instances don't skew metrics.

```bash
aws autoscaling put-scaling-policy --auto-scaling-group-name my-asg \
  --policy-name cpu50 --policy-type TargetTrackingScaling \
  --target-tracking-configuration '{"PredefinedMetricSpecification":{"PredefinedMetricType":"ASGAverageCPUUtilization"},"TargetValue":50.0}'
```

## Instance refresh (rolling updates)
Roll out a launch-template change (new AMI, user data) by replacing instances in batches:

```bash
aws autoscaling start-instance-refresh --auto-scaling-group-name my-asg \
  --preferences '{"MinHealthyPercentage":90,"InstanceWarmup":300}'
```

- **Skip matching is enabled by default in the console** — the refresh skips instances already matching the target config. If nothing gets replaced, the ASG probably isn't pointing at a new, specific launch-template version (e.g., it uses `$Latest`/`$Default` or an SSM-parameter AMI that resolved unchanged). Point the ASG at the new numeric version or disable skip matching.
- `MinHealthyPercentage` default 90; `MaxHealthyPercentage` 100–200 (requires Min set, spread ≤100). Setting `MinHealthyPercentage=100` (with `MaxHealthyPercentage>100`) launches replacements before terminating old ones (faster, extra cost).
- Checkpoints replace in stages (ascending %, last = 100). Monitor with `describe-instance-refreshes`; cancel with `cancel-instance-refresh`; mid-flight `rollback-instance-refresh`.
- **Auto-rollback is unsupported** when the launch template version is `$Latest`/`$Default` or the AMI is an SSM parameter — pin a numeric version to enable it.

## Mixed instances and Spot
A mixed instances policy combines a launch template with instance-type overrides and an on-demand/Spot distribution for cost and resilience.

- **Spot allocation strategy: use `price-capacity-optimized`** (low price + available capacity → fewer interruptions). `capacity-optimized` is a fine alternative; `lowest-price` is legacy and interrupts more.
- **Enable Capacity Rebalancing** (`--capacity-rebalance`) so the ASG proactively replaces at-risk Spot instances on the rebalance recommendation, before the 2-minute interruption notice.
- Diversify across many instance types and AZs. `OnDemandBaseCapacity` guarantees a floor of On-Demand; `OnDemandPercentageAboveBaseCapacity` splits the rest.

## Warm pools
A warm pool keeps pre-initialized (Stopped by default, or Running/Hibernated) instances ready, cutting scale-out latency for long-booting apps (e.g., 30s vs 4min). Default size = max − desired; cap with `MaxGroupPreparedCapacity`. Warm-pool instances don't contribute to scaling metrics until they enter service.

## Lifecycle hooks
Hooks pause instances at `Pending:Wait` (launch) or `Terminating:Wait` (terminate) so you can run setup/teardown.

- **Heartbeat timeout defaults to 3600s (1h); `DefaultResult` defaults to `ABANDON`** — a launch hook that times out terminates the instance. This is the classic "stuck in Pending:Wait for an hour then killed."
- Signal completion: `aws autoscaling complete-lifecycle-action --lifecycle-action-result CONTINUE …`, or extend with `record-lifecycle-action-heartbeat`. If the hook doesn't need to block, set `DefaultResult=CONTINUE`. Verify the notification target (SNS/SQS/EventBridge) and its IAM permissions. Since payloads carry instance metadata, enable SSE-KMS on the SNS topic/SQS queue and restrict its access policy so only authorized AWS accounts and principals can subscribe or poll — verify each SNS subscriber and SQS consumer is expected, and rely on SNS subscription confirmation to keep unauthorized endpoints from receiving instance metadata.

## Attaching a load balancer target group
Attach the **target group** to the ASG (not the instances) — the ASG auto-registers/deregisters:

```bash
aws autoscaling attach-traffic-sources --auto-scaling-group-name my-asg \
  --traffic-sources Identifier=<target-group-arn>
```

- Target group **target type must be `instance`** (not `ip`) for an ASG. LB, target group, and ASG must share account/VPC/Region.
- Don't manually register instances — the ASG owns registration.
- Deregistration delay (connection draining) defaults to 300s; premature termination during draining causes client 5xx.
- The launch template's security group must allow inbound from the load balancer; apply launch-template changes to existing instances via instance refresh.
- For a public web fleet, terminate TLS on the load balancer with an ACM certificate (HTTPS listener, redirect HTTP→HTTPS) so client traffic is encrypted in transit; the listener/ALB configuration itself belongs to `aws-networking`.
- For a public web fleet, also set security response headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options) via an ALB response header policy or application middleware; the detailed ALB setup belongs to `aws-networking`.
- For a public web fleet, front the ALB with AWS WAF for defense in depth against common web exploits (SQL injection, XSS, bot traffic); the detailed WAF rule configuration belongs to `aws-networking`.

## Monitoring
Enable ASG group metrics (`enable-metrics-collection`) plus detailed instance monitoring in the launch template, and alarm on key metrics (`GroupInServiceInstances`, unhealthy host count) and ASG activity notifications (to a KMS-encrypted SNS topic) so scaling failures surface early.

For a security audit trail (not just operational metrics), ensure CloudTrail is enabled in all Regions and alarm on sensitive Auto Scaling / EC2 API actions — e.g. `UpdateAutoScalingGroup`, `DeleteAutoScalingGroup`, and unexpected scaling activity — so unauthorized configuration changes are detected.

## Common Errors

| Error/Symptom | Cause | Fix |
|---------------|-------|-----|
| ASG never replaces LB-unhealthy instances | Health check type still EC2 | `--health-check-type ELB` |
| ASG keeps replacing booting instances | Grace period too short | Raise grace period or use a launch lifecycle hook |
| Instances stuck in `Pending:Wait`, killed after ~1h | Hook not completed (3600s, ABANDON) | `complete-lifecycle-action` CONTINUE, or `DefaultResult=CONTINUE` |
| Instance refresh replaced nothing | Skip matching + config unchanged | Point ASG at new numeric launch-template version, or disable skip matching |
| Instance refresh won't roll back | Launch template uses `$Latest`/`$Default`/SSM AMI | Pin a numeric version + specify desired config |
| Frequent Spot interruptions | `lowest-price` strategy, few types | `price-capacity-optimized` + Capacity Rebalancing + diversify |
| Can't attach target group | Target type is `ip` | Recreate target group with target type `instance` |
| `MaxHealthyPercentage` rejected | Out of 100–200 or Min unset or spread >100 | Set both, keep spread ≤100 |

## Security Considerations

- **Lifecycle-hook notifications carry instance metadata** — prevent confused-deputy on the notification role by adding `aws:SourceArn` (the ASG ARN) / `aws:SourceAccount` condition keys to the **IAM service role's trust policy** (the statement trusting `autoscaling.amazonaws.com`), not to the SNS/SQS policy. Separately harden the topic/queue: enable SSE-KMS, restrict the access policy to authorized accounts/principals and restrict publish to that role, verify each subscriber/consumer is expected, and require SNS subscription confirmation so unauthorized endpoints can't receive it.
- **Audit ASG configuration changes** — ensure CloudTrail is on and alarm on sensitive actions (`UpdateAutoScalingGroup`, `DeleteAutoScalingGroup`, unexpected scaling activity) to catch unauthorized changes.
- **Inherit least-privilege from the launch template** — the template's IMDSv2/security-group/instance-profile settings propagate to every launched instance, so harden it (see [provisioning.md](provisioning.md)).

## Related

- [provisioning.md](provisioning.md) — launch templates
- [instance-selection.md](instance-selection.md) — instance types and Spot suitability
- [troubleshooting.md](troubleshooting.md) — capacity and connectivity errors
