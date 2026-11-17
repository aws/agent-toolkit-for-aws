# Queues in Kinesis Data Streams: migrate an existing consumer

Work through these steps in order. Each depends on answers from the one before, and the fit check in step 2 can end the migration before any code is written.

The questions in bold are suggested wording. Adapt them to the conversation, but keep asking them: they are what stops a migration of a workload that queues can't serve.

## Before you start: resume or start fresh

- **The user mentions an in-progress migration:** ask where their plan or notes are. Read them, find the current step in the Status Summary table, and confirm: **"Based on your plan, here's where we left off: [step and status]. Ready to continue?"** Do not re-ask questions the plan already answers.
- **A plan document exists in the working directory** (for example `queues-migration-plan.md`): read it and offer to resume.
- **Starting fresh:** go to step 1.

## 1. Identify the current consumption method

Ask: **"How are you currently consuming from the stream?"**

- **KCL** - Scheduler or Worker, DynamoDB lease table, `processRecords`.
- **Custom `GetRecords` loop** - manual shard iterator management.
- **Lambda event source mapping** - Lambda can't use a queue as an event source (see [Consume with Lambda](queues-getting-started.md#consume-with-lambda)). Ask: **"Lambda event source mappings don't support queues in Kinesis Data Streams. Keep the current event source mapping on the stream, or move the processing to a consumer that calls `ReceiveQueueRecords`?"** If they keep it, there is nothing to migrate. If they move it, the existing event source mapping can keep running in parallel; decommissioning it is optional and comes later (step 6). If the Lambda documentation lists these queues as an event source, follow it instead.
- **No consumer yet** - this is a new setup, not a migration. Use [queues-getting-started.md](queues-getting-started.md).

## 2. Assess fit (go / no-go)

If the user already stated their requirements (for example, "records are processed independently, no ordering needed"), accept that. Otherwise ask: **"I can assess fit from your code, or from a few quick questions. Which do you prefer?"**

With code, look for ordering dependencies, partition-key grouping, and side effects that would repeat if a record is processed twice. With questions:

- **"Does your workload require strict per-key or per-shard ordering? A queue doesn't necessarily deliver records in the order producers wrote them."**
- **"Does your consumer rely on partition keys to group related records? A queue distributes records across consumers independently of shards."**
- **"Would processing the same record more than once cause a problem, such as a duplicate write or a repeated message? A queue delivers each record at least once, and rarely again after it's acknowledged."**

Any one of these can rule queues out, so get an answer to all three before moving on.

- Any applies to the **whole** workload: stop. Queues are not a fit. See [queues-getting-started.md](queues-getting-started.md#when-to-use-a-queue).
- Any applies to **part** of the workload: ask **"Would you like a hybrid approach - move only the order-insensitive parts to a queue and keep the rest on stream consumers?"**

If duplicates are the only problem, the user can make the processing idempotent first and then continue. That is a change to their processing logic outside this migration, so confirm the user accepts it before continuing. Deduplicate on a unique ID in the record's data if there is one; `RecordId` catches only redeliveries, not producer-retry duplicates (see [queues-getting-started.md](queues-getting-started.md#at-least-once-delivery)).

Even when the code suggests a good fit, confirm: **"Your processing looks stateless, doesn't rely on ordering, and is safe to run more than once on the same record. Does that match your understanding?"**

Check the producer for KPL aggregation ([queues-getting-started.md](queues-getting-started.md#no-record-de-aggregation)). If it's in use, the producer has to turn aggregation off. That is a producer change outside this migration, so confirm the user accepts it before continuing rather than adding it to the list below.

Then present the required changes and ask the user to confirm before continuing:

- Stream in on-demand mode (`UpdateStreamMode`)
- IAM policy changes ([queues-operations-and-iam.md](queues-operations-and-iam.md))
- Client-side filtering, if they relied on filtering elsewhere
- Dead-letter handling: the migrated consumer no longer sees dead-letter records, so decide who inspects, restores, or acknowledges them ([queues-dead-letter-records.md](queues-dead-letter-records.md))
- Room under the stream's registered consumer limit, which enhanced fan-out consumers and queues share ([queues-operations-and-iam.md](queues-operations-and-iam.md#quotas))

## 3. Analyze the existing consumer

If not already shared, ask for the consumer code and any IaC that defines the stream or the consumer. Identify:

- Language, SDK, and IaC tool
- Consumption pattern (KCL, `GetRecords` loop, Lambda handler)
- The per-record processing logic - **preserved verbatim**
- Any use of the record's `SequenceNumber`, for example as a deduplication key. Records received from a queue don't carry it; use `RecordId` instead.
- State management (checkpointing, lease table, Lambda batch window)
- How failed records are handled today (retries, bisect-on-error, on-failure destination), to inform the queue's visibility timeout and dead-letter configuration
- Current IAM policy
- Stream capacity mode

## 4. Confirm strategy and tracking

### 4.1 Strategy

Recommend this order: run the migration in a test environment first, then run the queue consumer alongside the existing consumer in production until validation (step 6) passes, and only then cut over.

Ask: **"Which migration strategy do you prefer?"**

- **Parallel run** (recommended) - both consumers side by side, zero downtime, easy rollback. With several consumers, migrate one at a time. Both consumers receive every record, so every side effect happens twice unless something prevents it. Either deduplicate against a store that both consumers check, or point the queue consumer at a separate output during validation and compare it with the existing consumer's output. Idempotency within each consumer alone is not enough.
- **All-at-once** (not recommended for production) - stop the old consumer, then start the queue consumer. Offer it only if the user accepts downtime during the cutover. Nothing is left running as a fallback: if the queue consumer fails, records wait in the stream until it is fixed or the existing consumer is restarted, and expire if that takes longer than the stream's retention period.

Wait for the user to choose. The strategy decides whether the old consumer gets stopped, so don't assume it.

### 4.2 Plan document

Ask: **"Would you like a migration plan document to track progress across sessions?"** If yes, use [../assets/queues-migration-plan-template.md](../assets/queues-migration-plan-template.md) and ask where to save it.

## 5. Generate the queue consumer (additively)

Generate new files alongside the existing consumer. Never modify, overwrite, or delete existing files; the existing consumer is the rollback path. The one exception is the stream's mode in IaC (5.1).

Work through 5.1-5.5 one step at a time, and have the user review each step's output before starting the next.

**5.1 Infrastructure.** Present and confirm before generating code:

- Stream mode to on-demand with `UpdateStreamMode`, if needed (see [SKILL.md Prerequisites](../SKILL.md#prerequisites)). Weigh cost and scaling before switching from provisioned - see [Choose the right mode to stream in](https://docs.aws.amazon.com/streams/latest/dev/how-do-i-size-a-stream.html).
- Encryption at rest: if `DescribeStreamSummary` shows `EncryptionType` `NONE`, recommend `StartStreamEncryption` before creating the queue, and ask before changing the stream (see [Add a queue consumer to a stream](queues-getting-started.md#add-a-queue-consumer-to-a-stream)).
- Queue creation as a CLI command and in the consumer's language, including the starting position, visibility timeout, and dead-letter configuration. The consumer should call `DescribeQueue` on startup and fail fast if the queue is missing.
- Starting position, which cannot be changed after creation. For a parallel run, `LATEST` is fine because the existing consumer keeps covering the stream. For all-at-once, records written between the old consumer's last checkpoint and the queue's creation would be skipped with `LATEST`. Either create the queue and confirm it is delivering before stopping the old consumer, or use `AT_TIMESTAMP` at or before the last checkpoint and accept some records being processed twice.

**If IaC manages the stream** (step 3), tell the user: **"I can review your existing IaC and update it for the queue: the stream mode and the consumer's IAM policy. The queue itself is created with the CLI or SDK."** Make the other infrastructure changes in the IaC. Follow [Create the queue with infrastructure as code](queues-getting-started.md#create-the-queue-with-infrastructure-as-code) for creating the queue, passing its ARN into the IaC, and the stream mode. For a migration, also:

- The stream mode change is the one edit to an existing file, so confirm it with the user first.
- Add the IAM policy from 5.3 as a new resource, scoped to the queue ARN passed in as a parameter.
- Leave the existing consumer's resources, such as the lease table and IAM policies, unchanged. They are the rollback path.

**If IaC doesn't manage the stream**, recommend IaC for the consumer's IAM policy and deployment, so the same change goes to the test environment and then to production. Follow [Create the queue with infrastructure as code](queues-getting-started.md#create-the-queue-with-infrastructure-as-code) for passing the queue ARN into the IaC. If the user prefers CLI or SDK calls, continue with those.

**5.2 Consumer code.**

- Match the language from step 3.
- Reuse the existing per-record processing logic by importing or calling it. Do not duplicate it: a copy can drift from the original, and the two consumers would then produce different results during validation.
- Do not modify the producer: adding a queue to a stream needs no producer changes. The one exception is KPL aggregation (see step 2).
- Assume the queue already exists (created in 5.1).
- **Lambda consumer:** write it as a `ReceiveQueueRecords` loop, like other consumers (next bullet), and reuse the function's per-record processing logic. If the Lambda documentation lists queues in Kinesis Data Streams as an event source, follow it for the mapping, the event format, and the execution role's permissions instead.
- **Other consumers:** loop `ReceiveQueueRecords` -> process each record -> `AcknowledgeQueueRecords`. Check the `Failed` list.
- If processing can approach the visibility timeout, extend it with `UpdateQueueRecordsVisibility`.
- Do not acknowledge records that failed processing; let them redeliver and, after `MaxReceiveCount`, be put into the dead-letter state.

**5.3 IAM policy.** Use the consumer policy from [queues-operations-and-iam.md](queues-operations-and-iam.md) for the migrated consumer, as a separate JSON document (or a new IaC resource, see 5.1). The setup/operator policy is only for the principal that creates the stream and queue. Do not remove existing permissions; the old consumer is still the rollback path.

**5.4 Cutover and rollback plan.** Write it to the plan document if one exists; otherwise present it:

- Validation criteria (what "healthy" means for this workload)
- Cutover steps
- Rollback path (re-enable the existing consumer; keep its state stores until validation completes). Rollback does not return the stream to provisioned mode. A stream with queues cannot be switched back, so delete its queues first if it needs to return to provisioned.

**5.5 Checkpoint.** Generating the artifacts does not finish the migration. It isn't done until the new consumer is validated, and stopping here leaves two consumers running with no decision about cutover. Mark "Code Generation" complete in the plan document, then ask: **"All migration artifacts are generated. Continue to validation now, or stop here and resume later?"**

## 6. Validate

For a parallel run, run both consumers side by side. For all-at-once, validate the queue consumer on its own. Ask: **"What does healthy look like for your workload - throughput, latency, error rate?"** Use the answer as pass/fail criteria.

Verify:

- The queue consumer meets the user's criteria (see the CloudWatch metrics in [queues-operations-and-iam.md](queues-operations-and-iam.md))
- `AcknowledgeQueueRecords` returns no persistent `Failed` entries
- Records are not accumulating in the dead-letter state unexpectedly
- The same business outcomes as the existing consumer (same downstream writes and side effects; compare the separate output if the queue consumer writes to one, see 4.1)

If any check fails, report which one, observed versus expected values, and do not decommission.

Size the queue consumer fleet on `VisibleQueueRecords`, the number of records waiting to be received: add consumer instances while it keeps growing, and remove them while it stays near 0. Instances are not tied to shards, so the count can change at any time.

After all checks pass, ask: **"Validation looks good. Decommission the existing consumer, or keep running in parallel longer?"** Do not delete the KCL lease table, event source mapping, or other state until validation passes; they are the rollback path.

## Error handling

| Step | On failure |
|---|---|
| Stream not on-demand | Offer `UpdateStreamMode` (see 5.1). |
| Fit check fails | Stop: queues are not a fit. Suggest a hybrid if only part fits. |
| Code generation | Check operation behavior in [queues-operations-and-iam.md](queues-operations-and-iam.md). |
| Validation fails | Do not cut over. Report what diverged. Keep the existing consumer running. |
