# CloudWatch Omni context graph and GetContextGraph

Reference for the **CloudWatch Omni context graph** — the service topology Omni
builds from a Space's telemetry — and the **`GetContextGraph`** API that reads it.
Use it when an investigation needs to answer "what does this service depend on,
what depends on it, and which of those is actually broken" before writing a single
telemetry query.

The context graph is read through the same public SigV4 API as the rest of Omni:
service `cloudwatch-omni`, signing name `cloudwatch`, invoked as
`aws cloudwatch-omni get-context-graph` from the AWS CLI (through the `aws___call_aws`
tool or a shell). See [programmatic-access.md](programmatic-access.md) for endpoints,
SDK access, and what to do when the CLI reports the service as unsupported.

---

## Contents

- [What the context graph is](#what-the-context-graph-is)
- [GetContextGraph API](#getcontextgraph-api)
- [Reading the graph](#reading-the-graph)
- [Using the graph in an investigation](#using-the-graph-in-an-investigation)
- [Gotchas](#gotchas)

---

## What the context graph is

The context graph is a directed graph of **nodes** (the things that run) and
**edges** (the observed relationships between them), derived from telemetry and
other discovery sources flowing into a Space. It is the answer to "what talks to
what" for one account in one Region, over a time window you choose.

### Nodes

Every node has a `nodeType`, one of:

| `nodeType` | Meaning |
|---|---|
| `SERVICE` | An instrumented workload that emits its own telemetry — an application service, an AI agent, a Lambda function |
| `RESOURCE` | Infrastructure a service uses or runs on — a database, queue, cache, host, cluster |
| `REMOTE_SERVICE` | A dependency seen only from the caller's side — an AWS service API, a third-party endpoint, anything not instrumented in this Space |

Orthogonal to `nodeType`, a node may carry a coarser `nodeProperties.category`:
`GEN_AI_AGENT`, `GEN_AI_MODEL`, `DATABASE`, `MESSAGING_QUEUE`, `COMPUTE`, `STORAGE`,
`NETWORK`. This is how AI agents and the models they call show up in the same graph
as ordinary services. The model documents `category` as **absent on most nodes
today**, so treat its absence as "not reported", not "not a database".

A node's identity lives in `nodeProperties` — `region`, `cloudProvider`
(defaults to `"aws"`), `sourceAccountId`, `namespace`, plus `category` and `stage`.
The first four are the node's merge key: a service seen from several sources
(traces, flow logs, CloudTrail) is resolved into **one node**, its resolved `name`
wins, and the names it was merged away from appear in `alternateNames`.

### Edges

Every edge is **directed**, `from` → `to` (both are `nodeId`s), with an `edgeType`:

| `edgeType` | Meaning | Follow it when |
|---|---|---|
| `CALLS` | `from` invokes `to` — a service dependency | Tracing request-path latency or errors downstream |
| `ACCESSES` | `from` reads or writes datastore `to` — a database, queue, or cache | A service is slow or erroring on I/O |
| `RUNS_ON` | `from` executes on host or compute `to` | Suspecting an infrastructure-level cause shared by co-located services |

`edgeProperties` carries whatever the producing source reported: `errorCode`,
`httpStatusCode`, `httpMethod`, `protocol`, `sourcePort`/`destinationPort`,
`blocked`, `serviceInitiated`, and `trafficStats` (`bytes`, `packets`, `flows`,
`sentBytes`, `receivedBytes`). **The presence of `errorCode` means the edge exists
but the dependency is failing** — a live failing call. Most edges carry only a few
of these members.

### Where nodes and edges come from

Each node and edge lists the `sources` that contributed it and the `signalTypes`
observed on it:

- `sources` — `TELEMETRY` (spans and metrics emitted by instrumented code),

  `VPC_FLOW_LOG`, `ELB_ACCESS_LOG`, `CLOUDFRONT_ACCESS_LOG`, `S3_ACCESS_LOG`,
  `WAF_ACCESS_LOG`, `CLOUDTRAIL`, `IAM_POLICY`, `CONFIG`, `AWS_INTEGRATION`,
  `CODE_SEMANTICS`, `AZURE_VNET_FLOW_LOG`.

- `signalTypes` — `LOGS`, `METRICS`, `TRACES`, `CONFIG`, `UNKNOWN`.

The request-path edges an investigation cares about (`CALLS`, `ACCESSES`) come
overwhelmingly from **traces**: a parent span in service A with a child span
reaching service B is a `CALLS` edge A → B, and the span's status and attributes are
what populate `errorCode` / `httpStatusCode`. Vended metrics contribute nodes and
the per-node `metadata.metrics` list. Network-derived edges (flow logs, access logs)
add `protocol`, ports, `blocked`, and `trafficStats`. An edge that merged across
sources reports the earliest `firstObservedAt` and latest `lastObservedAt` any source
saw.

### How it relates to a Space

The graph is what **one account's Space in one Region** can see. A
`GetContextGraph` request carries no Space identifier: it is scoped by the
credentials you sign with (the caller's account) and the Region you send it to.
Because an account has at most one Space per Region (see
[concepts.md](concepts.md)), the Region of the call *is* the Space selection.
Calling the wrong Region returns a different — usually empty — graph, not an error.

Where a Space centralizes telemetry forwarded from other accounts, those services
appear as nodes whose `nodeProperties.sourceAccountId` differs from the caller's
account. Read account and Region for later queries off the node — never assume they
match the credentials you are using.

---

## GetContextGraph API

`GetContextGraph` queries the context graph with filtering, traversal, and
pagination. It is read-only. The caller's access grant (or IAM policy) must allow
`cloudwatch:GetContextGraph`; the model does not document a resource-level ARN for it,
so scope it at the Space rather than inventing a resource ARN.

### Request

| Field | Type | Required | Notes |
|---|---|---|---|
| `startTime` | timestamp (UTC) | yes | Inclusive start of the observation window |
| `endTime` | timestamp (UTC) | yes | Inclusive end; must not be before `startTime` (`ValidationException` otherwise) |
| `nodeFilters` | `NodeFilters` | no | Which nodes to start from (see below). Omit to match every node |
| `edgeFilters` | `EdgeFilters` | no | Which edges to return (see below) |
| `depth` | integer 0–3 | no | Hops to traverse out from the nodes matched by `nodeFilters`. `0` returns only the matched nodes |
| `maxResults` | integer 1–1000 | no | Page size, counted in **nodes** |
| `maxEdgesPerNode` | integer 1–50 | no | Caps the fan-out returned for any one node |
| `includeMetadata` | boolean | no | Also return the `metadata` block on each node and edge. Off by default — costs an extra lookup per node |
| `nextToken` | string | no | Cursor from the previous page |

**`NodeFilters`** — criteria for selecting the starting nodes:

| Field | Type | Matches |
|---|---|---|
| `nodeId` | string | Exactly this node |
| `nodeType` | `SERVICE` \| `RESOURCE` \| `REMOTE_SERVICE` | Nodes of this type |
| `name` | string | Nodes with exactly this display name |
| `namespace` | list of strings | Nodes in any of these logical service groupings (this is **not** a metric namespace) |
| `region` | list of strings | Nodes running in any of these Regions |
| `sourceAccountId` | list of strings | Nodes discovered from telemetry produced by any of these accounts |
| `cloudProvider` | list of strings | Nodes on any of these providers |
| `category` | list of `NodeCategory` | Nodes of any of these categories |
| `stage` | list of strings | Nodes observed in any of these deployment environments |
| `sources` | list of `Source` | Nodes contributed by any of these discovery sources |
| `tags` | list of `KeyFilter` | Tags on the underlying resource |
| `telemetryAttributes` | list of `KeyFilter` | Raw OTel attributes on the node |

**`EdgeFilters`** — criteria for the edges returned:

| Field | Type | Matches |
|---|---|---|
| `edgeId` | string | Exactly this edge |
| `from` | string (`nodeId`) | Edges originating from this node |
| `to` | string (`nodeId`) | Edges pointing to this node |
| `edgeType` | `CALLS` \| `ACCESSES` \| `RUNS_ON` | Edges of this kind |
| `operations` | list of strings | Edges carrying any of these operations |
| `sources` | list of `Source` | Edges contributed by any of these sources |
| `telemetryAttributes` | list of `KeyFilter` | **Accepted but not applied today** — the model documents it as currently ignored, in the same way as `nodeFilters.telemetryAttributes`. Do not rely on either to narrow results |

**`KeyFilter`** is `{ key, values[] }`. Multiple `KeyFilter`s in one list are
AND'ed; multiple `values` inside one `KeyFilter` are OR'ed. Each value may be an
exact match, a negation (`!value`), or a wildcard (`*value*`, `value*`, `*value`).

### Response

```
{
  "nodes": [ Node, ... ],     // the paginated collection
  "nextToken": "..."          // absent when there are no more pages
}
```

Edges are **not** a separate top-level list. Each `Node` carries its **outbound**
edges in `node.edges[]`, every one of them with its own `from` (equal to that
node's `nodeId`) and `to`. Pagination cursors advance over nodes; each page includes
the edges connecting the nodes on that page. Treat nodes as the collection you
paginate and edges as relationship data attached to them.

**`Node`:**

| Field | Notes |
|---|---|
| `nodeId` | Unique within the graph; the key `from`/`to` refer to |
| `nodeType` | `SERVICE` \| `RESOURCE` \| `REMOTE_SERVICE` |
| `name` | Resolved display name |
| `alternateNames` | Names this node was merged away from |
| `nodeProperties` | `region`, `cloudProvider`, `sourceAccountId`, `namespace`, `category`, `stage` |
| `telemetryAttributes` | Raw OTel attributes as emitted, minus any key promoted onto `nodeProperties` |
| `tags` | Tags on the underlying resource |
| `operationDetails` | Operations observed on the node, keyed by operation name, each listing the dimension sets that identify its metric series |
| `signalTypes`, `sources` | As above |
| `firstObservedAt`, `lastObservedAt` | UTC, minute granularity; earliest / latest across merged sources |
| `edges` | Outbound `Edge` list (bounded by `maxEdgesPerNode`) |
| `metadata` | Only when `includeMetadata` is set — see below |

**`Edge`:**

| Field | Notes |
|---|---|
| `edgeId`, `from`, `to`, `edgeType` | Identity and direction |
| `operations` | Operation names observed on the edge, e.g. `"POST /charges"` |
| `edgeProperties` | `errorCode`, `httpStatusCode`, `httpMethod`, `protocol`, `sourcePort`, `destinationPort`, `blocked`, `serviceInitiated`, `trafficStats` |
| `telemetryAttributes` | Raw OTel attributes, minus any key promoted onto `edgeProperties` |
| `signalTypes`, `sources`, `firstObservedAt`, `lastObservedAt`, `metadata` | As for nodes |

**`metadata`** (only with `includeMetadata: true`) is what lets you pivot from a
graph element to the exact telemetry behind it:

- `metrics[]` — each metric observed on the node: `name`, `preferredStat` (e.g.

  `"p99"`, often absent), `metricType` (`gauge`, `sum`, `histogram`, ...),
  `semantics.description` / `semantics.unit`, and `attributes` — the **raw, stored**
  attribute values (`service.name`, `service.namespace`, `cloud.account.id`,
  `cloud.region`, ...) that select this metric's series. These are deliberately
  *not* the node's normalized identity, because a merged node can carry different
  raw values per metric.

- `semantics` — on nodes only: `purpose`, `language`, `framework`, `kind`,

  `repository`.

- `logs[]` / `traces[]` — per-signal query selectors: a list of blocks that are

  OR'ed together, each an AND of exact store column → raw values. `logs` is
  node-level only; `traces` appears on both nodes and edges.

### Errors

`ValidationException` (bad range, `endTime` before `startTime`, out-of-range
`depth`/`maxResults`), `AccessDeniedException` (missing `cloudwatch:GetContextGraph`,
or the account is not enabled for Omni Intelligence), `ThrottlingException`
(retryable), `InternalServerException`.

### CLI form

Nested structures are passed as JSON. Timestamps are ISO-8601. Because the
operation is modeled as paginated, the CLI **auto-paginates** by default — pass
`--no-paginate` to get exactly one page, and `--max-items` to cap the total.

```bash
# A service and its direct dependencies over the incident hour
aws___call_aws → aws cloudwatch-omni get-context-graph \
  --region us-east-1 \
  --start-time 2026-09-16T00:00:00Z --end-time 2026-09-16T01:00:00Z \
  --node-filters '{"nodeType":"SERVICE","name":"checkout-service"}' \
  --depth 1 --max-results 200 --max-edges-per-node 50

# Everything in one logical grouping, two hops out, with metadata for pivoting
aws___call_aws → aws cloudwatch-omni get-context-graph \
  --region us-east-1 \
  --start-time 2026-09-16T00:00:00Z --end-time 2026-09-16T01:00:00Z \
  --node-filters '{"namespace":["ecommerce"]}' \
  --depth 2 --include-metadata

# Who calls payments-service? (edges pointing INTO a node)
aws___call_aws → aws cloudwatch-omni get-context-graph \
  --region us-east-1 \
  --start-time 2026-09-16T00:00:00Z --end-time 2026-09-16T01:00:00Z \
  --edge-filters '{"to":"svc:payments-service","edgeType":"CALLS"}' \
  --max-results 1000

# Only nodes that talk to a datastore, failing or not
aws___call_aws → aws cloudwatch-omni get-context-graph \
  --region us-east-1 \
  --start-time 2026-09-16T00:00:00Z --end-time 2026-09-16T01:00:00Z \
  --node-filters '{"nodeType":"SERVICE"}' \
  --edge-filters '{"edgeType":"ACCESSES"}' --depth 1
```

The response from the first call looks like this (abridged from the model's own
example):

```json
{
  "nodes": [
    {
      "nodeId": "svc:checkout-service",
      "nodeType": "SERVICE",
      "name": "checkout-service",
      "nodeProperties": { "region": "us-east-1", "cloudProvider": "aws",
                          "sourceAccountId": "123456789012", "namespace": "ecommerce" },
      "signalTypes": ["TRACES"], "sources": ["TELEMETRY"],
      "firstObservedAt": "2026-09-16T00:03:00Z", "lastObservedAt": "2026-09-16T00:58:00Z",
      "edges": [
        { "edgeId": "edge:checkout-service->payments-service",
          "from": "svc:checkout-service", "to": "svc:payments-service",
          "edgeType": "CALLS", "operations": ["POST /charges"],
          "signalTypes": ["TRACES"], "sources": ["TELEMETRY"] }
      ]
    },
    { "nodeId": "svc:payments-service", "nodeType": "SERVICE", "name": "payments-service",
      "nodeProperties": { "region": "us-east-1", "cloudProvider": "aws",
                          "sourceAccountId": "123456789012", "namespace": "ecommerce" } }
  ],
  "nextToken": "<next-page-token>"
}
```

---

## Reading the graph

### Direction: upstream, downstream, blast radius

Edges point in the direction of dependency: `from` depends on `to`.

- **Downstream of X** — the nodes X's own `edges[]` point `to`. These are X's

  dependencies; if one of them is failing, X will look degraded.

- **Upstream of X** — the nodes whose edges point `to` X. These are X's callers;

  if X is failing, they will look degraded. `node.edges[]` is outbound only, so
  callers are found with `edgeFilters.to = <X's nodeId>` (the third CLI example
  above), not by reading X.

- **Blast radius of X** — everything transitively upstream of X: the set of

  services whose degradation X alone would explain. A node with a large blast
  radius and a failing edge beneath it is the shape a root cause usually takes.

The model describes `depth` as hops traversed "out from" the matched nodes, but the
traversal is undirected: each hop follows edges in both directions, so `depth: 1` on X
returns X's callers as well as its dependencies, and every intermediate node from hop 0
up to `depth` (max 3) is included, not only the outermost hop. `edgeFilters` narrow
which edges are *returned*, not which are traversed. To isolate callers, filter with
`edgeFilters.to = <X's nodeId>` rather than sifting the `depth` output.

### Symptom vs. cause

- A **symptom** is an upstream caller that looks degraded only because something it

  `CALLS` or `ACCESSES` downstream is failing.

- A **cause** is a shared downstream dependency that *all* failing paths traverse.

Prefer the cause. Rank candidates, in order, by:

1. **Downstream fan-in explained** — the deepest node whose failure accounts for the

   most affected upstream services.

2. **Shared dependency** across multiple *independently* failing services.
3. **Temporal precedence** — the node whose failing edges or anomalies began first.

   On the graph itself, compare `firstObservedAt` of the failing edge (or of a
   newly-appeared node) against the incident window.

Name the **deepest node that explains the most downstream symptoms** as the primary
hypothesis — not the first degraded node you saw — and state the traversal path
(node names and edge types) as the supporting evidence.

### Hop-by-hop traversal

1. **Locate the alarming node** — the service named by the alert, the Omni

   Intelligence insight shown in the console, or the user's symptom. Fetch it with
   `nodeFilters.name` (or `nodeId`), `depth: 1`, and a **narrow** window around the
   incident.

2. **Read the edges.** Any `edgeProperties.errorCode` or a non-2xx

   `httpStatusCode` on a `CALLS`/`ACCESSES` edge is a live failing dependency —
   follow it first. Edges with no error fields are not proven healthy; they are
   unreported.

3. **Walk outward along `CALLS` / `ACCESSES`** — not just immediate neighbors. At

   each hop, query telemetry for correlated errors or latency at that node **before**
   expanding further (see the next section for how).

4. **Go deeper only where signal appears.** Stop a branch that is clean. Raise

   `depth` one hop at a time rather than asking for `depth: 3` up front — a dense
   graph at depth 3 is hundreds of nodes and hides the path you care about.

5. **Confirm along the path with traces.** Parent → child spans mirror `CALLS`

   edges, so once a candidate path exists, query for slow or erroring spans along
   exactly that path to establish which hop *originates* the latency or error.

---

## Using the graph in an investigation

The graph localizes; queries confirm. Alternate between them, spending the cheap
call (graph) before the expensive one (telemetry scan).

1. **Start from the symptom.** An alert firing ([alerts.md](alerts.md)) names a

   query and a Space; a CloudWatch Omni Intelligence insight or anomaly in the console
   names the affected service(s), severity, and time; a user names a service. Any of
   these gives you a service name, a Region, and a time window. Listing insights and
   anomalies is not part of the public API today — read them in the console, then
   carry the affected service names into the graph call.

2. **Fetch the neighborhood.** `get-context-graph` with `nodeFilters.name`,

   `depth: 1`, `includeMetadata: true`, and a window of roughly the incident ± 15
   minutes. Take `nodeProperties.region` and `nodeProperties.sourceAccountId` from
   the returned node for every subsequent call — **do not guess them** from the
   credentials you hold.

3. **Pick the next node** by the rules above: follow the edge that carries an

   `errorCode`/`httpStatusCode`, else the shared `ACCESSES` datastore, else the
   `CALLS` edge with the most operations.

4. **Pivot to telemetry at the suspected node**, using the `metadata` block so

   your query matches what is actually stored rather than the graph's normalized
   name:

   - **Traces and logs (SQL)** — `metadata.traces[]` / `metadata.logs[]` give the

     exact column → value selectors; `alternateNames` tells you which raw
     `service.name` values to include. Write the query per
     [query/sql-logs-traces.md](query/sql-logs-traces.md), always with a
     `` `@timestamp` `` range, and discover the real field names with
     `EXPLAIN (ANALYZE_FIELDS)` before filtering on anything but `@`-fields. For
     example, to find erroring spans at the suspected node inside the window:

     ```sql
     SELECT `@timestamp`, `@record`
     FROM traces.default
     WHERE `@timestamp` BETWEEN to_timestamp_nanos('2026-09-16T00:00:00Z')
                            AND to_timestamp_nanos('2026-09-16T01:00:00Z')
       AND resource['attributes']['service.name'] = 'payments-service'
     ORDER BY `@timestamp` DESC
     LIMIT 50
     ```

     Then narrow with the status / error attributes that schema discovery shows are
     present for this service.

   - **Metrics (PromQL)** — `metadata.metrics[]` gives the metric `name`, its

     `preferredStat`, and the raw `attributes` (`service.name`, `service.namespace`,
     `cloud.region`, ...) to use as label matchers. Write the query per
     [query/promql-metrics.md](query/promql-metrics.md).

   - An edge's `operations[]` (e.g. `"POST /charges"`) is the operation name to

     filter spans or metrics on when you want just that call path.

5. **Decide, then expand or stop.** Signal at this node → fetch *its* neighborhood

   (`nodeFilters.nodeId = <that node>`, `depth: 1`) and repeat from step 3. No
   signal → this branch is a symptom; go back to the last node with signal and try
   its next edge.

6. **Report** the deepest node that explains the most upstream symptoms, the path you

   walked (`checkout-service —CALLS→ payments-service —ACCESSES→ payments-db`), the
   edge evidence (`errorCode`, `httpStatusCode`, `firstObservedAt`), and the query
   that confirmed it. If the cause is a `REMOTE_SERVICE` node you cannot query, say
   so: the evidence is the failing edge and the caller-side spans, and the fix is
   on the caller's side (retries, timeouts, fallbacks) or with the remote owner.

---

## Gotchas

- **Empty `nodes` is usually scope, not absence.** In order of likelihood: the

  Region is wrong (a Space is per Region — the call went to a Region with a
  different or no Space); the time window does not overlap any observation
  (`firstObservedAt`/`lastObservedAt` are minute-granular; widen the window before
  concluding); `nodeFilters.name` is an exact match and the stored name differs
  (drop `name`, filter on `namespace` or `nodeType`, and look at `alternateNames`);
  nothing is instrumented, or telemetry is not reaching this Space yet (see the
  setup order in [concepts.md](concepts.md) — instrumentation started before a
  Space exists delivers nowhere you can see).

- **`AccessDeniedException` on an otherwise-correct call** means either the

  principal lacks `cloudwatch:GetContextGraph` or the account is not enabled for
  Omni Intelligence. Neither is fixed by changing the request.

- **Edges can point at nodes that are not on this page.** Edges are nested under

  their `from` node and pagination is by node, so a `to` may reference a `nodeId`
  you have not received yet — or one past your `depth`. Collect every page (or let
  the CLI auto-paginate) before treating a dangling `to` as a missing node.

- **`maxEdgesPerNode` silently truncates hubs.** A shared datastore or gateway with

  more outbound edges than the cap loses some of them from the response. If a
  dependency you expect is missing, raise the cap (max 50) or query it directly with
  `edgeFilters.from`/`to`.

- **Stale edges.** An edge is returned if it was observed anywhere in your window.

  Compare its `lastObservedAt` with the incident: an edge last seen well before the
  incident is history, not a live call path — and a `CALLS` edge that stops
  appearing mid-window can itself be the signal (the caller stopped reaching the
  dependency).

- **Absent is not negative.** `errorCode` absent means the source did not report

  one, not that the call succeeded. `blocked` absent means the edge did not come
  from network-flow data, not that traffic was allowed. `category` is absent on most
  nodes. Only conclude "healthy" from telemetry, never from a missing field.

- **`namespace` is a logical service grouping, not a CloudWatch metric namespace.**

  Do not paste it into a metrics query as one. The metric's own
  `metadata.metrics[].attributes["service.namespace"]` is what selects series.

- **Merged nodes do not match stored telemetry by `name`.** The graph's `name` is

  the resolved identity; the store still holds the raw values. Use
  `alternateNames`, `metadata.traces[]`/`logs[]` selectors, and
  `metadata.metrics[].attributes` for the values your queries must match.

- **`telemetryAttributes` filters do not narrow results today** (both on

  `edgeFilters` and, per the model, `nodeFilters`). Filter server-side on `name`,
  `namespace`, `nodeType`, `sourceAccountId`, `region`, or `stage`, and post-filter
  on attributes client-side.

- **`REMOTE_SERVICE` nodes have only a caller's-eye view.** There is no telemetry

  of their own in this Space to pivot to. Their edges' `errorCode`/`httpStatusCode`
  and the calling service's spans are all the evidence you will get.

- **Cross-account nodes need the node's account, not yours.** When

  `nodeProperties.sourceAccountId` differs from the caller's account, the telemetry
  was forwarded in. Queries against this Space still work, but any per-account
  follow-up (IAM, resource configuration) must target `sourceAccountId`.

- **`includeMetadata` is not free.** It adds a lookup per returned node. Use it on

  the small `depth: 1` neighborhood you are about to pivot from, not on a
  `depth: 3` sweep of the whole Space.
