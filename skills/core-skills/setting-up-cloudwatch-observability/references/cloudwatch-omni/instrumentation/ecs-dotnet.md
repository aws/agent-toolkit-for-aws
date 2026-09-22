# Instrument a .NET Application on Amazon ECS with ADOT

Wire the ADOT .NET auto-instrumentation SDK into an ECS task definition (Fargate or EC2 launch type). An init container copies the SDK into a shared volume at task startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-ecs.md](collector-ecs.md).

## Prerequisites

- An existing ECS service running a .NET application
- The task definition available to edit — as CDK, Terraform, CloudFormation, or raw JSON
- Whether the task runs **Linux** or **Windows Server** containers (the paths and the copy command differ)

## Critical Requirements

**Do NOT:**

- Add a CloudWatch Agent sidecar container, or any collector sidecar — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), where the CloudWatch Agent sidecar is the primary collector
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Set `OTEL_AWS_APPLICATION_SIGNALS_*`, `OTEL_AWS_SERVICE_EVENTS_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the task role — **unless you are also deploying a collector** ([collector-ecs.md](collector-ecs.md)), which requires `CloudWatchAgentServerPolicy` on the **task** role
- Run `cdk deploy`, `terraform apply`, or `aws ecs update-service` automatically
- Modify the application's `.cs` files or its `.csproj`

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The task may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ecs.md](collector-ecs.md)), the collector is what gets the IAM — the workload still gets none.

## Step 1: Add a shared volume to the task definition

```typescript
const taskDefinition = new ecs.FargateTaskDefinition(this, '<Service>TaskDefinition', {
  // ... existing configuration unchanged ...
  volumes: [
    { name: 'opentelemetry-auto-instrumentation-dotnet' },
  ],
});
```

A bind mount (a volume with only a `name`) is all that is needed — no EFS, no host path.

## Step 2: Add the ADOT init container

### Linux containers

```typescript
const initContainer = taskDefinition.addContainer('init', {
  // Look up the latest tag — see instrumentation.md
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet:v1.15.0'),
  essential: false,
  memoryReservationMiB: 64,
  cpu: 32,
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-dotnet'],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'init-<service>',
    logGroup: serviceLogGroup,
  }),
});

initContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-dotnet',
  containerPath: '/otel-auto-instrumentation-dotnet',
  readOnly: false,
});
```

### Windows Server containers

```typescript
const initContainer = taskDefinition.addContainer('init', {
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet:v1.15.0'),
  essential: false,
  memoryReservationMiB: 64,
  cpu: 32,
  command: ['CMD', '/c', 'xcopy', '/e', 'C:\\autoinstrumentation\\*', 'C:\\otel-auto-instrumentation', '&&', 'icacls', 'C:\\otel-auto-instrumentation', '/grant', '*S-1-1-0:R', '/T'],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'init-<service>',
    logGroup: serviceLogGroup,
  }),
});

initContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-dotnet',
  containerPath: 'C:\\otel-auto-instrumentation',
  readOnly: false,
});
```

`essential: false` matters — the init container exits after the copy, and an essential container exiting would stop the whole task.

## Step 3: Configure the application container

.NET needs the most environment variables of any language, because the CoreCLR profiler is loaded by the runtime at process start and reads its configuration entirely from the environment.

**Four of them are what actually attach the profiler** — omit any one and the app starts normally with no instrumentation and no error: `CORECLR_ENABLE_PROFILING`, `CORECLR_PROFILER`, `CORECLR_PROFILER_PATH`, `DOTNET_STARTUP_HOOKS`. `OTEL_DOTNET_AUTO_HOME` and `OTEL_DOTNET_AUTO_PLUGINS` select the ADOT distro's behaviour.

`DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` are set for parity with the distro's own `instrument.sh`, but the `AdditionalDeps/` and `store/` directories **do not exist in the container image** (they ship only in the tarball). Instrumentation works with both paths dangling, so do not treat them as evidence of a broken install when auditing paths.

### Linux containers

```typescript
const mainContainer = taskDefinition.addContainer('<service>-container', {
  // ... existing image, ports, health check unchanged ...
  environment: {
    // ... existing environment variables preserved ...

    // CoreCLR profiler — all four are required for the profiler to attach
    CORECLR_ENABLE_PROFILING: '1',
    CORECLR_PROFILER: '{918728DD-259F-4A6A-AC2B-B85E1B658318}',
    CORECLR_PROFILER_PATH: '/otel-auto-instrumentation-dotnet/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so',
    DOTNET_STARTUP_HOOKS: '/otel-auto-instrumentation-dotnet/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll',
    // SDK locations
    DOTNET_ADDITIONAL_DEPS: '/otel-auto-instrumentation-dotnet/AdditionalDeps',
    DOTNET_SHARED_STORE: '/otel-auto-instrumentation-dotnet/store',
    OTEL_DOTNET_AUTO_HOME: '/otel-auto-instrumentation-dotnet',
    OTEL_DOTNET_AUTO_PLUGINS: 'AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation',
    OTEL_SERVICE_NAME: '<service>',
  },
});

mainContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-dotnet',
  containerPath: '/otel-auto-instrumentation-dotnet',
  readOnly: false,
});
```

`CORECLR_PROFILER_PATH` depends on **two** things, and none of this guide's other checks catch getting it wrong — a bad path means the profiler silently does not attach:

- **Architecture**, from the task: `linux-x64` for X86_64, `linux-arm64` for ARM64 (Graviton). Check `runtimePlatform.cpuArchitecture`; Fargate defaults to X86_64 when it is unset.
- **libc, from the application's base image** — not the task. `linux-<arch>` for glibc bases (`mcr.microsoft.com/dotnet/aspnet:*`, Debian, Ubuntu); **`linux-musl-<arch>` for Alpine bases.**

The amd64 image ships `linux-x64` **and** `linux-musl-x64`, and no `linux-arm64` — so on X86_64 the choice is entirely about the image's libc. If you are unsure, list what the image actually shipped rather than inferring it.

### Windows Server containers

Same variables, with Windows paths and the native DLL instead of the shared object:

```typescript
environment: {
  // ... existing environment variables preserved ...

  CORECLR_ENABLE_PROFILING: '1',
  CORECLR_PROFILER: '{918728DD-259F-4A6A-AC2B-B85E1B658318}',
  CORECLR_PROFILER_PATH: 'C:\\otel-auto-instrumentation\\win-x64\\OpenTelemetry.AutoInstrumentation.Native.dll',
  DOTNET_STARTUP_HOOKS: 'C:\\otel-auto-instrumentation\\net\\OpenTelemetry.AutoInstrumentation.StartupHook.dll',
  DOTNET_ADDITIONAL_DEPS: 'C:\\otel-auto-instrumentation\\AdditionalDeps',
  DOTNET_SHARED_STORE: 'C:\\otel-auto-instrumentation\\store',
  OTEL_DOTNET_AUTO_HOME: 'C:\\otel-auto-instrumentation',
  OTEL_DOTNET_AUTO_PLUGINS: 'AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation',
  OTEL_SERVICE_NAME: '<service>',
},
```

Mount the volume at `C:\otel-auto-instrumentation` on the application container as well.

Set `OTEL_SERVICE_NAME` from the existing ECS service or container name. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

## Step 4: Make the application wait for the init container

```typescript
mainContainer.addContainerDependencies({
  container: initContainer,
  condition: ecs.ContainerDependencyCondition.SUCCESS,
});
```

Without this, the application can start before the SDK finishes copying and the profiler paths will point at files that do not exist yet.

## Raw task definition JSON

If the task definition is managed as JSON (or through Terraform's `container_definitions`), the same four pieces, Linux shown, are:

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
  "volumes": [{ "name": "opentelemetry-auto-instrumentation-dotnet" }],
  "containerDefinitions": [
    {
      "name": "init",
      "image": "public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet:v1.15.0",
      "essential": false,
      "command": ["cp", "-a", "/autoinstrumentation/.", "/otel-auto-instrumentation-dotnet"],
      "mountPoints": [
        { "sourceVolume": "opentelemetry-auto-instrumentation-dotnet", "containerPath": "/otel-auto-instrumentation-dotnet", "readOnly": false }
      ]
    },
    {
      "name": "<service>-container",
      "environment": [
        { "name": "CORECLR_ENABLE_PROFILING", "value": "1" },
        { "name": "CORECLR_PROFILER", "value": "{918728DD-259F-4A6A-AC2B-B85E1B658318}" },
        { "name": "CORECLR_PROFILER_PATH", "value": "/otel-auto-instrumentation-dotnet/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so" },
        { "name": "DOTNET_STARTUP_HOOKS", "value": "/otel-auto-instrumentation-dotnet/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll" },
        { "name": "DOTNET_ADDITIONAL_DEPS", "value": "/otel-auto-instrumentation-dotnet/AdditionalDeps" },
        { "name": "DOTNET_SHARED_STORE", "value": "/otel-auto-instrumentation-dotnet/store" },
        { "name": "OTEL_DOTNET_AUTO_HOME", "value": "/otel-auto-instrumentation-dotnet" },
        { "name": "OTEL_DOTNET_AUTO_PLUGINS", "value": "AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation" },
        { "name": "OTEL_SERVICE_NAME", "value": "<service>" }
      ],
      "mountPoints": [
        { "sourceVolume": "opentelemetry-auto-instrumentation-dotnet", "containerPath": "/otel-auto-instrumentation-dotnet", "readOnly": false }
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

**Do not check the application container's log for OpenTelemetry startup lines** — ADOT .NET writes
none there at the default level: a fully working task logs nothing matching
`opentelemetry|otlp|exporter`, and the init
container's log stream is empty because `cp -a` is silent. Judge init by `exitCode: 0`, not content.

The check that matters for .NET is that every CoreCLR variable reached the running process and each
path it names exists — if one is missing or wrong, the profiler does not attach and the application
starts normally with no instrumentation and no error. On Fargate that needs ECS Exec
(`enableExecuteCommand` plus `ssmmessages:*Channel` on the task role), which is a verification-only
addition — say so if you add it:

```bash
aws ecs execute-command --cluster <cluster> --task <task-arn> --container <app> --interactive \
  --command "sh -c 'tr \"\\0\" \"\\n\" < /proc/1/environ | grep -E \"^(CORECLR|DOTNET_|OTEL_)\" | sort'"
```

The SDK also writes its own log at the default level —
`/tmp/otel-dotnet-auto-<pid>-<App>-Managed-<date>.log`, carrying
`The profiler has been initialized with NN direct definitions` — but that file lives in the task's
filesystem and is never sent to the awslogs stream, so on Fargate it needs ECS Exec **too**. It is
not a fallback for not having Exec.

Without ECS Exec, the honest position is that there is no local verification on Fargate: rely on
`init` exit code 0, the task definition diff, and — once a destination exists — spans arriving.

Note `DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` name directories that are **not shipped in
the container image**; both dangle on a working deployment and are not the fault.

Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that
is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT .NET auto-instrumentation into your ECS task definition.

**Changes:**

- Added a bind mount volume, `opentelemetry-auto-instrumentation-dotnet`
- Added a non-essential `init` container that copies the ADOT .NET SDK into that volume
- Added the CoreCLR profiler variables, the SDK location variables, and `OTEL_SERVICE_NAME` to the application container, plus the volume mount and a `SUCCESS` dependency on `init`

**Not changed:** your application image, your application source and `.csproj`, the task role's IAM policies, and the service's sidecars — no CloudWatch Agent or collector was added.

**Next steps:**

1. Review the diff — confirm `CORECLR_PROFILER_PATH` matches your task's OS and CPU architecture.
2. Deploy and let the tasks recycle.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ecs.md](collector-ecs.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
