# Enable AWS Application Signals for .NET on EC2

Your task is to modify Infrastructure as Code (IaC) files to enable AWS Application Signals for a .NET application running on EC2 instances. You will update IAM permissions, install monitoring agents, and configure OpenTelemetry instrumentation through UserData scripts.

## What You Will Accomplish

After completing this task:

- The EC2 instance will have permissions to send telemetry data to CloudWatch
- The CloudWatch Agent will be installed and configured for Application Signals
- The .NET application will be automatically instrumented with AWS Distro for OpenTelemetry (ADOT)
- Traces, metrics, and performance data will appear in the CloudWatch Application Signals console

## Critical Requirements

**Error Handling:**

- If you cannot determine required values from the IaC, STOP and ask the user
- For multiple EC2 instances, ask which one(s) to modify
- Preserve all existing UserData commands; add new ones in sequence

**Do NOT:**

- Run deployment commands automatically (`cdk deploy`, `terraform apply`, etc.)
- Remove existing application startup logic
- Skip the user approval step before deployment

## IaC Tool Support

**Code examples use CDK TypeScript syntax.** If you are working with Terraform or CloudFormation, translate the CDK syntax to the appropriate format while keeping all bash commands identical.

## Before You Start: Gather Required Information

### Step 1: Determine Deployment Type

- `docker run` or `docker start` → Docker deployment
- `dotnet run`, `dotnet myapp.dll`, or similar → Non-Docker deployment

### Step 2: Extract Placeholder Values

- `{{SERVICE_NAME}}` - Service name for Application Signals console. **Example:** `my-dotnet-app`
- `{{APP_NAME}}` (Docker only) - Container name. **Example:** `dotnet-api-app`
- `{{IMAGE_URI}}` (Docker only) - Docker image URI.

### Step 3: Identify Instance OS

**Linux:**

- **Amazon Linux 2:** `yum`, **Amazon Linux 2023:** `dnf`, **Ubuntu/Debian:** `apt`

**Windows Server:**

- Supported. Use the **For Windows instances** code blocks in Steps 4–7 (PowerShell). **How to detect:** look for a Windows AMI reference in the IaC (e.g. `Windows_Server`, `windowsLatest`), PowerShell in existing UserData, or ask the user.

## Instructions

### Step 1: Locate the IaC Files

Search for EC2 instance definitions (`new ec2.Instance(`, `resource "aws_instance"`, `AWS::EC2::Instance`).

### Step 2: Locate the IAM Role

Find the IAM role attached to the EC2 instance.

### Step 3: Update the IAM Role

```typescript
const role = new iam.Role(this, 'AppRole', {
  assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy'),
    // ... keep existing policies
  ],
});
```

### Step 4: Modify UserData - Install CloudWatch Agent

**For Linux instances:**

```typescript
instance.userData.addCommands(
  'dnf install -y amazon-cloudwatch-agent',  // Use dnf for AL2023, yum for AL2, apt-get for Ubuntu
);
```

**For Windows instances:**

```typescript
instance.userData.addCommands(
  'Invoke-WebRequest -Uri "https://amazoncloudwatch-agent.s3.amazonaws.com/windows/amd64/latest/amazon-cloudwatch-agent.msi" -OutFile "C:\\amazon-cloudwatch-agent.msi"',
  'Start-Process msiexec.exe -Wait -ArgumentList "/i C:\\amazon-cloudwatch-agent.msi /quiet"',
  'Remove-Item "C:\\amazon-cloudwatch-agent.msi"',
);
```

### Step 5: Modify UserData - Configure CloudWatch Agent

**For Linux instances:**

```typescript
instance.userData.addCommands(
  "cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'",
  '{',
  '  "traces": {',
  '    "traces_collected": {',
  '      "application_signals": {}',
  '    }',
  '  },',
  '  "logs": {',
  '    "metrics_collected": {',
  '      "application_signals": {}',
  '    }',
  '  }',
  '}',
  'EOF',
  '/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \\',
  '  -a fetch-config -m ec2 -s \\',
  '  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json',
);
```

**For Windows instances:**

```typescript
instance.userData.addCommands(
  '@"',
  '{ "traces": { "traces_collected": { "application_signals": {} } }, "logs": { "metrics_collected": { "application_signals": {} } } }',
  '"@ | Out-File -FilePath "C:\\ProgramData\\Amazon\\AmazonCloudWatchAgent\\amazon-cloudwatch-agent.json" -Encoding ASCII',
  '& "C:\\Program Files\\Amazon\\AmazonCloudWatchAgent\\amazon-cloudwatch-agent-ctl.ps1" -a fetch-config -m ec2 -s -c file:"C:\\ProgramData\\Amazon\\AmazonCloudWatchAgent\\amazon-cloudwatch-agent.json"',
);
```

### Step 6: Install ADOT .NET Auto-Instrumentation

#### Option A: Docker Deployment - Modify Dockerfile

**For Linux-based containers:**

```dockerfile
# Install unzip (required by ADOT installation script)
RUN dnf install -y unzip  # Adjust package manager as needed

# Download and install ADOT .NET auto-instrumentation
RUN curl -L -O https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest/download/aws-otel-dotnet-install.sh \
    && chmod +x ./aws-otel-dotnet-install.sh \
    && OTEL_DOTNET_AUTO_HOME="/opt/otel-dotnet-auto" ./aws-otel-dotnet-install.sh \
    && chmod -R 755 /opt/otel-dotnet-auto
```

#### Option B: Non-Docker Deployment - Modify UserData

**For Linux instances:**

```typescript
instance.userData.addCommands(
  'dnf install -y unzip',
  'curl -L -O https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest/download/aws-otel-dotnet-install.sh',
  'chmod +x ./aws-otel-dotnet-install.sh',
  'OTEL_DOTNET_AUTO_HOME="/opt/otel-dotnet-auto" ./aws-otel-dotnet-install.sh',
  'chmod -R 755 /opt/otel-dotnet-auto',
);
```

**For Windows instances:**

```typescript
instance.userData.addCommands(
  '$module_url = "https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest/download/AWS.Otel.DotNet.Auto.psm1"',
  '$download_path = Join-Path $env:temp "AWS.Otel.DotNet.Auto.psm1"',
  'Invoke-WebRequest -Uri $module_url -OutFile $download_path',
  'Import-Module $download_path',
  'Install-OpenTelemetryCore',
);
```

### Step 7: Modify UserData - Configure Application

#### Option A: Docker Deployment

**Container networking — match the customer's existing setup (minimal change).** The example below uses `--network host` with `localhost:4316` endpoints. That pairing is one option, not a hard requirement — the right choice depends on how the container already reaches the host-installed CloudWatch Agent. Don't change the customer's networking model just to instrument; instead pick the variant that fits theirs:

- **Already using `--network host`** (or willing to): keep it, and the `localhost:4316` / `localhost:2000` endpoints in the example work as-is. Trade-off: host networking shares the host's network namespace (no container isolation), though the agent's ports can stay bound to loopback, unreachable off-host. For production, it is recommended to restrict the OTLP `4316` / proxy `2000` ports via EC2 security groups / host firewall and to avoid co-locating untrusted containers; this guide does not apply those controls, so assess and configure them for your environment.
- **Using a bridge/default network:** don't add `--network host`. Point the endpoints at the host instead — `host.docker.internal:4316`/`:2000` (add `--add-host=host.docker.internal:host-gateway` on Linux) or the bridge gateway IP. This requires the CloudWatch Agent to listen on a non-loopback address, so it is recommended to restrict those ports with security groups / host firewall.
- **Option 2 — CloudWatch Agent as a sidecar container** (most isolated): run the agent as another container on the same user-defined Docker network and target it by name (e.g. `cwagent:4316`). Nothing binds to host interfaces. This is the same model the ECS guides use; choose it if the customer prefers full container isolation over a host-installed agent.

**For Linux-based containers (`--network host` example — adapt per the networking variant you chose above):**

```typescript
instance.userData.addCommands(
  `docker run -d --name {{APP_NAME}} \\`,
  `  -e OTEL_DOTNET_AUTO_HOME=/opt/otel-dotnet-auto \\`,
  `  -e DOTNET_STARTUP_HOOKS=/opt/otel-dotnet-auto/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll \\`,
  `  -e DOTNET_SHARED_STORE=/opt/otel-dotnet-auto/store \\`,
  `  -e DOTNET_ADDITIONAL_DEPS=/opt/otel-dotnet-auto/AdditionalDeps \\`,
  `  -e OTEL_METRICS_EXPORTER=none \\`,
  `  -e OTEL_LOGS_EXPORTER=none \\`,
  `  -e OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true \\`,
  `  -e OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \\`,
  `  -e OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT=http://localhost:4316/v1/metrics \\`,
  `  -e OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4316/v1/traces \\`,
  `  -e OTEL_RESOURCE_ATTRIBUTES=service.name={{SERVICE_NAME}} \\`,
  `  --network host \\`,
  `  {{IMAGE_URI}}`,
);
```

#### Option B: Non-Docker Deployment

**For Linux instances:**

```typescript
instance.userData.addCommands(
  '. /opt/otel-dotnet-auto/instrument.sh',
  'export OTEL_METRICS_EXPORTER=none',
  'export OTEL_LOGS_EXPORTER=none',
  'export OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true',
  'export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf',
  'export OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT=http://localhost:4316/v1/metrics',
  'export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4316/v1/traces',
  'export OTEL_RESOURCE_ATTRIBUTES=service.name={{SERVICE_NAME}}',
  '',
  '# Start application (existing command remains unchanged)',
  '# The OTEL environment variables will automatically enable instrumentation',
);
```

> The `export ...` / `. instrument.sh` form above only instruments an app **launched in the same shell session**. If the application runs as a **systemd service** (the app is started by an `ExecStart=` in a `.service` unit), those exports do **not** reach the service process — `ExecStart` is a fresh process that does not inherit the userdata shell's environment, and sourcing `instrument.sh` in `ExecStartPre=` does not propagate either. You must put the variables on the unit itself. The CoreCLR profiler env vars are required because the .NET profiler is loaded by the runtime at process start from these variables.

**For Linux instances where the app runs as a systemd service:** set the auto-instrumentation env vars in the unit (or an `EnvironmentFile=`) so the `ExecStart` process inherits them. The Linux CoreCLR values below are from the [Application Signals EC2 docs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-EC2Main.html) — adjust `OTEL_DOTNET_AUTO_HOME` (here `/opt/otel-dotnet-auto`) to your install dir:

```ini
# /etc/systemd/system/{{SERVICE_NAME}}.service  (add to the [Service] section)
[Service]
Environment=CORECLR_ENABLE_PROFILING=1
Environment=CORECLR_PROFILER={918728DD-259F-4A6A-AC2B-B85E1B658318}
Environment=CORECLR_PROFILER_PATH=/opt/otel-dotnet-auto/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so
Environment=DOTNET_ADDITIONAL_DEPS=/opt/otel-dotnet-auto/AdditionalDeps
Environment=DOTNET_SHARED_STORE=/opt/otel-dotnet-auto/store
Environment=DOTNET_STARTUP_HOOKS=/opt/otel-dotnet-auto/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll
Environment=OTEL_DOTNET_AUTO_HOME=/opt/otel-dotnet-auto
Environment=OTEL_DOTNET_AUTO_PLUGINS=AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation
Environment=OTEL_METRICS_EXPORTER=none
Environment=OTEL_LOGS_EXPORTER=none
Environment=OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true
Environment=OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
Environment=OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT=http://localhost:4316/v1/metrics
Environment=OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4316/v1/traces
Environment=OTEL_RESOURCE_ATTRIBUTES=service.name={{SERVICE_NAME}}
```

After editing the unit, the userdata must reload and (re)start it: `systemctl daemon-reload` then `systemctl restart {{SERVICE_NAME}}`. (Equivalently, write these `KEY=VALUE` pairs to a file and reference it with `EnvironmentFile=/etc/{{SERVICE_NAME}}.env` instead of inline `Environment=` lines.)

**For Windows instances:**

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
  '[Environment]::SetEnvironmentVariable("OTEL_RESOURCE_ATTRIBUTES", "service.name={{SERVICE_NAME}}", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4316", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT", "http://127.0.0.1:4316/v1/metrics", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_METRICS_EXPORTER", "none", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_AWS_APPLICATION_SIGNALS_ENABLED", "true", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_TRACES_SAMPLER", "xray", "Machine")',
  '[Environment]::SetEnvironmentVariable("OTEL_TRACES_SAMPLER_ARG", "http://127.0.0.1:2000", "Machine")',
  '# The command below is optional. It registers Application signals in IIS',
  'Register-OpenTelemetryForIIS',
);
```

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your .NET application. Here's what I modified:

**Files Changed:**

- IAM role: Added CloudWatchAgentServerPolicy
- UserData: Installed and configured CloudWatch Agent
- UserData: Downloaded and installed ADOT .NET auto-instrumentation
- UserData/Dockerfile: Added OpenTelemetry environment variables
- Dockerfile: Installed ADOT .NET auto-instrumentation (if using Docker)

**Next Steps:**

1. Review the changes I made using `git diff`
2. Deploy your infrastructure:
   - For CDK: `cdk deploy`
   - For Terraform: `terraform apply`
   - For CloudFormation: Deploy your stack
3. After deployment, wait 5-10 minutes for telemetry data to start flowing

**Verification:**
Once deployed, you can verify Application Signals is working by:

- Opening the AWS CloudWatch Console
- Navigating to Application Signals → Services
- Looking for your service (named: {{SERVICE_NAME}})

**Monitor Application Health:**
After enablement, you can monitor your application's operational health using Application Signals dashboards. For more information, see [Monitor the operational health of your applications with Application Signals](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Services.html).

Let me know if you'd like me to make any adjustments before you deploy!"
