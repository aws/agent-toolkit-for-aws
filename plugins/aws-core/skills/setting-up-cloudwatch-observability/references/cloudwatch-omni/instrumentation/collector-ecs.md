# OTel Collector on ECS

Read [collector.md](collector.md) first — it holds the destination choice, the config, and the
endpoint limits. This guide covers only the sidecar and how the application finds it.

The collector runs as a **sidecar container in the same task**. Under `awsvpc` networking all
containers in a task share a network namespace, so the app reaches it on `localhost:4318` with
no port mapping and no service discovery. This mirrors how the CloudWatch Agent sidecar works
in the Application Signals guides — same shape, different image and config.

## Step 1: Grant the task permissions

Two roles, two different reasons. Mixing them up is the most common failure here.

- **Task role** — the collector's runtime identity, needs
  `arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy`.
- **Execution role** — only needs `ssm:GetParameters`, and only if the config comes from
  Parameter Store (Step 2, option B). It is used to *fetch* the config before the container
  starts, not to send telemetry.

```hcl
resource "aws_iam_role_policy_attachment" "otel_collector" {
  role       = aws_iam_role.task_role.name      # task role, NOT execution role
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}
```

`CloudWatchAgentServerPolicy` is the grant for the destination — CloudWatch's own per-signal OTLP
endpoints.

A collector that starts cleanly and then logs `AccessDenied` on every export is this policy on
the wrong role.

## Step 2: Add the sidecar container

### Primary: the CloudWatch Agent sidecar

Image `public.ecr.aws/cloudwatch-agent/cloudwatch-agent:<tag>`, pinned to **1.300070.0b1586 or later**
(tags carry no `v` prefix and always carry a `b####` build suffix — there is no `v1.300070.1` tag)
for the `opentelemetry` section. Do not float `:latest`, and do not assume a tag is new enough: an
older agent reports `configstatus: configured` and `status: running` while starting no OTLP
listener at all. Confirm from the task's log stream that the collector
logged its `traces`/`metrics` pipelines before believing it works. The whole config goes in `CW_CONFIG_CONTENT`, so no custom
image and no SSM parameter are required:

```hcl
{
  name              = "cloudwatch-agent"
  image             = "public.ecr.aws/cloudwatch-agent/cloudwatch-agent:1.300072.0b1766"
  essential         = false
  cpu               = 64
  memoryReservation = 128
  environment = [{
    name  = "CW_CONFIG_CONTENT"
    value = jsonencode({
      agent         = { region = var.region }
      opentelemetry = { collect = { otlp = {
        grpc_endpoint = "0.0.0.0:4317"
        http_endpoint = "0.0.0.0:4318"
      } } }
    })
  }]
  logConfiguration = {
    logDriver = "awslogs"
    options = {
      "awslogs-group"         = aws_cloudwatch_log_group.otel_collector.name
      "awslogs-region"        = var.region
      "awslogs-stream-prefix" = "cwagent"
    }
  }

}
```

`jsonencode` avoids the heredoc indentation hazard entirely — there is no YAML to mis-indent. Do
**not** add any `application_signals` section; that is out of scope here.

**The snippet above references a log group you must declare.** Give the collector its own, so a
failing collector is not invisible:

```hcl
resource "aws_cloudwatch_log_group" "otel_collector" {
  name              = "/ecs/${var.service_name}-collector"
  retention_in_days = 7
}
```

The **execution** role needs `logs:CreateLogStream` / `logs:PutLogEvents` on it — unless it already
carries `AmazonECSTaskExecutionRolePolicy`, which grants both on `*` and is the common case for an
existing ECS stack. Check before adding an inline policy. (CDK's `LogDrivers.awsLogs()` adds the
grant itself, which is why it shows up as an execution-role change in `cdk diff`.)

Also check the **task-level** `cpu`/`memory`: the init container and the collector are added inside
the existing envelope, and a 256/512 task leaves too little for a real app. 512/1024 is the practical
floor; 1024/2048 is comfortable for a small app plus init container plus collector. On Fargate the pair
must remain one of the valid combinations, so a naive bump fails at deploy time.

**The same sidecar in CDK TypeScript.** The ECS language guides are written in CDK, so most readers
need this form rather than the HCL above:

```typescript
// Assumes the usual imports: aws-ecs as ecs, aws-iam as iam, aws-logs as logs, aws-cdk-lib as cdk.
// `serviceName` and `taskDefinition` are whatever the surrounding stack already calls them.
const collectorLogGroup = new logs.LogGroup(this, 'CollectorLogGroup', {
  logGroupName: `/ecs/${serviceName}-collector`,
  retention: logs.RetentionDays.ONE_WEEK,
  // REQUIRED with a fixed logGroupName. CDK defaults LogGroup removal to RETAIN, so deleting the
  // stack orphans the group -- and the next deploy then fails with "already exists".
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});

taskDefinition.addContainer('cloudwatch-agent', {
  image: ecs.ContainerImage.fromRegistry(
    'public.ecr.aws/cloudwatch-agent/cloudwatch-agent:1.300072.0b1766'),
  essential: false,
  cpu: 64,
  memoryReservationMiB: 128,          // NOTE: renamed from HCL's `memoryReservation`
  environment: {                       // NOTE: a map, not HCL's list of {name, value}
    CW_CONFIG_CONTENT: JSON.stringify({
      agent: { region: this.region },
      opentelemetry: { collect: { otlp: {
        grpc_endpoint: '0.0.0.0:4317',
        http_endpoint: '0.0.0.0:4318',
      } } },
    }),
  },
  logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'cwagent', logGroup: collectorLogGroup }),
});

taskDefinition.taskRole.addManagedPolicy(
  iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy'));
```

`JSON.stringify` is the CDK equivalent of `jsonencode` and sidesteps the indentation hazard the same
way. Two traps in a verbatim HCL→CDK port: `memoryReservation` becomes `memoryReservationMiB`, and
`environment` becomes an object rather than a list of name/value pairs. Also add the collector
**last**, or at least after the app container — CDK's `defaultContainer` (what a load-balancer target
binds to) is the first *essential* container added.

### Backup: upstream otelcol-contrib sidecar

Image: `otel/opentelemetry-collector-contrib:<version>` — the upstream **contrib** distribution
(`sigv4auth` is a contrib component; the core image fails at startup without it). Pin a version from
[the releases page](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/latest);
do not float `latest`.

Upstream reads its config from a file or from an environment variable via `--config=env:VAR`, so
**no custom image is needed** — put the YAML in a variable and point `command` at it.

**Option A — inline config** (simplest; the config is visible in the task definition):

```hcl
{
  name              = "otel-collector"
  image             = "otel/opentelemetry-collector-contrib:<version>"
  command           = ["--config=env:OTEL_CONFIG_YAML"]
  essential         = false
  cpu               = 64
  memoryReservation = 128
  environment = [{
    name  = "OTEL_CONFIG_YAML"
    value = <<-YAML
      receivers:
        otlp:
          protocols:
            grpc:                 # both protocols: Java defaults to gRPC/4317
              endpoint: 0.0.0.0:4317
            http:
              endpoint: 0.0.0.0:4318
      processors:
        batch:
          send_batch_size: 200
          timeout: 10s
      exporters:
        otlphttp/traces:
          traces_endpoint: https://xray.${var.region}.amazonaws.com/v1/traces
          compression: gzip
          auth:
            authenticator: sigv4auth/traces
        otlphttp/metrics:
          metrics_endpoint: https://monitoring.${var.region}.amazonaws.com/v1/metrics
          compression: gzip
          auth:
            authenticator: sigv4auth/metrics
      extensions:
        sigv4auth/traces:
          region: "${var.region}"
          service: "xray"
        sigv4auth/metrics:
          region: "${var.region}"
          service: "monitoring"
      service:
        extensions: [sigv4auth/traces, sigv4auth/metrics]
        pipelines:
          traces:
            receivers: [otlp]
            processors: [batch]
            exporters: [otlphttp/traces]
          metrics:
            receivers: [otlp]
            processors: [batch]
            exporters: [otlphttp/metrics]
    YAML
  }]
  logConfiguration = {
    logDriver = "awslogs"
    options = {
      "awslogs-group"         = aws_cloudwatch_log_group.otel_collector.name
      "awslogs-region"        = var.region
      "awslogs-stream-prefix" = "otel"
    }
  }
}
```

**Option B — config in SSM Parameter Store** (keeps the task definition small, lets the config
change without a new task revision):

```hcl
secrets = [{
  name      = "OTEL_CONFIG_YAML"
  valueFrom = aws_ssm_parameter.otel_config.arn
}]
```

`essential = false` matters: the collector is not the workload, and an essential container
exiting kills the whole task.

Give the collector a log group of its own — without one, a failing collector is invisible.

**Do not add `dependsOn`.** The SDK retries, so the app can start first. A `dependsOn` with
condition `HEALTHY` would additionally require a `healthCheck` on the collector container, and
without one the task never starts at all.

## Step 3: Point the application at the collector

On the **application** container, alongside the loader variable the `ecs-*.md` instrumentation
guides add:

```hcl
environment = [
  # ... existing, including the language's loader variable ...
  { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
  { name = "OTEL_EXPORTER_OTLP_PROTOCOL", value = "http/protobuf" },
]
```

`localhost` is correct **only under `awsvpc`**. If the task uses `bridge` networking, the
containers do not share a namespace — add a `links` entry from the app to the collector and
address it by the collector's **container name** instead — `http://cloudwatch-agent:4318` on the primary path, `http://otel-collector:4318` on the backup — and use that same name in `links`. Check
`network_mode` before writing `localhost`; Fargate is always `awsvpc`.

`OTEL_EXPORTER_OTLP_PROTOCOL` is not optional — see
[collector.md](collector.md#step-4-wire-the-app-to-the-collector).

## Verify

```bash
aws ecs describe-tasks --cluster <cluster> --tasks <task-arn> \
  --query 'tasks[0].containers[].{name:name,status:lastStatus,exit:exitCode}'
```

The collector container — `cloudwatch-agent` on the primary path, `otel-collector` on the backup —
should be `RUNNING` alongside the app, and the `init` container `STOPPED` with exit code 0.

**Check you are reading the new revision.** An apply that changes only *service* properties does not
recycle running tasks, so confirm the task's `taskDefinitionArn` is the revision you just created
and the old deployment has drained before drawing conclusions from logs.

**`collector.md`'s `curl` checks on 4318 and 8888 are not reachable on Fargate** — no host shell, and
no route into the task's network namespace unless you add `enableExecuteCommand` plus
`ssmmessages:*` on the task role. The log stream below is the ECS substitute, and it is sufficient.

Then read its log stream:
startup lines listing the `traces` and `metrics` pipelines mean the config parsed; `403`,
`AccessDenied`, or `no such host` mean it did not reach the destination.

| Symptom | Cause |
|---|---|
| Collector container `STOPPED` immediately | Malformed config YAML — indentation is the usual culprit. Note the HCL `<<-YAML` heredoc strips leading indentation; a CDK TypeScript template literal does **not**, so a verbatim port produces invalid YAML |
| Collector exits with `unknown extension "sigv4auth"` | Core image instead of `-contrib` |
| Task won't start, collector never pulls | Execution role missing `ssm:GetParameters` (option B) |
| Collector runs, every export `403` | **Read the 403's `Message=` body first.** If it names the principal and a denied action, the policy is on the execution role instead of the task role. If it describes account enablement instead, IAM is fine and no policy change will help |
| App can't connect to `localhost:4318` | Task is `bridge`, not `awsvpc` |
| Metrics arrive, spans do not | Transaction Search not enabled on the account |

## Completion

Tell the user the sidecar was added to the task definition, which role got which policy and
why, that the app now exports to `localhost:4318`, and that no application source or Dockerfile
changed. Present the diff; do not deploy or update the service.
