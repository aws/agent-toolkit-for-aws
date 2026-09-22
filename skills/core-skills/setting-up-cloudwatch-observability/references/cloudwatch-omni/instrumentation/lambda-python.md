# Instrument a Python Lambda Function with ADOT

Add the ADOT Python Lambda layer to a function so it emits OpenTelemetry traces, with Application Signals explicitly disabled.

Read [instrumentation.md](instrumentation.md) first. Note that **Lambda differs from the other platforms**: the Lambda execution environment supplies its own X-Ray receiver, and with active tracing enabled the layer exports traces to it — so the function's export path is already wired rather than left at the SDK default. That is why this guide keeps the layer's standard configuration instead of omitting endpoint setup entirely.

If you cannot determine a value (such as the AWS Region), ask the user. Do not guess.

## Critical Requirements

**Do NOT:**

- Set `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true`, or add `OTEL_AWS_SERVICE_EVENTS_*` / `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*` variables
- Add `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` — it grants Application Signals, which is disabled here
- Hardcode a layer version from this guide
- Run `terraform apply`, `cdk deploy`, or `sam deploy` automatically
- Modify the function's handler source

## Layer ARN

The ADOT Lambda layer ARN is region-specific and its **layer version changes over time**. Look up the current value rather than copying one from this guide:

- Latest Version Reference: https://raw.githubusercontent.com/aws-otel/aws-otel.github.io/refs/heads/main/src/config/lambdaLayerArns.js
- (Human-readable: https://github.com/aws-otel/aws-otel.github.io/blob/main/src/config/lambdaLayerArns.js)

ARN format — fill in `<REGION>`, `<ACCOUNT_ID>`, and `<LAYER_VERSION>` from the source above:

```
arn:aws:lambda:<REGION>:<ACCOUNT_ID>:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
```

Sample regions (illustrative — confirm the current version and account ID, and use the source of truth for **any** supported region, not just these):

```
us-east-1:      arn:aws:lambda:us-east-1:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
us-west-2:      arn:aws:lambda:us-west-2:615299751070:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
ap-east-1:      arn:aws:lambda:ap-east-1:888577020596:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
eu-south-1:     arn:aws:lambda:eu-south-1:257394471194:layer:AWSOpenTelemetryDistroPython:<LAYER_VERSION>
...
```

> Some partitions use a different prefix and account ID (`arn:aws-cn:` for China). The source of truth has the exact ARN per region.

## Step 1: Add the layer

**CDK:**

```typescript
// lambda-stack.ts
const myFunction = new lambda.Function(this, 'MyFunction', {
  // ... existing runtime, handler, code unchanged ...
  layers: [
    lambda.LayerVersion.fromLayerVersionArn(this, 'AdotLayer', adotLayerArn),
  ],
});
```

**Terraform:**

```hcl
# lambda.tf
resource "aws_lambda_function" "my_function" {
  # ... existing configuration unchanged ...
  layers = [local.adot_layer_arn]
}
```

## Step 2: Enable X-Ray active tracing

Retained from the standard ADOT Lambda setup — active tracing is what makes the execution environment's X-Ray receiver available, so the layer's export path depends on it.

**CDK:** `tracing: lambda.Tracing.ACTIVE`
**Terraform:** `tracing_config { mode = "Active" }`

## Step 3: Set the environment variables

```
AWS_LAMBDA_EXEC_WRAPPER              = /opt/otel-instrument
OTEL_AWS_APPLICATION_SIGNALS_ENABLED = false
OTEL_SERVICE_NAME                    = <function-name>
```

`AWS_LAMBDA_EXEC_WRAPPER` is what loads the SDK — without it the layer is inert. `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false` is **required, not stylistic**. The layer's `otel-instrument` wrapper defaults this variable to `true` when it is unset — every ADOT Lambda runtime does — so taking the defaults would silently ENABLE Application Signals, which is out of scope here. This is the one place in this reference where an `OTEL_AWS_*` variable is written deliberately, and it must not be omitted.

`OTEL_SERVICE_NAME` is optional: the wrapper already defaults it to `$AWS_LAMBDA_FUNCTION_NAME`. Set it only if the service should be named something other than the function. `OTEL_METRICS_EXPORTER` and `OTEL_PROPAGATORS` are also defaulted sensibly by the wrapper, so do not set them.

**CDK:**

```typescript
environment: {
  AWS_LAMBDA_EXEC_WRAPPER: '/opt/otel-instrument',
  OTEL_AWS_APPLICATION_SIGNALS_ENABLED: 'false',
  OTEL_SERVICE_NAME: 'my-function',
},
```

**Terraform:**

```hcl
environment {
  variables = {
    AWS_LAMBDA_EXEC_WRAPPER              = "/opt/otel-instrument"
    OTEL_AWS_APPLICATION_SIGNALS_ENABLED = "false"
    OTEL_SERVICE_NAME                    = "my-function"
  }
}
```

Preserve any environment variables the function already sets — append to them.

## Step 4: Grant X-Ray write permissions to the execution role

With active tracing and the layer's default configuration, traces reach X-Ray through the execution environment's X-Ray receiver, so the execution role needs `xray:PutTraceSegments` and `xray:PutTelemetryRecords`. `AWSLambdaBasicExecutionRole` does not include them.

**CDK — already handled by Step 2.** Setting `tracing` to anything other than `DISABLED` makes the `Function` construct add those two actions to the role as an inline statement. Do not attach `AWSXRayDaemonWriteAccess` on top of that; confirm the grant with `cdk diff` instead.

**Terraform:**

```hcl
# lambda.tf
resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}
```

**SAM:** add `AWSXRayDaemonWriteAccess` to the function's `Policies` list. **CloudFormation, or a console-managed function:** attach the same managed policy to the execution role.

`AWSXRayDaemonWriteAccess` is broader than what the function actually uses — it also permits sampling-rule reads. If the user prefers least privilege, an inline policy with just the two `xray:Put*` actions covers this configuration.

## A note on IAM

The X-Ray permissions in Step 4 are the only ones this instrumentation needs, and they are added here because they follow directly from active tracing on the function itself.

Do not add `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` — it exists to grant Application Signals, which this configuration disables.

If the function is later pointed at a **different** destination — such as a customer-run collector — the permissions for that destination are not decided here.

## Verify

Invoke the function and check its CloudWatch Logs. The layer logs that the ADOT/OpenTelemetry instrumentation initialized on cold start.

Note that the wrapper adds cold-start latency while the SDK initializes. If the function is latency-sensitive, mention this to the user rather than silently changing memory or timeout settings.

## Completion

**Tell the user:**

"I've added ADOT Python instrumentation to your Lambda function.

**Changes:**

- Added the `AWSOpenTelemetryDistroPython` layer (version looked up from the ADOT source of truth for your region)
- Enabled X-Ray active tracing
- Set `AWS_LAMBDA_EXEC_WRAPPER`, `OTEL_SERVICE_NAME`, and `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false`
- Granted the execution role X-Ray write permissions — inline, via CDK's `tracing` setting, or the `AWSXRayDaemonWriteAccess` managed policy for Terraform/SAM/CloudFormation

**Not changed:** your handler source. No Application Signals policy was added.

**Next steps:**

1. Review the diff and confirm the layer version and region are right.
2. Deploy, then invoke the function once to trigger a cold start.
3. **Traces land in X-Ray**, by way of the execution environment's X-Ray receiver, which is where the layer sends them by default. If they should go somewhere else instead — such as your own collector — that destination needs different permissions from the X-Ray ones added here.

Let me know if you'd like adjustments before you deploy."
