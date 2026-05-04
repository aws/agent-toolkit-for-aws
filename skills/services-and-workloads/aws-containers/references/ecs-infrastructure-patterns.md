# ECS Infrastructure Patterns

## Table of Contents

- [Verify Dependencies](#verify-dependencies)
- [L3 Construct Overview](#l3-construct-overview)
- [Web App on Fargate](#web-app-on-fargate)
- [SQS Worker](#sqs-worker)
- [Scheduled Task](#scheduled-task)
- [Path-Based Routing](#path-based-routing)
- [EFS Volume](#efs-volume)
- [ECS Exec Setup](#ecs-exec-setup)
- [Private Subnets with VPC Endpoints](#private-subnets-with-vpc-endpoints)
- [FireLens Logging](#firelens-logging)
- [Secrets with Explicit Role Separation](#secrets-with-explicit-role-separation)
- [CloudFormation YAML Template for Fargate](#cloudformation-yaml-template-for-fargate)
- [Security Considerations](#security-considerations)

---

## Verify Dependencies

Operators MUST confirm the following before proceeding:

| Dependency | Check Command |
|---|---|
| Correct account/region | `aws sts get-caller-identity --output json` |
| CDK bootstrapped in target account | `cdk bootstrap aws://$ACCOUNT_ID/$REGION` |

---

## L3 Construct Overview

| Pattern | Construct | Module | Use Case |
|---|---|---|---|
| Web App (ALB + Fargate) | `ApplicationLoadBalancedFargateService` | `aws-ecs-patterns` | HTTP/HTTPS services behind ALB |
| Web App (NLB + Fargate) | `NetworkLoadBalancedFargateService` | `aws-ecs-patterns` | TCP/UDP services, static IP |
| SQS Worker | `QueueProcessingFargateService` | `aws-ecs-patterns` | Queue-driven background processing |
| Scheduled Task | `ScheduledFargateTask` | `aws-ecs-patterns` | Cron jobs, periodic batch work |
| Web App (ALB + EC2) | `ApplicationLoadBalancedEc2Service` | `aws-ecs-patterns` | HTTP/HTTPS on EC2 launch type |
| SQS Worker (EC2) | `QueueProcessingEc2Service` | `aws-ecs-patterns` | Queue processing on EC2 launch type |

**When to drop to L2 constructs:** Use L2 (`ecs.FargateService` + `elbv2.ApplicationLoadBalancer`) when you need multiple services behind one ALB, custom task definitions with multiple containers, fine-grained log driver configuration (`mode: blocking`), or EFS volumes. L3 patterns don't expose these.

---

## Web App on Fargate

```typescript
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecsPatterns from 'aws-cdk-lib/aws-ecs-patterns';

const service = new ecsPatterns.ApplicationLoadBalancedFargateService(this, 'WebApp', {
  cluster,
  taskImageOptions: {
    image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
    containerPort: $CONTAINER_PORT,
    environment: {
      NODE_ENV: 'staging',
    },
  },
  desiredCount: 2,
  circuitBreaker: { rollback: true },
  publicLoadBalancer: true,
});

// Reduce deregistration delay for faster deployments
service.targetGroup.setAttribute('deregistration_delay.timeout_seconds', '30');

// Auto scaling
const scaling = service.service.autoScaleTaskCount({
  minCapacity: 2,
  maxCapacity: 10,
});

scaling.scaleOnCpuUtilization('CpuScaling', {
  targetUtilizationPercent: 60,
});

scaling.scaleOnRequestCount('RequestScaling', {
  requestsPerTarget: 1000,
  targetGroup: service.targetGroup,
});
```

Key points:

- `circuitBreaker: { rollback: true }` MUST be set — this automatically rolls back failed deployments instead of leaving the service in a degraded state. In CDK, specifying the `circuitBreaker` property implicitly enables it (`enable` is optional and defaults to `true`).
- Operators SHOULD reduce `deregistration_delay.timeout_seconds` from the default 300s. A value of 30s is appropriate for most web services.
- `setAttribute` is used because the L3 pattern does not expose deregistration delay in its props (the underlying `ApplicationTargetGroup` has a `deregistrationDelay` property, but the L3 pattern doesn't pass it through).

**Validate before deploying:** `cdk synth` to catch type errors and missing props → `cdk diff` to review changes → `cdk deploy` only after validation passes.

- To set `mode: blocking` for guaranteed log delivery (see CloudFormation section for rationale), use a custom task definition instead of `taskImageOptions`:

```typescript
const taskDef = new ecs.FargateTaskDefinition(this, 'TaskDef', { cpu: 512, memoryLimitMiB: 1024 });
taskDef.addContainer('App', {
  image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
  portMappings: [{ containerPort: 8080 }],
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'app',
    mode: ecs.AwsLogDriverMode.BLOCKING,
  }),
});
```

---

## SQS Worker

```typescript
import * as ecsPatterns from 'aws-cdk-lib/aws-ecs-patterns';

const worker = new ecsPatterns.QueueProcessingFargateService(this, 'Worker', {
  cluster,
  image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
  environment: {
    WORKER_TYPE: 'processor',
  },
  minScalingCapacity: 1,
  maxScalingCapacity: 20,
  scalingSteps: [
    { upper: 0, change: -1 },
    { lower: 1, change: +1 },
    { lower: 50, change: +3 },
    { lower: 200, change: +5 },
  ],
  cpu: 512,
  memoryLimitMiB: 1024,
  circuitBreaker: { rollback: true },
});
```

Key points:

- `scalingSteps` defines step scaling based on the `ApproximateNumberOfMessagesVisible` metric on the SQS queue.

---

## Scheduled Task

```typescript
import * as ecsPatterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as appscaling from 'aws-cdk-lib/aws-applicationautoscaling';

new ecsPatterns.ScheduledFargateTask(this, 'NightlyJob', {
  cluster,
  scheduledFargateTaskImageOptions: {
    image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
    memoryLimitMiB: 2048,
    cpu: 1024,
    environment: {
      JOB_NAME: 'nightly-report',
    },
  },
  schedule: appscaling.Schedule.expression('cron(0 3 * * ? *)'),
  platformVersion: ecs.FargatePlatformVersion.LATEST,
});
```

---

## Path-Based Routing

```typescript
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';

const alb = new elbv2.ApplicationLoadBalancer(this, 'ALB', {
  vpc,
  internetFacing: true,
});

const listener = alb.addListener('Listener', { port: 80 });

// Service A: /api/*
const serviceA = new ecs.FargateService(this, 'ApiService', {
  cluster,
  taskDefinition: apiTaskDef,
  healthCheckGracePeriod: cdk.Duration.seconds(60),
});

const targetGroupA = listener.addTargets('ApiTarget', {
  port: $CONTAINER_PORT,
  targets: [serviceA],
  conditions: [elbv2.ListenerCondition.pathPatterns(['/api/*'])],
  priority: 10,
  healthCheck: {
    path: '/api/health',
    interval: cdk.Duration.seconds(30),
  },
});

// Service B: /* (default)
const serviceB = new ecs.FargateService(this, 'WebService', {
  cluster,
  taskDefinition: webTaskDef,
  healthCheckGracePeriod: cdk.Duration.seconds(60),
});

listener.addTargets('WebTarget', {
  port: $CONTAINER_PORT,
  targets: [serviceB],
  healthCheck: {
    path: '/health',
    interval: cdk.Duration.seconds(30),
  },
});
```

Key points:

- Rules with `conditions` MUST have a `priority` — lower numbers evaluate first.
- `healthCheckGracePeriod` SHOULD be tuned on each service if the default 60 seconds is insufficient for the application's startup time. CDK defaults to 60s when a load balancer is attached.

---

## EFS Volume

```typescript
import * as efs from 'aws-cdk-lib/aws-efs';
import * as ecs from 'aws-cdk-lib/aws-ecs';

const fileSystem = new efs.FileSystem(this, 'SharedFS', {
  vpc,
  encrypted: true,
  performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
  removalPolicy: cdk.RemovalPolicy.RETAIN,
});

const taskDef = new ecs.FargateTaskDefinition(this, 'TaskDef', {
  cpu: 512,
  memoryLimitMiB: 1024,
});

taskDef.addVolume({
  name: 'efs-volume',
  efsVolumeConfiguration: {
    fileSystemId: fileSystem.fileSystemId,
  },
});

const container = taskDef.addContainer('App', {
  image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
});

container.addMountPoints({
  sourceVolume: 'efs-volume',
  containerPath: '/mnt/data',
  readOnly: false,
});

const service = new ecs.FargateService(this, 'Service', {
  cluster,
  taskDefinition: taskDef,
});

// CRITICAL: Allow ECS tasks to connect to EFS on port 2049
fileSystem.connections.allowDefaultPortFrom(service);
```

Key points:

- `allowDefaultPortFrom` opens NFS port 2049 from the ECS service security group to the EFS security group. Without this, tasks WILL hang on mount with timeout errors.
- `removalPolicy: RETAIN` prevents accidental deletion of persistent data.

---

## ECS Exec Setup

```typescript
const taskDef = new ecs.FargateTaskDefinition(this, 'TaskDef', {
  cpu: 512,
  memoryLimitMiB: 1024,
});

const service = new ecs.FargateService(this, 'Service', {
  cluster,
  taskDefinition: taskDef,
  enableExecuteCommand: true, // Automatically grants the 4 required ssmmessages actions to the task role
});
```

> **CRITICAL**: `enableExecuteCommand: true` automatically grants the task role the 4 required `ssmmessages` actions (`CreateControlChannel`, `CreateDataChannel`, `OpenControlChannel`, `OpenDataChannel`). No manual policy attachment is needed in CDK. For CloudFormation, add an inline policy with these 4 actions on the task role.
> **CRITICAL**: SSM permissions MUST be on the **task role**, NOT the execution role. The execution role is used by the ECS agent to pull images and write logs. The task role is assumed by the running container — ECS Exec runs inside the container and therefore needs SSM permissions on the task role.

Common mistake:

```typescript
// WRONG — this will NOT work for ECS Exec
taskDef.executionRole.addManagedPolicy(
  iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore')
);
```

Verify ECS Exec after deployment:

```bash
aws ecs execute-command \
  --cluster $CLUSTER \
  --task $TASK_ID \
  --container $CONTAINER_NAME \
  --interactive \
  --command "/bin/sh" \
  --region $REGION
```

---

## Private Subnets with VPC Endpoints

When running ECS tasks in private subnets without a NAT gateway, operators MUST create these 4 VPC endpoints:

```typescript
// 1. ECR Docker — pull container images
vpc.addInterfaceEndpoint('EcrDockerEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
});

// 2. ECR API — authenticate with ECR
vpc.addInterfaceEndpoint('EcrApiEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.ECR,
});

// 3. CloudWatch Logs — push container logs
vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
  service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
});

// 4. S3 Gateway — ECR stores image layers in S3
vpc.addGatewayEndpoint('S3Endpoint', {
  service: ec2.GatewayVpcEndpointAwsService.S3,
});
```

| Endpoint | Type | Purpose |
|---|---|---|
| `ECR_DOCKER` | Interface | Pull container images |
| `ECR` | Interface | ECR API authentication |
| `CLOUDWATCH_LOGS` | Interface | Container log delivery |
| `S3` | Gateway | ECR image layer storage (no cost) |

Additional endpoints MAY be needed:

| Endpoint | When Required |
|---|---|
| `ssmmessages` | ECS Exec |
| `secretsmanager` | Secrets Manager references in task definition |
| `ssm` | SSM Parameter Store references in task definition |

---

## FireLens Logging

```typescript
// Log router sidecar — SHOULD be essential:true (AWS recommended)
const logRouter = taskDef.addFirelensLogRouter('LogRouter', {
  image: ecs.ContainerImage.fromRegistry('amazon/aws-for-fluent-bit:latest'),
  essential: true,
  firelensConfig: {
    type: ecs.FirelensLogRouterType.FLUENTBIT,
  },
  // Log router's OWN logs MUST use awslogs, NOT awsfirelens
  logging: ecs.LogDrivers.awsLogs({
    streamPrefix: 'firelens',
    logGroup,
  }),
});

// Application container uses awsfirelens driver
const appContainer = taskDef.addContainer('App', {
  image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
  essential: true,
  logging: ecs.LogDrivers.firelens({
    options: {
      Name: 'cloudwatch_logs',
      region: '$REGION',
      log_group_name: '$LOG_GROUP',
      log_stream_prefix: 'app/',
      auto_create_group: 'true',
    },
  }),
});
```

Key rules:

- The log router container SHOULD have `essential: true` (AWS recommends this). If it crashes and is not essential, logs are silently lost with no indication.
- The log router MUST use `awslogs` for its own logs, NOT `awsfirelens`. Using `awsfirelens` for the log router creates a circular dependency that prevents the task from starting.
- Application containers use `awsfirelens` to route logs through the FireLens sidecar.

---

## Secrets with Explicit Role Separation

```typescript
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';

const dbSecret = secretsmanager.Secret.fromSecretNameV2(this, 'DbSecret', '$SECRET_NAME');

const taskDef = new ecs.FargateTaskDefinition(this, 'TaskDef', {
  cpu: 512,
  memoryLimitMiB: 1024,
});

const container = taskDef.addContainer('App', {
  image: ecs.ContainerImage.fromRegistry('$IMAGE_URI'),
  secrets: {
    DB_PASSWORD: ecs.Secret.fromSecretsManager(dbSecret, 'password'),
  },
});

// CDK automatically grants the execution role read access to secrets
// specified in the secrets block (via ContainerDefinition.addSecret).
// An explicit grantRead is only needed if the secret is fetched at
// runtime by the task role and not referenced in the task definition.
```

Role separation:

| Role | Purpose | Needs Secret Access When |
|---|---|---|
| **Execution role** | Used by ECS agent to pull images, push logs, and inject secrets at task start | Secrets are referenced in the task definition `secrets` block |
| **Task role** | Used by the running application code | Application calls Secrets Manager API at runtime |

- If secrets are injected via the task definition `secrets` block, `grantRead` MUST target the **execution role**.
- If the application fetches secrets at runtime via SDK calls, `grantRead` MUST target the **task role**.
- Operators SHOULD NOT grant secret access to both roles unless both access patterns are used.

---

## CloudFormation YAML Template for Fargate

For operators who need raw CloudFormation instead of CDK:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: ECS Fargate service with ALB

Parameters:
  ClusterName:
    Type: String
  ImageUri:
    Type: String
  ContainerPort:
    Type: Number
    Default: 8080
  VpcId:
    Type: AWS::EC2::VPC::Id
  PublicSubnetIds:
    Type: List<AWS::EC2::Subnet::Id>
    Description: Public subnets for the internet-facing ALB
  PrivateSubnetIds:
    Type: List<AWS::EC2::Subnet::Id>
    Description: Private subnets for ECS tasks (must have NAT gateway or VPC endpoints)
  CertificateArn:
    Type: String
    Description: ARN of the ACM certificate for HTTPS
  DesiredCount:
    Type: Number
    Default: 2

Resources:
  TaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      Family: !Sub '${ClusterName}-task'
      Cpu: '512'
      Memory: '1024'
      NetworkMode: awsvpc
      RequiresCompatibilities:
        - FARGATE
      ExecutionRoleArn: !GetAtt ExecutionRole.Arn
      TaskRoleArn: !GetAtt TaskRole.Arn
      ContainerDefinitions:
        - Name: app
          Image: !Ref ImageUri
          PortMappings:
            - ContainerPort: !Ref ContainerPort
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref LogGroup
              awslogs-region: !Ref 'AWS::Region'
              awslogs-stream-prefix: app
              mode: blocking

  Service:
    Type: AWS::ECS::Service
    DependsOn: ListenerRule
    Properties:
      Cluster: !Ref ClusterName
      TaskDefinition: !Ref TaskDefinition
      DesiredCount: !Ref DesiredCount
      LaunchType: FARGATE
      DeploymentConfiguration:
        DeploymentCircuitBreaker:
          Enable: true
          Rollback: true
      NetworkConfiguration:
        AwsvpcConfiguration:
          Subnets: !Ref PrivateSubnetIds
          SecurityGroups:
            - !Ref ServiceSG
      LoadBalancers:
        - ContainerName: app
          ContainerPort: !Ref ContainerPort
          TargetGroupArn: !Ref TargetGroup
      HealthCheckGracePeriodSeconds: 60

  ServiceSG:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: ECS service security group
      VpcId: !Ref VpcId
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: !Ref ContainerPort
          ToPort: !Ref ContainerPort
          SourceSecurityGroupId: !Ref AlbSG

  AlbSG:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: ALB security group
      VpcId: !Ref VpcId
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 443
          ToPort: 443
          CidrIp: 0.0.0.0/0

  LogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/ecs/${ClusterName}'
      RetentionInDays: 30

  ExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ecs-tasks.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

  TaskRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ecs-tasks.amazonaws.com
            Action: sts:AssumeRole

  TargetGroup:
    Type: AWS::ElasticLoadBalancingV2::TargetGroup
    Properties:
      Port: !Ref ContainerPort
      Protocol: HTTP
      VpcId: !Ref VpcId
      TargetType: ip
      HealthCheckPath: /health
      HealthCheckIntervalSeconds: 30
      TargetGroupAttributes:
        - Key: deregistration_delay.timeout_seconds
          Value: '30'

  ALB:
    Type: AWS::ElasticLoadBalancingV2::LoadBalancer
    Properties:
      Scheme: internet-facing
      SecurityGroups:
        - !Ref AlbSG
      Subnets: !Ref PublicSubnetIds

  Listener:
    Type: AWS::ElasticLoadBalancingV2::Listener
    Properties:
      LoadBalancerArn: !Ref ALB
      Port: 443
      Protocol: HTTPS
      SslPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06
      Certificates:
        - CertificateArn: !Ref CertificateArn
      DefaultActions:
        - Type: forward
          TargetGroupArn: !Ref TargetGroup

  # This rule is functionally redundant with the Listener's DefaultActions (both forward to the same TargetGroup).
  # It exists so the Service resource can use DependsOn: ListenerRule to ensure listener infrastructure is ready
  # before ECS registers targets. To remove it, change Service DependsOn to reference the Listener instead.
  ListenerRule:
    Type: AWS::ElasticLoadBalancingV2::ListenerRule
    Properties:
      ListenerArn: !Ref Listener
      Priority: 1
      Conditions:
        - Field: path-pattern
          Values:
            - '/*'
      Actions:
        - Type: forward
          TargetGroupArn: !Ref TargetGroup
```

Key points:

- `DeploymentCircuitBreaker` with `Rollback: true` MUST be enabled.
- `mode: blocking` MUST be set in log configuration for guaranteed log delivery. The ECS `defaultLogDriverMode` account setting defaults to `non-blocking`, which drops logs when the buffer fills. Without an explicit `mode: blocking`, tasks inherit the account default and may silently drop logs under backpressure.
- Security group ingress uses `SourceSecurityGroupId` (ALB → service) rather than open CIDR ranges.
- The ALB security group uses `0.0.0.0/0` per [AWS recommended rules for internet-facing ALBs](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-update-security-groups.html). For internal-only services, use `Scheme: internal` with VPC CIDR instead.
- For production internet-facing ALBs, attach an [AWS WAF WebACL](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl.html) for defense in depth against common web exploits.
- Operators SHOULD NOT log sensitive data (secrets, PII, tokens) to container stdout/stderr — these flow to CloudWatch Logs via the awslogs driver. Enable CloudWatch Logs encryption with a KMS key if sensitive data may appear in logs.
- `HealthCheckGracePeriodSeconds` SHOULD be set when using a load balancer (CDK defaults to 60s when a load balancer is attached).
- **Validate before deploying:** `aws cloudformation validate-template --template-body file://template.yaml`

---

## Security Considerations

- **Encryption at rest**: EFS volumes MUST use `encrypted: true`. CloudWatch Log Groups SHOULD use a KMS key for encryption when logs may contain sensitive data. ECR repositories encrypt images at rest by default (AES-256).
- **Encryption in transit**: ALBs SHOULD use HTTPS listeners with ACM certificates and a modern TLS policy (`ELBSecurityPolicy-TLS13-1-2-2021-06` or newer). EFS traffic is encrypted in transit when using the TLS mount helper.
- **IAM least privilege**: Task roles MUST be scoped to specific resources — avoid `*` wildcards and `*FullAccess` policies. The execution role should use `AmazonECSTaskExecutionRolePolicy` (managed, scoped) plus only the additional permissions needed (e.g., Secrets Manager access for specific secrets).
- **Secrets management**: Use `ecs.Secret.fromSecretsManager()` or `ecs.Secret.fromSsmParameter()` — never pass secrets via `environment` variables in plain text.
- **Network security**: Use private subnets with VPC endpoints for production workloads. The service security group should only allow inbound from the ALB security group (via `SourceSecurityGroupId`), not open CIDRs.
- **Web application protection**: Attach [AWS WAF](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl.html) to internet-facing ALBs. Add security headers (CSP, HSTS, X-Frame-Options) at the application level or via ALB response header insertion.
- **Monitoring**: Enable [CloudWatch Container Insights](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-container-insights.html) for cluster and service metrics. Enable [CloudTrail](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html) for ECS API audit logging.
- **Reference**: [ECS Security Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/security.html)
