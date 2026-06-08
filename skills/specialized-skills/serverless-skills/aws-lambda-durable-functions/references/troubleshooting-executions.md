# Troubleshooting Executions

**PROACTIVE AGENT**: When users report issues with durable function executions, spawn a specialized troubleshooting agent.

## When to Spawn Troubleshooting Agent

Spawn the agent when users mention:

- "My execution is stuck"
- "Execution failed with ID xyz"
- "Debug execution abc123"
- "Troubleshoot execution"
- "Why is my durable function not completing"
- Provide an execution ID and need diagnosis

## Agent Instructions

When spawning the troubleshooting agent, provide:

```
Diagnose durable function execution issue:
- Durable Execution ARN: <durable-execution-arn>
- Region: <region> (infer from ARN)

CRITICAL SAFETY RULES:
- This is READ-ONLY diagnosis
- NEVER call StopDurableExecution or any termination APIs
- NEVER modify execution state
- Only suggest manual remediation if user explicitly requests it

Steps:
0. If the user provides a function name + alias (e.g., my-function:live) instead of a full ARN:
   - Resolve the alias to a version: aws lambda get-alias --function-name <functionName> --name <alias> --region <region> --query 'FunctionVersion' --output text
   - List executions for that function: aws lambda list-durable-executions-by-function --function-name <functionName>:<version> --region <region>
   - Ask the user to identify the execution, or use the most recent one.

1. Fetch the execution history directly:
   Run: aws lambda get-durable-execution-history --durable-execution-arn <durable-execution-arn> --region <region> --include-execution-data
   Note: execution data may contain sensitive information (PII, credentials, business data). Do not display raw step results to users without reviewing content first.

2. If the command succeeds, analyze and provide a user-friendly diagnosis:
   a. Report the execution status (RUNNING/SUCCEEDED/FAILED/STOPPED/TIMED_OUT)
   b. Identify the root cause by looking for these key events in the history:

      **Execution-level failures:**
      - `ExecutionFailed` — entire execution crashed; extract the error and cause fields
      - `ExecutionTimedOut` — the execution exceeded its configured timeout
      - `ExecutionStopped` — execution was manually stopped via StopDurableExecution

      **Context and step failures:**
      - `ContextFailed` — a child context threw an unhandled error; check the parent context for what triggered it
      - `StepFailed` — an individual step failed; includes RetryDetails (CurrentAttempt, NextAttemptDelaySeconds) showing retry state

      **Callback issues:**
      - `CallbackStarted` with a Timeout field — confirms a timeout was registered; correlate with any subsequent `CallbackTimedOut`
      - `CallbackTimedOut` — a timeout fired but may not have been caught by the function code
      - `CallbackFailed` — the callback was resolved with an error

      **Chained invocation failures:**
      - `ChainedInvokeFailed` — a chained (child) durable execution failed
      - `ChainedInvokeTimedOut` — a chained execution exceeded its timeout
      - `ChainedInvokeStopped` — a chained execution was stopped

      **Other signals:**
      - `WaitCancelled` — a scheduled wait was cancelled before completing
      - `InvocationCompleted` with an Error field — the Lambda invocation itself errored (e.g., runtime crash)

      **Diagnosis patterns:**
      - Failed operations: Show the EXACT error message verbatim in a code block
      - Stuck in WAIT_FOR_CALLBACK: Extract callback ID, show how long it's been waiting
      - Timeout: Show which operation was running when timeout occurred
      - Unexpected behavior: Compare operation order with expected flow
   c. Calculate operation durations and timeline
   d. Provide a clear, plain-language explanation of what went wrong and why

3. If the command fails:
   - Execution not found: Tell the user the execution ID may be incorrect or the execution may have been purged. Ask them to verify the ARN.
   - Permissions/network error: check that your caller identity has lambda:GetDurableExecutionHistory on the function ARN.
   - In either case, direct them to the console as a fallback (see step 4)

4. ALWAYS provide a direct link to the Execution Details page in the Lambda console.
   Parse the ARN (arn:<partition>:lambda:<region>:<accountId>:function:<functionName>:<functionVersion>/durable-execution/<executionName>/<invocationId>)
   to extract region, functionName, functionVersion, executionName, and invocationId, then construct:
   https://<region>.console.aws.amazon.com/lambda/home?region=<region>#/functions/<functionName>/versions/<functionVersion>/executions/<executionName>/<invocationId>

   Frame it as: "**[View this execution in the console](<url>)**"

5. Provide specific, actionable next steps based on the diagnosis.

6. If unable to determine the root cause from execution history:
   - Provide the console link (step 4)
   - Offer to fetch the log group and pull relevant logs:
     a. Get the log group:
        aws lambda get-function-configuration --function-name <functionName>:<functionVersion> --region <region> --query 'LoggingConfig.LogGroup'
     b. Query logs filtered by invocation ID (parsed from the ARN):
        aws logs filter-log-events --log-group-name <logGroup> --region <region> --filter-pattern '"<invocationId>"'
     c. If the function uses SDK structured logging (context.logger), query for step-level logs.
        Use execution start time from step 2 as start-time, and execution end time (or current time if still running) as end-time:
        QUERY_ID=$(aws logs start-query --log-group-name <logGroup> --region <region> \
          --start-time <startEpoch> --end-time <endEpoch> \
          --query-string 'fields @timestamp, @message | filter executionName = "<executionName>" | sort @timestamp asc' \
          --query 'queryId' --output text)
        Then poll for results:
        aws logs get-query-results --query-id $QUERY_ID --region <region>
   - If unable to determine the log group, ask the user to check the function's logs

OUTPUT FORMAT:
- Lead with a short summary: "Your execution [status] because [reason]."
- Show the error message verbatim in a code block if one exists.
- Explain what this means in plain language.
- Provide the console link for visual debugging.
- List recommended next steps.

Use jq for JSON parsing if available, otherwise use --query (AWS CLI built-in JMESPath) or python -m json.tool.
```

## Example Usage

```
User: "My durable function execution abc-123 is stuck on my-function:live in us-west-2"

Agent: [Runs get-durable-execution-history command]
Agent: [Analyzes with jq queries]

Claude: Your execution is **waiting for an external callback** that hasn't arrived yet.

        The operation `wait-for-approval` has been pending since 2026-02-14 (3 days).
        It will time out in 12 hours if no callback is received.

        Callback ID: `xyz789`

        **[View this execution in the console](https://us-west-2.console.aws.amazon.com/lambda/home?region=us-west-2#/functions/my-function/versions/3/executions/abc-123/inv-456)**
        ```
        https://us-west-2.console.aws.amazon.com/lambda/home?region=us-west-2#/functions/my-function/versions/3/executions/abc-123/inv-456
        ```

        **Next steps:**
        1. Check if the approval email was sent to the recipient
        2. Verify the callback ID `xyz789` was included in the email
        3. If you'd like me to help send the callback manually, let me know
```

```
User: "Execution def-456 failed on order-processor:live in us-east-1"

Agent: [Runs get-durable-execution-history command]
Agent: [Analyzes with jq queries]

Claude: Your execution **failed** at the `charge-payment` step after 3 retry attempts.

        Error message:
        ```
        PaymentGatewayError: Card declined - insufficient funds (code: card_declined)
        ```

        This means the payment provider rejected the charge. The durable function
        retried 3 times with exponential backoff but the error persisted because
        it's a permanent failure (not a transient network issue).

        **[View this execution in the console](https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/order-processor/versions/5/executions/def-456/inv-789)**
        ```
        https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions/order-processor/versions/5/executions/def-456/inv-789
        ```

        **Next steps:**
        1. This is a business logic failure, not an infrastructure issue
        2. Consider adding a non-retryable error classification for `card_declined`
        3. Implement a compensation step to release the reserved inventory
```
