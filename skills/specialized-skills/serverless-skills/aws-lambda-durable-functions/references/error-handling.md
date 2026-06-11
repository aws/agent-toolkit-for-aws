# Error Handling and Retry Strategies

Comprehensive error handling patterns for durable functions.

**TypeScript:**

```typescript
import { createRetryStrategy, JitterStrategy } from '@aws/durable-execution-sdk-js';

// Exponential backoff with jitter
const result = await context.step(
  'api-call',
  async () => callAPI(),
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

// Fixed delay
const result = await context.step(
  'simple-retry',
  async () => operation(),
  {
    retryStrategy: createRetryStrategy({
      maxAttempts: 3,
      delay: { seconds: 5 },
      backoffRate: 1
    })
  }
);
```

**Python:**

```python
from aws_durable_execution_sdk_python.retries import RetryStrategyConfig, create_retry_strategy, JitterStrategy

retry_config = RetryStrategyConfig(
    max_attempts=5,
    initial_delay=Duration.from_seconds(1),
    max_delay=Duration.from_seconds(60),
    backoff_rate=2.0,
    jitter_strategy=JitterStrategy.FULL
)

result = context.step(
    func=api_call(),
    config=StepConfig(retry_strategy=create_retry_strategy(retry_config))
)
```

## Custom Retry Logic

**TypeScript:**

```typescript
const result = await context.step(
  'custom-retry',
  async () => riskyOperation(),
  {
    retryStrategy: (error, attemptCount) => {
      // Don't retry client errors
      if (error.statusCode >= 400 && error.statusCode < 500) {
        return { shouldRetry: false };
      }
      
      // Retry server errors with exponential backoff
      if (attemptCount < 5) {
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
def custom_retry(error: Exception, attempt: int) -> RetryDecision:
    if hasattr(error, 'status_code') and 400 <= error.status_code < 500:
        return RetryDecision.no_retry()
    
    if attempt < 5:
        return RetryDecision(
            should_retry=True,
            delay=Duration.from_seconds(2 ** attempt)
        )
    
    return RetryDecision.no_retry()
```

## Error Classification

### Retryable vs Non-Retryable

**TypeScript:**

```typescript
class ValidationError extends Error {
  name = 'ValidationError';
}

class NetworkError extends Error {
  name = 'NetworkError';
}

const result = await context.step(
  'selective-retry',
  async () => operation(),
  {
    retryStrategy: createRetryStrategy({
      maxAttempts: 3,
      retryableErrorTypes: [NetworkError],
      // ValidationError won't be retried
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

## Saga Pattern

Implement compensating transactions for distributed workflows:

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const compensations: Array<{
    name: string;
    fn: () => Promise<void>;
  }> = [];

  try {
    // Step 1: Reserve inventory
    const reservation = await context.step('reserve-inventory', async () =>
      inventoryService.reserve(event.items)
    );
    compensations.push({
      name: 'cancel-reservation',
      fn: () => inventoryService.cancelReservation(reservation.id)
    });

    // Step 2: Charge payment
    const payment = await context.step('charge-payment', async () =>
      paymentService.charge(event.paymentMethod, event.amount)
    );
    compensations.push({
      name: 'refund-payment',
      fn: () => paymentService.refund(payment.id)
    });

    // Step 3: Create shipment
    const shipment = await context.step('create-shipment', async () =>
      shippingService.createShipment(event.address, event.items)
    );
    compensations.push({
      name: 'cancel-shipment',
      fn: () => shippingService.cancelShipment(shipment.id)
    });

    return { success: true, orderId: shipment.orderId };

  } catch (error) {
    context.logger.error('Order failed, executing compensations', error);
    
    // Execute compensations in reverse order
    for (const comp of compensations.reverse()) {
      try {
        await context.step(comp.name, async () => comp.fn());
      } catch (compError) {
        context.logger.error(`Compensation ${comp.name} failed`, compError);
        // Continue with other compensations
      }
    }
    
    throw error;
  }
});
```

**Python:**

```python
# Note: All service methods are decorated with @durable_step
@durable_execution
def handler(event: dict, context: DurableContext) -> dict:
    compensations = []

    try:
        # Step 1: Reserve inventory
        reservation = context.step(reserve_inventory(event['items']))
        compensations.append(('cancel-reservation', cancel_reservation, reservation['id']))

        # Step 2: Charge payment
        payment = context.step(charge_payment(event['payment_method'], event['amount']))
        compensations.append(('refund-payment', refund_payment, payment['id']))

        # Step 3: Create shipment
        shipment = context.step(create_shipment(event['address'], event['items']))

        return {'success': True, 'order_id': shipment['order_id']}

    except Exception as error:
        context.logger.error(f'Order failed, executing compensations: {error}')
        
        for name, comp_step, resource_id in reversed(compensations):
            try:
                context.step(comp_step(resource_id))
            except Exception as comp_error:
                context.logger.error(f'Compensation {name} failed: {comp_error}')
        
        raise error
```

## Unrecoverable Errors

Mark errors as unrecoverable to stop execution immediately:

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const user = await context.step(
    'fetch-user',
    async () => {
      const user = await fetchUser(event.userId);
      
      if (!user) {
        throw new Error('User not found');
      }
      
      return user;
    },
    { retryStrategy: () => ({ shouldRetry: false }) }
  );
  
  // Continue processing...
});
```

**Python:**

```python
from aws_durable_execution_sdk_python.exceptions import ExecutionError

@durable_execution
def handler(event: dict, context: DurableContext) -> dict:
    @durable_step
    def fetch_user_step(step_ctx: StepContext):
        user = fetch_user(event['user_id'])
        if not user:
            # Stop execution immediately — permanent failure, no retry
            raise ExecutionError('User not found')
        return user
    
    user = context.step(fetch_user_step())
    # Continue processing...
```

The SDK provides these exception types for different failure scenarios:

| Exception | Retryable | Use case |
|-----------|-----------|----------|
| `ExecutionError` | No | Permanent business logic failures (returns FAILED status) |
| `InvocationError` | Yes (by Lambda) | Transient infrastructure issues (Lambda retries invocation) |
| `CallbackError` | No | Callback handling failures |
| `DurableExecutionsError` | — | Base class for all SDK exceptions |

## Error Determinism

Ensure errors are deterministic across replays:

**TypeScript:**

```typescript
class CustomBusinessError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly details: any
  ) {
    super(message);
    this.name = 'CustomBusinessError';
  }
}

const result = await context.step('validate', async () => {
  if (!isValid(data)) {
    // ✅ Deterministic error
    throw new CustomBusinessError(
      'Validation failed',
      'INVALID_DATA',
      { field: 'email', reason: 'invalid format' }
    );
  }
  
  return processData(data);
});
```

## Circuit Breaker Pattern

**TypeScript:**

```typescript
class CircuitBreaker {
  private failures = 0;
  private lastFailureTime = 0;
  private readonly threshold = 5;
  private readonly timeout = 60000; // 1 minute

  async execute<T>(fn: () => Promise<T>): Promise<T> {
    if (this.isOpen()) {
      throw new Error('Circuit breaker is open');
    }

    try {
      const result = await fn();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  private isOpen(): boolean {
    if (this.failures >= this.threshold) {
      const elapsed = Date.now() - this.lastFailureTime;
      return elapsed < this.timeout;
    }
    return false;
  }

  private onSuccess() {
    this.failures = 0;
  }

  private onFailure() {
    this.failures++;
    this.lastFailureTime = Date.now();
  }
}

// Use in handler
const breaker = new CircuitBreaker();

export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const result = await context.step('api-call', async () => {
    return await breaker.execute(() => callExternalAPI());
  });
  
  return result;
});
```

## Partial Failure Handling

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const results = await context.map(
    'process-items',
    event.items,
    async (ctx, item, index) => {
      return await ctx.step(async () => processItem(item));
    },
    {
      completionConfig: {
        toleratedFailurePercentage: 10  // Allow 10% failures
      }
    }
  );

  if (results.hasFailure) {
    // Log failures but continue
    context.logger.warn('Some items failed', {
      failureCount: results.failureCount,
      failures: results.failed().map(f => ({
        index: f.index,
        error: f.error?.message
      }))
    });

    // Store failed items for later retry
    await context.step('store-failures', async () => {
      const failedItems = results.failed().map(f => event.items[f.index]);
      return await storeFailedItems(failedItems);
    });
  }

  return {
    totalProcessed: results.successCount,
    failed: results.failureCount
  };
});
```

## Best Practices

1. **Use appropriate retry strategies** - exponential backoff for most cases
2. **Classify errors correctly** - distinguish retryable from non-retryable
3. **Implement compensating transactions** for distributed workflows
4. **Make errors deterministic** - same input produces same error
5. **Use unrecoverable errors** to stop execution early when appropriate
6. **Log errors with context** using `context.logger`
7. **Handle partial failures** gracefully in batch operations
8. **Implement circuit breakers** for external service calls
9. **Test error scenarios** thoroughly with test runners
10. **Monitor error rates** and adjust retry strategies accordingly
