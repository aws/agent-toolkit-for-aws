# ECS Logging

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [awslogs Driver](#awslogs-driver)
- [Blocking vs Non-Blocking Mode](#blocking-vs-non-blocking-mode)
- [Multiline Logs](#multiline-logs)
- [FireLens / Fluent Bit Setup](#firelens--fluent-bit-setup)
- [When to Use Which](#when-to-use-which)

---

## Verify Dependencies

| Dependency | Check Command |
|---|---|
| Execution role has log permissions | Execution role MUST have `logs:CreateLogStream` and `logs:PutLogEvents` |

---

## awslogs Driver

The `awslogs` driver sends container stdout/stderr directly to CloudWatch Logs.

### Required and Optional Options

| Option | Required | Default | Description |
|---|---|---|---|
| `awslogs-group` | Yes | — | CloudWatch Logs log group name |
| `awslogs-region` | Yes | — | Region for the log group. Required for all launch types. |
| `awslogs-stream-prefix` | Yes (Fargate) | — | Prefix for log stream names. Required for Fargate, optional for EC2. Stream format: `$PREFIX/$CONTAINER_NAME/$TASK_ID` |
| `awslogs-create-group` | No | `false` | Auto-create the log group if it does not exist. Execution role MUST have `logs:CreateLogGroup` permission. |
| `mode` | No | `non-blocking` (ECS service default; overridable via `defaultLogDriverMode` account setting) | `blocking` or `non-blocking`. See [Blocking vs Non-Blocking Mode](#blocking-vs-non-blocking-mode). |
| `max-buffer-size` | No | `10m` | Buffer size for non-blocking mode. Only applies when `mode` is `non-blocking`. |

### CLI Example

```bash
aws ecs register-task-definition \
  --family $TASK_FAMILY \
  --network-mode awsvpc \
  --requires-compatibilities FARGATE \
  --cpu 512 \
  --memory 1024 \
  --execution-role-arn $EXECUTION_ROLE_ARN \
  --container-definitions '[
    {
      "name": "app",
      "image": "'$IMAGE_URI'",
      "essential": true,
      "portMappings": [{"containerPort": '$CONTAINER_PORT'}],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "'$LOG_GROUP'",
          "awslogs-region": "'$REGION'",
          "awslogs-stream-prefix": "app",
          "mode": "blocking"
        }
      }
    }
  ]' \
  --region $REGION \
  --output json
```

---

## Blocking vs Non-Blocking Mode

> **IMPORTANT**: ECS defaults to `non-blocking` log driver mode, which silently drops logs when the buffer fills (per [API_LogConfiguration.html](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_LogConfiguration.html)). The [`defaultLogDriverMode`](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-account-settings.html#default-log-driver-mode) account setting can override this per account. For guaranteed log delivery, explicitly set `"mode": "blocking"` in `logConfiguration.options`.

### Behavior Comparison

| Aspect | `blocking` | `non-blocking` |
|---|---|---|
| **Delivery guarantee** | All logs delivered | Logs MAY be dropped when buffer fills |
| **Application impact** | Application pauses if CloudWatch is slow/unavailable | Application continues; logs silently dropped |
| **Buffer** | No buffer — writes are synchronous | Ring buffer (`max-buffer-size`, default 10m) |
| **Default (ECS service)** | No | Yes — logs may be dropped when buffer fills |
| **Explicit `blocking`** | Yes — app may stall if CloudWatch is slow | No |

### Recommendation

Operators MUST set `mode` to `blocking` when log completeness is required:

- Audit trails
- Financial transaction logs
- Security event logs
- Debugging intermittent failures

Operators MAY use `non-blocking` mode when:

- Application availability is more important than log completeness
- High-throughput logging would cause backpressure issues
- Logs are supplementary (metrics are the primary observability signal)

### Setting Blocking Mode Explicitly

Because the default changed, operators MUST explicitly set `mode: blocking` in all task definitions where guaranteed log delivery is required. Do NOT rely on the default.

```json
"logConfiguration": {
  "logDriver": "awslogs",
  "options": {
    "awslogs-group": "$LOG_GROUP",
    "awslogs-region": "$REGION",
    "awslogs-stream-prefix": "app",
    "mode": "blocking"
  }
}
```

### Non-Blocking Buffer Tuning

When using non-blocking mode, operators SHOULD tune `max-buffer-size` based on log volume:

- Default `10m` is sufficient for low-throughput services.
- High-throughput services SHOULD increase to `25m` or higher (AWS uses `25m` in its [FireLens example](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/firelens-taskdef.html)).
- When logs are dropped in non-blocking mode, they are silently lost — there is no built-in CloudWatch metric for dropped logs. Monitor `IncomingLogEvents` and compare against expected application log volume to detect gaps.

---

## Multiline Logs

Stack traces and multi-line log entries are split across multiple CloudWatch log events by default. Use these options to group them:

### awslogs-datetime-format

Matches the timestamp at the start of each log entry. Lines without a matching timestamp are appended to the previous entry.

```json
"logConfiguration": {
  "logDriver": "awslogs",
  "options": {
    "awslogs-group": "$LOG_GROUP",
    "awslogs-region": "$REGION",
    "awslogs-stream-prefix": "app",
    "awslogs-datetime-format": "%Y-%m-%d %H:%M:%S",
    "mode": "blocking"
  }
}
```

Common datetime patterns:

| Pattern | Matches |
|---|---|
| `%Y-%m-%d %H:%M:%S` | `2026-04-26 14:30:00` |
| `%Y-%m-%dT%H:%M:%S` | `2026-04-26T14:30:00` |
| `%d/%b/%Y:%H:%M:%S` | `26/Apr/2026:14:30:00` (Apache) |
| `\\[%Y-%m-%d %H:%M:%S` | `[2026-04-26 14:30:00` (bracketed) |

### awslogs-multiline-pattern

A regex pattern that matches the start of a new log entry. More flexible than `awslogs-datetime-format` but MUST NOT be used together with it.

```json
"logConfiguration": {
  "logDriver": "awslogs",
  "options": {
    "awslogs-group": "$LOG_GROUP",
    "awslogs-region": "$REGION",
    "awslogs-stream-prefix": "app",
    "awslogs-multiline-pattern": "^(INFO|WARN|ERROR|DEBUG|FATAL)",
    "mode": "blocking"
  }
}
```

- `awslogs-datetime-format` and `awslogs-multiline-pattern` MUST NOT be used together. If both are set, `awslogs-datetime-format` takes precedence and `awslogs-multiline-pattern` is ignored.
- Operators SHOULD prefer `awslogs-datetime-format` when log entries start with a timestamp.

---

## FireLens / Fluent Bit Setup

FireLens routes container logs through a Fluent Bit (or Fluentd) sidecar, enabling delivery to multiple destinations (CloudWatch, S3, Elasticsearch, Datadog, etc.).

### Architecture

```
┌─────────────┐     stdout/stderr     ┌──────────────┐     ┌─────────────────┐
│ App Container│ ──────────────────── │ Log Router   │ ──► │ CloudWatch Logs  │
│ (awsfirelens)│                      │ (Fluent Bit) │ ──► │ S3              │
└─────────────┘                       │ (awslogs)    │ ──► │ Elasticsearch   │
                                      └──────────────┘     └─────────────────┘
```

### Task Definition Structure

```json
{
  "family": "$TASK_FAMILY",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "$EXECUTION_ROLE_ARN",
  "taskRoleArn": "$TASK_ROLE_ARN",
  "containerDefinitions": [
    {
      "name": "log-router",
      "image": "public.ecr.aws/aws-observability/aws-for-fluent-bit:3",
      "essential": true,
      "firelensConfiguration": {
        "type": "fluentbit"
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "$LOG_GROUP",
          "awslogs-region": "$REGION",
          "awslogs-stream-prefix": "firelens",
          "mode": "blocking"
        }
      }
    },
    {
      "name": "app",
      "image": "$IMAGE_URI",
      "essential": true,
      "portMappings": [{"containerPort": $CONTAINER_PORT}],
      "logConfiguration": {
        "logDriver": "awsfirelens",
        "options": {
          "Name": "cloudwatch_logs",
          "region": "$REGION",
          "log_group_name": "$LOG_GROUP",
          "log_stream_prefix": "app/",
          "auto_create_group": "true"
        }
      }
    }
  ]
}
```

### Critical Rules

1. The log router container SHOULD have `"essential": true` ([AWS recommendation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/firelens-taskdef.html)). If the log router crashes and is not essential, the task continues running but **all logs are silently lost**.

2. The log router SHOULD use `awslogs` for its own logs, NOT `awsfirelens`. All [AWS examples](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/firelens-taskdef.html) follow this pattern. Using `awsfirelens` on the log router would route its own logs through itself, which can prevent the task from starting.

3. The application container uses `awsfirelens` as its log driver to route logs through the FireLens sidecar.

4. The task role (not execution role) MUST have permissions for the destination services (CloudWatch Logs, S3, Kinesis, etc.) because Fluent Bit runs as the task role.

---

## Security Considerations

- CloudWatch Logs log groups SHOULD be encrypted with a KMS key for sensitive workloads (audit, financial, security logs). Use `aws logs associate-kms-key --log-group-name $LOG_GROUP --kms-key-id $KMS_KEY_ARN`.
- Containers may log sensitive data (credentials, tokens, PII) to stdout/stderr. Consider [CloudWatch Logs data protection policies](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/cloudwatch-logs-data-protection.html) to detect and mask sensitive patterns.
- Scope IAM log permissions to specific log group ARNs instead of `Resource: "*"` where possible.
- FireLens listens on port `24224`. Do NOT allow inbound traffic on this port in the task's security group to prevent external access to the log router.

---

## When to Use Which

| Scenario | Recommended Driver | Reason |
|---|---|---|
| CloudWatch Logs only, simple setup | `awslogs` | Simplest configuration, no sidecar overhead |
| Multiple log destinations | FireLens (`awsfirelens`) | Route to CloudWatch + S3 + third-party simultaneously |
| Log transformation/filtering needed | FireLens (`awsfirelens`) | Fluent Bit supports parsing, filtering, enrichment |
| Minimal resource overhead | `awslogs` | No sidecar container consuming CPU/memory |
| Third-party log aggregator (Datadog, Splunk) | FireLens (`awsfirelens`) | Native output plugins for third-party services |
| Compliance requiring guaranteed delivery | `awslogs` with `mode: blocking` | Simplest path to guaranteed delivery |
