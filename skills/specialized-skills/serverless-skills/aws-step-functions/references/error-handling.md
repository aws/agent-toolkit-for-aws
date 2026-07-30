# Error Handling in JSONata Mode

## Overview

When a state encounters an error, Step Functions defaults to failing the entire execution. You can override this with `Retry` (retry the failed state) and `Catch` (transition to a fallback state). `Retry` and `Catch` are available on: Task, Parallel, and Map states.

## Error Names

Errors are identified by case-sensitive strings. Step Functions defines these built-in error codes:

| Error Code | Description |
|-----------|-------------|
| `States.ALL` | Wildcard — matches any error |
| `States.Timeout` | Task exceeded `TimeoutSeconds` or missed heartbeat |
| `States.HeartbeatTimeout` | Task missed heartbeat interval |
| `States.TaskFailed` | Task failed during execution |
| `States.Permissions` | Insufficient privileges |
| `States.QueryEvaluationError` | JSONata expression evaluation failed |
| `States.BranchFailed` | A Parallel state branch failed |
| `States.NoChoiceMatched` | No Choice rule matched and no Default |
| `States.ExceedToleratedFailureThreshold` | Map state exceeded failure tolerance |
| `States.ItemReaderFailed` | Map state ItemReader failed |
| `States.ResultWriterFailed` | Map state ResultWriter failed |

Custom error names are allowed but must NOT start with `States.`.

---

## Retry

The `Retry` field is an array of Retrier objects. The interpreter scans retriers in order and uses the first one whose `ErrorEquals` matches.

### Retrier Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ErrorEquals` | string[] | Required | Error names to match |
| `IntervalSeconds` | integer | 1 | Seconds before first retry |
| `MaxAttempts` | integer | 3 | Maximum retry attempts (0 = never retry) |
| `BackoffRate` | number | 2.0 | Multiplier for retry interval (must be ≥ 1.0) |
| `MaxDelaySeconds` | integer | — | Cap on retry interval |
| `JitterStrategy` | string | — | Jitter strategy (e.g., `"FULL"`) |

Rules:

- `States.ALL` must appear alone in its `ErrorEquals` array.
- `States.ALL` must be in the last retrier.
- `MaxAttempts: 0` means "never retry this error."
- Retrier attempt counts reset when the interpreter transitions to another state.
- Retriers are evaluated in order. Each retrier tracks its own attempt count independently.

---

## Catch

The `Catch` field is an array of Catcher objects. After retries are exhausted (or if no retrier matches), the interpreter scans catchers in order.

### Catcher Fields (JSONata)

| Field | Type | Description |
|-------|------|-------------|
| `ErrorEquals` | string[] | Required. Error names to match |
| `Next` | string | Required. State to transition to |
| `Output` | any | Optional. Transform the error output |
| `Assign` | object | Optional. Assign variables from error context |

### Error Output Structure

When a state fails and matches a Catcher, `$states.errorOutput` is a JSON object with:

- `Error` (string) — the error name
- `Cause` (string) — human-readable error description

In a Catch block, `Assign` and `Output` can reference:

- `$states.input` — the original state input
- `$states.errorOutput` — the error details
- `$states.context` — execution context

If a Catcher matches, the state's top-level `Assign` is NOT evaluated — only the Catcher's `Assign` runs. If no `Output` is provided in the Catcher, the state output is the raw Error Output object.

When both Retry and Catch are present, retries are attempted first. Only if retries are exhausted does the Catch apply.

---

## Handling States.QueryEvaluationError

JSONata expressions can fail at runtime. Common causes:

1. Type error — `{% $x + $y %}` where `$x` or `$y` is not a number
2. Type incompatibility — `"TimeoutSeconds": "{% $name %}"` where `$name` is a string
3. Value out of range — negative number for `TimeoutSeconds`
4. Undefined result — `{% $data.nonExistentField %}` — JSON cannot represent undefined

Prevent these errors with defensive expressions: use `$exists()` before accessing fields evaluated at runtime, `$type()` before arithmetic, and guard filtered results that may return a single object instead of an array. Always guard with `$exists()` — if a variable was never assigned (e.g., the Catch didn't fire for that path), referencing it directly throws `States.QueryEvaluationError`. See `transforming-data.md` for defensive JSONata examples.

---

## Error Handling in Parallel States

If any branch fails, the entire Parallel state fails. Use `States.BranchFailed` in Retry/Catch at the Parallel state level.

---

## Error Handling in Map States

Individual iteration failures can be tolerated with `ToleratedFailurePercentage` or `ToleratedFailureCount`. If the threshold is exceeded, the Map state throws `States.ExceedToleratedFailureThreshold`.

---

## Retry and Catch with User-Friendly Error

Retries transient errors with backoff, then catches all errors into a variable and transitions to a Fail state with a descriptive Cause. Guard variable references with `$exists()` in case the Catch path wasn't taken.

```json
"ChargePayment": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:ChargeCard:$LATEST",
    "Payload": "{% $states.input %}"
  },
  "Retry": [
    {
      "ErrorEquals": ["ThrottlingException", "ServiceUnavailable"],
      "IntervalSeconds": 2,
      "MaxAttempts": 3,
      "BackoffRate": 2.0,
      "JitterStrategy": "FULL"
    },
    {
      "ErrorEquals": ["States.QueryEvaluationError"],
      "MaxAttempts": 0
    }
  ],
  "Catch": [
    {
      "ErrorEquals": ["States.ALL"],
      "Assign": {
        "error": "{% $states.errorOutput %}"
      },
      "Next": "PaymentFailed"
    }
  ],
  "Output": "{% $states.result.Payload %}",
  "Next": "ConfirmOrder"
},
"PaymentFailed": {
  "Type": "Fail",
  "Error": "PaymentError",
  "Cause": "{% 'Payment failed for order ' & ($exists($orderId) ? $orderId : 'unknown') & ': ' & ($exists($error.Error) ? $error.Error : 'Unknown') & ' - ' & ($exists($error.Cause) ? $error.Cause : 'No details') & '. Timestamp: ' & $now() %}"
}
```
