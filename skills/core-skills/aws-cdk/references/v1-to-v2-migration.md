# CDK v1 to v2 Migration

## Table of Contents

- [Overview](#overview)
- [V1 Import Paths](#v1-import-paths)
- [Wrong Construct Import](#wrong-construct-import)
- [Duplicate aws-cdk-lib](#duplicate-aws-cdk-lib)

---

## Overview

CDK v2 consolidated all `@aws-cdk/*` packages into a single `aws-cdk-lib` package and moved `Construct` to the standalone `constructs` package. These changes cause three common error patterns when migrating from v1 or when mixing v1/v2 code.

---

## V1 Import Paths

### Symptom

```
Cannot find module '@aws-cdk/aws-ec2'
Cannot find module '@aws-cdk/aws-s3'
Cannot find module '@aws-cdk/core'
```

### Cause

CDK v2 consolidated all `@aws-cdk/*` packages into `aws-cdk-lib`. Old v1 package names no longer resolve.

### Fix

Replace v1 imports with v2 equivalents:

```typescript
// Wrong (v1)
import * as ec2 from '@aws-cdk/aws-ec2';
import * as s3 from '@aws-cdk/aws-s3';
import { Construct } from '@aws-cdk/core';

// Correct (v2)
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
```

You MUST also remove all `@aws-cdk/*` packages from `package.json` dependencies and replace with a single `aws-cdk-lib` dependency.

---

## Wrong Construct Import

### Symptom

```
Argument of type 'this' is not assignable to parameter of type 'Construct'
```

This error appears even though the code looks correct — the types have the same name but come from different packages.

### Cause

`Construct` was imported from `@aws-cdk/core` or `aws-cdk-lib` instead of the standalone `constructs` package. In CDK v2, all constructs MUST extend `Construct` from the `constructs` package.

### Fix

```typescript
// Wrong
import { Construct } from 'aws-cdk-lib';
import { Construct } from '@aws-cdk/core';

// Correct
import { Construct } from 'constructs';
```

You MUST ensure `constructs` is listed as a dependency in `package.json`.

---

## Duplicate aws-cdk-lib

### Symptom

```
Argument of type 'Function' is not assignable to parameter of type 'IFunction'
Argument of type 'Bucket' is not assignable to parameter of type 'IBucket'
```

TypeScript uses structural typing, but CDK classes contain private members, which causes TypeScript to treat them nominally. When two copies of `aws-cdk-lib` exist, the private members originate from different class declarations, making types like `Function` and `IFunction` from different copies incompatible.

### Cause

Multiple copies of `aws-cdk-lib` exist in the module graph. Common causes:

- Monorepo with improperly hoisted dependencies
- Shared construct library declares `aws-cdk-lib` as a regular dependency instead of a peer dependency
- `npm link` or `file:` protocol pulling in a second copy

### Diagnosis

```bash
npm ls aws-cdk-lib
```

If more than one version appears, you have duplicates.

### Fix

1. You MUST make `aws-cdk-lib` and `constructs` **peer dependencies** in shared construct libraries
2. Run `npm dedupe` to collapse duplicates
3. In monorepos, hoist `aws-cdk-lib` to the root workspace
4. Verify with `npm ls aws-cdk-lib` — only one copy SHOULD appear
