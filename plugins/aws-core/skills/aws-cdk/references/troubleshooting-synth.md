# Troubleshooting: Synth Failures

## Table of Contents

- [Overview](#overview)
- [Cannot Find Module (Synth Time)](#cannot-find-module-synth-time)
- [Asset Errors](#asset-errors)
- [App Required](#app-required)
- [Annotation Errors](#annotation-errors)
- [Concurrent Lock](#concurrent-lock)
- [Dependency Cycle](#dependency-cycle)
- [No Stacks Matched](#no-stacks-matched)

---

## Overview

This reference covers errors that occur during `cdk synth` — before any CloudFormation deployment begins. These failures prevent the cloud assembly from being produced. Each section maps a specific error class to its root cause and fix.

---

## Cannot Find Module (Synth Time)

`cdk synth` fails with `Cannot find module` (TS) or `ModuleNotFoundError` (Python) before producing a template. The error occurs at **synth time**, not deploy time.

> For `Cannot find module '@aws-cdk/aws-*'` (v1→v2 migration) → see [v1-to-v2-migration](v1-to-v2-migration.md).
> For `Cannot find module` at **Lambda runtime** → see [troubleshooting-deployment](troubleshooting-deployment.md).

### TypeScript — diagnostic flow

**Step 1: Run `npx tsc --noEmit`.**

- **tsc fails** → problem is in your TS project. Check: missing `npm ci`, wrong `tsconfig.json` paths/rootDir/typeRoots, duplicate `aws-cdk-lib` (`npm ls aws-cdk-lib`), stale `node_modules` (`rm -rf node_modules && npm ci`).
- **tsc succeeds** → problem is in how CDK runs your app. Go to Step 2.

**Step 2: Check how `cdk.json` runs your app.**

The `app` field in `cdk.json` determines the execution mode. The failure causes differ:

**If `cdk.json` uses compiled JS** (e.g., `"app": "node bin/app.js"`):

| Cause | Symptom | Fix |
|-------|---------|-----|
| `outDir` mismatch with `cdk.json` | `Cannot find module 'bin/app.js'` | Ensure `tsconfig.json` `outDir` aligns with the path in `cdk.json`. If `outDir: "dist"`, then `"app": "node dist/bin/app.js"` |
| Stale compiled `.js` files | Module existed before but was renamed/deleted in TS | `rm -rf cdk.out dist && npm run build && cdk synth` |
| Never compiled | `.js` files don't exist | Run `npx tsc` or `npm run build` before `cdk synth` |

**If `cdk.json` uses direct TS execution** (e.g., `"app": "npx tsx bin/app.ts"`):

| Cause | Symptom | Fix |
|-------|---------|-----|
| Path aliases not resolved by ts-node | `Cannot find module 'lib/MyStack'` | Switch to `tsx`: `"app": "npx tsx bin/my-app.ts"` |
| Monorepo — wrong `node_modules` | `Cannot find module 'typescript'` | Verify hoisting: `npm ls typescript`. Point `cdk.json` at correct binary. pnpm: `shamefully-hoist=true`. |
| `npm link` / symlinked packages | `Cannot find module '@my/shared-constructs'` | Install peer deps explicitly, or `NODE_OPTIONS=--preserve-symlinks`. Long-term: publish to registry. |
| Wrong working directory | `cdk.json` not found | `cd` to directory containing `cdk.json` |

### Python — diagnostic flow

**Step 1: Check which Python is running** — `which python` vs the interpreter in `cdk.json`.

**Step 2: Test import** — `python -c "import aws_cdk; print(aws_cdk.__version__)"`.

| Cause | Symptom | Fix |
|-------|---------|-----|
| Virtualenv not activated | `No module named 'aws_cdk'` | `source .venv/bin/activate && pip install -r requirements.txt` |
| Missing `pip install` | `No module named 'my_constructs'` | `pip install -r requirements.txt` |
| CI — venv not activated | Module errors in pipeline | Activate in script, or set `"app": ".venv/bin/python app.py"` in `cdk.json` |
| Poetry / Pipenv | CDK runs outside managed env | `"app": "poetry run python app.py"` or `"app": "pipenv run python app.py"` |
| `cannot import name 'core' from 'aws_cdk'` | v1→v2 API change | Replace `from aws_cdk import core` with `import aws_cdk as cdk`. See [v1-to-v2-migration](v1-to-v2-migration.md). |

### Prevention

- You SHOULD use `tsx` instead of `ts-node` — native path alias support, faster
- You SHOULD run `npm ci` (TS) or `pip install -r requirements.txt` (Python) as the first CI step
- You SHOULD install `aws-cdk` CLI as a pinned dev dependency and invoke via `npx cdk`

---

## Asset Errors

Asset errors occur when CDK cannot locate, bundle, or publish file or Docker image assets.

### CannotFindAsset

The asset path does not exist at synth time.

**Fix:** You MUST use `path.join(__dirname, ...)` to build asset paths relative to the source file, not the working directory:

```typescript
new lambda.Function(this, 'Fn', {
  code: lambda.Code.fromAsset(path.join(__dirname, '../lambda')),
  // ...
});
```

### FailedToBundleAsset

The bundling command failed. Common cause: Docker is not running.

**Fix:** You MUST ensure Docker is running before synth. For Lambda bundling with esbuild, you SHOULD install esbuild locally to avoid the Docker fallback:

```bash
npm install --save-dev esbuild
```

### AssetBuildFailed

esbuild or Docker build returned a non-zero exit code.

**Fix:** Run the bundling command manually outside CDK to see the full error output. Check for missing dependencies, syntax errors, or incompatible platform targets.

### AssetPublishFailed

The asset was built successfully but upload to the bootstrap S3 bucket or ECR repository failed.

**Fix:** You MUST verify that the CDK publishing role has permission to write to the bootstrap bucket and ECR repository. Re-bootstrap if necessary:

```bash
cdk bootstrap aws://$ACCOUNT/$REGION
```

---

## App Required

```
--app is required either in command-line, in cdk.json, or in ~/.cdk.json
```

The CDK CLI cannot find the app entry point.

**Fix:** You MUST add the `app` key to `cdk.json`:

```json
{
  "app": "npx tsx bin/$APP_NAME.ts"
}
```

You SHOULD verify the path points to the file containing your `new App()` call.

---

## Annotation Errors

An Aspect or construct called `Annotations.of(node).addError()`, which causes synth to fail. This covers:

- **cdk-nag errors** — security/compliance rule violations.
- **Custom Aspect errors** — organization-wide policy checks.
- **Built-in CDK warnings promoted to errors** by the `--strict` flag.

### Diagnosis

You MUST fix the underlying issue flagged by the annotation. Read the error message to identify which construct and which rule triggered it.

### Suppression (last resort)

You SHOULD only suppress annotations when the flagged pattern is intentional and justified. Suppression patterns for cdk-nag:

**Per-resource:**

```typescript
NagSuppressions.addResourceSuppressions(myBucket, [
  { id: '$RULE_ID', reason: '$JUSTIFICATION' },
]);
```

**Per-stack:**

```typescript
NagSuppressions.addStackSuppressions(myStack, [
  { id: '$RULE_ID', reason: '$JUSTIFICATION' },
]);
```

**By path:**

```typescript
NagSuppressions.addResourceSuppressionsByPath(stack, '/$STACK/$CONSTRUCT_PATH', [
  { id: '$RULE_ID', reason: '$JUSTIFICATION' },
]);
```

You MUST NOT suppress annotations without providing a reason.

---

## Concurrent Lock

```
Cannot lock cdk.out: file is locked by another process
```

A file lock on the `cdk.out` directory prevents synth. This happens when a previous synth crashed or when multiple synth processes target the same output directory.

### Fix — single build

```bash
rm -rf cdk.out
```

### Fix — parallel CI

You MUST use a unique output directory per build to avoid lock contention:

```bash
cdk synth --output ./cdk.out.$BUILD_ID
```

---

## Dependency Cycle

```
Error: 'StackA' depends on 'StackB' depends on 'StackA'
```

A circular reference exists between two or more stacks.

### Fixes

1. **Extract shared resource into a third stack.** The shared resource lives in its own stack, and both consumers depend on it (one-way).

2. **Use SSM for late-binding.** The producer writes a value to SSM Parameter Store; the consumer reads it at deploy time. This breaks the synth-time dependency:

   ```typescript
   // Producer stack
   new ssm.StringParameter(this, 'Param', {
     parameterName: '/$APP/$RESOURCE_ARN',
     stringValue: resource.resourceArn,
   });

   // Consumer stack
   const arn = ssm.StringParameter.valueForStringParameter(this, '/$APP/$RESOURCE_ARN');
   ```

3. **Pass raw ARN strings** instead of construct references when the full construct object is not needed.

### Prevention

You SHOULD design stack dependencies as one-way: props flow from producer to consumer. You MUST NOT create reverse references from a producer back to its consumer.

---

## No Stacks Matched

```
No stacks match the name(s) $STACK_NAME
```

CDK selects stacks by their **logical ID** (the second argument to the `Stack` constructor), not by the CloudFormation stack name.

### Diagnosis

List all stack IDs in the app:

```bash
cdk list
```

### Deploy options

```bash
# Exact logical ID
cdk deploy $STACK_ID

# Wildcard
cdk deploy "$PATTERN*"

# All stacks
cdk deploy --all
```

You MUST use the logical ID as shown by `cdk list`, not the CloudFormation stack name visible in the AWS console.
