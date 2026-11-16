---
_fragment: compute
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify compute requirements

For each web or private service, ask only missing facts that can change the compute winner: desired management model; source/image/build behavior; Kubernetes API, operator, CRD, cluster-policy, or upgrade-control needs; bind protocol and port; scaling; cold-start tolerance; graceful shutdown; architecture compatibility; and storage/network eliminators.

For each background worker, establish whether it is a continuously supervised queue consumer or finite/on-demand/event-driven work. Resolve desired count, concurrency, queue visibility timeout, restart and graceful-shutdown behavior, retries, idempotency, duration, package/runtime/resource limits, filesystem, GPU/specialized compute, VPC access, and outbound dependencies. Continuous consumers route to an ECS/Fargate service. Finite work must have enough evidence to select exactly one of Lambda, ECS/Fargate task, or AWS Batch.

For each cron job, resolve UTC versus named time zone and DST intent, actual execution duration, package/runtime/resources, VPC access, filesystem, overlap/concurrency, retry/catch-up policy, idempotency, and outbound dependencies. A schedule is not runtime evidence. Lambda eligibility requires all Lambda eliminators to be answered; otherwise the documented default is EventBridge Scheduler with ECS RunTask.

For each web service that can select ECS on Fargate, ask `compute.release_strategy` (`canary`, `rolling`, `blue_green`) unless the user already stated it. The documented default is `canary`, recorded as `defaulted` with `default_rule: "release.canary_default"` and the consequence that ECS Express Mode remains eligible. `rolling` and `blue_green` select standard ECS because Express Mode deploys canary only. Never ask it for Beanstalk, EKS, workers, cron, or static sites.
Static sites never receive runtime-capacity questions. Build/runtime version pinning is a delivery question, not a reason to allocate compute to a static site.
