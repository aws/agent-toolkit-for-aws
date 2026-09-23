# AWS Batch (Fargate) — Service Card

## One-liner

Managed batch job execution, scale-to-zero between runs, no always-on compute.

## Best for

Scheduled or event-triggered batch work (`batch` workload class, W2): long-running jobs
(> 15 min), large fan-out over a work list, latency-tolerant processing that idles between
runs.

## Hard limits

Not for interactive/synchronous request-response (no long-lived endpoint). Jobs run to
completion and exit — there is no persistent server to receive traffic.

## Six dimensions

> The Bedrock-related items below describe a job that CALLS a model. A **model-less** batch job
> (`model_recommendation: null` — a plain compute/data job) omits `bedrock:InvokeModel`, Bedrock
> Guardrails, and the direct-Bedrock-call line; keep only its service-specific permissions (e.g.
> S3). Design/Generate strip the Bedrock items for such a unit (see design.md model-less rule).

- Identity: IAM — job execution role + job role with `bedrock:InvokeModel` (model-bearing jobs only) + service-specific permissions
- Observability: CloudWatch Logs per job; job state via the Batch console/API
- Guardrails: bring-your-own + Bedrock Guardrails (when the job calls a model)
- Scaling: managed compute environment scales to zero between jobs; pay per job-second
- Tool/Gateway: not applicable (no agent runtime); a model-bearing job calls Bedrock directly
- Protocols: none exposed — jobs are submitted, not served

## Tradeoffs

No inbound endpoint, so unsuitable for request-driven work; cold start per job (compute
environment spins up). Wins on cost for spiky/scheduled batch because idle cost is zero.
Hands off to the source-platform migration skill (`gcp-to-aws` or `heroku-to-aws`) for compute-layer config.

## Serving & security notes

Entry: no served endpoint — jobs are SUBMITTED to a job queue (SubmitJob), run on a Fargate
compute environment, and exit. IAM: job execution role (pull image, write logs) + job role with
service-specific permissions scoped to the job's needs, PLUS `bedrock:InvokeModel` ONLY when the
job actually calls a model (a model-less batch job omits it). Networking: jobs run in the default
VPC's subnets with egress to S3 (and to Bedrock only for a model-calling job) over TLS; no ALB,
no inbound listener; VPC endpoints only if policy demands.
