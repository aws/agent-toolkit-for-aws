# Fargate Spot

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [When to Use Fargate Spot](#when-to-use-fargate-spot)
- [Capacity Provider Strategy](#capacity-provider-strategy)
- [Interruption Handling](#interruption-handling)

---

## Verify Dependencies

Operators MUST confirm the following before proceeding:

| Dependency | Check Command |
|---|---|
| Correct account/region | `aws sts get-caller-identity --output json` |
| ECS cluster exists | `aws ecs describe-clusters --clusters $CLUSTER --region $REGION --output json` |
| Cluster has Fargate capacity providers | `aws ecs describe-clusters --clusters $CLUSTER --region $REGION --output json --query 'clusters[0].capacityProviders'` |

If the cluster does not have `FARGATE` and `FARGATE_SPOT` capacity providers, add them:

```bash
aws ecs put-cluster-capacity-providers \
  --cluster $CLUSTER \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
  --region $REGION \
  --output json
```

---

## When to Use Fargate Spot

### Good Fit (SHOULD Use)

| Workload Type | Why |
|---|---|
| Development and test environments | Interruptions have no customer impact; up to 70% cost savings |
| Batch processing jobs | Jobs can be retried; ECS restarts interrupted tasks automatically |
| Queue workers (SQS, Kinesis) | Messages return to queue on interruption; natural retry mechanism |
| Data processing pipelines | Checkpointing allows resume from last state |
| CI/CD build tasks | Builds can be retried with minimal waste |

### Poor Fit (MUST NOT Use)

| Workload Type | Why |
|---|---|
| Latency-sensitive API endpoints | 2-minute interruption causes request failures and latency spikes |
| Singleton services (exactly-one-task) | Interruption causes complete outage until replacement starts |
| Long-running stateful tasks without checkpointing | Hours of work lost on interruption |
| Services with slow startup (>2 minutes) | Replacement task may not be ready before next interruption |

---

## Capacity Provider Strategy

The capacity provider strategy controls the mix of FARGATE (on-demand) and FARGATE_SPOT tasks.

### Strategy Parameters

| Parameter | Description |
|---|---|
| `base` | Minimum number of tasks that MUST run on this capacity provider. Only one provider in a strategy MAY have a non-zero base. |
| `weight` | Relative proportion of tasks placed on this provider after `base` is satisfied. |

### Recommended Pattern: On-Demand Base + Spot Overflow

Use `base` on FARGATE to guarantee a minimum number of always-available tasks, then `weight` on FARGATE_SPOT for cost-effective scaling.

### CLI Example

```bash
# Create service with mixed capacity provider strategy
aws ecs create-service \
  --cluster $CLUSTER \
  --service-name $SERVICE_NAME \
  --task-definition $TASK_DEFINITION \
  --desired-count 6 \
  --capacity-provider-strategy \
    capacityProvider=FARGATE,base=2,weight=1 \
    capacityProvider=FARGATE_SPOT,base=0,weight=3 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_1,$SUBNET_2],securityGroups=[$SECURITY_GROUP_ID]}" \
  --region $REGION \
  --output json
```

With this strategy and `desired-count=6`:

1. First 2 tasks run on FARGATE (base=2).
2. Remaining 4 tasks are split by weight ratio (1:3) → 1 on FARGATE, 3 on FARGATE_SPOT.
3. Result: 3 FARGATE + 3 FARGATE_SPOT.

### CDK Example

```typescript
import * as ecs from 'aws-cdk-lib/aws-ecs';

const service = new ecs.FargateService(this, 'Service', {
  cluster,
  taskDefinition: taskDef,
  desiredCount: 6,
  capacityProviderStrategies: [
    {
      capacityProvider: 'FARGATE',
      base: 2,
      weight: 1,
    },
    {
      capacityProvider: 'FARGATE_SPOT',
      weight: 3,
    },
  ],
});
```

### Updating an Existing Service

```bash
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE_NAME \
  --capacity-provider-strategy \
    capacityProvider=FARGATE,base=2,weight=1 \
    capacityProvider=FARGATE_SPOT,base=0,weight=3 \
  --region $REGION \
  --output json
```

> **Note**: When switching from `launchType: FARGATE` to a capacity provider strategy, operators MUST remove the `launchType` field and pass `--force-new-deployment`. A service MUST NOT have both `launchType` and `capacityProviderStrategy` set.

---

## Interruption Handling

When AWS reclaims Fargate Spot capacity, the following sequence occurs:

### Interruption Timeline

```
Time 0:00  ─── AWS sends SIGTERM to all containers in the task
                ECS fires a task state change event (stoppedReason: "Your Spot Task was interrupted.")
                
Time 0:00 to stopTimeout ─── Application performs graceful shutdown
                              (drain connections, flush buffers, save state)

Time stopTimeout ─── ECS sends SIGKILL — container is forcefully terminated
```

### Critical: stopTimeout Interaction

> **The container receives SIGKILL after `stopTimeout` seconds, NOT after 2 minutes.**

The 2-minute Spot interruption warning is the maximum time AWS guarantees between the SIGTERM and the task being forcefully removed. However, the container's `stopTimeout` setting controls when SIGKILL is sent:

| stopTimeout | Behavior |
|---|---|
| Not set (default 30s) | Container gets SIGTERM, then SIGKILL after 30 seconds — only 30s for graceful shutdown despite 2-minute warning |
| `120` (maximum) | Container gets SIGTERM, then SIGKILL after 120 seconds — full use of the 2-minute warning window |
| `60` | Container gets SIGTERM, then SIGKILL after 60 seconds — 60s for graceful shutdown |

Operators MUST set `stopTimeout` to match their application's graceful shutdown needs, up to a maximum of 120 seconds:

```json
{
  "containerDefinitions": [
    {
      "name": "app",
      "image": "$IMAGE_URI",
      "stopTimeout": 120,
      "essential": true
    }
  ]
}
```

### Application-Side SIGTERM Handling

Applications MUST handle SIGTERM to shut down gracefully:

```python
# Python example
import signal
import sys

def handle_sigterm(signum, frame):
    print("Received SIGTERM — starting graceful shutdown")
    # Drain connections, flush buffers, save checkpoint
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
```

```javascript
// Node.js example
process.on('SIGTERM', () => {
  console.log('Received SIGTERM — starting graceful shutdown');
  // Stop accepting new requests
  server.close(() => {
    // Flush buffers, save state
    cleanup().then(() => process.exit(0));
  });
});
```

### Monitoring Spot Interruptions

```bash
# Check for Spot interruption events in service events
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE_NAME \
  --region $REGION \
  --output json \
  --query 'services[0].events[:20]'
```

Operators SHOULD set up an EventBridge rule to capture Spot interruption events:

```bash
aws events put-rule \
  --name $RULE_NAME \
  --event-pattern '{
    "source": ["aws.ecs"],
    "detail-type": ["ECS Task State Change"],
    "detail": {
      "stoppedReason": ["Your Spot Task was interrupted."]
    }
  }' \
  --region $REGION \
  --output json
```

This enables alerting and tracking of interruption frequency to validate that the workload tolerates Spot well.
