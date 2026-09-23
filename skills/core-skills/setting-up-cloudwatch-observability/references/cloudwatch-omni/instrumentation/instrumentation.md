# Instrument an Application with ADOT (CloudWatch Application Observability)

Instrument an application that is **not yet instrumented** so it emits OpenTelemetry traces and metrics, using the AWS Distro for OpenTelemetry (ADOT) auto-instrumentation SDKs. This is plain OTel instrumentation — the ADOT SDK is wired into the workload and exports over OTLP to the SDK's default endpoint.

**Before you start:** confirm a Space exists in the target Region (`aws cloudwatch-omni list-spaces --region <region>`); if none, stop and run `../spaces-and-domains.md` first — instrumentation started before a Space exists appears to succeed while delivering telemetry nowhere the customer can see.

**Never modify application source code** (`.py`, `.js`, `.ts`, `.java`, `.cs`). Only edit infrastructure-as-code, Dockerfiles, CI/CD workflows, dependency files, and deployment manifests. Make the minimum change needed and preserve existing configuration. Present changes for the user to review; do not run `terraform apply`, `cdk deploy`, `kubectl apply`, `helm install`/`helm upgrade`, `kubectl annotate`, `kubectl delete`, or `aws ecs update-service` automatically. That applies to the collector step too: some of it is imperative commands rather than a diff, and those still belong to the user.

## Scope

The default job is **instrumentation only** — getting the ADOT SDK loaded into the running workload and emitting telemetry. Standing up a destination is a separate, optional second step.

| In scope | Out of scope |
|---|---|
| Installing / injecting the ADOT auto-instrumentation SDK | Application Signals, ServiceEvents, Dynamic Instrumentation |
| Setting the standard OTel SDK environment variables | Application Signals wiring of any kind: the `amazon-cloudwatch-observability` EKS add-on, the CloudWatch Agent's `application_signals` config sections, and port 4316 |
| Service name and resource attributes | Standing up the telemetry destination (deploying a collector — see [collector.md](collector.md)) |
| **Optional, only if the user asks for a destination:** deploying a collector — the CloudWatch Agent by default — and pointing the app at it, see [collector.md](collector.md) | |

**Where telemetry goes is deliberately not configured here.** The SDK falls back to its spec defaults (`http://localhost:4318` for OTLP/HTTP, `http://localhost:4317` for OTLP/gRPC). **Which of the two applies depends on the SDK:** the Java agent defaults to OTLP/gRPC on 4317, while the Python, Node.js and .NET distros default to OTLP/HTTP on 4318. Instrumentation is complete without a destination, and you must never invent an endpoint.

When the user does need one, **deploy a collector.** Use [collector.md](collector.md) and its platform guides to put a collector on EC2, ECS, or EKS and wire the app to it — the **CloudWatch Agent** by default, with upstream `otelcol-contrib` as the backup. The collector exports straight to CloudWatch's own per-signal OTLP endpoints. `../data-forwarding-and-centralization.md` is not an alternative here — it accepts no telemetry over OTLP, it forwards what is *already* in CloudWatch log groups into a Dataset.

Do not start down this path unprompted — instrumentation alone is a complete answer to "instrument my app".

## Do NOT add these

These belong to CloudWatch Application Signals and must not appear in an Omni instrumentation change. If the user explicitly wants Application Signals instead, stop and route to the **aws-observability** skill.

- `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true`, `OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT`
- `OTEL_AWS_SERVICE_EVENTS_*` (git/deployment metadata, `PACKAGES_INCLUDE`)
- `OTEL_AWS_OTLP_LOGS_ENDPOINT`, `OTEL_AWS_OTLP_METRICS_ENDPOINT`
- `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- The `amazon-cloudwatch-observability` EKS add-on, and the `instrumentation.opentelemetry.io/inject-*` annotation that depends on it
- Any endpoint on the CloudWatch Agent's port **4316** (a CloudWatch-specific port, not an OTel default)

**One exception, on Lambda only:** set `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false` explicitly. This is **required, not stylistic** — the layer's `otel-instrument` wrapper defaults the variable to `true` when it is unset, so omitting it silently ENABLES Application Signals. See the Lambda guides.

**A benign ServiceEvents WARN on ADOT Java 2.30.0.** Even with none of these variables set, the Java agent logs `OTEL_AWS_SERVICE_EVENTS_FUNCTION_INSTRUMENT_ENABLED=true but OTEL_AWS_SERVICE_EVENTS_PACKAGES_INCLUDE ...` around four times during startup, interleaved with `[SERVICE_EVENTS]` INFO lines such as `ServiceEventsInstrumentation initialized at startup` that read as though it were enabled, and then `ServiceEventsSpanProcessor not registered (serviceevents disabled)`. It defaults the flag internally and self-disables; nothing leaks. Expect the warning and leave it alone — do **not** "fix" it by setting `OTEL_AWS_SERVICE_EVENTS_FUNCTION_INSTRUMENT_ENABLED=false`, which is one of the variables above.

### IAM follows the destination, not the instrumentation

On **EC2, ECS, and EKS**, instrumentation itself needs no IAM changes — loading the SDK into a workload grants nothing, and the SDK is left pointing at its default local endpoint. Do not add `CloudWatchAgentServerPolicy`, `AWSXRayDaemonWriteAccess`, or `application-signals:*` permissions to those workloads.

That is **not** the same as saying the workload will never need permissions — it means *instrumentation* does not. Permissions follow whatever ends up talking to AWS:

- **A destination the user already has** — the permission belongs with it. Do not add a policy speculatively.
- **A collector deployed via [collector.md](collector.md)** — the collector is the thing calling AWS, so it does get IAM: `CloudWatchAgentServerPolicy` on the instance profile (EC2), the task role (ECS), or an IRSA role (EKS). The application still gets nothing.

**Lambda is different, and does get a policy here.** The ADOT layer exports to the execution environment's X-Ray receiver under active tracing, so the destination is already known and lives inside the function's own configuration. The Lambda guides therefore grant the execution role `xray:PutTraceSegments` and `xray:PutTelemetryRecords` — via `AWSXRayDaemonWriteAccess`, or the inline grant CDK adds when `tracing` is enabled. `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` is still out of scope, since Application Signals is disabled.

## Step 1: Determine platform and language

Detect from the IaC and application code, and confirm with the user if ambiguous.

- **EKS**: k8s Deployment manifests (`kind: Deployment`), Helm charts, `kubectl` in scripts, Terraform `aws_eks_*`
- **ECS**: ECS task definitions, `containerDefinitions`, Terraform `aws_ecs_*`
- **EC2**: EC2 instances, userdata scripts, launch templates, Terraform `aws_instance`
- **Language**: `requirements.txt`/`pyproject.toml`/`*.py` → Python; `package.json`/`*.ts`/`*.js` → Node.js; `pom.xml`/`build.gradle`/`*.java` → Java; `*.csproj`/`*.sln`/`*.cs` → .NET

If the workload is an **AI agent** built on a framework (LangChain, LangGraph, Strands, CrewAI, OpenAI Agents, Vercel AI), stop — use `../omni-agents-instrumentation/omni-agents-instrumentation.md` instead. That path instruments at the framework layer.

## Step 2: Read the matching guide

|  | Python | Node.js | Java | .NET |
|---|---|---|---|---|
| **EC2** | [ec2-python.md](ec2-python.md) | [ec2-nodejs.md](ec2-nodejs.md) | [ec2-java.md](ec2-java.md) | [ec2-dotnet.md](ec2-dotnet.md) |
| **ECS** | [ecs-python.md](ecs-python.md) | [ecs-nodejs.md](ecs-nodejs.md) | [ecs-java.md](ecs-java.md) | [ecs-dotnet.md](ecs-dotnet.md) |
| **EKS** | [eks-python.md](eks-python.md) | [eks-nodejs.md](eks-nodejs.md) | [eks-java.md](eks-java.md) | [eks-dotnet.md](eks-dotnet.md) |
| **Lambda** | [lambda-python.md](lambda-python.md) | [lambda-nodejs.md](lambda-nodejs.md) | [lambda-java.md](lambda-java.md) | [lambda-dotnet.md](lambda-dotnet.md) |

Only if the user also needs a destination, continue to [collector.md](collector.md) — it is language-agnostic and covers EC2, ECS, and EKS. Lambda is excluded: there is nowhere to run a collector in it, and its layer already exports to the execution environment's X-Ray receiver.

## How the SDK gets in

The mechanism differs by platform, but on ECS and EKS it is the same idea — an **init container copies the SDK into a shared volume** at startup, so the application image never changes:

| Platform | Mechanism | Touches the image? |
|---|---|---|
| **EKS** | `initContainers` + `emptyDir` volume, env vars on the container | No |
| **ECS** | Init container in the task definition + shared volume | No |
| **EC2** | Install in userdata; env vars on the process / systemd unit | No |
| **Lambda** | ADOT Lambda layer + `AWS_LAMBDA_EXEC_WRAPPER` | No |

For instrumentation alone, no cluster-level components are installed on EKS — no add-on and no operator; injection is written directly into the Deployment manifest. (If the user also asks for a destination, [collector.md](collector.md) deploys the CloudWatch Agent by Helm, which necessarily brings its operator. That is expected there, and is not the `amazon-cloudwatch-observability` add-on.)

Lambda is the odd one out: the execution environment supplies an X-Ray receiver that the layer exports to, so unlike the other three platforms its export path is already wired. That is why the Lambda guides look different and why `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false` is set explicitly there.

## Verifying without a receiver

Because no endpoint is configured, the SDK exports to `localhost:4318` where nothing is listening. **OTLP connection errors in the logs after instrumenting are expected and are not a failure** — they mean the SDK loaded and is trying to export. Tell the user the errors will clear once a receiver exists.

**Do not rely on "the SDK announces itself" as the check — it only works for Java.** What a working deployment actually logs, by language:

| Language | What the app log actually shows |
|---|---|
| Java | `opentelemetry-javaagent - version: <x>` — a reliable signal |
| Node.js | `automatic instrumentation started successfully`. Grep that string, not `opentelemetry`, which also matches benign warnings containing "Failed" |
| Python | No line containing "opentelemetry". The real one is `configurator already loaded` |
| .NET | **Nothing in the application log** at the default level — a log grep there reports failure on a healthy app. But the SDK writes its own file at the **default** level: `/tmp/otel-dotnet-auto-<pid>-<App>-Managed-<date>.log`. Read that instead. `The profiler has been initialized with NN direct definitions` is the attach signal. The export lines in it depend on whether a receiver exists yet — `Export succeeded for .../v1/traces` once a collector is running, export failures before then, which is expected |

For Python and .NET, verify by other means: the init container exiting 0, the loader variables present in the *running process* (`printenv`, or `tr '\0' '\n' < /proc/1/environ` — use PID 1 in a single-process container, since slim images often lack `pgrep`), and ultimately spans at the destination.

For .NET the strongest check is the SDK's own `Managed` log above. If you also check paths, expand the variable **inside** the container — `kubectl exec <pod> -- sh -c 'test -f "$CORECLR_PROFILER_PATH"'`; unwrapped, it expands in your local shell where it is unset and always reports failure. Note `DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` legitimately dangle in the container image.

If a collector was deployed in the same change, these errors should be absent — and on the CloudWatch Agent, all of them. The agent builds `traces`, `metrics` **and `logs`** pipelines from its `opentelemetry` section, so a correctly wired app logs no OTLP errors at all — a GET probe of `/v1/logs` returns 405 (method not allowed on a path that IS registered), not 404. Treat any OTLP error on the agent path as a real problem.

**On the `otelcol-contrib` backup only:** the hand-written Option A config in [collector.md](collector.md) defines only `traces` and `metrics` pipelines, while the SDKs default `OTEL_LOGS_EXPORTER=otlp` — so the receiver returns **404 on `/v1/logs`** and the app logs that permanently. That is expected there and is **not** a connectivity failure; traces flow fine alongside it. Either add a logs pipeline or set `OTEL_LOGS_EXPORTER=none`. Do not set `OTEL_LOGS_EXPORTER=none` on the CloudWatch Agent path — it would discard a signal the agent delivers for free.

## Step 3: Set the service identity

Every guide sets these two, and nothing else about export:

| Variable | Value |
|---|---|
| `OTEL_SERVICE_NAME` | The service's name as it should appear in Omni |
| `OTEL_RESOURCE_ATTRIBUTES` | Optional additional resource attributes, e.g. `deployment.environment=production` |

Derive `OTEL_SERVICE_NAME` from the existing workload name in the IaC (deployment name, ECS service name, or the application name) rather than inventing one. If it cannot be determined, ask.

## Step 4: Review

Summarize the changes grouped by file, state the platform and language, and list the environment variables that will reach the application at runtime. Note explicitly that **no exporter endpoint was configured** and that telemetry will go to the SDK default until a receiver is set up — and point the user to the two paths in [Scope](#scope). If a collector was deployed, state the endpoint the app now exports to and where the collector forwards it. Present the changes for review; do not deploy.

## Component versions

Use the latest published ADOT auto-instrumentation version for the language unless the user pins one. Look the current version up from the source of truth rather than hardcoding from this guide:

| Language | Releases | Container image (ECS / EKS init container) |
|---|---|---|
| Python | [releases](https://github.com/aws-observability/aws-otel-python-instrumentation/releases/latest) | [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-python) |
| Node.js | [releases](https://github.com/aws-observability/aws-otel-js-instrumentation/releases/latest) | [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-node) |
| Java | [releases](https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest) | [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-java) |
| .NET | [releases](https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest) | [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet) |

## Constraints

- Only IaC, Dockerfiles, CI/CD workflows, dependency files, and deployment manifests — never application source code.
- Do not deploy. Stage the changes and let the user review and apply them.
- Do not configure an OTLP endpoint, collector, or agent unless the user asked for a destination. If they did, use [collector.md](collector.md), where the CloudWatch Agent is the primary collector.
- Do not add Application Signals, ServiceEvents, or Dynamic Instrumentation configuration.
