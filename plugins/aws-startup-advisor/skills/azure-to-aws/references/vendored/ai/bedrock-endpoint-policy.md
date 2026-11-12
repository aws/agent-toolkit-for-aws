# Bedrock Endpoint Policy — `bedrock-runtime` by default, `bedrock-mantle` by selector

> Canonical endpoint-selection policy for every Bedrock migration path in this plugin.
> Vendored into each consuming skill as `references/vendored/ai/bedrock-endpoint-policy.md`
> and kept byte-identical by `tools/sync-vendored.py`; edit HERE, then run the sync.
> Every statement below comes from the public Amazon Bedrock User Guide pages listed in
> § Sources (read 2026-11-07; the GPT-5.4 and GPT-5.5 model cards read 2026-11-08).
> Re-read those pages before changing a row.

## The rule

**Use `bedrock-runtime` for new applications.** Amazon Bedrock documents `bedrock-runtime` as the
recommended endpoint for most new applications; it serves InvokeModel, Converse, the
OpenAI-compatible Responses and Chat Completions APIs, and the Anthropic Messages API.

**Use `bedrock-mantle` only for a verified Mantle-only need.** The documented reasons are:

- background (asynchronous, long-running) inference — Responses `background=true` is rejected
  with a 400 on `bedrock-runtime`;
- server-side tool use and pre-configured tools, including Web Search;
- customer-created Projects (OpenAI-compatible) or Workspaces (Anthropic-compatible) —
  `bedrock-runtime` exposes only the account's default project;
- a model or API that the Endpoint availability page lists on `bedrock-mantle` only;
- strict in-Region processing for a model that `bedrock-runtime` serves only through a
  cross-Region inference (CRIS) profile while `bedrock-mantle` serves it in the required Region.

**API continuity alone never selects Mantle.** An OpenAI Responses, OpenAI Chat Completions or
Anthropic Messages source keeps its SDK on `bedrock-runtime` by changing the base URL, the
credential and the model ID. Choosing Mantle because "the app already speaks Responses" is not a
selector.

**Pricing never selects an endpoint.** Choose by API and capability need. Read the per-token
rate from that model's card for the inference option the endpoint serves. A card with no Geo or
Global row has not published that price; do not use the In-Region rate in its place.

## `mantle_selector` — the recorded reason

Every `bedrock_models[]` row whose `migration_path` starts with `mantle_` (`mantle_openai_responses`,
`mantle_openai_chat`, `mantle_messages`) MUST record `mantle_selector` with exactly one value:

| `mantle_selector`           | Verified need                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------------- |
| `background_inference`      | Responses requests with `background=true` / long-running asynchronous inference                 |
| `server_side_tools`         | Server-side tool use (Lambda-backed MCP tools) or pre-configured tools other than Web Search    |
| `web_search`                | The built-in Web Search tool                                                                    |
| `projects`                  | Customer-created Projects (OpenAI-compatible) for isolation and cost tracking                   |
| `workspaces`                | Workspaces (Anthropic-compatible) referenced by `anthropic-workspace-id`                        |
| `mantle_only_model_or_api`  | The model, or the API for that model, is listed on `bedrock-mantle` only                        |
| `in_region_processing`      | Strict in-Region processing where `bedrock-runtime` offers only a CRIS profile for that model   |

A `mantle_*` row without a `mantle_selector`, or with a reason outside this table, is a design
defect: rewrite the row as the `bedrock-runtime` path (`runtime_openai_cris` with the source
app's `required_client_api`, or `runtime_messages`) or justify it with one of the values above.
A `runtime_*` or `converse` row never carries `mantle_selector`.

## How a selector is learned

The seven values are learned in three different ways; no phase may guess one it cannot learn.

- **Detected in code, confirmed by the user.** `background_inference`, `web_search`,
  `server_side_tools`, `projects` and `workspaces` are the only code-detectable selectors.
  Discover's app-code scanners record each match with file:line evidence — as
  `workloads[].mantle_signals[]` in the gcp-to-aws / azure-to-aws profile
  (`discover-app-code.md` Step 5C) and as top-level `mantle_signals[]` in the provider-neutral
  profile (bedrock-migration-assessment `discover-app-code.md` Step 4.5); the usage-API discovery
  files add `projects` / `workspaces` / `web_search` signals from the account's own scoping and
  model strings. Clarify shows the detected signals and the user confirms or drops each one into
  `ai_constraints.mantle_requirements` (full flow Q22b, AI-only Q10.5); when no code was
  scanned, Clarify asks the same five outright. A detected signal is a prompt for the question,
  never the answer. Design then derives `bedrock_models[].mantle_selector` from that field alone
  and records `mantle_requirement` on every Mantle row and `endpoint_assumption` on every
  runtime row (`schema-design-aws-ai.md`).
  - `background_inference` — positive: `background=True` / `background: true` on
    `responses.create`, or a raw `"background": true` Responses body. Not a signal: `store=True`,
    `stream=True`, or polling `responses.retrieve` without `background`. `bedrock-runtime`
    rejects `background=true` with a 400
    (https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html, read
    2026-11-07).
  - `web_search` — positive: `tools=[{"type": "web_search"}]`, `"type": "web_search_preview"`
    (any dated `web_search_preview_*` form), Anthropic `"type": "web_search_20250305"`,
    OpenRouter `plugins: [{"id": "web"}]` or a `:online` model suffix. Not a signal: a
    client-side `"type": "function"` tool merely named `web_search`.
  - `server_side_tools` — positive: a tools entry of `"type": "mcp"` (`server_url` /
    `server_label`), `code_interpreter`, `file_search`, `computer_use_preview`,
    `image_generation` used as a tool type, or an Anthropic `code_execution_*` tool type — any
    provider-executed tool other than web search. Not a signal: `"type": "function"` tools,
    Gemini `function_declarations=`, `@tool` decorators, `tool_choice` — client-side function
    tools never count; Anthropic `computer_*` (incl. `computer_toolset_*`), `browser_toolset_*`, `text_editor_*`, `bash_*` and `memory_*` are CLIENT-executed tools listed on both `bedrock-runtime` and `bedrock-mantle` by the Sonnet 5 and Opus 5.5 cards (`model-card-anthropic-claude-sonnet-5.html`, `model-card-anthropic-claude-opus-5-5.html`, read 2026-11-09) — a client-tool-only Anthropic app stays `runtime_messages`.
  - `projects` — positive: an `OpenAI-Project` header
    (`default_headers={"OpenAI-Project": ...}`), a `project=` kwarg on the OpenAI client, or an
    `OPENAI_PROJECT_ID`-style environment name read in code; in usage discovery, a
    `project_filter` naming more than one project or a non-default project. Not a signal:
    `OpenAI-Organization` alone; no header means the default project.
  - `workspaces` — positive: an `anthropic-workspace-id` header or an `ANTHROPIC_WORKSPACE_ID`-style
    environment name; in usage discovery, `workspace_ids` naming more than one workspace or a
    non-default workspace. Not a signal: OpenRouter's own `workspace_id` scoping, which is an
    OpenRouter account concept.
- **Derived by Design, never asked.** `mantle_only_model_or_api` is derived from the model id and
  the required API against the access-path tables in `ai-openai-to-bedrock.md` /
  `openai-on-bedrock.md`; it is not a scanner output and not a Clarify question.
- **Always asked, never detected.** `in_region_processing` is never code-detectable: nothing in a
  call site says whether cross-Region inference is acceptable. Clarify always asks it together
  with the Region.

## Public comparison (read 2026-11-07)

| Item                                           | `bedrock-runtime`                                                                 | `bedrock-mantle`                                                | Source page                                     |
| ---------------------------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------- |
| Recommended default                            | Yes — "for most new applications"                                                 | Only for capabilities available only there                      | `endpoints.html`, `models-endpoint-availability.html` |
| InvokeModel / Converse                         | Supported                                                                         | Not supported                                                   | `endpoints.html`                                |
| OpenAI Responses API                           | Supported at `/openai/v1`; always synchronous; default project only               | Supported at `/v1` (some models `/openai/v1`); background OK    | `inference-responses-api.html`                  |
| OpenAI Chat Completions API                    | Supported at `/openai/v1/chat/completions`                                        | Supported at `/v1/chat/completions` (some models `/openai/v1`)  | `inference-chat-completions.html`               |
| Anthropic Messages API                         | Supported at `/anthropic` (SDK sends `/anthropic/v1/messages`)                    | Supported at `/anthropic/v1/messages`                           | `inference-messages-api.html`                   |
| Background Responses (`background=true`)       | Rejected (400)                                                                    | Supported                                                       | `endpoints.html`, `inference-responses-api.html` |
| Server-side tool use / pre-configured tools    | Not available; client-side tools work                                             | Supported                                                       | `tool-use-server-side.html`, `endpoints.html`   |
| Web Search                                     | Not available                                                                     | Supported                                                       | `web-search.html`, `endpoints.html`             |
| Projects / Workspaces                          | Default project only; use inference profiles for isolation and tagging            | Create and manage your own                                      | `projects.html`, `workspaces.html`              |
| Cross-Region inference (Geo / Global profiles) | Supported                                                                         | Not supported — in-Region only                                  | `endpoints.html`, `monitoring-mantle-metrics.html` |
| In-Region processing                           | Through an on-demand (unprefixed) model ID where the model card lists one; proprietary GPT models list CRIS profiles only | Always in-Region                        | `endpoints.html`, the per-model cards            |
| Guardrails, intelligent prompt routing         | Supported                                                                         | Not supported                                                   | `endpoints.html`                                |
| Application inference profiles / per-request metadata | InvokeModel and Converse only (Responses and Chat Completions reject an AIP target with 400) | Not available — Projects / Workspaces attribute usage | `cost-mgmt-application-inference-profiles.html`, `endpoints.html` |
| Model invocation logging                       | Supported, including the OpenAI-compatible APIs on this endpoint                   | Not currently captured                                          | `model-invocation-logging.html`                 |
| CloudWatch metrics namespace                   | `AWS/Bedrock` (`Invocations`, `InputTokenCount`, …)                                | `AWS/BedrockMantle` (`Inferences`, `TotalInputTokens`, …)       | `monitoring-mantle-metrics.html`                |
| Authentication                                 | SigV4 or Bedrock API key / short-term bearer token; IAM `bedrock:InvokeModel*`     | SigV4 or Bedrock API key; IAM `bedrock-mantle:CreateInference`  | `endpoints.html`                                |

## Lifecycle wording (the only sentence to repeat)

Existing `bedrock-mantle` applications continue to be fully supported and do not need to change.
Do not add claims about permanence, model-quality equivalence between the endpoints,
launch-day parity for new models, or future plans — the public pages make none, and the
guides in this plugin must not either. Both endpoint surfaces use the same underlying inference
engine (`endpoints.html`).

## Quotas (why endpoint choice affects capacity planning)

- **`bedrock-runtime`** — per-model, per-Region token quotas (input and output counted
  together, output weighted by a model-specific burndown rate) shared across every inference
  API on the endpoint; a requests-per-minute quota exists for some models and not others
  (`quotas-runtime.html`, `scaling-throughput-best-practices.html`).
- **`bedrock-mantle`** — no requests-per-minute quota; separate input-tokens-per-minute and
  output-tokens-per-minute quotas per model and Region for models with published quotas. A
  model without a published quota is not unlimited — internal service capacity and transient
  rate limiting still apply (`quotas-mantle.html`, `scaling-throughput-best-practices.html`).
- Traffic on the two endpoints consumes separate quota allocations even for the same model;
  plan capacity per endpoint. Batch inference, Provisioned Throughput and custom inference
  profiles exist only on `bedrock-runtime`.

## Sources

All pages under `https://docs.aws.amazon.com/bedrock/latest/userguide/`, read 2026-11-07:

- `endpoints.html` — https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html
- `model-card-openai-gpt-54.html` and `model-card-openai-gpt-55.html` (read 2026-11-08) —
  commercial In-Region prices only. Runtime lists `us.` and `global.` ids, and those rows
  publish no price.
- `model-card-anthropic-claude-sonnet-5.html` and `model-card-anthropic-claude-opus-5-5.html`
  (read 2026-11-09) — "Computer use" and "Client tools and toolsets using `bedrock-runtime` and
  `bedrock-mantle` endpoints": `computer_20251124`, `computer_toolset_20260801`,
  `browser_toolset_20260801`, `bash_20250124`, `text_editor_20250728`, `memory_20250818` are
  client-executed on both endpoints.
- `models-endpoint-availability.html`
- `inference-responses-api.html`
- `inference-chat-completions.html`
- `inference-messages-api.html`
- `tool-use-server-side.html`
- `web-search.html`
- `projects.html`
- `workspaces.html`
- `cost-mgmt-application-inference-profiles.html`
- `model-invocation-logging.html`
- `monitoring-mantle-metrics.html`
- `quotas-runtime.html`
- `quotas-mantle.html`
- `scaling-throughput-best-practices.html`
