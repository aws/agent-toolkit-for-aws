# Architecture Patterns (JSONata Mode)

## Polling Loop (Wait → Check → Choice)

Some AWS operations and user-defined tasks are asynchronous. The states pattern is: Start Task → initial wait (what is the expected time it takes to complete the task?) → call describe/status API → check result → short wait → loop back.

See `assets/polling-loop-wait-check-choice.asl.json`

> **Security:** Enable server-side encryption on the `FulfillmentQueue` (SSE-SQS or SSE-KMS) and encryption at rest on the `OrdersTable` (KMS).

---

## Compensation / Saga Pattern

Step Functions has no built-in rollback. The saga pattern chains compensating actions in reverse order. Each forward step has a Catch that records which step failed, then routes to the appropriate compensation entry point.

See `assets/compensation-saga-pattern.asl.json`

Compensation chain: `ReserveInventory` fails → `OrderFailed`. `ChargePayment` fails → `ReleaseInventory` → `OrderFailed`. `ShipOrder` fails → `RefundPayment` → `ReleaseInventory` → `OrderFailed`. Each Catch records `$failedStep` and `$errorInfo`. Compensation states use variables from forward steps (`$chargeId`, `$reservedQty`) to know what to undo.

> **Security:** Enable encryption at rest (KMS) on the `InventoryTable` and any DynamoDB tables this workflow touches, since they hold order and inventory data.

---

## Nested Map / Parallel Structures

Map and Parallel states can be nested in any order to create multiple layers. The key constraint is understanding variable scope and data flow at each nesting boundary.

See `assets/nested-map-parallel-structures.asl.json`
See `processing-state-inputs-and-outputs.md` for details about variable scopes

---

## Scatter-Gather with Partial Results

When calling unreliable external APIs per-item, use `ToleratedFailurePercentage` on a Map to continue with whatever succeeded, then post-process the results to separate successes from failures. Failed iterations return objects with `Error` and `Cause` fields.

See `assets/scatter-gather-with-partial-results.asl.json`

Key elements:

- `ToleratedFailurePercentage: 100` lets the Map complete even if every item fails. Lower the threshold to bail out early.
- Filter on `$exists(Error)` to separate failed from successful iterations.
- Guard filtered results with the `$type`/`$exists`/`[]` pattern — JSONata returns a single object (not a 1-element array) when exactly one item matches, and undefined when nothing matches.

> **Security:** Use TLS for the external API calls and store any API credentials in AWS Secrets Manager. Encrypt at rest (KMS) any data store that holds the per-item inputs or results.

---

## Semaphore / Concurrency Lock

Step Functions has no native mutual exclusion. Use DynamoDB conditional writes as a distributed lock when only one execution should process a given resource at a time. Pattern: acquire lock → do work → release lock, with Catch ensuring release on failure.

See `assets/semaphore-concurrency-lock.asl.json`

Key elements:

- `ConditionExpression` with `attribute_not_exists` ensures only one writer wins. The `expiresAt` check provides stale-lock recovery if an execution crashes without releasing.
- `executionId` on the lock item lets `ReleaseLock` conditionally delete only its own lock.
- Retry on `ConditionalCheckFailedException` acts as a spin-wait. Tune `MaxAttempts` and `IntervalSeconds` based on expected hold time.
- Catch on `DoProtectedWork` routes to `ReleaseLock` so the lock is always released. After releasing, `CheckWorkResult` re-raises the error path.
- Set `expiresAt` to a reasonable TTL (here 15 min). Use a DynamoDB TTL attribute to auto-clean expired locks.

> **Security:** The `LocksTable` stores customer identifiers, so enable encryption at rest with a customer-managed KMS key (`aws/dynamodb` or a CMK) for key-rotation control and audit visibility.

---

## Human-in-the-Loop with Timeout Escalation

Chain multiple `.waitForTaskToken` states with `States.Timeout` catches to build escalation: primary approver → manager → auto-reject.

See `assets/human-in-the-loop-with-timeout-escalation.asl.json`

> **Security:** Enable server-side encryption (KMS) on the escalation SNS topic and the approval SQS queue. Escalation notifications should reference an order ID rather than embedding customer PII or financial amounts in the message body; have recipients look up details through an authorized interface. Restrict SNS topic subscriptions to verified, authorized recipients via the topic access policy, and do not subscribe shared or unmonitored endpoints.

---

## Express → Standard Handoff

Express workflows are more cost-effective for high volume State Machine Invocations, but don't support callbacks or long waits. Standard workflows handle those but cost per state transition. Use Express for fast, high-volume ingest and kick off a Standard execution for the long-running tail.

See `assets/express-standard-handoff.asl.json`

> **Security:** Encrypt at rest (KMS) the data stores both workflows read or write (e.g. `CustomersTable`), enable CloudWatch Logs encryption on the Express workflow, and scope each workflow's execution role to least privilege for the cross-workflow `StartExecution` call.
