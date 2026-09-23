# Amazon EKS — Service Card

## One-liner

Kubernetes, full control, portable across clouds, GPU-capable.

## Best for

Existing K8s cluster, platform-engineering team, multi-cloud portability, GPU workloads.

## Hard limits

None that eliminate it for agents (it's the GPU / multi-cloud / full-control winner).

## Six dimensions

- Identity: IRSA / bring-your-own
- Observability: CloudWatch / Prometheus (you configure)
- Guardrails: bring-your-own + Bedrock Guardrails
- Scaling: Spot + Karpenter
- Tool/Gateway: AgentCore services available as add-ons
- Protocols: anything you expose

## Tradeoffs

Highest ops burden; only worth it with existing K8s or GPU/multi-cloud needs.
Hands off to the source-platform migration skill (`gcp-to-aws` or `heroku-to-aws`) for compute-layer config.

## Serving & security notes

Entry: container behind Ingress/Service exposing your HTTP/gRPC endpoint. IAM: IRSA for pod-level permissions with `bedrock:InvokeModel` (model-bearing units only — a model-less unit omits it) + service-specific permissions. Networking: in-VPC by nature; Service/Ingress endpoints over TLS; VPC endpoints for AWS services.
