# Service Scaling and Updates Reference

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [Scaling Policy Types](#scaling-policy-types)
- [Web Service CPU Target Tracking](#web-service-cpu-target-tracking)
- [SQS Worker Scaling](#sqs-worker-scaling)
- [Scale-to-Zero](#scale-to-zero)
- [Deployment Types](#deployment-types)
- [Rolling Update Configuration](#rolling-update-configuration)
- [Deployment Circuit Breaker](#deployment-circuit-breaker)
- [Native ECS Blue/Green Deployment](#native-ecs-bluegreen-deployment)
- [Service Connect](#service-connect)
- [Deployment Troubleshooting](#deployment-troubleshooting)
- [Graceful Shutdown](#graceful-shutdown)

---

## Verify Dependencies

Before configuring scaling or updating deployment settings, the operator MUST confirm:

1. The ECS service `$SERVICE_NAME` exists in cluster `$CLUSTER`.
2. The service is in a steady state (`runningCount` equals `desiredCount`).
3. For scaling: the Application Auto Scaling service-linked role exists.

```bash
aws sts get-caller-identity --output json
aws ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$SERVICE_NAME" \
  --region "$REGION" \
  --output json
```

---

## Scaling Policy Types

| Policy Type      | Use Case                                                    | Trigger                                    |
|------------------|-------------------------------------------------------------|--------------------------------------------|
| Target Tracking  | Maintain a metric at a target value (e.g., CPU at 70%).     | CloudWatch metric crosses target.          |
| Step Scaling     | Scale in discrete steps based on alarm thresholds.          | CloudWatch alarm breaches.                 |
| Predictive       | Pre-scale based on historical traffic patterns.             | ML forecast of future demand.              |
| Scheduled        | Scale at known times (e.g., business hours, batch windows). | Cron, at, or rate expression.              |

The operator SHOULD use target tracking for most workloads. Step scaling MAY be used when finer control over scaling increments is needed.

---

## Web Service CPU Target Tracking

For a web service behind an ALB, CPU-based target tracking is the most common scaling approach.

### Register Scalable Target

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "service/$CLUSTER/$SERVICE_NAME" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --min-capacity 2 \
  --max-capacity 20 \
  --region "$REGION" \
  --output json
```

### Create Target Tracking Policy

```bash
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "service/$CLUSTER/$SERVICE_NAME" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --policy-name "$SERVICE_NAME-cpu-target-tracking" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 70.0,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
    },
    "ScaleOutCooldown": 60,
    "ScaleInCooldown": 300
  }' \
  --region "$REGION" \
  --output json
```

| Parameter          | Value | Rationale                                                    |
|--------------------|-------|--------------------------------------------------------------|
| `TargetValue`      | 70.0  | SHOULD be set as high as possible with a buffer for traffic spikes. AWS examples use 75.0. |
| `ScaleOutCooldown` | 60    | Seconds to wait for a previous scale-out to take effect. Default is 300s for ECS; 60s shown here for faster response. A larger scale-out CAN override the cooldown. |
| `ScaleInCooldown`  | 300   | Seconds to wait after a scale-in. SHOULD be longer to avoid flapping. |

---

## SQS Worker Scaling

Two patterns exist for SQS-based auto scaling:

### Pattern 1: Backlog-per-task target tracking (recommended)

The operator SHOULD scale on a custom **backlog-per-task** metric rather than queue depth alone.

```
BacklogPerTask = ApproximateNumberOfMessagesVisible / RunningTaskCount
```

Use metric math in the scaling policy to compute this inline — no custom metric publishing needed. Specify `(m1)/(m2)` where m1 is `ApproximateNumberOfMessagesVisible` (Sum) and m2 is `RunningTaskCount` (Average). The target value SHOULD be the acceptable backlog per task (e.g., 10 messages per task).

### Pattern 2: CDK QueueProcessingFargateService (step scaling on queue depth)

The CDK L3 pattern uses **step scaling** on raw `ApproximateNumberOfMessagesVisible` (queue depth), NOT target tracking on backlog-per-task. This is simpler but less proportional.

```typescript
import * as ecs_patterns from 'aws-cdk-lib/aws-ecs-patterns';

const service = new ecs_patterns.QueueProcessingFargateService(this, 'Worker', {
  cluster,
  image: ecs.ContainerImage.fromEcrRepository(repo, '$IMAGE_TAG'),
  queue: queue,
  minScalingCapacity: 1,
  maxScalingCapacity: 50,
  scalingSteps: [
    { upper: 0, change: -1 },
    { lower: 1, change: +1 },
    { lower: 100, change: +5 },
    { lower: 500, change: +10 },
  ],
  cpu: 512,
  memoryLimitMiB: 1024,
});
```

The `scalingSteps` define step scaling increments based on the `ApproximateNumberOfMessagesVisible` metric. The `upper: 0` step scales in when the queue is empty.

---

## Scale-to-Zero

ECS Auto Scaling natively supports scaling to zero. Set `minCapacity` to 0 and target tracking will scale in to 0 tasks when the metric indicates low utilization. Per AWS docs: "If you want your task count to scale to zero when there's no work to be done, set a minimum capacity of 0."

### Scale-out from zero depends on the metric type

When at 0 tasks, target tracking needs metric data to trigger scale-out. Whether this works depends on whether the metric continues to emit at 0 tasks:

| Metric Type | Emitted at 0 Tasks? | Full Round-Trip (0→N→0)? |
|---|---|---|
| SQS queue depth (`ApproximateNumberOfMessagesVisible`) | Yes — SQS emits regardless of consumers | ✅ Works natively |
| External custom metric (published by Lambda or external source) | Yes — publisher runs independently | ✅ Works natively |
| CPU/Memory (`ECSServiceAverageCPUUtilization`) | No — no tasks, no metric data | ❌ Scale-out from 0 fails (`INSUFFICIENT_DATA`) |
| ALB request count (`ALBRequestCountPerTarget`) | No — no registered targets | ❌ Scale-out from 0 fails |
| Per-task custom metric (e.g., backlog/tasks) | No — division by zero at 0 tasks | ❌ Scale-out from 0 fails |

### EventBridge + Lambda Pattern (for task-dependent metrics)

For workloads using CPU, memory, ALB, or per-task metrics, the operator MUST use an external trigger to scale out from 0:

1. An EventBridge rule triggers a Lambda function on a schedule or when the SQS queue has messages.
2. The Lambda function sets the service desired count to 1 when work is available.
3. Auto Scaling handles scaling beyond 1.
4. Target tracking handles scaling back to 0 when utilization drops (no workaround needed for scale-in).

```bash
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE_NAME" \
  --desired-count 0 \
  --region "$REGION" \
  --output json
```

> The operator MUST ensure the auto scaling `minCapacity` is set to 0 for scale-to-zero to work.

---

## Deployment Types

| Type                          | Mechanism                                                  | Availability         |
|-------------------------------|------------------------------------------------------------|----------------------|
| Rolling Update (ECS)          | Replaces tasks incrementally using `minimumHealthyPercent` and `maximumPercent`. | GA                   |
| Native ECS Blue/Green         | ECS-managed blue/green with traffic shifting.              | GA (July 2025+)      |
| CodeDeploy Blue/Green         | CodeDeploy-managed blue/green with traffic shifting.       | GA — native ECS blue/green recommended for new workloads. CodeDeploy remains valid for existing CodePipeline integrations. |

---

## Rolling Update Configuration

### minimumHealthyPercent and maximumPercent

| desiredCount | minimumHealthyPercent | maximumPercent | Behavior                                                  |
|--------------|-----------------------|----------------|-----------------------------------------------------------|
| 1            | 0                     | 200            | Scheduler starts new task first (ceiling allows 2), then stops old. But if new task fails, service can drop to 0 tasks (downtime). No zero-downtime guarantee. |
| 1            | 100                   | 200            | Starts new task first, waits for healthy, then stops old. Zero downtime. |
| 2+           | 50                    | 200            | Stops half, starts replacements. Faster but reduced capacity during deploy. |
| 2+           | 100                   | 200            | Starts new tasks first, then drains old. RECOMMENDED for zero downtime. |

The operator SHOULD use `minimumHealthyPercent=100` and `maximumPercent=200` for services that require zero downtime.

For `desiredCount=1`, the operator MUST set `maximumPercent=200` to allow the new task to start before the old one stops.

---

## Deployment Circuit Breaker

The circuit breaker monitors deployment health in two stages:

### Stage 1: Task Reaches RUNNING

ECS verifies the new task transitions to `RUNNING` state. If the container crashes or fails to start, this stage fails.

### Stage 2: Health Checks Pass

If the service uses a load balancer, ECS verifies the target passes health checks. If using container health checks, those MUST also pass.

### Failure Threshold Formula

```
Minimum threshold (3) <= ceil(0.5 * desired task count) => Maximum threshold (200)
```

The circuit breaker has a minimum threshold of **3** and a maximum threshold of **200**. You cannot change either value.

| Desired Task Count | Calculation | Threshold |
|---|---|---|
| 1 | `ceil(0.5 * 1) = 1` → below minimum | 3 |
| 25 | `ceil(0.5 * 25) = 13` | 13 |
| 400 | `ceil(0.5 * 400) = 200` | 200 |
| 800 | `ceil(0.5 * 800) = 400` → above maximum | 200 |

When the number of consecutive failed tasks reaches the threshold, the circuit breaker marks the deployment as `FAILED` and (if `rollback=true`) automatically rolls back to the last `COMPLETED` deployment.

### Enable Circuit Breaker

```bash
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE_NAME" \
  --deployment-configuration "minimumHealthyPercent=100,maximumPercent=200,deploymentCircuitBreaker={enable=true,rollback=true}" \
  --region "$REGION" \
  --output json
```

---

## Native ECS Blue/Green Deployment

Available since July 2025, native ECS blue/green deployment is managed entirely by ECS without CodeDeploy.

### Advantages Over CodeDeploy Blue/Green

- No CodeDeploy application or deployment group to manage.
- Integrated with ECS service events and CloudWatch metrics.
- Supports traffic shifting strategies (all-at-once, linear, canary) natively.
- Simpler IAM — no CodeDeploy role required.
- Faster rollback — ECS shifts traffic back without waiting for CodeDeploy orchestration.

The operator SHOULD use native ECS blue/green for new services that require blue/green deployment.

---

## Service Connect

Service Connect provides service mesh capabilities for ECS services, enabling service-to-service communication with automatic load balancing and traffic management.

The operator MAY use Service Connect for:

- Service discovery without Route 53 DNS — ECS manages Cloud Map namespaces automatically.
- Client-side load balancing across tasks.
- Observability with built-in metrics for inter-service traffic.

Service Connect is configured in the service definition via `serviceConnectConfiguration`. Task definitions contribute `portMappings` with `name` and `appProtocol` fields.

Service Connect replaces App Mesh for most ECS service-to-service communication. Use App Mesh only when you need advanced traffic policies (weighted routing, retries with custom conditions) across non-ECS workloads.

---

## Deployment Troubleshooting

### Stuck Deployment

A deployment is stuck when `runningCount` does not converge to `desiredCount`.

1. Check service events for error messages:

   ```bash
   aws ecs describe-services \
     --cluster "$CLUSTER" \
     --services "$SERVICE_NAME" \
     --region "$REGION" \
     --query "services[0].events[:10]" \
     --output json
   ```

2. Check stopped tasks for the failure reason:

   ```bash
   aws ecs list-tasks \
     --cluster "$CLUSTER" \
     --service-name "$SERVICE_NAME" \
     --desired-status STOPPED \
     --region "$REGION" \
     --output json
   ```

3. Common causes: image pull failure, insufficient resources, health check failure, security group misconfiguration.

### Reducing Deployment Time

- Lower `deregistration_delay.timeout_seconds` on the target group (30s is often sufficient).
- Set `stopTimeout` to match the application's drain time (not longer).
- Use `maximumPercent=200` to start new tasks before stopping old ones.
- Ensure health check intervals and thresholds are not overly conservative.

### Force New Deployment

To force a redeployment with the same task definition (e.g., to pick up a new image on a mutable tag):

```bash
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE_NAME" \
  --force-new-deployment \
  --region "$REGION" \
  --output json
```

> The operator SHOULD use immutable image tags and register a new task definition revision instead of relying on `--force-new-deployment` with mutable tags.

---

## Graceful Shutdown

When ECS stops a task (during deployments, scale-in, or manual stop), it sends **SIGTERM** to the container's PID 1 process.

### Signal Flow

1. ECS sends `SIGTERM` to the container.
2. The application SHOULD begin draining connections and completing in-flight requests.
3. After `stopTimeout` seconds (default 30s, max 120s on Fargate), ECS sends `SIGKILL`.

### Application Requirements

The application MUST handle `SIGTERM` to shut down gracefully. Common patterns:

- Stop accepting new connections.
- Complete in-flight requests.
- Close database connections and flush buffers.
- Exit with code 0.

### stopTimeout Configuration

```bash
# In the task definition containerDefinitions:
"stopTimeout": 60
```

The `stopTimeout` SHOULD be set to:

- At least as long as the target group `deregistration_delay.timeout_seconds`.
- Long enough for the application to complete in-flight work.
- No longer than necessary — longer values slow down deployments.

### initProcessEnabled

The operator SHOULD set `initProcessEnabled: true` in the container definition. This runs an init process (tini) as PID 1, which properly forwards signals to the application and reaps zombie processes.

```json
"linuxParameters": {
  "initProcessEnabled": true
}
```
