# Deployment with Infrastructure as Code

Deploy durable functions using CloudFormation, CDK, or SAM.

## Requirements

All durable functions require:

1. **DurableConfig** property on the function
2. **AWSLambdaBasicDurableExecutionRolePolicy** attached to execution role
3. **Qualified ARN** (version or alias) for invocation

## AWS CloudFormation

**template.yaml:**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  DurableFunctionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicDurableExecutionRolePolicy

  DurableFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: myDurableFunction
      Runtime: nodejs24.x  # or python3.14
      Handler: index.handler
      Role: !GetAtt DurableFunctionRole.Arn
      Code:
        ZipFile: |
          // Your durable function code
      DurableConfig:
        ExecutionTimeout: 3600        # Max execution time (seconds)
        RetentionPeriodInDays: 7      # How long to keep execution state
      Environment:
        Variables:
          LOG_LEVEL: INFO

  DurableFunctionVersion:
    Type: AWS::Lambda::Version
    Properties:
      FunctionName: !Ref DurableFunction

  DurableFunctionAlias:
    Type: AWS::Lambda::Alias
    Properties:
      FunctionName: !Ref DurableFunction
      FunctionVersion: !GetAtt DurableFunctionVersion.Version
      Name: live

Outputs:
  FunctionArn:
    Value: !GetAtt DurableFunction.Arn
  AliasArn:
    Value: !Ref DurableFunctionAlias
```

**Deploy:**

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name my-durable-function \
  --capabilities CAPABILITY_IAM
```

## AWS CDK

**TypeScript:**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';

export class DurableFunctionStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const durableFunction = new lambda.Function(this, 'DurableFunction', {
      runtime: lambda.Runtime.NODEJS_24_X,  // or PYTHON_3_14
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda'),
      durableConfig: {
        executionTimeout: cdk.Duration.hours(1),
        retentionPeriod: cdk.Duration.days(7)
      },
      environment: {
        LOG_LEVEL: 'INFO'
      }
    });

    // CDK automatically adds checkpoint permissions when durableConfig is set

    // Create version and alias
    const version = durableFunction.currentVersion;
    const alias = new lambda.Alias(this, 'LiveAlias', {
      aliasName: 'live',
      version: version
    });

    // Output the qualified ARN
    new cdk.CfnOutput(this, 'FunctionAliasArn', {
      value: alias.functionArn
    });
  }
}
```

**Deploy:**

```bash
cdk deploy
```

### CDK Custom Log Group Management

**Best Practice:** Explicitly create and manage CloudWatch Log Groups for better control over retention, cleanup, and costs.

```typescript
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';

// 1. Create explicit log group
const functionLogGroup = new logs.LogGroup(this, 'DurableFunctionLogGroup', {
  logGroupName: '/aws/lambda/myDurableFunction',
  retention: logs.RetentionDays.ONE_WEEK,
  removalPolicy: cdk.RemovalPolicy.DESTROY,  // Delete on stack destroy
});

// 2. Link to function
const durableFunction = new lambda.Function(this, 'DurableFunction', {
  runtime: lambda.Runtime.NODEJS_24_X,
  handler: 'index.handler',
  code: lambda.Code.fromAsset('lambda'),
  logGroup: functionLogGroup,  // Link to managed log group
  durableConfig: {
    executionTimeout: cdk.Duration.hours(1),
    retentionPeriod: cdk.Duration.days(7)
  }
});

// 3. Add durable execution policy (required with explicit log groups)
durableFunction.role?.addManagedPolicy(
  iam.ManagedPolicy.fromAwsManagedPolicyName(
    'service-role/AWSLambdaBasicDurableExecutionRolePolicy'
  )
);
```

**Benefits:**

- **Explicit Cleanup**: `removalPolicy: cdk.RemovalPolicy.DESTROY` ensures log groups are deleted when stack is destroyed
- **Custom Retention**: Set retention periods matching compliance/debugging needs
- **Predictable Naming**: Control exact log group name
- **Cost Control**: Avoid accumulating costs from orphaned log groups

**When to use:**

- ✅ Production environments where log retention policies must be enforced
- ✅ Development/test environments where automatic cleanup saves costs
- ✅ Multi-function stacks where consistent log management is needed

**Important:** Don't forget to add `AWSLambdaBasicDurableExecutionRolePolicy` when using explicit log groups.

## AWS SAM

**template.yaml:**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Globals:
  Function:
    Timeout: 900
    MemorySize: 512

Resources:
  DurableFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: myDurableFunction
      Runtime: nodejs24.x  # or python3.14
      Handler: index.handler
      CodeUri: ./src
      DurableConfig:
        ExecutionTimeout: 3600
        RetentionPeriodInDays: 7
      Policies:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicDurableExecutionRolePolicy
      AutoPublishAlias: live
      Environment:
        Variables:
          LOG_LEVEL: INFO

Outputs:
  FunctionArn:
    Value: !GetAtt DurableFunction.Arn
  AliasArn:
    Value: !Ref DurableFunction.Alias
```

**Deploy:**

```bash
sam build
sam deploy --guided
```

## Durable Invokes

For functions that invoke other durable functions:

**CloudFormation:**

```yaml
DurableFunctionRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicDurableExecutionRolePolicy
    Policies:
      - PolicyName: InvokeOtherFunctions
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action:
                - lambda:InvokeFunction
              Resource:
                - !GetAtt TargetFunction.Arn
                - !Sub '${TargetFunction.Arn}:*'  # For versions/aliases
```

**CDK:**

```typescript
const targetFunction = new lambda.Function(this, 'TargetFunction', {
  // ... configuration
});

const orchestratorFunction = new lambda.Function(this, 'OrchestratorFunction', {
  // ... configuration with durableConfig
});

// Grant invoke permission
targetFunction.grantInvoke(orchestratorFunction);
```

## External Callbacks

For external systems to send callbacks:

**IAM Policy:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:SendDurableExecutionCallbackSuccess",
        "lambda:SendDurableExecutionCallbackFailure",
        "lambda:SendDurableExecutionCallbackHeartbeat"
      ],
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:myDurableFunction:*"
    }
  ]
}
```

## Environment Configuration

**Development:**

```yaml
DurableFunction:
  Type: AWS::Lambda::Function
  Properties:
    DurableConfig:
      ExecutionTimeout: 900          # 15 minutes
      RetentionPeriodInDays: 1       # Short retention
    Environment:
      Variables:
        LOG_LEVEL: DEBUG             # Use INFO or higher in non-dev — DEBUG may expose step results and execution state
        ENVIRONMENT: development
```

**Production:**

```yaml
DurableFunction:
  Type: AWS::Lambda::Function
  Properties:
    DurableConfig:
      ExecutionTimeout: 86400        # 24 hours
      RetentionPeriodInDays: 30      # Long retention
    Environment:
      Variables:
        LOG_LEVEL: INFO
        ENVIRONMENT: production
```

## Multi-Environment Deployment

**CDK with Stages:**

```typescript
const app = new cdk.App();

new DurableFunctionStack(app, 'DurableFunction-Dev', {
  env: { account: '123456789012', region: 'us-east-1' },
  stage: 'dev',
  durableConfig: {
    executionTimeout: cdk.Duration.minutes(15),
    retentionPeriod: cdk.Duration.days(1)
  }
});

new DurableFunctionStack(app, 'DurableFunction-Prod', {
  env: { account: '123456789012', region: 'us-east-1' },
  stage: 'prod',
  durableConfig: {
    executionTimeout: cdk.Duration.hours(24),
    retentionPeriod: cdk.Duration.days(30)
  }
});
```

## Invocation Examples

### Critical Requirements

**⚠️ Important Invocation Rules:**

1. **Qualified Function Name Required**: You MUST provide a qualified function name with version, alias, or `:$LATEST`
2. **Idempotency with durable-execution-name**: Use this parameter to ensure the same execution name always refers to the same execution
3. **Binary Format**: Use `--cli-binary-format raw-in-base64-out` to avoid base64 encoding issues

### Synchronous Invocation (RequestResponse)

Synchronous invocation waits for the function to complete and returns the result immediately. Suitable for short workflows.

```bash
aws lambda invoke \
  --function-name 'myDurableFunction:$LATEST' \
  --invocation-type RequestResponse \
  --durable-execution-name "execution-123" \
  --payload '{"userId":"12345","action":"process"}' \
  --cli-binary-format raw-in-base64-out \
  --output json \
  response.json

# View the response
cat response.json
```

**When to use RequestResponse:**

- Short-running workflows (under 15 minutes total)
- When you need the result immediately
- Interactive applications requiring synchronous responses

### Asynchronous Invocation (Event)

Asynchronous invocation returns immediately with the execution ID. Ideal for long-running workflows.

```bash
aws lambda invoke \
  --function-name 'myDurableFunction:$LATEST' \
  --invocation-type Event \
  --durable-execution-name "background-task-456" \
  --payload '{"orderId":"ORD-789","amount":99.99}' \
  --cli-binary-format raw-in-base64-out \
  --output json \
  response.json

# Response contains execution ID, not the result
cat response.json
```

**When to use Event:**

- Long-running workflows (hours, days, or longer)
- Background processing tasks
- Workflows with wait operations or human-in-the-loop steps

### Idempotency with durable-execution-name

The `--durable-execution-name` parameter ensures that the same execution is never created twice:

```bash
# First invocation - creates new execution
aws lambda invoke \
  --function-name 'myDurableFunction:$LATEST' \
  --invocation-type RequestResponse \
  --durable-execution-name "order-processing-ORD-123" \
  --payload '{"orderId":"ORD-123"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

# Second invocation with same execution name - returns existing execution result
aws lambda invoke \
  --function-name 'myDurableFunction:$LATEST' \
  --invocation-type RequestResponse \
  --durable-execution-name "order-processing-ORD-123" \
  --payload '{"orderId":"ORD-123"}' \
  --cli-binary-format raw-in-base64-out \
  response.json
```

### Using Specific Function Versions

Durable functions require qualified ARNs (version, alias, or `$LATEST`):

```bash
# ✅ Invoke specific version
aws lambda invoke \
  --function-name 'myDurableFunction:1' \
  --invocation-type RequestResponse \
  --durable-execution-name "versioned-exec-1" \
  --payload '{"test":"data"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

# ✅ Invoke using alias
aws lambda invoke \
  --function-name 'myDurableFunction:live' \
  --invocation-type RequestResponse \
  --durable-execution-name "my-exec-1" \
  --payload '{"test":"data"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

# ❌ Unqualified - will fail!
aws lambda invoke \
  --function-name 'myDurableFunction' \
  --payload '{"test":"data"}' \
  response.json
# Error: Durable execution requires qualified function identifier
```

## Monitoring and Observability

**CloudWatch Logs:**

```yaml
DurableFunction:
  Type: AWS::Lambda::Function
  Properties:
    # ... other properties
    LoggingConfig:
      LogFormat: JSON
      LogGroup: !Ref DurableFunctionLogGroup

DurableFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: /aws/lambda/myDurableFunction
    RetentionInDays: 7
```

**CloudWatch Alarms:**

```yaml
DurableFunctionErrorAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: DurableFunction-Errors
    MetricName: Errors
    Namespace: AWS/Lambda
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 1
    Threshold: 5
    ComparisonOperator: GreaterThanThreshold
    Dimensions:
      - Name: FunctionName
        Value: !Ref DurableFunction
```

## Best Practices

1. **Always use qualified ARNs** (versions or aliases) for invocation
2. **Set appropriate execution timeouts** based on workflow duration
3. **Configure retention periods** to balance cost and debugging needs
4. **Use aliases** for production deployments
5. **Grant minimal IAM permissions** - only what's needed
6. **Enable structured logging** (JSON format)
7. **Set up CloudWatch alarms** for errors and throttles
8. **Use environment variables** for configuration
9. **Deploy to multiple environments** (dev, staging, prod)
10. **Version your infrastructure code** alongside function code

## Common issues

### Function Not Durable

**Issue:** Function executes but doesn't checkpoint.

**Solution:** Verify `DurableConfig` is set and role has checkpoint permissions.

### Invocation Fails with "Unqualified ARN"

**Issue:** `InvalidParameterValueException: Durable execution requires qualified function identifier`

**Solution:** Use version, alias, or `$LATEST`:

```bash
# ✅ Correct
aws lambda invoke --function-name myFunction:live ...
aws lambda invoke --function-name myFunction:1 ...

# ❌ Wrong
aws lambda invoke --function-name myFunction ...
```

### Checkpoint Permission Denied

**Issue:** `AccessDeniedException: User is not authorized to perform: lambda:CheckpointDurableExecution`

**Solution:** Add `AWSLambdaBasicDurableExecutionRolePolicy` to execution role.
