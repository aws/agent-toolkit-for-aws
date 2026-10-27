# CloudWatch Omni Intelligence — insights, observations, and the context graph

Answers status, troubleshooting, root-cause, and dependency questions from the **insights and
observations** Omni detects and correlates continuously from the CloudWatch dataset — the
surface this reference owns. It leans on two sibling surfaces owned elsewhere and referenced,
not redefined, here: the **context graph** (service/resource topology and blast radius) in
[context-graph.md](context-graph.md), and intelligence **enablement and configuration** in the
`setting-up-cloudwatch-observability` skill's `references/cloudwatch-omni/intelligence-setup.md`.
Starting here instead of scanning raw telemetry reaches an answer in fewer tool calls and
tokens, and cites more of the evidence that matters.

## Scope and neighbours

This reference **composes** the metric, service-health, context-graph, and SQL references
rather than replacing them. Hand the ask back when it is not a cause question: a bare
single-signal metric symptom belongs to
[query/promql-metrics.md](query/promql-metrics.md); a bare "is `<service>` healthy" verdict
or a role-labelled dependency map belongs to [service-health.md](service-health.md); a pure
traversal-direction or edge-semantics question belongs to
[context-graph.md](context-graph.md). Use this file when the question is *what is wrong and
why* — status, triage, root cause, or a past incident.

## Contents

- [Scope and neighbours](#scope-and-neighbours)
- [Operations](#operations)
- [When to use](#when-to-use)
- [Using Omni Intelligence in an investigation](#using-omni-intelligence-in-an-investigation)
- [Data model](#data-model)
- [ListInsights](#listinsights)
- [ListObservations](#listobservations)
- [GetContextGraph](#getcontextgraph)
- [Cost and performance guardrails](#cost-and-performance-guardrails)
- [Gotchas](#gotchas)

## Operations

Three operations answer the questions in this reference, all on the public CloudWatch Omni
SigV4 API (service `cloudwatch-omni`, signing name `cloudwatch`) — reachable from the AWS CLI
(`aws cloudwatchomni …`), boto3, or any SigV4 caller:

| Operation | CLI | What it reads |
|---|---|---|
| `ListInsights` | `aws cloudwatchomni list-insights` | Correlated findings — insights |
| `ListObservations` | `aws cloudwatchomni list-observations` | Anomaly episodes — observations |
| `GetContextGraph` | `aws cloudwatchomni get-context-graph` | Service/resource topology (full API in [context-graph.md](context-graph.md)) |

Observations and insights say **what moved**; the context graph says **how the moving parts
are connected**. Used together they answer most status and root-cause questions faster than
scanning raw telemetry. The CloudWatch Omni **Intelligence console view** presents the same
insights and observations for a human to read; use it as a cross-check, not as a replacement
for the API in an automated investigation.

### When a call fails

The 403 / 404 / local-client-error model is the same for all three operations and is stated
once, in context-graph.md's
[Check permissions to access the Context Graph](context-graph.md#check-permissions-to-access-the-context-graph).
In short: a **403 `AccessDeniedException`** is an authorization result (a missing access grant
or IAM action, or — when the Space has a customer-managed KMS key — a denied
`kms:Decrypt` / `kms:GenerateDataKey` or an encryption context the key policy does not allow; a
merely *disabled* key is not this cause); a **404 `UnknownOperationException`** means the
operation is not available to the account, so the server rejects it as if it did not exist (do
**not** retry or reshape the request); and a local "unknown service" / invalid-choice error is
a too-old AWS CLI or boto3/botocore that fails **locally**, before any request is sent (upgrade
the client). Read the error, not the symptom, and never substitute X-Ray `GetServiceGraph`.

## When to use

Use when the user asks to:

- Check status: "Is anything wrong right now?" / "How is `<service>` doing?" / "Any open issues in my system?"
- Troubleshoot a symptom: "Why is `<service>` slow / erroring?" / "What changed on `<service>` this morning?"
- Find a root cause: "Users saw errors between X and Y — what caused it?" / "Explain this insight"
- Look back: "What happened during last night's incident?" (its insights may be `INACTIVE` now)
- Trace dependencies and impact: "What does `<service>` depend on, and which of those is broken?" / "Who is affected if `<service>` fails?"
- Read Omni's findings directly: insights, observations, anomalies, the context graph, `ListInsights`, `ListObservations`, `GetContextGraph`

## Using Omni Intelligence in an investigation

One way to use the three operations together; adapt it to the question.

1. **Insights: what's going on.** List insights for the window the question needs. `ACTIVE`
   insights cover "now", which is also the place to start when no time is given. For a past
   incident the insight it raised may since have gone `INACTIVE` — the two statuses are
   reversible — so an insight you expect may not be `ACTIVE` in the window; say that you are
   looking at a past incident.
2. **Rank them by relevance** to the problem under investigation, and keep the ones that match.
3. **Dive into their observations.** Resolve a kept insight's `observations[]` with one
   `ListObservations` call using `anomalyIds` — the batch-get, up to 100 ids, mutually
   exclusive with the other filters (see [ListObservations](#listobservations)). Each
   observation names a service, a signal, how it changed, and when; these are the evidence for
   the answer.
4. **Context graph: blast radius and causal chain.** Start from the affected services and
   resources and follow their dependencies, to see which one the others depend on and who is
   impacted.
5. **Answer with the evidence.** Name the root cause and each impacted service, and for each
   one cite the observations behind it: service, signal (metric, log pattern, or operation),
   how it changed, and when.

An insight is a **hypothesis to confirm**, never the final answer on its own: check that its
window actually overlaps the incident, then confirm the candidate on the graph and in
telemetry.

---

## Data model

**Observation**: one anomaly episode detected in a service's telemetry (logs, metrics, or traces).

| Field | Meaning |
|---|---|
| `anomalyId` | Episode id; what an insight's `observations[]` lists |
| `service` | The monitored service the anomaly was detected on |
| `signalType` | `logs` \| `metrics` \| `traces` |
| `anomalyType` | Analyzer classification (a free-form string), for example `latency_spike`, `error_rate_spike`, `frequency_spike`, `rate_drop`, `new_pattern`, `outlier` |
| `title`, `description` | What moved, in words; usually names the metric, log pattern, or operation |
| `details` | Key–value pairs (all values are strings): the signal identity (metric name, statistic, log pattern, operation, dimensions) and analyzer values |
| `severity`, `peakSeverity` | Latest and highest severity in the episode: `info`, `low`, `medium`, `high`, `critical` |
| `firstSeenAt`, `lastSeenAt` | Episode start and latest occurrence |
| `occurrenceCount` | Occurrences merged into the episode |
| `sourceAccountId`, `sourceRegion` | Where the signal was produced (may differ from the owner under centralized monitoring) |
| `evidenceSamples[]` | Up to 100 timestamped samples (`timestamp`, `details`); large |

**Insight**: Omni's correlation of related observations into one explained finding.

| Field | Meaning |
|---|---|
| `insightId` | Id (lowercase alphanumeric) |
| `accountId` | The account the insight belongs to |
| `title`, `summary` | Headline and what was found |
| `reasoning` | How the correlated observations led to the finding; usually says which service or resource is the source and which are affected |
| `severity` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `status` | `ACTIVE` or `INACTIVE`, and the two are **reversible** — an insight transitions between them in both directions, so an `INACTIVE` insight can return to `ACTIVE`. `ACTIVE` means the condition it tracks is currently firing; `INACTIVE` means it is not firing right now. There is no `CLOSED` or `DISCARDED` status |
| `observations[]` | The `anomalyId`s it correlates |
| `affectedNodes[]` | Services and resources involved: `name`, `nodeType` (`SERVICE`, `RESOURCE`, `REMOTE_SERVICE`), `accountId`, `sourceAccountId`, `region`, `cloudProvider`, optional `nodeId` (a context-graph id). `name` is the value to pass in the ListObservations `services` filter |
| `createdAt`, `updatedAt`, `createdBy`, `updatedBy` | Lifecycle timestamps and actors (`createdBy` is the system for generated insights) |

---

## ListInsights

Lists insights, **most recently updated first**. Call it as `aws cloudwatchomni list-insights`,
boto3, or any SigV4 client.

| Input | Meaning |
|---|---|
| `filters.status` | List; any of `ACTIVE`, `INACTIVE`. Without this filter, insights in either status are returned |
| `filters.severity` | List, up to 4 of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `filters.services` | Up to 50 service names; matches insights affecting any of them |
| `filters.timeRange` `{start,end}` | Insights whose lifetime overlaps the range: created at or before `end` and last updated at or after `start` |
| `query` | Free-text search over title, summary, reasoning, and affected service and resource names. Case-insensitive; every whitespace-separated term must match |
| `insightIds` | Batch-get up to 100 ids. Mutually exclusive with `query` and `filters` (ValidationException otherwise); missing or inaccessible ids come back in `unprocessedIds` |
| `maxResults`, `nextToken` | Page size 1–100 (service default 50) and the cursor |

The response returns the insights in `items`, plus `nextToken` and (only when `insightIds` was
set) `unprocessedIds`.

An insight must match every filter you set; within one filter, any listed value matches. For
example, `filters.status: [ACTIVE]` with `filters.severity: [HIGH, CRITICAL]` returns active
insights that are high or critical. The `status`, `severity`, `services`, and `timeRange`
members live **under the `filters` envelope**, not at the top level — only `query`,
`insightIds`, `maxResults`, and `nextToken` are top-level.

A window ranked by severity, as a real request:

```json
{
  "filters": {
    "status": ["ACTIVE"],
    "severity": ["CRITICAL", "HIGH"]
  },
  "maxResults": 50
}
```

Keep the response small by reading only the fields you need to rank and continue (title,
severity, status, times, `affectedNodes[].name`, summary, `observations`), and read
`reasoning` only for the one insight you examine.

## ListObservations

Lists observations (anomaly episodes). Call it as `aws cloudwatchomni list-observations`,
boto3, or any SigV4 client.

| Input | Meaning |
|---|---|
| `timeRange` `{start,end}` | Window to search |
| `services` | Up to 50 service names |
| `signalTypes` | Up to 3 of `logs`, `metrics`, `traces` (lowercase on the wire) |
| `severity` | A single value: `info`, `low`, `medium`, `high`, or `critical` |
| `sourceAccountId` | Restrict to anomalies on signals produced by these accounts |
| `anomalyIds` | Batch-get up to 100 ids, typically an insight's `observations[]`. Mutually exclusive with `timeRange`, `services`, `signalTypes`, `severity`, and `sourceAccountId` (ValidationException otherwise); missing or inaccessible ids come back in `unprocessedIds` |
| `maxResults`, `nextToken` | Page size 1–100 and the cursor |

The response returns the observations in `items`, plus `nextToken` and (only when `anomalyIds`
was set) `unprocessedIds`.

**Getting one insight's observations.** Use the `anomalyIds` batch-get: one call, passing that
insight's `observations[]` (up to 100 ids), returns exactly those observations. `anomalyIds` is
mutually exclusive with the other filters, so send it alone. This is the primary, cheapest path —
one scoped call rather than listing a window and filtering client-side.

Anomalies on given services and signals in a window — a filtered query, with no `anomalyIds`:

```json
{
  "timeRange": {"start": "2026-09-16T00:00:00Z", "end": "2026-09-16T02:00:00Z"},
  "services": ["orders-api", "inventory-service"],
  "signalTypes": ["traces", "logs"],
  "severity": "high"
}
```

A filtered query answers specific questions: "what else moved on the services in this path?",
"did traces change before the logs started erroring?", "is there anything high severity that
no insight covers?".

## GetContextGraph

`GetContextGraph` reads the context graph — which services and resources depend on which — so
you can tell the root cause apart from the services it impacts and see the blast radius. It
holds services (`SERVICE`), resources (`RESOURCE`: a database, queue, cache, host), and remote
services (`REMOTE_SERVICE`: an AWS API or other dependency seen only from the caller), linked by
`CALLS`, `ACCESSES` (reads or writes a datastore), or `RUNS_ON` (hosted on compute) edges. Full
API and traversal rules are in [context-graph.md](context-graph.md); the parts used most with
insights:

- An insight's `affectedNodes[].nodeId` (as `nodeFilters.nodeId`), or a service or resource
  `name` (as `nodeFilters.name`), is the starting point, with `depth` 1 and a window around the
  problem. `startTime` and `endTime` are required.
- Edges point from caller to dependency, and each service or resource carries only its
  outbound `edges[]`; callers are found with `edgeFilters.to`. An edge's `to` is a `nodeId`,
  mapped to a name from the same response.
- An `errorCode` or non-2xx `httpStatusCode` on an edge is an observed failure of that
  dependency; a missing one is unreported, not healthy.
- `includeMetadata` returns the exact metric names and log/trace selectors behind a service or
  resource, for follow-up queries.

AWS CLI example:

```bash
# One service and its direct neighbors. --query keeps only each node's identity and its
# outbound edges (target id, edge type, error code, HTTP status): enough to see what the service
# depends on and which of those calls are failing, without the full graph payload.
aws cloudwatchomni get-context-graph --region <region> \
  --start-time 2026-09-16T00:00:00Z --end-time 2026-09-16T01:00:00Z \
  --node-filters '{"name":"orders-api"}' --depth 1 --no-paginate \
  --query 'nodes[].{id:nodeId,name:name,type:nodeType,
           out:edges[].{to:to,type:edgeType,err:edgeProperties.errorCode,http:edgeProperties.httpStatusCode}}'
```

For the error semantics — in particular that an `AccessDeniedException` here is an access
grant / IAM or customer-KMS cause and **never** an "intelligence not enabled" signal — see
[context-graph.md](context-graph.md#errors) and
[When a call fails](#when-a-call-fails) above.

## Cost and performance guardrails

Every tool result is re-read on every later turn, so output size and call count drive the cost
and latency of an investigation. All three operations have a CLI, so the same projections apply
to each.

- **Bound calls in time.** Use the window the question needs plus modest slack; widen in
  steps only when a narrow window is empty. Avoid multi-day sweeps.
- **Project and cap output.** The AWS CLI fetches *all* pages of a paginated call by default,
  so use `--max-items` or `--no-paginate`, and a JMESPath `--query` that keeps only the fields
  you need. Read only what you need to rank and continue (title, severity, status, times,
  affected service and resource names, summary, observation ids); read `reasoning` only for the
  insight you examine. Observation `evidenceSamples` arrays are large; ignore them unless you
  need per-sample values.
- **Batch, don't loop.** One call scoped to many things beats one call per thing: a single
  `services` list rather than a loop, and one `anomalyIds` call to fetch an insight's whole
  `observations[]` rather than one call per observation.
- **Context graph:** `depth` 1 first; `maxEdgesPerNode` (1–50) to bound a densely connected
  service or resource; `includeMetadata` only on a small neighborhood.
- **Stop when the evidence agrees.** Once the insight's reasoning, its observations, and the
  context graph (if you checked it) point to the same root cause, answer. Each extra confirming
  call adds a turn and rarely changes the result.

## Gotchas

- **Empty results are usually scope:** the wrong Region (the Region of the call selects which
  CloudWatch dataset is read), a window that misses the problem, a service name that differs
  from the stored one (compare `affectedNodes[].name` or the graph's `alternateNames`), or
  retention: older insights and observations may no longer be listed. An empty result is a
  scoping signal, never a "healthy" verdict.
- **Account and Region come from the data.** The CloudWatch dataset can hold telemetry from
  several accounts. Use `affectedNodes[].accountId` / `region` and an observation's
  `sourceAccountId` / `sourceRegion` for follow-up calls.
- **A pre-existing insight is not a fresh incident's cause.** Check that an insight's window
  overlaps the incident before citing it; a chronic background insight that started hours
  earlier is not the root cause of something that began at the incident time.
