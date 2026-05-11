# Troubleshooting: Credentials and Environment

## Table of Contents

- [Troubleshooting: Credentials and Environment](#troubleshooting-credentials-and-environment)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [NoCredentials / ExpiredToken / AssumeRoleFailed](#nocredentials--expiredtoken--assumerolefailed)
    - [Error variants](#error-variants)
    - [Diagnosis](#diagnosis)
    - [Common causes and fixes](#common-causes-and-fixes)
  - [Bootstrap Version Validation](#bootstrap-version-validation)
    - [Error variants](#error-variants-1)
    - [Fixes](#fixes)
  - [Unresolved Account](#unresolved-account)
    - [Fix — set explicit environment](#fix--set-explicit-environment)
    - [Fix — commit context](#fix--commit-context)
    - [Alternatives to context providers](#alternatives-to-context-providers)
  - [Account/Region Tokens](#accountregion-tokens)
    - [Problem](#problem)
    - [Fix](#fix)

---

## Overview

This reference covers authentication, authorization, and environment-resolution errors. These failures occur when the CDK CLI cannot determine who you are, what account/region to target, or whether the bootstrap stack is compatible.

---

## NoCredentials / ExpiredToken / AssumeRoleFailed

### Error variants

| Error                    | Meaning                                                        |
| ------------------------ | -------------------------------------------------------------- |
| `NoCredentials`          | No AWS credentials found in the environment                    |
| `ExpiredToken`           | Credentials exist but the session has expired                  |
| `AssumeRoleFailed`       | CLI found credentials but cannot assume the CDK bootstrap role |
| `AssumeRoleExpiredToken` | Token expired during a role assumption chain                   |

### Diagnosis

You MUST run these commands first:

```bash
aws sts get-caller-identity
cdk doctor
```

If `get-caller-identity` fails, the problem is with your base credentials, not CDK.

### Common causes and fixes

**No CLI credentials configured:**

You MUST configure credentials via one of: `~/.aws/credentials`, environment variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`), or SSO.

**Wrong profile:**

```bash
cdk deploy $STACK --profile $PROFILE
```

Or set the environment variable:

```bash
export AWS_PROFILE=$PROFILE
```

**Expired SSO session:**

```bash
aws sso login --profile $PROFILE
```

**Missing `sts:AssumeRole` on bootstrap roles:**

The CDK CLI assumes roles created by `cdk bootstrap`. If the calling principal lacks `sts:AssumeRole` permission on those roles, deployment fails. You MUST verify the trust policy on the bootstrap roles allows your identity.

---

## Bootstrap Version Validation

### Error variants

- `BootstrapVersionValidation` — the deployed bootstrap stack version is too old for the constructs being deployed.
- `SSM parameter /cdk-bootstrap/$QUALIFIER/version not found` — the bootstrap stack does not exist in the target account/region, or the qualifier does not match.
- `Cloud assembly schema version mismatch` — the CLI version is incompatible with the cloud assembly produced by the CDK library.

### Fixes

**Re-bootstrap the target environment:**

```bash
cdk bootstrap aws://$ACCOUNT/$REGION
```

**Match the qualifier** if you use a custom one:

```bash
cdk bootstrap aws://$ACCOUNT/$REGION --qualifier $QUALIFIER
```

**Grant SSM read access:**

The CDK CLI reads the bootstrap version from SSM Parameter Store. The deploying role MUST have `ssm:GetParameter` permission on `/cdk-bootstrap/$QUALIFIER/version`.

**CLI version mismatch:**

You SHOULD pin `aws-cdk` as a dev dependency to keep the CLI version aligned with the library:

```bash
npm install --save-dev aws-cdk@$VERSION
npx cdk deploy $STACK
```

This prevents drift between the globally installed CLI and the library version used in your project.

---

## Unresolved Account

```
Cannot determine account/region; context providers need concrete values
```

Context providers (e.g., `Vpc.fromLookup`) make API calls at synth time and MUST know the target account and region. Env-agnostic stacks (no explicit `env`) cannot use context providers.

### Fix — set explicit environment

```typescript
new MyStack(app, 'MyStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});
```

`CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION` are set automatically by the CDK CLI from your current credentials.

### Fix — commit context

You MUST commit `cdk.context.json` to version control. This file caches the results of context provider lookups so that synth is reproducible without live API calls.

### Alternatives to context providers

If you cannot set an explicit environment, you SHOULD use one of:

- `ec2.Vpc.fromVpcAttributes()` — provide VPC ID, AZs, and subnet IDs directly.
- SSM Parameter Store lookups at deploy time — store infrastructure values in SSM and read them with `ssm.StringParameter.valueForStringParameter()`.

---

## Account/Region Tokens

`stack.account` and `stack.region` return **Tokens** (lazy placeholders), not real values, when the stack is env-agnostic.

### Problem

```typescript
if (stack.region === 'us-east-1') {
  // This NEVER matches — stack.region is a Token string like ${Token[AWS.Region.1234]}
}
```

Tokens are resolved by CloudFormation at deploy time, not at synth time. You MUST NOT use them in synth-time conditional logic.

### Fix

Set an explicit environment on the stack so that `stack.account` and `stack.region` resolve to real values at synth time:

```typescript
new MyStack(app, 'MyStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
});
```

With an explicit env, synth-time conditionals work as expected. Without it, you MUST use `CfnCondition` for deploy-time branching instead of TypeScript `if` statements.
