---
_fragment: workflow
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify Workflow requirements

For each Workflow, resolve whether orchestration is code-centric checkpointing or separately modeled state; total and per-step duration; waits; branching and fan-out/fan-in; callbacks; approvals; audit/history; compensation; broad AWS service coordination; volume and delivery guarantees; retries; idempotency keys; concurrency; trigger/schedule; state retention; and failure/cancellation behavior.

For every task class, independently resolve runtime/package, duration, memory/CPU, container requirement, VPC/filesystem access, queue behavior, array-job or GPU/specialized-compute needs, side effects, retries, and idempotency. These facts must select exactly one task target: Lambda, ECS/Fargate task, or AWS Batch.

Do not infer live Render parity from documented source or an unexecuted fixture. Missing orchestration or task eliminators return to Clarify. Conditional unsupported artifact generation does not permit Design to defer the Workflow decision.
