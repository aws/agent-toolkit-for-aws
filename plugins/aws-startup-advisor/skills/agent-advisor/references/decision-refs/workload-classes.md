# Workload-Class Verdicts (non-agent units)

Deterministic verdicts for units whose `workload_class` is NOT `agent_session`.
Agent-class units are scored by `scoring.py`; everything else resolves HERE.
Rules are evaluated IN ORDER — first match wins. Cite the rule id in
`design.json.units[].rationale` (e.g. "W2: batch → AWS Batch").

| #      | When (first match wins)                                                           | Verdict                                                    |
| ------ | --------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **W1** | `system.existing_cluster` is `eks` or `ecs` AND the unit is `service` or `batch`  | `eks` or `ecs` — reuse the team's platform                 |
| **W2** | `batch` with runs > 15 min or GPU/large memory                                    | `batch` — AWS Batch (Fargate compute env; EC2 only if GPU) |
| **W3** | `batch` with short runs (≤ 15 min), scheduled or event-triggered                  | `lambda` — scheduled Lambda (EventBridge Scheduler)        |
| **W4** | `light_io` (webhooks, thin APIs, event handlers) with spiky/scale-to-zero traffic | `lambda` — Lambda                                          |
| **W5** | `light_io` with sustained high traffic                                            | `fargate` — Fargate behind ALB                             |
| **W6** | `service` (long-running server, WebSocket, stateful daemon)                       | `fargate` — Fargate (ECS)                                  |

Hard constraints (checked before the table):

- `batch` is **never AgentCore** — AgentCore sessions are interactive-shaped
  (session-scoped billing and lifecycle; even the Instances compute type frames work
  as sessions with a 14-day ceiling); a batch job on AgentCore pays session premiums
  for nothing that AWS Batch does not do cheaper.
- Anything needing > 15 min per invocation is never plain Lambda (W2 guards this).

These verdicts feed the same consolidation question as scored units (SKILL.md
§ Routing & gates): an ECS/EKS superset can absorb W2–W6 workloads when the user
chooses consolidation; AgentCore cannot.
