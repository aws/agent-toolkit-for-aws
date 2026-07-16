# Component mapping

Map each source component to its harness target. **Mirror** behavior, not Bedrock structure. Adapt the `.tmpl` templates in the skill's `assets/` directory: substitute every `{{TOKEN}}`, and delete every marker block — `# <<< RENDER … # <<< /RENDER` (token docs) and `# <<< OPTIONAL: … # <<< /OPTIONAL` (features that don't apply). After rendering, no `{{`, `}}`, or `<<<` may remain — that grep is the verification gate, and it must come back clean.

The `.tmpl` files are not for any template engine; they are guidance for you (the LLM) on how to fill them in.

## Mapping action groups to Gateway targets

A Bedrock action-group Lambda speaks the Bedrock event envelope; AgentCore Gateway invokes Lambda targets with a different shape, so the original won't work behind Gateway unchanged.

**Default: proxy-by-ARN.** Create a *new* shim Lambda ([lambda_shim.py.tmpl](assets/lambda_shim.py.tmpl) — its docstring documents both envelopes) that translates the Gateway event into the Bedrock event, invokes the original by ARN, and unwraps the response. This leaves the original **untouched** — editing it in place can change its response shape and break the source agent. The original's ARN is rendered into the shim source as a literal (no env vars — see [deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md)).

**OpenAPI action groups: pass the route TEMPLATE verbatim.** The original Lambda dispatches by matching `apiPath` against the literal route template (`/customer/{customer_id}`), with path-param values delivered separately in `parameters`. Substituting a value into the path (`/customer/tkashina`) matches no template, so the original falls through to its unhandled-op branch. Render the shim's `_OP_ROUTES` table (mapping each operationId to its `{method, apiPath-template}`) from the source OpenAPI schema with placeholders intact, and keep values in `parameters`.

Each action group becomes one Gateway **`targetType: "lambda"` code target**, hand-added to `agentcore.json` (the CLI can't create it non-interactively), with `toolDefinitions` holding **one entry per function/operation**. `agentcore deploy` then builds the shim Lambda. Exact block + gotchas in [deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md); follow it.

### Tool schemas — mirror exactly
Reproduce the source action group's schema faithfully into the tool-schema file ([tool_schema.json.tmpl](assets/tool_schema.json.tmpl)): same tool names, parameter names, types, and descriptions. Do **not** rewrite or "improve" them — fidelity to the source agent's behavior is the goal, and a renamed tool or tightened type changes how the model selects it.

## Mapping the knowledge base (connector or KB shim, by type)

**Decide by `knowledgeBaseConfiguration.type` FIRST — the native Gateway connector accepts ONLY a `MANAGED` Bedrock KB.**

- **Any non-`MANAGED` type (`VECTOR`, `KENDRA`, `SQL`)** → **always the KB shim.** The connector cannot accept these at all, so type alone decides and retrieval config is irrelevant. Use the **KB shim** ([kb_shim.py.tmpl](assets/kb_shim.py.tmpl)): a hand-added **`targetType: "lambda"` code target** (see [deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md)) that calls `bedrock-agent-runtime:Retrieve` and returns MCP-shaped passages.
- **`MANAGED`** → then (and only then) check the **retrieval config on the KB association** (`knowledgeBaseConfigurations[].retrievalConfiguration`: reranker, metadata filter, hybrid/search-type override, top-k):
  - **default** retrieval config → native Gateway connector: `add gateway-target --type connector --connector bedrock-knowledge-bases --knowledge-base-id <id>`.
  - **non-default** retrieval config → the **KB shim** (the connector uses a fixed retrieval contract and would silently drop the custom config), reproducing that config from the manifest's KB association.

Both paths reproduce the source agent's retrieval — the choice is wiring, not fidelity, so every reachable KB is still **clean**. (An *unreachable* KB is a hard-stop — see [eligibility.md](references/bedrock-agents-to-agentcore-harness/eligibility.md). Type picks the wiring; it is never itself the blocker.)

### Return-of-Control action groups — cannot migrate
A `customControl: RETURN_CONTROL` action group has no Lambda; the original application handled execution outside Bedrock. There is no automatic harness equivalent. **Do not silently drop it.** Classify it **cannot** in the migration assessment and confirm with the user before continuing — the migrated agent will lack that capability unless the user supplies a backend for it.

## Built-in action groups

- **`AMAZON.UserInput`**: no tool. Add a clarification instruction to the system prompt; the harness asks clarifying questions naturally.
- **`AMAZON.CodeInterpreter`**: use the built-in tool, `agentcore add tool --harness <harness-name> --type agentcore_code_interpreter --name <tool-name>` (`--harness` and `--name` required — see [deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md)).

## Mapping memory to managed memory (default)

Use the harness's **managed memory**, which is on by default — the harness auto-provisions an AgentCore Memory instance (semantic + summarization strategies, with the service's default expiry) and loads/saves session history automatically. Check the [harness memory devguide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html) or `DescribeHarness` for the current defaults rather than assuming a fixed retention. Do not pass `--no-harness-memory`. This covers the common source case (`SESSION_SUMMARY`) via the built-in `SUMMARIZATION` strategy; customize strategies via `UpdateHarness` only if the source clearly needs more.

**Leave truncation at its default (`sliding_window`).** Do not set truncation to `summarization` — it runs mid-conversation and errors on short sessions (`Cannot summarize: insufficient messages`). The default is already safe.

Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html

## Mapping model parameters to the harness model config
Set model params via `agentcore add harness` flags: `--model-id`, `--model-max-tokens`, `--temperature`, `--top-p`, `--api-format`. Some models reject setting temperature and top-p together — check the target model's inference-parameter constraints (e.g. `aws bedrock get-foundation-model`, or a probe call) and set **only one** if so.

## Mapping idle session TTL (preserve the source's session-lifetime bound)
The source's `idleSessionTTLInSeconds` bounds how long an idle session is retained — a security control (it caps the credential/context leakage and replay window). Read its actual value from the discovery manifest (the source agent's own setting, whatever it is) and preserve it: if `agentcore add harness` exposes an equivalent session-TTL flag, set it to the source value. If the CLI has no equivalent, **classify it degraded in Phase 4** with the concrete delta (e.g. "source set 300s; migrated defaults to Ns") so the builder decides — never silently extend the window.

## Guardrail — cannot migrate; surface to the user
Check whether the installed CLI can attach a guardrail to a **bedrock** harness before classifying: look in `agentcore add harness --help` for a guardrail field, and note that `--additional-params` (the pass-through) is `lite_llm`-provider only, so a bedrock harness rejects it. If no guardrail path exists in the CLI surface you're running, classify the guardrail **cannot** in the assessment and tell the user the migrated harness will **not** enforce it, recording the source `guardrailIdentifier` + version. Do **not** fake it with a system-prompt mention (that enforces nothing). Enforcing it means applying `ApplyGuardrail` outside the harness — out of scope. If the CLI surface you're running exposes a guardrail field, use it and reclassify as clean.

## Mapping the prompt to the system prompt
Fold the agent instruction into the harness `--system-prompt`. If `AMAZON.UserInput` was present, include the clarification instruction.

Prompt overrides in **DEFAULT** mode carry nothing custom — skip them. But a **non-DEFAULT override** (especially `ORCHESTRATION` or `PRE_PROCESSING`) may hold real business logic — routing rules like "use tool X for billing questions, tool Y for refunds," or input-classification the app relied on. Don't discard that as boilerplate. Read each non-DEFAULT override, separate the Bedrock-Agents scaffolding (the orchestration loop mechanics the harness now owns) from the business intent, and fold the intent into the system prompt — a modern model handles tool-routing guidance cleanly in the prompt. When unsure whether an override is boilerplate or load-bearing, surface it to the user rather than dropping it.

## Mapping the model (mirror the source)
Default `--model-id` to the source agent's `foundationModel`. If the CLI's harness default differs, set it explicitly to match the source (parity).
