# Service Integrations in JSONata Mode

## Integration Types

Step Functions can integrate with AWS services in three patterns:

1. **Optimized integrations** — Purpose-built, recommended where available
2. **AWS SDK integrations** — Call any AWS SDK API action directly
3. **HTTP Task** — Call HTTPS APIs (e.g., Stripe, Salesforce)

## Integration Patterns

| Pattern | Resource ARN | Behavior | When to Use |
|---------|-------------|----------|-------------|
| Optimized | `arn:aws:states:::servicename:apiAction` | Call API and continue immediately | Fire-and-forget operations (start a process, send a message) |
| Optimized (sync) | `arn:aws:states:::servicename:apiAction.sync` | Wait for the job to complete | When you need the result before continuing (run ECS task, execute child workflow, run Glue job) |
| Optimized (callback) | `arn:aws:states:::servicename:apiAction.waitForTaskToken` | Pause until a task token is returned | Human approval, external system processing, long-running async operations |
| AWS SDK | `arn:aws:states:::aws-sdk:serviceName:apiAction` | Call any AWS SDK API action directly | When no optimized integration exists for the service |
| HTTP Task | `arn:aws:states:::http:invoke` | Call an HTTPS API endpoint | External APIs (e.g., Stripe, Salesforce) |

> **HTTP Task security:** Store API keys, tokens, and other credentials in AWS Secrets Manager and reference them through an EventBridge connection (`ConnectionArn`). Never embed credentials in the state machine definition or in `Arguments`.

---

## Examples

### Lambda Function

#### Optimized Integration (Recommended)
Always review the AWS Documentation to check availability and proper usage of an optimized integration before using it: https://docs.aws.amazon.com/step-functions/latest/dg/integrate-optimized.html

```json
"InvokeFunction": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:MyFunction:$LATEST",
    "Payload": {
      "orderId": "{% $states.input.orderId %}",
      "customer": "{% $states.input.customer %}"
    }
  },
  "Output": "{% $states.result.Payload %}",
  "Next": "NextState"
}
```

Always include a version qualifier (`:$LATEST`, `:1`, or an alias like `:prod`) on the function ARN.

The result is wrapped in a `Payload` field, so use `$states.result.Payload` to access the Lambda return value.

#### SDK Integration

```json
"InvokeViaSDK": {
  "Type": "Task",
  "Resource": "arn:aws:states:::aws-sdk:lambda:invoke",
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:MyFunction",
    "Payload": "{% $string($states.input) %}"
  },
  "Next": "NextState"
}
```

---

### DynamoDB

#### GetItem

```json
"GetUser": {
  "Type": "Task",
  "Resource": "arn:aws:states:::dynamodb:getItem",
  "Arguments": {
    "TableName": "UsersTable",
    "Key": {
      "userId": {
        "S": "{% $states.input.userId %}"
      }
    }
  },
  "Assign": {
    "user": "{% $states.result.Item %}"
  },
  "Output": "{% $states.result.Item %}",
  "Next": "ProcessUser"
}
```

> **Encryption at rest:** DynamoDB encrypts all tables by default with AWS-owned keys. For sensitive workloads that need key-rotation control, cross-account access, or audit visibility, use an AWS-managed (`aws/dynamodb`) or customer-managed KMS key.

---

### SQS (Simple Queue Service)

#### Send Message

```json
"QueueMessage": {
  "Type": "Task",
  "Resource": "arn:aws:states:::sqs:sendMessage",
  "Arguments": {
    "QueueUrl": "https://sqs.us-east-1.amazonaws.com/123456789012/ProcessingQueue",
    "MessageBody": "{% $string($states.input) %}"
  },
  "Next": "Done"
}
```

> **Encryption:** Enable server-side encryption (SSE-SQS or SSE-KMS) on the queue, even for fire-and-forget messages.

#### Send Message with Wait for Task Token

```json
"WaitForApproval": {
  "Type": "Task",
  "Resource": "arn:aws:states:::sqs:sendMessage.waitForTaskToken",
  "Arguments": {
    "QueueUrl": "https://sqs.us-east-1.amazonaws.com/123456789012/ApprovalQueue",
    "MessageBody": "{% $string({'taskToken': $states.context.Task.Token, 'orderId': $orderId}) %}"
  },
  "TimeoutSeconds": 86400,
  "Next": "ProcessApproval"
}
```

The execution pauses until an external system calls `SendTaskSuccess` or `SendTaskFailure` with the task token.

> **Encryption and sensitive data:** Enable server-side encryption (`KmsMasterKeyId`) on SQS queues and SNS topics used by a workflow. The task token is a sensitive credential, and message bodies may carry order or approval details — avoid placing PII, financial data, or secrets in the body; pass a reference ID and look up details through an authorized channel.

---

### Step Functions (Nested Execution)

#### Start Execution (Synchronous)

```json
"RunSubWorkflow": {
  "Type": "Task",
  "Resource": "arn:aws:states:::states:startExecution.sync:2",
  "Arguments": {
    "StateMachineArn": "arn:aws:states:us-east-1:123456789012:stateMachine:ChildWorkflow",
    "Input": "{% $states.input %}"
  },
  "Output": "{% $parse($states.result.Output) %}",
  "Next": "ProcessSubResult"
}
```

Note: The `.sync:2` suffix waits for completion. The child output is a JSON string in `$states.result.Output`, so use `$parse()` to deserialize it.

#### Start Execution (Async — Fire and Forget)

```json
"StartAsync": {
  "Type": "Task",
  "Resource": "arn:aws:states:::states:startExecution",
  "Arguments": {
    "StateMachineArn": "arn:aws:states:us-east-1:123456789012:stateMachine:AsyncWorkflow",
    "Input": "{% $string($states.input) %}"
  },
  "Next": "Continue"
}
```

---

### Cross-Account Access

Use the `Credentials` field to assume a role in another account:

```json
"CrossAccountCall": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Credentials": {
    "RoleArn": "arn:aws:iam::111122223333:role/CrossAccountRole"
  },
  "Arguments": {
    "FunctionName": "arn:aws:lambda:us-east-1:111122223333:function:RemoteFunction:$LATEST",
    "Payload": "{% $states.input %}"
  },
  "Output": "{% $states.result.Payload %}",
  "Next": "Done"
}
```

> **Restrict role assumption:** In the trust policy of `CrossAccountRole`, include a condition that scopes which state machines may assume it, e.g. `"aws:SourceArn": "arn:aws:states:us-east-1:<account>:stateMachine:<name>"` (or `aws:SourceAccount`), to prevent unintended cross-account assumption.

---

### Callback Pattern

```json
"WaitForHumanApproval": {
  "Type": "Task",
  "Resource": "arn:aws:states:::sqs:sendMessage.waitForTaskToken",
  "Arguments": {
    "QueueUrl": "https://sqs.us-east-1.amazonaws.com/123456789012/ApprovalQueue",
    "MessageBody": "{% $string({'taskToken': $states.context.Task.Token, 'requestId': $states.input.requestId}) %}"
  },
  "TimeoutSeconds": 604800,
  "Catch": [
    {
      "ErrorEquals": ["States.Timeout"],
      "Output": {
        "status": "approval_timeout"
      },
      "Next": "HandleTimeout"
    }
  ],
  "Next": "ApprovalReceived"
}
```

The external system must call `SendTaskSuccess` or `SendTaskFailure` with the task token to resume execution.
