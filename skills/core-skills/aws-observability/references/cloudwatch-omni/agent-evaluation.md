# CloudWatch Omni: Agent Evaluation

> **Tool capability:** the AWS CLI (`aws___call_aws`, or the CLI from a shell) for the AgentCore Evaluations control plane (`bedrock-agentcore-control`) and data plane (`bedrock-agentcore`), plus the CloudWatch Omni SQL query surface for the agent's own telemetry and the stored scores. SQL syntax (tables, the required `` `@timestamp` `` bound, bracket-notation field access, quoting, `CAST`, JOINs) lives in [`query/sql-logs-traces.md`](query/sql-logs-traces.md) — this file adds only the evaluation-specific schema and patterns and does not restate it.

Use when the user asks to:

- "Score/evaluate these traces" / "How helpful was my agent on this trace/session?" (on-demand)
- "Which evaluator should I use?" / "What evaluators are available?"
- "Set up online / continuous evaluation" / "monitor my deployed agent's quality"
- "Create a dataset from traces" / "build a regression / golden set"
- "What did my evaluation find?" / "how are my agent's scores this week" / "which sessions scored low and why" (read back stored scores)
- "Is my agent's instrumentation healthy / are traces flowing end-to-end?" (audit)

Deploying an agent so that traces reach CloudWatch (AgentCore, ECS, Lambda, EC2 env vars, IAM, ADOT floors) is instrumentation, not evaluation — see `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md` ("Production deployment").

---

## 1. What agent evaluation is

**Agent Observability quality evaluation** scores an AI agent's OpenTelemetry traces with an **evaluator** — a judge (LLM-as-judge or code) that reads a trace's spans and returns a score (numeric `value` and/or categorical `label`) with an `explanation`. Three ways to run it, all writing their scores into the same telemetry store so they can be read back later:

| Path | What it scores | API |
|---|---|---|
| **On-demand** (sync) | Specific traces/sessions the user names, now — no setup | `bedrock-agentcore evaluate` (data plane) via the bundled helper `evaluate_traces.py` (Section 4) |
| **Online** (continuous) | A sample of a deployed agent's live sessions, over time | `bedrock-agentcore-control create-online-evaluation-config` and friends (Section 5) |
| **Batch** (dataset-based) | A published **dataset** version — a re-runnable regression / golden set | `bedrock-agentcore-control` dataset ops (Section 6) |

Every score — online, on-demand, or batch — lands as a `gen_ai.evaluation.result` log record in `logs.default` (Section 7). The agent's own spans are in `traces.default`; the two are separate records joined by `traceId`.

**Evaluators** come from `list-evaluators` (Section 3): `Builtin.<Name>` (AWS), `ThirdParty.<Provider>.<Name>`, and any `Custom`/`CustomCode` evaluators created in the account. Each has a **level** — `TRACE` (whole request/response), `TOOL_CALL` (individual tool invocations; needs tool spans), `SESSION` (whole conversation) — and every evaluator in one scoring call shares one level.

**Prerequisites (every path):** the agent must be emitting telemetry with **CloudWatch Transaction Search enabled**, and there is a 2–5 min ingestion lag before a fresh session is evaluable. **Custom** evaluators that invoke Bedrock need `bedrock:InvokeModel` on the caller (on-demand) or on the execution role (online); built-in evaluators do not — the service invokes the judge model itself. All of these resources are Region-scoped — they appear only in the Region they were created in.

### Operating contract

Before any action that **scores, creates, edits, or deletes**, confirm the specifics with the user first. This contract governs every step below, even where a step does not restate it:

- **The evaluator set is the user's choice, never yours.** If the user named the evaluators or a clear dimension ("score for correctness", "helpfulness and goal success"), use exactly those and run — unless the named evaluator cannot run on the target (a ground-truth-required evaluator against a raw trace; see "Ground-truth check" in Section 3): then say why it cannot run, recommend the evaluator that answers their question, offer the dataset path, and confirm before running — an open recommendation is not a silent substitution. If they did NOT ("evaluate these traces", "check my agent", "the 3 slowest"), list the available evaluators, recommend the one or two that fit the trace and their question, and **ask which to run — then STOP** and wait. Never default to "all evaluators" or silently substitute one you think is close: scoring runs cost quota and money, and an unrequested evaluator produces a number the user did not ask for. If the id they gave is not an exact match to a `list-evaluators` id (a typo, different casing, or an encoded/escaped string), surface the id you resolved it to and confirm before scoring.
- **You MUST run the real evaluator — never judge quality yourself.** Reading a trace and assigning a number is wrong: the score has to come from the `evaluate` API or a stored result, not from you — even when the API errors (see "If the evaluator can't score the trace" in Section 4).
- **Never blend evaluators into one combined score** — no overall average, no "pass rate", no "% good". Evaluators use different rubrics and scales; a 0.8 Helpfulness and a 0.8 Toxicity are opposite outcomes. Report each evaluator separately; if a single headline is wanted, name the weakest dimension.
- **Never skip data-source verification when creating an online-eval config.** Run the `@logGroupName` query first — a user naming a log group is **not** permission to skip it. If the group isn't confirmed, do **not** create: report what you found and wait.
- **Writes are real** (create/update/delete of datasets, evaluators, online-eval configs; running evaluations costs quota). Draft → confirm the specifics → then call, and report the returned id (`datasetId` / `onlineEvaluationConfigId` / `evaluatorId`). Never claim a resource was created without the API returning its id, and never act on a non-interactive request without confirmation.
- An override ("just do it", "I don't need you checking") only counts when it comes **after** you have reported the concern — never inferred from the original request.

### Which path / evaluator, when?

| You want to… | Path | The one move that makes or breaks it |
|---|---|---|
| Score a few specific traces/sessions now, no setup | **On-demand** — `bedrock-agentcore evaluate` (Section 4; use `evaluate_traces.py`) | `evaluate` scores the trace's **raw session spans fetched from Logs** — not a flattened query row, not a trace id alone — and each span's `kind` must be a bare OTel string (`SERVER`/`INTERNAL`) or it fails `ValidationException: Failed to parse span data`; the bundled helper normalizes it. No dataset or online config needed. |
| Continuously monitor a live agent's quality | **Online** — `create-online-evaluation-config` (Section 5) | Resolve the log group from the agent's own spans via the `@logGroupName` query — **never** from `resource['attributes']['aws.log.group.names']`, or the config goes ACTIVE and silently scores nothing. Show groups + span counts for approval before creating. |
| Reuse traces as a re-runnable regression / golden set | **Dataset** (Section 6) | Build the examples **from the traces** (no server-side "trace → example" op — use `capture_dataset_from_traces.py`), then **publish an immutable version** — a repeatable target evaluates against the version, not the mutable DRAFT. |
| Score a dimension no built-in covers (e.g. brand voice, tone) | **Custom evaluator** — `create-evaluator` (Section 5) | An LLM-as-judge at **`TRACE` level** for response quality; `instructions` must embed a **single-brace** placeholder (`{context}`/`{assistant_turn}`, not `{{context}}`), the judge model must be **discovered** (`list-inference-profiles --type-equals SYSTEM_DEFINED`, prefer `us.`/`global.` ids), and you present the draft for confirmation before creating. |
| See what evaluation already found | **Read back stored scores** (Section 7) | Query `logs.default` (not `traces.default`) with the `gen_ai.evaluation.*` field names verbatim, gate on `error.type IS NULL`, roll up **per evaluator first**, read by polarity, then drill into the WHY. |

---

## 2. Instrumentation health audit

Use when the user asks whether an agent's instrumentation is healthy or traces are flowing end-to-end. This is a **query-based** check over the agent's own telemetry in `traces.default` (a bounded `` `@timestamp` `` window; see [`query/sql-logs-traces.md`](query/sql-logs-traces.md) for the dialect) — it verifies the telemetry that actually reached CloudWatch Omni, **not** the OTel SDK/collector/runtime *setup* (that belongs to the instrumentation reference).

Staged, over a bounded window (start ~1 hour, widen if the agent is idle):

1. **Are spans arriving?** Filter by the agent's `resource['attributes']['service.name']` (and `resource['attributes']['aws.service.type'] = 'gen_ai_agent'`); check span/trace counts and a recent `` MAX(`@timestamp`) `` (last_seen). No rows → nothing is reaching Omni — an upstream instrumentation gap, not something to fix here.
2. **Is the trace continuous?** Confirm agent / LLM / tool spans are present and linked within a trace (parent/child), not orphaned single spans. Grouping the agent's spans by `scope['name']` shows which instrumentation scopes are emitting — a framework scope (e.g. `strands.telemetry.tracer`) alongside an HTTP-server scope is healthy; HTTP-only means the agent framework is not instrumented.
3. **Is telemetry quality good?** Confirm the expected GenAI attributes are populated — model, token counts, and input/output — not just bare spans. Missing/empty attributes mean the agent emits spans but not usable agent-observability data.

Report what the queries showed. If spans are absent or attributes empty, say it's an upstream instrumentation gap to fix in the agent's OTel/ADOT setup (see `setting-up-cloudwatch-observability` → `references/cloudwatch-omni/omni-agents-instrumentation/omni-agents-instrumentation.md`), not something to change here.

---

## 3. Choosing an evaluator

Two distinct jobs: **choosing** an evaluator (read-only — no scoring pass) and **running** one (Section 4). When the user asks "which evaluator should I use?" or is unsure, answer WITHOUT scoring anything.

### Discover evaluators first — never hardcode ids

```
aws bedrock-agentcore-control list-evaluators
```

Each summary carries `evaluatorId`, `evaluatorName`, `evaluatorType` (`Builtin` | `ThirdParty` | `Custom` | `CustomCode` | `CustomDerived`), `provider` (e.g. `AWS`, `DeepEval`, `AutoEval`), `level` (`TRACE` | `TOOL_CALL` | `SESSION`), `description`, `status`, and `lockedForModification` (whether the evaluator can be modified — relevant before proposing an edit), plus `evaluatorArn`, `createdAt`, `updatedAt` and, where set, `kmsKeyArn` — enough to choose from without any further call.

Call `aws bedrock-agentcore-control get-evaluator --evaluator-id <id>` only when a question actually needs more — the rating scale under `evaluatorConfig`, or a custom evaluator's judge model. The detail response does **not** carry machine-readable input-requirement flags — judge an evaluator's ground-truth needs from its identity and description (below). For a field's exact semantics, consult the current AWS documentation rather than guessing.

**Use only the ids `list-evaluators` returns.** The catalog varies by account and Region and changes over time, so a name baked into this doc goes stale. Current accounts expose `Builtin.<Name>` (e.g. `Builtin.Helpfulness`, `Builtin.Correctness`, `Builtin.ToolSelectionAccuracy`, `Builtin.GoalSuccessRate`) and third-party evaluators namespaced `ThirdParty.<Provider>.<Name>` (e.g. `ThirdParty.DeepEval.ToolUse`), plus any custom evaluators created in the account — but treat the live list as the only source of truth. An id you did not see in this account's list output may not exist here; do not recommend or run it.

**Listed ≠ invocable.** If `evaluate` rejects an id that `list-evaluators` returned (e.g. `ValidationException: Unknown evaluator`), treat it as a service-side issue, offer a different evaluator, and never self-assign a score to compensate.

### Ground-truth check (before recommending for on-demand)

A live trace carries **no ground truth**, so an evaluator that needs an expected value cannot score it on-demand. There is no machine-readable requirement flag — decide from the evaluator's identity and description:

- **Ground-truth-required (on-demand: no) — the trajectory matchers** `Builtin.TrajectoryExactOrderMatch`, `Builtin.TrajectoryInOrderMatch`, `Builtin.TrajectoryAnyOrderMatch` compare the actual tool sequence against an **expected** trajectory. They only work against a dataset whose examples carry `expected_trajectory` (Section 6) — never on a raw trace.
- **Ground-truth-free (on-demand: yes)** — response-quality/safety judges (`Builtin.Helpfulness`, `Builtin.Coherence`, `Builtin.Faithfulness`, and the like) and the tool judges `Builtin.ToolSelectionAccuracy` / `Builtin.ToolParameterAccuracy` score a trace on its own merits. **For "does my agent pick the right tools?" use `Builtin.ToolSelectionAccuracy`, not a trajectory matcher.** `Builtin.Correctness` and `Builtin.GoalSuccessRate` also run without ground truth (they can optionally use it, but do not require it).

When a user's question maps only to a ground-truth-required evaluator, say the raw-trace path can't supply the expected values and offer the dataset path (Section 6) instead of substituting an evaluator that doesn't answer their question.

> **When you redirect an evaluator, tell the user ALL of this:** which evaluator actually answers their question (for "does it pick the right tools?" that is `Builtin.ToolSelectionAccuracy`); that the trajectory matchers (exact-order, in-order, any-order) are ground-truth-required — they compare the actual tool sequence against an EXPECTED trajectory; that a live trace carries no ground truth, so a matcher cannot score raw traces on-demand and only works against a dataset whose examples carry an expected trajectory; that the dataset path (Section 6) is the alternative if they want the matcher; and that there is no machine-readable input-requirement flag on the detail API — an evaluator's ground-truth need is judged from its identity and description.

### Level → target rules

Every scoring call runs at ONE level, and the level decides what gets scored:

- `TRACE` — whole request/response interactions. The default for "is this trace any good?" questions.
- `TOOL_CALL` — individual tool invocations within a trace. Use for "did it pick the right tool?" / "were the tool calls correct?". Only works when the trace actually has tool spans.
- `SESSION` — the whole conversation across the trace.

All evaluators in a single scoring call must share that one level. The level is a property of the scoring call (the `--level` argument), set explicitly — it is not inferred from the evaluators; each evaluator's own `level` must match the call's level, which is why evaluators at different levels need separate calls.

> **When a request implies more than one level (e.g. a request that names both a per-tool-call check
> and a whole-conversation session-level check together), tell the user ALL of this:** every scoring call runs at exactly ONE level and all evaluators in
> a call share it; the two asks map to different levels (TOOL_CALL vs SESSION) so they need SEPARATE
> calls; briefly define the levels involved (TRACE = whole request/response, TOOL_CALL = individual tool
> invocations, SESSION = whole conversation); and TOOL_CALL only scores when the trace actually has tool
> spans. Then confirm the evaluator choice before running (operating contract).

### Recommend

Recommend the evaluator whose `level` and `description` match the trace and the user's question. Ask the user to confirm when the intent is genuinely ambiguous (e.g. "helpfulness" vs. "correctness" for the same trace) rather than guessing — and per the operating contract, never start scoring until the user has chosen.

---

## 4. Running an on-demand evaluation

Best when the user has a specific session/trace and wants a score now — **no dataset and no online config are required**, so this is the answer to "score this one trace without setting up a whole pipeline." The score has to come from the `evaluate` API (service `bedrock-agentcore`, data plane), not from you.

### Use the bundled helper — do not hand-build an evaluation request

`evaluate` needs the trace's spans reconstructed into the exact `sessionSpans` shape, with **each span's `kind` coerced to a bare OTel string** (`SERVER`/`INTERNAL`, never a number or null) or it fails with `ValidationException: Failed to parse span data`. **Do not hand-shape spans in the conversation** — reshaping turn-by-turn is exactly where a one-shot flow thrashes (reshape → ValidationException → retry → loop). Do **not** instead call any `cloudwatch-omni` Evaluate operation or assemble `structuredInput` (input / output / toolCalls extracted from spans) by hand: that is a different API on a different shape. If you catch yourself writing code to pull messages/tool-calls out of spans, stop and use the helper.

This skill **bundles a tested helper**, [`scripts/cloudwatch-omni/evaluate_traces.py`](../../scripts/cloudwatch-omni/evaluate_traces.py), that does resolve-session → fetch spans from `traces.default` via Omni SQL → normalize `kind` → call `evaluate` deterministically:

1. **Pick the evaluator** (Section 3) — e.g. `Builtin.Helpfulness` (TRACE level). A raw trace has no ground truth, so pick a ground-truth-free evaluator; ground-truth evaluators belong to dataset-based evaluation (Section 6).
2. **Resolve the trace ids** if the user named traces by symptom rather than id (see "Query → evaluate chaining" below).
3. **Retrieve and run the helper** (this skill's supplementary file — fetch it, then run it with your shell):

   ```
   # one trace, one evaluator
   python evaluate_traces.py --trace-id <traceId> --evaluator-id Builtin.Helpfulness \
     --level TRACE --region <region> --include-explanations
   # many traces and/or many evaluators — ONE run, each trace fetched once, every
   # (trace, evaluator) pair scored:
   python evaluate_traces.py --trace-ids <id1>,<id2>,… \
     --evaluator-ids Builtin.Helpfulness,Builtin.Correctness --level TRACE --region <region> --include-explanations
   # a different level is a separate run — tool judges score at TOOL_CALL, not alongside TRACE:
   python evaluate_traces.py --trace-ids <id1>,<id2>,… \
     --evaluator-ids Builtin.ToolSelectionAccuracy --level TOOL_CALL --region <region> --include-explanations
   ```

   It accepts one or many trace ids (`--trace-id` / `--trace-ids`) and one or many evaluator ids (`--evaluator-id` / `--evaluator-ids`), auto-resolves each trace's session (`--session-id` pins it for a single trace), fetches every session's spans from CloudWatch Omni (`traces.default`) via Omni SQL **once**, normalizes every span's `kind`, scores each (trace, evaluator) pair via `evaluate` (level → target: TRACE → `traceIds`; TOOL_CALL → `spanIds`; SESSION → no target), and prints a compact JSON **receipt** — a per-(trace, evaluator) `results` matrix (`traceId` / `evaluatorId` / `value` / `label` / `explanation`, plus `errorCode` if the evaluator returned one) with a small rollup. Raw spans never enter the conversation.
4. **Report the receipt** — carry `value` / `label` and the `explanation` as the "why." You are **not done** until the helper prints a `results` array (or an error).

### Query → evaluate chaining (resolving trace ids)

If the user names traces by symptom ("my slowest traces", "the failing ones") or by service and time window ("traces for checkout-api in the last hour") rather than by id, first resolve the ids with a telemetry query over `traces.default`, then pass those ids to the helper. Never fetch or reason over raw spans yourself — the helper fetches and reshapes them.

**Candidate traces are the user's AGENT traces.** When resolving trace ids to score without a named service, fetch the user's **agent** traces (`resource['attributes']['aws.service.type'] = 'gen_ai_agent'`), not arbitrary application/service traces.

**Filter to a supported instrumentation scope.** `evaluate` accepts only spans whose `scope['name']` is on the service's allowlist of agent-framework instrumentations (for Strands, `strands.telemetry.tracer`; the rejection message lists the current allowlist verbatim). An instrumented agent also emits HTTP-server spans (e.g. `opentelemetry.instrumentation.starlette`) that arrive as traces of their own — health checks and other requests that never reach the agent — and on a busy agent those shells can outnumber real agent traces twenty to one. A "newest N traces for this agent" query with no scope filter therefore returns mostly shells, and every one of them is rejected with `ValidationException: Provided input has no spans with supported scope`. Add the scope filter to the trace-resolution query:

```sql
SELECT traceId FROM "traces.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '2 HOUR' AND NOW()
  AND resource['attributes']['aws.service.type'] = 'gen_ai_agent'
  AND resource['attributes']['service.name'] = '<agent service.name>'
  AND scope['name'] = 'strands.telemetry.tracer'
GROUP BY traceId ORDER BY MAX(`@timestamp`) DESC LIMIT <N>
```

If you do not know which scope the agent emits, first group the agent's spans by `scope['name']` and pick the framework scope, not the HTTP one.

- **Ask for one row per trace.** Group by the trace id and take the newest timestamp per group. `DISTINCT` over *(trace id, timestamp)* is the trap: a trace holds ~15–40 spans with ~15–40 distinct timestamps, so it yields one row PER SPAN, and a row limit then bounds spans rather than traces — a 50-row result can cover as few as 2 traces.
- **Ask for the ids alone.** A timestamp or row-number column roughly halves how many ids fit in one result, and the helper does not need either.
- **Count what you got back, every time.** The query result is length-capped, so a request for N ids can return fewer without any error — and a clipped id is unusable (a trace id is exactly 32 hex characters; anything shorter is a fragment, not an id). Count the complete ids and drop any fragment **silently** — never echo, enumerate or number the ids in your reply; report the COUNT, never the list. If you have fewer than the user asked for, either fetch the remainder (query again for the window *older* than your earliest id) or say plainly how many you got. **Never score a short set silently** — "You asked for 80; the query returned 55, so I scored 55" is required.

### One run per homogeneous grouping

Each run is a full matrix: every evaluator is applied to every trace, at one level. Group the work by "these traces → this set of evaluators at this level":

- "Score traces A, B, C for helpfulness and correctness" → ONE run (three traces, two evaluators, `TRACE`).
- "Score A and B for helpfulness, but C for tool selection accuracy" → TWO runs (one per homogeneous grouping), because the trace subsets and evaluators differ. Decide the groupings yourself and make the separate runs.

### Volume — the helper batches in one run; don't loop it or hand-roll a scorer

Pass every trace id and evaluator id to a **single** run (`--trace-ids`, `--evaluator-ids`); it fetches each trace once and scores every (trace, evaluator) pair. One run covers at most **50 traces**, at most **10 evaluators**, and at most **100 (trace × evaluator) pairs** — three independent bounds, so 60 traces × 1 evaluator is over the limit even though 60 pairs < 100. The helper truncates with a `notes` entry in the receipt rather than silently. Before running, check the trace count and the evaluator count separately, then the product:

- Within all three → run it in one call.
- Over any of them → do NOT quietly score a subset. Tell the user the limit up front and offer to **narrow the time window**, **use fewer evaluators**, or score the first 50 and continue in a follow-up — let them choose. "Evaluate 80 traces" is NOT satisfiable in one pass; say so plainly rather than scoring 50 and presenting it as the answer. Whole-window / "evaluate everything" at large scale is not supported here — say so rather than appearing to do it.
- **Account quotas** are **100 evaluations/min** and **200,000 input tokens/min** per Region per account, so a big matrix throttles and takes a while; the helper paces within a run. A throttled call comes back as a run-level failure, not a per-cell one — retry with fewer traces or fewer evaluators rather than assuming the traces were bad.
- If the cap truncated, an error hit partway, or you scored only a subset, report "scored N of M" and name what was skipped (the receipt's `notes` / `fetchErrors` / `scoreErrors` carry this). Never present a partial pass as if it covered everything.

### If the evaluator can't score the trace, report that — never self-judge

When the receipt has a top-level `error` (e.g. the `evaluate` call raised) or a `results[].errorCode`, tell the user the evaluator couldn't score this trace and give the exact error/`errorCode` verbatim, then STOP. Do **not** fall back to reading the trace and assigning a number yourself. Per-trace errors the service surfaces:

- `AgentSpanMappingException` — span shape not recognized.
- `ValidationException: Failed to parse span data` — span payload malformed.
- `ValidationException: Provided input has no spans with supported scope` — the trace has no span from an allowed agent-framework instrumentation scope, usually an HTTP-only shell trace picked up by a scope-blind "newest N" query. That rejection is deterministic per trace, so do **not** retry it: re-resolve the trace ids with `AND scope['name'] = '<supported scope>'` (the error lists the current allowlist) and score those.

For other fixable span issues you may retry the helper **once**; if it still errors, report the error. When you report an evaluator error — or, with no error text supplied, ask for it — say which of these three it is (or likely is) and, for the unsupported-scope one, state explicitly that it is deterministic per trace and will not be retried as-is; re-resolving to a supported scope is the only fix.

### Scores are persisted so they can be read back later

> **When the user asks to STORE / persist / "query later" scores, tell them ALL of this before writing:**
>
> 1. `evaluate` returns the score inline but does NOT store it — the helper writes each back as a
>    `gen_ai.evaluation.result` record so it is queryable later (Section 7).
> 2. NAME the results log group `/aws/cloudwatch/evaluations/results/<sanitized-service-name>` and say the
>    helper CREATES it if absent. The helper sanitizes non-safe characters to `_` and truncates to the
>    log-group name limit, so the final segment may not equal the literal service name.
> 3. WARN it stores the judge's prose `explanation`, which quotes the agent's own inputs/outputs — the
>    group inherits the conversations' sensitivity and is readable by anyone with log read access.
> 4. RECOMMEND retention (`--retention-days`) and a customer-managed KMS key (`--kms-key-id`); note the
>    data is billed like any other log data.
> 5. Note writeback is BEST-EFFORT and NUMERIC-only — a categorical-only result stays in the receipt,
>    not the log group; a missing `logs:PutLogEvents` leaves the score non-durable.
> 6. Mention `--no-writeback` for users who do not want scores in their logs.

`evaluate` returns a score inline but does not store it, so the helper also writes each one back as a `gen_ai.evaluation.result` telemetry record under `/aws/cloudwatch/evaluations/results/<sanitized-service-name>` — the same shape online evaluation emits. A score therefore outlives this conversation and can be queried later (Section 7), by a later session or another user, alongside the online results. This is best-effort: the receipt reports `persistedTraces` (how many traces' scores were written) plus the `resultsLogGroupPrefix`, or carries a `notes` entry explaining why a write did not happen (for example the caller has no `logs:PutLogEvents` — the score is still in `results`, it just is not durable). Pass `--no-writeback` when the user does not want scores written into their logs. Writeback covers **numeric** scores only — a successful row whose `value` is `None` (categorical-only) is returned in the receipt but not written back; the helper also filters failed jobs on the write path so they never persist for on-demand.

**Writeback creates a log group, and what it stores is sensitive.** If `/aws/cloudwatch/evaluations/results/<sanitized-service-name>` does not exist, the helper creates it — with 90-day retention by default (`--retention-days` to change; `0` opts out), and optionally a customer-managed KMS key if `--kms-key-id` is passed — and its stored data is billed like any other log data. The records include `gen_ai.evaluation.explanation`, the judge's prose, which quotes the agent's own inputs and outputs — so this log group inherits the sensitivity of the conversations being scored, and it is queryable later by anyone with read access to it. Name the results log group to the user before the first writeback (the receipt reports `resultsLogGroupPrefix` but cannot tell you whether it already existed — use `aws logs describe-log-groups --log-group-name-prefix` if you need to know), and recommend they set retention (`aws logs put-retention-policy`) and attach a KMS CMK (`aws logs associate-kms-key`) so scored prompt and completion text is not held indefinitely in plaintext.

### Synthesizing the receipt

A run returns one receipt whose `results` is the per-(trace, evaluator) matrix — each row a numeric **value** and/or a categorical **label** (which one depends on the evaluator's rating scale), the evaluator's **explanation**, and an error marker when that cell could not be evaluated. Turn the matrix (and across runs if you had to split) into a finding, not a table dump. A per-evaluator mean is the FLOOR, not the answer.

**Know the rating scale before you summarize — `value` and `label` are two shapes:**

- **Numerical evaluator** (has a `value`): summarize the **distribution** — the range and how many sit at the low end — not just a mean. A mean of 0.6 hides "6 great + 4 zero" vs. "all mediocre". Any `label` here is a natural-language gloss on the number (e.g. `0.5 = "Somewhat Helpful"`) — carry it, don't treat it as the score.
- **Categorical evaluator** (has a `label`, no `value`): there is nothing to average — report a **count per category** ("6 Excellent, 3 Good, 1 Poor").

**Good vs. bad is NOT in the result — it comes from the evaluator's scale.** A low number is not automatically bad and `0` can be the DESIRED outcome (e.g. a refusal or toxicity check). The direction, range, and category ordering live on the evaluator's configured scale (`get-evaluator` when you need it), never on the raw magnitude or on the label TEXT (a free-form descriptor, not a pass/fail flag). When the direction isn't obvious, read the explanation before you call an outcome good or bad. See "Polarity" in Section 7 for the known inverted evaluators.

**Then find the patterns the numbers hide — this is where the insight is:**

- **Cluster the poor cells by shared CAUSE** from their explanations. When several traces come out badly for the same reason, say it once and name those traces ("4 traces failed Correctness — all invented a `region` value not in the input: T2, T4, T7, T9") rather than restating a reason per row.
- **Always carry the WHY, scaled to size.** A few notable cells → give each one's reason. Many that share a cause → the cluster's reason once. Many notable cells with VARIED reasons → give a high-level characterization (the main themes, or how many distinct causes) and invite the user to probe specific traces/evaluators — do NOT enumerate every reason, and do NOT drop the reasoning entirely.
- **Roll up the OTHER axis:** call out traces that come out poorly across MULTIPLE evaluators (a broadly-bad response, worth prioritizing) — distinct from one that only dips on a single dimension.
- **Surface the outliers and the errored cells specifically** — the worst results and any cell that could not be evaluated — not every row.

**Shape of the answer — always deliver the insight; scale only how much raw detail rides with it:**

- **Small matrix → detail is affordable.** A compact view of the actual cells (a small table is fine) plus the takeaway. One trace × several evaluators is a single compact row, NOT a section per evaluator.
- **Large matrix → summarize INSTEAD of dumping the grid — never skip the analysis.** Lead with the distribution / category counts, the clusters + worst traces, and WHY the notable ones landed there. "Large" means "summarize, not enumerate"; it never means "give a bare number and stop."
- **Uniform results → collapse, at any size.** If everything landed the same (e.g. all good), one line says so; break out a specific evaluator or trace ONLY where it deviates.
- **Never blend evaluators into one combined score** (operating contract) — a scoring rule, NOT a layout rule; it does not require a separate table per evaluator.
- Close on what the finding sets up — a failing cluster is a ready-made set to re-check after a fix, or to build an evaluation dataset from (Section 6).

For many sessions or continuous coverage, use online evaluation (Section 5).

---

## 5. Online (continuous) evaluation and custom evaluators

### Online evaluation — score live traffic over time

Best for **continuously monitoring** a deployed agent — it samples live sessions and scores them, accruing results in `logs.default`. All ops on `bedrock-agentcore-control`:

| Intent | operation |
|---|---|
| Create | `create-online-evaluation-config` |
| List / inspect | `list-online-evaluation-configs` / `get-online-evaluation-config --online-evaluation-config-id <id>` |
| Enable / disable (pause) | `update-online-evaluation-config --online-evaluation-config-id <id> --execution-status ENABLED\|DISABLED` |
| Change evaluators, sampling, or data source | `update-online-evaluation-config` (a data-source change re-runs the `@logGroupName` verification below) |
| Delete | `delete-online-evaluation-config --online-evaluation-config-id <id>` — destructive; name the config and confirm first |

`status` (ACTIVE / CREATING / …) is the provisioning state only; `executionStatus` (ENABLED / DISABLED) is the separate field that switches scoring on or off — ACTIVE says nothing about whether scoring is enabled. And neither field proves scores are being produced: a config with a misresolved data source goes ACTIVE/ENABLED and scores nothing (see the `@logGroupName` rule below). Online evaluation only scores sessions arriving **after** it is enabled. This sets up and manages scoring; to **report** what it found, query the evaluation-result telemetry (Section 7), not the config.

> **When the user asks to set up online / continuous evaluation — whether or not they name a
> log group — tell them ALL of this before any create:** you will run the `@logGroupName` query
> against the agent's own spans first (a named group is the group you verify, not permission to
> skip verification); the group must never be taken from
> `resource['attributes']['aws.log.group.names']`, because that yields a config that goes
> ACTIVE/ENABLED and silently scores nothing; you will show the candidate groups with their span
> counts for approval; if the group is not confirmed you will not create — you report what you
> found and wait; the create is a real write — draft → confirm the specifics → call → report the
> returned `onlineEvaluationConfigId`; and you will never report it as created without that id.
> Say this in the answer even when you cannot run the query yet (no Region or Space given).

Gather before creating:

- **One agent per config.** `dataSourceConfig.cloudWatchLogs.serviceNames` is **exactly one** service (`logGroupNames` up to 10, or `logGroupNamePrefixes` 1–5 as the alternative). To watch N agents, create N configs — never fold several agents into one.
- **Log group(s) — read them off the agent's own spans; never derive, construct, or guess a name.** The `@logGroupName` column records the log group each span actually landed in:

  ```sql
  SELECT `@logGroupName` AS log_group, COUNT(*) AS spans
  FROM "traces.default"
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '24 HOUR' AND NOW()
    AND resource['attributes']['service.name'] = '<service>'
    AND resource['attributes']['aws.service.type'] = 'gen_ai_agent'
  GROUP BY `@logGroupName`
  ORDER BY spans DESC
  LIMIT 10
  ```

  - Every returned row is a group **proven** to hold this service's spans — the row is the proof, so run no separate span check. Pass each name **verbatim**: never add or remove a leading slash (`aws/spans` is a real group, `/aws/spans` is not). Skip NULL/empty rows.
  - **Pass every returned group**, highest span count first, up to the 10-group cap — a service may legitimately emit to several, and passing only one leaves the rest unevaluated. If more than 10 return, pass the top 10 and say which you dropped.
  - **Show the resolved group(s) with their span counts and get the user's approval before creating.** `service.name` is self-declared by whatever emits the telemetry, so a resolved group is a proposal, not a fact to act on.
  - **Never** resolve from `resource['attributes']['aws.log.group.names']`. It is absent for many agents (it is self-declared by the OTel/ADOT config, so EKS/ECS/other-hosted ones omit it), and where present it names the runtime's `<name>-<id>-DEFAULT` application group — which exists and holds stdout lines but **zero spans**. Creating against it yields a config that goes ACTIVE/ENABLED and scores nothing, silently.
  - **Always run the query before any create — no request waives it.** A user naming a log group is not permission to skip verification and not consent to an unverified create; it is the group you verify.
  - **When the query does not confirm the group** — no rows (widen to 7 days and re-run first), the query errored, or it returned rows and the named group is not among them — **do not create.** Report what the query showed (naming the groups it did return), say the group is unconfirmed and that if it is wrong the config will score nothing without erroring, then stop and let the user decide. An unconfirmed group is not necessarily wrong: an idle agent is legitimate to configure.
  - **If the user answers that report by telling you to create anyway** ("I don't care", "go ahead"), create it and state in the result that the log group is unverified. That override requires an instruction given **after** you reported the problem — never infer it from the original request.

  **HARD STOP — run the `@logGroupName` query before every create, and never create against an unconfirmed group until the user has been told it is unconfirmed and has answered that you should proceed.** The same applies to an `update` that changes the data source. A misresolved group produces a config that goes ACTIVE/ENABLED and scores nothing, with no error to signal it — the user must hear it from you before the write, not from empty dashboards afterwards.
- **Evaluators (1–25) — or `insights` (up to 10) instead; exactly one of the two lists is required** — evaluator ids from `list-evaluators`. Omitting both (or sending an empty `evaluators`) is rejected with "Exactly one of evaluators or insights must be provided"; 26 evaluators is rejected with "Member must have length less than or equal to 25".
- **Sampling percentage (required, 0.01–100)** — there is no server default; 10 is a reasonable start.
- **Execution role ARN (required)** — online eval runs under an IAM role AgentCore assumes to read traces, write results, and (for custom evaluators) invoke the judge model. You cannot create IAM roles from this skill, so resolve one in this order:
  1. **Reuse an existing role.** Discover candidates with `aws iam list-roles` and offer any whose NAME starts with `AgentCoreEvaluationRole` / `AgentCoreEvalRole`, OR whose TRUST POLICY PRINCIPAL is `bedrock-agentcore.amazonaws.com`. An account that already runs evaluations usually has one — show the matches and let the user pick.
  2. **Else have the user create one** — the AgentCore Evaluations console ("Create and use a new service role"), or the AgentCore CLI/SDK (`auto_create_execution_role=True`) — then use the returned ARN.

  Do NOT hardcode the role's IAM policy here — it drifts; the console/CLI build the authoritative policy on creation. At a glance the role trusts `bedrock-agentcore.amazonaws.com` and needs CloudWatch Logs read/write + log-index and (for custom evaluators) Bedrock invoke, but confirm the exact current trust + permission policy against the AWS documentation rather than reciting a possibly-stale one.
- `enableOnCreate` (required) — `true` scores immediately, `false` creates it paused.

```
aws bedrock-agentcore-control create-online-evaluation-config \
  --online-evaluation-config-name my_agent_helpfulness \
  --rule '{"samplingConfig":{"samplingPercentage":10.0}}' \
  --data-source-config '{"cloudWatchLogs":{"logGroupNames":["<every confirmed @logGroupName, verbatim, highest span count first, max 10 — never a constructed name>"],"serviceNames":["<resolved service.name>"]}}' \
  --evaluators '[{"evaluatorId":"Builtin.Helpfulness"}]' \
  --evaluation-execution-role-arn <execution-role-arn> \
  --enable-on-create
```

The config name uses **underscores, not hyphens**. Report the returned `onlineEvaluationConfigId`. While a config that uses a custom evaluator is ENABLED, that evaluator is locked — disable the config before editing or deleting the evaluator.

### Author a custom evaluator (only when no built-in fits)

Built-ins are referenced, never created. Author a **custom** evaluator only when the user wants something the built-in set does not score — either an **LLM-as-judge** (a judge model plus scoring instructions and a rating scale) or a **code-based** one (`CustomCode`). All three operations are `bedrock-agentcore-control` calls: `create-evaluator`, `update-evaluator`, `delete-evaluator`.

**These are writes — draft with the user, then confirm.** Gather what it should score, the `level` (`TRACE` / `TOOL_CALL` / `SESSION` — a **response-quality** dimension such as brand voice, tone, or conciseness is judged at `TRACE` level), and, for an LLM judge, the judge model, the scoring instructions, and the scale. **Present the draft back before creating** — its name, what it judges, the level, the judge model, and the rubric — and create only after the user confirms *that specific draft*. Never invent the rubric, and never treat a "yes" from an earlier turn as approval of a rubric the user has not seen. A delete is destructive and a change alters what every future run is judged on, so confirm those too.

- **Read the exact `evaluatorConfig` shape from the CLI's own model — do not guess it.** `aws bedrock-agentcore-control create-evaluator help` gives the required fields, types, and nesting (`llmAsAJudge` vs `codeBased`; the judge model under `modelConfig.bedrockEvaluatorModelConfig`; the `ratingScale`). If a create still fails validation, the error carries the input schema — correct against it.
- On `update-evaluator`, resend the **FULL** evaluator config; fields you omit revert.
- The name must match `[a-zA-Z][a-zA-Z0-9_]{0,47}` (start with a letter; letters, digits, underscores; no hyphens; ≤48 chars) and must not collide with a built-in name.
- `description` is a short **label** for the listing (≤200 chars) and is **not** read by the judge — only `instructions` is. Keep it to one crisp sentence; put the rubric in `instructions`.
- Creation is asynchronous (`CREATING → ACTIVE`, terminal `CREATE_FAILED`) and Region-scoped — wait for `ACTIVE` before scoring with it, and keep the judge model in the same Region.
- While an online-evaluation config that uses a custom evaluator is ENABLED, that evaluator is locked — disable the config before editing or deleting it.

**Judge model (LLM-as-judge).** `evaluatorConfig.llmAsAJudge.modelConfig.bedrockEvaluatorModelConfig.modelId` must be a foundation model available in the Region — don't guess it. Discover it and fold a recommended model into the draft you present rather than asking as a separate step:

- Inference profiles (prefer these): `aws bedrock list-inference-profiles --type-equals SYSTEM_DEFINED` → `us.` / `global.`-prefixed ids, the form these judges use.
- On-demand text models: `aws bedrock list-foundation-models --by-inference-type ON_DEMAND --by-output-modality TEXT`.

**Instructions must embed a placeholder valid for the level.** A create with none, or with an unrecognized token, is rejected — a content rule the schema does not express. Use **single** curly braces (`{context}`); `{{context}}` and `${...}` / `%s` forms are rejected.

| `level` | Allowed placeholders (embed at least one, as `{token}`) |
|---|---|
| `TRACE` | `context`, `assistant_turn`, `expected_response`, `system_instructions` |
| `TOOL_CALL` | `context`, `available_tools`, `tool_turn`, `user_message`, `system_instructions`, `available_skills`, `invoked_skill`, `skill_content` |
| `SESSION` | `context`, `available_tools`, `actual_tool_trajectory`, `expected_tool_trajectory`, `assertions` |

`{context}` is valid at every level, so it is the safe default; add the level-specific tokens the rubric actually judges (e.g. `{assistant_turn}` for TRACE response quality, `{actual_tool_trajectory}` for SESSION tool use). Example TRACE instruction: `"Evaluate the assistant's response for conciseness.\n\nConversation:\n{context}\n\nResponse:\n{assistant_turn}\n\nScore 1-5, where 5 = tight and precise and 1 = excessively verbose."` If a create is rejected for placeholders, its validation error enumerates the allowed set for that level — follow that, and re-check single braces.

---

## 6. Datasets (create, manage, and build from traces)

A dataset is a versioned collection of schema-typed **examples** — the target for repeatable / regression evaluation, and the only way to supply ground truth (`expected_response`, `expected_trajectory`, `assertions`) to evaluators that need it. All ops on `bedrock-agentcore-control`. Optional: on-demand (Section 4) and online (Section 5) evaluation need no dataset.

**Writes are real** — creating/extending a dataset costs resources. Confirm with the user before any create or delete, and never act on a non-interactive request without confirmation.

### Dataset operations

| Intent | operation |
|---|---|
| Create (examples required) | `create-dataset` |
| Add / edit / remove examples | `add-dataset-examples` / `update-dataset-examples` / `delete-dataset-examples` |
| Publish an immutable version | `create-dataset-version` |
| Read (to support a write/summary) | `get-dataset`, `list-datasets`, `list-dataset-examples`, `list-dataset-versions` |
| Edit metadata / delete | `update-dataset` / `delete-dataset` |

### Core model — read before creating

- `schemaType` is chosen at creation and is **immutable**:
  - `AGENTCORE_EVALUATION_PREDEFINED_V1` — author-fixed conversation turns (what trace-derived examples use).
  - `AGENTCORE_EVALUATION_SIMULATED_V1` — an LLM actor drives the conversation from a goal; needs `actor_profile.goal`, so it cannot be derived from a trace.
  - `THIRD_PARTY_EVALUATION_V1` — the shape for datasets carrying third-party / external evaluation-framework examples. You will mostly **encounter** it on a dataset created elsewhere rather than create it here. Read the target dataset's `schemaType` with `get-dataset` before adding examples and build examples in the shape that dataset actually declares — a PREDEFINED-shaped example rejected against a third-party dataset fails the whole batch.
  - This type was renamed from `GENERIC_EVALUATION_PREDEFINED_V1`, and the old name was **removed rather than kept as an alias**: passing it to `create-dataset` now fails, and a dataset created with it earlier cannot be read back until its type is migrated. If `get-dataset` fails on a dataset that predates the rename, that is the cause — the dataset has to be recreated (or its type migrated by the service team), not worked around from here.
- A dataset **cannot be created empty** — `create-dataset` needs a `source`, either `inlineExamples.examples` (1–1000) or an `s3Source.s3Uri` pointing at a JSONL file.
- Writes edit the mutable **DRAFT**; `create-dataset-version` snapshots an immutable numbered version. Evaluations that need a stable target run against a published version.
- A dataset is keyed by **`datasetId`** (the name is a display label, pattern `[a-zA-Z][a-zA-Z0-9_]{0,47}` — use underscores); an example is keyed by its server-minted **`exampleId`** (returned by `add-dataset-examples`, shown by `list-dataset-examples`), **not** its `scenario_id`.
- **Editing or deleting an example keys off `exampleId` — resolve it first.** `update-dataset-examples` and `delete-dataset-examples` take `exampleId`s. A `traceId`, a `scenario_id`, or any id the user pasted is **not** the server-assigned `exampleId` — call `list-dataset-examples` and resolve it to the real `exampleId` before the write. Passing the wrong id deletes or overwrites the wrong example. Each entry in an update MUST carry the `exampleId` it replaces.
- **Validation is all-or-nothing.** Every example is validated against the dataset's `schemaType` before anything lands — one bad example rejects the whole batch. Fix and resubmit; a partial batch never writes.
- **Three size limits apply, not one.** (1) **Per request:** at most **1000** inline examples / ~**5 MB** — 1001 rows is a `400` ("Member must have length less than or equal to 1000"). (2) **Per dataset:** at most **1000 examples in total** across every request — the service returns **HTTP 402 `ServiceQuotaExceededException`** ("Maximum number of examples (1000) reached for this dataset") as soon as a write would push the dataset past 1000, so `add-dataset-examples` against a dataset that already holds examples fails even when the request itself is within limits. Count the existing examples (`get-dataset` / `list-dataset-examples`) before adding, and create a second dataset when the total would exceed 1000. (3) **Per example:** at most **1 MB** serialized — a single oversized example is a `400` ("Example at index N exceeds maximum size of 1MB") and, being one bad example, rejects the whole batch; trim or drop long inputs/outputs before sending.
- Writes accept an optional `clientToken` for idempotency — pass one when retrying a create/add so a retry cannot double-write.
- **`delete-dataset` and `delete-dataset-examples` are destructive and not undoable** — name what will be deleted and get the user's confirmation before calling, and never widen the scope they asked for. `update-dataset` edits metadata only (the name and `schemaType` are immutable).

### Example shapes

PREDEFINED example (the trace-derived shape):

```json
{
  "scenario_id": "checkout_happy_path",
  "turns": [{ "input": "Add the blue mug and check out", "expected_response": "Order placed — #A1B2." }],
  "expected_trajectory": ["search_catalog", "add_to_cart", "place_order"],
  "assertions": ["The order confirmation number is returned"],
  "metadata": { "sourceTraceId": "<traceId>" }
}
```

`scenario_id` + `turns` (each `input` non-empty) are the minimum. Optional ground-truth fields gate which evaluators can score the example: `expected_response` → correctness; `expected_trajectory` (ordered tool names) → tool-trajectory; `assertions` → goal-success. Omit them for ground-truth-free scoring.

SIMULATED example (author-supplied only — an LLM actor drives the turns, so this shape cannot come from a trace); `input`, `actor_profile.goal`, and `actor_profile.context` are required:

```json
{
  "scenario_id": "refund_dispute",
  "input": "I want a refund for an order that already shipped",
  "actor_profile": { "goal": "Get a full refund", "context": "Impatient customer",
                     "traits": { "tone": "frustrated" } },
  "max_turns": 8,
  "assertions": ["The agent explains the return policy"]
}
```

### Create a dataset

```
aws bedrock-agentcore-control create-dataset \
  --dataset-name checkout_regressions \
  --schema-type AGENTCORE_EVALUATION_PREDEFINED_V1 \
  --source '{"inlineExamples":{"examples":[ … ]}}'
```

Returns a `datasetId`; the dataset may be `CREATING` briefly — re-check `get-dataset` until `status` is `ACTIVE`. Then `create-dataset-version --dataset-id <id>` to publish the immutable version a repeatable evaluation targets.

### Build a dataset from traces

> **When the user asks to turn traces into a re-runnable / regression set, tell them ALL of this:**
> the capture helper builds the examples FROM the traces client-side (no server-side trace→example op);
> a repeatable target MUST evaluate against a PUBLISHED IMMUTABLE version, not the mutable draft;
> creation is a real write (draft → confirm → call) and you will report the returned `datasetId`;
> and before writing, the service caps apply — ≤1 MB per example and ≤1000 examples per dataset — and
> both caps reject the whole add rather than trimming it: a per-example >1 MB row fails the entire
> `add-dataset-examples` batch with a `400`, because validation is all-or-nothing (nothing lands unless
> every example passes), and the 1000-examples-per-dataset cap refuses the whole add up front with a
> service-quota error (create a new dataset with `--mode create` for the remainder). Neither is auto-split;
> and the capture helper itself caps each invocation at 25 traces (`MAX_TRACES`): if more than 25
> unique trace ids are supplied, only the first 25 become examples and the receipt notes that the rest
> need another run — so a large trace set needs multiple invocations.

There is no server-side "trace → example" operation, so this skill **bundles a tested helper**, [`scripts/cloudwatch-omni/capture_dataset_from_traces.py`](../../scripts/cloudwatch-omni/capture_dataset_from_traces.py), that does the whole fetch → reshape → validate → write. **Do not hand-reshape spans in the conversation** — the one-shot flow is error-prone and bloats context.

1. **Retrieve and run the helper** (this skill's supplementary file — fetch it, then run it with your shell). It queries each trace's spans from CloudWatch Omni (`traces.default`), converts each into a PREDEFINED example (root-span input/output, ordered tool trajectory), validates every example, and writes the batch:

   ```
   python capture_dataset_from_traces.py --mode create \
     --dataset-name checkout_regressions --trace-ids <id1>,<id2>,… --region <region>
   ```

   Append to an existing dataset with `--mode add --dataset-id <id>` (an id or a name; a name is resolved via `list-datasets`). It looks back 30 days (`--window-days`) and prints a compact JSON **receipt** (`datasetId`, `examplesWritten`, any per-trace `conversionErrors`) — raw spans never enter the conversation, and a partial/invalid batch never lands.
2. **Report the receipt** — the returned `datasetId` and counts. You are **not done** until the helper prints a `datasetId`. Relay it honestly: if the receipt lists per-trace `conversionErrors`, say which traces did not become examples rather than reporting only the successes; and when an example is stamped `metadata.partial = true` (its trace's span set was truncated, so the turns/trajectory may be incomplete), tell the user which ones are partial instead of presenting the set as complete.

(First resolve the trace ids with a telemetry query if the user named traces by symptom rather than id — Section 4's "Query → evaluate chaining" applies; the bad-end `traceId`s from Section 7 are also a ready-made input.)

**What the helper does (span → field mapping).** Read this only if you need to explain or extend the mapping — the helper implements it; do not re-implement it in the conversation:

- **Root span** = the span with no `parentSpanId` (fall back to the first span).
- **`turns[0].input`** — first non-empty string, preferring the **root span**, else the **first** span in start-time order; COALESCE these **string-valued** keys: `input.value` → `gen_ai.input_value`.
- **`turns[0].expected_response`** — same COALESCE on output keys, preferring the **root span**, else the **last** span (final answer): `output.value` → `gen_ai.output_value`. **Omitted** entirely if the trace has no output.
- The OTel GenAI `gen_ai.input.messages` / `gen_ai.output.messages` keys are **structured arrays**, not strings, so they are **not** used. Frameworks that emit only those message-array keys aren't captured by this string COALESCE.
- **`expected_trajectory`** — the ordered `tool.name` of the TOOL spans (`openinference.span.kind = "TOOL"` or `aws.genai.span_kind = "TOOL"`, by start time), with **adjacent duplicates collapsed** (`[a,a,b,a] → [a,b,a]` — a retried tool adds no signal; non-adjacent repeats keep real order). **Omitted** if no tools were called.
- **`scenario_id`** — the trace id (stable, unique per batch). **`metadata`** — `{ "sourceTraceId": <traceId> }`, plus `"sessionId"` when the spans carry `session.id`, plus `"partial": true` when the trace's spans were truncated.
- (`input.value` / `output.value` / `tool.name` are the OpenInference names; `gen_ai.*` are OTel GenAI-semconv fallbacks for frameworks that emit those instead.)

**Guardrails the helper enforces** (and that you must respect when splitting work):

- **Dedupes** trace ids; fetches each trace's spans once.
- **Validates before writing** — each example needs ≥1 turn, every `turns[].input` a non-empty string (or non-empty object), every example ≤ 1 MB — and drops traces whose input didn't extract, so a batch is never rejected wholesale.
- **Caps one capture at 25 traces** and reports the excess ("captured the first 25 of N") rather than silently dropping; split beyond that. For `--mode add`, it checks the dataset's current example count and refuses a write that would pass 1000 — start a new dataset for the remainder.
- **Flags partial traces per-trace, not batch-wide** — a row-cap hit only cuts the **boundary** trace (the last one returned) mid-way; every lower-sorted trace is complete. Only the boundary trace gets `metadata.partial = true`. Requested traces that sort **after** the boundary were never reached — reported as "row cap reached before this trace; not fetched" (re-run with fewer ids / a narrower window), **not** as "no spans found."
- **Report a receipt, not the data** — after writing, report the dataset id, example count, and any per-trace conversion errors; do not echo the example JSON or raw spans back into the conversation.

### Summarize a dataset

Read with `list-dataset-examples` (paginate with `nextToken`) and report a compact synthesis — the count, the schema type, a few representative scenarios, notable gaps. Do not dump every example into the conversation.

---

## 7. Reading back stored scores

Reading stored scores is a **two-part** job: the **retrieval plan and reporting** (what to fetch, in what order, and how to turn rows into a finding) and the **query mechanics** (schema, filters, ready SQL). Every scored result — online, on-demand, or batch — lands as a `logs.default` record readable by any user with access, not just whoever ran the evaluation.

### Retrieval plan — how to read and report

**Rollup first, whenever the evaluator scope is open.** The per-evaluator rollup (Q1) reveals WHICH evaluators sit at the bad end by polarity, so it runs first whenever the ask spans multiple or unnamed evaluators ("how are they doing", "why are they failing", "what's wrong", "which are worst"). You can't open with a drill / bad-end / `explanation` fetch — you don't yet know what to drill. A named **service, dataset, session, or time-window does NOT pin the evaluator** — the scope is still open, so rollup first. Two things do NOT let you skip it: (1) **a guessed evaluator set** — deciding yourself which evaluators are "failing" is not the user naming them; (2) **an invented score cutoff** — don't add a fixed `WHERE score < 0.5` to *define* "failing" (no universal pass mark; polarity may be inverted), and don't reproduce one as `SELECT` buckets either (`SUM(CASE WHEN score >= 0.5 …) AS pass_like` is the same invented pass mark, just moved out of the `WHERE`). Ranking by score is fine — sort by each evaluator's bad direction and take the worst N; just don't hard-code an absolute pass/fail line.

**A missing region / `service.name` / time-window is NOT a precondition — lead with the rollup, then offer to scope down.** When the ask is to interpret or summarize an evaluation run and no region, service, or window was supplied ("how are my agents doing", "how did the run go"), run the rollup FIRST at the broadest reasonable scope — omit the `service.name` filter so it spans every scored agent, over a sensible default window (the 7-day window the patterns below use) in the Space already in context — then report it, drilling the WHY of any bad-end evaluator per the second pass below, and OFFER to narrow by region, service, or window. Region / `service.name` / window are inputs you gather to DRILL DEEPER, never a gate the first rollup waits behind; the placeholder filters in the query patterns below are scope-down options, not inputs you must collect before running. The user asked for a read, so lead with the read rather than stopping to ask for scope.

**The number of rollup VIEWS is bounded by the intent the user EXPRESSED — but the WHY-drill is not optional once the rollup surfaces a bad-end evaluator.** A **status** ask ("how is X doing", "tell me about X performance", "average X", "what's our X") is answered by the per-evaluator rollup **plus a required WHY-drill into the worst 2–3 evaluators that sit at a bad end by polarity** (pull their `explanation` field — see the second pass below): run the rollup, and if any evaluator is at a bad end, drill the worst 2–3 of those by polarity for the WHY, report that, then *offer* the deeper cuts. If NO evaluator is at a bad end (all healthy, or only one evaluator and it is healthy), report the rollup, name the worst-by-polarity evaluator as healthy, and skip the `explanation` fetch. Do NOT add, on your own initiative, a time-bucket / trend view, a per-agent view, a per-session view, or any other break-down **dimension** the user did not name — each extra dimension is another query round, and the user asked a fast question. A break-down runs only when the user **named that slice** ("per session", "by day", "which agent", "break it down by …") or asked to go deeper. When they DID ask to drill or investigate, fan out properly — the multi-slice breakdown is the right answer there, and this ceiling is not a reason to under-answer a real investigation.

**Once the evaluator scope IS pinned, answer it directly.** When the user named the evaluator(s), or the rollup has surfaced the bad ones, match the query to the ask: a **status/number** ask ("average Correctness") → the per-evaluator aggregate scoped to it, **plus the required WHY-drill when the pinned evaluator(s) sit at a bad end by polarity — pull the bad-end evaluator's `explanation` (Q3), the worst 2–3 by polarity when several are in scope (ceiling 4), so even a plain status answer carries the WHY; when the pinned evaluator(s) are healthy, report the number(s), name the result as healthy, and skip the `explanation` fetch**; a **"why"/deeper** ask ("why is Correctness failing", "which sessions") → the same bad-end `explanation` drill (Q3), read by polarity, widened as the ask warrants.

**Evaluator names are DATA, not a fixed catalog — do NOT assume the `Builtin.` prefix.** A user's common term ("toxicity", "bias") is not necessarily the stored `gen_ai.evaluation.name`: the real name may be `ThirdParty.<Provider>.Toxicity`, a custom evaluator's id, etc. To scope to an evaluator the user named, either (a) match LOOSELY (`… attributes['gen_ai.evaluation.name'] ILIKE '%toxicity%'`) or (b) first read the DISTINCT evaluator names in the window (the rollup already lists every name that ran) and map the term to the real one. **An empty result from an exact-name filter is INCONCLUSIVE** — it may be a name mismatch, not absence. Only conclude an evaluator isn't running when it is absent from the DISTINCT-names list for the window; when unsure, say the exact name wasn't found and offer to match loosely.

**Compose the rollup as SEPARATE queries — three shapes, ONE GRAIN PER QUERY.** Never fuse two grains into a single query with a `row_type` discriminator and padded `CAST(NULL AS …)` columns to "get both shapes at once" — that SQL is slow to write, fragile, and Q1 already tells you which shape you need (`avg_score` non-NULL ⇒ numerical, stop; `avg_score = NULL` with `scored > 0` ⇒ categorical ⇒ Q2). Read the shape off Q1 instead of guessing it inside one bundled query.

- **Q1 — per-evaluator rollup (the headline): scores + errored SIDECAR in ONE query.** Conditional aggregation splits scored vs errored INSIDE the aggregates (not in `WHERE`), grouped by evaluator name. Numerical evaluators get a real `avg_score` + spread; categorical come back `avg_score = NULL, scored > 0` → read by label in Q2. `failed_to_run` is the sidecar for EVERY evaluator — report it as "(+N failed to run)" beside the scores: surfaced, NOT hidden, and NEVER conflated with a low SCORE.
- **Q2 — categorical label distribution (a SEPARATE call):** count grouped by evaluator + label, gated `error.type IS NULL`. Issue it for the NULL-avg (categorical) evaluators. **Categorical = read by label, not "no data"** — report those evaluators by name, never drop them or call them scoreless. **A NUMERICAL evaluator gets NO label query at all.** Once ANY query has come back with a real `avg_score` for an evaluator (this turn or an earlier one), that evaluator is numerical and the question is settled: do NOT issue Q2 for it, do NOT add `label` to a `GROUP BY` on it, and do NOT hedge by asking for both shapes in one query. Its `label` is only a gloss on the number (carry it if a row already has it); a label roll-up on it adds rows, not information.
- **Q3 — the WHY of the low ones (required whenever the rollup surfaces a bad-end evaluator — see the second pass), and/or the `error.type` breakdown (only on an explicit execution-failure ask).** The errored COUNT already shows in Q1's sidecar; Q3 is the detail, not the rollup.

**First pass — per-evaluator rollup.** For **each** evaluator on its own — **numerical** by **avg + spread (min/max) + count**, **categorical** by **label distribution + count**. Never a single blended number across evaluators (operating contract). **This holds inside every break-down dimension too:** per session (or per day, per online-eval config), roll up per (dimension × evaluator), never a single per-session number that averages distinct evaluators together. The per-evaluator table IS the headline; do NOT open with a "Headline KPIs" dashboard of invented top-line metrics.

**Read each evaluator per its polarity — never a blanket "low = bad."** Higher-is-better for most evaluators, but for **inverted** ones — Toxicity, Harmfulness, Bias, Stereotyping, Refusal, PII-leakage — a **higher** score is worse. For a **categorical** evaluator judge by the label, not a number. `0` can be the DESIRED outcome. Don't rank, or pick "worst," by low score alone.

**Second pass — drill into the worst evaluator(s), BOUNDED and REQUIRED WHEN THE ROLLUP SURFACES A BAD-END EVALUATOR.** Runs after the rollup on **every** eval-results report that has at least one evaluator at a bad end by polarity — including a plain status ask, not only "why" / "failing" / "what's wrong" asks. **"Bad end" is a judgment from the rollup's own spread, not a fixed threshold:** an evaluator is at a bad end when its scores cluster toward that evaluator's bad pole by polarity or show a visible bad-end tail — Q1's `min`/`max` spread reaching the bad pole (a low `min` for higher-is-better, a high `max` for an inverted one), or bad-pole labels in Q2 — never because they crossed an invented universal cutoff. Pull the `explanation` field for those worst, bad-end evaluators so the answer carries the WHY, then offer the deeper cuts. **When every evaluator sits toward its good pole (no bad-end cluster or tail), none is at a bad end: report the rollup, name the worst-by-polarity evaluator as healthy, fetch no `explanation`, and OFFER the drill rather than forcing it.** It is tightly bounded:

- **Drill the worst 2–3 bad-end evaluators by polarity (a HARD ceiling of 4) — required whenever a bad-end evaluator exists, not a default to skip.** Pick them from the rollup (worst by each evaluator's own polarity, among those at a bad end); do NOT drill middling or clean evaluators — if fewer than 2–3 sit at a bad end, drill only those that do, and if none do, drill nothing. Do NOT widen past the ceiling unless the user explicitly asks ("all", a named evaluator, "go deeper"). Drilling every non-max evaluator is the main cause of a turn running long.
- **ONE query PER drilled evaluator, issued together as one batch — ranked, not thresholded.** Each query is filtered to one evaluator and ranked top-N (~15) by that evaluator's own polarity, worst first (a categorical evaluator ranks by label / recency — a numeric predicate silently drops every categorical row). The queries are independent, so start all of them before reading any result rather than running them one round at a time. Do NOT fuse them into one query (`QUALIFY … PARTITION BY evaluator`, or a flat `LIMIT`): a fused result is read from the top, so later-sorted evaluators get starved or dropped — no WHY for them, and a second drill round. And do NOT filter by an invented cutoff (`score < 0.5`).
- **One representative example per drilled evaluator, then STOP and offer more.** Give the shared cause per drilled evaluator + ONE real bad-end example each — "Correctness (6 low): mostly missing-context, e.g. *'…'*" — not just "6 scored low." **The fetched WHY MUST appear in the final answer** — the cause is the headline, not an appendix.
- **Never conclude "no bad results" for an evaluator you drilled from a capped/truncated slice** — that's absence-vs-truncation, not proof. (This applies only to the ones you drill; it is NOT a mandate to drill the others to prove them clean.)

**Show one representative example — the actual scored input/output.** For a notable finding, fetch the trace's prompt → agent response for ONE representative **poorly-scored** result — a real bad-end *score*, NOT an errored (`error.type`) job (those have no score, no explanation, and often no valid trace to fetch) — and show it concretely ("user asked *'…'*, the agent replied *'…'*"), not every row and not full transcripts.

**Traces for low-scoring evaluations — match the depth to the ask.** Each bad-end eval record already carries its scored trace's `traceId`, so the bad-end results give you the trace ids directly. Handing traces to a **next step** (add to a dataset, re-evaluate) needs only those `traceId`s — no trace fetch. Showing the **actual trace** (prompt / response / spans) means querying `traces.default` for those ids. Don't over-fetch.

**"Failing" evals mean LOW SCORES, NOT execution failures.** Disambiguate BEFORE composing the query. "Failing evals", "failing", "bad", "poor", "worst", "underperforming", "unhealthy", "what's wrong" — with NO execution-failure wording — mean evals **performing badly: a low/bad SCORE judged by polarity, or a bad-end label** (SCORED records, `error.type IS NULL`). That is the DEFAULT, and it does not change the ORDER — the FIRST query is still the rollup. This holds for the word "evaluation(s)" too: "which online evaluations are failing?" means low-scoring RESULTS scoped to online-produced records, `error.type IS NULL` — NOT the online-eval configs/jobs failing to run; the `online` / `on-demand` / `batch` word is ONLY the eval-TYPE scope. "Which tool/span are the failures concentrated in?" means: after the rollup, take the bad-END SCORED results, follow their `traceId`s into `traces.default`, and group the spans/tool-calls there. Treat it as **execution failures** (`error.type IS NOT NULL`) ONLY when the user EXPLICITLY says "failed to run", "failed to execute", "execution failure(s)", "errored", "did not run". An `error.type` record is NOT a "failing" score; there is no pass/fail and no "pass rate". When errored jobs fall in the window, say so ("N scored, **Y failed to run** (`<error.type>`)") rather than silently omitting them.

**"Unhealthy / underperforming online evaluators" is this same RESULTS question.** Answer it by filtering the scored results by `attributes['aws.bedrock_agentcore.online_evaluation_config.name']` and rolling up per (config × evaluator) by polarity (`error.type IS NULL`) — NOT by reading `list-online-evaluation-configs` / `get-online-evaluation-config`. A config's `status` / `executionStatus` describe provisioning and on/off, not evaluation quality; an ACTIVE / ENABLED config exposes no health field. Use `error.type` only on the explicit "failed to run / errored" ask.

### Query surface — dataset and schema

> **When the user asks to read eval scores or `gen_ai.evaluation.*` from `traces.default`, or
> asks which table holds them, tell them ALL of this:** NO — evaluation results are LOG records
> in `logs.default`, not spans in `traces.default`; on `traces.default` those attributes are not
> span columns, so the query returns zero rows silently, with no error; that failure is silent —
> zero rows is indistinguishable from "no evaluations ran" unless the table choice is checked;
> what IS valid on `traces.default` is reading the scored trace's own spans by `traceId`; and the
> eval-result field names live with the `logs.default` surface (table below).

Each score is a **log record** in **`logs.default`** (query `FROM "logs.default"`, or the unscoped `"default"`) — **NOT `traces.default`**, where the agent's own request/response spans live. **Reading `gen_ai.evaluation.*` off `traces.default` is not an error — those attributes are not span columns, so they come back `NULL` for every span row.** The eval-read pattern *filters* on them (`WHERE attributes['gen_ai.evaluation.name'] IS NOT NULL`), so on `traces.default` that filter matches nothing and the query returns **zero rows** — indistinguishable from "no evaluations ran" unless you notice the wrong table. What *is* valid on `traces.default` is reading a scored trace's own spans by `traceId` (Section 7's trace-first join); the eval scores themselves live only in `logs.default`. Identify eval-result records by the evaluator-name attribute:

```
attributes['gen_ai.evaluation.name'] IS NOT NULL
```

**Use these attribute paths verbatim — never shortened.** The query engine reads the key **literally** — a wrong or shortened path (e.g. `attributes['score.value']` for `attributes['gen_ai.evaluation.score.value']`) is **not** an error; it silently returns **NULL for every row** (an empty `avg_score` for *all* evaluators), which then wastes turns re-discovering the schema.

| Field | What it is |
|---|---|
| `attributes['gen_ai.evaluation.name']` | The identifier the score is filed under — filter/group on this. For built-in evaluators this is the display name (e.g. `Builtin.Helpfulness`, where id and name coincide); online records carry the evaluator **name**. For **custom** evaluators, on-demand records written by `evaluate_traces.py` carry the server-minted `evaluatorId` here (not the human-readable name), so resolve the id from `list-evaluators` before filtering |
| `attributes['gen_ai.evaluation.score.value']` | Numeric score, **string-typed** — `CAST(... AS DOUBLE)` before aggregation. **NULL for a categorical evaluator** (label-only); **empty and non-numeric on an errored job** |
| `attributes['gen_ai.evaluation.score.label']` | Human-readable label, e.g. `Above And Beyond` / `Very Helpful` / `Yes`. **Usually present for BOTH numerical (naming the score level) and categorical evaluators — but not guaranteed.** A **categorical** evaluator has ONLY this. NULL on an errored job |
| `attributes['gen_ai.evaluation.explanation']` | The evaluator's rationale (the "why"). Empty on an errored job |
| `attributes['session.id']` | The scored session |
| `resource['attributes']['service.name']` | The agent scored. **Online evaluation** records use `'<service>.DEFAULT'`; **on-demand** records written by `evaluate_traces.py` use the raw service name (no `.DEFAULT` suffix). Scope with `IN ('<service>', '<service>.DEFAULT')` to match both exactly (a prefix `LIKE` would also pull in `<service>-api`, `<service>-worker`, …), or `= '<service>.DEFAULT'` for online only |
| `attributes['aws.bedrock_agentcore.online_evaluation_config.name']` | Online-eval config that produced the record; **NULL for on-demand** |
| `attributes['aws.bedrock_agentcore.evaluation_level']` | `TRACE` / `TOOL_CALL` / `SESSION` |
| `attributes['gen_ai.evaluation.partial']` | `'true'` when scored on a truncated span set (span fetch hit its row cap); exclude or caveat when aggregating |
| `traceId`, `` `@timestamp` `` | The scored trace and when the score was written. Top-level `traceId` is **empty on an errored job** |
| `attributes['error.type']` | Present **only when the eval JOB ERRORED / did not run** (e.g. `ValidationException`); **NULL on success**. Marks an **execution error** — a job that produced NO result — it is **NOT** a low or "failing" SCORE. When set, `score.value` / `label` / `explanation` are all empty. The failure gate |
| `attributes['error.message']` | The error reason (e.g. *"…spanIds that do not exist…"*) |
| `attributes['gen_ai.evaluation.target.session_id']`, `attributes['gen_ai.evaluation.target.span_ids']` | What an (errored) job was asked to score — use these to correlate an error, since an errored record's top-level `traceId` / `spanId` are empty |

### Validity and filter rules

- **`error.type IS NULL` is the "job succeeded" gate.** A record with `gen_ai.evaluation.name` present is **not** necessarily a score — the job may have **errored**, in which case `score.value` / `label` / `explanation` are all empty and `score.value` is non-numeric. **Every score query filters `AND attributes['error.type'] IS NULL`** (the Q1 rollup is the deliberate exception — it buckets errored rows with `CASE` instead). This also prevents `CAST(<non-numeric> AS DOUBLE)` failures ("failed to coerce" / "results fail to compute"), most visibly where the CAST is in a `WHERE` / `ORDER BY` comparison. `evaluate_traces.py` filters failed jobs on the write path so they never persist for on-demand, but **online-evaluation records can still fail server-side and land in `logs.default` with `error.type` set** — keep the gate on every score query rather than assuming the corpus is failure-free.
- **A scored record has a `score.value` OR a `score.label`.** Categorical evaluators have ONLY a label. The valid-result predicate is `error.type IS NULL AND (score.value IS NOT NULL OR score.label IS NOT NULL)`.
- **Do NOT gate on `score.value IS NOT NULL` alone.** `CAST(NULL AS DOUBLE)` is safe — it yields NULL, which `AVG` skips and a `< 0.5` comparison drops — so that filter adds no safety and silently **drops every categorical evaluator**. Let `error.type IS NULL` do the gating.
- **On-demand writeback covers numeric scores only** (Section 4). An on-demand categorical result lives only in the receipt, not in `logs.default`; online categorical scores are persisted server-side and do land. When a categorical-label-distribution query returns fewer rows than expected for a service, check whether the missing scores were on-demand categorical runs.
- **Scope:** the defaults below use `IN ('<service>', '<service>.DEFAULT')` and so include both online and on-demand records for exactly that service (never a prefix `LIKE`, which would blend sibling services such as `<service>-api` into the rollup). An on-demand-only or online-only report has to scope explicitly ("Other filters" below), or an on-demand quality regression can be masked by a larger online sample scoring well over the same window.

### Polarity for filtering — pick the "bad" end

When a query filters to the *bad* results, pick the bad end **per the evaluator's polarity** — do NOT hardcode one comparison for every evaluator:

- **Higher-is-better is the default** — a **low** score is the bad end (`< threshold`, e.g. `< 0.5`).
- **Inverted evaluators flip to the HIGH end** — for **Toxicity, Harmfulness, Bias, Stereotyping, Refusal, PII-leakage** a **higher** score is worse, so the bad end is `> threshold`.
- **Categorical evaluators are judged by their LABEL**, not a number — filter on the bad `score.label` value(s), never on `score.value`.
- **This inverted list is a HINT, not exhaustive.** For an unknown or custom evaluator, judge by its label or its `get-evaluator` rating scale; **never assume higher-is-better**, and **never** flag "failing" with `score.value = 0` or `score.label LIKE '%fail%'` — evaluators sit on their own scales with no universal pass/fail.

A single-comparison bad-end query must be **polarity-homogeneous** — do not mix inverted and higher-is-better evaluators in one `IN (...)` list behind one `<` / `>`, or it surfaces desired-outcome rows on one side and hides the actual bad end on the other. To drill mixed polarities in one query, use the `QUALIFY` pattern below, which carries a per-evaluator comparison and ranking.

### Query patterns

All over `FROM "logs.default"`, filtering `attributes['gen_ai.evaluation.name'] IS NOT NULL` and a bounded `` `@timestamp` `` window (relative form `NOW() - INTERVAL 'N HOUR'` — never a bare integer; see [`query/sql-logs-traces.md`](query/sql-logs-traces.md)). Score queries also add `AND attributes['error.type'] IS NULL`.

**Recent scores for an agent:**

```sql
SELECT `@timestamp`,
       attributes['gen_ai.evaluation.name']        AS evaluator,
       attributes['gen_ai.evaluation.score.value'] AS score,
       attributes['gen_ai.evaluation.score.label'] AS label,
       attributes['session.id']                    AS session_id
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
ORDER BY `@timestamp` DESC
LIMIT 100
```

**Q1 — per-evaluator rollup: avg + spread + errored SIDECAR in ONE query.** Do NOT filter `error.type` in `WHERE`; split it INSIDE the aggregates and always `GROUP BY` the evaluator name. The `CAST` sits INSIDE the scored `CASE`, so it never runs on an errored row (no cast failure); `AVG` skips a categorical evaluator's NULL value → `avg_score = NULL` for it (read those by label with Q2) instead of dropping the evaluator. `MIN`/`MAX` give the spread without a dialect-specific `STDDEV`:

```sql
SELECT attributes['gen_ai.evaluation.name'] AS evaluator,
       AVG(CASE WHEN attributes['error.type'] IS NULL
                THEN CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) END) AS avg_score,
       MIN(CASE WHEN attributes['error.type'] IS NULL
                THEN CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) END) AS min_score,
       MAX(CASE WHEN attributes['error.type'] IS NULL
                THEN CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) END) AS max_score,
       SUM(CASE WHEN attributes['error.type'] IS NULL     THEN 1 ELSE 0 END) AS scored,
       SUM(CASE WHEN attributes['error.type'] IS NOT NULL THEN 1 ELSE 0 END) AS failed_to_run
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
GROUP BY evaluator
```

`failed_to_run` is the per-evaluator sidecar (it covers categorical evaluators too, since their errored rows have no label). For a strictly scored-only view with no sidecar, add `AND attributes['error.type'] IS NULL` to the `WHERE` and drop the `CASE` wrappers.

**Average score per session (or any break-down dimension) AND evaluator.** `GROUP BY` the dimension **AND** the evaluator name, and SELECT the evaluator name so the breakdown is legible. **Never `GROUP BY session_id` alone** — that silently averages a session's Helpfulness, Correctness, Toxicity, … into one meaningless number. Swap `session.id` for any other dimension the same way:

```sql
SELECT attributes['session.id']                 AS session_id,
       attributes['gen_ai.evaluation.name']     AS evaluator,
       AVG(CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE)) AS avg_score,
       COUNT(*)                                 AS n
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
GROUP BY session_id, evaluator
ORDER BY session_id, evaluator
```

Categorical evaluators come back with `avg_score = NULL` here — roll those up with Q2, adding `session_id` to its `GROUP BY` the same way. **For a NUMERICAL evaluator never add `label` to the `GROUP BY`** — that's the categorical shape only, and it multiplies rows past the display cap.

**Q2 — categorical label distribution per evaluator** (for the evaluators Q1 returned with `avg_score = NULL`). One query returns every categorical evaluator's label breakdown:

```sql
SELECT attributes['gen_ai.evaluation.name']        AS evaluator,
       attributes['gen_ai.evaluation.score.label'] AS label,
       COUNT(*)                                    AS n
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND attributes['gen_ai.evaluation.score.value'] IS NULL   -- categorical = label-only, no numeric value
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
GROUP BY evaluator, label
ORDER BY evaluator, n DESC
```

`GROUP BY evaluator, label` keeps each evaluator's own label set separate. **Never `GROUP BY label` alone** — that mixes distinct evaluators' categories. **And never run this pattern for an evaluator already known to be NUMERICAL:** if a previous query returned a real `avg_score` for it, it has scores, so this query is the wrong shape for it (its `label` is a gloss on the number). The `score.value IS NULL` predicate would return zero rows for it anyway — don't spend a query round proving that.

**Q3 — results at the bad end of the scale + why** (pull `explanation` for the bad results). The comparison is **per-evaluator polarity**: the example assumes higher-is-better (`< 0.5`, `ASC`); for an inverted evaluator flip **both** the comparison to `> 0.5` **and** the `ORDER BY` to `DESC` so `LIMIT` returns the actual worst, not the least-bad breachers near the threshold; for a categorical one filter `score.label` instead. Scope with `IN (...)` to evaluators of **one** polarity:

```sql
SELECT attributes['session.id']                    AS session_id,
       attributes['gen_ai.evaluation.name']        AS evaluator,
       attributes['gen_ai.evaluation.score.value'] AS score,
       attributes['gen_ai.evaluation.explanation'] AS why,
       traceId                                     AS trace_id
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND attributes['gen_ai.evaluation.name'] IN ('<eval1>', '<eval2>', '<eval3>')   -- same-polarity evaluators only
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
  AND CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) < 0.5   -- higher-is-better; flip to > 0.5 for inverted, or filter score.label for categorical
ORDER BY CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) ASC
LIMIT 50
```

**Multi-evaluator drill — top-N PER evaluator.** The default drill is **one Q3 per drilled evaluator, issued together as a batch** (Retrieval plan, second pass): each query filters to a single evaluator and ranks by its own polarity, so nothing starves. When several evaluators must share ONE query anyway, a single flat `LIMIT`/`ORDER BY` STARVES later-sorted ones — all rows land on the first evaluator, and "no bad results for evaluator X" becomes indistinguishable from "truncated by the LIMIT" — so cap PER evaluator with `QUALIFY ROW_NUMBER() OVER (PARTITION BY evaluator …)`, and remember a fused result is still read from the top, so later partitions can be cut by the row cap. Two rules: (1) inside `QUALIFY` reference the SELECT **aliases** (`evaluator`, `score`), NOT the raw `attributes['…']` — post-projection the raw expression is out of scope and errors `No field named attributes`. (2) size N so `N × (num evaluators) ≤ ~50` so the default row cap never truncates the union (e.g. ~15 each for 3 evaluators).

Numerical evaluators — rank "worst" polarity-aware (a plain `ORDER BY score` ranks one polarity backwards):

```sql
SELECT attributes['session.id']                    AS session_id,
       attributes['gen_ai.evaluation.name']        AS evaluator,
       attributes['gen_ai.evaluation.score.value'] AS score,
       attributes['gen_ai.evaluation.explanation'] AS why,
       traceId                                     AS trace_id
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND ( (attributes['gen_ai.evaluation.name'] IN ('<inverted-eval>')
           AND CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) > 0.5)
     OR (attributes['gen_ai.evaluation.name'] IN ('<higher-is-better-eval>')
           AND CAST(attributes['gen_ai.evaluation.score.value'] AS DOUBLE) < 0.5) )
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY evaluator
  ORDER BY CASE WHEN evaluator IN ('<inverted-eval>')
                THEN  CAST(score AS DOUBLE)          -- inverted: higher = worse
                ELSE -CAST(score AS DOUBLE) END DESC -- higher-is-better: lower = worse
) <= 15
```

Categorical evaluators — no numeric value, so filter/rank by LABEL, never a threshold:

```sql
SELECT attributes['session.id']                    AS session_id,
       attributes['gen_ai.evaluation.name']        AS evaluator,
       attributes['gen_ai.evaluation.score.label'] AS label,
       attributes['gen_ai.evaluation.explanation'] AS why,
       `@timestamp`                                AS ts
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NULL
  AND attributes['gen_ai.evaluation.score.value'] IS NULL      -- categorical = label-only
  AND attributes['gen_ai.evaluation.score.label'] IS NOT NULL
  -- optional, when a bad label is known: AND attributes['gen_ai.evaluation.score.label'] IN ('<bad-label>', …)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY evaluator
  ORDER BY ts DESC          -- no numeric severity to rank on; sample by recency (or per chosen label)
) <= 15
```

**Do NOT combine numeric and categorical bad-ends in ONE query** — a numeric `score > 0.5` predicate silently drops every categorical row (its value is NULL). Run them as separate queries.

**Evaluations that failed to run** (run this ONLY when the request is about evals that errored / did not run — `error.type IS NOT NULL`, the inverse of the score gate):

```sql
SELECT attributes['gen_ai.evaluation.name']  AS evaluator,
       attributes['error.type']              AS error_type,
       attributes['error.message']           AS error_message,
       COUNT(*)                              AS n
FROM "logs.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND attributes['gen_ai.evaluation.name'] IS NOT NULL
  AND attributes['error.type'] IS NOT NULL
  AND resource['attributes']['service.name'] IN ('<service>', '<service>.DEFAULT')
GROUP BY evaluator, error_type, error_message
ORDER BY n DESC
```

**Traces behind low-scoring evals** (two steps). Each bad-end eval record already carries the scored trace's id as top-level `traceId` — the bad-end queries above already select it, so the `traceId`s ARE the trace list; a next step that only needs the ids (add to a dataset, re-evaluate) needs **no** further query. To show the actual traces (prompt / response / spans), take those `traceId`s and query **`traces.default`**:

```sql
SELECT traceId, name, `@timestamp`
FROM "traces.default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAY' AND NOW()
  AND traceId IN ('<traceId1>', '<traceId2>', …)   -- the ids from the bad-end query
ORDER BY `@timestamp` DESC
```

**Other filters:** **one session** → `AND attributes['session.id'] = '<sid>'`. **One trace** → `AND traceId = '<traceId>'` (the eval-result record references the scored trace by `traceId`; the score is a separate record, not an attribute on the trace's own spans). **Online only** → `attributes['aws.bedrock_agentcore.online_evaluation_config.name'] IS NOT NULL` (or `= '<config_name>'` for one config); **on-demand only** → the same field `IS NULL`.

**From a trace (trace-first).** A trace's eval scores are **not** attributes on the trace's own spans — they are **separate `logs.default` eval-result records** that reference the scored trace by top-level `traceId`. So "the eval result of this trace" is a `logs.default` query filtered by that id (add `AND attributes['session.id'] = '<sid>'` for the session variant). To show a trace's spans **and** its eval score together, JOIN `"logs.default"` ⋈ `"traces.default"` on `traceId` — JOIN mechanics are in [`query/sql-logs-traces.md`](query/sql-logs-traces.md).

### Notes

- Results are Region-scoped and appear after the normal ingestion lag (a score shows up a couple of minutes after the evaluation runs). If a just-run evaluation is not visible, widen the window or wait for ingestion.
- On-demand scores are written back best-effort (Section 4) — a score that failed to write (e.g. missing `logs:PutLogEvents` on the caller) will not appear; online evaluation is the source with guaranteed persistence.

---

## After analysis — offer follow-up actions

```markdown
**What would you like to do next?**
1. **Score these traces now** — run an on-demand evaluation with a chosen evaluator
2. **Monitor continuously** — set up an online evaluation on live traffic
3. **Save as a dataset** — capture these traces as a regression / golden set for reuse
4. **Read back stored scores** — roll up what online / on-demand evaluation has already found
```

Wait for the user to pick an action before proceeding.
