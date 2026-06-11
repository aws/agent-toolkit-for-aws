# Step Operations

Steps are atomic operations with automatic retry and state persistence.

## Basic Step Patterns

### Python: Two Ways to Define Steps

**Recommended: `@durable_step` Decorator**

```python
from aws_durable_execution_sdk_python import durable_step, StepContext

@durable_step
def fetch_user(step_ctx: StepContext, user_id: str):
    """Fetch user from database - reusable step function."""
    return fetch_user_from_api(user_id)

# Call it - name is automatically inferred from function name
result = context.step(fetch_user(user_id))
```

Alternative: **Inline Lambda**

```python
# For simple one-off operations
result = context.step(
    func=lambda step_ctx: fetch_user_from_api(user_id),
    name='fetch-user'
)
```

**Use `@durable_step` for:**

- Reusable step functions
- Complex logic
- Better readability and testing

**Use lambda for:**

- Simple inline operations
- One-off transformations

### TypeScript: Named Steps

**TypeScript:**

```typescript
const result = await context.step('fetch-user', async () => {
  return await fetchUserFromAPI(userId);
});
```

**Best Practice:** Always name steps for easier debugging and testing.

## Retry Configuration

### Exponential Backoff

**TypeScript:**

```typescript
import { createRetryStrategy, JitterStrategy } from '@aws/durable-execution-sdk-js';

const result = await context.step(
  'api-call',
  async () => callExternalAPI(),
  {
    retryStrategy: createRetryStrategy({
      maxAttempts: 5,
      initialDelay: { seconds: 1 },
      maxDelay: { seconds: 60 },
      backoffRate: 2.0,
      jitter: JitterStrategy.FULL
    })
  }
);
```

**Python:**

```python
# Note: api_call is decorated with @durable_step
from aws_durable_execution_sdk_python.config import StepConfig, Duration
from aws_durable_execution_sdk_python.retries import RetryStrategyConfig, create_retry_strategy, JitterStrategy

retry_config = RetryStrategyConfig(
    max_attempts=5,
    initial_delay=Duration.from_seconds(5),
    max_delay=Duration.from_seconds(60),
    backoff_rate=2.0,
    jitter_strategy=JitterStrategy.FULL
)

result = context.step(
    func=api_call(),
    config=StepConfig(retry_strategy=create_retry_strategy(retry_config))
)
```

### Custom Retry Strategy

**TypeScript:**

```typescript
const result = await context.step(
  'custom-retry',
  async () => riskyOperation(),
  {
    retryStrategy: (error, attemptCount) => {
      // Don't retry validation errors
      if (error.name === 'ValidationError') {
        return { shouldRetry: false };
      }
      
      // Retry up to 3 times with exponential backoff
      if (attemptCount < 3) {
        return {
          shouldRetry: true,
          delay: { seconds: Math.pow(2, attemptCount) }
        };
      }
      
      return { shouldRetry: false };
    }
  }
);
```

**Python:**

```python
from aws_durable_execution_sdk_python.retries import RetryDecision

def custom_retry(error: Exception, attempt: int) -> RetryDecision:
    if isinstance(error, ValidationError):
        return RetryDecision.no_retry()
    
    if attempt < 3:
        return RetryDecision(
            should_retry=True,
            delay=Duration.from_seconds(2 ** attempt)
        )
    
    return RetryDecision.no_retry()

result = context.step(
    risky_operation(),
    config=StepConfig(retry_strategy=custom_retry)
)
```

### Retryable Error Types

**TypeScript:**

```typescript
class NetworkError extends Error {
  name = 'NetworkError';
}

class TimeoutError extends Error {
  name = 'TimeoutError';
}

const result = await context.step(
  'selective-retry',
  async () => operation(),
  {
    retryStrategy: createRetryStrategy({
      maxAttempts: 3,
      retryableErrorTypes: [NetworkError, TimeoutError]
    })
  }
);
```

**Python:**

```python
retry_config = RetryStrategyConfig(
    max_attempts=3,
    retryable_error_types=[NetworkError, TimeoutError]
)
```

## Step Semantics

### AtLeastOncePerRetry (default)

Step executes at least once on each retry attempt. If the step succeeds but the checkpoint fails (e.g. due to a sandbox crash), the step will re-execute on replay. Use for idempotent operations that can tolerate duplicate execution.

**TypeScript:**

```typescript
import { StepSemantics } from '@aws/durable-execution-sdk-js';

const result = await context.step(
  'idempotent-operation',
  async () => idempotentAPI(),
  { semantics: StepSemantics.AtLeastOncePerRetry }
);
```

### AtMostOncePerRetry

Step executes at most once per retry attempt. If a crash happens between the pre-step checkpoint and step completion, the step is skipped on replay rather than re-executed. The step can still run across multiple retry attempts. To guarantee at-most-once overall, pair with `retryStrategy: () => ({ shouldRetry: false })`.

**TypeScript:**

```typescript
import { StepSemantics } from '@aws/durable-execution-sdk-js';

const result = await context.step(
  'charge-payment',
  async () => chargeCard(amount),
  {
    semantics: StepSemantics.AtMostOncePerRetry,
    retryStrategy: () => ({ shouldRetry: false })
  }
);
```

**Python:**

```python
from aws_durable_execution_sdk_python.config import StepSemantics, StepConfig

result = context.step(
    charge_card(amount),
    config=StepConfig(
        step_semantics=StepSemantics.AT_MOST_ONCE_PER_RETRY,
        retry_strategy=lambda error, attempt: RetryDecision.no_retry()
    )
)
```

## Custom Serialization

For complex types, provide custom serialization:

**TypeScript:**

```typescript
import { createClassSerdesWithDates } from '@aws/durable-execution-sdk-js';

class User {
  id: string = '';
  name: string = '';
  createdAt: Date = new Date();
}

const userSerdes = createClassSerdesWithDates(User, ['createdAt']);

const user = await context.step(
  'fetch-user',
  async () => {
    const user = new User();
    user.id = '123';
    user.name = 'Alice';
    user.createdAt = new Date();
    return user;
  },
  { serdes: userSerdes }
);
```

**Python:**

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class User:
    id: str
    name: str
    created_at: datetime

# Python SDK handles dataclass serialization automatically
user = context.step(
    lambda _: User('123', 'Alice', datetime.now()),
    name='fetch-user'
)
```

## When to Use Steps vs Child Contexts

### Use Steps For:

- Single atomic operations
- API calls
- Database queries
- Data transformations
- Operations that should retry as a unit

### Use Child Contexts For:

- Grouping multiple durable operations
- Complex workflows with steps, waits, and invokes
- Isolating state tracking
- Organizing related operations

**Example:**

```typescript
// ❌ WRONG: Cannot nest durable operations in step
await context.step('process', async () => {
  await context.wait({ seconds: 1 });  // ERROR!
});

// ✅ CORRECT: Use child context
await context.runInChildContext('process', async (childCtx) => {
  const data = await childCtx.step('fetch', async () => fetch());
  await childCtx.wait({ seconds: 1 });
  return await childCtx.step('save', async () => save(data));
});
```

## Error Handling

Steps throw errors after all retry attempts are exhausted:

**TypeScript:**

```typescript
try {
  const result = await context.step('risky', async () => riskyOperation());
} catch (error) {
  if (error instanceof StepError) {
    context.logger.error('Step failed', error.cause);
    // Handle or rethrow
  }
}
```

**Python:**

```python
try:
    # Note: risky_operation is decorated with @durable_step
    result = context.step(risky_operation())
except Exception as error:
    context.logger.error('Step failed: %s', str(error))
    # Handle or rethrow
```

For SDK-specific exceptions, use the base class or specific types:

```python
from aws_durable_execution_sdk_python import DurableExecutionsError

try:
    result = context.step(risky_operation())
except DurableExecutionsError as error:
    context.logger.error('SDK error: %s', str(error))
except Exception as error:
    context.logger.error('Application error: %s', str(error))
```

## Best Practices

1. **Always name steps** for debugging and testing
2. **Keep steps atomic** - one logical operation per step
3. **Make steps idempotent** when possible
4. **Use appropriate retry strategies** based on operation type
5. **Handle errors explicitly** - don't let them propagate unexpectedly
6. **Use custom serialization** for complex types
7. **Choose correct semantics** (`AtLeastOncePerRetry` vs `AtMostOncePerRetry`)
