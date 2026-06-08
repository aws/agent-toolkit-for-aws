# Concurrent Operations

Process arrays and run operations in parallel with concurrency control.

## Map Operations

Process arrays with automatic concurrency control and completion policies:

**TypeScript:**

```typescript
const items = [1, 2, 3, 4, 5];

const results = await context.map(
  'process-items',
  items,
  async (ctx, item, index) => {
    return await ctx.step(`process-${index}`, async () => 
      processItem(item)
    );
  },
  {
    maxConcurrency: 3,
    completionConfig: {
      minSuccessful: 4,
      toleratedFailureCount: 1
    }
  }
);

results.throwIfError();
const allResults = results.getResults();
```

**Python:**

```python
# Note: process is decorated with @durable_step
from aws_durable_execution_sdk_python.config import MapConfig, CompletionConfig

items = [1, 2, 3, 4, 5]

def process_item(ctx: DurableContext, item: int, index: int, items: list):
    return ctx.step(process(item), name=f'process-{index}')

results = context.map(
    inputs=items,
    func=process_item,
    name='process-items',
    config=MapConfig(
        max_concurrency=3,
        completion_config=CompletionConfig(
            min_successful=4,
            tolerated_failure_count=1
        )
    )
)

results.throw_if_error()
all_results = results.get_results()
```

## Parallel Operations

Run heterogeneous operations concurrently:

**TypeScript:**

```typescript
const results = await context.parallel(
  'parallel-ops',
  [
    {
      name: 'fetch-user',
      func: async (ctx) => ctx.step(async () => fetchUser(userId))
    },
    {
      name: 'fetch-orders',
      func: async (ctx) => ctx.step(async () => fetchOrders(userId))
    },
    {
      name: 'fetch-preferences',
      func: async (ctx) => ctx.step(async () => fetchPreferences(userId))
    }
  ],
  { maxConcurrency: 3 }
);

const [user, orders, preferences] = results.getResults();
```

**Python:**

```python
# Note: fetch_user, fetch_orders, fetch_preferences are decorated with @durable_step
from aws_durable_execution_sdk_python.config import ParallelConfig

def fetch_user_data(ctx: DurableContext):
    return ctx.step(fetch_user(user_id))

def fetch_orders_data(ctx: DurableContext):
    return ctx.step(fetch_orders(user_id))

def fetch_prefs_data(ctx: DurableContext):
    return ctx.step(fetch_preferences(user_id))

results = context.parallel(
    [fetch_user_data, fetch_orders_data, fetch_prefs_data],
    name='parallel-ops',
    config=ParallelConfig(max_concurrency=3)
)

user, orders, preferences = results.get_results()
```

## Completion Policies

### Minimum Successful

Require a minimum number of successful operations:

**TypeScript:**

```typescript
const results = await context.map(
  'process-batch',
  items,
  async (ctx, item, index) => ctx.step(async () => process(item)),
  {
    completionConfig: {
      minSuccessful: 8  // Need at least 8 successes
    }
  }
);
```

### Tolerated Failures

Allow a specific number of failures:

**TypeScript:**

```typescript
const results = await context.map(
  'process-batch',
  items,
  async (ctx, item, index) => ctx.step(async () => process(item)),
  {
    completionConfig: {
      toleratedFailureCount: 2  // Allow up to 2 failures
    }
  }
);
```

### Tolerated Failure Percentage

Allow a percentage of failures:

**TypeScript:**

```typescript
const results = await context.map(
  'process-batch',
  items,
  async (ctx, item, index) => ctx.step(async () => process(item)),
  {
    completionConfig: {
      toleratedFailurePercentage: 10  // Allow up to 10% failures
    }
  }
);
```

**Python:**

```python
results = context.map(
    inputs=items,
    func=process_item,
    config=MapConfig(
        completion_config=CompletionConfig(
            tolerated_failure_percentage=10
        )
    ),
    name='process-batch'
)
```

## Batch Result Handling

### Check Status

**TypeScript:**

```typescript
const results = await context.map('process', items, processFunc);

console.log(results.status);           // 'SUCCEEDED' | 'FAILED'
console.log(results.totalCount);       // Total items
console.log(results.startedCount);     // Items started
console.log(results.successCount);     // Successful items
console.log(results.failureCount);     // Failed items
console.log(results.hasFailure);     // Boolean
```

### Get Results

**TypeScript:**

```typescript
// Get all results (throws if any failed)
const allResults = results.getResults();

// Get successful results only
const successful = results.succeeded().map(item => item.result);

// Get failed items
const failed = results.failed().map(item => ({
  index: item.index,
  error: item.error
}));

// Get all items with status
const all = results.all.map(item => ({
  index: item.index,
  status: item.status,
  result: item.result,
  error: item.error
}));
```

### Error Handling

**TypeScript:**

```typescript
const results = await context.map('process', items, processFunc);

if (results.hasFailure) {
  context.logger.error('Some items failed', {
    failureCount: results.failureCount,
    failures: results.failed().map(f => f.index)
  });
  
  // Retry failed items
  const failedItems = results.failed().map(f => items[f.index]);
  await context.map('retry-failed', failedItems, processFunc);
}
```

## Concurrency Control

### Fixed Concurrency

**TypeScript:**

```typescript
const results = await context.map(
  'process',
  items,
  processFunc,
  { maxConcurrency: 5 }  // Process 5 items at a time
);
```

### Dynamic Concurrency

Adjust based on item characteristics:

**TypeScript:**

```typescript
const results = await context.map(
  'process',
  items,
  async (ctx, item, index) => {
    // Heavy items get their own processing
    if (item.size > 1000) {
      return await ctx.step(`heavy-${index}`, async () => 
        processHeavy(item)
      );
    }
    
    // Light items can be batched
    return await ctx.step(`light-${index}`, async () => 
      processLight(item)
    );
  },
  { maxConcurrency: 10 }
);
```

## Advanced Patterns

### Map with Callbacks

**TypeScript:**

```typescript
const results = await context.map(
  'process-with-approval',
  items,
  async (ctx, item, index) => {
    const processed = await ctx.step('process', async () => 
      process(item)
    );
    
    const approved = await ctx.waitForCallback(
      'approval',
      async (callbackId) => sendApproval(item, callbackId),
      { timeout: { hours: 24 } }
    );
    
    return { processed, approved };
  },
  { maxConcurrency: 3 }
);
```

### Nested Map Operations

**TypeScript:**

```typescript
const results = await context.map(
  'process-batches',
  batches,
  async (ctx, batch, batchIndex) => {
    return await ctx.map(
      `batch-${batchIndex}`,
      batch.items,
      async (itemCtx, item, itemIndex) => {
        return await itemCtx.step(async () => process(item));
      }
    );
  }
);
```

### Map with Child Contexts

**TypeScript:**

```typescript
const results = await context.map(
  'complex-process',
  items,
  async (ctx, item, index) => {
    return await ctx.runInChildContext(`item-${index}`, async (childCtx) => {
      const validated = await childCtx.step('validate', async () => 
        validate(item)
      );
      
      await childCtx.wait({ seconds: 1 });
      
      const processed = await childCtx.step('process', async () => 
        process(validated)
      );
      
      return processed;
    });
  },
  { maxConcurrency: 5 }
);
```

## Performance Optimization

### Batch Size Selection

```typescript
// Small items: Higher concurrency
const results = await context.map(
  'small-items',
  smallItems,
  processFunc,
  { maxConcurrency: 20 }
);

// Large items: Lower concurrency
const results = await context.map(
  'large-items',
  largeItems,
  processFunc,
  { maxConcurrency: 3 }
);
```

### Early Termination

Use completion policies to stop early:

```typescript
const results = await context.map(
  'find-match',
  candidates,
  async (ctx, candidate) => {
    return await ctx.step(async () => checkMatch(candidate));
  },
  {
    completionConfig: {
      minSuccessful: 1  // Stop after first success
    }
  }
);
```

## Best Practices

1. **Set appropriate maxConcurrency** based on downstream system capacity
2. **Use completion policies** to handle partial failures gracefully
3. **Name all operations** for debugging
4. **Handle batch results explicitly** - check for failures
5. **Consider retry strategies** for failed items
6. **Monitor concurrency limits** to avoid overwhelming systems
7. **Use child contexts** for complex per-item workflows
8. **Implement circuit breakers** for external service calls
