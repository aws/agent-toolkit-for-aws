---
name: aws-lambda-durable-functions
description: Builds resilient, long-running, multi-step applications with AWS Lambda durable functions with automatic state persistence, retry logic, and orchestration for long-running executions. Covers the critical replay model, step operations, wait/callback patterns, error handling with saga pattern, testing with LocalDurableTestRunner. Triggers on phrases like lambda durable functions, durable execution, workflow orchestration, state machines, retry/checkpoint patterns, long-running stateful Lambda functions, saga pattern, human-in-the-loop callbacks, reliable serverless applications, context.step, context.wait, context.invoke, context.runInChildContext, withDurableExecution, DurableContext, durable-execution-sdk, qualified ARN invocation, and durable handler replay.
version: 2
---

# AWS Lambda durable functions

Durable functions are Lambda functions that checkpoint progress and can run multi-step workflows for up to one year, suspending without compute charges during waits and callbacks.

## Use the developer guides for APIs

Do not write SDK method signatures, configuration objects, or IaC properties from memory. Read the relevant page first. The SDK guide covers TypeScript, Python, Java, Go, and C#, and the API names differ between languages.

[AWS Durable Execution SDK Developer Guide](https://docs.aws.amazon.com/durable-execution/):

| Topic | Link |
| --- | --- |
| Key concepts and quickstart | <https://docs.aws.amazon.com/durable-execution/getting-started/key-concepts/> |
| Steps (retries, step semantics) | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/step/> |
| Waits | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/wait/> |
| Wait for condition (polling) | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/wait-for-condition/> |
| Callbacks and wait for callback | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/callback/> |
| Invoke (function chaining) | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/invoke/> |
| Parallel | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/parallel/> |
| Map (concurrency, completion policies) | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/map/> |
| Child contexts | <https://docs.aws.amazon.com/durable-execution/sdk-reference/operations/child-context/> |
| Errors | <https://docs.aws.amazon.com/durable-execution/sdk-reference/error-handling/errors/> |
| Retries | <https://docs.aws.amazon.com/durable-execution/sdk-reference/error-handling/retries/> |
| Serialization | <https://docs.aws.amazon.com/durable-execution/sdk-reference/state/serialization/> |
| Logging | <https://docs.aws.amazon.com/durable-execution/sdk-reference/observability/logging/> |
| Python language guide | <https://docs.aws.amazon.com/durable-execution/sdk-reference/languages/python/> |
| TypeScript language guide | <https://docs.aws.amazon.com/durable-execution/sdk-reference/languages/typescript/> |
| Testing (local and cloud runners) | <https://docs.aws.amazon.com/durable-execution/testing/> |
| Writing tests | <https://docs.aws.amazon.com/durable-execution/testing/authoring/> |
| Test assertions | <https://docs.aws.amazon.com/durable-execution/testing/assertions/> |
| Best practices (determinism, idempotency, state) | <https://docs.aws.amazon.com/durable-execution/patterns/best-practices/> |

[Lambda durable functions guide](https://docs.aws.amazon.com/lambda/latest/dg/durable-functions.html), for the Lambda service side:

| Topic | Link |
| --- | --- |
| Deploying with CloudFormation, AWS CDK, AWS SAM, Terraform | <https://docs.aws.amazon.com/lambda/latest/dg/durable-getting-started-iac.html> |
| Invoking (sync, async, execution names) | <https://docs.aws.amazon.com/lambda/latest/dg/durable-invoking.html> |
| Security and permissions | <https://docs.aws.amazon.com/lambda/latest/dg/durable-security.html> |
| Monitoring and execution history | <https://docs.aws.amazon.com/lambda/latest/dg/durable-monitoring.html> |
| Best practices | <https://docs.aws.amazon.com/lambda/latest/dg/durable-best-practices.html> |
| Supported runtimes | <https://docs.aws.amazon.com/lambda/latest/dg/durable-supported-runtimes.html> |

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) for reading these pages, but it is not required.

## Critical rules: Lambda

1. **Durable execution is enabled only when a function is created.** It cannot be added to an existing function. Create a new function with durable execution (`DurableConfig` in IaC) and move the logic into it.
2. **The handler must be wrapped with the SDK** (`withDurableExecution` in TypeScript, `@durable_execution` in Python). A plain handler deployed to a durable function fails every execution, so when moving existing code, wrap it rather than copying it unchanged.
3. **Invoke with a qualified ARN**: a version, an alias, or `$LATEST` (for example `my-function:live`). An unqualified function name fails.
4. **The execution role needs `AWSLambdaBasicDurableExecutionRolePolicy`.** It grants `lambda:CheckpointDurableExecution`, `lambda:GetDurableExecutionState`, and CloudWatch Logs permissions. Durable invokes also need `lambda:InvokeFunction` on the target. External systems that complete callbacks need `lambda:SendDurableExecutionCallbackSuccess` and `lambda:SendDurableExecutionCallbackFailure`.

## Critical rules: the replay model

Durable functions use checkpoint and replay. After a wait, failure, or resume, the handler re-runs from the beginning. Completed operations return their checkpointed results without re-executing, and code outside operations runs again on every replay.

1. **Code outside steps must be deterministic.** Put timestamps, random values, UUIDs, API calls, and database queries in a step.
2. **Never call durable operations inside a step.** Use a child context to group operations.
3. **Closure mutations inside steps are lost on replay.** Return values from steps instead.
4. **Side effects outside steps repeat on every replay.** Put them in steps. The context logger is replay-aware and safe anywhere.
5. **Don't sleep in the handler.** Use a durable wait or callback, which suspends the execution without compute charges.
6. **For human approval or an external job that can report back, use wait for callback** (`waitForCallback` / `wait_for_callback`). Use wait for condition only when the external system can only be polled.
7. **For sagas, run compensations as named steps, in reverse order, from the catch block** around the forward steps.
8. **Steps default to at-least-once (`AtLeastOncePerRetry`)**, so a crash before the checkpoint re-runs the step. For non-idempotent calls, say so and use `AtMostOncePerRetry` with retries disabled or an idempotency key.
9. **Express map and parallel failure tolerance in the form the user gives it.** A percentage becomes a tolerated failure percentage in the completion config, not a computed count.

When the user asks for code, a test, or a template, show it inline in your answer, even if you also write it to a file. When writing or reviewing durable function code, check it against these rules. When writing tests, name every operation and look operations up by name, not by index.

## Troubleshooting executions

Diagnosis is read-only. Read the execution and its history (`aws lambda get-durable-execution`, `aws lambda get-durable-execution-history`) and report what you find. Never stop an execution or change its state unless the user explicitly asks.

## Security

- Step results and callback payloads are checkpointed. Do not return secrets, credentials, or PII from steps. Store them in Secrets Manager or SSM Parameter Store, retrieve them inside steps, and return references.
- Validate event payloads at the handler entry point, and validate callback payloads, which come from external systems.
- Encrypt the function's CloudWatch Logs log group with KMS, and avoid `DEBUG` logging outside development because it can expose step results.

## When the guides and the SDK disagree

Trust the installed SDK source and tell the user about the discrepancy.
