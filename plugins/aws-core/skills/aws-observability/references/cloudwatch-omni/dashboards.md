# Building a CloudWatch Omni Dashboard

Use this when building, saving, reading back, or fixing a CloudWatch Omni dashboard
— "build me a dashboard for checkout", "show what's most critical for this
service", "lay this out", "which chart for this signal?", "why is that panel
empty?", "why did that field drop on save?" — and for the dashboard API itself
(`CreateOmniDashboard`and its siblings,`aws cloudwatch-omni *-omni-dashboard*`).

A CloudWatch Omni dashboard is a set of **panels** laid out on a fixed 60-column
grid, most of them charts over CloudWatch Omni queries. The dashboard **body is
JSON** — a `panels[]`array (plus an optional`scope`) that the Omni UI renders. It
belongs to a **Space** and is stored, as a JSON string, in the `body` field of a
dashboard resource you create and update through the API (section 7). The
deliverable is therefore two things: a valid, grounded body, and the API call that
saves it.

## Contents

1. [Omni dashboard vs. CloudWatch dashboard](#1-omni-dashboard-vs-cloudwatch-dashboard)
2. [Decide what the dashboard shows](#2-decide-what-the-dashboard-shows)
3. [Ground every panel query](#3-ground-every-panel-query)
4. [Author the panel bodies](#4-author-the-panel-bodies)
5. [Lay out on the 60-column grid](#5-lay-out-on-the-60-column-grid)
6. [Troubleshooting](#6-troubleshooting)
7. [API reference](#7-api-reference)
8. [Appendix — Archetype templates](#8-appendix--archetype-templates)

Two rules hold across every step:

- **Never chart a metric, field, or label you have not confirmed exists.** An
  invented name renders an **empty** panel, which on a saved dashboard reads like
  an outage — worse than no panel. Ground first (section 3); drop what you cannot
  ground.
- **Query text follows the CloudWatch Omni query dialect.** The SQL rules for logs
  and traces live in [sql-logs-traces.md](query/sql-logs-traces.md); metric
  semantics and PromQL selectors live in [promql-metrics.md](query/promql-metrics.md).
  This reference owns the dashboard body — the panel schema, chart choices, grid
  math — and the dashboard API. It does not restate the dialects.

**ALWAYS STATE — two silent failures a dashboard body never warns you about.**
Neither raises an error; each just quietly does the wrong thing, so call them out
whenever you author, explain, or debug a body:

- **Unknown or misspelled keys are silently dropped.** Any key not in the panel
  schema — including a correctly-placed field whose *name is misspelled* — is
  silently ignored on save; nothing errors, the value just never persists (a field
  you set "doesn't take effect"). Validate every key's spelling against section 4.
- **`queryLanguage` must be set explicitly per panel; a mismatch fails silently.**
  Set each `explore`panel's`queryLanguage`to`'sql'`or`'promql'` yourself — it
  is **not** inferred from the query text, and a language that doesn't match the
  query is a silent failure, not an error. (Metrics → `promql`; log/trace content →
  `sql`.)

Work sections 2–5 in order — each depends on the one before — then save with the
API in section 7.

---

## 1. Omni dashboard vs. CloudWatch dashboard

Both are called "a CloudWatch dashboard" in ordinary speech, but they are different
resources with different bodies, different APIs, and different query languages:

| | CloudWatch Omni dashboard (this file) | CloudWatch dashboard |
|---|---|---|
| Lives in | An Omni **Space** (`spaceId` on every call) | The AWS account/Region |
| API / CLI | `CreateOmniDashboard`etc. —`aws cloudwatch-omni …`|`PutDashboard`etc. —`aws cloudwatch …` |
| Body | `{ "panels": [...], "scope": {...} }`— panel`type`,`config`,`layout {x,y,w,h}`|`{ "widgets": [...] }`— widget`type`,`properties`,`x/y/width/height` |
| Grid | **60** columns; `y`/`h` in **pixels** | 24 columns; all four in grid units |
| Panel queries | Omni SQL (logs/traces) and PromQL (metrics), one query per panel | CloudWatch metric definitions, Metrics Insights, Logs Insights |
| Identity | `dashboardId` (system-minted UUID); the name is metadata | The dashboard name |

The two bodies are **not** interchangeable — a CloudWatch `widgets[]` body pasted into
`CreateOmniDashboard`is rejected, and an Omni`panels[]` body means nothing to
`PutDashboard`. CloudWatch dashboards are documented in
[../cloudwatch/dashboards.md](../cloudwatch/dashboards.md).

**Confirm Omni is enabled before acting.** The Omni dashboard API is only reachable
once a Space exists in the target Region. Before you create, update, or delete a
dashboard, probe with `aws cloudwatch-omni list-spaces` in that Region. If there is
no Space, say so plainly and route the same need to the CloudWatch path — that is the
correct fallback, not a wrong answer. A **knowledge question** ("does Omni have a
dashboard API?", "what's the panel schema?") is answered from this file directly;
do not gate it behind the probe. See [concepts.md](concepts.md) for what a Space is.

---

## 2. Decide what the dashboard shows

Pick the panels, order them into sections, and choose a visualization per signal.

### Start focused — a tight dashboard beats an exhaustive one

- **The default is a FOCUSED ~6–8 panels:** roughly **4 KPI tiles + 2–3
  golden-signal trends + at most one breakdown table.** A single-signal dashboard
  is smaller still (**3–6 panels**). Don't emit dozens of panels for a vague ask.
- **But build the COMPLETE core — never collapse to one row.** A real dashboard
  reads as summary → trend → breakdown (below): a KPI row AND at least one trend
  chart AND a breakdown. If some metric-based panels cannot ground, fill those
  tiers from traces/logs (section 3) rather than shipping a lone KPI row.
- **Cap the KPI row at 4 tiles** (`number` panels). Four is also the natural grid
  fit — `15 × 4 = 60` columns — so a fifth tile forces an awkward wrap.
- **Always include a saturation panel in the core when the grounded catalog has
  one** — backlog / queue depth, consumer lag / liveness, or circuit-open /
  write-denied. This is the incident-visibility panel; the broader "infra / USE
  health" sweep below remains a deferrable follow-up, but the single saturation
  signal belongs in the core.
- **Build the core, then offer depth as a follow-up "add section."** Defer these
  rather than placing them up front: per-service latency, error / status-code
  breakdown, infra / USE health, and log signals. Name the one the user most likely
  wants next instead of pre-building all of them.

### Ordering principle — headline first, detail last

Every dashboard reads top-to-bottom as **summary → trend → breakdown → raw**:

1. **KPI row** — a few `number` panels with the headline figures (availability,
   error rate, p99 latency, request rate). The fast "is it healthy?" read.
2. **Trend charts** — `line`/`area`/`bar` time series for the golden signals.
3. **Ranked breakdown** — a `table` (top-N by the primary signal) so the worst
   offenders surface.
4. **Raw / drill-down** — logs, spans, alerts, or an application map. Optional
   depth, offered as a follow-up rather than built by default.

Open a logically distinct group with a `divider`, and open an on-call / incident
dashboard with a short `markdown` runbook panel.

### If the ask names a resource type, start from a template

When the request names a known resource TYPE — a Lambda function, a
Kubernetes/EKS workload, an RDS/database instance, an ECS/web service, or an API
Gateway API — don't classify from scratch. Start from that archetype's ready panel
set in the [Appendix](#8-appendix--archetype-templates), then ground and lay it out.

### Recipes (for a general intent)

- **Golden-signals service health (the default when the ask is vague).** For
  "build a dashboard for `<service>`" / "how is`<service>` doing?". Use RED
  (rate/errors/duration) for a request-serving service, USE (utilization,
  saturation, errors) for an infrastructure resource. CORE (~6–8): a KPI row
  (availability %, error rate, p99 latency, request rate); a request-rate `line`;
  an errors `bar`(stacked) or`area`; a latency`line` (p50/p90/p99) **when a real
  percentile source exists** (section 3); and a top-N `table`. Build each family
  from the service's OWN grounded metric first, falling back to a generic OTel
  metric, then a span / log derivation, only when no higher tier grounds it.
- **Errors-focused.** A headline error-rate `number`; a stacked`bar`/`area` of the
  status-code or fault/error breakdown over time; a `table` of top error sources.
  Offer a recent-error log panel and — if the space has alerts — an `alerts` panel
  filtered to `CRITICAL`(or`WARNING`) as a follow-up.
- **Latency-focused.** A p99 `number`; a`line`of p50/p90/p99 together; a`table`
  of the slowest operations. If the service exposes no percentile-capable source,
  chart the average with an honest title — never a fake p99.
- **Throughput-focused.** A request/message-rate `number`; a`line` over time
  grouped by the identity label — read the aggregation off the counter's
  temporality (`sum_over_time`for a delta Sum,`rate()`/`increase()` for a
  cumulative Sum), not a uniform `rate()`; for a queue, pair inbound vs. outbound
  counters and add the backlog gauges (depth, age).
- **Saturation / capacity.** Utilization gauges (`solidgauge` for a bounded %
  against a threshold, `line` for a trend): CPU, memory, disk/queue depth, credit
  balances; a `table` of the resources closest to their limit. An empty series
  often means "not applicable," not zero.
- **Incident review (a fixed past window).** Open with a `markdown` summary, set a
  **fixed** `scope.timeRange` (absolute start and end) on the dashboard so every
  panel covers the incident, then golden-signal charts plus a `spans` panel — or
  a `dashboard`panel with`source.id: "trace-details"` — for the offending path.
  Find the offending trace with a span query per
  [sql-logs-traces.md](query/sql-logs-traces.md) and pin its `traceId` in that
  panel's `source.params.traceConfig`.
- **Multi-service overview (a fleet or whole space).** One compact row per service
  — a `number`KPI plus a small`line`— under a`divider` per service, or a single
  wide `table`ranking all services by health. Prefer a`table`or`topk(...)` over
  a `line` with more than ~25 series.

One query per `explore` panel. To compare two signals, emit two side-by-side
panels (section 5), never one overlaid panel. If the intent is genuinely one
number, a single `number` panel is a complete answer — don't pad it.

---

## 3. Ground every panel query

Ground each data panel's query against live telemetry **before** you write the
body. The query languages themselves are deferred to
[sql-logs-traces.md](query/sql-logs-traces.md) and
[promql-metrics.md](query/promql-metrics.md); this section is the discipline.

**The grounding loop, per data panel:**

1. **Discover what exists.** Run discovery queries against the Space — don't guess
   service names, field names, or metric names.
   - Logs and traces: `EXPLAIN (ANALYZE_FIELDS)`or`SELECT`@record`… LIMIT 10`,
     narrowed to the service and telemetry type (see *Schema Discovery* in
     [sql-logs-traces.md](query/sql-logs-traces.md)). Interactive discovery queries
     **need** a `` `@timestamp` `` bound — only the final panel query is windowless
     (below).
   - Metrics: enumerate the real metric names and their identity labels per
     [promql-metrics.md](query/promql-metrics.md) — which metrics a service emits,
     each metric's instrument type (Sum / Gauge / Histogram) and temporality
     (delta / cumulative), and the labels that scope it.
   - Follow a service's dependencies (the services it calls, from span data) to
     find neighbors worth a panel.
2. **List the real names.** For each signal a panel will chart, list the actual
   metric / field / label names for that data set and signal kind (LOGS, TRACES,
   METRICS). Use those names **exactly** — don't shorten, alias, pluralize, or
   invent them. Nouns in the request ("throttles", "5xx", "timeouts") describe
   *what to aggregate*, not field names — map them to a real grounded name.
   **Metric names are emitter/OTel-specific — they are NOT Prometheus
   conventions.** Do not assume `requests_total`,`http_requests_total`,`*_total`,
   `*_seconds`,`*_count`, or`*_bucket`; a PromQL selector MUST name a metric from
   the grounded list verbatim. If the list lacks the metric you wanted, it does not
   exist here — use a fallback surface (step 4), never a guessed name.
   **Pick the SOURCE per signal by a strict 3-tier priority — reach for a lower
   tier only when no higher tier grounds the signal:** (1) the service's OWN domain
   metric it emits (a business counter / gauge / histogram) FIRST; (2) a generic
   OTel metric (e.g. `Count`/`Errors`) as a fallback; (3) a trace-span / log
   derivation (span `durationNano` percentiles, log counts) LAST.
3. **Pick the surface and set `queryLanguage` to match.** Metrics → **PromQL**; log
   or trace content → **SQL**. Metrics execute as NATIVE PromQL
   (`queryLanguage: "promql"`), NEVER SQL — there is **no**`metrics.default` SQL
   table; a SQL `FROM`is only`default`,`logs.default`, or`traces.default`. Set
   the panel's `queryLanguage` explicitly — it is **not** inferred from the query
   text, and a mismatch is a silent failure.
4. **Fall back to a lower tier before dropping.** The same RED signal can come from
   more than one place: request rate, error rate, and latency can be derived from
   **TRACES/spans (SQL)** — counts, error status, duration percentiles — and
   error/volume counts from **LOGS (SQL)**, not only from METRICS. If the metric you
   wanted is not grounded, re-express the SAME panel from a lower-tier surface
   rather than dropping it. A service with sparse metrics but rich traces/logs
   should still yield a FULL dashboard.
5. **Self-check the draft.** Scan every field / metric / label reference in the
   drafted `queryString` against the grounded lists. If a reference cannot be
   confirmed, re-ground; if it still cannot — on any surface — **drop that panel**
   rather than shipping an invented query. Optionally run the final windowless
   query once with a temporary time bound added, to confirm it returns rows.

**Bind panels to the grounded metric identity.** Vended AWS metrics carry an
instrumentation scope (`@instrumentation.@name="cloudwatch.aws/<service>"`) plus a
datapoint attribute (e.g. `FunctionName`); OTLP-native signals carry
`@resource.*`labels. Select the metric by name — use an`{__name__="<exact>"}`
matcher for a name that starts with a digit or contains `%`,`.`, or spaces (e.g.
`4xxErrors`,`traces.span.metrics.*`); a plain non-dotted name may be used bare.
A bare Prometheus `job=`/`service=` selector is an ungrounded reference — drop
panels that use one. The per-service scope + datapoint-attribute matrix lives in
[promql-metrics.md](query/promql-metrics.md).

**Pick the aggregation from the metric's type.** Read it off the grounded
instrument type and temporality — `sum_over_time(<m>[w])` for a DELTA Sum,
`rate()`/`increase()`for a CUMULATIVE Sum,`avg()`/`max()` for a Gauge, and
`histogram_quantile(0.99, rate(<base>[5m]))` for a Histogram (use the BASE metric
name — NO `_bucket`, NO`by (le)`). Never label an average as a percentile, and
never chart a counter as a raw value.

**Two grounding cautions:**

- **Keep every panel query WINDOWLESS.** Never embed a time window in the
  `queryString`— no`` `@timestamp` ``bound, no`NOW() - INTERVAL`, no PromQL
  range that pins an absolute time. The panel (or dashboard) `scope` drives the
  time range; a hard-coded window fights the time picker and freezes the panel.
  (This is the one place a dashboard query differs from an interactive one, which
  *requires* a time bound — so don't copy an interactive query verbatim.)
- **An empty series is often correct.** A signal that only exists under a specific
  configuration (an agent installed, request metrics enabled, a burstable
  instance) returns nothing when that condition is absent. Confirm a metric is
  expected to have data before making it a headline panel.

---

## 4. Author the panel bodies

This is the round-tripping JSON schema — the format a user hand-edits in the
source editor and the one the UI persists. Every field here survives save → reopen;
anything not in it is dropped on read. The whole object is what you serialize into
the API's `body` string (section 7).

### Top-level shape

```jsonc
{
  "panels": [ /* Panel[] — required, may be empty */ ],
  "scope": { "timeRange": { "start": "now-3h", "end": "now" } }  // optional
}
```

- **`panels`** is the only required key. Panels sit on a **fixed 60-column grid**;
  the column count is not a field and is not configurable.
- **`scope.timeRange`** is the window the whole dashboard opens under. Omit it to
  inherit whatever range is already active.

> There is no `views`, no`layout: { columns: 60 }`, no per-panel`id`, no
> `refreshInterval`, and no top-level`owner`. Older bodies that carried those are
> upgraded on read (`views`→`panels`, legacy relative ranges →`{ start, end }`,
> the rest dropped) — so a body you read back may differ from what was saved.
> Author new bodies in the `panels[]` form only.

### Panel

```jsonc
{
  "type": "explore",                 // required — selects the panel and its config shape
  "layout": { "x": 0, "y": 0, "w": 30, "h": 320 },  // optional — no layout ⇒ full-width (section 5)
  "title": "Read IOPS",              // optional
  "description": "…",                // optional, one line
  "config": { /* shape depends on type */ },
  "scope": { "timeRange": { "start": "now-7d", "end": "now" } }, // optional per-panel override
  "variant": "transparent"           // optional — drop the card frame (headings, spacers, prose)
}
```

Only `type`is required — a panel with no`layout` is accepted and renders
full-width, but its vertical placement relative to layout-carrying siblings is not
defined; the renderer does not reflow overlaps (section 5), so author `layout` on
every panel in a mixed body to keep placement deterministic. An untitled panel takes
a heading from its content. `variant`accepts`"transparent"` (drops the card frame)
or `"default"` (explicit no-op) — omit the key for the default card frame. Any other
value is one of the "bad values" that saves with HTTP 200 and blanks the whole canvas
(see "API save semantics" below); other `variant` values you read back in
product-authored bodies are private — do not author them.

### Scope and time range

`scope.timeRange` has the same shape at the dashboard and panel level; a panel's
scope overrides the dashboard's for that panel only (e.g. a 7-day baseline beside a
1-hour detail view).

```jsonc
"timeRange": { "start": "now-1h", "end": "now" }               // rolling window
"timeRange": { "start": "2026-01-01T00:00:00Z", "end": "now" } // growing window (since incident)
"timeRange": { "start": "2026-01-01T00:00:00Z",
               "end":   "2026-02-01T00:00:00Z" }               // fixed window
```

Each bound is independently an ISO-8601 instant, the literal `now`, or a relative
`now-<N><unit>`. Units:`m`minutes,`h`hours,`d`days,`w`weeks,`mo` months.
There is no seconds or years unit and no rounding syntax — use an absolute instant
for a calendar boundary. The scope drives a query's time range; never embed a
window in a `queryString` (section 3).

### Panel types

`alerts`·`explore`·`markdown`·`divider`·`spans`·`application-map` ·
`dashboards-list`·`investigation-list`·`dashboard`·`agent-kpi-strip` ·
`recent-error-traces-table`·`agent-health-table`·`agent-playground`. **Author
only these thirteen** — this is the public authoring contract. `dashboard` and
`agent-playground` are full-bleed surfaces (public and hand-authorable, but not
offered for free composition; a `dashboard`panel is always`x: 0, w: 60`). There
is no `navigation`type.`alert-detail`and`trace-details` are **withdrawn**: a
saved body that already holds one still reads back, but do not author them in a
new body — see below for the `dashboard`-panel replacement. Other product-authored
types you read back are private; leave them as they are and do not author new ones.
A missing or unrecognised `type` is not rejected at save — it is one of the "bad
values" that saves with HTTP 200 and blanks the canvas (see "API save semantics"
below).

#### explore — charts and query results (the workhorse)

```jsonc
"config": {
  "queryString": "sum by (FunctionName) (rate({__name__=\"Invocations\", \"@instrumentation.@name\"=\"cloudwatch.aws/lambda\"}[5m]))",
  "queryLanguage": "promql",      // 'sql' | 'promql' — REQUIRED; SET IT EXPLICITLY; not inferred; a mismatch silently blanks the panel
  "visualization": "line",         // REQUIRED; one of the nine below; missing or unknown silently blanks the panel (no 'table' fallback)
  "autoRun": true,                 // run on open — set this on any data panel
  "promqlQueryOptions": { "step": 300 },  // PromQL step in SECONDS (default 60)
  "chartOptions": { /* appearance — see below */ }
}
```

- **Always set `queryLanguage` explicitly** — it is **not** inferred from the query
  text; a mismatch is a silent failure. The telemetry source is the query's `FROM`
  clause (SQL) or metric selector (PromQL); there is no separate source field.
- **Always set `autoRun: true`** on a panel meant to show data without a click —
  otherwise it opens showing its query, not its result.
- **Match `step`to the range vector.** A`[5m]` window sampled at the default 60s
  over-samples 5×; set `promqlQueryOptions.step`to`300` (SECONDS).
- **`inputMode`.** Omit for a chart tile (the default). Set`"inputMode": "editor"`
  **only** when authoring a full Explore-surface panel — that is the one accepted
  value, and it is load-bearing on read (a saved Explore surface with `inputMode`
  dropped reopens as a tile).
- The `@`-labels are double-quoted PromQL selectors, so they are JSON-escaped
  (`\"`) once more inside the`queryString`; and because the whole body is itself
  passed to the API as a JSON **string**, it is escaped a third time on the wire —
  build the body as an object and let your JSON library serialize it (section 7)
  rather than hand-escaping.

#### markdown — formatted text

```jsonc
"config": { "content": "## On call\n\n1. Check error rate.\n2. Open the failing trace." }
```

Pair with `"h": "auto"`and`"variant": "transparent"` for prose that reads as
part of the canvas.

#### divider — collapsible section heading

```jsonc
"config": { "title": "Service health", "collapsed": false }
```

Always full width (`x: 0, w: 60`); give it a small fixed height (`40`). Groups the
panels beneath it, down to the next divider, into a collapsible section.

#### alerts

```jsonc
{ "type": "alerts", "config": { "state": "CRITICAL" } }  // OK | WARNING | CRITICAL | NODATA (the Omni alert states); omit for all. Not the classic alarm states `ALERT`/`INSUFFICIENT_DATA` — an unknown state value silently blanks the canvas
```

**One alert's detail** is not a panel type of its own any more — `alert-detail` is
withdrawn (readable, not authorable). Author a `dashboard` panel instead:

```jsonc
{ "type": "dashboard",
  "source": { "kind": "system", "id": "alert-details", "version": 1,
              "params": { "alertName": "checkout-error-rate-high", "alertId": "6c89…" } },  // alertName required; alertId optional
  "layout": { "x": 0, "y": 0, "w": 60, "h": "auto" } }
```

The required parameter is the alert's **name**, but alert names are **not** unique
within a space — two alerts can share one name. The stable identity is the
`alertId` (see [alerts.md](alerts.md)); pass it too so the panel is unambiguous.
Resolve a name to its `alertId`s with`ListAlerts`(`filterCriteria.names`) first,
and rename one via `UpdateAlert` if two collide.

#### application-map / spans

Both take a public `config`; either also renders correctly with no`config` and
picks up the dashboard's time range.

```jsonc
{ "type": "application-map", "config": { "focusServiceName": "checkout" } }  // opens focused on one service; a one-time opening intent the console drops on its next save
{ "type": "spans", "config": { "lens": "application",   // application | agent (default application)
                               "grain": "traces",       // application lens: traces | spans (default traces)
                               "agentGrain": "traces",  // agent lens: traces | sessions (default traces)
                               "agentName": "…" } }     // agent lens only: scope to one agent; absent = all
```

An absent or unrecognised selector falls back to its default. Everything else —
service/operation/status/duration/trace-id filters, camera, node selection, rail
state — is per-user console state, not saved.

#### dashboards-list

`"config": {}` — a list of the Space's saved dashboards.

#### one trace's detail — a `dashboard`panel, not`trace-details`

`trace-details` is a **withdrawn** panel type: a saved body that holds one still
reads back, but do not author it in a new body — like any unrecognised `type` it
saves with HTTP 200 and blanks the canvas. Author a `dashboard` panel whose
`source.id`is`trace-details`:

```jsonc
{ "type": "dashboard",
  "source": { "kind": "system", "id": "trace-details", "version": 1,
              "params": { "traceConfig": {
                "traceId": "…",                                    // required
                "startTime": 1730000000000, "endTime": 1730000600000,
                "initialMode": "waterfall",  // waterfall | graph | flame | raw (`flamegraph`is a legacy alias read as`graph`)
                "focusSpanId": "…" } } },    // optional — deep-link to a specific span
  "layout": { "x": 0, "y": 0, "w": 60, "h": "auto" } }
```

`startTime`/`endTime`are epoch **milliseconds** in`traceConfig` (not the panel
scope), fixed at author time. A pinned trace is useful only while it is still
retained — prefer a `spans` panel for a durable dashboard.

### Visualizations — exactly nine legal values

`line`·`area`·`bar`·`scatter`·`pie`·`table`·`number`·`solidgauge` ·
`heatmap`.

> `stacked-bar`,`single-metric`, and`donut`are **not** valid — use`bar` with a
> stacking flag, `number`, and`pie`respectively.`visualization` is REQUIRED and
> there is no fallback default that renders: a missing value, an unknown value such
> as `stacked-bar`, or the empty string`""` saves with HTTP 200 but silently blanks
> the panel at render.

**`number`tile trap (known product bug).** A`number` panel driven by a
`SELECT count(*) AS n`(or similar`COUNT(*)`) query currently renders the ROW
COUNT of the result set — usually `1` when the query aggregates to one row —
instead of the value in the aliased column. Author the query so the aggregate
value is the first column of the first row (e.g. `SELECT <aggregate_expression>`),
and reserve `COUNT(*)`-shaped queries for`table` panels until the bug is fixed.

Pick by signal kind:

| Signal | Visualization |
|--------|---------------|
| Time series, ≤ ~25 series, comparable units | `line` |
| Additive series / discrete buckets (2xx/4xx/5xx, per-AZ) | `bar`(stacked) or`area` |
| Correlation point cloud (no connecting line) | `scatter` |
| One number, with a delta | `number` |
| Resources ranked by a metric | `table` (default sort: descending on the primary signal) |
| Genuine part-of-whole | `pie` |
| A bounded ratio against thresholds (availability %) | `solidgauge` |

Two shapes authors most often get wrong — check them explicitly: a **scalar
aggregate** (one number, no `by`/ no`GROUP BY`over time) should be a`number`
tile, not a table; a **top-N ranking** (`ORDER BY … LIMIT`/`topk(...)`) should be
a `table`, not a line.

Anti-patterns: no `line`past ~25 series (use`topk(...)`or a`table`); don't
stack a `bar` whose series go negative; don't put two units on one chart — split
into two `w: 30`panels.`heatmap` does not yet ingest histogram-bucket output —
for a latency distribution use `line`with a`histogram_quantile`.

### Chart options

`chartOptions`sets appearance and is a discriminated union keyed on`view`, which
must match the panel's `visualization`(when both are present,`view` wins — so
setting only `visualization` is the simpler, recommended form).

```jsonc
"chartOptions": {
  "view": "line",
  "title": { "text": "Requests/sec", "show": true },
  "plotOptions": {
    "legend": { "show": true, "position": "bottom" },
    "yAxis": [ { "min": 0, "title": "req/s" } ]   // TUPLE of 1 or 2 axes (2nd = right-hand)
  }
}
```

- **Cartesian** (`line`/`area`/`bar`/`scatter`):`legend`,`stacking`,`xAxis`, and
  `yAxis` as a **tuple** of one or two axes (the second is the right-hand axis). Use
  `type: 'datetime'`for a time axis (not`'time'`).
- **`solidgauge`**:`yAxis`is an **object**`{ min, max }` (not a tuple), plus
  `plotBands: [{ from, to, color }]`.
- **`heatmap`**:`xAxis`/`yAxis`with`categories`, and`colorScale`.
- **`table`**:`hiddenColumns`,`summaryColumns`(`MIN`/`MAX`/`SUM`/`AVG`),
  `layout`(`horizontal`/`vertical`),`stickySummary`,`showTimeSeriesData`,
  `formatJson`(`true`|`'raw'`|`'raw-single-line'`). Column order is **not** a
  chart option — the console does not save it. `number`and`pie` take little
  beyond the base fields.
- **Stacking depends on the view.** For `line`/`area`, set
  `plotOptions.stacking: "normal"`(or`"percent"`) — an **enum**, not a boolean,
  keyed directly on `plotOptions`; it wins over the equivalent
  `plotOptions.style.lineOptions.stacked: true`. A **`bar`** panel does not read
  `stacking` at all — the only stacking field the bar renderer reads is
  `plotOptions.style.barOptions.stacked: true`. There is **no**`plotOptions.stacked`
  field; a flag placed there is an unknown key, silently dropped on save, and the
  chart will not stack.

### API save semantics — what happens to a body on read/write

The save API accepts any parseable body with **HTTP 200**. There is **no
server-side rejection** of malformed panels, unknown enum values, unknown keys, or
out-of-range coordinates, and **no toast or error** in the UI when a body is
unrenderable — a saved dashboard whose canvas renders as a blank page is
indistinguishable at the API from a valid one. Storage is verbatim:
`GetOmniDashboard` returns the body **byte-identical** to what was written; the
API neither rejects nor coerces it. (That is the *storage* path; the *renderer* is
what ignores unknown keys and blanks on bad values, below.) Consequences:

- **Do not rely on a 200 to confirm renderability.** Validate the body against this
  reference before the save call; a `200`+ a`dashboardId` proves only that the
  JSON parsed and persisted.
- **One bad value on one panel blanks the whole canvas.** A single unknown enum (a
  `variant`or`visualization`outside its legal set, an unknown`alerts` state), a
  negative `layout.x`,`x + w > 60`,`now-30s`/`now-1y` (no seconds/years unit), a
  missing `panels`key,`panels`set to an object, or a panel with no`type` —
  beside otherwise valid siblings — makes the whole dashboard render as an empty
  page. The valid siblings do not survive the bad neighbor.
- **A panel with no `layout` is accepted** and drawn full-width (it is NOT rejected).
- **Unknown or misspelled keys are ignored by the renderer** — including a
  correctly-placed field whose *name* is misspelled (e.g. `visualisation`). The key
  is stored verbatim and comes back on read, but the value never takes effect and
  nothing errors on save or on read. Check every key against this section.
- **`queryLanguage` mismatches are silent failures**, not errors. Set it per panel.
- **Dashboard names** (the API's `name`, not part of the body) must be 1–256 chars
  matching `^[a-zA-Z0-9_.@~()-]+$`. Nothing is trimmed: surrounding whitespace,
  spaces, `/`,`:`,`#`,`+`, accented letters and emoji all fail the pattern, and
  257+ chars fails the length check. The body itself must be 1–1,048,576 bytes
  once serialized.

---

## 5. Lay out on the 60-column grid

Assign each panel's `layout: { x, y, w, h }` so panels tile cleanly with no overlap
and no overflow. This is the single most error-prone part of a body.

### The two-unit rule (memorize this)

`x`/`w`and`y`/`h` do **not** share a unit:

| Field | Unit | Rule |
|-------|------|------|
| `x`| grid **column** | integer`0`–`59`;`x: 0` is the left edge |
| `w`| grid **columns** | integer`1`–`60`; **`x + w`must not exceed`60`** — nothing enforces this for you; an overflow saves with HTTP 200 and blanks the canvas |
| `y`| **pixels** | integer pixels from the top (`0` or greater), not a row index |
| `h`| **pixels** or`'auto'`| integer pixels within roughly`100`–`2000`(`divider` `40`is the sanctioned sub-100 row), or the literal`'auto'`; never fractional; never a relative CSS unit (`vh`/`%`/`vw`) |

Mixing the units (treating `y`as a row index, or`w` as pixels) is the most common
authoring bug. Prefer `'auto'` for content-sized panels (markdown, lists, nested
`dashboard` panels) and a fixed pixel height where the content needs one; a relative
CSS unit such as `'80vh'` is an unknown value that blanks the canvas.

### Width conventions

Every row MUST match one of the width-per-count patterns below. Author the correct
shape yourself — nothing re-shapes it for you.

| Row count | Width per panel (`w`) | Use for |
|-----------|-----------------------|---------|
| 1 panel | `60`| full-width strip (hero chart, table, status strip, divider, application-map,`dashboard`) |
| 2 panels | `30` each | two halves side-by-side (most time-series pairs) |
| 3 panels | `20` each | three thirds (read/write/idle, 2xx/4xx/5xx) |
| 4 panels | `15` each | four quarters (KPI row) |

**Hard rules — all MUST:**

- A row's widths sum to **EXACTLY 60**, with `x` as the cumulative sum from 0
  (`0, 30`;`0, 20, 40`;`0, 15, 30, 45`).
- Every panel in a row shares the **same `y`** AND the **same`h`**.
- **Never more than 4 panels in one row.** A 5th starts a new row below: 5 panels =
  3 then 2; 6 = 3+3; 7 = 4+3. Five across does not fit the 60-column grid and the
  overflow lands on top of its neighbours.
- **No mixed-width rows** except an intentional hero-supporting layout, which uses
  TWO rows: row 1 is one `w: 60`hero, row 2 is`w: 30`×2 or`w: 20`×3 supporting
  panels — never side-by-side with the hero.
- **No heterogeneous chart/table rows.** A `line`chart and a`table` on the same
  row read badly — split them into two rows (chart row above, table row below).

### Stacking rows with `y`

`y` is the pixel offset from the top and it orders rows. Give successive rows
**increasing `y`** equal to the running sum of prior row heights:

- KPI row (`h: 120`) at`y: 0`
- first chart row (`h: 320`) at`y: 120`
- next chart row at `y: 440`, and so on.

When a row uses `'auto'`heights, still give the next row a larger`y`; the renderer
resolves final positions from each row's height, so approximate but
monotonically-increasing `y` values are fine.

### Height guidance by panel kind

| Panel kind | Suggested `h` |
|------------|---------------|
| `number`KPI tile |`120` (short — one figure) |
| Time-series (`line`/`area`/`bar`/`scatter`) | ~`320` |
| `table`| ~`320`–`400`, taller for many rows |
| `pie`/`solidgauge`| ~`280`–`320` (roughly square reads best) |
| `divider`|`40`(always full width,`x: 0, w: 60`) |
| `dashboard`(nested system dashboard) |`'auto'`(always full width,`x: 0, w: 60`) |
| `markdown`runbook |`'auto'`(pair with`variant: 'transparent'`) |
| `application-map`/`spans`| full width, tall (~`480`) |

### Layout shortcuts

- **Full-width strip** — `{ x: 0, y: <row>, w: 60, h: <h> }`.
- **Two halves** — `{ x: 0, …, w: 30 }`and`{ x: 30, …, w: 30 }`, same`y`.
- **Three thirds** — `x: 0`,`x: 20`,`x: 40`, each`w: 20`, same`y`.
- **KPI row of four** then a wide chart — four tiles at `y: 0`,`w: 15`,
  `x: 0/15/30/45`,`h: 120`; one chart at`y: 120`,`x: 0`,`w: 60`,`h: 320`.
- **Divider-led section** — a full-width `divider`(`h: 40`) at the row's`y`, then
  the section's panels at a larger `y` beneath it.

### Overflow and overlap

- A panel that overflows the grid (`x + w > 60`) is never reflowed into what you
  meant — it saves with HTTP 200 and blanks the whole canvas (section 4, API save
  semantics). Keep `x + w <= 60` on every panel yourself.
- The renderer does not reflow overlaps. Two panels sharing a `y` must not share
  columns — give them non-overlapping `[x, x+w)` ranges. Follow the
  width-per-count patterns above and give each row a larger `y` and you will never
  overlap.

---

## 6. Troubleshooting

### A panel rendered empty

Work down this list in order; the first match is usually the cause.

1. **An ungrounded name.** A metric, field, or label that does not exist returns
   nothing, not an error. Re-run discovery (section 3) for exactly the names in
   the `queryString`; a`*_total`/`*_seconds` Prometheus-convention name, or a
   bare `job=`/`service=` selector, is the CloudWatch tell.
2. **`queryLanguage`mismatch.** A PromQL selector under`"queryLanguage": "sql"`
   (or SQL under `promql`) fails silently. Check the language against the text.
3. **A time window embedded in the query.** A `` `@timestamp` `` bound, a
   `NOW() - INTERVAL`, or an absolute PromQL range pins the panel to a window the
   time picker no longer covers. Remove it; the `scope` drives the range.
4. **The panel's or dashboard's `scope` excludes the data.** A fixed incident-window
   scope, or a per-panel override, can legitimately show nothing outside its range.
5. **`autoRun`is not`true`.** The panel opens showing its query, not its result —
   it looks empty until clicked.
6. **The metric selector's identity is wrong.** A vended metric without its
   `@instrumentation.@name` scope, or the wrong datapoint attribute
   (`FunctionName`vs.`ApiName`), matches nothing. Compare against the archetype
   identity forms and [promql-metrics.md](query/promql-metrics.md).
7. **The series is genuinely empty — and that is correct.** Conditional signals
   (`IteratorAge`for a non-stream consumer,`RunningTaskCount` without Container
   Insights, burst-credit metrics on a non-burstable instance) return nothing when
   the condition is absent. Say so, and either drop the panel or retitle it.
8. **A `step` far coarser than the window.** With a very large
   `promqlQueryOptions.step` over a short scope there may be no evaluation point.

### A field has no effect, or the canvas is blank

- **The field is not in the schema, or its name is misspelled.** Unknown keys are
  ignored by the renderer — the save succeeds, the key is stored verbatim, and the
  value simply never takes effect. Check each ineffective key's spelling against
  section 4. The frequent offenders: `plotOptions.stacked` (should be
  `plotOptions.stacking: "normal"`or`plotOptions.style.<view>Options.stacked`),
  `layout.columns`, per-panel`id`,`refreshInterval`,`owner`,`views`.
- **`inputMode` was omitted from an Explore-surface panel.** It reopens as a tile.
- **The whole canvas is blank after a 200.** Nothing was rejected — the save
  returned HTTP 200 — but one panel carries a bad value: a missing `panels` array, a
  panel without `type`, a withdrawn or private panel type, an unknown enum
  (`variant`,`visualization`,`alerts` state), a coordinate outside the grid rules
  (negative `x`,`x + w > 60`, a fractional or`vh`height), a`timeRange` bound with
  a seconds/years unit, a `source`on a non-`dashboard`panel, or a`dashboard` panel
  without one. The valid siblings do not render until it is fixed — validate each
  panel against section 4 to find the offender.
- **A panel is blank but the rest render.** A missing or invalid `visualization`
  (`stacked-bar`,`donut`,`single-metric`,`""`) does not fall back to`table` — it
  blanks that panel.
- **Legacy keys were rewritten.** `views`became`panels`, old relative ranges
  became `{ start, end }` — that is the read-time upgrade, not data loss.

### Reading back a body (pasted into chat, or fetched with GetOmniDashboard)

1. **Get the JSON.** From the API, `omniDashboard.body` is a JSON **string** —
   parse it before inspecting it. From a paste, strip any surrounding prose.
2. **Check the top level.** `panels`must be an array; note any`scope.timeRange`
   (a fixed absolute window means an incident dashboard).
3. **Walk each panel** and describe it in the user's terms — what it shows, from
   which telemetry, over what range — while checking, for each:
   `type`is one of the thirteen authorable types;`layout` uses the two units correctly
   and stays inside 60 columns; rows share `y`and`h`; for`explore`,
   `queryLanguage`matches the query text,`visualization` is one of the nine, the
   query is windowless, and every name in it is plausible for the grounded catalog;
   `chartOptions.view`matches`visualization`; no unknown keys.
4. **Explain the two silent failures** (unknown keys dropped; `queryLanguage` not
   inferred) whenever you find an instance of either, because the user will not
   have seen an error.
5. **Do not narrate the schema when the user asked what the dashboard shows** —
   lead with the panels' meaning; surface the defects as a short list after.

---

## 7. API reference

Five operations manage dashboards. They are exposed by the CloudWatch Omni service
(endpoint prefix `cloudwatch-omni`, SigV4 signing name`cloudwatch` — see
[programmatic-access.md](programmatic-access.md)) and reachable from the AWS CLI as
`aws cloudwatch-omni <kebab-case-operation>`, from every AWS SDK, or through an AWS
MCP `aws___call_aws` tool with the same operation and parameter names.

**Common to all five:**

- **Space-scoped.** `spaceId` (the Space's UUID) is required on every call. There
  is no account-wide list of dashboards — you list per Space.
- **The identity is `dashboardId`**, a system-minted lowercase UUID
  (`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`). The
  caller-supplied `name` is metadata, is **not** unique, and is **not** part of the
  id — renaming never changes the id or the ARN.
- **ARN:** `arn:<partition>:cloudwatch:<region>:<account-id>:omni-dashboard/<dashboardId>`
  — the `cloudwatch`vendor namespace with an`omni-dashboard/` resource type, the
  same convention as alerts. Neither the Space nor the name appears in it.
- **`body` is a string**, 1–1,048,576 bytes, containing the serialized JSON from
  section 4. The service stores it opaquely — it does not merge, reformat, or
  partially accept it — so validation of the panel schema happens when the UI reads
  it, not at the API. An API `ValidationException`on`body` is a length or type
  problem, not a panel-schema one.
- **`name`:** 1–256 chars,`^[a-zA-Z0-9_.@~()-]+$` (section 4's rule).
  **`description`:** 1–1024 chars, optional.
- **Errors** every operation can return: `ValidationException`,
  `AccessDeniedException`,`InternalServerException`,`ThrottlingException`.
  Per-operation additions are noted below.
- **Authorization** is the Space's access grants, exactly as for a console user. A
  correctly-signed call returning `AccessDeniedException` usually means the caller
  has no grant on the Space — check that before suspecting the request. The IAM
  action names are the operation names (`cloudwatch:CreateOmniDashboard`, etc.).

### CreateOmniDashboard

Creates a dashboard in a Space. Returns the full **`omniDashboard`** — read
`dashboardId`and`arn`from it; you do not need a follow-up`GetOmniDashboard`.

| Input | Required | Notes |
|---|---|---|
| `spaceId` | ✔ | The Space to create the dashboard in |
| `name`| ✔ | Display name, 1–256 chars,`^[a-zA-Z0-9_.@~()-]+$`. Not unique |
| `body`| ✔ | The serialized`{ "panels": [...] }` JSON, 1–1,048,576 bytes |
| `description` | | 1–1024 chars |
| `tags` | | Key/value map |
| `clientToken` | | Idempotency token — a retry with the same token returns the original result instead of creating a duplicate. SDKs and the CLI fill it automatically |

Errors beyond the common set: `ServiceQuotaExceededException` (the Space's
dashboard limit), `ResourceNotFoundException`(unknown Space),`ConflictException`.

```bash
# body.json holds the panels[] object from section 4; file:// passes its text as the string value
aws cloudwatch-omni create-omni-dashboard \
  --region us-east-1 \
  --space-id 3f2c1e9a-7b4d-4c0e-9a1b-2d3e4f5a6b7c \
  --name checkout-service-health \
  --description "RED golden signals for checkout" \
  --body file://body.json
```

Build `body.json` with a JSON library from the panel objects — do not hand-escape
the nested `\"` in PromQL selectors a second time; the CLI/SDK serializes the string
for the wire.

### GetOmniDashboard

Retrieves one dashboard **including its body**. This is the only way to read a
saved body — list results do not carry it.

| Input | Required |
|---|---|
| `spaceId` | ✔ |
| `dashboardId` | ✔ |

Returns **`omniDashboard`**:`dashboardId`,`arn`,`name`,`body` (a JSON string —
parse it), `createdBy`(the creating principal),`description`,`tags`,`createdAt`,
`updatedAt`. Read-only. Errors beyond the common set:`ResourceNotFoundException`.

```bash
aws cloudwatch-omni get-omni-dashboard --region us-east-1 \
  --space-id <spaceId> --dashboard-id <dashboardId> \
  --query 'omniDashboard.body' --output text > body.json
```

### ListOmniDashboards

Enumerates the dashboards in a Space, optionally filtered by name prefix, with
pagination.

| Input | Notes |
|---|---|
| `spaceId` | Required |
| `namePrefix`| 1–256 chars, same character set as`name`; matches names that start with it |
| `maxResults` | 1–100 per page |
| `nextToken` | Pagination token |

**Read the summaries from `items`** and page with`nextToken`—`items` is the only
list member the response carries. Each entry is an
`OmniDashboardSummary`:`dashboardId`,`arn`,`name`,`createdBy`,`description`,
`tags`,`createdAt`,`updatedAt`— **no`body`**. Because names are not unique, a
`namePrefix` (or an exact-name match on the client side) can return several
dashboards; this is the usual way to resolve a name to a `dashboardId` before
`Get`/`Update`/`Delete`. Follow`nextToken` rather than treating the first page as
the complete set. Errors beyond the common set: `ResourceNotFoundException`
(unknown Space).

```bash
aws cloudwatch-omni list-omni-dashboards --region us-east-1 \
  --space-id <spaceId> --name-prefix checkout- --max-results 50
```

### UpdateOmniDashboard

Modifies a dashboard in place, addressed by `dashboardId`. **PATCH semantics:**
only the fields you send change; an omitted field is left unchanged. Returns the
full updated **`omniDashboard`**, so you can confirm the result without a second
call. `@idempotent`.

| Input | Required | Notes |
|---|---|---|
| `spaceId` | ✔ | |
| `dashboardId` | ✔ | The dashboard to update |
| `body`| | Full replacement body, 1–1,048,576 bytes. There is no partial-panel patch — send the complete`panels[]` |
| `name` | | Renaming is supported; the id and ARN do not change |
| `description` | | 1–1024 chars |

`tags` cannot be changed through this operation. Errors beyond the common set:
`ResourceNotFoundException`,`ConflictException`,`ServiceQuotaExceededException`.

**To edit one panel:** `GetOmniDashboard`→ parse`body` → change the panel →
serialize → `UpdateOmniDashboard` with the whole body. Because a body is replaced,
not merged, an update built from a stale copy silently discards someone else's
edits — fetch immediately before you write.

**Confirm before updating.** Draft the exact change, state that `body` replaces the
whole panel set, and confirm with the user before calling.

```bash
aws cloudwatch-omni update-omni-dashboard --region us-east-1 \
  --space-id <spaceId> --dashboard-id <dashboardId> \
  --body file://body.json
```

### DeleteOmniDashboard

Permanently removes a dashboard. Returns an empty response.

| Input | Required |
|---|---|
| `spaceId` | ✔ |
| `dashboardId` | ✔ |

**Idempotent** — deleting a dashboard that has already been removed succeeds
without error (the operation does not return `ResourceNotFoundException`), so a
successful response does not prove the dashboard existed. Deletion cannot be undone;
if the body might be wanted later, `GetOmniDashboard` and keep it first.

**Confirm before deleting.** This is destructive and irreversible. Name the specific
dashboard (id and name) and confirm with the user before calling — never delete on
inference, and because a success does not tell you whether you deleted the one you
meant, confirm the target up front rather than checking after.

```bash
aws cloudwatch-omni delete-omni-dashboard --region us-east-1 \
  --space-id <spaceId> --dashboard-id <dashboardId>
```

### End-to-end: build, save, verify

1. Probe: `aws cloudwatch-omni list-spaces`— pick the`spaceId` (section 1).
2. Plan, ground, author, lay out (sections 2–5) → a `panels[]` object.
3. Serialize it to `body.json`;`create-omni-dashboard`with a valid`name`.
4. Read back with `get-omni-dashboard`, parse`body`, and run the read-back checks
   in section 6 — the API accepts any well-sized string, so this is where a
   panel-schema slip would surface.
5. Report the `dashboardId`,`arn`, and a one-line description of each panel.

**CLI says `cloudwatch-omni` is not a valid choice.** The local AWS CLI predates
Omni's service model; upgrade it. The failure is client-side argument parsing and
says nothing about whether Omni is enabled. `aws cloudwatch <omni-operation>`
will never work at any version — CloudWatch is a different service that
shares only the signing name.

---

## 8. Appendix — Archetype templates

When the ask names a known resource TYPE, start from its ready panel set below,
then **ground** every query (section 3) and **lay it out** (section 5). Build the
CORE subset by default and offer the optional-depth panels as a follow-up "add
section." Look up each panel's real metric and reading (gauge vs. counter, derived
formulas, whether a real percentile source exists) in
[promql-metrics.md](query/promql-metrics.md); the query strings are TEMPLATES — the
identity form is canonical, but the metric name and statistic MUST be grounded. If
a signal cannot be grounded, **drop that panel** and re-sequence `y` so no blank row
is left.

Every template binds to the `@`-label identity (section 3) — vended AWS metrics on
`@instrumentation.@name="cloudwatch.aws/<svc>"` + datapoint attribute, OTLP /
span-RED on `@resource.*`. Set`queryLanguage`explicitly,`autoRun: true` on every
data panel, and `promqlQueryOptions.step` to match the range vector; keep every
query windowless. `…` in a template stands for the identity labels shown in that
archetype's first row.

### Lambda

Serverless function — RED-shaped; scope `cloudwatch.aws/lambda`by`FunctionName`.
`Duration` is a gauge with no percentile label; the error-rate tile is the derived
`Errors / Invocations`.

**CORE (~8 panels — the default build):**

| Panel | Viz | Query template | Layout |
|-------|-----|----------------|--------|
| Invocations/s | `number`|`sum(rate({__name__="Invocations", "@instrumentation.@name"="cloudwatch.aws/lambda", FunctionName="<fn>"}[5m]))`|`{x:0,y:0,w:15,h:120}` |
| Error rate | `number`|`sum(rate({__name__="Errors", …, FunctionName="<fn>"}[5m])) / sum(rate({__name__="Invocations", …, FunctionName="<fn>"}[5m]))`|`{x:15,y:0,w:15,h:120}` |
| Throttles/s | `number`|`sum(rate({__name__="Throttles", …, FunctionName="<fn>"}[5m]))`|`{x:30,y:0,w:15,h:120}` |
| Concurrency | `number`|`max({__name__="ConcurrentExecutions", …, FunctionName="<fn>"})`|`{x:45,y:0,w:15,h:120}` |
| Invocation rate | `line`|`sum by (FunctionName) (rate({__name__="Invocations", …, FunctionName="<fn>"}[5m]))`|`{x:0,y:120,w:30,h:320}` |
| Errors/s | `line`|`sum by (FunctionName) (rate({__name__="Errors", …, FunctionName="<fn>"}[5m]))`|`{x:30,y:120,w:30,h:320}` |
| Duration (ms) | `line`|`{__name__="Duration", …, FunctionName="<fn>"}`|`{x:0,y:440,w:60,h:320}` |
| Recent errors | `table`(SQL) | scope to`/aws/lambda/<fn>`with a grounded log-group filter;`queryLanguage:'sql'`|`{x:0,y:760,w:60,h:360}` |

**Optional depth (follow-up):** Throttles `line`; Concurrent executions`line`;
Stream-consumer lag `line`(`IteratorAge` — only for a stream/event-source
consumer, empty otherwise). Append two-up (`w:30,h:320`) and re-sequence`y`.

### Kubernetes/EKS

OTLP-native — no vended scope. **RED** from the span metrics grouped by
`@resource.service.name`; **USE** from the OTLP Kubernetes resource metrics grouped
by `@resource.k8s.*`. The span-metric names, span-status attribute, and`k8s.*`
resource-metric names are ingestion-path-dependent — ground them against the live
catalog (section 3).

**CORE (~8 panels — the default build):**

| Panel | Viz | Query template | Layout |
|-------|-----|----------------|--------|
| Request rate | `number`|`sum(rate({__name__="traces.span.metrics.calls", "@resource.service.name"="<svc>"}[5m]))`|`{x:0,y:0,w:15,h:120}` |
| Error rate | `number`| ratio of`…calls, "@status.code"="ERROR"`to all calls |`{x:15,y:0,w:15,h:120}` |
| p99 latency | `number`|`histogram_quantile(0.99, rate({__name__="traces.span.metrics.duration", …}[5m]))`|`{x:30,y:0,w:15,h:120}` |
| Running pods | `number`|`count({"k8s.pod.phase", "@resource.k8s.namespace.name"="<ns>", "@resource.k8s.deployment.name"="<deploy>"})`|`{x:45,y:0,w:15,h:120}` |
| Request rate | `line`|`sum by ("@resource.service.name") (rate({__name__="traces.span.metrics.calls", …}[5m]))`|`{x:0,y:120,w:30,h:320}` |
| Errors by status | `bar`|`sum by ("@status.code") (rate({__name__="traces.span.metrics.calls", …}[5m]))`|`{x:30,y:120,w:30,h:320}` |
| Latency p50/p90/p99 | `line`|`histogram_quantile(0.99, rate({__name__="traces.span.metrics.duration", …}[5m]))`— one series per quantile (0.50, 0.90, 0.99) |`{x:0,y:440,w:60,h:320}` |
| Top services by errors | `table`|`topk(10, sum by ("@resource.service.name") (rate({__name__="traces.span.metrics.calls", "@status.code"="ERROR"}[5m])))`|`{x:0,y:760,w:60,h:360}` |

**Optional depth (follow-up "infra / USE health"):** Pod CPU usage, Pod memory
usage, Container restarts — grouped by `@resource.k8s.*`(`k8s.pod.cpu.usage`,
`k8s.pod.memory.usage`,`increase(k8s.container.restarts[15m])`). Append two-up and
re-sequence `y`.

### RDS/database

Infrastructure resource — USE/saturation; scope `cloudwatch.aws/rds` by
`DBInstanceIdentifier`. Reading rules: IOPS is already per-second → never`rate()`;
latency is in seconds → × 1000 for ms; mind `FreeStorageSpace`/`FreeableMemory`
polarity (higher is healthier).

**CORE (~7 panels — the default build):**

| Panel | Viz | Query template | Layout |
|-------|-----|----------------|--------|
| CPU % | `number`|`max({__name__="CPUUtilization", "@instrumentation.@name"="cloudwatch.aws/rds", DBInstanceIdentifier="<db>"})`|`{x:0,y:0,w:15,h:120}` |
| Connections | `number`|`max({__name__="DatabaseConnections", …, DBInstanceIdentifier="<db>"})`|`{x:15,y:0,w:15,h:120}` |
| Free storage | `number`|`min({__name__="FreeStorageSpace", …, DBInstanceIdentifier="<db>"})`|`{x:30,y:0,w:15,h:120}` |
| Read latency (ms) | `number`|`max({__name__="ReadLatency", …, DBInstanceIdentifier="<db>"}) * 1000`|`{x:45,y:0,w:15,h:120}` |
| CPU % | `line`|`{__name__="CPUUtilization", …, DBInstanceIdentifier="<db>"}`|`{x:0,y:120,w:30,h:320}` |
| Connections | `line`|`{__name__="DatabaseConnections", …, DBInstanceIdentifier="<db>"}`|`{x:30,y:120,w:30,h:320}` |
| Top instances by CPU | `table`|`topk(10, max by (DBInstanceIdentifier) ({__name__="CPUUtilization", …}))`|`{x:0,y:440,w:60,h:360}` |

**Optional depth (follow-up "infra / USE health"):** Read IOPS `line`; Read latency
(ms) `line`; add the`WriteIOPS`/`WriteLatency` counterparts for a full
read+write view. Append two-up and re-sequence `y`.

### ECS/web service

Cross-signal — **USE** from the ECS service tier combined with **RED** from the
load balancer in front (or from Application Signals). Identity + reading rules: ECS
scopes by `ClusterName`+ a non-empty`ServiceName`; ALB`TargetResponseTime` is a
gauge in seconds with no percentile label; the target status-code metrics carry the
`_Count` suffix.

**CORE (~7 panels — the default build; this archetype has no ranked table):**

| Panel | Viz | Query template | Layout |
|-------|-----|----------------|--------|
| Request rate | `number`|`sum(rate({__name__="RequestCount", "@instrumentation.@name"="cloudwatch.aws/applicationelb", LoadBalancer="<lb>"}[5m]))`|`{x:0,y:0,w:15,h:120}` |
| 5xx rate | `number`|`sum(rate({__name__="HTTPCode_Target_5XX_Count", …, LoadBalancer="<lb>"}[5m]))`|`{x:15,y:0,w:15,h:120}` |
| Peak response (ms) | `number`|`max({__name__="TargetResponseTime", …, LoadBalancer="<lb>"}) * 1000`|`{x:30,y:0,w:15,h:120}` |
| Service CPU % | `number`|`max({__name__="CPUUtilization", "@instrumentation.@name"="cloudwatch.aws/ecs", ClusterName="<cluster>", ServiceName="<svc>"})`|`{x:45,y:0,w:15,h:120}` |
| Request rate | `line`|`sum(rate({__name__="RequestCount", …, LoadBalancer="<lb>"}[5m]))`|`{x:0,y:120,w:30,h:320}` |
| Status codes | `bar`|`sum by (__name__) (rate({__name__=~"HTTPCode_Target_..._Count", …, LoadBalancer="<lb>"}[5m]))`|`{x:30,y:120,w:30,h:320}` |
| Response time (ms) | `line`|`{__name__="TargetResponseTime", …, LoadBalancer="<lb>"} * 1000`|`{x:0,y:440,w:60,h:320}` |

**Optional depth (follow-up "infra / USE health"):** Memory util % `line`; Running
tasks `line`(`RunningTaskCount` — needs ECS Container Insights or OTel enrichment,
empty otherwise). If the space runs Application Signals, swap the RED panels for
`Service`/`Fault`/`Error`and the availability formula`(1 − Fault/Total) × 100`.
Append two-up and re-sequence `y`.

### API Gateway

Request-serving — RED. Identity split: REST v1 on `ApiName`with`4XXError` /
`5XXError`, HTTP v2 on`ApiId`with`4xx`/`5xx`; gateway overhead is the formula
`Latency − IntegrationLatency`.

**CORE (~8 panels — the default build):**

| Panel | Viz | Query template | Layout |
|-------|-----|----------------|--------|
| Request count/s | `number`|`sum(rate({__name__="Count", "@instrumentation.@name"="cloudwatch.aws/apigateway", ApiName="<api>"}[5m]))`|`{x:0,y:0,w:15,h:120}` |
| 5xx rate | `number`|`sum(rate({__name__="5XXError", …, ApiName="<api>"}[5m]))`|`{x:15,y:0,w:15,h:120}` |
| 4xx rate | `number`|`sum(rate({__name__="4XXError", …, ApiName="<api>"}[5m]))`|`{x:30,y:0,w:15,h:120}` |
| Peak latency (ms) | `number`|`max({__name__="Latency", …, ApiName="<api>"})`|`{x:45,y:0,w:15,h:120}` |
| Request count | `line`|`sum(rate({__name__="Count", …, ApiName="<api>"}[5m]))`|`{x:0,y:120,w:30,h:320}` |
| Errors 4xx/5xx | `bar`|`sum by (__name__) (rate({__name__=~"[45]XXError", …, ApiName="<api>"}[5m]))`|`{x:30,y:120,w:30,h:320}` |
| Latency (ms) | `line`|`{__name__="Latency", …, ApiName="<api>"}`|`{x:0,y:440,w:60,h:320}` |
| Top resources by 5xx | `table`|`topk(10, sum by (Resource) (rate({__name__="5XXError", …, ApiName="<api>"}[5m])))`|`{x:0,y:760,w:60,h:360}` |

**Optional depth (follow-up "per-service latency"):** Integration latency (ms)
`line`(`IntegrationLatency`) — chart it beside`Latency` so the gap reads as
gateway overhead. Append two-up and re-sequence `y`.
