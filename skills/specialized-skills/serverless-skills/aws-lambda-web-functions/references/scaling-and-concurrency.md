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

See Multi-Concurrency Considerations in [architecture-patterns.md](./architecture-patterns.md).

## Endpoint Scaling Controls

There are two controls to limit an endpoint's scale within a region. Both are
endpoint properties and can be updated without creating a new revision:

**`scalingConfig.maxEnvironments`** constrains the number of environments an
endpoint can scale to. Optional, default is null.

- If a request arrives when all `maxEnvironments` environments are fully
  utilized, the request will be immediately throttled rather than queued.
- During revision updates, internal fleet cycling, and internally managed
  operational events, Lambda Web may temporarily exceed the `maxEnvironments`
  as Lambda Web generally prioritizes availability over strictly honoring the
  `maxEnvironments`.
- A large `maxEnvironments` value does not guarantee the ability to scale to
  that many environments. An endpoint's environment scaling is always limited
  by the regional vCPU account quota. See Service Limits in
  [SKILL.md](../SKILL.md).
- If `maxEnvironments` is configured, an endpoint's total concurrency limit
  can be thought of as `maxEnvironments` × dynamic concurrency limit.

**`throttleConfig.rateLimit`** constrains the endpoint's request arrival rate
to a value lower than account quotas. Optional, default is null.

- An endpoint's request rate is always limited by the two related account
  quotas: Per-endpoint rate limit and account total rate limit. See Service
  Limits in [SKILL.md](../SKILL.md).
- A `rateLimit` of 0 blocks all traffic.

## Reference Table

| Name | Configuration scope | Values | Notes |
|---|---|---|---|
| `serviceConfig.maxConcurrencyPerEnvironment` | Revision | Required, default 64, 1–128 | — |
| `scalingConfig.maxEnvironments` | Endpoint | Optional, default null | — |
| `throttleConfig.rateLimit` | Endpoint | Optional, default null; `0` blocks all traffic | — |
| Endpoint RPS limit | Account Quota | 10,000 RPS | See Service Limits in [SKILL.md](../SKILL.md) |
| Account RPS limit | Account Quota | 100,000 RPS | See Service Limits in [SKILL.md](../SKILL.md) |
| Account vCPU limit | Account Quota | 2,000 vCPUs | See Service Limits in [SKILL.md](../SKILL.md) |
