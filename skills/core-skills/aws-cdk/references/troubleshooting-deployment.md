# Troubleshooting: Deployment Failures

## Table of Contents

- [Overview](#overview)
- [Deploy Failure Root Cause Analysis](#deploy-failure-root-cause-analysis)
- [Deadly Embrace (Cross-Stack Reference Deadlock)](#deadly-embrace-cross-stack-reference-deadlock)
- [UPDATE_ROLLBACK_FAILED Recovery](#update_rollback_failed-recovery)
- [Non-Empty Bucket Deletion](#non-empty-bucket-deletion)

---

## Overview

This reference covers deployment-time failures — errors that occur after `cdk synth` succeeds and CloudFormation begins creating or updating resources. The CDK CLI error message is almost never the root cause; you MUST inspect CloudFormation stack events to find the actual failure.

Three error categories exist:

| Category | Meaning |
|---|---|
| `DeployFailed` | CloudFormation resource-level failure |
| `DeploymentError` | Asset publishing or IAM permission failure before CFN executes |
| `EarlyValidationFailure` | Pre-deploy check failed (e.g., bootstrap version mismatch) |

---

## Deploy Failure Root Cause Analysis

The CDK CLI surfaces only a terse summary; the real cause is in the failed deployment, not the CLI output. You MUST work through these steps in order.

### Step 1: Re-run with `--verbose`

```bash
cdk deploy $STACK --verbose
```

Prints every AWS API call, the change-set diff, and a fuller stack trace (`-vv` / `-vvv` for more).

### Step 2: `cdk diagnose` (preferred, CDK CLI ≥ 2.1120.0)

```bash
cdk --unstable=diagnose diagnose $STACK
```

Inspects the failed deployment and prints the root cause with pointers back to the CDK source that caused it. It runs after the fact, so it also works for diagnosing CI/CD pipeline failures. Requires the `--unstable=diagnose` flag.

### Step 3: CloudFormation events (fallback)

If `cdk diagnose` is unavailable (older CLI) or you need the raw stream:

```bash
aws cloudformation describe-events --stack-name $STACK --filters FailedEvents=true
```

`describe-events` groups events by operation ID and surfaces validation, provisioning, and hook-invocation errors — it supersedes `describe-stack-events`. The FIRST event in the output is the real root cause; later failures are rollback cascade.

### Step 4: Read the `ResourceStatusReason`

| Reason | Likely cause → fix |
|---|---|
| `... already exists` | Physical-name collision — remove `bucketName`/`tableName`/`roleName` and let CDK auto-generate. |
| `resource creation cancelled` | Not the root — another resource failed first; find that event. |
| `... in the WAITING state for approximately ... seconds` | Stabilization timeout (RDS, ASG signals, long-running Lambda). |
| `Export X cannot be deleted as it is in use by Stack Y` | Cross-stack deadlock — see [Deadly Embrace](#deadly-embrace-cross-stack-reference-deadlock). |
| `is not authorized to perform ...` | The default CDK bootstrap grants AdministratorAccess to the execution role — this error means you're using a customized bootstrap with a restricted execution role, a permissions boundary, or an SCP. Check which specific action/resource is denied, then add only that permission to your custom execution role or permissions boundary. Do NOT widen to `*` — grant the minimum action on the minimum resource ARN. |

### Step 5: Service logs for Lambda / API Gateway / custom resources

CloudFormation only reports *that* a resource failed. The actual reason (e.g. a custom-resource Lambda threw) is in CloudWatch Logs:

- Lambda: `/aws/lambda/<function-name>`
- CodeBuild-in-pipeline: `/aws/codebuild/<project>`
- CloudFormation custom resources: the backing Lambda's log group.

### `EarlyValidationFailure` specifically

Fails BEFORE the change set is submitted — a construct's `validate()` returned errors, a synth-time assertion tripped, or an `addError` annotation fired. The message names the exact property and constraint; fix it before redeploying.

> If you have the awslabs `aws-iac-mcp-server`, its `troubleshoot_cloudformation_deployment` tool matches the failure event stream against 30+ known patterns and returns CloudTrail deep links — use it to shortcut Steps 2–4.

---

## Deadly Embrace (Cross-Stack Reference Deadlock)

A deadly embrace occurs when Stack A exports a value that Stack B imports, and you then try to remove the export (or the resource behind it). CloudFormation refuses:

> Export Stack1:ExportsOutputFnGetAtt-XXXX cannot be deleted as it is in use by Stack2

The deadlock is structural: a safe removal needs B deployed first (so it stops importing), but CDK orders A before B because of the dependency.

Every cross-stack reference has a **strength**:

- **Strong** (default) — uses `Fn::ImportValue`. CloudFormation blocks the producer from removing the export while any consumer still imports it.
- **Weak** — uses `Fn::GetStackOutput`. No coupling; the producer can be changed or deleted independently.
- **Both** — transitional state for migrating strong → weak.

Cross-account references are always weak (strong is unsupported cross-account).

### Fix — reference strength (recommended)

CDK supports weakening the reference before removing the resource, with no manual `exportValue` hacks. You MUST do this as a **three-deploy migration**.

**Weaken all references to a resource** — `CrossStackReferences.of(resource).produce()`:

```typescript
import { CrossStackReferences, ReferenceStrength } from 'aws-cdk-lib';

// Deploy 1 — consumers move to Fn::GetStackOutput; the strong export stays
CrossStackReferences.of(bucket).produce(ReferenceStrength.BOTH);

// Deploy 2 — drop the strong export now that no consumer uses Fn::ImportValue
CrossStackReferences.of(bucket).produce(ReferenceStrength.WEAK);

// Deploy 3 — remove the resource or the reference entirely
```

**Weaken a single reference** — `Stack.consumeReference()`:

```typescript
import { Stack, ReferenceStrength } from 'aws-cdk-lib';

// Deploy 1 — wrap with consumeReference (defaults to BOTH)
new CfnOutput(consumer, 'BucketArn', { value: Stack.consumeReference(bucket.bucketArn) });

// Deploy 2 — switch to WEAK
new CfnOutput(consumer, 'BucketArn', {
  value: Stack.consumeReference(bucket.bucketArn, ReferenceStrength.WEAK),
});

// Deploy 3 — remove the resource or reference
```

(Use `Stack.consumeListReference()` for string-list references.)

### Fix — legacy two-deploy (`exportValue`)

Use this only on CDK versions that lack `ReferenceStrength`. It MUST be done in exactly two deployments:

**Deploy 1 — decouple the consumer, keep the export alive:**

1. In consumer Stack B, remove the cross-stack reference (replace with a hardcoded value, SSM lookup, etc.).
2. In producer Stack A, add `this.exportValue(resource.attribute)` to keep the export alive during the transition.
3. Deploy both.

**Deploy 2 — remove the export:**

1. In Stack A, remove the `this.exportValue()` call (and the underlying resource if desired).
2. Deploy again.

You MUST NOT attempt to remove the export and the import in a single deployment.

### Manual deploy ordering (`cdk deploy -e`)

If the consumer already stopped using the value and you control ordering yourself:

```bash
cdk deploy -e $CONSUMER_STACK   # deploy consumer first (drops the import)
cdk deploy -e $PRODUCER_STACK   # then producer, removing the export
```

`-e` / `--exclusively` deploys only the named stack and skips dependency reconciliation.

### Prevention

- Default cross-stack references to **weak** for resources you expect to remove or replace. Set app-wide in `cdk.json`:

  ```json
  { "context": { "@aws-cdk/core:defaultCrossStackReferences": "weak" } }
  ```

- Keep stateful, long-lived resources in their own stack, separate from consumers.
- Use SSM Parameter Store as indirection (producer writes a parameter, consumer reads it) — no CFN export, no embrace.

---

## UPDATE_ROLLBACK_FAILED Recovery

A stack enters `UPDATE_ROLLBACK_FAILED` when CloudFormation cannot roll back a failed update. The stack is wedged and MUST be recovered before any further operations.

### Root causes

- Resource deleted out-of-band (e.g., manually deleted in the console).
- Insufficient IAM permissions for the rollback operation.
- Service quota exceeded.
- Resource operation timed out.

### Recovery options

**Option 1 — Standard rollback:**

```bash
cdk rollback $STACK
```

**Option 2 — Orphan stuck resources:**

If a specific resource cannot be rolled back (e.g., it was deleted out-of-band), skip it:

```bash
cdk rollback $STACK --orphan $LOGICAL_ID
```

The resource is removed from the stack's state without attempting to delete or update it.

**Option 3 — Force rollback:**

```bash
cdk rollback $STACK --force
```

### Post-recovery steps

After the stack returns to a stable state, you MUST:

1. Run `cdk diff $STACK` to understand the current drift.
2. Fix the root cause (restore deleted resources, fix IAM, request quota increase).
3. Redeploy: `cdk deploy $STACK`.

You SHOULD NOT leave a stack in a recovered-but-drifted state.

---

## Non-Empty Bucket Deletion

Setting `removalPolicy: cdk.RemovalPolicy.DESTROY` alone MUST NOT be expected to delete an S3 bucket that contains objects. CloudFormation cannot empty a bucket during deletion. Versioned buckets are worse — delete markers and non-current object versions persist even after apparent object deletion, so the bucket can appear empty yet still fail to delete.

### Fix

You MUST add `autoDeleteObjects: true` alongside the removal policy:

```typescript
new s3.Bucket(this, 'MyBucket', {
  removalPolicy: cdk.RemovalPolicy.DESTROY,
  autoDeleteObjects: true,
});
```

`autoDeleteObjects` installs a custom resource Lambda that deletes all object versions and delete markers before CloudFormation attempts to delete the bucket.

You SHOULD only use this pattern in development or test stacks. Production buckets SHOULD retain the default `removalPolicy: RETAIN`.

---

## Lambda Cannot Find Module at Runtime

These errors occur at **Lambda invoke time**, not during `cdk synth`. The function deploys successfully but fails when invoked.

### Symptom

```
Cannot find module 'index'
Cannot find module 'aws-sdk'
Runtime.ImportModuleError: No module named 'requests'
```

### Cause

- Wrong `handler` value (e.g., `handler: 'handler'` instead of `handler: 'index.handler'`)
- `aws-sdk` v2 was removed from Node.js 18+ Lambda runtimes — code still imports it
- Python dependencies not bundled — `Code.fromAsset()` zips the directory without running `pip install`

### Fix

- Fix handler to match your file and export: `handler: 'index.handler'`
- Migrate from AWS SDK v2 to v3: `import { S3Client } from '@aws-sdk/client-s3'`
- Remove `externalModules: ['aws-sdk']` from bundling options if present
- For Python: use `PythonFunction` from `@aws-cdk/aws-lambda-python-alpha` which bundles pip dependencies automatically

---

## API Gateway Multi-Stage

This is a **construct design issue** that manifests at deploy time, not a synth failure.

### Symptom

Creating a `RestApi` produces only one stage. Adding extra `Stage` objects causes conflicts or duplicate deployments.

### Cause

`RestApi` creates a `Deployment` and a default `Stage` automatically. Creating additional `Stage` objects without disabling the default causes conflicts.

### Fix

Set `deploy: false` on the `RestApi`, then create `Deployment` and `Stage` objects explicitly:

```typescript
const api = new apigateway.RestApi(this, 'Api', { deploy: false });
// ... define resources and methods ...
const deployment = new apigateway.Deployment(this, 'Deployment', { api });
new apigateway.Stage(this, 'Dev', { deployment, stageName: 'dev' });
new apigateway.Stage(this, 'Prod', { deployment, stageName: 'prod' });
```
