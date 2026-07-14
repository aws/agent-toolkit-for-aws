# Enable AWS Application Signals for Node.js on ECS

## Overview
This guide provides complete steps to enable AWS Application Signals for ECS services (both EC2 and Fargate launch types), including distributed tracing, performance monitoring, and service mapping.

## Prerequisites

- Services running on ECS (EC2 or Fargate launch types)
- Applications using Node.js language

## Implementation Steps

**Constraints:**
You must strictly follow the steps in the order below, do not skip or combine steps.

### Step 1: Setup CloudWatch Agent Task

#### 1.1 Add CloudWatch Agent Permissions to ECS Task Role

```typescript
const taskRole = new iam.Role(this, 'EcsTaskRole', {
  assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('AWSXRayDaemonWriteAccess'),
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy'),
  ],
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
      name: "opentelemetry-auto-instrumentation-node"
    }
  ],
});
```

#### 2.2 Add ADOT Auto-instrumentation Init Container

```typescript
const initContainer = taskDefinition.addContainer('init', {
  image: ecs.ContainerImage.fromRegistry('public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0'), // Minimum version for ServiceEvents. Check ../application-signals-onboarding.md for how to query the latest version.
  essential: false,
  memoryReservationMiB: 64,
  cpu: 32,
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-node'],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'init-{{SERVICE_NAME}}',
    logGroup: serviceLogGroup,
  }),
});

initContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-node',
  containerPath: '/otel-auto-instrumentation-node',
  readOnly: false,
});
```

#### 2.3 Configure Main Application Container OpenTelemetry Environment Variables

```typescript
const mainContainer = taskDefinition.addContainer('{{SERVICE_NAME}}-container', {
  // Existing configuration...
  environment: {
    // Existing environment variables...

    // ADOT Configuration for Application Signals - Node.js
    OTEL_RESOURCE_ATTRIBUTES: 'service.name={{SERVICE_NAME}}',
    OTEL_METRICS_EXPORTER: 'none',
    OTEL_LOGS_EXPORTER: 'none',
    NODE_OPTIONS: '--require /otel-auto-instrumentation-node/autoinstrumentation.js', // CommonJS
    OTEL_TRACES_EXPORTER: 'otlp',
    OTEL_EXPORTER_OTLP_PROTOCOL: 'http/protobuf',
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: 'http://localhost:4316/v1/traces',
    OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT: 'http://localhost:4316/v1/metrics',
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED: 'true',
  },
});
```

**Module format note:**

- If the project uses **CommonJS**: `NODE_OPTIONS: '--require /otel-auto-instrumentation-node/autoinstrumentation.js'`
- If the project uses **ESM**: `NODE_OPTIONS: '--import /otel-auto-instrumentation-node/autoinstrumentation.js --experimental-loader=/otel-auto-instrumentation-node/node_modules/@opentelemetry/instrumentation/instrumentation/hook.mjs'`

#### 2.4 Add Mount Point to Main Container

```typescript
mainContainer.addMountPoints({
  sourceVolume: 'opentelemetry-auto-instrumentation-node',
  containerPath: '/otel-auto-instrumentation-node',
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

**Monitor Application Health:**
After enablement, you can monitor your application's operational health using Application Signals dashboards. For more information, see [Monitor the operational health of your applications with Application Signals](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Services.html).

**Troubleshooting**
If you encounter any other issues, refer to the [CloudWatch APM troubleshooting guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Troubleshoot.html).

Let me know if you'd like me to make any adjustments before you deploy!"
