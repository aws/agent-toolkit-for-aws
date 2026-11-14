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

## ECS Fargate mode (Express vs standard)
**ECS Express Mode is the default shape for a public HTTP(S) web service that selected `ECS on Fargate`.** Express Mode is an ECS service AWS provisions for you: Fargate cluster, task definition, Application Load Balancer with an HTTPS listener and ACM certificate, security groups, target-tracking auto scaling, CloudWatch log group, canary deployments, and an AWS-provided HTTPS endpoint, at no charge beyond the resources ([Express Mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html)). It is also AWS's named replacement for App Runner. Up to 25 Express services share one ALB per VPC and scheme. Express Mode derives the ALB scheme from the task subnets ([network defaults](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html#express-service-network-defaults)): public subnets give an internet-facing ALB and public task IPs; private subnets give an internal ALB.
Record the decision on every `ECS on Fargate` mapping (service or task target, not Lambda or Batch) as `aws_config.ecs_mode` (`"express"` or `"standard"`), a one-line `aws_config.ecs_mode_reason`, and, for `express`, `aws_config.placement` (`"public_subnets"` for a public service, `"private_subnets"` for an internal one). Select `"standard"` when any of these holds, evaluated in order; otherwise select `"express"`:

1. The resource is not an HTTP(S) listener: a background worker, cron task, or Workflow task (`ecs_mode_reason: "no_http_listener"`).
2. A private service with Cloud Map or Service Connect discovery and no established ALB requirement (`"private_discovery"`). A private service becomes Express only when this file already selected an internal ALB for it.
3. The service needs TCP/UDP passthrough, gRPC without HTTP/2 termination, an NLB, or no load balancer (`"passthrough"`).
4. The `compute.release_strategy` answer is `rolling` or `blue_green`. Express Mode deploys canary only (`"release_strategy"`).
5. Task size exceeds Express limits: CPU above 4096 units or memory above 8192 MiB (`"task_size"`).
6. A persistent disk is bound to the service, or the task has sidecars. The EFS mount needs a task definition the generator authors, and the Terraform resource does not accept a custom one (`"efs_mount"`).
7. The service has a custom domain. Generated Terraform owns the ALB listener and the customer's validated ACM certificate (`"custom_domain_alb"`).
8. A recorded network-isolation requirement keeps a public service's tasks in private subnets (`"private_tasks"`). Express cannot give a public ALB to private tasks.

Express Mode is a shape of Fargate, not a new service: `aws_service` stays `ECS on Fargate`, and sizing and cost come from the same tables. A design saved without `ecs_mode` is read as `"standard"` by Estimate and Generate. Express does not displace Elastic Beanstalk or EKS when those win the management-model selector. It applies only after Fargate is selected.

## Post-selection sizing

Capacity-preserving size comes from the normalized Render CPU and RAM dimensions independently, desired steady-state count, and the matching sizing knowledge table. Never infer CPU from a memory-heavy plan name. Measured right-sizing is a later Estimate scenario and cannot change the selected service. CPU architecture changes only after dependency/image compatibility is established; otherwise use x86_64 and record the default.
