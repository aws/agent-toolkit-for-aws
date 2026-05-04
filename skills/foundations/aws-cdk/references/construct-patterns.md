# Construct Patterns

## Table of Contents

- [Overview](#overview)
- [Choosing Construct Levels](#choosing-construct-levels)
- [Mixing L1 and L2](#mixing-l1-and-l2)
- [Cross-Stack References](#cross-stack-references)
- [Creating Custom Constructs](#creating-custom-constructs)
- [Testing CDK Infrastructure](#testing-cdk-infrastructure)

---

## Overview

This reference covers construct selection, composition, cross-stack wiring, and testing patterns. It provides decision frameworks for choosing construct levels, mixing them safely, passing references across stacks, building custom constructs, and verifying infrastructure with assertions.

---

## Choosing Construct Levels

You SHOULD prefer L2 constructs as the default choice. They provide sensible defaults, grant methods, and metric helpers.

### Decision tree

| Need                                   | Construct type                             |
| -------------------------------------- | ------------------------------------------ |
| Pure logic, no AWS resource            | Plain TypeScript/Python class              |
| Single resource with stricter defaults | Extend the L2 class (is-a)                 |
| Composition of multiple resources      | Extend `Construct` (has-a) — this is an L3 |
| Organization-wide policy enforcement   | `Aspect`                                   |

### When L1 is viable

L1 (`Cfn*`) constructs are acceptable when no L2 exists or when you need a property the L2 does not expose. You SHOULD combine L1 with Mixins, Facades, or `I``<Resource>``Ref` interfaces to retain type safety and grant support.

### When using L3

L3 constructs provision multiple resources behind a single API. You MUST read what they provision (check the source or `cdk synth` output) before using them in production. Hidden resources may have cost, security, or operational implications.

### When an L2 doesn't expose a property

Use this escalation ladder — prefer the first option that works:

1. **Cfn``<Resource>``PropsMixin** (preferred) — type-safe, applied via `.with()`:

   ```typescript
   import { CfnBucketPropsMixin } from '@aws-cdk/cfn-property-mixins/aws-s3';
   new s3.Bucket(this, 'Bucket').with(new CfnBucketPropsMixin({
     analyticsConfigurations: [{ id: 'full', prefix: '' }],
   }));
   ```

2. **`addPropertyOverride`** — untyped, string-keyed last resort:

   ```typescript
   const cfnBucket = bucket.node.defaultChild as s3.CfnBucket;
   cfnBucket.addPropertyOverride('AnalyticsConfigurations', [{ Id: 'full', Prefix: '' }]);
   ```

---

## Mixing L1 and L2

When a stack contains both L1 and L2 constructs, you MUST use `I``<Resource>``Ref` interfaces and Facades to bridge them — do not pass L1 property types to L2 props or vice versa, as their types are not interchangeable.

### I``<Resource>``Ref interfaces (e.g. IBucketRef)

Both L1 and L2 constructs implement `I``<Resource>``Ref`-style interfaces (e.g., `IBucketRef`, `IFunctionRef`). Use these interfaces as prop types to accept either level:

```typescript
interface MyProps {
  readonly bucket: s3.IBucketRef;
}
```

### Facades for L1 grants

L1 constructs lack `grant*()` methods. You SHOULD wrap them with `fromCfn``<Resource>``()` or `from``<Resource>``Attributes()` to get an L2 interface:

```typescript
const cfnTable = new dynamodb.CfnTable(this, 'Table', { /* ... */ });
const table = dynamodb.Table.fromTableArn(this, 'TableRef', cfnTable.attrArn);
table.grantReadData(myFunction);
```

### Escalation ladder

When you need to customize a resource, follow this order (least invasive first):

1. L2 prop — use the built-in property if available.
2. Mixin — add behavior via a helper function.
3. `Cfn``<Resource>``PropsMixin` — type-safe L1 prop injection.
4. `node.defaultChild` — access the underlying L1 construct.
5. `addPropertyOverride` — override arbitrary CloudFormation properties.

You SHOULD exhaust each level before moving to the next.

---

## Cross-Stack References

### Same app, same region

Pass construct references via stack props. CDK automatically creates CloudFormation exports and imports:

```typescript
interface ConsumerProps extends cdk.StackProps {
  readonly bucket: s3.IBucket;
}

class ConsumerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ConsumerProps) {
    super(scope, id, props);
    props.bucket.grantRead(myFunction);
  }
}
```

### Cross-region or cross-account (same app)

Enable `crossRegionReferences: true` on the consuming stack and use explicit physical names on shared resources:

```typescript
new ConsumerStack(app, 'Consumer', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
  crossRegionReferences: true,
  bucket: producerStack.bucket,
});
```

### Different apps

When stacks are in different CDK apps, automatic exports do not work. You MUST use one of:

- `CfnOutput` + `Fn.importValue`:

  ```typescript
  // Producer app
  new cdk.CfnOutput(this, 'BucketArn', { value: bucket.bucketArn, exportName: '$EXPORT_NAME' });

  // Consumer app
  const arn = cdk.Fn.importValue('$EXPORT_NAME');
  ```

- SSM Parameter Store for decoupled lookups.

### Fixing cycles

If cross-stack references create a dependency cycle, you MUST extract the shared resource into a third stack so that dependencies flow one way.

---

## Creating Custom Constructs

### Extend L2 (is-a)

Use when you want a single resource with stricter defaults:

```typescript
export class SecureBucket extends s3.Bucket {
  constructor(scope: Construct, id: string, props?: s3.BucketProps) {
    super(scope, id, {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      ...props,
    });
  }
}
```

### Compose L3 (has-a)

Use when you combine multiple resources behind a single API:

```typescript
export class ApiWithQueue extends Construct {
  public readonly queue: sqs.Queue;

  constructor(scope: Construct, id: string) {
    super(scope, id);
    this.queue = new sqs.Queue(this, 'Queue');
    // ... additional resources
  }
}
```

### Stable logical IDs

The default child ID determines the CloudFormation logical ID. You MUST NOT change construct IDs after deployment — this causes resource replacement. Use the `Default` child ID convention for the primary resource in an L3.

### Escape via defaultChild

When extending an L2, you can access the underlying CFN resource:

```typescript
const cfn = this.node.defaultChild as s3.CfnBucket;
cfn.addPropertyOverride('$PROPERTY_PATH', '$VALUE');
```

---

## Testing CDK Infrastructure

### Fine-grained assertions

Use `Template.fromStack()` to assert on specific resources:

```typescript
const template = Template.fromStack(myStack);

template.hasResourceProperties('AWS::SQS::Queue', {
  VisibilityTimeout: 300,
});
```

### Partial matching

Use `Match.*` helpers for flexible assertions:

```typescript
template.hasResourceProperties('AWS::Lambda::Function', {
  Runtime: Match.stringLikeRegexp('nodejs'),
  Environment: Match.objectLike({
    Variables: Match.objectLike({
      TABLE_NAME: Match.anyValue(),
    }),
  }),
});
```

### Snapshot tests

Capture the full template and compare against a stored baseline:

```typescript
expect(template.toJSON()).toMatchSnapshot();
```

You SHOULD use snapshot tests to detect unintended drift but MUST NOT rely on them as the sole testing strategy — they are brittle and hard to review.

### Logical ID stability tests

Assert that critical resource logical IDs remain stable to prevent accidental replacement:

```typescript
template.hasResource('AWS::DynamoDB::Table', {
  // Verifying the resource exists with this logical ID
});
```

### Integration tests

Use `@aws-cdk/integ-tests-alpha` for tests that deploy real infrastructure:

```typescript
const integ = new IntegTest(app, 'MyIntegTest', {
  testCases: [myStack],
});

integ.assertions
  .awsApiCall('DynamoDB', 'DescribeTable', { TableName: '$TABLE_NAME' })
  .assertAtPath('Table.TableStatus', ExpectedResult.stringLikeRegexp('ACTIVE'));
```

Integration tests SHOULD be run in a dedicated test account. They MUST NOT run against production.

### Application best practices

- Make decisions at synth time — use explicit `env` to enable synth-time logic.
- Use generated physical names (CDK default) unless cross-stack or cross-app references require explicit names.
- Set explicit `removalPolicy` and `logRetention` on every resource.
- Separate stateful resources (databases, buckets) into their own stack.
- Commit `cdk.context.json` to version control for reproducible synth.
- Use `grant*()` methods for IAM instead of hand-written policy statements.
