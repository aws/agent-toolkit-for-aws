# AgentCore Resources in an Agent's Traces

Recipes for the Amazon Bedrock AgentCore resources an AI agent calls (Memory, Gateway,
Browser, Code Interpreter and Runtime), read from the agent's own spans on
`traces.default`: which resources the agent uses, which agents use a resource, whether one
is slow, failing or throttled, why a Gateway refused a tool call, and what a Memory
retrieval returned. The SQL dialect, the mandatory `` `@timestamp` `` bound and the
failed-span rule are in [sql-logs-traces.md](sql-logs-traces.md); fetching and reading one
trace, and the agent-span attributes, are in [trace-exploration.md](trace-exploration.md).
This file adds only what is specific to AgentCore resources. Creating or configuring an
AgentCore resource is not covered here.

---

## 1. How a call to an AgentCore resource appears in a trace

One call can leave two spans in the agent's trace, and they answer different questions:

- **The agent's call**: a `CLIENT` span the agent emits, under the agent's own
  `resource['attributes']['service.name']`. Its duration is the **agent's wait**: the
  network, SDK retries and the resource's work together.
- **The resource's own span**: a `SERVER` span the resource emits, under its own
  `service.name`, in the same trace. Its duration is the **resource's own time**. It is
  there only when tracing is on for that resource (section 6).

Classify by these attributes, never by span name:

| Resource | The agent's call (`CLIENT`) | The resource's own span (`SERVER`) | Resource id |
|---|---|---|---|
| Memory | `attributes['aws.remote.resource.type'] = 'AWS::BedrockAgentCore::Memory'` | `attributes['aws.xray.origin']` is the same type | call: `aws.remote.resource.identifier`, else `gen_ai.memory.id`; own span: `memory.id` |
| Gateway | no resource type; `attributes['aws.remote.service']` is the Gateway host `<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com` | `aws.xray.origin = 'AWS::BedrockAgentCore::Gateway'`; a tool call is the span with `attributes['url.path'] = 'tools/call'` | call: the host's first label; own span: `gateway.id` |
| Browser | `aws.remote.resource.type` is `AWS::BedrockAgentCore::Browser` (built-in) or `AWS::BedrockAgentCore::BrowserCustom` | `aws.xray.origin` is the same type | call: `aws.remote.resource.identifier` (a built-in tool's id is AWS-managed, such as `aws.browser.v1`); own span: `aws.local.service` |
| Code Interpreter | `aws.remote.resource.type` is `AWS::BedrockAgentCore::CodeInterpreter` (built-in) or `AWS::BedrockAgentCore::CodeInterpreterCustom` | `aws.xray.origin` is the same type | as for a Browser (built-in: `aws.codeinterpreter.v1`) |
| Runtime (another agent) | `aws.remote.resource.type = 'AWS::BedrockAgentCore::Runtime'` | the Runtime's own `SERVER` span (`aws.xray.origin = 'AWS::BedrockAgentCore::Runtime'`), with the called agent's work under that agent's own `service.name` | `aws.remote.resource.identifier` |

The operation is `aws.remote.operation` on the call (for example `CreateEvent`,
`RetrieveMemoryRecords`, `StartBrowserSession`, `InvokeCodeInterpreter`,
`InvokeAgentRuntime`), and `aws.local.operation`, else the span `name`, on the resource's
own span. On a Gateway's `tools/call` span the operation that matters is the tool:
`gen_ai.tool.name`, else `tool.name`. `kind` may be stored as `CLIENT` / `SERVER`, as
`SPAN_KIND_*`, or as its numeric code, and ADOT also writes `attributes['aws.span.kind']`, so
the queries below match all of these.

Facts to keep straight:

- **A tool span often wraps a resource call.** A browser or code interpreter tool's child is
  the resource call, and a tool routed through a Gateway reaches the Gateway's `tools/call`
  span. Report the resource, and name the tool that called it.
- **A Gateway reached over MCP may leave no usable call span.** Without the host, the
  agent's call records `aws.remote.service = 'UnknownRemoteService'`, and only the Gateway's
  own spans name it.
- **Nested spans overlap.** A tool's duration includes the resource call under it, so never
  add a parent's and a child's durations.
- AgentCore Identity (credential provider) and Payments calls are not covered here.

---

## 2. Which latency a number is

Name the latency you quote every time:

- **The agent's wait**: the `CLIENT` call's duration (an `agent` row below).
- **The resource's own time**: the resource's `SERVER` span (a `resource` row). A Gateway's
  `tools/call` span also splits its time into `attributes['execute_tool_latency_ms']` (the
  target) and `attributes['overhead_latency_ms']` (the Gateway itself) when it carries them.
- **The vended `Latency` metric** in the `AWS/Bedrock-AgentCore` CloudWatch namespace: an
  average the service reports, not a span percentile (section 6).

For a Memory, Browser or Code Interpreter, the agent's wait is normally the larger. When it
is much larger than the resource's own time, the gap is the network, SDK retries
(`attributes['retry_attempts']` on the call) or session start, not the resource.

A Gateway is different. The agent's call to it records one operation for all the MCP requests
the agent sends (`initialize`, `tools/list`, notifications and `tools/call` together, for
example as `POST /mcp`), while the Gateway's own spans are one per tool. The two sides are not
comparable per operation, and a tool's own time can read larger than the agent's wait. For a
Gateway tool, compare `execute_tool_latency_ms` with `overhead_latency_ms` instead.

---

## 3. The resources an agent uses

One query reads both sides of every call. It returns one row per side, resource and
operation, with calls, failed, throttled (HTTP 429) and retried calls, traces, and p50/p99
in milliseconds. Failing resources sort first, then the most-called, and an operation's
`agent` and `resource` rows sit together when both sides record the same operation name. A
Gateway's two sides never do: its `agent` rows are its MCP requests, its `resource` rows its
tools (section 2).
Use the same window and agent scope in all three marked places:

```sql
SELECT g.side, g.resource_type, g.resource, g.operation, g.calls, g.error_calls,
       g.throttled_calls, g.retried_calls, g.traces, g.p50_ms, g.p99_ms
FROM (
  SELECT r.side AS side, r.resource_type AS resource_type, r.resource AS resource,
         r.operation AS operation, COUNT(*) AS calls, SUM(r.err) AS error_calls,
         SUM(r.throttled) AS throttled_calls, SUM(r.retried) AS retried_calls,
         COUNT(DISTINCT r.tid) AS traces,
         approx_percentile_cont(r.ms, 0.5) AS p50_ms,
         approx_percentile_cont(r.ms, 0.99) AS p99_ms,
         SUM(SUM(r.err)) OVER (PARTITION BY r.resource_type, r.resource) AS resource_errors,
         SUM(COUNT(*)) OVER (PARTITION BY r.resource_type, r.resource) AS resource_calls,
         SUM(COUNT(*)) OVER (PARTITION BY r.resource_type, r.resource, r.operation)
           AS operation_calls
  FROM (
    -- side 'agent': the agent's own calls to AgentCore resources
    SELECT traceId AS tid, 'agent' AS side,
           CASE
             WHEN (upper(TRY_CAST(kind AS VARCHAR)) IN ('CLIENT', 'SPAN_KIND_CLIENT', '3')
                   OR attributes['aws.span.kind'] = 'CLIENT')
                  AND attributes['aws.remote.resource.type'] IN (
                    'AWS::BedrockAgentCore::Memory', 'AWS::BedrockAgentCore::Gateway',
                    'AWS::BedrockAgentCore::Browser', 'AWS::BedrockAgentCore::BrowserCustom',
                    'AWS::BedrockAgentCore::CodeInterpreter',
                    'AWS::BedrockAgentCore::CodeInterpreterCustom',
                    'AWS::BedrockAgentCore::Runtime')
               THEN attributes['aws.remote.resource.type']
             WHEN (upper(TRY_CAST(kind AS VARCHAR)) IN ('CLIENT', 'SPAN_KIND_CLIENT', '3')
                   OR attributes['aws.span.kind'] = 'CLIENT')
                  AND attributes['aws.remote.service'] LIKE '%.gateway.bedrock-agentcore.%'
               THEN 'AWS::BedrockAgentCore::Gateway'
           END AS resource_type,
           COALESCE(NULLIF(attributes['aws.remote.resource.identifier'], ''),
                    CASE WHEN attributes['aws.remote.resource.type'] = 'AWS::BedrockAgentCore::Memory'
                         THEN NULLIF(attributes['gen_ai.memory.id'], '') END,
                    CASE WHEN attributes['aws.remote.service'] LIKE '%.gateway.bedrock-agentcore.%'
                         THEN split_part(attributes['aws.remote.service'], '.', 1) END) AS resource,
           NULLIF(attributes['aws.remote.operation'], '') AS operation,
           CASE WHEN upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')
                THEN 1 ELSE 0 END AS err,
           CASE WHEN TRY_CAST(attributes['http.response.status_code'] AS BIGINT) = 429
                THEN 1 ELSE 0 END AS throttled,
           CASE WHEN TRY_CAST(attributes['retry_attempts'] AS BIGINT) > 0 THEN 1 ELSE 0 END AS retried,
           CAST(durationNano AS DOUBLE) / 1e6 AS ms
    FROM traces.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()       -- (1) window
      AND resource['attributes']['service.name'] = '<agent service.name>'  -- (1) scope
    UNION ALL
    -- side 'resource': the resources' own spans in the agent's traces
    SELECT traceId AS tid, 'resource' AS side,
           CASE
             WHEN upper(TRY_CAST(kind AS VARCHAR)) IN ('SERVER', 'SPAN_KIND_SERVER', '2',
                                                        'CONSUMER', 'SPAN_KIND_CONSUMER', '5')
                  AND (attributes['aws.xray.origin'] IN (
                         'AWS::BedrockAgentCore::Memory', 'AWS::BedrockAgentCore::Browser',
                         'AWS::BedrockAgentCore::BrowserCustom',
                         'AWS::BedrockAgentCore::CodeInterpreter',
                         'AWS::BedrockAgentCore::CodeInterpreterCustom')
                       OR (attributes['aws.xray.origin'] = 'AWS::BedrockAgentCore::Gateway'
                           AND attributes['url.path'] = 'tools/call'))
               THEN attributes['aws.xray.origin']
           END AS resource_type,
           COALESCE(NULLIF(attributes['gateway.id'], ''), NULLIF(attributes['memory.id'], ''),
                    NULLIF(attributes['aws.local.service'], '')) AS resource,
           COALESCE(CASE WHEN attributes['aws.xray.origin'] = 'AWS::BedrockAgentCore::Gateway'
                         THEN NULLIF(COALESCE(attributes['gen_ai.tool.name'],
                                              attributes['tool.name']), '') END,
                    NULLIF(replace(COALESCE(NULLIF(attributes['aws.local.operation'], ''), name),
                                   'AgentCore.BuiltinTools.', ''), '')) AS operation,
           CASE WHEN upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')
                THEN 1 ELSE 0 END AS err,
           CASE WHEN TRY_CAST(attributes['http.response.status_code'] AS BIGINT) = 429
                THEN 1 ELSE 0 END AS throttled,
           CASE WHEN TRY_CAST(attributes['retry_attempts'] AS BIGINT) > 0 THEN 1 ELSE 0 END AS retried,
           CAST(durationNano AS DOUBLE) / 1e6 AS ms
    FROM traces.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()         -- (2) window
      AND traceId IN (
        SELECT traceId FROM traces.default
        WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()     -- (3) window
          AND resource['attributes']['service.name'] = '<agent service.name>') -- (3) scope
  ) r
  WHERE r.resource_type IS NOT NULL
  GROUP BY r.side, r.resource_type, r.resource, r.operation
) g
ORDER BY g.resource_errors DESC, g.resource_calls DESC, g.resource_type, g.resource NULLS LAST,
         g.operation_calls DESC, g.operation NULLS LAST, g.side
LIMIT 200
```

Keep `LIMIT 200`: a smaller limit keeps the first rows of this order, not the slowest ones.

**Estimate it first.** The `resource` side reads every span in the window, whatever the agent
scope, so this is the most expensive query in this file: one agent over 24 hours has scanned
more than 500 GB in a busy Space. Before the first run, and again before widening the window,
follow "When to estimate first" in
[Estimating Scan Volume](sql-logs-traces.md#estimating-scan-volume-explain-estimate): put
`EXPLAIN (ESTIMATE)` in front of the whole query, tell the user the bound, and ask before running
a large one. The queries in sections 4 and 5 that match `traceId IN (...)` read the window the
same way.

**Scope.** For one agent, use its `service.name` (agents hosted on AgentCore Runtime often
report `<runtime name>.<endpoint name>`; "Field discovery for traces" in
[trace-exploration.md](trace-exploration.md) finds the names). For several agents, use
`service.name IN (...)`. For every agent instrumented with ADOT, use
`resource['attributes']['aws.service.type'] = 'gen_ai_agent'`; agents instrumented with
OpenInference alone do not set it, so if that matches nothing, list the agents' names
instead. A fleet-wide read has one set of rows per resource, not one per agent; section 4
splits it by agent.

**Reading the rows.**

- Only resources the agent called in the window appear. The `list-*` calls in section 6
  show what is configured, used or not.
- Rows for a resource on one side only:
  - `agent` rows only: the resource wrote no spans of its own into these traces. That is
    expected for a Runtime, whose own spans this query leaves out. For any other type, its
    tracing may be off (section 6).
  - `resource` rows only: usually a Gateway reached over MCP without its host.
- A 429 that the SDK retried successfully counts in `retried_calls`, not
  `throttled_calls`. No 429 on the spans does not rule out throttles that only the vended
  `Throttles` metric records.
- p50/p99 are span percentiles. A Latency chart that plots the vended metric shows an
  average, so the two do not match.
- A Browser session's expiry and its automation-stream connection are traces of their
  own, outside the agent's traces, so they have no row.

> **The resources an agent uses — state ALL of this in the answer**, with the query shown:
> the agent scope (the `service.name`, or the fleet form used) and the window; which latency
> each `p50_ms` / `p99_ms` is (the agent's wait on an `agent` row, the resource's own time on
> a `resource` row) and that neither is the vended `Latency` metric, an average; for a Gateway,
> that its `agent` rows (MCP requests) and `resource` rows (tools) are not comparable per
> operation; that only
> resources used in the window appear; what a one-sided resource means (only `agent` rows:
> expected for a Runtime, otherwise its tracing may be off; only `resource` rows: a Gateway
> reached over MCP); that a 429 the SDK retried successfully counts as retried, not
> throttled; and the resource ids, with names only from the `get-*` calls in section 6,
> never guessed.

---

## 4. Which agents use a resource

When the resource has `agent` rows, group the agents' calls by the calling service:

```sql
WITH calls AS (
  SELECT resource['attributes']['service.name'] AS caller, traceId AS tid,
         CASE WHEN attributes['aws.remote.service'] LIKE '%.gateway.bedrock-agentcore.%'
              THEN 'AWS::BedrockAgentCore::Gateway'
              ELSE attributes['aws.remote.resource.type'] END AS resource_type,
         COALESCE(NULLIF(attributes['aws.remote.resource.identifier'], ''),
                  CASE WHEN attributes['aws.remote.resource.type'] = 'AWS::BedrockAgentCore::Memory'
                       THEN NULLIF(attributes['gen_ai.memory.id'], '') END,
                  CASE WHEN attributes['aws.remote.service'] LIKE '%.gateway.bedrock-agentcore.%'
                       THEN split_part(attributes['aws.remote.service'], '.', 1) END) AS resource
  FROM traces.default
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()
    AND (upper(TRY_CAST(kind AS VARCHAR)) IN ('CLIENT', 'SPAN_KIND_CLIENT', '3')
         OR attributes['aws.span.kind'] = 'CLIENT')
    AND (attributes['aws.remote.resource.type'] IN (
           'AWS::BedrockAgentCore::Memory', 'AWS::BedrockAgentCore::Gateway',
           'AWS::BedrockAgentCore::Browser', 'AWS::BedrockAgentCore::BrowserCustom',
           'AWS::BedrockAgentCore::CodeInterpreter',
           'AWS::BedrockAgentCore::CodeInterpreterCustom', 'AWS::BedrockAgentCore::Runtime')
         OR attributes['aws.remote.service'] LIKE '%.gateway.bedrock-agentcore.%')
)
SELECT resource_type, resource, caller, COUNT(*) AS calls, COUNT(DISTINCT tid) AS traces
FROM calls
GROUP BY resource_type, resource, caller
ORDER BY resource_type, resource, calls DESC
```

For one resource, add `WHERE resource = '<resource id>'` before the `GROUP BY`.

When the resource has `resource` rows only (a Gateway reached over MCP), find the agents
through the resource's own spans: take the traces that hold them, and name the services
that wrote agent spans in those traces:

```sql
SELECT resource['attributes']['service.name'] AS agent, COUNT(DISTINCT traceId) AS traces
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()
  AND traceId IN (
    SELECT traceId FROM traces.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()
      AND attributes['aws.xray.origin'] = 'AWS::BedrockAgentCore::Gateway'
      AND attributes['gateway.id'] = '<gateway id>')
  AND (attributes['openinference.span.kind'] = 'AGENT' OR attributes['aws.genai.span_kind'] = 'AGENT'
       OR attributes['gen_ai.operation.name'] = 'invoke_agent'
       OR resource['attributes']['aws.service.type'] = 'gen_ai_agent')
GROUP BY resource['attributes']['service.name']
ORDER BY traces DESC
```

This names every service that wrote an agent span in those traces, including agents that did
not call the resource themselves. In a multi-agent trace, such as one agent invoking another
over AgentCore Runtime, the calling agent and its peers are named too, and their trace counts
overlap. Say so in the answer. Where the resource has `agent` rows, the first query is the
authoritative one; use this one only when it has none.

If both queries come back empty, or the resource's own spans are in no agent's trace, say the
spans cannot attribute it to an agent, not that no agent used it: untraced calls leave no
spans. Do not guess one from names.

The same join works for any resource's own spans: match `memory.id` for a Memory, and
`aws.local.service` for a Browser or Code Interpreter.

---

## 5. Diagnosing a symptom

Lead with the finding, then the evidence, and keep what was measured apart from what is
inferred. When the user names a trace or a session, or has one open, read that first
(fetch it as in [trace-exploration.md](trace-exploration.md) section 2), and widen to the
agent's traces only to say whether the problem is a one-off or a pattern.

### Slow, or timing out

Run the section 3 query. Name the slowest resource operation with its p50 and p99, the side,
and how the agent's wait compares with the resource's own time (section 2). For a timeout,
rank the agent's slowest traces ("Trace-level latency" in
[trace-exploration.md](trace-exploration.md)) and re-run the section 3 query on those traces
alone (add `AND traceId IN ('<id>', ...)` in all three places): the component that grows with
the trace is the bottleneck, not the one that is merely large. A p99 pinned at a round value,
such as 30,000 ms, is a timeout limit; say which component hit it. When the time goes to model
calls rather than a resource, say so.

### Failing or throttled

Read `error_calls`, `throttled_calls` and `retried_calls` in the section 3 rows, then read the
failing spans' status message and HTTP status as in "Why it failed" in
[trace-exploration.md](trace-exploration.md). On a Gateway, a failure inside
`execute_tool_latency_ms` is the target's, and one inside `overhead_latency_ms` is the
Gateway's.

When the Gateway's `tools/call` span carries no status message, the cause is on the target's
own spans in the same trace. Report the deepest failing span that is not the
Gateway's own (its `aws.xray.origin` is not `AWS::BedrockAgentCore::Gateway`), with its status
message or recorded exception, and name the target from `list-gateway-targets` (section 6). The
Gateway's intermediate spans and the agent's wrapping tool span may carry only a generic
message, such as "An internal error occurred"; do not report that as the cause. If the target
wrote no spans, say the spans do not record the cause.

### Refused by a Gateway policy

A Gateway's `tools/call` spans record its policy decision. Group them for the agent, or set
`traceId = '<trace id>'` for one request:

```sql
WITH tool_calls AS (
  SELECT attributes['gateway.id'] AS gateway,
         COALESCE(attributes['gen_ai.tool.name'], attributes['tool.name']) AS tool,
         attributes['aws.agentcore.policy.authorization_decision'] AS decision,
         attributes['aws.agentcore.gateway.policy.mode'] AS policy_mode,
         TRY_CAST(attributes['http.response.status_code'] AS BIGINT) AS http_status
  FROM traces.default
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()
    AND attributes['aws.xray.origin'] = 'AWS::BedrockAgentCore::Gateway'
    AND attributes['url.path'] = 'tools/call'
    AND traceId IN (
      SELECT traceId FROM traces.default
      WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOURS' AND NOW()
        AND resource['attributes']['service.name'] = '<agent service.name>')
)
SELECT gateway, tool, decision, policy_mode, http_status, COUNT(*) AS calls
FROM tool_calls
GROUP BY gateway, tool, decision, policy_mode, http_status
ORDER BY calls DESC
```

- Report the decision and the mode as recorded. A mode that only logs records a decision and
  blocks nothing, so a deny in that mode did not refuse the request. In the `LOG_ONLY` mode the
  decision can read `LOG_ONLY_ASYNC` rather than an allow or a deny.
- An empty decision and an empty mode mean no policy is attached to that Gateway. An empty
  decision under a named mode (such as `ENFORCE`) means no decision was recorded for that call.
  Neither is an allow or a deny; say which of the two it is.
- An HTTP 401 or 403 is an authorization failure, unlike a tool error.
- If no Gateway span carries an enforced deny, the refusal did not come from a Gateway
  policy. Check the model's own refusal on the LLM spans (`gen_ai.response.finish_reasons`
  when recorded), and report only guardrail attributes that are actually on the spans
  ("Signals the telemetry may not record" in [trace-exploration.md](trace-exploration.md)).

### A wrong or outdated answer (Memory)

Read the trace's Memory calls in start-time order by `aws.remote.operation`: `CreateEvent`
writes, `ListEvents` reads the session's recent events, and `RetrieveMemoryRecords` and
`ListMemoryRecords` read long-term records. The Memory's own spans carry `memory.id` and
`session.id`.

- Did a retrieval run before the LLM call that produced the answer, and did it fail? No
  retrieval points at the agent's flow; a failed one at the Memory call.
- The spans carry no record count. Read what a retrieval returned from the next LLM span's
  input (the input attributes in [trace-exploration.md](trace-exploration.md) section 1), and
  say it was read from the prompt, not counted. A successful retrieval that returned nothing
  useful points at what the Memory holds, not at the agent.

### Browser or Code Interpreter errors and timeouts

Separate the resource from the tool code that drives it:

1. The resource calls (`StartBrowserSession`, `StartCodeInterpreterSession`,
   `InvokeCodeInterpreter` and the rest, by `aws.remote.operation`), with their status and
   `retry_attempts`. A failed call is the resource's.
2. The tool span that wraps them. A failed one's status message, or a recorded exception, says
   why; report it. A failed tool over successful resource calls is the agent's own code, for
   example a page-load timeout inside a browser tool.
3. The resource's own spans carry `toolsession.id`, the session.

### Runtime invoke errors (an agent calling another agent)

Read the `InvokeAgentRuntime` calls (`aws.remote.resource.identifier` names the Runtime) and
their `http.response.status_code`. A 424 means the called agent itself failed: find the
deepest failing span among that agent's own spans in the same trace ("Why it failed" in
[trace-exploration.md](trace-exploration.md)). Another 4xx is the request; a 5xx is the
Runtime service.

> **Diagnosing a symptom through AgentCore resources — state ALL of this in the answer:**
> the trace, or the agent scope and window, that was read; the component the evidence points
> at (the model, a tool, or a named AgentCore resource and operation) with its numbers and
> which latency they are; what was measured kept apart from what was inferred (an empty
> Memory retrieval is read from the next prompt, not counted); for a refusal, the Gateway
> decision and mode found (an empty one named as no policy attached, or as no decision
> recorded), or that no Gateway span carried an enforced deny; and the next
> check or the fix tied to that component.

---

## 6. Names, configuration, vended metrics, and tracing

**Names and configuration.** Spans carry ids, not names. Read a resource's name and
configuration with its read-only `get-*` call; an `AccessDenied` means the caller cannot read
it, so report the id instead.

| Resource | Name and configuration | What is configured |
|---|---|---|
| Memory | `aws bedrock-agentcore-control get-memory --memory-id <id>` | `list-memories` |
| Gateway | `get-gateway --gateway-identifier <id>`; its targets: `list-gateway-targets --gateway-identifier <id>` | `list-gateways` |
| Browser (custom) | `get-browser --browser-id <id>` | `list-browsers`; `--type SYSTEM` lists the built-in ones |
| Code Interpreter (custom) | `get-code-interpreter --code-interpreter-id <id>` | `list-code-interpreters`; `--type SYSTEM` lists the built-in ones |
| Runtime | `get-agent-runtime --agent-runtime-id <id>` | `list-agent-runtimes` |

**Vended metrics.** AgentCore also publishes CloudWatch metrics in the
`AWS/Bedrock-AgentCore` namespace (for example `Latency`, `Invocations`, `Throttles`,
`SystemErrors`, `UserErrors`). They are CloudWatch vended metrics: unless a PromQL query for
them returns series in this account, read them as "Vended metrics that are not enriched are
not queryable" in section 1 of [promql-metrics.md](promql-metrics.md) says, through the
CloudWatch route. Name them as the service's own figures, next to the span numbers, never in
place of them.

**Tracing.** A resource's own spans exist only when tracing is on for it: AgentCore requires
explicit enablement for Memory, Gateway and built-in tool spans, and CloudWatch Transaction
Search must be on in the Region (see the
[AgentCore observability documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)).
Turning it on is setup, not something to do from this file: Transaction Search is covered in
`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/instrumentation/collector.md`,
and trace delivery for agents on AgentCore in
`setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md`.
