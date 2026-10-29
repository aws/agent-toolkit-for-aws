# Scaling and Concurrency

## Scaling Basics

Lambda Web provisions environments in response to incoming requests. If no warm
environments have room to serve the request, requests will queue for the next
available environment – either a warm one or a newly provisioned one. The latter
is known as a cold start. Lambda Web attempts to scale up new environments to
keep a headroom and avoid cold starts for small traffic increases. When
environments are underutilized, Lambda Web will scale them down, including
scaling to zero when there's no more traffic.

## Concurrent Execution Environments

Each execution environment handles multiple concurrent requests.

Lambda Web automatically load balances and scales an endpoint's environments by
managing a dynamic per-environment concurrency limit and target utilization.
For example, Lambda Web may not route new requests to an environment with high
sustained CPU utilization; Lambda Web will instead scale out new environments
to handle the load.

**`serviceConfig.maxConcurrencyPerEnvironment`** defines the **upper bound** of
the internally managed dynamic concurrency limit. It is configured on the
revision, defaults to 64, and can be set between 1–128. Most users don't need
to change this field and can rely on Lambda Web's dynamic concurrency limit to
balance environment utilization and performance.

See Multi-Concurrency Considerations in [architecture-patterns.md](references/architecture-patterns.md).

## New Endpoints Start With a Low Concurrency Limit

The dynamic limit starts conservatively on a **new endpoint**, including a new endpoint added to an
existing function, and rises as Lambda learns the function's resource usage. It is kept when the
endpoint scales to zero, so later traffic starts from the learned level. A new revision whose
performance differs a lot from the previous one also goes through a short learning period.

While the limit is low, each environment takes only a few concurrent requests, so a burst needs
more environments than it will later. If `scalingConfig.maxEnvironments` is set low, that burst
hits the cap and gets `429` with `lambda-web-error-type: Platform.EndpointMaxEnvThrottle` until
the limit rises. Left unset, the endpoint scales out instead and the burst is served.

Do not set `maxEnvironments` unless the user asks for a cap. When they do, tell them a low cap on a
new endpoint can throttle bursts and load tests for the first few minutes, and that results from
a first load test are not representative of steady state; repeat the test and use the later runs.

## Endpoint Scaling Controls

There are two controls to limit an endpoint's scale within a region. Both are
endpoint properties and can be updated without creating a new revision:

**`scalingConfig.maxEnvironments`** constrains the number of environments an
endpoint can scale to. Optional, default is null.

- If a request arrives when all `maxEnvironments` environments are fully
  utilized, the request will be immediately throttled rather than queued
  (`429`, `Platform.EndpointMaxEnvThrottle`). On a new endpoint this happens at
  lower load than later, see
  [New Endpoints Start With a Low Concurrency Limit](#new-endpoints-start-with-a-low-concurrency-limit).
- During revision updates, internal fleet cycling, and internally managed
  operational events, Lambda Web may temporarily exceed the `maxEnvironments`
  as Lambda Web generally prioritizes availability over strictly honoring the
  `maxEnvironments`.
- A large `maxEnvironments` value does not guarantee the ability to scale to
  that many environments. An endpoint's environment scaling is always limited
  by the regional vCPU account quota. See Service Limits in
  [SKILL.md](SKILL.md).
- If `maxEnvironments` is configured, an endpoint's total concurrency limit
  can be thought of as `maxEnvironments` × dynamic concurrency limit.

**`throttleConfig.rateLimit`** constrains the endpoint's request arrival rate
to a value lower than account quotas. Optional, default is null.

- An endpoint's request rate is always limited by the two related account
  quotas: Per-endpoint rate limit and account total rate limit. See Service
  Limits in [SKILL.md](SKILL.md).
- A `rateLimit` of 0 blocks all traffic.

## Reference Table

| Name | Configuration scope | Values | Notes |
|---|---|---|---|
| `serviceConfig.maxConcurrencyPerEnvironment` | Revision | Required, default 64, 1–128 | — |
| `scalingConfig.maxEnvironments` | Endpoint | Optional, default null | — |
| `throttleConfig.rateLimit` | Endpoint | Optional, default null; `0` blocks all traffic | — |
| Endpoint RPS limit | Account Quota | 10,000 RPS | See Service Limits in [SKILL.md](SKILL.md) |
| Account RPS limit | Account Quota | 100,000 RPS | See Service Limits in [SKILL.md](SKILL.md) |
| Account vCPU limit | Account Quota | 2,000 vCPUs | See Service Limits in [SKILL.md](SKILL.md) |
