# Workflow and task selectors

Design coverage is mandatory even when artifact generation for unvalidated semantics is conditionally unsupported. Never defer a Workflow as a generic row and never claim untested Render execution parity.

## Orchestrator

Candidate set: `AWS Lambda durable functions`, `AWS Step Functions Standard`, `AWS Step Functions Express`. Apply first decisive rule:

1. Select Step Functions Standard for long-running or auditable state, callbacks, human approvals, compensation/saga behavior, broad AWS service coordination, or separately modeled state visibility.
2. Select Express only when established high volume plus compatible at-least-once delivery, execution duration, and limited history requirements all fit. Missing volume/delivery/history facts cannot select Express.
3. Select Lambda durable functions for code-centric checkpointed flows whose language/runtime, total duration, state, integration, and Lambda constraints fit and none of rule 1's requirements exists.
4. If evidence establishes neither Standard nor durable-function fit, return the decisive question IDs to Clarify. Do not use Express as a fallback.
5. For a tiny, stateless, short, code-centric reviewed Workflow with no rule-1 requirement, select Lambda durable functions as the startup default and record what would select Standard.

Preserve trigger/schedule, branching, fan-out/fan-in, waits, retries, idempotency, callbacks, approvals, compensation, concurrency, cancellation, state retention, and artifact/state storage.

## Per-task target

Evaluate every task class independently. Candidate set: `AWS Lambda`, `ECS on Fargate task`, `AWS Batch`.

1. Select AWS Batch for array jobs, queued batch scheduling, GPU, specialized compute, or Batch-managed placement/retry requirements.
2. Reject Lambda for duration over 15 minutes, incompatible runtime/package/image, excessive CPU/memory/ephemeral storage, unsupported filesystem/state, or incompatible VPC/cold-start behavior.
3. Select ECS/Fargate for a containerized, long-running, resource-heavy, VPC/filesystem-dependent task that fits Fargate and did not trigger Batch.
4. Select Lambda for short stateless work only when all Lambda constraints are established.
5. Missing duration, runtime, package, resources, network, filesystem, queue, array-job, or GPU facts return to Clarify when they can change the winner.

The Workflow mapping references each task mapping ID. Each mapping emits one `aws_service`; no task target inherits the orchestrator by implication. Record all rejected candidates with the first concrete eliminator or preference reason.
