# Compute selectors

Every procedure is ordered and stops at the first decisive rule. Evidence is source-resource scoped. A missing fact named by a rule returns its question ID to Clarify. Each completed decision records all candidates: one `aws_service` winner and every other candidate in `rejected_candidates` with the first concrete rule that rejected it. AWS App Runner is not a candidate.

## Web and private service management model

Candidate set, in order for recording only: `Elastic Beanstalk`, `Elastic Beanstalk Cluster Mode`, `ECS on Fargate`, `Amazon EKS`. Selection order:

1. If Kubernetes APIs, `kubectl`, arbitrary resources, operators/CRDs, cluster policy, or Kubernetes version/upgrade control is required, select Amazon EKS.
2. If the team wants Beanstalk application/environment lifecycle with service-managed Kubernetes compute and the workload is container-compatible, select Elastic Beanstalk Cluster Mode.
3. If direct task/service control, independent worker topology, custom deployment topology, or rejection of Beanstalk lifecycle is explicit, select ECS on Fargate.
4. If a source-based language or Docker application wants Beanstalk application/environment lifecycle on EC2, select traditional Elastic Beanstalk.
5. If management model is unanswered, return `compute.management_model` to Clarify. Source versus image packaging alone does not decide.

Apply protocol, architecture, storage, privileged-container, host-access, GPU, and regional capability eliminators before management preference. A cluster may narrow candidates but cannot change a deterministic static/data/delivery mapping.

A public HTTP service on Fargate or EKS adds a public ALB. Traditional Beanstalk uses its managed public endpoint when public ingress is required. A private service uses private subnets and Cloud Map or Service Connect by default; add an internal ALB only for established load balancing, health routing, protocol, or multi-client requirements. A private service never gets public ingress merely because a web candidate normally does.

## Background workers

First classify process semantics; unknown semantics returns `worker.execution_shape` to Clarify.

- A continuously supervised queue consumer selects `ECS on Fargate service`. Preserve desired count, concurrency, visibility timeout, restart, graceful shutdown, retries, idempotency, and egress.
- Finite/on-demand/event-driven work evaluates the task selector below and emits one task target, never a pair.

Finite task candidate set: `AWS Lambda`, `ECS on Fargate task`, `AWS Batch`.

1. Select AWS Batch when array jobs, scheduling queues, GPU, specialized compute, large-scale batch placement, or Batch-managed retries are required.
2. Reject Lambda when duration exceeds 15 minutes, package/image/runtime limits do not fit, required filesystem/state does not fit, resource limits do not fit, or VPC/cold-start behavior violates requirements.
3. Select ECS on Fargate task when a container, duration, resources, network, or filesystem eliminates Lambda and Batch rule 1 did not fire.
4. Select AWS Lambda only when duration and all package/runtime/state/resource/network constraints fit.
5. Missing duration or eliminator evidence returns to Clarify; do not default to Lambda.

## Cron jobs

The orchestrator is deterministically EventBridge Scheduler. The selected `aws_service` combines it with exactly one target from `AWS Lambda`, `ECS on Fargate RunTask`, or `AWS Batch`.

1. Select AWS Batch for the Batch eliminators above.
2. Select Lambda only when actual duration is at most 15 minutes and every Lambda compatibility fact is established.
3. Otherwise select ECS RunTask as the startup default, provided container resource and Fargate limits fit.
4. If facts could select Batch or establish/defeat Fargate, return to Clarify.

Preserve schedule, named time zone/DST intent, overlap/concurrency, retries, catch-up, and idempotency. A cron expression is never treated as duration evidence.

## Post-selection sizing

Capacity-preserving size comes from the normalized Render CPU and RAM dimensions independently, desired steady-state count, and the matching sizing knowledge table. Never infer CPU from a memory-heavy plan name. Measured right-sizing is a later Estimate scenario and cannot change the selected service. CPU architecture changes only after dependency/image compatibility is established; otherwise use x86_64 and record the default.
