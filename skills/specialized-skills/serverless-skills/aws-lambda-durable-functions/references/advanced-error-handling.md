# Advanced Error Handling

Advanced error handling patterns for durable functions, including timeout handling, circuit breakers, and conditional retry strategies.

## Timeout Handling with Callbacks

**Pattern:** Wait for an external callback with a timeout, and implement fallback logic if the timeout is reached.

**Implementation approach:**

1. Use `waitForCallback` (TypeScript) or `wait_for_callback` (Python) with a timeout configuration set in the config argument
2. Wrap in try-catch to handle timeout errors
3. Check if the error is a timeout
4. Implement fallback logic in a step (e.g., escalate to manager, use default value, retry with different parameters)
5. Return appropriate status indicating timeout occurred

**Key considerations:**

- Timeout errors are thrown when the callback doesn't complete within the specified duration
- Fallback logic should be in a step to ensure it's checkpointed
- Log timeout events for monitoring and debugging

## Local Timeout with Promise.race in Typescript SDK

**Pattern:** Implement a timeout for a step operation within a single Lambda invocation.

**Implementation approach:**

1. Use `Promise.race()` to race the step operation against a timeout promise
2. The timeout promise rejects after the specified duration
3. Catch the timeout error and implement fallback logic
4. Execute fallback operation in a separate step

**Important limitation:**
In TypeScript, native setTimeout (and patterns like Promise.race using it) will fail during execution replays. To create a reliable timeout that persists across execution (expands over multi invocations), always use the timeout parameter provided by waitForCallback

## Conditional Retry Based on Error Type

**Pattern:** Retry operations selectively based on the type of error encountered.

**Implementation approach:**

1. Define a custom retry strategy function that examines the error
2. For client errors (4xx): Don't retry - these are permanent failures
3. For server errors (5xx): Retry with exponential backoff
4. For network errors: Retry with fixed delay
5. For unknown errors: Don't retry by default

**Key considerations:**

- Client errors (400-499) typically indicate bad input and shouldn't be retried
- Server errors (500-599) are often transient and benefit from retry
- Network errors (connection refused, timeout) should retry with reasonable limits
- Use exponential backoff for server errors to avoid overwhelming the service
- Set maximum retry attempts to prevent infinite loops

## Circuit Breaker Pattern

**Pattern:** Temporarily stop making requests to a failing external service to prevent cascading failures.

**Implementation approach:**

1. Track failure count and last failure time (note: these reset on replay due to closure mutations)
2. Check if circuit is "open" (too many recent failures)
3. If open, throw a circuit breaker error and wait before retrying
4. If closed, attempt the operation
5. On success, reset failure count
6. On failure, increment failure count and record timestamp
7. Configure retry strategy to wait longer when circuit is open

**Important caveat:** The example implementations use closure variables (`failureCount`, `lastFailureTime`) which reset on replay. For production use, store circuit breaker state in:

- A step return value that persists across replays
- An external store like DynamoDB
- A durable variable pattern

**Key considerations:**

- Circuit breaker prevents cascading failures to downstream services
- The "open" duration should be long enough for the service to recover
- Reset the circuit on successful operations
- Log circuit state changes for monitoring

## Error Handling Best Practices

1. **Timeout Handling**: Always implement fallback logic for callback timeouts - don't let executions fail silently
2. **Conditional Retries**: Classify errors as transient vs permanent, only retry transient errors
3. **Circuit Breakers**: Protect against cascading failures to external services, especially for high-volume operations
4. **Structured Logging**: Log error context (error type, attempt count, operation name) for debugging
5. **Graceful Degradation**: Return partial results when possible rather than failing completely
6. **Error Classification**: Distinguish between client errors (don't retry), server errors (retry with backoff), and network errors (retry with fixed delay)

## Common Error Patterns

### Transient Errors (Should Retry)

- Network timeouts
- Service unavailable (503)
- Rate limiting (429)
- Database connection failures
- Temporary infrastructure issues

### Permanent Errors (Should Not Retry)

- Invalid input (400)
- Authentication failures (401, 403)
- Resource not found (404)
- Business logic violations
- Validation errors

### Timeout Errors (Need Fallback)

- Callback timeouts - external system didn't respond in time
- External system delays - service is slow or unresponsive
- Long-running operations - operation exceeded expected duration
