# ASL Structure and State Types (JSONata Mode)

Quick reference for the eight state types in AWS Step Functions. See `processing-state-inputs-and-outputs.md` and `transforming-data.md` for details about the data fields available inside each state.
---

## Pass State

Passes input to output, optionally transforming it with JSONata. Useful for injecting or transforming data. Without `Output`, the Pass state copies input to output unchanged.

```json
"SetupAndGreet": {
  "Type": "Pass",
  "Assign": {
    "retryCount": 0,
    "maxRetries": 3,
    "config": "{% $states.input.configuration %}"
  },
  "Output": {
    "greeting": "{% 'Hello, ' & $states.input.name %}",
    "timestamp": "{% $now() %}"
  },
  "Next": "ProcessItem"
}
```

---

## Task State

Executes work via AWS service integrations, activities, or HTTP APIs. Reference service-integrations.md for full details.

### Required Fields

- `Resource`: ARN identifying the task to execute

### Optional Fields

- `Arguments`: Input to the task (replaces JSONPath `Parameters`)
- `Output`: Transform the result
- `Assign`: Store variables from input or result
- `TimeoutSeconds`: Max task duration (default 99999999, accepts JSONata expression)
- `HeartbeatSeconds`: Heartbeat interval (must be < TimeoutSeconds)
- `Retry`: Retry policy array
- `Catch`: Error handler array
- `Credentials`: Cross-account role assumption

---

## Choice State

Uses `Choices` and `Condition` fields with JSONata boolean expressions to implement branching logic.

Key points:

- `Condition` must evaluate to a boolean.
- Each Choice Rule can have its own `Assign` and `Output`.
- If a rule matches, its `Assign`/`Output` are used (not the state-level ones).
- If no rule matches, the state-level `Assign` is evaluated and `Default` is followed.
- `Default` is optional but recommended — without it, `States.NoChoiceMatched` is thrown.
- Choice states cannot be terminal (no `End` field).

```json
"RouteOrder": {
  "Type": "Choice",
  "Choices": [
    {
      "Condition": "{% $states.input.orderType = 'express' %}",
      "Next": "ExpressShipping"
    },
    {
      "Condition": "{% $states.input.total > 100 %}",
      "Assign": {
        "discount": "{% $states.input.total * 0.1 %}"
      },
      "Output": {
        "total": "{% $states.input.total * 0.9 %}"
      },
      "Next": "ApplyDiscount"
    },
    {
      "Condition": "{% $states.input.priority >= 5 and $states.input.category = 'urgent' %}",
      "Next": "PriorityQueue"
    }
  ],
  "Default": "StandardProcessing",
  "Assign": {
    "routedDefault": true
  }
}
```

JSONata supports rich boolean logic:

```json
"Condition": "{% $states.input.age >= 18 and $states.input.age <= 65 %}"
"Condition": "{% $states.input.status = 'active' or $states.input.override = true %}"
"Condition": "{% $not($exists($states.input.error)) %}"
"Condition": "{% $contains($states.input.email, '@') %}"
"Condition": "{% $count($states.input.items) > 0 %}"
"Condition": "{% $states.input.score >= $threshold %}"
```

---

## Wait State

Delays execution for a specified duration or until a timestamp.

```json
"DynamicWait": {
  "Type": "Wait",
  "Seconds": "{% $states.input.delaySeconds %}",
  "Next": "Continue"
}
```

### Wait Until Timestamp

```json
"WaitUntilDate": {
  "Type": "Wait",
  "Timestamp": "{% $states.input.scheduledTime %}",
  "Next": "Execute"
}
```

Timestamps must conform to RFC3339 (e.g., `"2026-03-14T01:59:00Z"`).

A Wait state must contain exactly one of `Seconds` or `Timestamp`.

---

## Succeed State

Terminates the state machine (or a Parallel branch / Map iteration) successfully.

```json
"Done": {
  "Type": "Succeed",
  "Output": {
    "status": "completed",
    "processedAt": "{% $now() %}"
  }
}
```

---

## Fail State

Terminates the state machine with an error.

```json
"DynamicFail": {
  "Type": "Fail",
  "Error": "{% $states.input.errorCode %}",
  "Cause": "{% $states.input.errorMessage %}"
}
```

Reference error-handling.md for more information.

---

## Parallel State

Executes multiple branches concurrently. All branches receive the same input.

Key points:

- `Arguments` provides input to each branch's StartAt state (optional, defaults to state input).
- Result is an array with one element per branch, in the same order as `Branches`.
- If any branch fails, the entire Parallel state fails (unless caught).
- States inside branches can only transition to other states within the same branch.
- Branch variables are scoped — branches cannot access each other's variables.
- Use `Output` on terminal states within branches to pass data back to the outer scope.

---

## Map State

Iterates over a JSON array or a JSON object, processing each element (potentially in parallel). See `assets/nested-map-parallel-structures.asl.json` for a complete state machine example combining Map + Parallel states.

### Key Map Fields

| Field | Description |
|-------|-------------|
| `Items` | JSON array, JSON object, or JSONata expression evaluating to an array or object |
| `ItemProcessor` | State machine to run for each item (has `StartAt` and `States`) |
| `ItemSelector` | Reshape each item before processing |
| `MaxConcurrency` | Max parallel iterations (0 = unlimited, 1 = sequential) |
| `ToleratedFailurePercentage` | 0-100, percentage of items allowed to fail |
| `ToleratedFailureCount` | Number of items allowed to fail |
| `ItemReader` | Read items from an external resource |
| `ItemBatcher` | Batch items into sub-arrays |
| `ResultWriter` | Write results to an external resource |

### Map ProcessorConfig

The `ItemProcessor` can include a `ProcessorConfig` to control execution mode.

- `INLINE` (default) — iterations run within the parent execution. Use for most cases.
- `DISTRIBUTED` — iterations run as child executions. Use for large-scale processing (thousands+ items), items read from S3, or when you need per-iteration execution history.

```json
"ProcessOrders": {
  "Type": "Map",
  "Items": "{% $states.input.orders %}",
  "MaxConcurrency": 10,
  "ItemProcessor": {
    "ProcessorConfig": { "Mode": "INLINE" },
    "StartAt": "ProcessOne",
    "States": {
      "ProcessOne": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Arguments": {
          "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:ProcessOrder:$LATEST",
          "Payload": "{% $states.input %}"
        },
        "Output": "{% $states.result.Payload %}",
        "End": true
      }
    }
  },
  "Assign": { "orderResults": "{% $states.result %}" },
  "Next": "Done"
}
```

### Map Failure Tolerance

Use `ToleratedFailurePercentage` (0–100) and/or `ToleratedFailureCount` to allow partial failures. The Map state fails if either threshold is breached.

### ItemReader (Distributed Map only, optional)

Specifies a dataset and its location for a Distributed Map state. Omit when iterating over JSON data from a previous state.

Sub-fields:

- `Resource` — The S3 API action. Use `arn:aws:states:::s3:getObject` for single files or `arn:aws:states:::s3:listObjectsV2` for listing objects.
- `Arguments` — JSON object specifying `Bucket`, `Key` (for getObject), or `Prefix` (for listObjectsV2). Values accept JSONata expressions.
- `ReaderConfig` — Configuration object with the following sub-fields:
  - `InputType` — Required for most sources. Valid values: `CSV`, `JSON`, `JSONL`, `PARQUET`, `MANIFEST`.
  - `Transformation` — Optional. `NONE` (default) iterates over metadata from ListObjectsV2. `LOAD_AND_FLATTEN` reads and processes the actual data objects, eliminating the need for nested Maps.
  - `ManifestType` — Optional. `ATHENA_DATA` for Athena UNLOAD manifests, `S3_INVENTORY` for S3 inventory reports. When `S3_INVENTORY`, do not specify `InputType`.
  - `CSVDelimiter` — Optional, for CSV/MANIFEST. Valid values: `COMMA` (default), `PIPE`, `SEMICOLON`, `SPACE`, `TAB`.
  - `CSVHeaderLocation` — Optional, for CSV/MANIFEST. `FIRST_ROW` uses the file's first line. `GIVEN` requires a `CSVHeaders` array in the config.
  - `CSVHeaders` — Array of column name strings. Required when `CSVHeaderLocation` is `GIVEN`.
  - `ItemsPointer` — Optional, for JSON files. Uses JSONPointer syntax (e.g., `/data/items`) to select a nested array or object within the file.
  - `MaxItems` — Optional. Limits the number of items processed. Accepts an integer or a JSONata expression evaluating to a positive integer. Maximum: 100,000,000.

S3 buckets must be in the same AWS account and Region as the state machine.

### ItemSelector (optional)

Overrides the values of input items before they are passed to each iteration. Accepts a JSON object with key-value pairs. Values can be static or JSONata expressions. Can access the map state's context object. Available in both Inline and Distributed Map states.

### ItemBatcher (Distributed Map only, optional)

Groups items into batches for processing. Each child workflow execution receives an `Items` array and an optional `BatchInput` object. You must specify at least one of:

- `MaxItemsPerBatch` — Maximum number of items per batch. Accepts an integer or a JSONata expression evaluating to a positive integer.
- `MaxInputBytesPerBatch` — Maximum batch size in bytes (up to 256 KiB). Accepts an integer or a JSONata expression evaluating to a positive integer.
- `BatchInput` — Optional. Fixed JSON merged into each batch. Values accept JSONata expressions.

If both `MaxItemsPerBatch` and `MaxInputBytesPerBatch` are specified, Step Functions reduces the item count to stay within the byte limit.

### ResultWriter (Distributed Map only, optional)

Controls output formatting and optional export of child workflow execution results to S3. The `ResultWriter` field cannot be empty — specify at least one of the following combinations:

- `WriterConfig` only — formats output without exporting to S3.
- `Resource` + `Arguments` only — exports to S3 without additional formatting.
- All three — formats and exports.

Sub-fields:

- `Resource` — `arn:aws:states:::s3:putObject`
- `Arguments` — JSON object with `Bucket` and `Prefix`. Values accept JSONata expressions.
- `WriterConfig` — Configuration object:
  - `Transformation` — `NONE` (includes execution metadata), `COMPACT` (output only, preserves array structure), or `FLATTEN` (output only, flattens nested arrays into one).
  - `OutputType` — `JSON` (array) or `JSONL` (JSON Lines).

When exporting, Step Functions writes `SUCCEEDED_n.json`, `FAILED_n.json`, and `PENDING_n.json` files plus a `manifest.json` to the specified S3 location. Individual result files are capped at 5 GB. The S3 bucket must be in the same account and Region as the state machine.

Without `ResultWriter`, the Map state returns an array of child execution results directly. If the output exceeds 256 KiB, the execution fails with `States.DataLimitExceeded` — use `ResultWriter` to export to S3 instead.

### Distributed Map State Example

```json
"ProcessCSV": {
  "Type": "Map",
  "MaxConcurrency": 100,
  "ToleratedFailurePercentage": 5,
  "ItemReader": {
    "Resource": "arn:aws:states:::s3:getObject",
    "ReaderConfig": {
      "InputType": "CSV",
      "CSVHeaderLocation": "FIRST_ROW"
    },
    "Arguments": {
      "Bucket": "{% $states.input.bucket %}",
      "Key": "{% $states.input.key %}"
    }
  },
  "ItemProcessor": {
    "ProcessorConfig": {
      "Mode": "DISTRIBUTED",
      "ExecutionType": "EXPRESS"
    },
    "StartAt": "ProcessRow",
    "States": {
      "ProcessRow": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Arguments": {
          "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:ProcessRow:$LATEST",
          "Payload": "{% $states.input %}"
        },
        "Output": "{% $states.result.Payload %}",
        "End": true
      }
    }
  },
  "ResultWriter": {
    "Resource": "arn:aws:states:::s3:putObject",
    "Arguments": {
      "Bucket": "{% $states.input.bucket %}",
      "Prefix": "results"
    }
  },
  "Next": "Done"
}
```

---
