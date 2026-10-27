# Exploring Traces in Omni

Recipes for working with whole traces and AI-agent spans on `traces.default`: fetching one
trace, reading where its time went or why it failed, comparing runs, and finding traces by
the pattern of their spans. The SQL dialect, quoting, time bounds and schema discovery are in
[sql-logs-traces.md](sql-logs-traces.md); this file assumes them. Scoring traces and reading
stored evaluation scores are in [agent-evaluation.md](../agent-evaluation.md).

---

## 1. The span fields a trace is built from

These are the OTel span fields as Omni stores OTLP spans. Only the `@`-prefixed system fields
are guaranteed on every record (see [sql-logs-traces.md](sql-logs-traces.md)); confirm the
rest with `EXPLAIN (ANALYZE_FIELDS)` before presenting them as present.

| Field | What it holds |
|---|---|
| `traceId`, `spanId` | The trace and span ids. A trace id is 32 hex characters. |
| `parentSpanId` | The parent span's id. The **root** span has none (NULL or empty). |
| `name` | The operation name (a route, a tool, a model call). |
| `kind` | The OTel **SpanKind** — the span's role on the wire: `SERVER`, `CLIENT`, `INTERNAL`, `PRODUCER`, `CONSUMER` (or the numeric / `SPAN_KIND_*` encodings). It is **not** a status and **not** the agent role; never read failure from it. |
| `status['code']` | The span status: ERROR (`2` / `ERROR` / `STATUS_CODE_ERROR`), OK, or UNSET. See "Finding failed spans" in [sql-logs-traces.md](sql-logs-traces.md). |
| `startTimeUnixNano`, `endTimeUnixNano` | Start and end in epoch nanoseconds. `` `@timestamp` `` is the **end** time. Order spans chronologically by `startTimeUnixNano`. |
| `durationNano` | Duration in nanoseconds, string-typed: `CAST(durationNano AS DOUBLE) / 1e9` is seconds. |
| `resource['attributes']['service.name']` | The service or agent that emitted the span. |

### AI-agent span attributes

Agent frameworks record the agent role, tool, payloads and token usage as span attributes.
Two naming families are common — OpenInference and OTel GenAI semantic conventions — and an
agent usually emits one of them, so **confirm which with `EXPLAIN (ANALYZE_FIELDS)` scoped to
that agent's spans** before building a query on them.

| Meaning | OpenInference / AWS | OTel GenAI |
|---|---|---|
| Agent role of the span (`AGENT`, `LLM`, `TOOL`, …) | `attributes['openinference.span.kind']`, `attributes['aws.genai.span_kind']` | `attributes['gen_ai.operation.name']` — `invoke_agent`, `chat` / `text_completion` / `generate_content` (an LLM call), `execute_tool` |
| Tool name | `attributes['tool.name']` | `attributes['gen_ai.tool.name']` |
| Input / output text | `attributes['input.value']`, `attributes['output.value']` | `attributes['gen_ai.input_value']`, `attributes['gen_ai.output_value']`; message arrays `gen_ai.input.messages` / `gen_ai.output.messages` |
| Token usage (LLM spans) | `attributes['llm.token_count.prompt']`, `attributes['llm.token_count.completion']` | `attributes['gen_ai.usage.input_tokens']`, `attributes['gen_ai.usage.output_tokens']` |
| Model | — | `attributes['gen_ai.request.model']`, `attributes['gen_ai.response.model']` |
| Session | `attributes['session.id']` | `attributes['session.id']` |

A tool span is any span whose role attribute says TOOL (`openinference.span.kind` or
`aws.genai.span_kind` = `'TOOL'`) or whose `gen_ai.operation.name` is `'execute_tool'`; when
the agent's family is not yet known, match all three. Token counts may be ingested as
strings — `TRY_CAST(... AS BIGINT)` before summing. Report a span that has no input, output
or token attribute as having none; never fill one in.

---

## 2. Fetching one trace

Every trace query needs a `` `@timestamp` `` bound, and a span is stamped with its **end**
time, so choose the window deliberately:

- **The user gave a time** ("around 14:05 today"): start a few minutes before it and end
  after it by at least the longest span duration you expect (a long agent run can last many
  minutes). Use absolute bounds with `to_timestamp_nanos`.
- **Only an id:** start with a recent window (the last hour, then the last day) and widen
  step by step only if the trace is not found. Do not open with a multi-day scan.
- **Say which window you used**, and when you widened it, the new range.

```sql
SELECT spanId, parentSpanId, name, kind, status['code'] AS status_code,
       startTimeUnixNano, CAST(durationNano AS DOUBLE) / 1e9 AS duration_s,
       resource['attributes']['service.name'] AS service
FROM traces.default
WHERE `@timestamp` BETWEEN to_timestamp_nanos('2026-08-20T14:00:00.000Z')
                        AND to_timestamp_nanos('2026-08-20T14:30:00.000Z')
  AND traceId = '<32-hex trace id>'
ORDER BY startTimeUnixNano ASC
```

Rebuild the tree from `spanId` → `parentSpanId` (the root has no parent). If the trace is
not in the window, it is a window problem first: widen it before concluding the trace does
not exist.

**Large payloads.** Agent spans can carry long prompts and outputs. Show a short excerpt
(for example the first few hundred characters, with `left(...)` or `substr(...)`) and say it
is truncated, rather than pasting whole payloads.

**Payloads can be sensitive.** Inputs and outputs are the agent's real conversations and can
contain personal data, credentials or business content. Show only the part the question
needs, mask any value that looks like a secret or credential instead of echoing it, and do
not copy payloads into anything persistent (a dataset, a dashboard, a saved view) unless the
user asks.
When the user does ask to persist payloads, redact secrets and credentials before writing,
tell the user that the destination now holds conversation data with the same sensitivity
and the same readers as that store, and recommend encryption at rest with a customer-managed
KMS key where the destination offers one (for example `--kms-key-id` on the evaluation
results log group in [agent-evaluation.md](../agent-evaluation.md)); AWS API calls are
already encrypted in transit with TLS.

> **One trace by id — state ALL of this in the answer, with the queries shown:** the
> attribute check (`EXPLAIN (ANALYZE_FIELDS)` on the agent's spans) when the answer relies on
> agent attributes; the fetch query with its window, and that the window runs past the
> request because `` `@timestamp` `` is a span's END time; the tree rebuilt from `spanId` /
> `parentSpanId`; durations converted from nanoseconds; long payloads shown as short,
> truncated excerpts with secrets masked; and, for every span shown, which of its input,
> output or token fields are absent.

---

## 3. Reading one trace

### Where the time went

- The trace's total is the **root span's** duration.
- Express each child's time as a share of the root's duration. Children nest and can run
  concurrently, so their shares do **not** add up to 100%; for a breakdown that does, use
  **self-time** — a span's duration minus the time covered by its children.
- Name the longest child span and its service (`resource['attributes']['service.name']`),
  and follow the critical path down: the slow step is usually the deepest long span, not the
  root that waited on it.

> **Where the time went — state in the answer:** the fetch window and the end-time reason
> for its upper bound; the root span as the total; each child's share of the root, with the
> note that overlapping children do not sum to 100% (or self-time when a full breakdown is
> wanted); and the longest child with its service.

### Why it failed

- Find the failing spans by **status** (`status['code']` ERROR, normalised as in
  [sql-logs-traces.md](sql-logs-traces.md)), never by `kind`. UNSET is not a failure.
- Follow the error to the **deepest** failing span — the root of a failed request is
  usually ERROR only because a child failed, and blaming it hides the cause.
- Read the reason: the failing span's status message, and any recorded **exception**. OTel
  records an exception as a span event named `exception` with `exception.type`,
  `exception.message` and `exception.stacktrace`. Where those land in the record depends on
  how the spans were ingested, so find them with `EXPLAIN (ANALYZE_FIELDS)` or the span's
  `` `@record` `` rather than assuming a path. Corroborate with
  `attributes['http.response.status_code']` or `attributes['rpc.grpc.status_code']`.
- Give concrete next steps tied to what the failing span shows (the dependency that timed
  out, the input that was rejected, the code path that threw).
- **If no message or exception was recorded,** say so, and recommend better error
  reporting in the code: record exceptions on the active span and set a descriptive status
  message, so the next failure explains itself. Do not invent a cause.

> **Why a trace failed — state ALL of this in the answer**, including before any result is
> back: failure is read from `status['code']` (never `kind`; UNSET is not a failure); the
> deepest failing span is the origin; the reason comes from its status message and exception
> event (`exception.type` / `.message` / `.stacktrace`); the likely fixes for the common
> failure shapes you would look for (a downstream timeout, a rejected input, an unhandled
> exception); and the fallback for a trace that recorded no message or exception — recording
> exceptions on spans and setting a status message. When the spans show the cause, **close
> with the fix for that cause**: the code or configuration change at the failing span (a
> missing-value check and the right error status for bad input, a timeout or retry setting
> for a slow dependency), and how to confirm it. Give that fix from this trace's evidence
> now; checking more traces for scope is an offer to add after it, not a reason to hold it back.

### Comparing two runs

Fetch both traces, each with its own window (section 2), and walk them side by side in
`startTimeUnixNano` order, aligning the LLM and tool calls. Compare:

- **Latency** — the root durations, then which steps account for the difference (an extra
  tool call, a retried step, a slower model call).
- **Tokens** — the LLM spans' token attributes (section 1), per call and in total, and what
  explains a change (more LLM calls, a longer context, a different model).
- **Quality** — stored evaluation scores are records in `logs.default` keyed by `traceId`,
  never span attributes; read them as in [agent-evaluation.md](../agent-evaluation.md)
  section 7. If neither trace has a stored score, say so and offer to score both; do not
  grade the runs yourself.

> **Comparing runs — state ALL of this in the answer**, with the queries shown: both fetches
> with their own windows; the step-by-step walk in start-time order with LLM and tool calls
> aligned; latency compared on the root spans (`durationNano` in nanoseconds, cast) and the
> difference attributed to specific steps; tokens compared from the LLM spans' usage
> attributes; and quality from the stored `logs.default` scores, or an offer to score both
> when none exist.

### Why a trace scored badly

Read the trace's evaluation records from `logs.default` (score, label, and the evaluator's
explanation; skip errored records; mind each evaluator's polarity — all in
[agent-evaluation.md](../agent-evaluation.md) section 7). Then fetch the trace's spans and
tie each explanation to the span it describes: the LLM output that was unhelpful or wrong,
the tool that was chosen badly or not called, the retrieval that returned nothing useful.
Propose a change aimed at that span — the system prompt, a tool's description or schema,
retrieval, or the orchestration — and how to confirm it worked (re-score the trace, or run a
regression dataset).

> **Why a trace scored badly — state ALL of this in the answer:** each evaluator's score,
> label and explanation as read from `logs.default` (never a score of your own), with
> errored records set aside rather than read as low scores and each score read by its
> polarity; the specific span each explanation points to; the change proposed for that span
> (prompt, tool description or schema, retrieval, orchestration); and how to verify it —
> re-scoring the trace or a regression dataset.

---

## 4. Finding traces by their spans

These questions span many traces, so scope them to the agent
(`resource['attributes']['service.name']`) and a bounded window, and state the window.

### Traces with several tool calls, or a tool repeated

Count tool spans **per trace** (and per tool, for repeats). Project nested attributes to
plain aliases in a CTE first — then group and filter on the aliases:

```sql
WITH tool_spans AS (
  SELECT traceId,
         COALESCE(attributes['tool.name'], attributes['gen_ai.tool.name']) AS tool,
         upper(TRY_CAST(status['code'] AS VARCHAR)) AS status_code
  FROM traces.default
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '12 HOURS' AND NOW()
    AND resource['attributes']['service.name'] = '<agent service.name>'
    AND (attributes['openinference.span.kind'] = 'TOOL'
         OR attributes['aws.genai.span_kind'] = 'TOOL'
         OR attributes['gen_ai.operation.name'] = 'execute_tool')
)
SELECT traceId, tool, COUNT(*) AS calls,
       COUNT(*) FILTER (WHERE status_code IN ('2', 'ERROR', 'STATUS_CODE_ERROR')) AS failed_calls
FROM tool_spans
GROUP BY traceId, tool
HAVING COUNT(*) >= <N>   -- N = the repeat count the user asked about
ORDER BY calls DESC
```

That query answers "the same tool called N or more times". For "traces with more than one
tool call" (any tools), group by the trace alone over the same CTE:

```sql
SELECT traceId, COUNT(*) AS tool_calls
FROM tool_spans
GROUP BY traceId
HAVING COUNT(*) > 1
ORDER BY tool_calls DESC
```

The `failed_calls` column separates **retries** — a tool called again after its previous
call failed — from legitimate repeated calls with successful statuses; say which each
matching trace is.

> **Finding traces by their tool calls — state ALL of this in the answer:** the agent scope
> and the window used; how tool spans are recognised (the role attribute the data carries);
> the grouping (per trace, or per trace and tool) and its threshold; that the result is
> reported as the number of matching traces with their trace ids (and, for repeats, the tool
> and its count, retry or not); that an empty result is followed by one wider window, named;
> and an offer to save the matching traces as an evaluation dataset or to score them —
> offered, not done.
>
> Close every answer in this section (several tool calls, a repeated tool, failed tool calls,
> slowest traces) with both of these, even when no query could run: **the result line** —
> `N traces matched: <ids>`, or `none matched in <window>; widened to <wider window>: <result>`,
> or, when the query has not run, exactly what that line will report, including the wider
> window you will try if nothing matches — and **the offer** —
> save the matching traces as an evaluation dataset, or score them, on the user's go-ahead.

### Traces where a tool call failed

Open with the schema caveat, as for any failed-span question ("Finding failed spans" in
[sql-logs-traces.md](sql-logs-traces.md)): show the `EXPLAIN (ANALYZE_FIELDS)` check of the
status field and the tool-span attribute first, then the filter. Return one row per failing
call with the trace, the tool and the reason:

```sql
SELECT DISTINCT traceId,
       COALESCE(attributes['tool.name'], attributes['gen_ai.tool.name']) AS tool,
       status['message'] AS status_message
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND (attributes['openinference.span.kind'] = 'TOOL'
       OR attributes['aws.genai.span_kind'] = 'TOOL'
       OR attributes['gen_ai.operation.name'] = 'execute_tool')
  AND upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')
```

Add the agent's `resource['attributes']['service.name']` when the user named one. The same
reporting rules apply (section 5): an empty result means check the field names and status
encodings, then widen once and say so — and the answer closes with the result line and the
offer, as in the callout above.

### Trace-level latency ("the slowest traces")

A trace's latency is its **root span's** duration (or the longest span per `traceId` when
the root is missing). Rank traces, not spans — ranking raw spans lets one slow trace fill
several places:

```sql
SELECT traceId, resource['attributes']['service.name'] AS service, name,
       CAST(durationNano AS DOUBLE) / 1e9 AS duration_s
FROM traces.default
WHERE `@timestamp` BETWEEN date_trunc('day', NOW()) AND NOW()
  AND (parentSpanId IS NULL OR parentSpanId = '')
  AND durationNano IS NOT NULL
ORDER BY CAST(durationNano AS DOUBLE) DESC
LIMIT 10
```

That query skips any trace whose root span was not ingested. When the root may be missing,
or the result has fewer traces than expected, rank by the longest span per trace instead;
for a well-formed trace the root is the longest span, so the two agree:

```sql
SELECT traceId, MAX(CAST(durationNano AS DOUBLE)) / 1e9 AS duration_s
FROM traces.default
WHERE `@timestamp` BETWEEN date_trunc('day', NOW()) AND NOW()
  AND durationNano IS NOT NULL
GROUP BY traceId
ORDER BY duration_s DESC
LIMIT 10
```

**"Today" is a calendar day, not the last 24 hours.** Bound it from the start of the day
(`date_trunc('day', NOW())`, which is midnight UTC, or an explicit
`to_timestamp_nanos('<date>T00:00:00.000Z')`), and state the timezone. If the user is in
another timezone, shift the bound to their midnight and say so.

> **Slowest traces — state in the answer:** the start-of-day bound and its timezone; that
> traces are ranked by the root span (one row per trace); the cast and NULL exclusion; and
> the summary you give from the rows (section 5) — the latency range, where the slow traces
> concentrate, the recurring bottleneck and its share, and outliers kept apart — with an
> offer to dig into any of them.

### Field discovery for traces

"What fields are on my traces" is answered per agent or service, because every application
records different attributes and the union over a whole Space is noise:

- Run `EXPLAIN (ANALYZE_FIELDS)` over `traces.default` with a `WHERE` on the service and a
  bounded window. `ListTelemetryFields` with `telemetryType` `TRACES` lists the Space's trace
  fields, but it takes no service filter, so it cannot narrow to one agent.
- If the user named no agent or service, ask which one, and offer to list the services that
  have recent spans.
- Present the result grouped as span system fields (section 1), resource attributes
  (`resource['attributes'][...]`), and span attributes (`attributes[...]`), with sample
  values, and say that the fields depend on what each application instrumented.

> **Fields on traces — state ALL of this in the answer:** the scoped `EXPLAIN
> (ANALYZE_FIELDS)` query (service filter and window); that `ListTelemetryFields` cannot be
> scoped to one service; the three groups with sample values; that only the `@` fields are
> guaranteed and everything else depends on instrumentation; and a direct question asking
> which agent or service to look at, when none was named.

---

## 5. Reporting

- **Lead with the finding, not the rows.** For a set of traces: the range (fastest to
  slowest), where they concentrate (which agent or service), the recurring bottleneck step or
  tool and its share of the time, and any one-off outliers (a cold start, a single retry)
  called out separately from the pattern. Offer to dig into a trace.
- **List the trace ids the user asked to see.** When the request is to find or show traces,
  give the matching count and the ids. (When resolving ids only to hand them to an
  evaluation or dataset helper, follow [agent-evaluation.md](../agent-evaluation.md)
  instead.)
- **An empty result is not an answer yet.** Check the field names and the window, widen the
  window once, and say what you searched before reporting that nothing matched.
- **Offer the next step; do not take it.** Matching traces can be saved as an evaluation
  dataset or scored — offer both, and do neither without the user's go-ahead (dataset writes
  need confirmation; see [agent-evaluation.md](../agent-evaluation.md)).
- **When you cannot run the query,** show it and say what you would read from the result.
  Never report spans, counts, durations or causes you did not get from the data.

---

## 6. Agent sessions, cost, and what changed

Questions about an agent's behaviour over many traces. Scope every query to the agent's
`resource['attributes']['service.name']` and a bounded window, and state both. Quality scores
behind any of these live in `logs.default` and are read as in
[agent-evaluation.md](../agent-evaluation.md) section 7; never grade the agent yourself.

### Sessions

A session is the set of traces that share `attributes['session.id']`. Confirm the agent emits
it with `EXPLAIN (ANALYZE_FIELDS)` on its spans before grouping. One row per session:

```sql
SELECT attributes['session.id'] AS session_id,
       COUNT(DISTINCT traceId) AS traces,
       MIN(TRY_CAST(startTimeUnixNano AS BIGINT)) AS first_start_ns,
       MAX(TRY_CAST(endTimeUnixNano AS BIGINT)) AS last_end_ns,
       (MAX(TRY_CAST(endTimeUnixNano AS BIGINT)) - MIN(TRY_CAST(startTimeUnixNano AS BIGINT))) / 1e9 AS duration_s,
       SUM(TRY_CAST(COALESCE(attributes['gen_ai.usage.input_tokens'], attributes['llm.token_count.prompt']) AS BIGINT))
         FILTER (WHERE attributes['gen_ai.operation.name'] IN ('chat', 'text_completion', 'generate_content')
                     OR attributes['openinference.span.kind'] = 'LLM'
                     OR attributes['aws.genai.span_kind'] = 'LLM') AS input_tokens,
       SUM(TRY_CAST(COALESCE(attributes['gen_ai.usage.output_tokens'], attributes['llm.token_count.completion']) AS BIGINT))
         FILTER (WHERE attributes['gen_ai.operation.name'] IN ('chat', 'text_completion', 'generate_content')
                     OR attributes['openinference.span.kind'] = 'LLM'
                     OR attributes['aws.genai.span_kind'] = 'LLM') AS output_tokens,
       COUNT(*) FILTER (WHERE upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')) AS error_spans
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND resource['attributes']['service.name'] = '<agent service.name>'
  AND attributes['session.id'] IS NOT NULL
GROUP BY attributes['session.id']
ORDER BY last_end_ns DESC
LIMIT 50
```

Tokens are summed over LLM spans only: some frameworks also record a request's accumulated
usage on the agent span, so summing every span counts the same tokens twice.

If the agent's spans carry no `session.id`, the telemetry cannot group by session: say so and
name the gap (the framework or the code has to set `session.id` on its spans). Do not
substitute the trace id, a user id, or a time bucket and call the result sessions.

### Walking one session step by step

Fetch every span with that `session.id` in a bounded window, ordered by `startTimeUnixNano`,
and walk it as a sequence of LLM decisions, tool calls, and tool results (section 1 for the
role attributes). For a session that loops, report where the repetition starts, what repeats
(the same tool with the same arguments, or the same prompt), how many iterations ran, and
what kept it going: a tool that kept failing and was retried, or an observation that never
changed so the model never reached a stop condition. Tie the fix to that cause: a maximum
iteration or tool-call cap in the orchestration, handling of the tool's error so the model
sees a usable result, or a clearer tool description or stop instruction.

### Token cost

The spans carry tokens, not money: what a token costs depends on the model, and hosting,
memory and tool backends do not appear in them at all. Rank the agent's traces by the input
and output tokens of their LLM spans, open the heaviest few, and match what you see to a fix:

| What the heavy trace shows | Change to propose |
|---|---|
| The prompt size climbs call after call | Cap or summarise conversation history |
| Tool results are pasted back to the model in full | Trim or summarise tool output before it returns |
| The same long system prompt rides on every call | Shorten it, or use prompt caching where the model supports it |
| More LLM calls than the task needs (re-planning, retries) | Tighten orchestration; fix the tool error that triggers retries |
| A large model doing routine steps | Route those steps to a smaller model |

Confirm a change by comparing token totals and the stored evaluation scores for the same kind
of traffic before and after, so a saving does not hide a quality drop.

### Signals the telemetry may not record

Guardrail interventions, deploys, prompt or knowledge-base updates, and agent versions are
visible only if something writes them onto the spans. Discover first, with
`EXPLAIN (ANALYZE_FIELDS)` on the agent's spans, looking for an attribute that records the
event (for example a guardrail action, `service.version`, or a deployment attribute).

- **Present:** filter or split on it, roll up to sessions or evaluation scores as asked, and
  report the share ("N of M sessions in the window").
- **Absent:** say the telemetry cannot answer the question and name what would need to be
  emitted. For change events, offer the fallback that needs no attribute: the user gives the
  change times and you compare equal windows before and after each. Never infer a guardrail
  block from response wording, and never claim a correlation with a change you cannot see.

### What changed: before and after

Anchor on the time the user names (or the start of the regression) and compare two absolute
windows of equal length, before and after, on the same service. Compare three layers and name
the one the evidence supports:

- **The agent:** span structure per trace (count and order of LLM and tool spans), the set of
  tools called, and any version or deployment attribute.
- **The model:** `gen_ai.request.model` / `gen_ai.response.model`, token usage per call, and
  LLM span latency.
- **Downstream:** tool and `CLIENT` span latency and error rate, grouped by
  `attributes['peer.service']` or `attributes['server.address']`.

Read quality for both windows from `logs.default` per evaluator (scored records only, both
`service.name` forms), as in [agent-evaluation.md](../agent-evaluation.md) section 7. When the
layers move together or the evidence points outside the agent's telemetry (a dependency's own
health, infrastructure), say the agent telemetry cannot separate them and recommend a
full-stack investigation of that dependency instead of naming a cause.
