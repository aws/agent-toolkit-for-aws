# Migrating from JSONPath to JSONata

Complete conversion guide for migrating existing JSONPath state machines to JSONata. Covers fields, states, intrinsic functions, common pitfalls, and the end-to-end conversion workflow.

## JSONPath → JSONata Quick Reference

| JSONPath | JSONata |
|---|---|
| `InputPath` | Not needed — use `$states.input` directly in `Arguments` |
| `Parameters` | `Arguments` |
| `ResultSelector` | `Output` (reference `$states.result`) |
| `ResultPath` | `Assign` (preferred) or `Output` |
| `OutputPath` | `Output` (return only what you need) |
| `TimeoutSecondsPath` | `TimeoutSeconds` with `{% %}` |
| `HeartbeatSecondsPath` | `HeartbeatSeconds` with `{% %}` |
| `ItemsPath` | `Items` with `{% %}` |
| `"key.$": "$.field"` | `"key": "{% $states.input.field %}"` |
| `$` or `$.field` (state input) | `$states.input` or `$states.input.field` |
| `$$` (context object) | `$states.context` |
| `$$.Execution.Input` | `$states.context.Execution.Input` |
| `$$.Task.Token` | `$states.context.Task.Token` |
| `$$.Map.Item.Value` | `$states.context.Map.Item.Value` |
| `$variable` (workflow var) | `$variable` (unchanged) |

---

## Converting Each State Type

### Task State

**Before (JSONPath):**

```json
"ProcessOrder": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "InputPath": "$.order",
  "Parameters": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:Process:$LATEST",
    "Payload": { "id.$": "$.orderId", "customer.$": "$.customerName" }
  },
  "ResultSelector": { "processedId.$": "$.Payload.id", "status.$": "$.Payload.status" },
  "ResultPath": "$.processingResult",
  "OutputPath": "$.processingResult",
  "Next": "Ship"
}
```

**After (JSONata):**

```json
"ProcessOrder": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:Process:$LATEST",
    "Payload": { "id": "{% $states.input.order.orderId %}", "customer": "{% $states.input.order.customerName %}" }
  },
  "Output": { "processedId": "{% $states.result.Payload.id %}", "status": "{% $states.result.Payload.status %}" },
  "Next": "Ship"
}
```

### Pass State

**Before (JSONPath):**

```json
"InjectDefaults": {
  "Type": "Pass",
  "Result": { "region": "us-east-1" },
  "ResultPath": "$.config",
  "Next": "Go"
}
```

**After (JSONata):**

```json
"InjectDefaults": {
  "Type": "Pass",
  "Assign": { "region": "us-east-1" },
  "Next": "Go"
}
```

### Choice State

JSONPath uses `Variable` + typed operators. JSONata uses a single `Condition` expression.

**Before (JSONPath):**

```json
"Choices": [
  { "Variable": "$.status", "StringEquals": "approved", "Next": "Approved" },
  { "And": [
    { "Variable": "$.priority", "StringEquals": "high" },
    { "Variable": "$.age", "NumericLessThanEquals": 30 }
  ], "Next": "FastTrack" },
  { "Not": { "Variable": "$.email", "IsPresent": true }, "Next": "RequestEmail" }
]
```

**After (JSONata):**

```json
"Choices": [
  { "Condition": "{% $states.input.status = 'approved' %}", "Next": "Approved" },
  { "Condition": "{% $states.input.priority = 'high' and $states.input.age <= 30 %}", "Next": "FastTrack" },
  { "Condition": "{% $not($exists($states.input.email)) %}", "Next": "RequestEmail" }
]
```

#### Choice Operator Mapping

| JSONPath Operator | JSONata |
|---|---|
| `StringEquals` / `StringEqualsPath` | `= 'value'` / `= $states.input.other` |
| `NumericGreaterThan` / `NumericLessThanEquals` | `> value` / `<= value` |
| `BooleanEquals` | `= true` / `= false` |
| `TimestampGreaterThan` | `$toMillis(field) > $toMillis('ISO-timestamp')` |
| `IsPresent: true` / `false` | `$exists(field)` / `$not($exists(field))` |
| `IsNull: true` | `field = null` |
| `IsNumeric` / `IsString` / `IsBoolean` | `$type(field) = 'number'` / `'string'` / `'boolean'` |
| `StringMatches` (wildcards) | `$contains(field, /regex/)` |
| `And` / `Or` / `Not` | `and` / `or` / `$not()` |

### Wait State

**Before (JSONPath):**

```json
{ "Type": "Wait", "TimestampPath": "$.deliveryDate", "Next": "Check" }
```

**After (JSONata):**

```json
{ "Type": "Wait", "Timestamp": "{% $states.input.deliveryDate %}", "Next": "Check" }
```

### Map State

| JSONPath | JSONata |
|---|---|
| `ItemsPath` | `Items` (fold `InputPath` into expression) |
| `Parameters` (with `$$.Map.*`) | `ItemSelector` (with `$states.context.Map.*`) |
| `Iterator` | `ItemProcessor` (add `ProcessorConfig`) |
| `ResultSelector` inside iterator | `Output` inside processor states |
| `ResultPath` on Map | `Assign` |

**After (JSONata):**

```json
"ProcessItems": {
  "Type": "Map",
  "Items": "{% $states.input.orderData.items %}",
  "ItemSelector": {
    "item": "{% $states.context.Map.Item.Value %}",
    "index": "{% $states.context.Map.Item.Index %}"
  },
  "MaxConcurrency": 5,
  "ItemProcessor": {
    "ProcessorConfig": { "Mode": "INLINE" },
    "StartAt": "Process",
    "States": {
      "Process": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Arguments": { "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:Process:$LATEST", "Payload": "{% $states.input %}" },
        "Output": "{% $states.result.Payload %}",
        "End": true
      }
    }
  },
  "Assign": { "processedItems": "{% $states.result %}" },
  "Next": "Done"
}
```

---

## Converting Intrinsic Functions

| JSONPath Intrinsic | JSONata Equivalent |
|---|---|
| `States.Format('Order {}', $.id)` | `'Order ' & $states.input.id` |
| `States.StringToJson($.str)` | `$parse($states.input.str)` |
| `States.JsonToString($.obj)` | `$string($states.input.obj)` |
| `States.StringSplit($.str, ',')` | `$split($states.input.str, ',')` |
| `States.Array($.a, $.b)` | `[$states.input.a, $states.input.b]` |
| `States.ArrayPartition($.arr, 2)` | `$partition($states.input.arr, 2)` |
| `States.ArrayContains($.arr, $.v)` | `$states.input.v in $states.input.arr` |
| `States.ArrayRange(0, 10, 2)` | `$range(0, 10, 2)` |
| `States.ArrayGetItem($.arr, 0)` | `$states.input.arr[0]` |
| `States.ArrayLength($.arr)` | `$count($states.input.arr)` |
| `States.ArrayUnique($.arr)` | `$distinct($states.input.arr)` |
| `States.Base64Encode($.str)` | `$base64encode($states.input.str)` |
| `States.Base64Decode($.str)` | `$base64decode($states.input.str)` |
| `States.Hash($.data, 'SHA-256')` | `$hash($states.input.data, 'SHA-256')` |
| `States.JsonMerge($.a, $.b)` | `$merge([$states.input.a, $states.input.b])` |
| `States.MathRandom()` | `$random()` |
| `States.MathAdd($.a, $.b)` | `$states.input.a + $states.input.b` |
| `States.UUID()` | `$uuid()` |

---

## Converting Catch Blocks

JSONPath Catch uses `ResultPath`. JSONata Catch uses `Assign` and `Output` with `$states.errorOutput`.

**Before (JSONPath):**

```json
"Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "HandleError" }]
```

**After (JSONata):**

```json
"Catch": [{
  "ErrorEquals": ["States.ALL"],
  "Assign": { "errorInfo": "{% $states.errorOutput %}" },
  "Output": "{% $states.input %}",
  "Next": "HandleError"
}]
```

Retry syntax is identical between JSONPath and JSONata — no conversion needed.

---

## Conversion Pitfalls and How to Avoid Them

### 1. Do not mix JSONPath and JSONata fields in the same state
Invalid combinations: `Arguments` + `InputPath`, `Output` + `ResultSelector`, `Condition` + `Variable`. Remove all JSONPath fields from converted states.

### 2. You must remove `.$` suffixes

```json
❌  "orderId.$": "{% $states.input.orderId %}"
✓  "orderId": "{% $states.input.orderId %}"
```

### 3. Use `$states` instead of `$` or `$$`.

```json
❌  "{% $.orderId %}"        ❌  "{% $$.Task.Token %}"
✓  "{% $states.input.orderId %}"   ✓  "{% $states.context.Task.Token %}"
```

Note: `$` is valid inside nested filter expressions (e.g., `$states.input.items[$.price > 10]`).

### 4. Do not use double quotes inside JSONata expressions

```json
❌  "{% $states.input.status = "active" %}"
✓  "{% $states.input.status = 'active' %}"
```

### 5. Do not attempt to access the output of `Assign` or `Output` in the same state where they are assigned.
`Assign` and `Output` evaluate in parallel — new variable values are not available until the next state.

```json
❌  "Assign": { "total": "{% $states.result.Payload.total %}" },
    "Output": { "total": "{% $total %}" }
✓  "Assign": { "total": "{% $states.result.Payload.total %}" },
    "Output": { "total": "{% $states.result.Payload.total %}" }
```

### 6. Use defensive coding to prevent undefined errors in JSONata
JSONPath silently returns null. JSONata throws `States.QueryEvaluationError`:

```json
❌  "{% $states.input.customer.middleName %}"
✓  "{% $exists($states.input.customer.middleName) ? $states.input.customer.middleName : '' %}"
```

### 7. Use defensive coding to prevent invalid filter results
JSONata returns a single object (not a 1-element array) when exactly one item matches a filter, and undefined when nothing matches. Both break Map state `Items` and functions like `$count`:

```json
❌  "Items": "{% $states.input.orders[status = 'pending'] %}"
✓  "Items": "{% ( $f := $states.input.orders[status = 'pending']; $type($f) = 'array' ? $f : $exists($f) ? [$f] : [] ) %}"
```

### 8. Iterator → ItemProcessor rename
`Iterator` was renamed to `ItemProcessor` and requires `ProcessorConfig`:

```json
❌  "Iterator": { "StartAt": "...", "States": {...} }
✓  "ItemProcessor": { "ProcessorConfig": { "Mode": "INLINE" }, "StartAt": "...", "States": {...} }
```

---

## Conversion Workflow

For each state being converted, apply these steps in order:

1. Add `"QueryLanguage": "JSONata"` to the state
2. `Parameters` → `Arguments`: remove `.$` suffixes from all keys, wrap values in `{% %}`, replace `$` with `$states.input` and `$$` with `$states.context`
3. Convert `ResultPath` based on its value:
   - Absent or `"$"` → no action needed (default behavior is replaced by `Output`)
   - `null` → add `"Output": "{% $states.input %}"`
   - `"$.field"` → add `"Assign": { "field": "{% $states.result %}" }` and `"Output": "{% $states.input %}"`
4. `ResultSelector` → fold selection logic into `Output` (reference `$states.result`)
5. `OutputPath` → fold into `Output` (return only what you need)
6. Reminder: If the state has `ResultSelector` + `ResultPath` + `OutputPath`, collapse all three into a single `Output` field
7. Remove all five JSONPath I/O fields: `InputPath`, `Parameters`, `ResultSelector`, `ResultPath`, `OutputPath`
8. Convert `*Path` fields to base field + `{% %}` expression (`TimeoutSecondsPath` → `TimeoutSeconds`, `HeartbeatSecondsPath` → `HeartbeatSeconds`, `ItemsPath` → `Items`)
9. Replace `States.*` intrinsic functions with JSONata equivalents (see Converting Intrinsic Functions table)
10. Choice states: replace `Variable` + comparison operators with a single `Condition` expression
11. Map states: `Iterator` → `ItemProcessor` with `ProcessorConfig`, `ItemsPath` → `Items`, `Parameters` with `$$.Map.*` → `ItemSelector` with `$states.context.Map.*`
12. Catch blocks: replace `ResultPath` with `Assign` + `Output` using `$states.errorOutput`
13. Pass states: replace `Result` with `Output` or `Assign`
14. Where multiple consecutive states used `ResultPath` to thread data through the payload, refactor to use `Assign` variables instead — downstream states reference `$variableName` directly
15. Validate the converted state using the TestState API
16. Repeat for all states, then promote `"QueryLanguage": "JSONata"` to the top level and remove per-state declarations
