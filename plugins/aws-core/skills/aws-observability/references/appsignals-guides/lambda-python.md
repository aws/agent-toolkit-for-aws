# Enable AWS Application Signals for Python on AWS Lambda

Your task is to modify Infrastructure as Code (IaC) files to enable AWS Application Signals for Python Lambda functions. You will:

1. Add IAM permissions for Application Signals
2. Configure X-Ray tracing
3. Add the ADOT Lambda layer
4. Set the required environment variables.

If you cannot determine a value (such as AWS Region): Ask the user for clarification before proceeding. Do not guess or make up values.

## Region-Specific Layer ARNs

The ADOT Lambda layer ARN is region-specific, and its **layer version changes over time**. Do **not** hardcode a version from this guide — look up the current value from the source of truth, which lists **all supported regions and the latest layer version**:

- Source of truth: https://raw.githubusercontent.com/aws-otel/aws-otel.github.io/refs/heads/main/src/config/lambdaLayerArns.js
- (Backup / human-readable: https://github.com/aws-otel/aws-otel.github.io/blob/main/src/config/lambdaLayerArns.js)

ARN format — fill in `<REGION>` and `<LAYER_VERSION>` (the latest version for that region from the source above):

```
arn:aws:lambda:<REGION>:<ACCOUNT_ID>:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
```

A few sample regions (illustrative — confirm the current `<LAYER_VERSION>` and account ID from the source of truth, and use it for **any** supported region, not just these):

```
us-east-1:      arn:aws:lambda:us-east-1:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
us-west-2:      arn:aws:lambda:us-west-2:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
ca-central-1:   arn:aws:lambda:ca-central-1:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
ap-east-1:      arn:aws:lambda:ap-east-1:888577020596:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
ap-southeast-1: arn:aws:lambda:ap-southeast-1:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
eu-west-1:      arn:aws:lambda:eu-west-1:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
eu-south-1:     arn:aws:lambda:eu-south-1:257394471194:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
...
```

> Note: some partitions use a different ARN prefix and account ID (`arn:aws-cn:` for China, `arn:aws-us-gov:` for GovCloud). The source of truth has the exact ARN for every supported region.

## Instructions

### Step 1: Add IAM Permissions

Add the AWS managed policy `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` to the Lambda function's execution role.

**CDK:**

```typescript
const role = new iam.Role(this, 'LambdaRole', {
  assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
    iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchLambdaApplicationSignalsExecutionRolePolicy'),
  ],
});
```

**Terraform:**

```hcl
resource "aws_iam_role_policy_attachment" "application_signals" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLambdaApplicationSignalsExecutionRolePolicy"
}
```

**CloudFormation:**

```yaml
ManagedPolicyArns:
  - arn:aws:iam::aws:policy/CloudWatchLambdaApplicationSignalsExecutionRolePolicy
```

### Step 2: Enable X-Ray Active Tracing

**CDK:**

```typescript
const myFunction = new lambda.Function(this, 'MyFunction', {
  tracing: lambda.Tracing.ACTIVE,
});
```

**Terraform:**

```hcl
resource "aws_lambda_function" "my_function" {
  tracing_config {
    mode = "Active"
  }
}
```

**CloudFormation:**

```yaml
TracingConfig:
  Mode: Active
```

### Step 3: Add ADOT Python Lambda Layer

Use the layer name `AWSOpenTelemetryDistroPython` with automatic region detection.

**CDK:**

```typescript
const layerArns: { [region: string]: string } = {
  // ... (see Region-Specific Layer ARNs section above for complete mapping)
};

const myFunction = new lambda.Function(this, 'MyFunction', {
  layers: [
    lambda.LayerVersion.fromLayerVersionArn(this, 'AdotLayer', layerArns[this.region]),
  ],
});
```

**Terraform:**

```hcl
locals {
  layer_arns = {
    // ... (see Region-Specific Layer ARNs section above for complete mapping)
  }
}

data "aws_region" "current" {}

resource "aws_lambda_function" "my_function" {
  layers = [local.layer_arns[data.aws_region.current.name]]
}
```

### Step 4: Set Environment Variable

Add `AWS_LAMBDA_EXEC_WRAPPER` environment variable with value `/opt/otel-instrument`.

**CDK:**

```typescript
environment: {
  AWS_LAMBDA_EXEC_WRAPPER: '/opt/otel-instrument',
},
```

**Terraform:**

```hcl
environment {
  variables = {
    AWS_LAMBDA_EXEC_WRAPPER = "/opt/otel-instrument"
  }
}
```

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your Python Lambda function.

**Configuration Changes:**

- IAM Permissions: Added CloudWatchLambdaApplicationSignalsExecutionRolePolicy
- X-Ray Tracing: Enabled active tracing
- ADOT Layer: Added AWSOpenTelemetryDistroPython layer
- Environment Variable: Set AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument

**Next Steps:**

1. Ensure that [Application Signals is enabled in AWS account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html).
2. Review the changes using `git diff`
3. Deploy your infrastructure
4. After deployment, invoke your Lambda function to generate telemetry data

**Verification:**

- Open AWS CloudWatch Console → Application Signals → Services
- Look for your Lambda function service

**Troubleshooting**
Refer to the [CloudWatch APM troubleshooting guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Troubleshoot.html).

Let me know if you'd like me to make any adjustments before you deploy!"
