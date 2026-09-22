# Instrument a Node.js Application on Amazon ECS with ADOT

Wire the ADOT Node.js auto-instrumentation SDK into an ECS task definition (Fargate or EC2 launch type). An init container copies the SDK into a shared volume at task startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-ecs.md](collector-ecs.md).

## Prerequisites

- An existing ECS service running a Node.js application
- The task definition available to edit — as CDK, Terraform, CloudFormation, or raw JSON

## Critical Requirements

**Do NOT:**

- Add a CloudWatch Agent sidecar container, or any collector sidecar — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), where the CloudWatch Agent sidecar is the primary collector
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Set `OTEL_AWS_APPLICATION_SIGNALS_*`, `OTEL_AWS_SERVICE_EVENTS_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the task role — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), which requires `CloudWatchAgentServerPolicy` on the **task** role
- Run `cdk deploy`, `terraform apply`, or `aws ecs update-service` automatically
- Modify `server.js` or any other application source file

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The task may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ecs.md](collector-ecs.md)), the collector is what gets the IAM — the workload still gets none.

## Determine the module format first

The `NODE_OPTIONS` value differs between CommonJS and ESM. Check `package.json`:

- `"type": "module"` → **ESM**
- `"type": "commonjs"` or no `type` field → **CommonJS** (default)

If the project uses `import` syntax in its entrypoint without `"type": "module"`, ask the user rather than guessing.

## Step 1: Add a shared volume to the task definition

```typescript
const taskDefinition = new ecs.FargateTaskDefinition(this, '<Service>TaskDefinition', {
  // ... existing configuration unchanged ...
  volumes: [
    { name: 'opentelemetry-auto-instrumentation-node' },
  ],
});
```

A bind mount (a volume with only a `name`) is all that is needed — no EFS, no host path.

## Step 2: Add the ADOT init container

```typescript
const initContainer = taskDefinition.addContainer('init', {
  // Look up the latest tag — see instrumentation.md
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0'),
  essential: false,
  memoryReservationMiB: 64,
  cpu: 32,
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-node'],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'init-<service>',
    logGroup: serviceLogGroup,
  }),
});

initContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-node',
  containerPath: '/otel-auto-instrumentation-node',
  readOnly: false,
});
```

`essential: false` matters — the init container exits after the copy, and an essential container exiting would stop the whole task.

## Step 3: Configure the application container

```typescript
const mainContainer = taskDefinition.addContainer('<service>-container', {
  // ... existing image, ports, health check unchanged ...
  environment: {
    // ... existing environment variables preserved ...

    // CommonJS. For ESM, see the note below.
    NODE_OPTIONS: '--require /otel-auto-instrumentation-node/autoinstrumentation.js',
    OTEL_SERVICE_NAME: '<service>',
  },
});

mainContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-node',
  containerPath: '/otel-auto-instrumentation-node',
  readOnly: false,
});
```

**For ESM applications**, replace the `NODE_OPTIONS` value with:

```
--import /otel-auto-instrumentation-node/autoinstrumentation.js --experimental-loader=/otel-auto-instrumentation-node/node_modules/@opentelemetry/instrumentation/hook.mjs
```

Set `OTEL_SERVICE_NAME` from the existing ECS service or container name. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

## Step 4: Make the application wait for the init container

```typescript
mainContainer.addContainerDependencies({
  container: initContainer,
  condition: ecs.ContainerDependencyCondition.SUCCESS,
});
```

Without this, the application can start before the SDK finishes copying and `NODE_OPTIONS` will point at a file that does not exist yet.

## Raw task definition JSON

If the task definition is managed as JSON (or through Terraform's `container_definitions`), the same four pieces are:

**Terraform note:** in `aws_ecs_task_definition`, `container_definitions` is `jsonencode` of **only
the containers array** — `volumes` is a sibling HCL block, not a key inside that JSON. Pasting the
whole object below into `jsonencode(...)` silently drops the volume, after which every mount path is
missing and the app starts uninstrumented:

```hcl
resource "aws_ecs_task_definition" "app" {
  # ...
  volume { name = "opentelemetry-auto-instrumentation-<lang>" }
  container_definitions = jsonencode([ /* the containers array only */ ])
}
```

```json
{
  "volumes": [{ "name": "opentelemetry-auto-instrumentation-node" }],
  "containerDefinitions": [
    {
      "name": "init",
      "image": "public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0",
      "essential": false,
      "command": ["cp", "-a", "/autoinstrumentation/.", "/otel-auto-instrumentation-node"],
      "mountPoints": [
        { "sourceVolume": "opentelemetry-auto-instrumentation-node", "containerPath": "/otel-auto-instrumentation-node", "readOnly": false }
      ]
    },
    {
      "name": "<service>-container",
      "environment": [
        { "name": "NODE_OPTIONS", "value": "--require /otel-auto-instrumentation-node/autoinstrumentation.js" },
        { "name": "OTEL_SERVICE_NAME", "value": "<service>" }
      ],
      "mountPoints": [
        { "sourceVolume": "opentelemetry-auto-instrumentation-node", "containerPath": "/otel-auto-instrumentation-node", "readOnly": false }
      ],
      "dependsOn": [{ "containerName": "init", "condition": "SUCCESS" }]
    }
  ]
}
```

## Verify

After the user deploys and tasks recycle:

```bash
# The init container should have exited 0
aws ecs describe-tasks --cluster <cluster> --tasks <task-arn> \
  --query 'tasks[0].containers[?name==`init`].[name,lastStatus,exitCode]'
```

Then check the application container's CloudWatch Logs for the literal string `AWS Distro of OpenTelemetry automatic instrumentation started successfully` — **not** a bare `-i opentelemetry`, which also matches the benign `@aws/aws-distro-opentelemetry-instrumentation-vercel-ai Failed to register VercelAISpanProcessor` line a healthy start always emits. Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT Node.js auto-instrumentation into your ECS task definition.

**Changes:**

- Added a bind mount volume, `opentelemetry-auto-instrumentation-node`
- Added a non-essential `init` container that copies the ADOT Node.js SDK into that volume
- Added `NODE_OPTIONS` (module format: CommonJS/ESM) and `OTEL_SERVICE_NAME` to the application container, plus the volume mount and a `SUCCESS` dependency on `init`

**Not changed:** your application image, your application source, the task role's IAM policies, and the service's sidecars — no CloudWatch Agent or collector was added.

**Next steps:**

1. Review the diff.
2. Deploy and let the tasks recycle.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ecs.md](collector-ecs.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
