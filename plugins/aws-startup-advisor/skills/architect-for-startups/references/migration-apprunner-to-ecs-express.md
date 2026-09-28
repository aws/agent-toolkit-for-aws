# Migration App Runner to ECS Express — Startup-Specific Guidance

## Why This Matters for Startups

App Runner was the "startup-friendly" compute option. It's closing to new customers April 30, 2026. Existing services keep running, but you need a plan.

## Startup Decision: What to Migrate TO

Don't assume ECS Express Mode is the answer. Choose based on your situation:

| Your Situation                                | Best Target                                                     | Why                                                     |
| --------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------- |
| Simple API, low traffic, want PaaS simplicity | **ECS Express Mode**                                            | Closest to App Runner experience                        |
| Spiky traffic, want $0 at idle                | **Lambda + API Gateway**                                        | If your app fits Lambda constraints (15 min, stateless) |
| Already considering containers seriously      | **ECS Fargate (standard)**                                      | More control than Express Mode, same pricing            |
| Source-code deploy (no Dockerfile)            | **Lambda** (repackage) or **Express Mode** (containerize first) | Express Mode requires container images                  |

### The "Do I Even Need to Migrate?" Question

**Existing App Runner services continue to work.** You only MUST migrate if:

- You need to create NEW services (can't after April 2026)
- You want to consolidate on fewer platforms
- App Runner's scaling model (concurrent requests) doesn't fit your workload

**If your App Runner service is stable and you're not creating new ones, deprioritize this migration.** Focus on product, not infrastructure churn.

## Cost Comparison for Startups

| Scenario              | App Runner               | ECS Express Mode     | Lambda   |
| --------------------- | ------------------------ | -------------------- | -------- |
| Idle (0 req/min)      | ~$5/mo (provisioned min) | $16/mo (ALB minimum) | $0       |
| Light (1 req/sec)     | ~$20/mo                  | ~$30/mo              | ~$3/mo   |
| Moderate (10 req/sec) | ~$50/mo                  | ~$60/mo              | ~$25/mo  |
| Heavy (100 req/sec)   | ~$200/mo                 | ~$180/mo             | ~$200/mo |

**Key insight**: ECS Express Mode is MORE expensive than App Runner at low traffic due to the ALB baseline. If cost matters and traffic is light, Lambda might be the better migration target.

## Startup Quick Migration Path

For non-critical services (dev, staging, internal tools):

1. Extract config: `aws apprunner describe-service --service-arn <arn>`
2. Note: image URI, port, env vars, CPU/memory
3. Create Express Mode service with same config
4. Test the `*.ecs.<region>.on.aws` URL
5. Update DNS or upstream references
6. Keep App Runner as rollback for 48 hours, then delete

**Total time**: 2-4 hours for a simple service.

## Startup-Specific Gotchas

| Gotcha                                      | Impact                                                      | Mitigation                                                       |
| ------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------- |
| ALB is shared across up to 25 services      | Good — amortizes $16/mo baseline across services            | Migrate all App Runner services to one Express Mode ALB          |
| Auto-scaling metric change (requests → CPU) | Bursty traffic may scale differently                        | Monitor for 48h after cutover; adjust `--scaling-target`         |
| No source-code deploy                       | Must containerize if currently deploying from GitHub source | Write a Dockerfile first (budget 1-2 hours)                      |
| IAM roles are more complex                  | App Runner had simpler permissions model                    | Reuse existing roles — don't create new ones unless needed       |
| Health check default differs                | App Runner: TCP. Express Mode: HTTP `/ping`                 | Add a `/ping` endpoint or configure health check path explicitly |

## When to NOT Use Express Mode (Startup Context)

Choose standard ECS Fargate instead if:

- You need fine-grained networking control (specific subnets, custom security groups)
- You want to share an ALB you already manage
- You need sidecar containers (observability agents, proxies)
- You're running >5 services and want central control

Choose Lambda instead if:

- Your app fits Lambda constraints (stateless, <15 min, <10GB memory)
- Traffic is highly variable with long periods of zero requests
- You want $0 baseline cost
- You're willing to handle cold starts (or pay for provisioned concurrency)
