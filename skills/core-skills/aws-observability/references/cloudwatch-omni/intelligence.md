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
[../cloudwatch/promql.md](../cloudwatch/promql.md); a bare "is `<service>` healthy" verdict
or a role-labelled dependency map belongs to [service-health.md](service-health.md); a pure
traversal-direction or edge-semantics question belongs to
[context-graph.md](context-graph.md). Use this file when the question is *what is wrong and
why* — status, triage, root cause, or a past incident.

## Investigation question — facts you MUST surface

A how-to-investigate answer, and every root-cause answer, states each of these, with or
without live data:

1. **Scope first:** the Region (it selects the Space), the anchor service, and the window —
   the incident window for telemetry, at least the 24 hours ending at the incident for the
   context graph. Never open with an unscoped log or metric scan.
2. **Intelligence before raw telemetry:** `ACTIVE` insights and their observations that
   overlap the window, from the API or the console.
3. **Localize on the context graph:** `GetContextGraph` at depth 1, `includeMetadata` true,
   walking downstream to the deepest unhealthy node.
4. **An insight or edge is a hypothesis.** Confirm the candidate hop with RED metrics in
   PromQL and with slow or failing spans in SQL.
5. **An empty or zero result is a scoping signal**, never "healthy".
6. **Commit to one root-cause service**, with the causal chain and the evidence.

## Contents

- [Scope and neighbours](#scope-and-neighbours)
- [Investigation question — facts you MUST surface](#investigation-question--facts-you-must-surface)
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

These three are the **read** operations this reference teaches, not the whole Intelligence
API. Enabling and configuring Intelligence has its own public operations —
`get-intelligence-configuration` / `put-intelligence-configuration` for the optional
customer-managed KMS key, and `create-integration` / `list-integrations` and their siblings for
integrations such as `AWS_INTEGRATION` and `AWS_CONFIG_SLREC`. They are real; never tell the
user they do not exist. For any of them — what they do, the IAM they need, an error they
return, or a graph that is still empty right after setup — route to the
`setting-up-cloudwatch-observability` skill's `references/cloudwatch-omni/intelligence-setup.md`.
An error or an empty result from one of the three read operations above stays here: see
[When a call fails](#when-a-call-fails) and the context graph's empty-result rules.

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

0. **Scope first.** Fix the Region (it selects the Space), the anchor service, and the
   window: the incident window for telemetry, and at least the 24 hours ending at the
   incident for the context graph. Say what you assumed for any of the three. Do not open
   with an unscoped log or metric scan.
1. **Insights: what's going on.** List insights for the window the question needs. `ACTIVE`
   insights cover "now", which is also the place to start when no time is given. For a past
   incident the insight it raised may since have gone `INACTIVE` — the two statuses are
   reversible — so an insight you expect may not be `ACTIVE` in the window; say that you are
   looking at a past incident.
2. **Rank them by relevance** to the problem under investigation, and keep the ones that match.
3. **Dive into their observations.** Resolve a kept insight's `observations[]` with one
   `ListObservations` call using `observationIds` — the batch-get, up to 100 ids, sent
   without `filters` (see [ListObservations](#listobservations)). Each
   observation names a service, a signal, how it changed, and when; these are the evidence for
   the answer.
4. **Context graph: blast radius and causal chain.** Start from the affected services and
   resources and follow their dependencies, to see which one the others depend on and who is
   impacted. For a slow or erroring service, walk **downstream** (its callees and datastores
   hold the cause; its callers are blast radius): `GetContextGraph` at depth 1 with
   `includeMetadata` true, follow the edge with an `errorCode` or non-2xx `httpStatusCode`
   first, raise depth one hop at a time, and check each edge's `lastObservedAt` against the
   incident. An edge with no error fields is unreported, not healthy. The rules are in
   [context-graph.md](context-graph.md)'s "facts you MUST surface".
5. **Confirm the candidate hop in telemetry.** Read its RED metrics (error rate, p99
   latency, throughput) with PromQL per [../cloudwatch/promql.md](../cloudwatch/promql.md),
   and its slow or failing spans with SQL per
   [query/sql-logs-traces.md](query/sql-logs-traces.md).
6. **Answer with the evidence.** Name **one** root-cause service and each impacted service,
   with the causal chain, and for each one cite the observations behind it: service, signal
   (metric, log pattern, or operation), how it changed, and when. Without live data, still
   end the method on that step: say the walk ends by naming one service and what would
   confirm it.

An insight or a graph edge is a **hypothesis to confirm**, never the final answer on its own:
check that its window actually overlaps the incident, then confirm the candidate on the graph
and in telemetry. An empty or zero result is a scoping signal (Region, window, name), never a
"healthy" finding.

---

## Data model

**Observation**: a correlated finding over one or more anomalies in a service's telemetry
(logs, metrics, or traces). Field names below are from the registered `cloudwatchomni` model
(`ObservationMembers`): `observationId`, `accountId`, `title`, `summary`, `severity`, `status`,
`reasoning`, `anomalies[]` (the anomaly ids it correlates), `affectedNodes`, and the lifecycle
timestamps and actors. The remaining rows describe anomaly-level detail that a response may
carry; they could not be confirmed against that model, so read the field names off the
response rather than relying on them.

| Field | Meaning |
|---|---|
| `observationId` | Observation id; the value to pass in `observationIds` |
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
| `observations[]` | The ids it correlates, passed as `observationIds` to ListObservations. Unconfirmed: the registered model documents these as anomaly ids, which may not be the same ids as `observationId`; check that the batch-get returns one item per id |
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
| `filters.timeRange` `{start,end}` | Window to search |
| `filters.services` | Up to 50 service names |
| `filters.severity` | A list of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `filters.status` | A list of `ACTIVE`, `INACTIVE` |
| `query` | Free-text search over observations |
| `observationIds` | Batch-get up to 100 ids, typically an insight's `observations[]`. Send it without `query` or `filters` (mutually exclusive, ValidationException otherwise); a missing or inaccessible id is omitted from `items`, so compare the ids you sent with the ids returned |
| `maxResults`, `nextToken` | Page size 1–100 and the cursor |

Every filter sits under `filters`; a top-level `timeRange`, `services` or `severity` is
rejected client-side with `Unknown parameter in input`. The response returns the observations
in `items`, plus `nextToken`; unlike ListInsights there is no `unprocessedIds`.

**Getting one insight's observations.** Use the `observationIds` batch-get: one call, passing
that insight's `observations[]` (up to 100 ids), returns exactly those observations. Send it
alone. This is the primary, cheapest path — one scoped call rather than listing a window and
filtering client-side.

Anomalies on given services in a window — a filtered query, with no `observationIds`:

```json
{
  "filters": {
    "timeRange": {"start": "2026-09-16T00:00:00Z", "end": "2026-09-16T02:00:00Z"},
    "services": ["<service-a>", "<service-b>"],
    "severity": ["HIGH", "CRITICAL"]
  }
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
  `name` (as `nodeFilters.name`), is the starting point, with `depth` 1 and a 24-hour window
  ([why](context-graph.md#choosing-the-time-window)). `startTime` and `endTime` are required.
- Edges point from caller to dependency, and each service or resource carries only its
  outbound `edges[]`; callers are found with `edgeFilters.to`. An edge's `to` is a `nodeId`,
  mapped to a name from the same response.
- An `errorCode` or non-2xx `httpStatusCode` on an edge is an observed failure of that
  dependency; a missing one is unreported, not healthy.
- `includeMetadata` returns the exact metric names and log/trace selectors behind a service or
  resource, for follow-up queries.

AWS CLI example:

```bash
# One service and its direct neighbors over the 24 hours ending at the incident. --query keeps
# only each node's identity and its outbound edges (target id, edge type, error code, HTTP
# status, last seen): enough to see what the service depends on, which of those calls are
# failing, and whether an edge was live at the incident. --include-metadata adds the selectors
# that the confirming PromQL and SQL queries are built from.
aws cloudwatchomni get-context-graph --region <region> \
  --start-time 2026-09-15T00:45:00Z --end-time 2026-09-16T00:45:00Z \
  --node-filters '{"name":"<service-name>"}' --depth 1 --include-metadata --no-paginate \
  --query 'nodes[].{id:nodeId,name:name,type:nodeType,metadata:metadata,
           out:edges[].{to:to,type:edgeType,err:edgeProperties.errorCode,http:edgeProperties.httpStatusCode,seen:lastObservedAt}}'
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
  steps only when a narrow window is empty. Avoid multi-day sweeps. (This is for insights; the
  context graph needs 24 hours.)
- **Project and cap output.** The AWS CLI fetches *all* pages of a
  paginated call by default, so use `--max-items` or `--no-paginate`, and a JMESPath `--query`
  that keeps only the fields you need. Read only what you need to rank and continue (title, severity, status, times,
  affected service and resource names, summary, observation ids); read `reasoning` only for the
  insight you examine. Observation `evidenceSamples` arrays are large; ignore them unless you
  need per-sample values.
- **Batch, don't loop.** One call scoped to many things beats one call per thing: a single
  `services` list rather than a loop, and one `observationIds` call to fetch an insight's whole
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
