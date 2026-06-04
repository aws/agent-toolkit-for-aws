# Advanced Patterns

Advanced techniques and patterns for sophisticated durable function workflows.

## Advanced GenAI Agent Patterns

### Agent with Reasoning and Dynamic Step Naming

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  context.logger.info('Starting AI agent', { prompt: event.prompt });
  const messages = [{ role: 'user', content: event.prompt }];

  while (true) {
    // Invoke AI model with reasoning
    const { response, reasoning, tool } = await context.step(
      'invoke-model',
      async (stepCtx) => {
        stepCtx.logger.info('Invoking AI model', {
          messageCount: messages.length
        });
        return await invokeAIModel(messages);
      }
    );

    // Log AI's reasoning
    if (reasoning) {
      context.logger.debug('AI reasoning', { reasoning });
    }

    // If no tool needed, return response
    if (tool == null) {
      context.logger.info('AI agent completed - no tool needed');
      return response;
    }

    // Execute tool with dynamic step naming
    const toolResult = await context.step(
      `execute-tool-${tool.name}`,  // Dynamic step name
      async (stepCtx) => {
        stepCtx.logger.info('Executing tool', {
          toolName: tool.name,
          toolParams: tool.parameters
        });
        return await executeTool(tool, response);
      }
    );

    // Add result to conversation
    messages.push({
      role: 'assistant',
      content: toolResult,
    });

    context.logger.debug('Tool result added', {
      toolName: tool.name,
      resultLength: toolResult.length
    });
  }
});
```

**Python:**

```python
# Note: invoke_ai_model and execute_tool are decorated with @durable_step
@durable_execution
def handler(event: dict, context: DurableContext) -> str:
    context.logger.info('Starting AI agent', extra={'prompt': event['prompt']})
    messages = [{'role': 'user', 'content': event['prompt']}]

    while True:
        # Invoke AI model
        result = context.step(invoke_ai_model(messages))

        response = result['response']
        reasoning = result.get('reasoning')
        tool = result.get('tool')

        if reasoning:
            context.logger.debug('AI reasoning', extra={'reasoning': reasoning})

        if tool is None:
            context.logger.info('AI agent completed')
            return response

        # Execute tool with dynamic step naming
        tool_result = context.step(
            func=execute_tool(tool, response),
            name=f"execute-tool-{tool['name']}"
        )

        messages.append({'role': 'assistant', 'content': tool_result})
        context.logger.debug('Tool result added', extra={'tool': tool['name']})
```

## Step Semantics Deep Dive

### AtMostOncePerRetry vs AtLeastOncePerRetry

**TypeScript:**

```typescript
import { StepSemantics } from '@aws/durable-execution-sdk-js';

// AtLeastOncePerRetry (DEFAULT) - For operations that can execute multiple times
// Step may execute multiple times per retry attempt
// Use when idempotency is handled externally
await context.step(
  'update-database',
  async () => {
    // This is idempotent - safe to retry
    return await updateUserRecord(userId, data);
  },
  { semantics: StepSemantics.AtLeastOncePerRetry }
);

// AtMostOncePerRetry - For non-idempotent operations
// Step executes at most once per retry attempt
// If step fails partway through, it won't re-execute the same attempt
await context.step(
  'charge-payment',
  async () => {
    // Non-idempotent - duplicates would double-charge the customer
    return await chargePayment(customerId, amount);
  },
  {
    semantics: StepSemantics.AtMostOncePerRetry,
    // Pair with shouldRetry: false to guarantee at-most-once overall,
    // since the default retry strategy still allows multiple retry attempts.
    retryStrategy: () => ({ shouldRetry: false }),
  }
);
```

**When to use each:**

| Semantic                | Use When                      | Example Operations                                |
| ----------------------- | ----------------------------- | ------------------------------------------------- |
| **AtLeastOncePerRetry** (default) | Operation is idempotent, or external dedup exists | Database upserts, idempotency-keyed API calls, queuing systems |
| **AtMostOncePerRetry**            | Operation is non-idempotent, duplicates must be avoided | Charge payment, send unique notification, non-idempotent external writes |

## Completion Policies - Interaction and Combination

### Combining Multiple Constraints

Completion policies can be combined, and execution **stops when the first constraint is met**:

**TypeScript:**

```typescript
const results = await context.map(
  'process-items',
  items,
  processFunc,
  {
    completionConfig: {
      minSuccessful: 8,              // Need at least 8 successes
      toleratedFailureCount: 2,       // OR can tolerate 2 failures
      toleratedFailurePercentage: 20, // OR can tolerate 20% failures
    }
  }
);

// Execution stops when ANY of these conditions is met:
// 1. 8 successful items (minSuccessful reached)
// 2. 2 failures occur (toleratedFailureCount reached)
// 3. 20% of items fail (toleratedFailurePercentage reached)
```

### Understanding Stop Conditions

**Example with 10 items:**

```typescript
const items = Array.from({ length: 10 }, (_, i) => i);

const results = await context.map(
  'process',
  items,
  processFunc,
  {
    maxConcurrency: 3,
    completionConfig: {
      minSuccessful: 7,
      toleratedFailureCount: 3
    }
  }
);

// Scenario 1: 7 successes, 0 failures
// ✅ Stops after 7th success (minSuccessful reached)
// Remaining 3 items are not processed

// Scenario 2: 5 successes, 3 failures
// ❌ Stops after 3rd failure (toleratedFailureCount reached)
// Remaining 2 items are not processed
// results.throwIfError() will throw because minSuccessful not met

// Scenario 3: 7 successes, 2 failures
// ✅ Stops after 7th success (minSuccessful reached)
// 1 item not processed, but completion policy satisfied
```

### Early Termination Pattern

Use completion policies for early termination when searching:

**TypeScript:**

```typescript
// Stop after finding first match
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

// Only one item processed (assuming first succeeds)
if (results.successCount > 0) {
  const match = results.succeeded()[0];
  context.logger.info('Found match', { match });
}
```

## Advanced Error Handling

For timeout handling (waitForCallback, Promise.race), conditional retries, and circuit breaker patterns, see [advanced-error-handling.md](advanced-error-handling.md).

## Advanced and Retry Strategies

For conditional retry strategies and circuit breaker patterns, see [advanced-error-handling.md](advanced-error-handling.md).

## Custom Serialization Patterns

### Class with Date Fields

**TypeScript:**

```typescript
import {
  createClassSerdesWithDates
} from '@aws/durable-execution-sdk-js';

class User {
  name: string = '';
  email: string = '';
  createdAt: Date = new Date();
  updatedAt: Date = new Date();
}

const result = await context.step(
  'create-user',
  async () => {
    const user = new User();
    user.name = 'Alice';
    user.email = 'alice@example.com';
    user.createdAt = new Date();
    user.updatedAt = new Date();
    return user;
  },
  {
    serdes: createClassSerdesWithDates(User, ['createdAt', 'updatedAt'])
  }
);

// result is properly deserialized User instance with Date objects
console.log(result.createdAt instanceof Date); // true
```

### Complex Object Graphs

**TypeScript:**

```typescript
import { createClassSerdes } from '@aws/durable-execution-sdk-js';

class Order {
  id: string = '';
  items: OrderItem[] = [];
  customer: Customer = new Customer();
}

class OrderItem {
  sku: string = '';
  quantity: number = 0;
}

class Customer {
  id: string = '';
  name: string = '';
}

// Create serdes for each class
const orderSerdes = createClassSerdes(Order);
const itemSerdes = createClassSerdes(OrderItem);
const customerSerdes = createClassSerdes(Customer);

const result = await context.step(
  'process-order',
  async () => {
    const customer = new Customer();
    customer.id = 'CUST-123';
    customer.name = 'Alice';

    const item1 = new OrderItem();
    item1.sku = 'SKU-001';
    item1.quantity = 2;

    const item2 = new OrderItem();
    item2.sku = 'SKU-002';
    item2.quantity = 1;

    const order = new Order();
    order.id = 'ORD-456';
    order.items = [item1, item2];
    order.customer = customer;
    return order;
  },
  { serdes: orderSerdes }
);
```

## Nested Workflows

### Parent-Child Workflow Pattern

**TypeScript:**

```typescript
// Parent orchestrator
export const orchestrator = withDurableExecution(
  async (event, context: DurableContext) => {
    const childFunctionArn = process.env.CHILD_FUNCTION_ARN!;

    // Invoke child workflows in parallel
    const results = await context.parallel(
      'process-batches',
      [
        {
          name: 'batch-1',
          func: async (ctx) => ctx.invoke(
            'process-batch-1',
            childFunctionArn,
            { batch: event.batches[0] }
          )
        },
        {
          name: 'batch-2',
          func: async (ctx) => ctx.invoke(
            'process-batch-2',
            childFunctionArn,
            { batch: event.batches[1] }
          )
        }
      ]
    );

    return results.getResults();
  }
);

// Child worker
export const worker = withDurableExecution(
  async (event, context: DurableContext) => {
    const items = event.batch.items;

    const results = await context.map(
      'process-items',
      items,
      async (ctx, item) => {
        return await ctx.step(async () => processItem(item));
      }
    );

    return results.getResults();
  }
);
```

## Best Practices Summary

1. **Dynamic Step Naming**: Use template literals for dynamic operation names
2. **Structured Logging**: Log reasoning and context with each operation
3. **Error Handling**: See [advanced-error-handling.md](advanced-error-handling.md) for timeout, retry, and circuit breaker patterns
4. **Completion Policies**: Understand how combined constraints interact
5. **Custom Serialization**: Use proper serdes for complex objects
6. **Nested Workflows**: Use invoke for modular, composable architectures
