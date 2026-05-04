# Import and Migrate Reference

## Table of Contents

- [Overview](#overview)
- [Read-Only References (from* Methods)](#read-only-references-from-methods)
- [Full Resource Adoption (cdk import)](#full-resource-adoption-cdk-import)
- [CI-Friendly Import (--import-existing-resources)](#ci-friendly-import---import-existing-resources)
- [Migrating with cdk migrate](#migrating-with-cdk-migrate)
  - [From an Existing Stack](#from-an-existing-stack)
  - [From a Template File](#from-a-template-file)
  - [From a Live Account Scan](#from-a-live-account-scan)
  - [Migration Constraints](#migration-constraints)
  - [First Deploy After Migration](#first-deploy-after-migration)
  - [Incremental Refactoring](#incremental-refactoring)
- [Post-Import Verification](#post-import-verification)

---

## Overview

CDK provides three mechanisms for referencing or adopting existing AWS resources,
plus a migration tool for converting existing CloudFormation stacks or live
infrastructure into CDK code. The right mechanism depends on whether you need
read-only access or full lifecycle management.

| Mechanism                        | Use Case                          | Lifecycle Control |
|----------------------------------|-----------------------------------|-------------------|
| `from*` methods                  | Reference existing resources      | Read-only         |
| `cdk import`                     | Adopt resources into a stack      | Full (interactive)|
| `--import-existing-resources`    | Adopt resources in CI             | Full (automated)  |
| `cdk migrate`                    | Convert stacks/infra to CDK code  | Full              |

---

## Read-Only References (from* Methods)

Use `from*` static methods (e.g., `Bucket.fromBucketName()`,
`Vpc.fromLookup()`) to reference existing resources without managing their
lifecycle:

```typescript
const bucket = s3.Bucket.fromBucketName(this, 'ImportedBucket', '$BUCKET_NAME');
const vpc = ec2.Vpc.fromLookup(this, 'ImportedVpc', { vpcId: '$VPC_ID' });
```

Constraints:

- `from*` references are **read-only** — CDK MUST NOT attempt to modify or
  delete these resources.
- `fromLookup` methods require the `env` property (account and region) to be
  set on the stack. They perform API calls at synth time and cache results in
  `cdk.context.json`.
- `cdk.context.json` SHOULD be committed to version control so that synth is
  reproducible without network access.

---

## Full Resource Adoption (cdk import)

`cdk import` adopts existing resources into a CDK stack so CDK fully manages their lifecycle.

**Interactive (default):**

```bash
cdk import $STACK_NAME
```

The CLI prompts for each resource's physical identifier (bucket name, table name, etc.).

**Non-interactive (CI-friendly):**

```bash
# First, generate a mapping template:
cdk import $STACK_NAME --record-resource-mapping mapping.json

# Fill in the physical resource IDs, then import:
cdk import $STACK_NAME --resource-mapping mapping.json
```

Workflow:

1. Add the construct to your CDK code matching the existing resource's properties
2. Run `cdk import $STACK_NAME` (interactive) or with `--resource-mapping` (CI)
3. CloudFormation executes an import change set — no resource is created

Constraints:

- Not all CloudFormation resource types support import
- Resources that depend on each other MUST be imported together or in the correct order
- The only allowed changes during import are additions of the imported resources

---

## CI-Friendly Import (--import-existing-resources)

For non-interactive, CI-friendly imports, use the `--import-existing-resources` flag during a normal deploy:

```bash
cdk deploy $STACK_NAME --import-existing-resources
```

The CLI matches resources in the synthesized template against existing unmanaged resources in the account by their **custom physical name** (e.g., explicit `bucketName`, `tableName`, `roleName`). Matches are imported instead of created.

**Constraints:**

- You MUST set explicit physical names on resources you want to import — auto-generated names cannot be matched
- The resource MUST be unmanaged (not already part of another CloudFormation stack)
- Not every resource type supports CloudFormation import
- Supports mixed operations — you can add new resources AND import existing ones in the same deploy

**When to prefer over `cdk import`:**

- CI/CD pipelines where interactive prompts are not possible
- Rolling out a new stack that overlaps with existing resources
- Mixed operations (new + imported resources in one change set)

---

## Migrating with cdk migrate

`cdk migrate` generates CDK code from existing CloudFormation stacks, template
files, or live account scans.

### From an Existing Stack

```bash
cdk migrate --from-stack --stack-name $STACK_NAME
```

### From a Template File

```bash
cdk migrate --from-path $TEMPLATE_FILE_PATH --stack-name $STACK_NAME
```

### From a Live Account Scan

```bash
cdk migrate --from-scan --stack-name $STACK_NAME
```

### Migration Constraints

- Output is **L1 constructs only** (`Cfn*` classes). Higher-level L2/L3
  constructs are NOT generated.
- Only a **single stack** can be migrated per invocation.
- **Assets are not migrated** — inline code, S3 references, and Docker images
  MUST be handled manually after migration.

### First Deploy After Migration

A `migrate.json` file is generated alongside the CDK code. This file is
REQUIRED for the first deployment after migration — it tells CloudFormation to
import the existing resources rather than creating new ones.

```bash
cdk deploy $STACK_NAME
```

The `migrate.json` file is consumed automatically on the first deploy and MAY
be removed afterward.

### Incremental Refactoring

After migration, incrementally refactor L1 constructs to L2/L3 constructs:

1. Replace one `Cfn*` resource at a time with its L2/L3 equivalent.
2. Run `cdk diff` after each change to verify no unintended replacements.
3. Deploy incrementally to validate each refactoring step.

---

## Post-Import Verification

After importing or migrating resources, the following steps MUST be performed:

1. **Verify drift** — Run `cdk drift $STACK_NAME` to confirm the imported
   resource state matches the CDK definition.
2. **Protect logical IDs** — Logical ID changes after import will cause
   resource replacement. Lock logical IDs with unit tests or use
   `overrideLogicalId()` where necessary.
3. **Run `cdk diff`** — Confirm no unexpected changes are pending before the
   next deployment.
