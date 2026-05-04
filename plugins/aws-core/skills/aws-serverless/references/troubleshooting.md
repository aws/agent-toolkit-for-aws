# Serverless Troubleshooting Reference

Actionable error lookup tables: exact error string → cause → fix with CLI commands.

## Contents

- [Quick fixes](#quick-fixes)
- [Lambda Error Lookup](#lambda-error-lookup)
- [API Gateway Error Lookup](#api-gateway-error-lookup)
- [Step Functions Error Lookup](#step-functions-error-lookup)
- [SAM/CDK Error Lookup](#samcdk-error-lookup)
- [Timeout Debugging](#timeout-debugging)
- [OOM Debugging](#out-of-memory-oom-debugging)
- [Throttling Diagnosis](#throttling-diagnosis)
- [CloudWatch Logs Insights Queries](#cloudwatch-logs-insights-queries)
- [X-Ray Tracing](#x-ray-tracing)

---

## Quick fixes

### 502 Bad Gateway from API Gateway
Lambda proxy integration requires `{ statusCode: int, headers: {}, body: "string" }`.
The `body` must be a string (`JSON.stringify()`), not an object. API Gateway returns 502 when it cannot parse the Lambda response — the function ran successfully but the response shape was wrong. Note: string statusCode (e.g., "200") is silently coerced to integer, and missing statusCode defaults to 200.

### CORS errors
With Lambda proxy integration, Lambda must return CORS headers — the API Gateway console "Enable CORS" button does not work for Lambda proxy integration. Add `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers` to every Lambda response including errors. For HTTP API, use the built-in `CorsConfiguration` instead. CORS is enforced by the browser, not the server — missing headers cause the browser to block the response even though the API call succeeded.

### Lambda timeout + API Gateway 504
API Gateway has a hard integration timeout: REST API default 29s (configurable 50ms–29s; Regional/private APIs can request higher), HTTP API max 30s (can be lowered, cannot be raised). This is independent of Lambda's 15-min limit. The 504 means API Gateway gave up waiting, not that Lambda failed. For long operations, return 202 immediately, process via SQS or Step Functions, poll or use WebSocket for results.

### VPC Lambda cannot reach internet
Lambda in a VPC needs a **private** subnet + NAT Gateway in a **public** subnet. Placing Lambda in a public subnet does NOT give it a public IP — Lambda never gets a public IP regardless of subnet type because Lambda's network interface is managed by the service and doesn't support public IP assignment. For AWS services only, use VPC endpoints (free for S3 and DynamoDB gateway endpoints).

### ImportModuleError / MODULE_NOT_FOUND
Handler path doesn't match file structure, or dependencies weren't bundled. Lambda extracts code to `/var/task` and layers to `/opt` — if the handler path doesn't match the file's location relative to `/var/task`, the runtime can't find it. Python: `pip install -r requirements.txt -t ./package --platform manylinux2014_x86_64 --only-binary=:all:`. Node: verify `exports.handler` exists and `node_modules` is included. Use `sam build` to handle cross-platform packaging automatically.

---

## Lambda Error Lookup

### Runtime.ImportModuleError

**Error:** `Runtime.ImportModuleError: Unable to import module 'lambda_function': No module named 'lambda_function'`
**Cause:** Handler references a module missing from the deployment package.

```bash
pip install -r requirements.txt -t ./package
cd package && zip -r ../deployment.zip . && cd .. && zip deployment.zip lambda_function.py
# Or: sam build && sam deploy
```

### Runtime.HandlerNotFound

**Error:** `Runtime.HandlerNotFound: Handler 'handler' missing on module 'function'`
**Cause:** File exists but function/method name doesn't match handler setting.

```bash
aws lambda update-function-configuration --function-name my-func --handler app.lambda_handler
# Python: file.function  Node: file.export  Java: package.Class::method
```

### Task timed out

**Error:** `Task timed out after 3.00 seconds`
**Cause:** Execution exceeded configured timeout. Slow downstream calls, low memory/CPU, or VPC delays.

```bash
aws lambda update-function-configuration --function-name my-func --timeout 30
aws lambda update-function-configuration --function-name my-func --memory-size 512
# Set SDK/HTTP timeouts shorter than Lambda timeout for meaningful errors
```

### Runtime.OutOfMemory (OOM)

**Error:** `Runtime.OutOfMemory: ... signal: killed` or `Runtime exited without providing a reason`
**Cause:** Function exceeded allocated memory — kernel sent SIGKILL.

```bash
# Check REPORT lines: Max Memory Used vs Memory Size
aws lambda update-function-configuration --function-name my-func --memory-size 1024
# Stream large files instead of loading into memory; bound global caches
```

### AccessDeniedException

**Error:** `AccessDeniedException: ... not authorized to perform: lambda:InvokeFunction`
**Cause:** Calling IAM principal lacks `lambda:InvokeFunction` permission.

```bash
aws lambda add-permission --function-name my-func \
  --statement-id AllowInvoke --action lambda:InvokeFunction \
  --principal s3.amazonaws.com --source-arn arn:aws:s3:::my-bucket
```

### TooManyRequestsException

**Error:** `TooManyRequestsException: Rate Exceeded.`
**Cause:** Function exceeded account concurrency limit (default 1,000).

```bash
aws lambda get-account-settings
aws service-quotas request-service-quota-increase \
  --service-code lambda --quota-code L-B99A9384 --desired-value 3000
aws lambda put-function-concurrency --function-name my-func --reserved-concurrent-executions 100
```

### InvalidParameterValueException (size)

**Error:** `Unzipped size must be smaller than 262144000 bytes`
**Cause:** Package exceeds 50 MB zipped / 250 MB unzipped.

```bash
find ./package -name "*.pyc" -delete && find ./package -name "*.dist-info" -type d -exec rm -rf {} +
aws lambda publish-layer-version --layer-name my-deps --zip-file fileb://layer.zip --compatible-runtimes python3.13
# Or upload via S3, or switch to container image packaging (10 GB limit)
```

### ETIMEDOUT (VPC)

**Error:** `Error: connect ETIMEDOUT 176.32.98.189:443`
**Cause:** VPC Lambda can't reach internet — missing NAT Gateway or VPC Endpoint.

```bash
aws ec2 describe-route-tables --filters "Name=association.subnet-id,Values=subnet-xxx"
aws ec2 create-route --route-table-id rtb-xxx --destination-cidr-block 0.0.0.0/0 --nat-gateway-id nat-xxx
# Or use VPC Endpoints for AWS services:
aws ec2 create-vpc-endpoint --vpc-id vpc-xxx --service-name com.amazonaws.us-east-1.s3 --route-table-ids rtb-xxx
```

### MODULE_NOT_FOUND

**Error:** `Error: Cannot find module 'my-module'`
**Cause:** Node.js dependency missing — not bundled or built on incompatible platform.

```bash
npm install --production
sam build --use-container  # for native modules
unzip -l deployment.zip | grep my-module  # verify inclusion
```

### RecursiveInvocationException

**Error:** `RecursiveInvocationException: Recursive invocation detected`
**Cause:** Function writes to a resource that triggers itself again (~16 invocations before halt).

```bash
# Emergency stop
aws lambda put-function-concurrency --function-name my-func --reserved-concurrent-executions 0
# Fix: use separate input/output buckets or prefix filters in trigger config
```

### SnapStart Errors

**Error:** `SnapStartException` / `SnapStartNotReadyException` / `SnapStartTimeoutException`
**Cause:** SnapStart failed during snapshot — init threw exception or uses non-snapshottable resources (e.g., open network connections).

```bash
aws lambda get-function --function-name my-func --query 'Configuration.SnapStart'
# Java: Use CRaC hooks — beforeCheckpoint() to close connections, afterRestore() to reopen
# Python: Use snapshot_restore runtime hooks to re-establish connections after restore
# .NET: Use SnapshotRestore register hooks for before-snapshot and after-restore actions
```

### Sandbox.Timedout

**Error:** `Sandbox.Timedout`
**Cause:** Function exceeded its timeout. In newer runtimes, this covers both init-phase and invoke-phase timeouts. A suppressed init failure consumes the invoke timeout.

```bash
aws lambda update-function-configuration --function-name my-func --timeout 60 --memory-size 1024
# Move heavy initialization to lazy loading inside the handler
```

### ENILimitReachedException

**Error:** `ENILimitReachedException`
**Cause:** VPC reached network interface quota. Lambda Hyperplane ENIs have a default quota of 500 per VPC (see lambda.md); the overall VPC ENI quota is 5,000 per region. Check which limit applies.

```bash
aws service-quotas request-service-quota-increase --service-code vpc --quota-code L-DF5E4CA3 --desired-value 10000
# Consolidate functions to use same subnet + security group combinations
```

### InvalidZipFileException

**Error:** `InvalidZipFileException: Could not unzip uploaded file.`
**Cause:** Invalid ZIP or handler nested in subdirectory instead of at root.

```bash
unzip -t deployment.zip  # verify integrity
cd my-folder && zip -r ../deployment.zip . && cd ..  # files at root, not nested
```

### CodeStorageExceededException

**Error:** `CodeStorageExceededException: Code storage limit exceeded.`
**Cause:** Account exceeded 75 GB code storage per region (all versions + layers).

```bash
aws lambda list-versions-by-function --function-name my-func
aws lambda delete-function --function-name my-func --qualifier 1
aws lambda list-layers  # delete unused layers too
```

---

## API Gateway Error Lookup

### Malformed Lambda Proxy Response (502)

**Error:** `Malformed Lambda proxy response` → 502
**Cause:** Lambda response missing required format — `body` must be a string, response must be a JSON object (not a plain string or array).

```python
return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"msg": "ok"})}
```

```javascript
return { statusCode: 200, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ msg: "ok" }) };
```

### Missing Authentication Token (403)

**Error:** `403 Forbidden: Missing Authentication Token`
**Cause:** URL doesn't match any resource/method, or API not deployed to stage. Usually routing, not auth.

```bash
aws apigateway create-deployment --rest-api-id abc123 --stage-name prod
# Verify: https://{api-id}.execute-api.{region}.amazonaws.com/{stage}/{resource}
```

### Invalid Permissions on Lambda (500)

**Error:** `Invalid permissions on Lambda function`
**Cause:** API Gateway lacks `lambda:InvokeFunction` permission on the target function.

```bash
aws lambda add-permission --function-name my-func --statement-id apigw-invoke \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:123456789012:api-id/*/GET/resource"
```

### Endpoint Request Timed Out (504)

**Error:** `Endpoint request timed out` → 504
**Cause:** Lambda didn't respond within 29s (REST) / 30s (HTTP) integration timeout.

```bash
aws lambda update-function-configuration --function-name my-func --memory-size 1024
# For long operations: return 202 immediately, process async, poll for results
```

### Authorizer Unauthorized (401)

**Error:** `Unauthorized` (401)
**Cause:** Lambda authorizer returned deny, threw error, or timed out.

```bash
aws logs tail /aws/lambda/my-authorizer --since 1h --filter-pattern ERROR
# Verify authorizer returns: { principalId, policyDocument: { Statement: [{ Effect: "Allow" }] } }
```

### WAF Access Denied (403)

**Error:** `403 Forbidden` with `x-amzn-errortype: ForbiddenException`
**Cause:** AWS WAF rule matched — IP denylist, rate limit, or injection detection.

```bash
# Check WAF sampled requests in console to identify blocking rule
# Test rules in Count mode before switching to Block
```

### CORS Errors

**Error:** `blocked by CORS policy: No 'Access-Control-Allow-Origin' header`
**Cause:** Lambda proxy integration must return CORS headers; HTTP APIs can configure at API level.

```yaml
# SAM Globals
Globals:
  Api:
    Cors:
      AllowOrigin: "'*'"
      AllowMethods: "'GET,POST,OPTIONS'"
      AllowHeaders: "'Content-Type,Authorization'"
```

```bash
# HTTP API
aws apigatewayv2 update-api --api-id abc123 \
  --cors-configuration AllowOrigins="*",AllowMethods="GET,POST",AllowHeaders="Content-Type"
```

### Internal Server Error — Lambda Throttled (500)

**Error:** 500 with CloudWatch log `Lambda invocation failed with status 429`
**Cause:** Lambda throttled but API Gateway surfaces as 500.

```bash
# Increase Lambda concurrency (see TooManyRequestsException above)
aws apigateway update-stage --rest-api-id abc123 --stage-name prod \
  --patch-operations op=replace,path=/*/*/throttling/rateLimit,value=1000
```

---

## Step Functions Error Lookup

### States.TaskFailed

**Error:** `States.TaskFailed`
**Cause:** Task failed — unhandled Lambda exception, service error, or missing permissions.

```json
"Retry": [{"ErrorEquals": ["States.TaskFailed","Lambda.ServiceException","Lambda.SdkClientException"], "IntervalSeconds": 2, "MaxAttempts": 3, "BackoffRate": 2.0}],
"Catch": [{"ErrorEquals": ["States.TaskFailed"], "Next": "HandleError", "ResultPath": "$.error"}]
```

### States.Timeout

**Error:** `States.Timeout`
**Cause:** Task exceeded `TimeoutSeconds` or missed `HeartbeatSeconds` deadline.

```json
{"Type": "Task", "Resource": "arn:aws:lambda:...", "TimeoutSeconds": 300, "HeartbeatSeconds": 60, "Next": "NextState"}
```

### States.DataLimitExceeded

**Error:** `States.DataLimitExceeded`
**Cause:** State input/output exceeded 256 KB. Cannot be caught by `States.ALL`.

**Fix:** Store large data in S3, pass only S3 keys between states. Use `InputPath`/`OutputPath` to filter.

### ExecutionAlreadyExists

**Error:** `ExecutionAlreadyExists`
**Cause:** Execution name must be unique per state machine for 90 days.

```bash
aws stepfunctions start-execution --state-machine-arn arn:aws:states:... \
  --name "exec-$(date +%s)" --input '{}'
# Or omit --name for auto-generated names
```

### States.Permissions

**Error:** `States.Permissions: insufficient privileges`
**Cause:** Execution role lacks permission to invoke target service.

```bash
aws iam list-attached-role-policies --role-name StepFunctionsRole
# Add lambda:InvokeFunction, dynamodb:PutItem, etc. to the execution role
```

---

## SAM/CDK Error Lookup

### Stale Build Cache

**Error:** `sam build` uses old dependencies after updating requirements.txt, or `--clear-cache` flag unrecognized.
**Cause:** SAM caches build artifacts. There is no `--clear-cache` flag.

```bash
sam build --no-cached              # Force clean build (correct flag)
rm -rf .aws-sam/cache              # Or manually delete cache directory
```

### PythonPipBuilder:ResolveDependencies

**Error:** `PythonPipBuilder:ResolveDependencies - pip install returned a non-zero exit code`
**Cause:** Dependency version conflicts or missing native libraries.

```bash
sam build --use-container --no-cached
# Use binary wheels: psycopg2-binary instead of psycopg2
```

### DockerBuildFailed

**Error:** `DockerBuildFailed: Docker build failed.`
**Cause:** Docker not running or Dockerfile errors.

```bash
docker info  # verify running
sudo systemctl start docker  # start if needed
```

### Cannot find module 'esbuild'

**Error:** `Cannot find module 'esbuild'`
**Cause:** CDK `NodejsFunction` needs esbuild for bundling.

```bash
npm install --save-dev esbuild
```

### CREATE_FAILED

**Error:** `CREATE_FAILED: AWS::Lambda::Function`
**Cause:** Invalid runtime, missing S3 code, role not ready, or package too large.

```bash
aws cloudformation describe-stack-events --stack-name my-stack \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table
```

### UPDATE_ROLLBACK_FAILED

**Error:** `UPDATE_ROLLBACK_FAILED`
**Cause:** Update failed and rollback also failed — resource manually deleted or permissions changed.

```bash
aws cloudformation continue-update-rollback --stack-name my-stack
aws cloudformation continue-update-rollback --stack-name my-stack --resources-to-skip MyFunction
```

### Security Constraints Not Satisfied

**Error:** `Security Constraints Not Satisfied`
**Cause:** SAM template missing required properties (Handler, Runtime, CodeUri).

```bash
sam validate --lint
```

### CDK Bootstrap Required

**Error:** `This stack uses assets, so the toolkit stack must be deployed`
**Cause:** Target account/region not bootstrapped.

```bash
cdk bootstrap aws://123456789012/us-east-1
```

### Circular Dependency

**Error:** `Circular dependency between resources: [MyFunction, MyRole, ...]`
**Cause:** Resources reference each other in a cycle.

```yaml
# Break cycle: give the function an explicit name and hardcode the ARN
MyFunction:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: my-function-name  # explicit name

MyRole:
  Type: AWS::IAM::Role
  Properties:
    Policies:
      - PolicyDocument:
          Statement:
            - Effect: Allow
              Action: lambda:InvokeFunction
              # No ${MyFunction} reference — no implicit dependency
              Resource: !Sub "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:my-function-name"
# Or restructure to eliminate the cycle (extract IAM role/policy into a separate resource)
```

---

## Timeout Debugging

```
Function times out
├── INIT phase? (Sandbox.Timedout)
│   ├── YES → Increase timeout + memory, lazy-load heavy deps
│   └── NO → INVOKE phase
│       ├── Timeout ≈ avg duration? → Set to 2-3x average
│       ├── Calling external services? → Set SDK timeouts < Lambda timeout
│       ├── CPU-bound? → Increase memory (1,769 MB = 1 vCPU)
│       └── VPC? → Check NAT Gateway / security group / VPC Endpoints
```

```bash
aws lambda get-function-configuration --function-name my-func --query '[Timeout,MemorySize]'
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=my-func --period 300 --statistics Average Maximum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S)
# For percentiles, use a separate call:
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=my-func --period 300 --extended-statistics p99 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S)
```

---

## Out-of-Memory (OOM) Debugging

```
Runtime.OutOfMemory / signal: killed
├── Check REPORT: Max Memory Used ≈ Memory Size? → OOM confirmed
├── Immediate? → Payload/dependency too large → increase memory
├── Gradual? → Memory leak → check global vars accumulating across warm invocations
└── Fix: increase memory, stream large files, bound caches
```

| Memory (MB) | vCPUs | Use Case |
|-------------|-------|----------|
| 128 | ~0.08 | Simple transforms |
| 512 | ~0.3 | Moderate processing |
| 1,769 | 1.0 | CPU-intensive single-threaded |
| 3,538 | 2.0 | Multi-threaded |
| 10,240 | ~5.8 | Heavy compute, ML inference |

---

## Throttling Diagnosis

| Concept | Default | Notes |
|---------|---------|-------|
| Account concurrency | 1,000/region | Request increase via Service Quotas |
| Reserved concurrency | None | Guarantees AND caps function concurrency |
| Concurrency scaling rate | 1,000 envs/10s | Per function, uniform across regions |

| Invocation Type | Throttle Behavior |
|-----------------|-------------------|
| Synchronous (API GW) | Returns 429 (API GW may show 500) |
| Async (S3, SNS) | Auto-retries up to 6 hours |
| SQS trigger | Returns to queue, backs off |
| Kinesis/DDB Streams | Retries batch, blocks shard |

```bash
aws lambda get-account-settings
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles \
  --dimensions Name=FunctionName,Value=my-func --period 60 --statistics Sum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S)
```

---

## CloudWatch Logs Insights Queries

Run against `/aws/lambda/FUNCTION_NAME`. For API Gateway, use the access log group.

### Cold Starts

```
filter @type = "REPORT" | filter ispresent(@initDuration)
| stats count() as coldStarts, avg(@initDuration) as avgInitMs, max(@initDuration) as maxInitMs, pct(@initDuration, 99) as p99InitMs by bin(1h)
```

### Cold Start Percentage

```
filter @type = "REPORT"
| stats count() as total, sum(ispresent(@initDuration)) as coldStarts, sum(ispresent(@initDuration)) * 100.0 / count() as pct by bin(1h)
```

### Errors by Type

```
filter @message like /(?i)error|exception/
| parse @message /(?<errorType>[A-Za-z]+Error|[A-Za-z]+Exception)/
| stats count() as cnt by errorType | sort cnt desc
```

### Timeouts

```
filter @message like /Task timed out/ | stats count() as timeouts by bin(1h) | sort bin desc
```

### Memory Utilization

```
filter @type = "REPORT"
| stats max(@memorySize/1e6) as provisionedMB, avg(@maxMemoryUsed/1e6) as avgUsedMB, max(@maxMemoryUsed/1e6) as maxUsedMB, pct(@maxMemoryUsed/1e6, 99) as p99UsedMB
```

### Out-of-Memory Detection (>90% memory)

```
filter @type = "REPORT" | filter @maxMemoryUsed / @memorySize > 0.9
| fields @timestamp, @requestId, @maxMemoryUsed/1e6 as usedMB, @memorySize/1e6 as allocatedMB | sort @timestamp desc | limit 50
```

### Overprovisioned Memory (<50% used)

```
filter @type = "REPORT"
| stats max(@memorySize/1e6) as provMB, max(@maxMemoryUsed/1e6) as peakMB, max(@maxMemoryUsed)*100.0/max(@memorySize) as pct
| filter pct < 50
```

### Memory Growth (Leak Detection)

```
filter @type = "REPORT" | stats avg(@maxMemoryUsed/1e6) as avgMemMB by bin(5m) | sort bin asc
```

### Latency Percentiles

```
filter @type = "REPORT"
| stats avg(@duration) as avg, pct(@duration,50) as p50, pct(@duration,90) as p90, pct(@duration,95) as p95, pct(@duration,99) as p99, max(@duration) as max by bin(1h)
```

### Slowest Invocations

```
filter @type = "REPORT"
| fields @timestamp, @requestId, @duration, @maxMemoryUsed/1000000 as memMB, ispresent(@initDuration) as coldStart
| sort @duration desc | limit 20
```

### API Gateway 5xx

```
filter status >= 500 | stats count() as errors by status, path, httpMethod | sort errors desc
```

### API Gateway 5xx Over Time

```
filter status >= 500 | stats count() by bin(5m) | sort bin desc
```

### Throttle Events

```
filter @message like /Rate Exceeded|TooManyRequestsException|Throttl/
| fields @timestamp, @requestId, @message | sort @timestamp desc | limit 50
```

### Billed Duration

```
filter @type = "REPORT"
| stats count() as invocations, sum(@billedDuration)/1000 as totalBilledSec, avg(@billedDuration) as avgBilledMs by bin(1d)
```

### Error Messages with Request IDs

```
filter @message like /(?i)error|exception|fail/
| fields @timestamp, @requestId, @message | sort @timestamp desc | limit 50
```

---

## X-Ray Tracing

### Enable in SAM

```yaml
Globals:
  Function:
    Tracing: Active
```

### Enable in CDK

```typescript
new lambda.Function(this, 'Fn', {
  tracing: lambda.Tracing.ACTIVE,  // adds AWSXRayDaemonWriteAccess automatically
});
```

### Required IAM
`AWSXRayDaemonWriteAccess` managed policy on the execution role. SAM/CDK add this automatically.

### Default Sampling
1 request/second (reservoir) + 5% of additional requests.

### Instrument SDK Calls

```python
from aws_xray_sdk.core import patch_all
patch_all()
```

```javascript
// SDK v3 (Node.js 18+)
const { captureAWSv3Client } = require('aws-xray-sdk-core');
const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const ddb = captureAWSv3Client(new DynamoDBClient({}));
```

### Query Traces

```bash
aws xray get-trace-summaries --start-time $(date -u -d '1 hour ago' +%s) --end-time $(date -u +%s) \
  --filter-expression 'service("my-func") AND fault'
aws xray batch-get-traces --trace-ids "1-xxx-yyy"
```

### Enable for API Gateway

```yaml
Resources:
  MyApi:
    Type: AWS::Serverless::Api
    Properties:
      StageName: prod
      TracingEnabled: true
```

### Enable for Step Functions

```yaml
Resources:
  MyStateMachine:
    Type: AWS::Serverless::StateMachine
    Properties:
      Tracing:
        Enabled: true
```
