# ADOT Domain Knowledge & Decision Heuristics

## Contents

- [AgentCore Client Architecture](#agentcore-client-architecture)
- [ADOT Document Requirements](#adot-document-requirements)
- [Context Handling for Faithfulness Evaluators](#context-handling-for-faithfulness-evaluators)
- [Evaluator ID Formats](#evaluator-id-formats)
- [evaluationReferenceInputs Schema](#evaluationreferenceinputs-schema)
- [ADOT Validation Error Catalog](#adot-validation-error-catalog)
- [Decision Heuristics](#decision-heuristics)
- [ToolResponseHandling Structural Challenges](#toolresponsehandling-structural-challenges)
- [Gotchas](#gotchas)
- ["No Spans to Evaluate" Recovery](#no-spans-to-evaluate-recovery)
- [ADOT Generation for Live Agents (Topology B)](#adot-generation-for-live-agents-topology-b)

## AgentCore Client Architecture

```
EvaluationClient(region_name="us-east-1")
├── client._cp_client  — CONTROL PLANE: list_evaluators(), create_evaluator(), delete_evaluator()
├── client._dp_client  — DATA PLANE: evaluate(evaluatorId=..., evaluationInput=...)
├── client.create_evaluator_and_wait()  — convenience (creates + polls until ACTIVE)
└── client.run()  — HIGH-LEVEL (requires CloudWatch spans; NOT for in-memory migration)
```

## ADOT Document Requirements

All handled automatically by `convert_strands_to_adot()` from `bedrock_agentcore.evaluation`:

- **Scope** must be one of: `strands.telemetry.tracer`, `opentelemetry.instrumentation.langchain`, `openinference.instrumentation.langchain`
- **Span fields:** `flags: 3`, `status.code: "OK"` (not `"STATUS_CODE_OK"`), `kind: "INTERNAL"` (not `"SPAN_KIND_INTERNAL"`)
- **Root span attribute:** `gen_ai.operation.name: "invoke_agent"`
- **Log record fields:** `flags: 1`
- **Log record body structure:**

  ```json
  {
    "input": {
      "messages": [{"content": {"content": "[{\"text\": \"user query + context\"}]"}, "role": "user"}]
    },
    "output": {
      "messages": [{"content": {"message": "[{\"text\": \"agent response\"}]", "finish_reason": "end_turn"}, "role": "assistant"}]
    }
  }
  ```

- Flat text body fields are **silently ignored** → causes "no spans to evaluate"

## Context Handling for Faithfulness Evaluators

The `{context}` placeholder reads from the FIRST user message's `content.content` field.

```python
# CORRECT: Context visible to AgentCore judge
user_content = f"{query}\n\nContext:\n{search_results}"
# → json.dumps([{"text": user_content}]) in content.content

# WRONG: Context in separate message (judge won't see it)
messages = [
    {"role": "user", "content": {"content": json.dumps([{"text": query}])}},
    {"role": "user", "content": {"content": json.dumps([{"text": context}])}},  # IGNORED
]
```

## Evaluator ID Formats

The service appends `-{10charSuffix}` to the creating name, so resolution depends on the path.

| Type | Format | Example | How to resolve |
|---|---|---|---|
| Builtin | `Builtin.{Name}` | `Builtin.Conciseness` | Fixed ID, no lookup |
| Custom CLI | `{PascalTask}{UUID4}_{framework}_{metric}-{suffix}` | `RagPipelineA1B2_deepeval_faithfulness-N0HvYz28d3` | `resolve_evaluator_id()` on the project-scoped fragment |
| Custom SDK | `{evaluator_name}-{suffix}` — **no project prefix** | `phoenix_faithfulness-XMx1RnGK3F` | Paste the ID returned by `create_evaluator_and_wait()`; a fragment lookup cannot find it |

## evaluationReferenceInputs Schema

When calling `_dp_client.evaluate()` with ground-truth data (expected_output, expected_tools):

```python
response = client._dp_client.evaluate(
    evaluatorId="...",
    evaluationInput={"sessionSpans": adot_docs},
    evaluationReferenceInputs=[{
        "context": {                                    # REQUIRED — even if minimal
            "spanContext": {"sessionId": "eval-123"},
        },
        "expectedResponse": {"text": "expected output"},  # optional
        "expectedTrajectory": {                           # optional — for tool metrics
            "toolNames": ["tool_a", "tool_b"],
        },
        "assertions": [{"text": "claim 1"}, {"text": "claim 2"}],  # optional
    }],
)
```

**Common error:** `ParamValidationError: Missing required parameter in
evaluationReferenceInputs[0]: "context"` — the `context` field is MANDATORY even
when you only need `expectedResponse`. Always include at minimum:
`{"context": {"spanContext": {"sessionId": "default"}}}`.

The DeepEvalAdapter reads these fields via `evaluator_input.reference_inputs[0]`:

- `expectedResponse.text` → `LLMTestCase.expected_output`
- `expectedTrajectory.toolNames` → `LLMTestCase.expected_tools`
- `assertions[].text` → `LLMTestCase.context`

The generated `_agentcore.py` does not send these. It embeds each case's context and
reference in the first user message, and per-sample fields in a `Metric Inputs` JSON
section, and the generated DeepEval and RAGAS handlers read all three from there,
including the retrieved context chunks, which no reference input carries. Hand-add
`evaluationReferenceInputs` only when calling `evaluate()` yourself; a value passed
there takes precedence over the embedded one.

Naming convention:

- Evaluator names: `{PascalTask}{UUID4}_{framework}_{metric}`
- CF stack project: `{PascalTask}{UUID4}` (PascalCase + 4 uppercase hex, pattern `^[A-Za-z][A-Za-z0-9]{0,35}$`)

Auto-discover CLI-deployed evaluators with `resolve_evaluator_id()`. SDK-created
LLM-as-a-Judge IDs are not project-prefixed, so paste them into `EVALUATORS` instead.

## ADOT Validation Error Catalog

ADOT-related errors the `evaluate()` API returns.
`convert_strands_to_adot()` handles all of these correctly. These errors ONLY occur
when manually constructing ADOT. **If you see any of these, you are doing it wrong —
switch to `convert_strands_to_adot()` immediately.**

| Error Message | Root Cause | Fix |
|---|---|---|
| `Failed to parse span data ... Field 'trace_id': Input should be a valid string` | `trace_id` passed as integer or missing | Must be 32-char lowercase hex string: `uuid.uuid4().hex` |
| `Failed to parse span data ... Field 'span_id': Input should be a valid string` | `span_id` passed as integer or missing | Must be 16-char lowercase hex string: `uuid.uuid4().hex[:16]` |
| `Failed to parse span data ... Field 'start_time': Value error, month must be in 1..12` | Nanosecond integer being parsed as date components | Use field name `startTimeUnixNano` (camelCase) with nanosecond integer: `int(time.time() * 1e9)` |
| `Failed to parse span data ... Field 'start_time': Invalid isoformat string: '1784588875'` | Unix seconds in `start_time` field | Either use `startTimeUnixNano` (nanoseconds) OR `start_time` (ISO format string). Never raw seconds. |
| `Failed to parse span data ... Field 'end_time' is required but got None` | Missing `endTimeUnixNano` | Add `endTimeUnixNano: int(time.time() * 1e9) + 1000000` |
| `Provided input has no spans to evaluate. Please ensure that spans ... have model/tool/agent invocation details for the provided scope` | Span exists but has no semantic content | Spans need: (1) proper scope name, (2) `gen_ai.user.message` + `gen_ai.choice` span events, (3) linked log records with body content |
| `span with ID ... is missing a corresponding log event` | Span exists without paired log record | Every span needs a corresponding log record with `body.input.messages` and `body.output.messages` |
| `Parameter validation failed: Invalid type for parameter evaluationInput.sessionSpans` | Passed nested OTLP format `{"resourceSpans": [...]}` | `sessionSpans` expects a **flat list** of span/log dicts from `convert_strands_to_adot()`, NOT nested OTLP protobuf format |
| `Failed to parse span data: 'list' object has no attribute 'get'` | Wrapped flat list in another list | Pass the flat list directly, don't nest it |
| `1 validation error ... Value at 'evaluatorId' failed to satisfy constraint` | Evaluator name starts with digit or contains invalid chars | Use `scripts/names.py` — must match `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` |

## Decision Heuristics

### "No spans to evaluate" ValidationException

1. Verify agent is instrumented with OTel and producing spans
2. Verify using `convert_strands_to_adot()` or proven ADOT fallback pattern
3. Verify session has non-empty user prompt and agent response
4. Check log record body matches nested format (not flat text)
5. Check scope is one of: `strands.telemetry.tracer`, `opentelemetry.instrumentation.langchain`, `openinference.instrumentation.langchain`
6. Check spans have `gen_ai.user.message` and `gen_ai.choice` events

### Choosing ADOT Generation Approach

1. **Strands agent:** `convert_strands_to_adot(raw_spans)` — handles all format details.
2. **Non-Strands agent (any framework):** Use `detect_otel_mapper()` pipeline:

   ```python
   from strands_evals.mappers import detect_otel_mapper, readable_spans_to_dicts
   span_dicts = readable_spans_to_dicts(raw_otel_spans)
   mapper = detect_otel_mapper(span_dicts)
   session = mapper.map_to_session(span_dicts, session_id="eval-session")
   ```

   `detect_otel_mapper()` auto-routes to the correct mapper for any framework
   (PydanticAI, AutoGen, Google ADK, smolagents, LangChain/LangGraph, or custom).

**Available mappers (from `strands_evals.mappers`):**

- `OpenInferenceSessionMapper` — smolagents/Phoenix spans. Accepts both
  `openinference.instrumentation.langchain` and `openinference.instrumentation.smolagents`
  scopes. Handles bare-string `output.value` (numbers, lists) without dropping spans.
- `LangChainOtelSessionMapper` — LangChain/LangGraph OTel spans.
- `StrandsInMemorySessionMapper` — Strands spans (raw `ReadableSpan` objects only,
  NOT dict-format spans).
- `GenericGenAISessionMapper` — dict-format spans with any unrecognized scope.
  Parses `gen_ai.operation.name`, `gen_ai.tool.*`, and span events. Use this as
  fallback for custom instrumented agents.
- `detect_otel_mapper()` — auto-detect from span scope names. Routes smolagents
  to `OpenInferenceSessionMapper`, unrecognized dict spans to `GenericGenAISessionMapper`,
  Strands `ReadableSpan` objects to `StrandsInMemorySessionMapper`.

### Choosing Evaluator Level for Phoenix

- Judges overall response quality → `TRACE`
- Judges tool selection/invocation → `TOOL_CALL`
- `ToolResponseHandlingEvaluator` → `TRACE` (judges response quality given tool results)

### Score Divergence > 0.1

1. Check context handling (retrieval context in first user message?)
2. Check for ambiguous test inputs → report them with their per-case scores. Never replace or
   reword a customer test case (SKILL.md, Core Invariants)
3. Check if Phoenix evaluates different scope than AgentCore → single-tool-call inputs
4. Check judge model matches between evaluators
5. If inherent methodology difference, note in summary as expected

### AgentCore Returns All 0.0 Scores

1. **Most common:** Context/retrieval data not embedded in first user message
2. For tool evaluators: tool interaction data not in ADOT `{context}`
3. Check `body.input.messages[].content.content` is JSON string `'[{"text": "..."}]'` (not plain text)
4. Known converter gap: tool data from span events (smolagents) not yet in output log records

## ToolResponseHandling Structural Challenges

1. **No unified OTel field for tool data** — smolagents uses span events, OpenInference uses attributes, standard GenAI uses child spans
2. **AgentCore needs full tool interaction in ADOT** — without it, scores are 0.0
3. **`convert_strands_to_adot()` gap** — does not extract from span events for non-Strands agents
4. **Multi-tool queries cause mismatch** — Phoenix evaluates ONE response; AgentCore sees all

**Mitigation for single-tool-call inputs:** Use test inputs that trigger exactly one tool call.

**Mitigation for smolagents multi-step agents (CodeAgent):**

smolagents CodeAgent runs multiple internal steps (code generation → execution → iteration)
before calling `final_answer()`. Phoenix only evaluates the LAST tool_call/tool_result pair.
When building ADOT, embed only the final step's data:

```python
# Extract LAST tool interaction from smolagents memory
last_step = agent.memory.steps[-1]  # or equivalent
tool_call = last_step.tool_calls[-1] if last_step.tool_calls else None
tool_result = last_step.observations[-1] if last_step.observations else None

# Embed in first user message (matching Phoenix's simplified view)
user_content = f"{query}\n\nTool Call: {tool_call}\n\nTool Result: {tool_result}"
```

Do NOT include all intermediate CodeAgent steps. This causes AgentCore's judge to
evaluate against a much more complex interaction than Phoenix ever saw, producing
systematic divergence.

**Document as known limitation if all-0.0 persists** after applying this pattern.
## Gotchas

| Agent might think... | But actually... | Instead... |
|---|---|---|
| "I'll manually construct ADOT JSON from scratch" | Dozens of validated fields will fail | Use `convert_strands_to_adot()` for Strands agents, or Strands Evals mappers + `build_adot_docs()` for non-Strands |
| "I'll re-run through a Strands agent for ADOT" | Evaluates DIFFERENT execution; original reasoning lost | Use Strands Evals mappers (`detect_otel_mapper()`) on original spans → extract data → `build_adot_docs()` |
| "I need to explore SDK source for ADOT format" | Wastes many steps | Everything the SDK exposes is catalogued in [ADOT Document Requirements](#adot-document-requirements) above |
| "I'll put retrieval context in a separate message" | AgentCore's `{context}` reads only FIRST user message | Embed context INTO first message: `f"{query}\n\nContext:\n{ctx}"` |
| "I need to explore site-packages to understand the SDK" | ALL SDK knowledge is in `references/`. Reading site-packages wastes steps and provides nothing beyond what references contain | This document plus `references/deployment-*.md` already carry it |
| "I'll build ADOT from memory — I know the format" | ADOT has dozens of validated fields. Manual construction causes `Failed to parse span data` errors | ALWAYS use `convert_strands_to_adot()`. The validated field list is in [ADOT Document Requirements](#adot-document-requirements) above |
| "I'll pass nested OTLP format to sessionSpans" | `_dp_client.evaluate(sessionSpans=...)` expects a flat list, NOT `{"resourceSpans": [...]}` | Pass the flat list from `convert_strands_to_adot()` directly |
| "Lambda body field has the conversation data" | Service transforms spans: body is in `span_events[0].body` | Always read from `span_events[0].body` in Lambda handlers |
| "Each ADOT span can have its own trace_id" | AgentCore API groups spans by session.id and rejects "spans from more than one session" | ALL spans + log records in one evaluate() call MUST share ONE trace_id AND ONE session.id resource attribute |

## "No Spans to Evaluate" Recovery

The error `Provided input has no spans to evaluate` means the ADOT document format
is wrong for the evaluator's `level` (SESSION vs TRACE). Maximum 2 attempts to fix.

```
Got "no spans to evaluate"?
├── Is it a multi-turn metric?
│   ├── Verify level=SESSION in mapping.json (classify.py sets this automatically)
│   ├── All turns as span_events in ONE span document
│   └── Verify all span_events have body.input.messages AND body.output.messages
├── Is it a Lambda evaluator (single-turn)?
│   ├── Check scope_name: use framework-specific (e.g. "opentelemetry.instrumentation.langchain")
│   ├── Fallback: try "strands.telemetry.tracer" (works universally)
│   └── Verify ADOT doc has body.output.messages AND body.input.messages
├── Is it LLM-as-a-Judge (TRACE level)?
│   ├── scope_name MUST be "strands.telemetry.tracer"
│   └── Verify span has gen_ai.operation.name attribute
└── Is it LLM-as-a-Judge (SESSION level)?
    └── SWITCH to TRACE level. SESSION is fragile for LLM-as-a-Judge.
```

## ADOT Generation for Live Agents (Topology B)

**⚠️ BEFORE writing any ADOT code, read [ADOT Document Requirements](#adot-document-requirements)
and the [ADOT Validation Error Catalog](#adot-validation-error-catalog) above.**

For Topology B tasks (live agent without OTel), do NOT manually construct ADOT JSON.
Instead: instrument the agent with OTel → map spans to ADOT via the mapper pipeline.

**Phase 1: Instrument the agent to produce OTel spans.**

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
```

**Phase 2: Map spans to ADOT using `detect_otel_mapper()`.**

```python
from strands_evals.mappers import detect_otel_mapper, readable_spans_to_dicts
span_dicts = readable_spans_to_dicts(exporter.get_finished_spans())
mapper = detect_otel_mapper(span_dicts)
adot_docs = mapper.map_to_session(span_dicts, session_id="eval-session").to_adot_docs()
```

**For Strands agents:** Use `convert_strands_to_adot(raw_spans)` directly — skip above.

**If the mapper doesn't support the framework**, use `ADOTDocumentBuilder` from the SDK:

```python
from bedrock_agentcore.evaluation.span_to_adot_serializer.adot_models import (
    ADOTDocumentBuilder, ConversationTurn, ResourceInfo, SpanMetadata
)
```

See [ADOT Document Requirements](#adot-document-requirements) above for the field-by-field format.

**Do NOT hand-build raw ADOT JSON dicts**; every error in the validation catalog above
comes from hand-built documents.
