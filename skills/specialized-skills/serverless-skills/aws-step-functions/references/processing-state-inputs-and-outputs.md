# Processing State Inputs and Outputs

## State Fields Quick Reference

| Field | Purpose | Available In |
|-------|---------|-------------|
| `Type` | State type identifier | Task, Parallel, Map, Pass, Wait, Choice, Succeed, Fail |
| `Comment` | Human-readable description | Task, Parallel, Map, Pass, Wait, Choice, Succeed, Fail |
| `Output` | Transform state output | Task, Parallel, Map, Pass, Wait, Choice, Succeed |
| `Assign` | Store workflow variables | Task, Parallel, Map, Pass, Wait, Choice |
| `Next` / `End` | Transition control | Task, Parallel, Map, Pass, Wait |
| `Arguments` | Input to task/branches | Task, Parallel |
| `Retry` & `Catch` | Error handling | Task, Parallel, Map |
| `Items` | a JSON array, a JSON object, or a JSONata expression | Map |
| `ItemSelector` | Reshape each item before processing | Map |
| `Condition` | Boolean branching | Choice (inside rules) |
| `Error` & `Cause` | Error name and description (accept JSONata) | Fail |

## The `$states` Reserved Variable

Step Functions provides a reserved `$states` variable in every JSONata state:

```
$states = {
  "input":       // Original input to the state
  "result":      // Task/Parallel/Map result (if successful)
  "errorOutput": // Error Output (only available in Catch)
  "context":     // Context object (execution metadata)
}
```

### Context Object Fields

| Path | Type | Description |
|------|------|-------------|
| `$states.context.Execution.Id` | String | Execution ARN |
| `$states.context.Execution.Input` | Object | Original workflow input |
| `$states.context.Execution.Name` | String | Execution name |
| `$states.context.Execution.RoleArn` | String | IAM execution role |
| `$states.context.Execution.StartTime` | String (ISO 8601) | When execution started |
| `$states.context.Execution.RedriveCount` | Number | Number of times execution was redriven |
| `$states.context.Execution.RedriveTime` | String (ISO 8601) | When execution was last redriven |
| `$states.context.State.EnteredTime` | String (ISO 8601) | When current state was entered |
| `$states.context.State.Name` | String | Current state name |
| `$states.context.State.RetryCount` | Number | Number of retries attempted |
| `$states.context.StateMachine.Id` | String | State machine ARN |
| `$states.context.StateMachine.Name` | String | State machine name |
| `$states.context.Task.Token` | String | Task token (only in `.waitForTaskToken` states) |
| `$states.context.Map.Item.Index` | Number | Index number for the array item that is being currently processed |
| `$states.context.Map.Item.Value` | any | Current item being processed |
| `$states.context.Map.Item.Key` | String | Property name when iterating over a JSON object (not valid for arrays) |
| `$states.context.Map.Item.Source` | String | Item source: `STATE_DATA` for state input, `S3://bucket-name` for S3 LIST_OBJECTS_V2 with NONE transformation, or `S3://bucket-name/object-key` for all other S3 input types |

---

## Workflow Variables with `Assign`

Variables let you store data in one state and reference it in any subsequent state without threading data through Output/Input chains.

### Declaring Variables

```json
"StoreData": {
  "Type": "Pass",
  "Assign": {
    "productName": "product1",
    "count": 42,
    "available": true,
    "config": "{% $states.input.configuration %}"
  },
  "Next": "UseData"
}
```

### Referencing Variables

Prepend the variable name with `$`:

```json
"Arguments": {
  "product": "{% $productName %}",
  "quantity": "{% $count %}"
}
```

### Assigning from Task Results

```json
"FetchPrice": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:GetPrice:$LATEST",
    "Payload": {
      "product": "{% $states.input.product %}"
    }
  },
  "Assign": {
    "currentPrice": "{% $states.result.Payload.price %}"
  },
  "Output": "{% $states.result.Payload %}",
  "Next": "CheckPrice"
}
```

### Assign in Choice Rules and Catch

Choice Rules and Catch blocks can each have their own `Assign`:

```json
"CheckValue": {
  "Type": "Choice",
  "Choices": [
    {
      "Condition": "{% $states.input.value > 100 %}",
      "Assign": {
        "tier": "premium"
      },
      "Next": "PremiumPath"
    }
  ],
  "Default": "StandardPath",
  "Assign": {
    "tier": "standard"
  }
}
```

If a Choice Rule matches, its `Assign` is used. If no rule matches, the state-level `Assign` is used.

---

## Variable Evaluation Order

All expressions in `Assign` and `Output` are evaluated in parallel using variable values as they were on state entry. New values only take effect in the next state.

```json
"SwapExample": {
  "Type": "Pass",
  "Assign": {
    "x": "{% $y %}",
    "y": "{% $x %}"
  },
  "Next": "AfterSwap"
}
```

If `$x = 3` and `$y = 6` on entry, after this state: `$x = 6`, `$y = 3`. This works because all expressions are evaluated first, then assignments are made.

You cannot assign to a sub-path of a variable:

- Valid: `"Assign": {"x": 42}`
- Invalid: `"Assign": {"x.y": 42}` or `"Assign": {"x[2]": 42}`

---

## Variable Scope

Variables exist in a state-machine-local scope:

- **Outer scope**: All states in the top-level `States` field.
- **Inner scope**: States inside a Parallel branch or Map iteration.

### Scope Rules

1. Inner scopes can READ variables from outer scopes.
2. Inner scopes CANNOT ASSIGN to variables that exist in an outer scope.
3. Variable names must be unique across outer and inner scopes (no shadowing).
4. Variables in different Parallel branches or Map iterations are isolated from each other.
5. When a Parallel branch or Map iteration completes, its variables go out of scope.
6. Exception: Distributed Map states cannot reference variables in outer scopes.

### Passing Data Out of Inner Scopes

Use `Output` on terminal states within branches/iterations to return data to the outer scope:

```json
"ParallelWork": {
  "Type": "Parallel",
  "Branches": [
    {
      "StartAt": "BranchA",
      "States": {
        "BranchA": {
          "Type": "Task",
          "Resource": "...",
          "Output": "{% $states.result.Payload %}",
          "End": true
        }
      }
    }
  ],
  "Assign": {
    "branchAResult": "{% $states.result[0] %}"
  },
  "Next": "Continue"
}
```

### Catch Assign and Outer Scope

A Catch block in a Parallel or Map state can assign values to variables in the outer scope (the scope where the Parallel/Map state exists):

```json
"Catch": [
  {
    "ErrorEquals": ["States.ALL"],
    "Assign": {
      "errorOccurred": true,
      "errorDetails": "{% $states.errorOutput %}"
    },
    "Next": "HandleError"
  }
]
```

---

## Arguments and Output Fields

### Arguments

Provides input to Task and Parallel states:

```json
"Arguments": {
  "staticField": "hello",
  "dynamicField": "{% $states.input.name %}",
  "computed": "{% $count($states.input.items) %}"
}
```

### Output

Transforms the state output:

```json
"Output": {
  "customerId": "{% $states.input.id %}",
  "result": "{% $states.result.Payload %}",
  "processedAt": "{% $now() %}"
}
```

If `Output` is not provided:

- Task, Parallel, Map: state output = the result
- All other states: state output = the state input

---

## Variable Limits

| Limit | Value |
|-------|-------|
| Max size of a single variable | 256 KiB |
| Max combined size in a single Assign | 256 KiB |
| Max total stored variables per execution | 10 MiB |
| Max variable name length | 80 Unicode characters |

---
