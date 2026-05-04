# Orchestration Reference

AWS Step Functions, Amazon EventBridge, and Lambda Durable Functions patterns and configuration.

## Contents

- [Step Functions Standard vs Express](#step-functions-standard-vs-express)
- [State machine patterns](#state-machine-patterns)
- [Error handling](#error-handling)
- [EventBridge rules and patterns](#eventbridge-rules-and-patterns)
- [EventBridge Pipes](#eventbridge-pipes)
- [Lambda Durable Functions](#lambda-durable-functions)

---

## Step Functions Standard vs Express

### Decision Matrix

| Dimension | Standard | Express |
|---|---|---|
| Max duration | 1 year | 5 minutes |
| Execution semantics | Exactly-once | At-least-once (async) / At-most-once (sync) |
| Execution history | Stored 90 days (API/console) | CloudWatch Logs only (must enable) |
| `.sync` integration | Supported | **Not supported** |
| `.waitForTaskToken` | Supported | **Not supported** |
| Distributed Map | Supported | **Not supported** |
| Activities | Supported | **Not supported** |
| Idempotency | Automatic (execution name unique for 90 days) | Not managed |

Express sub-types:

- **Asynchronous**: Fire-and-forget. Results via CloudWatch Logs.
- **Synchronous**: Blocks until completion. Invokable from API Gateway, Lambda, or `StartSyncExecution`. 5-min max.

| Use Case | Type |
|---|---|
| Long-running orchestration, `.sync`/callback patterns | Standard |
| Non-idempotent operations (payments, exactly-once) | Standard |
| Distributed Map (large-scale parallel) | Standard |
| High-volume event processing (IoT, streaming) | Express |
| API-backed synchronous microservice orchestration | Synchronous Express |

---

## State Machine Patterns

### Saga Pattern (Compensating Transactions)

Each step has a corresponding undo step invoked on failure via `Catch`. Compensations chain in reverse.

```json
{
  "Comment": "Saga pattern — book travel",
  "StartAt": "BookHotel",
  "States": {
    "BookHotel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:book-hotel",
      "TimeoutSeconds": 30,
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.BookHotelError",
        "Next": "NotifyFailure"
      }],
      "Next": "BookFlight"
    },
    "BookFlight": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:book-flight",
      "TimeoutSeconds": 30,
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.BookFlightError",
        "Next": "CancelHotel"
      }],
      "Next": "BookCar"
    },
    "BookCar": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:book-car",
      "TimeoutSeconds": 30,
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.BookCarError",
        "Next": "CancelFlight"
      }],
      "Next": "ConfirmBooking"
    },
    "CancelFlight": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:cancel-flight",
      "Next": "CancelHotel"
    },
    "CancelHotel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:cancel-hotel",
      "Next": "NotifyFailure"
    },
    "NotifyFailure": {
      "Type": "Fail",
      "Error": "SagaFailed",
      "Cause": "One or more bookings failed; compensations executed"
    },
    "ConfirmBooking": { "Type": "Succeed" }
  }
}
```

### Parallel State

Executes branches concurrently. **Output is an array** with one element per branch. All branches must succeed or the entire Parallel state fails. Supports `Retry` and `Catch`.

```json
{
  "Type": "Parallel",
  "Branches": [
    {
      "StartAt": "ProcessImages",
      "States": {
        "ProcessImages": {
          "Type": "Task",
          "Resource": "arn:aws:lambda:us-east-1:123456789012:function:process-images",
          "End": true
        }
      }
    },
    {
      "StartAt": "ProcessMetadata",
      "States": {
        "ProcessMetadata": {
          "Type": "Task",
          "Resource": "arn:aws:lambda:us-east-1:123456789012:function:process-metadata",
          "End": true
        }
      }
    }
  ],
  "Next": "AggregateResults"
}
```

### Map State

**Inline Map**: Iterates over an array in the same execution. Max **40 concurrent** iterations.

```json
{
  "Type": "Map",
  "ItemsPath": "$.orders",
  "MaxConcurrency": 10,
  "ItemProcessor": {
    "ProcessorConfig": { "Mode": "INLINE" },
    "StartAt": "ProcessOrder",
    "States": {
      "ProcessOrder": {
        "Type": "Task",
        "Resource": "arn:aws:lambda:us-east-1:123456789012:function:process-order",
        "End": true
      }
    }
  },
  "Next": "Done"
}
```

**Distributed Map**: Up to **10,000 parallel child executions**. Reads from S3 (JSON, CSV, S3 inventory). Supports `ItemBatcher`, `ItemReader`, `ResultWriter`. **Standard workflows only.**

### Choice State

Routes execution based on input conditions. Always include a `Default` branch.

Comparison operators: `StringEquals`, `StringMatches`, `NumericGreaterThan`, `NumericLessThanEquals`, `BooleanEquals`, `IsPresent`, `IsNull`, `TimestampEquals`, and `Path` variants.

```json
{
  "Type": "Choice",
  "Choices": [
    { "Variable": "$.orderTotal", "NumericGreaterThan": 1000, "Next": "HighValueOrder" },
    { "Variable": "$.isPrime", "BooleanEquals": true, "Next": "PrimeProcessing" }
  ],
  "Default": "StandardProcessing"
}
```

### Agentic AI Loop Pattern (Tool Use)

Model outputs a structured response indicating a tool call or final answer. Choice state routes accordingly. Tool results feed back in a loop.

```json
{
  "Comment": "Agentic AI loop with tool use",
  "QueryLanguage": "JSONata",
  "StartAt": "InvokeModel",
  "States": {
    "InvokeModel": {
      "Type": "Task",
      "Resource": "arn:aws:states:::bedrock:invokeModel",
      "Arguments": {
        "ModelId": "global.anthropic.claude-sonnet-4-6",
        "Body": {
          "anthropic_version": "bedrock-2023-05-31",
          "max_tokens": 4096,
          "messages": "{% $states.input.messages %}"
        },
        "ContentType": "application/json",
        "Accept": "application/json"
      },
      "Next": "CheckAction"
    },
    "CheckAction": {
      "Type": "Choice",
      "Choices": [
        { "Condition": "{% $states.input.Body.stop_reason = 'tool_use' %}", "Next": "ExecuteTool" }
      ],
      "Default": "ReturnResult"
    },
    "ExecuteTool": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:123456789012:function:execute-tool",
      "TimeoutSeconds": 60,
      "Next": "InvokeModel"
    },
    "ReturnResult": { "Type": "Succeed" }
  }
}
```

---

## Error Handling

### Built-in Error Names

| Error Name | Description | Retriable? |
|---|---|---|
| `States.ALL` | Wildcard — matches any error | Yes |
| `States.TaskFailed` | Wildcard for task errors (except `States.Timeout`) | Yes |
| `States.Timeout` | Task exceeded `TimeoutSeconds` or `HeartbeatSeconds` | Yes |
| `States.HeartbeatTimeout` | No heartbeat within `HeartbeatSeconds` | Yes |
| `States.Permissions` | Insufficient IAM privileges | Yes |
| `States.DataLimitExceeded` | Payload exceeds 256 KiB — **terminal** | **No** |
| `States.Runtime` | Invalid JSONPath, null payload — **terminal** | **No** |
| `States.ItemReaderFailed` | Map couldn't read from ItemReader source | Yes |
| `States.ResultWriterFailed` | Map couldn't write to ResultWriter destination | Yes |

`States.ALL` does **not** match `States.DataLimitExceeded` or `States.Runtime`.

### Retry Configuration

Available on `Task`, `Parallel`, and `Map` states. Retries are attempted before catchers.

```json
"Retry": [
  {
    "ErrorEquals": ["States.Timeout"],
    "IntervalSeconds": 3,
    "MaxAttempts": 2,
    "BackoffRate": 2.0,
    "MaxDelaySeconds": 30,
    "JitterStrategy": "FULL"
  },
  {
    "ErrorEquals": ["Lambda.ServiceException", "Lambda.SdkClientException"],
    "IntervalSeconds": 1,
    "MaxAttempts": 3,
    "BackoffRate": 2.0
  },
  {
    "ErrorEquals": ["States.ALL"],
    "IntervalSeconds": 1,
    "MaxAttempts": 3,
    "BackoffRate": 2.0
  }
]
```

| Field | Default | Description |
|---|---|---|
| `ErrorEquals` | (required) | Array of error names to match |
| `IntervalSeconds` | 1 | Initial wait before first retry |
| `MaxAttempts` | 3 | Max retries; 0 = never retry |
| `BackoffRate` | 2.0 | Multiplier for exponential backoff |
| `MaxDelaySeconds` | — | Cap on computed backoff interval |
| `JitterStrategy` | `"NONE"` | `"FULL"` randomizes wait between 0 and computed interval |

Rules:

- `States.ALL` must be **last** in the Retry array
- Retries count as state transitions (billed in Standard workflows)
- `States.Runtime` and `States.DataLimitExceeded` **cannot be retried**
- Use `JitterStrategy: "FULL"` to prevent thundering herd

### Catch (Fallback States)

```json
"Catch": [
  {
    "ErrorEquals": ["CustomBusinessError"],
    "ResultPath": "$.error-info",
    "Next": "HandleBusinessError"
  },
  {
    "ErrorEquals": ["States.ALL"],
    "ResultPath": "$.error-info",
    "Next": "GenericErrorHandler"
  }
]
```

- `ResultPath` preserves original input alongside the error (e.g., `"$.error-info"`)
- Without `ResultPath`, error output replaces entire input
- Retries are attempted first; catchers apply only after retries are exhausted

### Error handling best practices

1. **Always set `TimeoutSeconds`** on every Task state
2. **Always retry Lambda service exceptions**: `Lambda.ServiceException`, `Lambda.SdkClientException`
3. **Use `HeartbeatSeconds`** for long-running tasks
4. **Combine Retry + Catch**: Retry transient, Catch permanent
5. **Use `JitterStrategy: "FULL"`** to prevent thundering herd
6. **Listen for execution failures via EventBridge** for top-level failures

---

## EventBridge Rules and Patterns

### Event Pattern Structure

All specified fields must match (AND). Values within an array are OR'd.

```json
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["terminated", "stopped"] }
}
```

### Advanced Pattern Operators

| Operator | Syntax | Description |
|---|---|---|
| Exact match | `["value"]` | Field equals value |
| Prefix | `[{"prefix": "prod-"}]` | Starts with string |
| Suffix | `[{"suffix": ".json"}]` | Ends with string |
| Anything-but | `[{"anything-but": ["val"]}]` | Not in list |
| Numeric range | `[{"numeric": [">", 0, "<=", 100]}]` | Numeric comparison |
| Exists | `[{"exists": true}]` | Field must be present |
| Wildcard | `[{"wildcard": "prod-*-east"}]` | Glob-style matching |

### EventBridge best practices

1. **Dedicated event bus per application domain** — default bus for AWS service events only
2. **Be precise with patterns** — broad patterns increase risk of infinite loops
3. **One target per rule** — simplifies debugging and IAM permissions
4. **Use DLQs on targets** — capture failed event deliveries
5. **Use the EventBridge Sandbox** to test patterns before deploying

### Step Functions Status Change Events

Step Functions emits to the default bus automatically:

```json
{
  "source": ["aws.states"],
  "detail-type": ["Step Functions Execution Status Change"],
  "detail": { "status": ["FAILED", "TIMED_OUT", "ABORTED"] }
}
```

### Integration Patterns

**SFN → EventBridge** (publish events from a workflow):

```json
{
  "Type": "Task",
  "QueryLanguage": "JSONata",
  "Resource": "arn:aws:states:::events:putEvents",
  "Arguments": {
    "Entries": [{
      "Detail": { "orderId": "{% $states.input.orderId %}", "status": "PROCESSED" },
      "DetailType": "OrderProcessed",
      "EventBusName": "my-app-bus",
      "Source": "my-app.orders"
    }]
  },
  "Next": "Done"
}
```

**EventBridge → SFN**: Rule target is the state machine ARN. Event payload becomes execution input.

**Fan-out**: Single event triggers multiple workflows via multiple rules on the same bus.

---

## EventBridge Pipes

### Architecture

```
Source → [Filter] → [Enrichment] → [Transform] → Target
```

Eliminates intermediary Lambda functions for point-to-point integrations.

### Supported Sources

| Source | Notes |
|---|---|
| Amazon SQS | Standard and FIFO queues |
| Amazon Kinesis Data Streams | Shard-level polling |
| Amazon DynamoDB Streams | Change data capture |
| Amazon MSK / Self-managed Kafka | Topic-level consumption |
| Amazon MQ | ActiveMQ and RabbitMQ |

### Enrichment Options

Lambda, API Gateway, EventBridge API Destinations, Step Functions (Synchronous Express).

### Key Features

- **Filtering**: Event patterns filter at the source — pay only for matched events
- **Ordering**: Maintains event ordering within batches
- **Built-in retry + DLQ**: Source-level retry with dead-letter queue support

### Pipes vs Rules

| Dimension | Pipes | Rules |
|---|---|---|
| Topology | Point-to-point (1→1) | Fan-out (1→N) |
| Sources | SQS, Kinesis, DDB Streams, MSK, MQ | Any event on a bus |
| Enrichment | Built-in | Not built-in |
| Use case | Replace Lambda glue | Event routing and distribution |

---

## Lambda Durable Functions

### Core Mechanism: Checkpoint-and-Replay

1. **Checkpoint**: As your function executes durable operations, the SDK persists each result to a checkpoint log
2. **Suspend**: On `wait` or interruption, Lambda saves the checkpoint and terminates — **zero compute during suspension**
3. **Replay**: On resume, Lambda invokes from the beginning. The SDK replays the log — completed operations return stored results without re-executing

### SDK Availability

| Language | Package | Handler Pattern |
|---|---|---|
| JavaScript/TypeScript | `@aws/durable-execution-sdk-js` | `withDurableExecution(async (event, ctx) => ...)` |
| Python | `aws-durable-execution-sdk-python` | `@durable_execution` decorator |
| Java | `software.amazon.lambda.durable:aws-durable-execution-sdk-java` | Extends `DurableHandler` |

Go, Rust, and .NET are **not supported**.

### DurableContext Operations

| Operation | Description |
|---|---|
| `step(name, fn)` | Execute a named step; result is checkpointed |
| `wait(name, seconds)` | Suspend execution for a duration (zero compute during wait) |
| `parallel(steps)` | Execute multiple steps concurrently |
| `map(items, fn)` | Iterate over items with checkpointing |
| `waitForCallback(name)` | Suspend until external callback resumes execution |
| `invoke(name, fn, arn)` | Invoke another Lambda and checkpoint the result |

### Example: Distributed Transaction

```typescript
import { DurableContext, withDurableExecution } from "@aws/durable-execution-sdk-js";

export const handler = withDurableExecution(
  async (event: any, context: DurableContext) => {
    const inventory = await context.step("reserve-inventory", async () => {
      return await inventoryService.reserve(event.items);
    });
    const payment = await context.step("process-payment", async () => {
      return await paymentService.charge(event.amount);
    });
    const shipment = await context.step("create-shipment", async () => {
      return await shippingService.createShipment(event.orderId, inventory);
    });
    return { orderId: event.orderId, status: "completed", shipment };
  }
);
```

### Limitations

- Must enable durable execution **at function creation time** (cannot retrofit)
- Max checkpoint size per child context result: **256 KB** (cumulative storage limit: 100 MB per execution)
- Code outside durable steps must be **deterministic** (replay re-executes it)
- **No nested steps** (steps cannot contain other steps)
- No Go, Rust, or .NET SDK
- Durable execution timeout: up to 1 year

### Decision Matrix: Durable Functions vs Step Functions

| Question | Durable Functions | Step Functions |
|---|---|---|
| Primary focus? | Application logic in Lambda | Orchestration across AWS services |
| Programming model? | Standard code (TS/Python/Java) | Amazon States Language (ASL) or visual designer |
| AWS service integrations? | Primarily Lambda | 200+ native integrations |
| Who reads the workflow? | Developers | Non-technical stakeholders |
| Best for? | Distributed transactions, stateful logic, AI agent loops | Business process automation, multi-service orchestration |

**Hybrid pattern**: Durable functions for application-level logic within Lambda, Step Functions for high-level orchestration across multiple AWS services.
