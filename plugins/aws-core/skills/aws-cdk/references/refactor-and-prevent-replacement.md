# Refactor and Prevent Replacement Reference

## Table of Contents

- [Overview](#overview)
- [Detecting Replacement](#detecting-replacement)
- [Common Causes](#common-causes)
- [Using cdk refactor](#using-cdk-refactor)
  - [Workflow](#workflow)
  - [Resolving Ambiguity](#resolving-ambiguity)
  - [Constraints](#constraints)
- [Prevention Techniques](#prevention-techniques)
  - [Do Not Hardcode Physical Names](#do-not-hardcode-physical-names)
  - [Use Default as Child ID](#use-default-as-child-id)
  - [Use cdk refactor for Moves and Renames](#use-cdk-refactor-for-moves-and-renames)
  - [Use overrideLogicalId](#use-overridelogicalid)
  - [Lock Logical IDs with Unit Tests](#lock-logical-ids-with-unit-tests)
  - [Isolate Stateful Resources with RETAIN](#isolate-stateful-resources-with-retain)
- [Protecting Stateful Resources](#protecting-stateful-resources)

---

## Overview

Resource replacement occurs when CloudFormation determines it must delete and
recreate a resource instead of updating it in place. For stateful resources
(databases, S3 buckets, encryption keys), replacement causes **data loss**.
This reference covers detection, common causes, and prevention techniques.

---

## Detecting Replacement

Use `cdk diff` to detect pending replacements before deploying:

```bash
cdk diff $STACK_NAME
```

In the output, look for:

- `[-]` markers indicating resource deletion.
- `[~]` markers with "requires replacement" annotations on specific properties.

Any resource showing "requires replacement" MUST be investigated before
deploying. MUST NOT deploy when `cdk diff` shows replacement of stateful
resources unless the replacement is intentional and data has been backed up.

---

## Common Causes

Resource replacement is typically caused by:

1. **Construct ID changes** — Renaming a construct or moving it to a different
   scope changes its CloudFormation logical ID, which CloudFormation treats as
   a delete + create.

2. **Immutable CloudFormation properties** — Certain resource properties cannot
   be updated in place (e.g., DynamoDB table name, RDS engine). Changing these
   forces replacement.

3. **Hardcoded physical names** — If a resource has a hardcoded physical name
   and the logical ID changes, CloudFormation cannot create the new resource
   because the name is already taken, causing a deployment failure.

---

## Using cdk refactor

`cdk refactor` safely moves or renames constructs without triggering resource
replacement. It is currently an unstable feature.

### Workflow

1. **Deploy a baseline** — Ensure the current state is deployed and clean.

   ```bash
   cdk deploy $STACK_NAME
   ```

2. **Edit the code** — Perform moves and renames only. MUST NOT change resource
   properties in the same step.

3. **Run refactor** — Generate the resource mapping:

   ```bash
   cdk refactor --unstable=refactor
   ```

4. **Confirm the mapping** — Review the proposed logical ID mappings.

5. **Deploy** — Apply the refactoring:

   ```bash
   cdk deploy $STACK_NAME
   ```

6. **Deploy property changes separately** — Any property changes MUST be made
   and deployed in a subsequent step, after the refactor deploy succeeds.

### Resolving Ambiguity

When `cdk refactor` cannot determine the mapping (e.g., multiple resources of
the same type were moved), provide an override JSON file to resolve the
ambiguity.

### Constraints

- Refactoring MUST stay within the same environment (account + region).
- Only moves and renames are supported — property changes MUST NOT be combined
  with refactoring in the same deployment.

---

## Prevention Techniques

### Do Not Hardcode Physical Names

Physical resource names (bucket names, table names, queue names) SHOULD NOT be
hardcoded. Let CloudFormation generate unique names. Hardcoded names prevent
CloudFormation from performing replacement when needed and cause name-collision
failures.

### Use Default as Child ID

When extracting inline resources into a separate construct, use `'Default'` as
the child construct ID to preserve the original logical ID:

```typescript
// Before: resource defined directly in the stack
new s3.Bucket(this, 'MyBucket', { ... });

// After: extracted into a construct — use 'Default' to keep the same logical ID
class MyConstruct extends Construct {
  constructor(scope: Construct, id: string) {
    super(scope, id);
    new s3.Bucket(this, 'Default', { ... });
  }
}
new MyConstruct(this, 'MyBucket');
```

### Use cdk refactor for Moves and Renames

When moving or renaming constructs, use `cdk refactor --unstable=refactor`
instead of manually tracking logical IDs. See [Using cdk refactor](#using-cdk-refactor).

### Use overrideLogicalId

As an alternative to `cdk refactor`, explicitly set the logical ID to preserve
it across code changes:

```typescript
const bucket = new s3.Bucket(this, 'NewId', { ... });
(bucket.node.defaultChild as s3.CfnBucket).overrideLogicalId('$ORIGINAL_LOGICAL_ID');
```

This approach SHOULD be used sparingly — it creates a maintenance burden and
bypasses CDK's automatic ID generation.

### Lock Logical IDs with Unit Tests

Write unit tests that assert the logical IDs of stateful resources. This
prevents accidental ID changes from reaching deployment:

```typescript
test('stateful resource logical IDs are stable', () => {
  const template = Template.fromStack($STACK);
  const tables = template.findResources('AWS::DynamoDB::Table');
  expect(Object.keys(tables)).toContain('$EXPECTED_LOGICAL_ID');
});
```

### Isolate Stateful Resources with RETAIN

Place stateful resources in a dedicated stack with the `RETAIN` removal policy.
This ensures that even if the stack is deleted, the resources are preserved:

```typescript
new s3.Bucket(this, 'DataBucket', {
  removalPolicy: RemovalPolicy.RETAIN,
});
```

---

## Protecting Stateful Resources

A defense-in-depth approach SHOULD be used for stateful resources:

1. **RETAIN removal policy** — Prevents data loss on stack deletion.
2. **Dedicated stack** — Isolates stateful resources from frequently changing
   application stacks.
3. **Logical ID unit tests** — Catches accidental renames before deployment.
4. **`cdk diff` review** — MUST be reviewed before every production deployment.
5. **No hardcoded physical names** — Avoids name-collision failures during
   replacement.
