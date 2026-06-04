# Wait Operations

Suspend execution without compute charges for delays, external callbacks, and polling.

## Simple Waits

Pause execution for a duration (no compute charges during wait):

**TypeScript:**

```typescript
await context.wait({ seconds: 30 });
await context.wait({ minutes: 5 });
await context.wait({ hours: 1, minutes: 30 });
await context.wait({ days: 7 });

// Named wait (recommended)
await context.wait('rate-limit-delay', { seconds: 60 });
```

**Python:**

```python
from aws_durable_execution_sdk_python.config import Duration

context.wait(duration=Duration.from_seconds(30))
context.wait(duration=Duration.from_minutes(5))
context.wait(duration=Duration.from_hours(1))
context.wait(duration=Duration.from_days(7))

# Named wait (recommended)
context.wait(duration=Duration.from_seconds(60), name='rate-limit-delay')
```

**Max wait duration:** Up to 1 year

## Wait for Callback

Wait for external systems to respond (human approval, webhook, async job):

**TypeScript:**

```typescript
const result = await context.waitForCallback(
  'wait-for-approval',
  async (callbackId, ctx) => {
    // Send callback ID to external system
    await sendApprovalEmail(approverEmail, callbackId);
  },
  {
    timeout: { hours: 24 },
    heartbeatTimeout: { minutes: 5 }
  }
);

// External system calls back with:
// aws lambda send-durable-execution-callback-success \
//   --callback-id <callbackId> \
//   --result '{"approved": true}'
```

**Python:**

```python
from aws_durable_execution_sdk_python.config import WaitForCallbackConfig

# Wait for external approval
def submit_approval(callback_id: str, ctx):
    ctx.logger.info('Sending approval request')
    send_approval_email(approver_email, callback_id)

result = context.wait_for_callback(
    submitter=submit_approval,
    name='wait-for-approval',
    config=WaitForCallbackConfig(
        timeout=Duration.from_hours(24),
        heartbeat_timeout=Duration.from_minutes(5)
    )
)
```

### Callback Success

**CLI:**

```bash
aws lambda send-durable-execution-callback-success \
  --callback-id <callbackId> \
  --result '{"status": "approved", "comments": "Looks good"}'
```

**SDK (TypeScript):**

```typescript
import { LambdaClient, SendDurableExecutionCallbackSuccessCommand } from '@aws-sdk/client-lambda';

const client = new LambdaClient({});
await client.send(new SendDurableExecutionCallbackSuccessCommand({
  CallbackId: callbackId,
  Result: JSON.stringify({ status: 'approved' })
}));
```

**SDK (Python / boto3):**

```python
import boto3
import json

lambda_client = boto3.client('lambda')
lambda_client.send_durable_execution_callback_success(
    CallbackId=callback_id,
    Result=json.dumps({'status': 'approved'})
)
```

### Callback Failure

**CLI:**

```bash
aws lambda send-durable-execution-callback-failure \
  --callback-id <callbackId> \
  --error-type "ApprovalDenied" \
  --error-message "Request denied by approver"
```

### Heartbeats

Keep callback alive during long-running external processes:

**TypeScript:**

```typescript
const result = await context.waitForCallback(
  'long-process',
  async (callbackId) => {
    await startLongRunningJob(callbackId);
  },
  {
    timeout: { hours: 24 },
    heartbeatTimeout: { minutes: 5 }  // Must receive heartbeat every 5 min
  }
);

// External system sends heartbeats:
// aws lambda send-durable-execution-callback-heartbeat --callback-id <callbackId>
```

**CLI Heartbeat:**

```bash
aws lambda send-durable-execution-callback-heartbeat \
  --callback-id <callbackId>
```

## Wait for Condition

Poll until a condition is met (job completion, resource availability):

**TypeScript:**

```typescript
const finalState = await context.waitForCondition(
  'wait-for-job',
  async (currentState, ctx) => {
    const status = await checkJobStatus(currentState.jobId);
    return { ...currentState, status };
  },
  {
    initialState: { jobId: 'job-123', status: 'pending' },
    waitStrategy: createWaitStrategy({
      maxAttempts: 60,
      initialDelay: { seconds: 5 },
      maxDelay: { seconds: 30 },
      backoffRate: 1.5,
      shouldContinuePolling: (result) => result.status !== "completed"
    }),
  }
);
```

**Python:**

```python
# Note: get_job_status is decorated with @durable_step
from aws_durable_execution_sdk_python.waits import WaitForConditionConfig, create_wait_strategy, WaitStrategyConfig
from aws_durable_execution_sdk_python.config import Duration

def check_job(state: dict, check_ctx):
    status = get_job_status(state['job_id'])
    return {'job_id': state['job_id'], 'status': status}

wait_strategy = create_wait_strategy(
    WaitStrategyConfig(
        should_continue_polling=lambda state: state['status'] != 'completed',
        max_attempts=60,
        initial_delay=Duration.from_seconds(2),
        max_delay=Duration.from_seconds(60),
        backoff_rate=1.5
    )
)

result = context.wait_for_condition(
    check=check_job,
    config=WaitForConditionConfig(
        initial_state={'job_id': 'job-123', 'status': 'pending'},
        wait_strategy=wait_strategy
    ),
    name='wait-for-job'
)
```

### Custom Wait Strategy

**TypeScript:**

```typescript
const result = await context.waitForCondition(
  'custom-poll',
  async (state) => {
    const data = await fetchData();
    return { ...state, data, attempts: state.attempts + 1 };
  },
  {
    initialState: { attempts: 0 },
    waitStrategy: (state, attempt) => {
      // Stop after 10 attempts
      if (state.attempts >= 10) {
        return { shouldContinue: false };
      }
      
      // Exponential backoff with max 60s
      return {
        shouldContinue: !state.data?.ready,
        delay: { seconds: Math.min(Math.pow(2, attempt), 60) }
      };
    }
  }
);
```

## Callback Patterns

### Human Approval Workflow

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const request = await context.step('create-request', async () =>
    createApprovalRequest(event)
  );

  const decision = await context.waitForCallback(
    'wait-approval',
    async (callbackId) => {
      await sendEmail({
        to: event.approver,
        subject: 'Approval Required',
        body: `Approve: ${approvalUrl}?callback=${callbackId}&action=approve\n` +
              `Reject: ${approvalUrl}?callback=${callbackId}&action=reject`
      });
    },
    { timeout: { hours: 48 } }
  );

  if (decision.action === 'approve') {
    await context.step('execute', async () => executeRequest(request));
    return { status: 'approved' };
  }
  
  return { status: 'rejected' };
});
```

### Webhook Integration

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const order = await context.step('create-order', async () =>
    createOrder(event)
  );

  const payment = await context.waitForCallback(
    'wait-payment',
    async (callbackId) => {
      await paymentProvider.createPayment({
        orderId: order.id,
        amount: order.total,
        webhookUrl: `${webhookUrl}?callback=${callbackId}`
      });
    },
    { timeout: { minutes: 15 } }
  );

  if (payment.status === 'success') {
    await context.step('fulfill', async () => fulfillOrder(order));
  }
  
  return { orderId: order.id, paymentStatus: payment.status };
});
```

### Async Job Polling

**TypeScript:**

```typescript
export const handler = withDurableExecution(async (event, context: DurableContext) => {
  const jobId = await context.step('start-job', async () =>
    startBatchJob(event.data)
  );

  const result = await context.waitForCondition(
    'poll-job',
    async (state) => {
      const job = await getJobStatus(state.jobId);
      return { jobId: state.jobId, status: job.status, result: job.result };
    },
    {
      initialState: { jobId, status: 'running' },
      waitStrategy: createWaitStrategy({
        maxAttempts: 60,
        initialDelay: { seconds: 5 },
        maxDelay: { seconds: 30 },
        backoffRate: 1.5,
        shouldContinuePolling: (result) => result.status === "running"
      }),
    }
  );

  return result;
});
```

## Best Practices

1. **Always name wait operations** for debugging
2. **Set appropriate timeouts** to prevent indefinite waits
3. **Use heartbeats** for long-running external processes
4. **Handle callback failures** explicitly
5. **Implement exponential backoff** for polling
6. **Keep check functions lightweight** in waitForCondition
7. **Store callback IDs securely** when sending to external systems
8. **Validate callback payloads** before processing

## Error Handling

**TypeScript:**

```typescript
try {
  const result = await context.waitForCallback(
    'wait-approval',
    async (callbackId) => sendApproval(callbackId),
    { timeout: { hours: 24 } }
  );
} catch (error) {
  if (error instanceof CallbackError) {
    if (error.errorType === 'Timeout') {
      context.logger.warn('Approval timed out');
      // Handle timeout
    } else {
      context.logger.error('Callback failed', error);
      // Handle failure
    }
  }
}
```

**Python:**

```python
from aws_durable_execution_sdk_python.exceptions import CallbackError
from aws_durable_execution_sdk_python.config import WaitForCallbackConfig

try:
    def submit_approval(callback_id: str, ctx):
        send_approval(callback_id)

    result = context.wait_for_callback(
        submitter=submit_approval,
        name='wait-approval',
        config=WaitForCallbackConfig(timeout=Duration.from_hours(24))
    )
except CallbackError as error:
    if error.error_type == 'Timeout':
        context.logger.warning('Approval timed out')
    else:
        context.logger.error(f'Callback failed: {error}')
```
