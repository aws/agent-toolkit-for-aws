# Temporal Worker Migration — Decision Reference

Single source of truth for Temporal Worker migrations, consumed by the main flow
(discover / clarify / design / generate — temporal workloads ride the unit pipeline). Content here is locked by
`scripts/test_temporal_decision_refs.py` — if you change the Tier 1 rules or
runbook preconditions, update that test in the same commit.

## Framing

Temporal is a durable-execution orchestration system: an open-source (MIT) Server
that stores workflow event history and schedules work, plus **Workers** — user-owned
processes that long-poll the Server and execute Workflow (deterministic
orchestration) and Activity (side-effecting work) code. The Server never sees or
runs user code.

"Migrate Temporal to AWS" is NOT a platform exit. The ask is: find an AWS home for
the Workers (and the work they execute), optionally move Activity-level LLM calls to
Bedrock. **Workflow orchestration code is untouched by design — never propose a
rewrite to Step Functions or AgentCore primitives.**

Key architectural fact: **the polling tier and the execution tier are different
decisions.** A Worker is a long-poll daemon; Workflow code MUST execute inside it
(replay requirement — non-negotiable). But each Activity's function body may either
do the work in-process or delegate it elsewhere.

## Way 1 vs Way 2 (where the Server lives)

**Way 1 (default): Temporal Cloud** via AWS Marketplace + Workers on AWS.
**Way 2: self-hosted Temporal Server on AWS** (EKS + Aurora/RDS) + Workers on AWS.

```
hard compliance signal (sovereignty/regulatory: orchestration
  state must be self-held)                                   → Way 2
very high volume AND user states Cloud-cost concern          → Way 2 (with both-ways comparison)
everything else                                              → Way 1 (default)
```

Before concluding Way 2 on compliance grounds, surface External Payload Storage
(own S3, Preview): payloads staying in the customer's S3 weakens many compliance
arguments for self-hosting the whole server.

Evidence for the Way 1 default: Serverless Workers, self-serve PrivateLink (GA),
and multi-region replication are Cloud-only or Cloud-first features. External
Payload Storage (Preview) is a capability that can weaken compliance arguments
for self-hosting, though it is preview and not Cloud-exclusive.

## Tier 1 — Polling tier (where the Worker daemon lives)

Every rule is decisive (eliminate or direct-pick); no weighted trade-offs, no
scoring script.

### Eliminations

- **Lambda classic**: 15-min cap + freeze model is incompatible with a long-poll
  loop → OUT.
- **AgentCore Runtime**: 8-hour max execution → OUT as Worker host. (Its correct
  role is the execution tier for agent-session Activities — Tier 2.)
- **Lambda MicroVMs**: can run long, but resident-polling cost is strictly worse
  than ECS → OUT.

### Rules (evaluate IN ORDER; first match wins)

```
1. K8s AND low/spiky (the only genuine tension)   → present both EKS and
                                                     Serverless Workers to the user
                                                     (AskUserQuestion), don't auto-pick
2. team already operates K8s                      → EKS
3. low/spiky traffic AND all Activities < 15 min
   AND Way 1 AND accepts Public Preview status    → Lambda Serverless Workers
                                                     (label Public Preview, always)
4. mixed durations                                → OFFER a split (AskUserQuestion):
                                                     split task queues (short →
                                                     Serverless Workers, long → small
                                                     ECS service) vs one plain ECS
                                                     service for everything. The split
                                                     buys scale-to-zero on the short
                                                     side but adds a second deployment
                                                     unit — declining it is legitimate.
5. otherwise                                      → ECS Fargate (default)
```

The tension rule is first so an EKS direct-pick cannot pre-empt it. Rules 1 and 4
are user-choice gates, not direct picks; the OTHER rules are decisive. When the
user declines rule 4's split, the outcome is recorded as "rule 4 offered, user
chose single ECS service" — NOT as falling through to rule 5. Apply the rules
**per task queue** when the inventory shows several.

## Tier 2 — Execution tier (what each Activity delegates to)

Classify each Activity (scan + user confirmation), then map:

| Activity class                                             | Signature                                        | Execution target                                                                                                                                                                                                                                                                                      |
| ---------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Light-IO (single LLM/API call, DB read-write)              | IO-bound, seconds–minutes                        | **in-process** — delegation adds hops for nothing. In-process does NOT waive Temporal hygiene: idempotency, Activity timeout/retry options, cancellation handling, heartbeats for external calls                                                                                                      |
| Agent-session (LLM loop + tools + memory, tens of minutes) | stateful session, isolation, independent scaling | **run `scoring.py`** via the adapter table below (§ Tier 2 adapter — agent-session Activity classes); typical winner AgentCore Runtime (microVMs ≤8h; Instances up to 14d for longer Activities) — DAF pattern; community reference github.com/koukish/async-agent-architecture-sample (not official) |
| Short-tool (convert, scrape, validate)                     | stateless, seconds, spiky                        | **Lambda** (<15 min)                                                                                                                                                                                                                                                                                  |
| Heavy (batch, fine-tune, >15 min, high CPU/GPU)            | long, resource-dense                             | **ECS task / AWS Batch**; GPU → EC2                                                                                                                                                                                                                                                                   |

## Tier 2 adapter — agent-session Activity classes

For agent-session Activities, build the scoring.py input via this adapter (unlisted dimensions stay `"unknown"` — the engine's DEFAULTS apply):

| scoring.py dimension                                    | Fill from Temporal context                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `session_duration`                                      | max expected runtime of this Activity (`under_15min` / `15min_to_8hr` / `over_8hr`)                                                                                                                                                                                                                                                         |
| `traffic_pattern`                                       | Activity start pattern from workflow schedule/volume (`bursty` / `steady` / `idle`)                                                                                                                                                                                                                                                         |
| `launch_concurrency`                                    | expected concurrent Activity starts (`high` / `moderate` / `low`)                                                                                                                                                                                                                                                                           |
| `session_state`                                         | agent loop holds conversation/tool state → `stateful`; waits for human signal → `hitl`                                                                                                                                                                                                                                                      |
| `memory_needs`                                          | memory scoped to one Activity run → `session_only`; persists across runs → `cross_session`. A retried/re-dispatched agent Activity (e.g. re-draft after a rejection signal) counts as a NEW run — stay `session_only` unless the business logic needs memory to carry across executions (shared investigation context, cross-ticket recall) |
| `isolation`                                             | per-session sandbox needed (untrusted code/tools) → `required`                                                                                                                                                                                                                                                                              |
| `framework`                                             | detected agent framework in the Activity body (`strands` / `langgraph` / `crewai` / `custom` / `none`)                                                                                                                                                                                                                                      |
| `platform_fit`                                          | caller is an in-VPC Worker, not a user-facing endpoint → team's existing AWS fit if stated (`ecs` / `eks`), else `none`                                                                                                                                                                                                                     |
| `existing_cluster`                                      | from Tier 1 answer (team's K8s/ECS reality)                                                                                                                                                                                                                                                                                                 |
| `ops_preference`, `multi_agent`, `compute_tier`, others | ask in Step 2 only if load-bearing; otherwise `unknown`                                                                                                                                                                                                                                                                                     |

## Cutover runbooks

### Runbook 1 — Server unchanged: zero downtime for Workflows

Applies when the Server stays where it is (Temporal Cloud, or an untouched
self-hosted cluster) and only Workers move to AWS.

New workers (AWS) join the same namespace + task queues → verify task pickup →
drain old workers. Replay reconstructs in-flight **Workflow** state on new workers;
no pause needed.

**Preconditions (state these explicitly in every generated plan):**

- New workers register the SAME workflow and activity types (compatible code).
- Same task queue names and namespace; mTLS certs / API keys provisioned on the
  AWS side before cutover.
- Old workers shut down GRACEFULLY (finish or heartbeat-cancel running
  Activities). Currently-executing Activities do NOT migrate mid-execution: they
  complete on the old worker, or fail and rely on the Activity retry policy to be
  re-dispatched to a new worker. Verify retry policies + heartbeat timeouts
  before drain.

### Runbook 2 — Self-hosted → Temporal Cloud: drain/dual-run

New executions start on Cloud; old executions finish on the old cluster, then
decommission. **WARN loudly: there is no official cross-cluster history migration
tool.** Detect in-flight long-running workflows during the scan and set
expectations — a workflow with months to run keeps the old cluster alive for
months. Interruptible flows may checkpoint business state and restart on Cloud.

### Runbook 3 — Workflow-determinism-affecting code changes (e.g. Bedrock rewrite)

The replay constraint is broader than Activity signatures: Workflow code must stay
deterministic against recorded history — including Activity type/name and arguments
at already-recorded command points. Options:

- keep changes replay-compatible, OR
- isolate via **Worker Versioning (GA)** or a **new task queue**.

Worker Versioning routes existing executions to compatible Build IDs — it is NOT a
compatibility layer: old Build IDs / old task queues must keep serving workers
until their histories drain.

## Temporal Cloud commercials (for the plan's commercials section)

What this section contains depends on the CURRENT server state, not just the
chosen Way:

**New Temporal Cloud customer** (current state: self-hosted server, chose Way 1)
— the full subscribe flow applies:

- AWS Marketplace SaaS listing `prodview-xx2x66m6fp2lo`; $0.01/action,
  pay-as-you-go; free trial + $1,000 credits; 12+ AWS regions; SCMP contract;
  Vendor Insights available.
- Flow: Marketplace subscribe → account link → create namespace → billing lands on
  the AWS bill (EDP-eligible per agreement).
- Self-serve PrivateLink: GA.

**Already on Temporal Cloud** (current states 2/3/5) — do NOT pitch the
subscribe flow; they already have a namespace and pay for it. Instead:

- Billing and namespace unchanged by this migration — only the workers move.
- Self-serve PrivateLink (GA): connect the new AWS-side workers to the existing
  namespace via a VPC endpoint.
- Optional commercial note: if they currently bill directly with Temporal, the
  AWS Marketplace listing may allow moving billing onto the AWS bill
  (EDP-eligible) — a question for their Temporal account team, not a technical
  migration step. Do not present it as required or guaranteed.

**Way 2** (self-hosted on AWS) — no Cloud commercials at all; the plan carries
the self-host stack (EKS + Aurora/RDS) and its ops cost framing instead.

## Serverless Workers (⚠️ Public Preview — label it, always)

Status: **Public Preview** (docs.temporal.io currently reads "AWS Lambda — Public
Preview", verified 2026-08). Do not trust the docs label at face value — it has
shifted before without a GA announcement (it read "Available" in 2026-07 while the
feature was still pre-release); re-verify at generation time and label the output
Public Preview until GA evidence appears (see freshness.md, Temporal section).

- Mechanism: Temporal Cloud invokes Lambda on task arrival (no persistent poll);
  fresh connection per invocation; Workflows span invocations via replay — a
  3-month workflow becomes hundreds of discrete invocations with zero cost while
  waiting. Activities hard-capped at 15 min.
- Not for: >15-min Activities, persistent-connection features, sustained high
  throughput (resident ECS wins on cost at sustained load).
- Cloud-only (Way 1). Per-SDK/language support matrix: verify at generation time
  (docs currently only confirm a Go guide).

## Replay 2026 feature statuses (cite with labels)

| Feature                              | Status             |
| ------------------------------------ | ------------------ |
| Workflow Streams                     | Preview            |
| External Payload Storage (own S3)    | Preview            |
| Worker Versioning                    | GA                 |
| Task Queue Priority/Fairness         | GA                 |
| OpenAI Agents SDK integration        | GA                 |
| Google ADK integration               | Available          |
| Multi-region/multi-cloud replication | GA (RTO 20 min)    |
| Self-serve PrivateLink               | GA                 |
| AWS AI Competency                    | Agentic AI (badge) |

## If the user asks "why not Step Functions?"

The generated plan does NOT include a Step Functions comparison section. If the
user raises it in conversation, answer briefly from these facts and move on:
first-class signals/HITL vs `waitForTaskToken` plumbing; unlimited execution
duration vs the 1-year Standard cap; workflows as ordinary code with
time-skipping unit tests; SFN per-transition pricing is far cheaper per step
but that is an engine-fee-only comparison — the rewrite cost and capability
loss dominate. Do not volunteer this unprompted.
