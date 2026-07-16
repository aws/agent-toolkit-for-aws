# Serverless Troubleshooting Reference

Error → cause → fix, focused on non-obvious gotchas and exact CLI commands. The five most common fixes are first.

## Quick fixes

- **502 Bad Gateway (proxy):** Lambda response must be `{ statusCode: int, headers: {}, body: "string" }`. `body` must be a `JSON.stringify`'d **string**, not an object. The function ran fine — only the response shape was wrong. (String statusCode is coerced. Under **HTTP API** payload format 2.0 a missing statusCode defaults to 200, but under **REST** proxy a missing statusCode is itself a malformed response and triggers the 502.)
- **CORS errors:** under proxy integration the **Lambda** returns CORS headers on **every** response including errors; the console "Enable CORS" button doesn't apply. HTTP API: use `CorsConfiguration`. CORS is browser-enforced — the API call itself succeeded. **Never use `AllowOrigin: '*'` in production** — wildcard CORS is a security risk (CWE-942); specify your exact domain (e.g. `https://app.example.com`).
- **504 from API Gateway:** integration timeout (REST 29s default; HTTP 30s max), independent of Lambda's 15-min limit. For long ops: return 202 immediately, process via SQS/Step Functions, poll or use WebSocket.
- **VPC Lambda can't reach internet:** needs **private** subnet + NAT Gateway in a **public** subnet. A public subnet does NOT give Lambda a public IP. For AWS services use VPC endpoints (free for S3/DynamoDB gateway endpoints).
- **ImportModuleError / MODULE_NOT_FOUND:** handler path doesn't match file structure, or deps weren't bundled for the right platform. Python: `pip install -r requirements.txt -t ./package --platform manylinux2014_x86_64 --only-binary=:all:`. Use `sam build` for cross-platform packaging.

---

## Lambda errors (gotchas)

### RecursiveInvocationException

A function writes to a resource that re-triggers it (Lambda halts after ~16 loops).

```bash
# Emergency stop:
aws lambda put-function-concurrency --function-name my-func --reserved-concurrent-executions 0
# Fix: separate input/output buckets, or prefix filters in the trigger config
```

### SnapStart errors

`SnapStartException` / `SnapStartNotReadyException` / `SnapStartTimeoutException` — init threw, or it uses non-snapshottable resources (open network connections).

```bash
aws lambda get-function --function-name my-func --query 'Configuration.SnapStart'
# Java:   CRaC hooks — beforeCheckpoint() closes connections, afterRestore() reopens
# Python: snapshot_restore runtime hooks to re-establish connections after restore
# .NET:   SnapshotRestore.Register hooks for before-snapshot / after-restore
```

### Sandbox.Timedout

Exceeded the timeout. In newer runtimes this covers **both** init-phase and invoke-phase timeouts — a suppressed init failure consumes the invoke timeout. Move heavy init to lazy loading inside the handler; raise `--timeout`/`--memory-size`.

### ENILimitReachedException

VPC hit its network-interface quota. Two limits can apply — the Lambda-specific Hyperplane ENI-per-VPC quota and the broader VPC ENI-per-Region quota — so check which one was reached (Service Quotas / `describe-account-attributes`).

```bash
aws service-quotas request-service-quota-increase --service-code vpc --quota-code L-DF5E4CA3 --desired-value 10000
# Consolidate functions onto the same subnet + security group combinations
```

### TooManyRequestsException / throttling

```bash
aws lambda get-account-settings
aws service-quotas request-service-quota-increase --service-code lambda --quota-code L-B99A9384 --desired-value 3000
aws lambda put-function-concurrency --function-name my-func --reserved-concurrent-executions 100
```

Throttle behavior by invocation type: **Sync (API GW)** → 429 (may surface as 500); **Async (S3, SNS)** → auto-retries up to 6h; **SQS** → returns to queue, backs off; **Kinesis/DynamoDB Streams** → retries batch, blocks shard.

### CodeStorageExceededException

Account exceeded its per-Region code storage quota (unzipped; all versions + layers). Check the current limit with `aws service-quotas get-service-quota --service-code lambda --quota-code L-2ACBD22F` (it is adjustable and has changed over time). Delete old versions and unused layers (`aws lambda list-versions-by-function`, `delete-function --qualifier`).

---

## API Gateway errors (gotchas)

| Error | Cause | Fix |
|---|---|---|
| `403 Missing Authentication Token` | URL doesn't match a resource/method, or API not deployed | Usually routing, not auth — verify path and `create-deployment` to the stage |
| `Invalid permissions on Lambda function` (500) | API GW lacks `lambda:InvokeFunction` | `aws lambda add-permission --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:...:api-id/*/GET/resource"` (add `--source-account <account-id>` to scope cross-service triggers like S3 to your account) |
| `Unauthorized` (401) | Lambda authorizer denied/errored/timed out | Check authorizer logs; verify it returns a valid Allow policy |
| `403` + `x-amzn-errortype: ForbiddenException` | WAF rule matched | Check WAF sampled requests; test rules in Count mode first |
| 500 with log `status 429` | Lambda throttled, surfaced as 500 | Increase Lambda concurrency |

---

## Step Functions errors

| Error | Cause / Fix |
|---|---|
| `States.TaskFailed` | Add `Retry` for `States.TaskFailed`/`Lambda.ServiceException`/`Lambda.SdkClientException`; `Catch` to a handler |
| `States.Timeout` | Set `TimeoutSeconds` (and `HeartbeatSeconds` for long tasks) |
| `States.DataLimitExceeded` | Input/output > 256 KiB — **cannot be caught by `States.ALL`**. Store in S3, pass keys |
| `ExecutionAlreadyExists` | Names unique per state machine for 90 days — use `--name "exec-$(date +%s)"` or omit `--name` |
| `States.Permissions` | Execution role lacks target-service permission |

---

## SAM/CDK errors

### Stale build cache

```bash
sam build --no-cached        # correct flag — there is NO --clear-cache
rm -rf .aws-sam/cache        # or delete the cache directory
```

### PythonPipBuilder:ResolveDependencies

Version conflicts or missing native libs: `sam build --use-container --no-cached`; use binary wheels (`psycopg2-binary`).

### CDK NodejsFunction: `Cannot find module 'esbuild'`

`npm install --save-dev esbuild`.

### CREATE_FAILED / UPDATE_ROLLBACK_FAILED

```bash
aws cloudformation describe-stack-events --stack-name my-stack \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table
# Rollback also failed (resource manually deleted / perms changed):
aws cloudformation continue-update-rollback --stack-name my-stack --resources-to-skip MyFunction
```

### Circular dependency

`Circular dependency between resources: [MyFunction, MyRole, ...]` — break the cycle by giving the function an explicit `FunctionName` and referencing the hardcoded ARN (`!Sub "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:my-function-name"`) instead of `!Ref`/`!GetAtt`, or extract the IAM role/policy into a separate resource.

### Other quick ones

- `DockerBuildFailed` → `docker info` / start Docker.
- `Security Constraints Not Satisfied` (missing Handler/Runtime/CodeUri) → `sam validate --lint`.
- `This stack uses assets, so the toolkit stack must be deployed` → `cdk bootstrap aws://ACCOUNT/REGION`.

---

## Diagnostics

For systematic timeout investigation (config → logs → metrics → VPC → cold start → memory → downstream), use the **debugging-lambda-timeouts** skill (see SKILL.md routing).

CloudWatch Logs Insights run against `/aws/lambda/FUNCTION_NAME` (API Gateway uses the access log group). Useful fields on `@type = "REPORT"` lines: `@initDuration` (cold start), `@duration`, `@billedDuration`, `@maxMemoryUsed`, `@memorySize`. Examples:

```
# Cold start rate + init latency
filter @type="REPORT" | stats count() as total, sum(ispresent(@initDuration)) as coldStarts,
  avg(@initDuration) as avgInitMs, pct(@initDuration,99) as p99InitMs by bin(1h)

# Out-of-memory (>90% used)
filter @type="REPORT" | filter @maxMemoryUsed/@memorySize > 0.9
  | fields @timestamp, @requestId, @maxMemoryUsed/1e6 as usedMB | sort @timestamp desc

# Latency percentiles
filter @type="REPORT" | stats pct(@duration,50) as p50, pct(@duration,90) as p90,
  pct(@duration,99) as p99, max(@duration) as max by bin(1h)

# API Gateway 5xx (access log group)
filter status >= 500 | stats count() as errors by status, path, httpMethod | sort errors desc
```

### Memory ↔ vCPU (for OOM / CPU tuning)

| Memory | vCPUs | Use case |
|---|---|---|
| 128 MB | ~0.08 | Simple transforms |
| 512 MB | ~0.3 | Moderate processing |
| 1,769 MB | 1.0 | CPU-intensive single-threaded |
| 3,538 MB | 2.0 | Multi-threaded |
| 10,240 MB | ~5.8 (up to 6 vCPU) | Heavy compute / ML inference |

### X-Ray

Enable via SAM `Tracing: Active` (Function) / `TracingEnabled: true` (Api) or CDK `tracing: lambda.Tracing.ACTIVE` (adds `AWSXRayDaemonWriteAccess` automatically). Default sampling: 1 req/s reservoir + 5%. Instrument SDK calls with `patch_all()` (Python) / `captureAWSv3Client` (Node).
