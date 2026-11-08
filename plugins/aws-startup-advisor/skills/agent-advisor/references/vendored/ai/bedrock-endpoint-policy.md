# Bedrock Endpoint Policy — `bedrock-runtime` by default, `bedrock-mantle` by selector

> Canonical endpoint-selection policy for every Bedrock migration path in this plugin.
> Vendored into each consuming skill as `references/vendored/ai/bedrock-endpoint-policy.md`
> and kept byte-identical by `tools/sync-vendored.py`; edit HERE, then run the sync.
> Every statement below comes from the public Amazon Bedrock User Guide pages listed in
> § Sources (read 2026-11-07). Re-read those pages before changing a row.

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

**Pricing never selects an endpoint.** Per-token pricing for the same model is identical on both
endpoints; choose by API and capability need.

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
