# Instrument a .NET Application on Amazon EC2 with ADOT

Install the ADOT .NET auto-instrumentation on an EC2 instance and set the CoreCLR profiler variables so the runtime loads it at process start, by editing the instance's UserData (or the systemd unit / machine environment that starts the app).

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-ec2.md](collector-ec2.md).

## Critical Requirements

**Do NOT:**

- Install or configure the CloudWatch Agent, or any collector, on the instance — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), where the CloudWatch Agent is the primary collector
- Set `OTEL_TRACES_SAMPLER=xray`, or any `localhost:4316` / `localhost:2000` endpoint — these stay forbidden in all cases
- Set `OTEL_EXPORTER_OTLP_*` — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Set `OTEL_AWS_APPLICATION_SIGNALS_*`, `OTEL_AWS_SERVICE_EVENTS_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*`
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the instance role — **unless you are also deploying a collector** ([collector-ec2.md](collector-ec2.md)), which requires `CloudWatchAgentServerPolicy` on the instance role
- Run `cdk deploy` / `terraform apply`, or modify a running instance in place
- Remove or reorder existing UserData commands — append in sequence
- Modify the application's `.cs` files or its `.csproj`

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The instance may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-ec2.md](collector-ec2.md)), the collector is what gets the IAM — the workload still gets none.

## Before you start: gather these values

If you cannot determine a value from the IaC, ask the user. Do not guess.

- **Instance OS** — Linux or Windows Server. The installer, the paths, and the variable names all differ.
- **Deployment type** — read the UserData and find the command that starts the application. `docker run` / `docker start` → Docker. `dotnet <app>.dll`, a systemd unit, or IIS → runs directly on the instance.
- **How the app is started** — a shell command in UserData, a **systemd service**, or **IIS**. This determines where the variables have to go, and it is the most common thing to get wrong (see the systemd note below).
- **`<SERVICE_NAME>`** — the application or stack name; becomes `OTEL_SERVICE_NAME`.
- **CPU architecture and libc** — x86-64 or ARM64 (Graviton), and glibc or musl (Alpine). `CORECLR_PROFILER_PATH` names a directory built for that exact combination.

**Terraform heredoc warning:** when adding lines to a `user_data` heredoc, match the exact leading whitespace of the existing lines. `<<-EOF` only strips indentation when it is consistent; inconsistent indentation leaves spaces before `#!/bin/bash` and cloud-init fails.

## Linux: install the auto-instrumentation

```typescript
instance.userData.addCommands(
  'dnf install -y unzip',  // yum on AL2, apt-get on Ubuntu/Debian
  // -f so an error page is not saved as the installer; --retry because a transient failure here
  // aborts the rest of UserData under `set -e`. See collector-ec2.md's placement note.
  'curl -fsSL --retry 5 --retry-delay 5 --retry-connrefused -O \\',
  '  https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest/download/aws-otel-dotnet-install.sh',
  'chmod +x ./aws-otel-dotnet-install.sh',
  'OTEL_DOTNET_AUTO_HOME="/opt/otel-dotnet-auto" ./aws-otel-dotnet-install.sh',
  'chmod -R 755 /opt/otel-dotnet-auto',
);
```

## Linux: the application is started from the UserData shell

**Set the loader variables explicitly rather than sourcing `instrument.sh`.** The distro ships that
script and the Application Signals guides use it, but it configures **Application Signals** — which
is what those guides want and what this one excludes. Its non-Lambda branch ends with (checked on
1.15.x):

```sh
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4316"
export OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT="http://127.0.0.1:4316/v1/metrics"
export OTEL_METRICS_EXPORTER="none"
export OTEL_AWS_APPLICATION_SIGNALS_ENABLED="true"
export OTEL_TRACES_SAMPLER="xray"
export OTEL_TRACES_SAMPLER_ARG="endpoint=http://127.0.0.1:2000"
```

4316 is the CloudWatch Agent's Application Signals port and 2000 its X-Ray sampler — correct for
Application Signals, out of scope here. **Those exports are unguarded**, unlike the script's Lambda
branch where nearly every assignment is wrapped in `if [ -z "${VAR}" ]`, so pre-setting a variable
does not protect it; an override would have to come *after* sourcing. And a `grep CORECLR` check
would not reveal any of it.

If you do source it — for instance to reuse its runtime detection, see below — you must then
override all seven, and re-check that list against the release you are on.

```typescript
instance.userData.addCommands(
  'export CORECLR_ENABLE_PROFILING=1',
  'export CORECLR_PROFILER={918728DD-259F-4A6A-AC2B-B85E1B658318}',
  'export CORECLR_PROFILER_PATH=/opt/otel-dotnet-auto/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so',
  'export DOTNET_STARTUP_HOOKS=/opt/otel-dotnet-auto/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll',
  'export OTEL_DOTNET_AUTO_HOME=/opt/otel-dotnet-auto',
  'export OTEL_DOTNET_AUTO_PLUGINS="AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation"',
  'export OTEL_SERVICE_NAME=<SERVICE_NAME>',
  '',
  '# Existing startup command remains unchanged — the env vars enable instrumentation',
);
```

The startup command itself does not change.

`linux-x64` above assumes a glibc x86-64 host. **It depends on both architecture and libc, and a
wrong segment means the profiler silently does not attach** — the app starts normally and emits
nothing. Derive it rather than assuming; see the detection snippet in the systemd section below,
which applies equally here.

## Linux: the application runs as a systemd service

**Exports do not reach a service.** Setting the variables in UserData — or sourcing anything in `ExecStartPre=` — does **not** instrument a service, because `ExecStart` is a fresh process that does not inherit that environment. The CoreCLR profiler is loaded by the runtime at process start from these variables, so they must be on the unit itself:

```ini
# /etc/systemd/system/<SERVICE_NAME>.service  (add to the [Service] section)
[Service]
Environment=CORECLR_ENABLE_PROFILING=1
Environment=CORECLR_PROFILER={918728DD-259F-4A6A-AC2B-B85E1B658318}
Environment=CORECLR_PROFILER_PATH=/opt/otel-dotnet-auto/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so
Environment=DOTNET_ADDITIONAL_DEPS=/opt/otel-dotnet-auto/AdditionalDeps
Environment=DOTNET_SHARED_STORE=/opt/otel-dotnet-auto/store
Environment=DOTNET_STARTUP_HOOKS=/opt/otel-dotnet-auto/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll
Environment=OTEL_DOTNET_AUTO_HOME=/opt/otel-dotnet-auto
Environment="OTEL_DOTNET_AUTO_PLUGINS=AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation"
Environment=OTEL_SERVICE_NAME=<SERVICE_NAME>
```

**The quotes around `OTEL_DOTNET_AUTO_PLUGINS` are required.** Its value contains a space, and
systemd splits an unquoted `Environment=` on whitespace: the tail becomes a second, invalid
assignment that systemd discards with `Invalid environment assignment, ignoring: ...`, leaving
the variable set to a trailing-comma plugin name that cannot be resolved. The profiler then
never attaches — the app starts normally, serves traffic, and emits nothing. The
`EnvironmentFile=` form below has no such splitting problem and is the safer default.

The space itself is optional: .NET assembly-qualified type names allow whitespace after the
comma, and `...Plugin,AWS.Distro.OpenTelemetry.AutoInstrumentation` resolves identically
(verified with `Type.GetType` on .NET 9). Dropping the space is therefore an equally valid fix
that needs no quoting at all. What does *not* resolve is the trailing-comma fragment systemd
leaves behind — `Type.GetType("...Plugin,")` returns null with a `FileLoadException`, which is
exactly why the profiler silently fails to attach.

Adjust the paths if `OTEL_DOTNET_AUTO_HOME` is not `/opt/otel-dotnet-auto`.

**The `linux-x64` segment depends on libc as well as architecture, and getting it wrong means the
profiler silently does not attach** — the app starts normally and emits nothing. Derive it the same
way `instrument.sh` does rather than assuming:

```bash
# linux-glibc | linux-musl
if [ "$(ldd /bin/ls | grep -m1 musl)" ]; then LIBC=musl-; else LIBC=; fi
case "$(uname -m)" in x86_64) ARCH=x64 ;; aarch64) ARCH=arm64 ;; esac
# -> /opt/otel-dotnet-auto/linux-${LIBC}${ARCH}/OpenTelemetry.AutoInstrumentation.Native.so
ls /opt/otel-dotnet-auto/            # or just list what the install actually produced
```

So `linux-x64` on a glibc x86-64 host, `linux-arm64` on Graviton, `linux-musl-x64` on Alpine. Then add `systemctl daemon-reload` and `systemctl restart <SERVICE_NAME>` to UserData. (Equivalently, write these `KEY=VALUE` pairs to a file and reference it with `EnvironmentFile=/etc/<SERVICE_NAME>.env`.)

`ExecStart` does not need to change.

**Do not verify this by looking for OpenTelemetry lines in the application log.** ADOT .NET
writes no startup diagnostics at the default log level — on a working instance there are no
OTel lines on stdout and no `/var/log/opentelemetry/dotnet` directory at all, so a broken and a
working setup look identical. Verify instead that the variables reached the *process*
(`tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value <SERVICE_NAME>)/environ | grep CORECLR`),
and confirm spans at the destination. **The SDK's own log is the best local check and needs no
`OTEL_LOG_LEVEL`** — at the default level `/tmp/otel-dotnet-auto-<pid>-<App>-Managed-<date>.log`
already contains `The profiler has been initialized with NN direct definitions` and a per-signal
`Export succeeded for http://localhost:4318/v1/{traces,metrics,logs}`. (`Loader` and `StartupHook`
files appear alongside it; nothing lands under `/var/log`.) Ignore the benign `AWSEKSDetector`
`DirectoryNotFoundException` / "Certificate file does not exist" warnings there on EC2. Also confirm `CORECLR_PROFILER_PATH` points at a file that exists — the variable's
string value being present proves nothing about the path being valid, which is the actual failure mode.

## Windows Server

Install via the PowerShell module, then set the variables at machine scope so any process — including an IIS worker — picks them up:

```typescript
instance.userData.addCommands(
  '$module_url = "https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest/download/AWS.Otel.DotNet.Auto.psm1"',
  '$download_path = Join-Path $env:temp "AWS.Otel.DotNet.Auto.psm1"',
  'Invoke-WebRequest -Uri $module_url -OutFile $download_path',
  'Import-Module $download_path',
  'Install-OpenTelemetryCore',
);
```

```typescript
instance.userData.addCommands(
  '$env:INSTALL_DIR = "C:\\Program Files\\AWS Distro for OpenTelemetry AutoInstrumentation"',
  '[Environment]::SetEnvironmentVariable("CORECLR_ENABLE_PROFILING", "1", "Machine")',
  '[Environment]::SetEnvironmentVariable("CORECLR_PROFILER", "{918728DD-259F-4A6A-AC2B-B85E1B658318}", "Machine")',
  '[Environment]::SetEnvironmentVariable("CORECLR_PROFILER_PATH_64", (Join-Path $env:INSTALL_DIR "win-x64/OpenTelemetry.AutoInstrumentation.Native.dll"), "Machine")',
  '[Environment]::SetEnvironmentVariable("CORECLR_PROFILER_PATH_32", (Join-Path $env:INSTALL_DIR "win-x86/OpenTelemetry.AutoInstrumentation.Native.dll"), "Machine")',
  '[Environment]::SetEnvironmentVariable("COR_ENABLE_PROFILING", "1", "Machine")',
  '[Environment]::SetEnvironmentVariable("COR_PROFILER", "{918728DD-259F-4A6A-AC2B-B85E1B658318}", "Machine")',
  '[Environment]::SetEnvironmentVariable("COR_PROFILER_PATH_64", (Join-Path $env:INSTALL_DIR "win-x64/OpenTelemetry.AutoInstrumentation.Native.dll"), "Machine")',
  '[Environment]::SetEnvironmentVariable("COR_PROFILER_PATH_32", (Join-Path $env:INSTALL_DIR "win-x86/OpenTelemetry.AutoInstrumentation.Native.dll"), "Machine")',
  '[Environment]::SetEnvironmentVariable("DOTNET_ADDITIONAL_DEPS", (Join-Path $env:INSTALL_DIR "AdditionalDeps"), "Machine")',
  '[Environment]::SetEnvironmentVariable("DOTNET_SHARED_STORE", (Join-Path $env:INSTALL_DIR "store"), "Machine")',
  '[Environment]::SetEnvironmentVariable("DOTNET_STARTUP_HOOKS", (Join-Path $env:INSTALL_DIR "net/OpenTelemetry.AutoInstrumentation.StartupHook.dll"), "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_DOTNET_AUTO_HOME", $env:INSTALL_DIR, "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_DOTNET_AUTO_PLUGINS", "AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_SERVICE_NAME", "<SERVICE_NAME>", "Machine")',
  '# Only if the application is hosted in IIS',
  'Register-OpenTelemetryForIIS',
);
```

The `COR_*` variables are the .NET Framework equivalents of the `CORECLR_*` ones; keep both if the instance hosts .NET Framework applications alongside .NET (Core).

## The application runs in a Docker container on the instance

The auto-instrumentation has to be visible inside the container. Install it into a host directory and bind-mount it — no image rebuild:

```typescript
instance.userData.addCommands(
  `docker run -d --name <APP_NAME> \\`,
  `  -v /opt/otel-dotnet-auto:/opt/otel-dotnet-auto:ro \\`,
  `  -e CORECLR_ENABLE_PROFILING=1 \\`,
  `  -e CORECLR_PROFILER={918728DD-259F-4A6A-AC2B-B85E1B658318} \\`,
  `  -e CORECLR_PROFILER_PATH=/opt/otel-dotnet-auto/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so \\`,
  `  -e DOTNET_STARTUP_HOOKS=/opt/otel-dotnet-auto/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll \\`,
  `  -e DOTNET_ADDITIONAL_DEPS=/opt/otel-dotnet-auto/AdditionalDeps \\`,
  `  -e DOTNET_SHARED_STORE=/opt/otel-dotnet-auto/store \\`,
  `  -e OTEL_DOTNET_AUTO_HOME=/opt/otel-dotnet-auto \\`,
  `  -e OTEL_DOTNET_AUTO_PLUGINS="AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation" \\`,
  `  -e OTEL_SERVICE_NAME=<SERVICE_NAME> \\`,
  `  <IMAGE_URI>`,
);
```

Keep every flag the existing `docker run` already had — ports, networks, volumes, restart policy.

The host install and the container must agree on the runtime and architecture the native profiler was built for. If the container's base image differs from the host (for example, an Alpine/musl image on a glibc host), the bind-mounted profiler will not load; in that case install the SDK in the image instead, or copy it out of `public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet` — the same image the ECS and EKS guides use — so the binaries match the container.

## Verify

After the user deploys and the instance boots, confirm the variables actually reached the application process:

- systemd: `systemctl show <SERVICE_NAME> --property=Environment` — every `CORECLR_*` and `DOTNET_*` variable should be listed. Two of them name directories that the ADOT distro does not ship — `DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` — so those paths dangle on a working install and are not the fault you are looking for. The ones that must resolve on disk are `CORECLR_PROFILER_PATH` and `DOTNET_STARTUP_HOOKS`
- Docker: `docker exec <APP_NAME> printenv | grep -E "CORECLR|DOTNET_|OTEL_"`
- Do **not** look for OpenTelemetry lines in the application log — ADOT .NET writes none at the default log level, so an empty result is expected on a working app

This check matters more for .NET than for other languages: if any variable is missing or a path is wrong, the profiler does not attach and the application starts normally with no instrumentation and no error. `/var/log/cloud-init-output.log` shows whether the installer succeeded. Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT .NET auto-instrumentation into your EC2 deployment.

**Changes:**

- UserData: installed the ADOT .NET auto-instrumentation to `/opt/otel-dotnet-auto` (Linux) or via the PowerShell module (Windows)
- Set the CoreCLR profiler variables, the SDK location variables, and `OTEL_SERVICE_NAME` — your startup command is unchanged
- systemd unit, if the app runs as a service: added `Environment=` lines. Sourcing `instrument.sh` in UserData would not have reached the service process, so the variables have to live on the unit
- Docker path: bind-mounted the SDK into the container, so your image and `Dockerfile` are unchanged

**Not changed:** your application source and `.csproj`, the instance role's IAM policies, and the instance's monitoring software — no CloudWatch Agent or collector was installed.

**Next steps:**

1. Review the diff — confirm `CORECLR_PROFILER_PATH` matches the host's architecture **and libc** (`linux-x64` / `linux-arm64` / `linux-musl-x64` / `win-x64`), and that the directory exists.
2. Deploy and replace the instance (UserData runs at first boot only), then confirm the variables reached the process.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-ec2.md](collector-ec2.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you deploy."
