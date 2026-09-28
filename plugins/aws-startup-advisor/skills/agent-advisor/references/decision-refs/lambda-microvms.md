# Lambda MicroVMs — Service Card

## One-liner

Firecracker microVM compute with full process-level suspend/resume, up to
16 vCPU / 32 GB, multi-port / gRPC, near-instant snapshot start. A compute
primitive, not an agent platform.

## Best for

Long interactive sessions with idle periods (suspend preserves memory + processes),
heavy non-GPU compute (>2 vCPU), multi-port / gRPC / per-session URL workloads,
sub-second cold starts.

## Hard limits (verify via MCP — volatile)

- Session cap: 8h (max 28,800s) — same as AgentCore microVMs; AgentCore's
  Instances compute type goes to 14 days, MicroVMs has no equivalent
- Max compute: up to 16 vCPU / 32 GB
- Launch rate: RunMicrovm 5 TPS, NOT adjustable (hard scaling weakness)
- Account memory cap: ~1,024 GB in select regions
- FedRAMP: unknown (verify)

## Lifecycle

Hooks: /ready, /launch, /resume, /suspend, /terminate. Hook failure/timeout terminates the VM.

## Six dimensions

- Identity: bring-your-own (JWE tokens, port-scoped)
- Observability: you instrument (no built-in OTEL)
- Guardrails: bring-your-own
- Scaling: 5 TPS launch (hard cap); memory-bound concurrency
- Tool/Gateway: not an agent platform; pair with AgentCore Gateway if needed
- Protocols: HTTP/2, WebSocket, gRPC, SSE; per-MicroVM URL

## Tradeoffs

Not agent-purpose-built (no /invocations contract, no built-in services). 5 TPS
launch cap is the decisive weakness for high-volume platforms.

## Serving & security notes

Entry: ARM64 handler packaging + lifecycle hooks (/ready, /launch, /resume, /suspend, /terminate); event-source wiring as needed. IAM: execution role with `bedrock:InvokeModel` (model-bearing units only — a model-less unit omits it) + service-specific permissions. Networking: per-MicroVM URL over TLS; public service endpoints OR private connectivity via AWS PrivateLink VPC Endpoints (for MicroVM control-plane API calls and per-MicroVM HTTP endpoint connections), available in all regions where Lambda MicroVMs is available.
