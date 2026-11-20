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
A service's runtime is its effective runtime from `design-refs/compute.md`: the service's own `config.runtime` (Blueprint) or `config.serviceDetails.runtime` (live capture) when present, otherwise the runtime of the Build Source it links to through `service_uses_build_source` (`config.git.runtime`, or `docker` for an `image` Build Source). A service declared with `buildSource` never carries `runtime` itself. For each web service or background worker that can select traditional Elastic Beanstalk and has no effective runtime (its Build Source came from a live capture, which records no runtime), ask `compute.runtime_family` (`resource_id` the service; one of `node`, `python`, `ruby`, `go`, `docker`), recorded as `answered` with `provenance: "user"`; never infer it from the repository name, build command or start command.

For each web service or background worker whose effective runtime is `node`, `python` or `ruby` that can select traditional Elastic Beanstalk, ask `compute.runtime_version` (`resource_id` the service): the language major version the service runs, as the Elastic Beanstalk platform branch names it (`22` for Node.js, `3.12` for Python, `3.3` for Ruby). The inventory gives only the family and Clarify reads no application files, so this row is always asked and recorded as `answered` with `provenance: "user"`; point the user at where their source pins it (`package.json` `engines.node`, `.nvmrc` or `.node-version`, `.python-version` or `runtime.txt`, `pyproject.toml` `requires-python`, `.ruby-version`). When the user does not know, record `value: null` as `answered` with the consequence that Generate names the lowest supported branch of the family and warns. Never invent a version. Services whose platform name carries no language version (`docker`, services deployed from an `image`, and `go`) record this row as `not_applicable`; a service whose Build Source is an `image` is one of them.

Static sites never receive runtime-capacity questions. Build/runtime version pinning is a delivery question, not a reason to allocate compute to a static site.
