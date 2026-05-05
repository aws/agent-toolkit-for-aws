# CloudWatch Synthetics

Runtime constraints, blueprint compatibility, and common pitfalls for CloudWatch Synthetics canaries.

## Contents

- [Runtime and blueprint compatibility](#runtime-and-blueprint-compatibility)
- [CDK pattern](#key-flags)
- [VPC canaries](#vpc-canaries)
- [Common failures](#common-failures)
- [Limits](#limits)

---

## Runtime and blueprint compatibility

| Blueprint | Puppeteer | Playwright | Python/Selenium | Java |
|-----------|-----------|------------|-----------------|------|
| Heartbeat | Yes | Yes | Yes | No |
| API canary | Yes | No | Yes | Yes |
| Broken link checker | Yes | No | Yes | No |
| Visual monitoring | Yes | No | No | No |
| Canary recorder | Yes | No | No | No |
| GUI workflow | Yes | Yes | Yes | No |
| Multi checks | Yes | Yes | Yes | Yes |

Playwright cannot use 4 of 7 blueprints. Java has no browser — API-only.

| Family | Latest | Node/Python | X-Ray tracing |
|--------|--------|-------------|---------------|
| `syn-nodejs-puppeteer-*` | 15.0 | Node 22 | Yes (not with Firefox) |
| `syn-nodejs-playwright-*` | 6.0 | Node 22 | Yes (not with Firefox) |
| `syn-python-selenium-*` | 10.0 | Python 3.11 | Yes |
| `syn-java-*` | 1.0 | Java 21 | Yes |

> Run `aws synthetics describe-runtime-versions` for the latest runtime versions.

Deprecated runtimes continue running but you **cannot update code or config** without upgrading first.

---

## Key flags

CDK:

```typescript
const canary = new synthetics.Canary(this, 'ApiCanary', {
  // ... standard props ...
  activeTracing: true,              // X-Ray — adds 2.5-7% to run time
  provisionedResourceCleanup: true, // delete Lambda on canary delete
  artifactsBucketLifecycleRules: [{ expiration: Duration.days(30) }], // prevent S3 accumulation
});

// BREACHING — canary not running IS the problem
canary.metricSuccessPercent().createAlarm(this, 'CanaryAlarm', {
  threshold: 90,
  evaluationPeriods: 3,
  datapointsToAlarm: 2,
  comparisonOperator: ComparisonOperator.LESS_THAN_THRESHOLD,
  treatMissingData: TreatMissingData.BREACHING,
});
```

`maxRetries` (via `Schedule.RetryConfig`) and `dryRunAndUpdate` are not exposed in the CDK L2 construct — use `CfnCanary` escape hatch or CLI.

CLI — alarm on canary success rate:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name my-api-canary-success \
  --namespace CloudWatchSynthetics \
  --metric-name SuccessPercent \
  --dimensions Name=CanaryName,Value=my-api-canary \
  --statistic Average --period 300 \
  --evaluation-periods 3 --datapoints-to-alarm 2 \
  --threshold 90 --comparison-operator LessThanThreshold \
  --treat-missing-data breaching
```

CLI — safe update via dry run:

```bash
aws synthetics start-canary-dry-run --name my-api-canary --runtime-version syn-nodejs-puppeteer-15.0
aws synthetics get-canary --name my-api-canary --dry-run-id $DRY_RUN_ID
aws synthetics update-canary --name my-api-canary --dry-run-id $DRY_RUN_ID
```

Key CDK/CloudFormation constraints:

- `ExecutionRoleArn` is **required** — CloudFormation does not auto-create roles (unlike the console)
- Changing `Name` triggers **replacement** (delete + create), causing monitoring gaps
- Without `provisionedResourceCleanup: true`, deleting the stack orphans Lambda functions and layers
- Editing any canary property **resets the schedule** — next run happens immediately

---

## VPC canaries

Canaries in VPCs must run in **private subnets** (Lambda ENIs don't get public IPs, even in public subnets).

**Internet access** (required for uploading metrics to CloudWatch and artifacts to S3):

- Option A: NAT Gateway in a public subnet + route from private subnet
- Option B: VPC endpoints — Interface endpoint for `monitoring`, Gateway endpoint for `s3`

**VPC endpoint policy constraint**: The S3 gateway endpoint policy must include `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, and `s3:PutObject` — separate from the IAM role policy.

**DNS**: Both DNS Resolution and DNS Hostnames must be enabled on the VPC.

**Silent failure mode**: If the VPC has no internet access and no VPC endpoints, the canary runs but cannot upload metrics or artifacts — it appears as if it never ran.

---

## Common failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Cannot find module" | Wrong ZIP structure | Node.js: `nodejs/node_modules/<folder>/<file>.js`. Python: `python/<file>.py` |
| "Unable to fetch S3 bucket location: Access Denied" | Missing `s3:ListAllMyBuckets` on role (must be `Resource: "*"`) | Add `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, `s3:PutObject` to execution role |
| `net::ERR_NAME_NOT_RESOLVED` in VPC | No DNS resolution or no route to AWS endpoints | Enable DNS Resolution + DNS Hostnames on VPC; add NAT Gateway or VPC endpoints |
| "No test result returned" | Canary in public subnet | Move to private subnet — Lambda ENIs don't get public IPs |
| Timeout with no artifacts | Lambda timeout < canary timeout | Ensure Lambda timeout ≥ canary timeout; set canary timeout ≥ 15s for cold starts |
| Canary stops running | `DurationInSeconds` set to non-zero value | Set `DurationInSeconds: 0` for continuous running |
| Can't update canary | Runtime deprecated | Upgrade runtime first — deprecated runtimes block all config changes |
| Visual monitoring fails after upgrade | Chromium version changed | Re-baseline screenshots after runtime upgrades |
| CORS failures with X-Ray | Active tracing adds trace headers triggering preflight | Disable active tracing or configure CORS to allow X-Ray headers |
| `SuccessPercent` alarm in INSUFFICIENT_DATA | Canary timed out — no metric published for that run | Use `treatMissingData: BREACHING` so timeouts trigger the alarm |

---

## Limits

| Limit | Value | Consequence |
|-------|-------|-------------|
| Canaries per region | 200 (default, adjustable via Service Quotas) | At scale with retries, can exhaust Lambda concurrent execution (1000 default) |
| Timeout | Max 840s (14 min) | Cannot be longer than the canary's schedule frequency |
| Memory | 960-3008 MiB (default 1024) | Not the standard Lambda 128-10240 range |
| Canary name | Max 255 chars, lowercase alphanumeric plus `_` and `-` | Pattern: `^[0-9a-z_\-]+$` |
| Groups | 20 per account, 10 canaries/group | Cross-region grouping supported |
| X-Ray tracing | Not supported in ap-southeast-3 | Also not supported with Firefox browser |
| Minimum timeout | 15 seconds recommended | Below this, cold starts cause silent failures |
| Orphaned resources on delete | Lambda, logs, S3, IAM role NOT auto-deleted | Set `provisionedResourceCleanup: true` (CDK) or `AUTOMATIC` (CFN); manually clean the rest |
