# Troubleshooting: Deployment Failures

## Table of Contents

- [Overview](#overview)
- [Deploy Failure Root Cause Analysis](#deploy-failure-root-cause-analysis)
- [Deadly Embrace (Cross-Stack Reference Deadlock)](#deadly-embrace-cross-stack-reference-deadlock)
- [UPDATE_ROLLBACK_FAILED Recovery](#update_rollback_failed-recovery)
- [Versioned Bucket Deletion](#non-empty-bucket-deletion)

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

The CDK CLI surfaces a summary, but you MUST check CloudFormation stack events for the real error.

### Step 1: Query failed events

```bash
aws cloudformation describe-stack-events \
  --stack-name $STACK \
  --query "StackEvents[?contains(ResourceStatus,'FAILED')]"
```

### Step 2: Enable verbose output

Re-run the deploy with verbose logging to capture the full CLI-to-CloudFormation interaction:

```bash
cdk deploy $STACK --verbose
```

### Diagnosis checklist

You MUST work through these in order:

1. Read the `ResourceStatusReason` from the failed CloudFormation event.
2. Identify the logical resource ID and map it back to your CDK construct.
3. Classify the error into one of the three categories above.
4. For `DeployFailed`: fix the resource configuration or IAM permissions.
5. For `DeploymentError`: check asset paths, Docker availability, and the CDK publishing role.
6. For `EarlyValidationFailure`: check bootstrap version, environment configuration, or CLI version.

---

## Deadly Embrace (Cross-Stack Reference Deadlock)

A deadly embrace occurs when Stack A exports a value that Stack B imports. CloudFormation MUST NOT delete an export while any other stack imports it. Attempting to remove the export or the resource behind it fails with:

> Export cannot be deleted while it is in use by another stack.

### Two-deploy fix

This MUST be done in exactly two deployments:

**Deploy 1 — Decouple the consumer:**

1. In the consuming stack (Stack B), remove the `Fn.importValue` / cross-stack reference. Replace it with a hardcoded value, SSM lookup, or other mechanism.
2. In the producing stack (Stack A), add `this.exportValue(resource.resourceArn)` (or the relevant attribute) to keep the export alive during transition.
3. Deploy both stacks.

**Deploy 2 — Remove the export:**

1. In the producing stack (Stack A), remove the `this.exportValue()` call.
2. Deploy again.

You MUST NOT attempt to remove the export and the import in a single deployment.

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
