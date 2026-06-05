# Testing Patterns

Test durable functions locally and in the cloud with comprehensive test runners.

## Critical Testing Patterns

**ALWAYS follow these patterns to avoid flaky tests:**

### DO:

- ✅ Name all operations for test reliability
- ✅ TypeScript: Use `runner.getOperation("name")` to find operations by name
- ✅ TypeScript: Use `WaitingOperationStatus.STARTED` when waiting for callback operations
- ✅ TypeScript: JSON.stringify callback parameters: `sendCallbackSuccess(JSON.stringify(data))`
- ✅ TypeScript: Use `skipTime: true` in setupTestEnvironment for fast tests
- ✅ TypeScript: Wrap event data in `payload` object: `runner.run({ payload: { ... } })`
- ✅ TypeScript: Cast `getResult()` to appropriate type: `execution.getResult() as ResultType`
- ✅ Python: Use `result.get_step("name")` to find step operations by name
- ✅ Python: Use `result.operations` to iterate and filter operations by type
- ✅ Python: Instantiate `DurableFunctionTestRunner(handler=my_handler)` directly
- ✅ Python: Use `runner.run(input={...}, timeout=10)` — note `input=` not `payload`
- ✅ Python: The value of result.result is serialized. Deserialize using the appropriate SerDes or default json deserializer.

### DON'T:

- ❌ Use `getOperationByIndex()` unless absolutely necessary
- ❌ Assume operation indices are stable (parallel creates nested operations)
- ❌ TypeScript: Send objects to sendCallbackSuccess — stringify first
- ❌ TypeScript: Forget that callback results are JSON strings — parse them
- ❌ TypeScript: Test callbacks without proper synchronization (leads to race conditions)
- ❌ Python: Confuse `DurableFunctionTestRunner` (local) with `DurableFunctionCloudTestRunner` (cloud)
- ❌ Python: Forget the `with runner:` context manager — it manages execution lifecycle

## Local Testing Setup

**TypeScript:**

```typescript
import {
  LocalDurableTestRunner,
  OperationType,
  OperationStatus
} from '@aws/durable-execution-sdk-js-testing';

describe('My Durable Function', () => {
  beforeAll(() => 
    LocalDurableTestRunner.setupTestEnvironment({ skipTime: true })
  );
  
  afterAll(() => 
    LocalDurableTestRunner.teardownTestEnvironment()
  );

  it('should execute workflow', async () => {
    const runner = new LocalDurableTestRunner({ 
      handlerFunction: handler 
    });
    
    const execution = await runner.run({ 
      payload: { userId: '123' } 
    });

    expect(execution.getStatus()).toBe('SUCCEEDED');
    expect(execution.getResult()).toEqual({ success: true });
  });
});
```

**Python:**

The Python testing SDK provides `DurableFunctionTestRunner` for local testing and `DurableFunctionCloudTestRunner` for cloud testing.

Install the testing SDK:

```bash
pip install aws-durable-execution-sdk-python-testing pytest
```

Example test:

```python
from aws_durable_execution_sdk_python_testing import DurableFunctionTestRunner
from aws_durable_execution_sdk_python.execution import InvocationStatus
from src.my_function import handler

def test_workflow():
    """Test durable function locally."""
    runner = DurableFunctionTestRunner(handler=handler)
    
    with runner:
        result = runner.run(input='{"user_id": "123"}', timeout=10)

    assert result.status is InvocationStatus.SUCCEEDED
```

## Getting Operations

**CRITICAL: Always get operations by NAME, not by index.**

**TypeScript:**

```typescript
it('should execute steps in order', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });
  await runner.run({ payload: { test: true } });

  // ✅ CORRECT: Get by name
  const fetchStep = runner.getOperation('fetch-user');
  expect(fetchStep.getType()).toBe(OperationType.STEP);
  expect(fetchStep.getStatus()).toBe(OperationStatus.SUCCEEDED);

  const processStep = runner.getOperation('process-data');
  expect(processStep.getStatus()).toBe(OperationStatus.SUCCEEDED);

  // ❌ WRONG: Get by index (brittle, breaks easily)
  // const step1 = runner.getOperationByIndex(0);
});
```

**Python:**

```python
from aws_durable_execution_sdk_python.lambda_service import OperationType
def test_steps_execute():
    """Test step execution."""
    runner = DurableFunctionTestRunner(handler=handler)
    
    with runner:
        result = runner.run(input={'test': True}, timeout=10)

    # ✅ CORRECT: Get step by name
    fetch_step = result.get_step('fetch-user')
    assert fetch_step is not None

    # ✅ Also valid: filter result.operations by type
    step_names = {op.name for op in result.operations if op.operation_type == OperationType.STEP}
    assert step_names >= {'fetch-user', 'process-data'}
    assert 'process-data' in step_names
```

## Testing Replay Behavior

**TypeScript:**

```typescript
it('should handle replay correctly', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });
  
  // First execution
  const execution1 = await runner.run({ payload: { value: 42 } });
  expect(execution1.getStatus()).toBe('SUCCEEDED');

  // Simulate replay
  const execution2 = await runner.run({ payload: { value: 42 } });
  expect(execution2.getStatus()).toBe('SUCCEEDED');
  
  // Results should be identical
  expect(execution1.getResult()).toEqual(execution2.getResult());
});
```

## Testing with Fake Clock

**TypeScript:**

```typescript
it('should wait for specified duration', async () => {
  const runner = new LocalDurableTestRunner({ 
    handlerFunction: handler 
  });

  const executionPromise = runner.run({ payload: {} });

  // Advance time by 60 seconds
  await runner.skipTime({ seconds: 60 });

  const execution = await executionPromise;
  expect(execution.getStatus()).toBe('SUCCEEDED');

  const waitOp = runner.getOperation('delay');
  expect(waitOp.getType()).toBe(OperationType.WAIT);
  expect(waitOp.getWaitDetails()?.waitSeconds).toBe(60);
});
```

## Test Runner API Patterns

**CRITICAL:** Always wrap event data in `payload` and cast results appropriately.

**TypeScript:**

```typescript
it('should use correct test runner API', async () => {
  const runner = new LocalDurableTestRunner({
    handlerFunction: handler,
  });

  // ✅ CORRECT: Wrap event in payload
  const execution = await runner.run({
    payload: { name: 'Alice', userId: '123' }
  });

  // ✅ CORRECT: Type cast result
  const result = execution.getResult() as {
    greeting: string;
    message: string;
  };

  expect(result.greeting).toBe('Hello, Alice!');

  // ✅ CORRECT: Get operations by name
  const greetingStep = runner.getOperation('generate-greeting');
  expect(greetingStep.getStepDetails()?.result).toBe('Hello, Alice!');
});

// ❌ WRONG: Missing payload wrapper and type casting
it('incorrect api usage', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });

  // ❌ Missing payload wrapper
  const execution = await runner.run({ name: 'Alice' });

  // ❌ No type casting - result is 'unknown'
  const result = execution.getResult();
  // expect(result.greeting).toBe('...'); // Type error!
});
```

## Testing Callbacks

**CRITICAL:** Use `waitForData()` with `WaitingOperationStatus.STARTED` to avoid flaky tests caused by promise races.

**TypeScript:**

```typescript
import { WaitingOperationStatus } from '@aws/durable-execution-sdk-js-testing';

it('should handle callback success', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });

  // Start execution (will pause at callback)
  const executionPromise = runner.run({
    payload: { approver: 'alice@example.com' }
  });

  // ✅ CRITICAL: Get operation by NAME
  const callbackOp = runner.getOperation('wait-for-approval');

  // ✅ CRITICAL: Wait for operation to reach STARTED status
  await callbackOp.waitForData(WaitingOperationStatus.STARTED);

  // ✅ CRITICAL: Must JSON.stringify callback data!
  await callbackOp.sendCallbackSuccess(
    JSON.stringify({ approved: true, comments: 'Looks good' })
  );

  const execution = await executionPromise;
  expect(execution.getStatus()).toBe('SUCCEEDED');

  // ✅ CRITICAL: Parse JSON string result
  const result: any = execution.getResult();
  const approval = typeof result.approval === 'string'
    ? JSON.parse(result.approval)
    : result.approval;

  expect(approval.approved).toBe(true);
  expect(approval.comments).toBe('Looks good');
});

it('should handle callback failure', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });

  const executionPromise = runner.run({ payload: {} });

  const callbackOp = runner.getOperation('wait-for-approval');
  await callbackOp.waitForData(WaitingOperationStatus.STARTED);

  await callbackOp.sendCallbackFailure(
    'ApprovalDenied',
    'Request was rejected'
  );

  const execution = await executionPromise;
  expect(execution.getStatus()).toBe('FAILED');
});
```

**Python:**

Testing callbacks in Python follows the same marker pattern. The callback operation
appears in `result.operations` with `operation_type == OperationType.CALLBACK`:

```python
def test_callback_creation():
    """Test that callback is created correctly."""
    runner = DurableFunctionTestRunner(handler=handler)
    
    with runner:
        result = runner.run(input={'approver': '[email]'}, timeout=10)

    # Find callback operations in the result
    callback_ops = [
        op for op in result.operations
        if op.operation_type == OperationType.CALLBACK
    ]
    assert len(callback_ops) == 1
    assert callback_ops[0].name == 'wait-for-approval'
    assert callback_ops[0].callback_id is not None
```

## Testing Callback Heartbeats

**TypeScript:**

```typescript
it('should handle callback heartbeats', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });

  const executionPromise = runner.run({ payload: {} });

  const callbackOp = runner.getOperation('long-running-process');
  await callbackOp.waitForData(WaitingOperationStatus.STARTED);

  // Send heartbeats
  await callbackOp.sendCallbackHeartbeat();
  await runner.skipTime({ minutes: 2 });
  await callbackOp.sendCallbackHeartbeat();
  await runner.skipTime({ minutes: 2 });
  
  // Complete callback
  await callbackOp.sendCallbackSuccess(JSON.stringify({ status: 'completed' }));

  const execution = await executionPromise;
  expect(execution.getStatus()).toBe('SUCCEEDED');
});
```

## Testing Error Scenarios

**TypeScript:**

```typescript
it('should retry on failure', async () => {
  let attemptCount = 0;
  
  const testHandler = withDurableExecution(async (event, context: DurableContext) => {
    return await context.step('flaky-operation', async () => {
      attemptCount++;
      if (attemptCount < 3) {
        throw new Error('Temporary failure');
      }
      return { success: true };
    });
  });

  const runner = new LocalDurableTestRunner({ handlerFunction: testHandler });
  const execution = await runner.run({ payload: {} });

  expect(execution.getStatus()).toBe('SUCCEEDED');
  expect(attemptCount).toBe(3);

  const step = runner.getOperation('flaky-operation');
  expect(step.getStatus()).toBe(OperationStatus.SUCCEEDED);
});

it('should fail after max retries', async () => {
  const testHandler = withDurableExecution(async (event, context: DurableContext) => {
    return await context.step(
      'always-fails',
      async () => {
        throw new Error('Permanent failure');
      },
      {
        retryStrategy: createRetryStrategy({ maxAttempts: 3 })
      }
    );
  });

  const runner = new LocalDurableTestRunner({ handlerFunction: testHandler });
  const execution = await runner.run({ payload: {} });

  expect(execution.getStatus()).toBe('FAILED');
  expect(execution.getError()?.errorMessage).toContain('Permanent failure');
});
```

## Testing Concurrent Operations

**TypeScript:**

```typescript
it('should process items concurrently', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });
  
  const execution = await runner.run({ 
    payload: { items: [1, 2, 3, 4, 5] } 
  });

  expect(execution.getStatus()).toBe('SUCCEEDED');

  const mapOp = runner.getOperation('process-items');
  expect(mapOp.getType()).toBe(OperationType.MAP);

  // Check individual item operations
  const item0 = runner.getOperation('process-0');
  expect(item0.getStatus()).toBe(OperationStatus.SUCCEEDED);
});
```

## Cloud Testing

For integration tests against real Lambda:

**TypeScript:**

```typescript
import { CloudDurableTestRunner } from '@aws/durable-execution-sdk-js-testing';

describe('Integration Tests', () => {
  it('should execute in real Lambda', async () => {
    const runner = new CloudDurableTestRunner({
      functionName: 'my-durable-function:1',  // Qualified ARN required
      client: new LambdaClient({ region: 'us-east-1' })
    });

    const execution = await runner.run({
      payload: { userId: '123' },
      config: { pollInterval: 1000 }
    });

    expect(execution.getStatus()).toBe('SUCCEEDED');
    
    const step = runner.getOperation('fetch-user');
    expect(step.getStatus()).toBe(OperationStatus.SUCCEEDED);
  });
});
```

**Python:**

Cloud mode uses `DurableFunctionCloudTestRunner` with the same API:

```bash
# Set environment variables for cloud mode
export AWS_REGION=us-west-2
export QUALIFIED_FUNCTION_NAME="my-durable-function:$LATEST"
export LAMBDA_FUNCTION_TEST_NAME="my_function"

# Run in cloud mode
pytest --runner-mode=cloud -k test_workflow
```

The same test works in both modes:

```python
def test_workflow_cloud():
    """Test against deployed Lambda function."""
    runner = DurableFunctionCloudTestRunner(
        function_name='my-function:$LATEST',
        region='us-west-2'
    )
    
    with runner:
        result = runner.run(input={'user_id': '123'}, timeout=60)

    assert result.status is InvocationStatus.SUCCEEDED
```

## Test Assertions

**TypeScript:**

```typescript
it('should validate operation details', async () => {
  const runner = new LocalDurableTestRunner({ handlerFunction: handler });
  await runner.run({ payload: {} });

  const step = runner.getOperation('process-data');
  
  // Check operation type
  expect(step.getType()).toBe(OperationType.STEP);
  
  // Check status
  expect(step.getStatus()).toBe(OperationStatus.SUCCEEDED);
  
  // Check timing
  expect(step.getStartTimestamp()).toBeDefined();
  expect(step.getEndTimestamp()).toBeDefined();
  
  // Check result
  const stepDetails = step.getStepDetails();
  expect(stepDetails?.result).toEqual({ processed: true });
});
```

## Best Practices

1. **Always name operations** for reliable test assertions
2. **Get operations by name**, never by index
3. **Test replay behavior** with multiple invocations
4. **Use fake clock** for time-dependent tests
5. **Test error scenarios** including retries and failures
6. **Test callbacks** with success, failure, and timeout cases
7. **Validate operation details** (type, status, timing, results)
8. **Use cloud tests** for integration testing
9. **Mock external dependencies** in unit tests
10. **Test concurrent operations** individually and as a group

## Common Pitfalls

### ❌ Getting Operations by Index

```typescript
// Brittle - breaks when operations change
const step = runner.getOperationByIndex(0);
```

### ✅ Getting Operations by Name

```typescript
// Robust - works even if operation order changes
const step = runner.getOperation('fetch-user');
```

### ❌ Not Waiting for Callbacks

```typescript
// Race condition - callback might not exist yet
const callbackOp = runner.getOperation('wait-approval');
await callbackOp.sendCallbackSuccess('{}');
```

### ✅ Waiting for Callbacks

```typescript
// Use waitForData with proper status
import { WaitingOperationStatus } from '@aws/durable-execution-sdk-js-testing';

const callbackOp = runner.getOperation('wait-approval');
await callbackOp.waitForData(WaitingOperationStatus.STARTED);
await callbackOp.sendCallbackSuccess(JSON.stringify({}));
```

## Common Testing Errors

### TypeScript

| Error                                 | Cause                                 | Solution                                          |
| ------------------------------------- | ------------------------------------- | ------------------------------------------------- |
| `'result' is of type 'unknown'`       | Missing type casting in tests         | Cast result: `as any` or specific type            |
| `'payload' does not exist in type`    | Wrong test runner API                 | Wrap event in `payload: {}` object                |
| `Cannot find operation at index`      | Using index for unstable operations   | Use `getOperation("name")` instead                |
| Flaky callback tests                  | Race condition with callback creation | Use `waitForData(WaitingOperationStatus.STARTED)` |
| `Unexpected token` in callback result | Forgot to JSON.stringify              | Always stringify: `JSON.stringify(data)`          |
| Callback result parsing error         | Result is JSON string                 | Parse result: `JSON.parse(result.value)`          |
| Operation not found by name           | Missing operation name                | Always name operations in handler                 |

## Jest Configuration

**jest.config.js:**

```javascript
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/*.test.ts'],
  transform: {
    '^.+\\.ts$': 'ts-jest',
  },
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.d.ts',
  ],
};
```

**Key points:**

- `preset: 'ts-jest'` is essential for TypeScript support
- `transform` maps .ts files to ts-jest transformer
- `testMatch` specifies test file patterns
- Use `skipTime: true` in test setup for fast execution
