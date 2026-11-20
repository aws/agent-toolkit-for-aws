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

## Isolation (Nitro Sandboxes)

Pods on a node share a Linux kernel by default. AWS Nitro Sandboxes gives each opted-in
pod its own Nitro-enforced VM: set `runtimeClassName: isolated-sandbox`, or
`confidential-sandbox` to add attestation and keep pod memory unreadable by the node.

- Requires Kubernetes 1.36 or later and a supported Nitro instance type. Flex instances
  and some of the smallest and metal sizes are excluded.
- EKS Auto Mode includes both runtime classes and provisions capable nodes. You do not
  build an AMI.
- Managed node groups, self-managed node groups, and Karpenter need a sandbox-enabled AMI,
  launched with Nitro Enclaves enabled (`EnclaveOptions.Enabled=true`). A supported instance
  type alone does not advertise sandbox capacity.
- No GPU passthrough: on accelerated instances a sandboxed pod runs CPU work only, so the
  engine gives EKS no Nitro Sandbox credit for `compute_tier: gpu`.
- No charge beyond the instances.
- Isolates workloads, not sessions: per-user session routing is still yours to build.
Source: https://docs.aws.amazon.com/eks/latest/userguide/sandboxing.html
Hands off to the source-platform migration skill (`gcp-to-aws` or `heroku-to-aws`) for compute-layer config.

## Serving & security notes

Entry: container behind Ingress/Service exposing your HTTP/gRPC endpoint. IAM: IRSA for pod-level permissions with `bedrock:InvokeModel` (model-bearing units only — a model-less unit omits it) + service-specific permissions. Networking: in-VPC by nature; Service/Ingress endpoints over TLS; VPC endpoints for AWS services.
