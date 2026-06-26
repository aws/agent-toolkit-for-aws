# Enable AWS Application Signals for Python on ECS

## Overview
This guide provides complete steps to enable AWS Application Signals for ECS services (both EC2 and Fargate launch types), including distributed tracing, performance monitoring, and service mapping.

## Prerequisites

- Services running on ECS (EC2 or Fargate launch types)
- Applications using Python language

## Implementation Steps

**Constraints:**
You must strictly follow the steps in the order below, do not skip or combine steps.

### Step 1: Setup CloudWatch Agent Task

When running in ECS, the CloudWatch Agent is deployed as a sidecar container next to the application container.

#### 1.1 Add CloudWatch Agent Permissions to ECS Task Role

Update ECS task role to add CloudWatchAgentServerPolicy:

```typescript
const taskRole = new iam.Role(this, 'EcsTaskRole', {
  assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('AWSXRayDaemonWriteAccess'),
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy'),
  ],
  inlinePolicies: {
    // Your existing inline policies...
  },
});
```

#### 1.2 Create CloudWatch Agent Log Group

```typescript
const cwAgentLogGroup = new logs.LogGroup(this, 'CwAgentLogGroup', {
  logGroupName: '/ecs/ecs-cwagent',
  removalPolicy: cdk.RemovalPolicy.DESTROY,
  retention: logs.RetentionDays.ONE_MONTH,
});
```

#### 1.3 Add CloudWatch Agent Container to Each Task Definition

```typescript
const cwAgentContainer = taskDefinition.addContainer('ecs-cwagent-{{SERVICE_NAME}}', {
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/cloudwatch-agent/cloudwatch-agent:latest'), // Use latest. ServiceEvents requires 1.300070.0+ (or 1.300069.0+).
  essential: false,
  memoryReservationMiB: 128,
  cpu: 64,
  environment: {
    CW_CONFIG_CONTENT: JSON.stringify({
      "traces": {
        "traces_collected": {
          "application_signals": {}
        }
      },
      "logs": {
        "metrics_collected": {
          "application_signals": {}
        }
      }
    }),
  },
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'ecs',
    logGroup: cwAgentLogGroup,
  }),
});
```

### Step 2: Add AWS Distro for OpenTelemetry Zero-Code Auto-Instrumentation to Main Service

#### 2.1 Add Bind Mount Volumes to Task Definition

```typescript
const taskDefinition = new ecs.FargateTaskDefinition(this, '{{SERVICE_NAME}}TaskDefinition', {
  // Existing configuration...
  volumes: [
    {
      name: "opentelemetry-auto-instrumentation-python"
    }
  ],
});
```

#### 2.2 Add ADOT Auto-instrumentation Init Container

```typescript
const initContainer = taskDefinition.addContainer('init', {
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/aws-observability/adot-autoinstrumentation-python:v0.18.0'), // Minimum version for ServiceEvents. Check ../application-signals-onboarding.md for how to query the latest version.
  essential: false,
  memoryReservationMiB: 64,
  cpu: 32,
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-python'],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'init-{{SERVICE_NAME}}',
    logGroup: serviceLogGroup,
  }),
});

initContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-python',
  containerPath: '/otel-auto-instrumentation-python',
  readOnly: false,
});
```

#### 2.3 Configure Main Application Container OpenTelemetry Environment Variables

```typescript
const mainContainer = taskDefinition.addContainer('{{SERVICE_NAME}}-container', {
  // Existing configuration...
  environment: {
    // Existing environment variables...

    // ADOT Configuration for Application Signals
    OTEL_RESOURCE_ATTRIBUTES: 'service.name={{SERVICE_NAME}}',
    OTEL_METRICS_EXPORTER: 'none',
    OTEL_LOGS_EXPORTER: 'none',
    PYTHONPATH: '/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:{{EXISTING_PYTHONPATH}}:/otel-auto-instrumentation-python',
    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED: 'true',
    OTEL_TRACES_EXPORTER: 'otlp',
    OTEL_EXPORTER_OTLP_PROTOCOL: 'http/protobuf',
    OTEL_PYTHON_DISTRO: 'aws_distro',
    OTEL_PYTHON_CONFIGURATOR: 'aws_configurator',
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: 'http://localhost:4316/v1/traces',
    OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT: 'http://localhost:4316/v1/metrics',
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED: 'true',
  },
});
```

Replace `{{EXISTING_PYTHONPATH}}` with the container's current `PYTHONPATH` value so the instrumentation paths are **prepended** to it rather than overwriting it. If the container does **not** already set a `PYTHONPATH`, drop that segment entirely:

```typescript
PYTHONPATH: '/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:/otel-auto-instrumentation-python',
```

#### 2.4 Add Mount Point to Main Container

```typescript
mainContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-python',
  containerPath: '/otel-auto-instrumentation-python',
  readOnly: false,
});
```

#### 2.5 Configure Container Dependencies

```typescript
mainContainer.addContainerDependencies({
  container: initContainer,
  condition: ecs.ContainerDependencyCondition.SUCCESS,
});

mainContainer.addContainerDependencies({
  container: cwAgentContainer,
  condition: ecs.ContainerDependencyCondition.START,
});
```

### Step 3: Apply Python Framework-Specific Changes

#### 3.a: Django-Specific Configuration

##### 3.a.1: Set DJANGO_SETTINGS_MODULE
If your ECS application is built with Django, explicitly set the DJANGO_SETTINGS_MODULE environment variable:

```typescript
const mainContainer = taskDefinition.addContainer('{{SERVICE_NAME}}-container', {
  environment: {
    // Existing environment variables...
    DJANGO_SETTINGS_MODULE: '{{your django settings}}'
  },
});
```

##### 3.a.2: Add --noreload When Using Django's Development Server
If using Django's development server, override the Docker CMD to add `--noreload`:

**Before (Dockerfile):**

```dockerfile
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

**After (ECS IaC override):**

```typescript
const appContainer = taskDefinition.addContainer('Application', {
  command: ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"],
});
```

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your application. Here's what I modified:

**Files Changed:**

- IAM role: Added CloudWatchAgentServerPolicy
- ECS container: Installed and configured CloudWatch Agent as sidecar
- ADOT SDK container: Mounted ADOT SDK dependencies into Application container
- Application container: Enabled zero-code auto-instrumentation for Application

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
