# Service health and dependency analysis in CloudWatch Omni

How to answer "**is `<service>` healthy**", "**give me a health summary of `<service>`**",
"**what does `<service>` depend on and what role does each dependency play**", and "**which
services call `<service>`**" — grounded in the context graph and confirmed with telemetry,
never from a resource's control plane and never as a bare verdict. (Pure blast radius —
"what breaks if `<datastore>` goes down" — belongs to [context-graph.md](context-graph.md),
which owns upstream/blast-radius traversal; this file uses that traversal only to place a
dependency's role and to confirm a caller's health.)

This file is the *investigation method* that ties three surfaces together. It does not
restate them:

- **Topology** — the dependency map, roles, and direction come from `GetContextGraph`. The
  traversal mechanics, edge semantics, pagination, truncation, and blast-radius/upstream
  walk live in [context-graph.md](context-graph.md); this file uses them and cites the
  roles each edge type assigns.
- **Metrics (RED / USE)** — the exact PromQL, the gauge-vs-counter read, the **per-service
  signal catalog (§5)**, and the empty-series rules are in
  [query/promql-metrics.md](query/promql-metrics.md). Do not duplicate a selector here;
  for a specific resource type (EC2, RDS, Lambda, …) take the resource-specific signals and
  their aggregation from that §5 catalog rather than the generic USE shape below.
- **Failed / slow spans and logs** — the SQL over `traces.default` / `logs.default`,
  `durationNano`, and `status['code']` are in
  [query/sql-logs-traces.md](query/sql-logs-traces.md).
- **Alarm state** — an Omni alert's state (`OK` / `WARNING` / `CRITICAL` / `NODATA`) and
  how to read it with `ListAlerts` / `GetAlert` are in [alerts.md](alerts.md).

---

## Contents

- [Service health & dependency question — facts you MUST surface](#service-health--dependency-question--facts-you-must-surface)
- [Dependency map with roles](#dependency-map-with-roles)
- [Blast radius — who is affected](#blast-radius--who-is-affected)
- [The multi-signal health verdict](#the-multi-signal-health-verdict)
- [Building the checks from the graph](#building-the-checks-from-the-graph)
- [Gotchas](#gotchas)

---

## Service health & dependency question — facts you MUST surface

"Is `<service>` healthy," "health summary of `<service>`," "what does `<service>` depend
on and what role does each play," and "which services call `<service>`" are
**observability-data questions answered from the telemetry surface and the context graph,
not from the resource's control plane**. (A pure "what breaks if `<datastore>` goes down"
blast-radius question is [context-graph.md](context-graph.md)'s.) Answering with the
*methodology* — the graph call, the signals to check, the verdict rubric — is an **output
contract**: surface every item below that applies, **whether or not** you also pull live
numbers and **even if** no matching service exists in the account yet. Presenting a verdict
without a telemetry check, or a dependency list without roles, is the single most common
wrong answer here.

- **Establish topology first, then confirm with telemetry — the graph localizes, queries
  confirm.** Call `GetContextGraph` on the named service (`nodeFilters.name`, `depth: 1`,
  `includeMetadata: true`, a window around the incident) *before* writing any query. Do
  not open with a metric scan of the fleet or a `depth: 3` sweep.
- **A dependency list MUST carry each dependency's ROLE, not just its name.** Derive the
  role from the edge type and direction (next section): a **callee service** (`CALLS`
  from `<service>`), a **datastore** (`ACCESSES` from `<service>` — database, queue,
  cache), the **host / compute it runs on** (`RUNS_ON` from `<service>`), and its
  **callers** (edges whose `to` is `<service>`). "3+ dependencies with correct roles" is
  the bar; a bare list of names is not.
- **A health VERDICT MUST rest on more than one signal, and MUST END with an explicit
  verdict word.** The minimum shape for a service is: its RED signals — request **rate**,
  **error/fault rate** (errors over total, not a raw count), and **latency including a
  p99** (not just an average) — **plus alarm state** (list the service's Omni alerts with
  `ListAlerts` / `GetAlert`) **plus any live failing edge** on the graph; for a resource,
  the USE signals (utilization, saturation, a headroom signal, errors) plus alarm state.
  Then state the verdict **in one of exactly three words — HEALTHY, DEGRADED, or DOWN —**
  with the evidence behind it. A one-signal answer ("CPU is fine, it's healthy"), or a
  description of signals with no explicit verdict word, does not meet the bar.
- **Never give a verdict from no telemetry.** A generic health answer with no metric,
  span, or alarm check is the lowest-scoring answer there is. An empty or zero result is
  a scoping signal (wrong Region/Space, wrong window, wrong label) — never proof of
  health. Never conclude "healthy" from a missing `errorCode`, an absent metric series,
  or an empty node list.
- **RED for services, USE for resources — and take the specific signals from the §5
  catalog.** A request-serving `SERVICE` node gets Rate / Errors / Duration; a `RESOURCE`
  node (database, host, queue, cache) gets Utilization / Saturation / Errors / headroom.
  Pick the shape from the node's `nodeType` / `nodeProperties.category`, then — for a
  specific resource type (EC2, RDS, ELB, …) — take the **resource-specific** signals and
  their aggregation from the [promql-metrics.md](query/promql-metrics.md) **§5 per-service
  catalog**, not the generic USE list: e.g. an EC2 fleet needs `StatusCheckFailed*` read
  with `max` (a 0/1 flag; averaging hides a failure), `CPUCreditBalance` with `min`
  (burstable only), grouped by `InstanceId` — those specifics live in §5, not here.
- **A `REMOTE_SERVICE` node cannot be queried directly.** It is an external dependency
  with no telemetry of its own in this Space, so it gets neither RED nor USE — judge it
  from the **caller-side edge evidence** (an `errorCode` / non-2xx `httpStatusCode` on the
  edge into it, plus the calling service's own spans), per the "a node you cannot query"
  guidance in [context-graph.md](context-graph.md#using-the-graph-in-an-investigation).
- **Build every query from the node's `metadata` selectors, not from the graph's display
  name.** With `includeMetadata: true`, `metadata.metrics[]` gives the metric names and
  the raw `attributes` to match, `metadata.traces[]` / `metadata.logs[]` give the exact
  column→value selectors, and `alternateNames` gives the raw `service.name` values a
  merged node is stored under. Querying by the resolved display name misses a merged
  node's telemetry.
- **Say which direction answers the question.** Cause of `<service>`'s own errors/latency
  → walk **downstream** (its dependencies). Who is affected if `<service>` fails → its
  **callers** (upstream). State this before traversing. For the full transitive
  blast-radius closure, defer to [context-graph.md](context-graph.md), which owns that
  walk; here you only need the immediate callers to place their role and confirm their
  health.
- **Metrics are PromQL, spans/logs are SQL, alarm state is `GetAlert`.** Never reach a
  metric with SQL over a `metrics.default` table (it does not exist), and never read a
  verdict off the resource control plane (`ecs describe-clusters`,
  `dynamodb describe-table`, `ec2 describe-instance-status`).

The dependency-map mechanics, the verdict rubric, and how to assemble the checks are
below.

---

## Dependency map with roles

A dependency map answers "what does `<service>` rely on, and how" — and the *how* is the
role. What is health-specific here is only the **role each edge type assigns**; the
traversal itself (inbound vs outbound edges, pagination, truncation) is
[context-graph.md](context-graph.md)'s — see its "Reading the graph" section. Roles come
straight from the edge type and direction (edges are directed `from` → `to`, and `from`
depends on `to`):

| Role | Edge, relative to `<service>` | Where it comes from |
|---|---|---|
| **Caller** (upstream) | edge whose `to` is `<service>` | the reverse query for inbound edges (`edgeFilters.to`) — a node's own edges never include its callers |
| **Callee service** (downstream) | `CALLS` from `<service>` | `<service>`'s own outbound edges, `edgeType: CALLS` |
| **Datastore** (downstream) | `ACCESSES` from `<service>` | `<service>`'s own outbound edges, `edgeType: ACCESSES` — database, queue, cache |
| **Host / compute** (runs-on) | `RUNS_ON` from `<service>` | `<service>`'s own outbound edges, `edgeType: RUNS_ON` |

Procedure:

1. `GetContextGraph` with `nodeFilters.name = <service>`, `depth: 1`,
   `includeMetadata: true`, and a window around the question's time (or a recent hour if
   none was given).
2. Bucket `<service>`'s outbound edges by `edgeType` into the callee / datastore / runs-on
   roles above, and fetch its callers with the reverse (inbound-edge) query — see
   [context-graph.md](context-graph.md) for the traversal mechanics.
3. Report **each dependency with its role and, where present, its edge evidence**
   (`operations[]`, `errorCode`, `httpStatusCode`, `lastObservedAt`). An edge carrying an
   `errorCode` or a non-2xx `httpStatusCode` is a *proven* failing dependency within the
   window — follow that one first. An edge with no error fields is unreported, **not**
   proven healthy.
4. **Raise `depth` one hop at a time** if the question asks for the transitive set, and
   confirm the health of a suspect dependency with telemetry before expanding further.

Two hops (`depth: 2`) is usually enough to answer "what does it depend on and what role
does each play" for a service and its immediate datastores. Go deeper only along a branch
that shows signal.

---

## Blast radius — who is affected

A pure blast-radius question ("what breaks if `<datastore>` goes down," "who is affected
if `<service>` fails") is owned by [context-graph.md](context-graph.md) — it is the
reverse (upstream) traversal, and the mechanics (inbound-edge query, node-by-node
pagination, silent hub truncation, collect every page) all live there. Use it for that.

What is health-specific — and all you need here — is the read on an affected caller:
**a caller whose edge to the target carries an `errorCode` or a non-2xx `httpStatusCode`
is proven-affected**; a caller with an edge but no error fields is merely dependent, so
confirm its state with the caller's own telemetry before calling it degraded.

---

## The multi-signal health verdict

A verdict rests on several signals, chosen by whether the node is a service or a resource.
The RED/USE shapes below are only the *categories* to cover — they are **not** the
per-resource signal list. For a specific resource type (EC2, RDS, ELB, DynamoDB, …), the
exact metrics, their aggregation, and the identity label to group by come from the
[promql-metrics.md](query/promql-metrics.md) **§5 per-service catalog** — go there and
use its signals rather than the generic USE list here (which would under-cover a resource
type: an EC2 verdict needs `StatusCheckFailed*` with `max`, `CPUCreditBalance` with `min`
on burstable, memory/disk from the CloudWatch agent, grouped by `InstanceId` — §5 names
them, this section does not).

**For a `SERVICE` node — RED:**

- **Rate** — request throughput. From span RED (`traces.span.metrics.calls`, a delta Sum —
  `sum_over_time(...[5m])`, not `rate()`) or Application Signals request count.
- **Errors** — error/fault *rate*, derived as `errors / total` over the same window, never
  a numerator alone. Application Signals `Fault` (5xx + span-status errors) and `Error`
  (4xx), or the span error split on `status['code']`.
- **Duration** — latency including a **p99**, not just an average. From the native
  histogram `traces.span.metrics.duration` via `histogram_quantile(0.99, rate(...[5m]))`,
  Application Signals `Latency`, or span `durationNano` in SQL
  ([sql-logs-traces.md](query/sql-logs-traces.md)).

**For a `RESOURCE` node — USE:**

- **Utilization** — CPU / memory / connections (e.g. `CPUUtilization`,
  `DatabaseConnections`), read as a gauge (`avg` / `max`; on the enriched vended surface a
  delta exponential histogram, so `histogram_avg` / `histogram_quantile`).
- **Saturation** — queue depth, `DiskQueueDepth`, message backlog / age, task counts.
- **Errors** — throttles, `5xx`, status-check failures (read a 0/1 check with `max`, never
  averaged away).
- **Headroom** — a signal that trends toward a limit and is alerted *below* a threshold:
  `FreeStorageSpace`, `FreeableMemory`, `CPUCreditBalance` (burstable only). A balance near
  zero while utilization looks flat is throttling, not health.

**Across both — always add:**

- **Alarm state** — check Omni alerts on the service with `ListAlerts` / `GetAlert`
  ([alerts.md](alerts.md)). A `WARNING` or `CRITICAL` state, or a `contributorSummary`
  count above zero, is direct evidence of a breaching signal; `NODATA` is itself a finding
  (the rule ran and saw nothing), not "healthy". `OK` is one signal, not the verdict.
- **A live failing edge on the graph** — any `errorCode` / non-2xx `httpStatusCode` on an
  edge into or out of the node, with a `lastObservedAt` inside the window.

**State the verdict explicitly:**

| Verdict | Shape of the evidence |
|---|---|
| **HEALTHY** | Error rate at baseline, p99 latency within norms, no saturation/headroom signal near a limit, alarms `OK`, no failing edges in the window — and at least one of these actually queried, not assumed. |
| **DEGRADED** | One or more signals elevated but the service is still serving: raised error rate or latency, a headroom signal trending toward a limit, an alarm at `WARNING`, or a proven failing edge to one dependency while others are clean. Name which signal and the number. |
| **DOWN** | Serving is broken: request rate collapsed to ~0 with errors, alarm `CRITICAL`, or the node/its critical datastore unreachable. Distinguish "the service is the cause" from "a dependency is down and this service is a victim" using the downstream walk. |

Every verdict cites the evidence: the metric and its value, the span/log query, the alarm
state, and the edge. A verdict with no cited signal is the failure this file exists to
prevent.

---

## Building the checks from the graph

The `metadata` block (only with `includeMetadata: true`) is what makes the queries match
what is actually stored, rather than the graph's normalized name:

1. **Metrics** — `metadata.metrics[]` gives each metric `name`, its `preferredStat`, and
   the raw `attributes` (`service.name`, `service.namespace`, `cloud.region`, ...) to use
   as PromQL label matchers. Build the selector per
   [promql-metrics.md](query/promql-metrics.md) — do not guess the metric name from the
   node's display name.
2. **Traces / logs** — `metadata.traces[]` / `metadata.logs[]` are per-signal query
   selectors (OR'ed blocks of AND'ed exact column→value maps). Use them and
   `alternateNames` to write the SQL over `traces.default` / `logs.default` per
   [sql-logs-traces.md](query/sql-logs-traces.md), always with a `` `@timestamp` `` range.
3. **Alarms** — the service name (and its `alternateNames`) is what you match when listing
   its alerts ([alerts.md](alerts.md)).

Read the account and Region for every follow-up query off the node
(`nodeProperties.region`, `nodeProperties.sourceAccountId`) — do not assume they match the
credentials you signed with, because a Space can centralize telemetry forwarded from other
accounts.

---

## Gotchas

- **A verdict without a telemetry check is the top failure.** Health and dependency
  answers that reason from prose alone score lowest. Always query at least one grounded
  signal, and state the verdict from it.
- **A dependency list without roles is incomplete.** The role (callee / datastore /
  runs-on / caller) is the substance of the answer, and it comes from the edge type and
  direction — not from the name.
- **An empty result is a scoping signal, never a verdict.** Empty nodes, zero rows, or an
  absent metric series most often mean the wrong Region/Space, a window that does not
  overlap, or a name/label mismatch (see [context-graph.md](context-graph.md) and
  [promql-metrics.md](query/promql-metrics.md) empty-series tables). Never report
  "healthy" from it.
- **Hub fan-out is silently truncated and pagination is by node** — so a dependency map
  or affected-caller set built from one page can be incomplete. This mechanic (and its fix)
  is in [context-graph.md](context-graph.md); collect every page and raise the per-node
  edge cap (or query the relationship directly) before treating a map as complete.
- **`NODATA` on an alert is a finding, not health.** The rule evaluated and saw nothing —
  investigate why (no telemetry reaching the Space, wrong scope) rather than reading it as
  a pass.
- **Absent is not negative.** An edge with no `errorCode`, a metric with no series, and an
  alert at `OK` each mean "this one signal did not report a problem", not "the service is
  healthy". The verdict comes from the *set* of signals.
- **Do not read health off the control plane.** `ecs describe-clusters`,
  `dynamodb describe-table`, `ec2 describe-instance-status`, and `list-metrics` describe
  configuration, not health. Health is on the telemetry surface.
- **Use `GetContextGraph`, never X-Ray `GetServiceGraph`.** If a too-old **AWS CLI**
  rejects the `cloudwatchomni` command (invalid choice), or **boto3/botocore** raises
  `UnknownServiceError` for the `cloudwatch-omni` service, that is a client-version issue
  (upgrade the CLI/SDK), not a reason to switch products.
