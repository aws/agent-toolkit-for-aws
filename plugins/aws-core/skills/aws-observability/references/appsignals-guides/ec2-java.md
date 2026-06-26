# Enable AWS Application Signals for Java on EC2

Your task is to modify Infrastructure as Code (IaC) files to enable AWS Application Signals for a Java application running on EC2 instances. You will update IAM permissions, install monitoring agents, and configure OpenTelemetry instrumentation through UserData scripts.

## What You Will Accomplish

After completing this task:

- The EC2 instance will have permissions to send telemetry data to CloudWatch
- The CloudWatch Agent will be installed and configured for Application Signals
- The Java application will be automatically instrumented with AWS Distro for OpenTelemetry (ADOT)
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

Read the UserData script and look for the application startup command.

**If you see:**

- `docker run` or `docker start` → Docker deployment
- `java -jar`, `mvn spring-boot:run`, `gradle bootRun`, or similar → Non-Docker deployment

**If unclear:**

- Ask the user: "Is your Java application running in a Docker container or directly on the EC2 instance?" DO NOT GUESS

### Step 2: Extract Placeholder Values

- `{{SERVICE_NAME}}`
  - **Why It Matters:** Sets the service name displayed in Application Signals console via `OTEL_RESOURCE_ATTRIBUTES=service.name={{SERVICE_NAME}}`
  - **How to Find It:** Use the application name, stack name, or construct ID.
  - **Example Value:** `my-java-app`
  - **Required For:** Both Docker and non-Docker

For Docker-based deployments:

- `{{PORT}}` - Docker port mapping. **Example:** `8080`
- `{{APP_NAME}}` - Container name. **Example:** `java-springboot-app`
- `{{IMAGE_URI}}` - Docker image. **Example:** `123456789012.dkr.ecr.us-east-1.amazonaws.com/my-app:latest`

### Step 3: Identify Instance OS

- **Amazon Linux 2:** Use `yum` package manager
- **Amazon Linux 2023:** Use `dnf` package manager
- **Ubuntu/Debian:** Use `apt` package manager

## Instructions

### Step 1: Locate the IaC Files

**Search for EC2 instance definitions** using these patterns:

**CDK:** `new ec2.Instance(`, `CfnInstance(`
**Terraform:** `resource "aws_instance"`
**CloudFormation:** `AWS::EC2::Instance`

### Step 2: Locate the IAM Role

Find the IAM role attached to the EC2 instance.

### Step 3: Update the IAM Role

Add the CloudWatch Agent Server Policy to the IAM role's managed policies.

**CDK:**

```typescript
const role = new iam.Role(this, 'AppRole', {
  assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy'),
    // ... keep existing policies
  ],
});
```

### Step 4: Modify UserData - Add Prerequisites

**CRITICAL for Terraform Users:** Preserve the EXACT indentation of existing heredoc lines.

**CDK TypeScript example:**

```typescript
instance.userData.addCommands(
  'dnf install -y amazon-cloudwatch-agent',  // Use dnf for AL2023, yum for AL2
);
```

### Step 5: Modify UserData - Configure CloudWatch Agent

```typescript
instance.userData.addCommands(
  '# Create CloudWatch Agent configuration for Application Signals',
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
  '',
  '# Start CloudWatch Agent with Application Signals configuration',
  '/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \\',
  '  -a fetch-config \\',
  '  -m ec2 \\',
  '  -s \\',
  '  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json',
);
```

### Step 6: Install ADOT Java Auto-Instrumentation SDK

#### Option A: Docker Deployment - Modify Dockerfile

Add these lines to download the ADOT Java agent JAR file BEFORE the `CMD` line:

```dockerfile
# Downloads latest release. ServiceEvents requires aws-opentelemetry-agent>=2.28.2.
RUN curl -Lo /opt/aws-opentelemetry-agent.jar \
    https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest/download/aws-opentelemetry-agent.jar
```

#### Option B: Non-Docker Deployment - Modify UserData

```typescript
instance.userData.addCommands(
  '# Download ADOT Java agent (latest; ServiceEvents requires >=2.28.2)',
  'curl -Lo /opt/aws-opentelemetry-agent.jar \\',
  '  https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest/download/aws-opentelemetry-agent.jar',
);
```

### Step 7: Modify UserData - Configure Application

#### Option A: Docker Deployment

**Container networking — match the customer's existing setup (minimal change).** The example below uses `--network host` with `localhost:4316` endpoints. That pairing is one option, not a hard requirement — the right choice depends on how the container already reaches the host-installed CloudWatch Agent. Don't change the customer's networking model just to instrument; instead pick the variant that fits theirs:

- **Already using `--network host`** (or willing to): keep it, and the `localhost:4316` / `localhost:2000` endpoints in the example work as-is. Trade-off: host networking shares the host's network namespace (no container isolation), though the agent's ports can stay bound to loopback, unreachable off-host. For production, it is recommended to restrict the OTLP `4316` / proxy `2000` ports via EC2 security groups / host firewall and to avoid co-locating untrusted containers; this guide does not apply those controls, so assess and configure them for your environment.
- **Using a bridge/default network:** don't add `--network host`. Point the endpoints at the host instead — `host.docker.internal:4316`/`:2000` (add `--add-host=host.docker.internal:host-gateway` on Linux) or the bridge gateway IP. This requires the CloudWatch Agent to listen on a non-loopback address, so it is recommended to restrict those ports with security groups / host firewall.
- **Option 2 — CloudWatch Agent as a sidecar container** (most isolated): run the agent as another container on the same user-defined Docker network and target it by name (e.g. `cwagent:4316`). Nothing binds to host interfaces. This is the same model the ECS guides use; choose it if the customer prefers full container isolation over a host-installed agent.

**`--network host` example — adapt per the networking variant you chose above:**

```typescript
instance.userData.addCommands(
  '# Run container with Application Signals environment variables',
  `docker run -d --name {{APP_NAME}} \\`,
  `  -e JAVA_TOOL_OPTIONS=-javaagent:/opt/aws-opentelemetry-agent.jar \\`,
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

```typescript
instance.userData.addCommands(
  '# Set OpenTelemetry environment variables',
  'export JAVA_TOOL_OPTIONS=-javaagent:/opt/aws-opentelemetry-agent.jar',
  'export OTEL_METRICS_EXPORTER=none',
  'export OTEL_LOGS_EXPORTER=none',
  'export OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true',
  'export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf',
  'export OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT=http://localhost:4316/v1/metrics',
  'export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4316/v1/traces',
  'export OTEL_RESOURCE_ATTRIBUTES=service.name={{SERVICE_NAME}}',
  '',
  '# Start application (existing command remains unchanged)',
  '# The JAVA_TOOL_OPTIONS will automatically attach the agent',
);
```

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your Java application. Here's what I modified:

**Files Changed:**

- IAM role: Added CloudWatchAgentServerPolicy
- UserData: Installed and configured CloudWatch Agent
- UserData: Downloaded ADOT Java agent JAR
- UserData/Service file: Added OpenTelemetry environment variables (`JAVA_TOOL_OPTIONS`)
- Dockerfile: Downloaded ADOT Java agent JAR (if using Docker)

**Next Steps:**

1. Ensure that [Application Signals is enabled in AWS account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html).
2. Review the changes I made using `git diff`
3. Deploy your infrastructure:
   - For CDK: `cdk deploy`
   - For Terraform: `terraform apply`
   - For CloudFormation: Deploy your stack
4. After deployment, wait 5-10 minutes for telemetry data to start flowing

**Verification:**
Once deployed, you can verify Application Signals is working by:

- Opening the AWS CloudWatch Console
- Navigating to Application Signals → Services
- Looking for your service (named: {{SERVICE_NAME}})
- Checking that traces and metrics are being collected

**Monitor Application Health:**
After enablement, you can monitor your application's operational health using Application Signals dashboards. For more information, see [Monitor the operational health of your applications with Application Signals](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Services.html).

**Troubleshooting**
If you encounter any other issues, refer to the [CloudWatch APM troubleshooting guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Troubleshoot.html).

Let me know if you'd like me to make any adjustments before you deploy!"
