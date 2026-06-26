# Enable AWS Application Signals for Java on AWS Lambda

Your task is to modify Infrastructure as Code (IaC) files to enable AWS Application Signals for Java Lambda functions. You will:

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
arn:aws:lambda:<REGION>:<ACCOUNT_ID>:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
```

A few sample regions (illustrative — confirm the current `<LAYER_VERSION>` and account ID from the source of truth, and use it for **any** supported region, not just these):

```
us-east-1:      arn:aws:lambda:us-east-1:615299751070:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
us-west-2:      arn:aws:lambda:us-west-2:615299751070:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
ca-central-1:   arn:aws:lambda:ca-central-1:615299751070:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
ap-east-1:      arn:aws:lambda:ap-east-1:888577020596:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
ap-southeast-1: arn:aws:lambda:ap-southeast-1:615299751070:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
eu-west-1:      arn:aws:lambda:eu-west-1:615299751070:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
eu-south-1:     arn:aws:lambda:eu-south-1:257394471194:layer:AWSOpenTelemetryDistroJava:<LAYER_VERSION>
...
```

> Note: some partitions use a different ARN prefix and account ID (`arn:aws-cn:` for China, `arn:aws-us-gov:` for GovCloud). The source of truth has the exact ARN for every supported region.

## Instructions

### Step 1: Add IAM Permissions

Add `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` to the Lambda function's execution role.

**CDK:**

```typescript
managedPolicies: [
  iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
  iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchLambdaApplicationSignalsExecutionRolePolicy'),
],
```

**Terraform:**

```hcl
resource "aws_iam_role_policy_attachment" "application_signals" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLambdaApplicationSignalsExecutionRolePolicy"
}
```

### Step 2: Enable X-Ray Active Tracing

**CDK:** `tracing: lambda.Tracing.ACTIVE`
**Terraform:** `tracing_config { mode = "Active" }`

### Step 3: Add ADOT Java Lambda Layer

Use the layer name `AWSOpenTelemetryDistroJava` with automatic region detection. See Region-Specific Layer ARNs section above for complete mapping.

### Step 4: Set Environment Variable

Add `AWS_LAMBDA_EXEC_WRAPPER = "/opt/otel-instrument"`.

## Completion

**Tell the user:**

"I've completed the Application Signals enablement for your Java Lambda function.

**Configuration Changes:**

- IAM Permissions: Added CloudWatchLambdaApplicationSignalsExecutionRolePolicy
- X-Ray Tracing: Enabled active tracing
- ADOT Layer: Added AWSOpenTelemetryDistroJava layer
- Environment Variable: Set AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument

**Next Steps:**

1. Ensure that [Application Signals is enabled in AWS account](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable.html).
2. Review the changes using `git diff`
3. Deploy your infrastructure
4. After deployment, invoke your Lambda function to generate telemetry data

**Verification:**

- Open AWS CloudWatch Console → Application Signals → Services

**Troubleshooting**
Refer to the [CloudWatch APM troubleshooting guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Troubleshoot.html).

Let me know if you'd like me to make any adjustments before you deploy!"
