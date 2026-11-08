---
_fragment: artifacts-ai
_of_phase: generate
_contributes:
  - ai-migration/ (provider adapter, scripts, monitoring tf)
  - generation-ai.json
---

# Generate — AI Migration Artifacts

> **Loaded when `aws-design-ai.json` exists AND `run_mode` is `decide_and_execute`.** Runs under
> the `rw` worker (file-only: no skill calls, no `terraform`/`python` execution — validation stays
> main-window). Execute ALL steps in order.

The Azure port of gcp's `generate-artifacts-ai.md` + the essential migration-plan output of gcp's
`generate-ai.md`, folded into one fragment (azure keeps Generate lean — `generate-artifacts-*`
fragments, no separate plan file). Reads `aws-design-ai.json`, `estimation-ai.json` (for the
budget seed), `ai-workload-profile.json`, `preferences.json`. Missing a REQUIRED input → STOP
("Missing required artifact: `<file>`. Complete the prior phase that produces it.").

## Step 0: Determine the artifact path

Read `aws-design-ai.json → ai_architecture.code_migration.migration_path` and
`preferences.json → ai_constraints.ai_framework`. Language for the adapter comes from
`ai-workload-profile.json → integration.languages[0]` (`python`→`.py`, `javascript`/`typescript`→
`.js`, `go`→`.go`, else `.py`).

| `migration_path` / framework                                      | Emits (in addition to the always-on set)                                  |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `runtime_openai_cris` (default same-model path)                   | `ai-migration/migrate_to_mantle.sh` (CRIS variant — `bedrock-runtime` base URL + CRIS id + the row's `required_client_api`) — skip the provider adapter |
| `mantle_openai_responses` / `mantle_openai_chat` (only with `mantle_selector`) | `ai-migration/migrate_to_mantle.sh` — **skip the provider adapter**       |
| `runtime_messages` (Anthropic source, default)                    | `ai-migration/provider_adapter.{py,js,go}` whose Bedrock class keeps the Anthropic SDK at `https://bedrock-runtime.{region}.amazonaws.com/anthropic` with a string Bedrock token (`required_client_api: messages`; `bedrock:InvokeModel*` IAM) — not a Mantle script, not a Converse rewrite |
| `mantle_messages` (Anthropic source, only with `mantle_selector`) | same adapter shape at `https://bedrock-mantle.{region}.api.aws/anthropic` with `bedrock-mantle:*` IAM |
| `direct` (or absent) or `converse`                                | `ai-migration/provider_adapter.{py,js,go}` — `converse` is an explicit boto3 Converse rewrite, not a Mantle script |
| `gpt-oss`                                                         | `ai-migration/provider_adapter.{py,js,go}` targeting gpt-oss via Converse |
| gateway (`llm_router`/`api_gateway`/`voice_platform`/`framework`) | `ai-migration/gateway_config.{yaml,py,json}` — skip the adapter           |
| agentic `migration_approach == harness`                           | `ai-migration/harness.json`, `ai-migration/deploy_harness.sh`             |
| agentic `migration_approach == strands`                           | `ai-migration/strands_agents.py`, `ai-migration/deploy_strands.sh`        |
| eval opted in                                                     | `ai-migration/eval-prompts.jsonl`, `ai-migration/run-evaluation.sh`       |

**Always emit (every path):** `ai-migration/setup_bedrock.sh`, `ai-migration/test_comparison.py`
(always Python), `ai-migration/bedrock_monitoring.tf`.

> **`bedrock-runtime` CRIS is the default path for Azure OpenAI.** Azure OpenAI apps use the OpenAI
> SDK, so a same-model move keeps the SDK and changes only base URL
> (`https://bedrock-runtime.{region}.amazonaws.com/openai/v1`), credential, model ID (CRIS profile),
> and IAM (`bedrock:InvokeModel*`) — `migrate_to_mantle.sh` in its CRIS variant, not a rewritten
> adapter. Mantle is used only when Design recorded a `mantle_selector`
> (`references/vendored/ai/bedrock-endpoint-policy.md`). The `direct` adapter path is the exception
> (cross-family swap, or a Converse feature no same-model path can serve), not the default.

## Step 1M: `migrate_to_mantle.sh` (mantle path)

Shell script, **dry-run by default** with an `--execute` flag. Sets
`OPENAI_BASE_URL=https://bedrock-mantle.{region}.api.aws/openai/v1` (the `/openai/v1` segment is
load-bearing — bare `/v1` 404s), a Bedrock API key / token provider (NOT an OpenAI key), the
`openai.gpt-*` model ID, and IAM needing `bedrock-mantle:*` (not `bedrock:InvokeModel`). Per-workload
`MAX_TOKENS` from a lookup table, default `1024`. No prompt changes when the source already uses
`responses.create`; a Chat Completions source may keep `chat.completions.create` for GPT-6/GPT-5.6
models (both support it natively) — reshape to Responses is optional, not mandatory.

**CRIS variant (`runtime_openai_cris`) client surface:** check `aws-design-ai.json` →
`ai_architecture.bedrock_models[].required_client_api`. If non-Responses (`converse`,
`chat_completions`, or `invoke`), the generated CRIS script/adapter MUST emit that surface — e.g.
a Converse call against the `bedrock-runtime` CRIS id — rather than defaulting to
`responses.create`. Absent or `"responses"` keeps the Responses surface (the region-only-move
default).

Adapt Azure-specific client/deployment/API-version settings to the Bedrock client rather than relying on OPENAI_BASE_URL alone.

## Step 1: `provider_adapter.{py,js,go}` (direct / gpt-oss / runtime_openai_cris path)

Feature-flagged on `AI_PROVIDER` (values `azure_openai` | `bedrock` | `shadow`; **default
`azure_openai`**). Emits methods gated on `integration.capabilities_summary`: `text_generation`→
`generate`, `streaming`→`generate_stream`, `embeddings`→`embed`. Bedrock side is boto3 Converse
(`BEDROCK_INFERENCE_PROFILE_ARN` env, model-id fallback); for `runtime_messages` it is instead
`anthropic.Anthropic(base_url="https://bedrock-runtime.{region}.amazonaws.com/anthropic",
api_key=provide_token(region=region))` — a string token minted per client, client created and
closed per request boundary, `messages.create` / `messages.stream` unchanged, `global.`/Geo
Claude profile ID (`mantle_messages`: same shape at `https://bedrock-mantle.{region}.api.aws/anthropic`). **Azure source side:** the `azure_openai`
branch calls the `AzureOpenAI` client (`azure_endpoint`, `api_version`) for Python / `@azure/openai`
(or the `openai` SDK with `azure` config) for Node — NOT Vertex/`@google-cloud/vertexai`.

## Step 2: `test_comparison.py`

Always Python. Runs the same prompts through the source (Azure OpenAI) and the Bedrock target and
diffs outputs, so the user validates behavior before cutover.

## Step 3: `setup_bedrock.sh`

Enables the chosen Bedrock model(s), sets up IAM, and (mantle path) the Bedrock API key. For
EVERY `runtime_openai_cris` target whose `required_client_api` is `responses` or
`chat_completions` — by id form, not model family: any proprietary GPT CRIS id, so GPT-5.6 Sol /
Terra / Luna, the GPT-6 family (Astra, Sol, Luna, 6.1 Sol, 6.1 Terra) and GPT-5.5 / GPT-5.4
(`us.openai.gpt-5.5` / `global.openai.gpt-5.5`, `us.openai.gpt-5.4` / `global.openai.gpt-5.4`), or
their `inference-profile/` ARNs — the IAM policy must grant `bedrock:InvokeModel` on
`arn:aws:bedrock:{region}:{account}:project/default` in addition to the CRIS inference-profile
ARN: a Responses request on `bedrock-runtime` authorizes the default project separately from the
inference target (<https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html>,
"Permissions", read 2026-11-07), and each of those model cards (read 2026-11-07) repeats the
requirement for its runtime CRIS ids. `iam_policy.py --target <aws_model_id>=<required_client_api>`
(one pair per `bedrock_models[]` row, each with its own API — a GPT Chat / Responses secondary beside
a Claude Messages primary still gets the grant) emits the third ARN for exactly those rows and omits
it for a `converse` or `messages` row (Converse is the application-inference-profile route) and for
every Anthropic / Nova / gpt-oss id. The mantle
`bedrock-mantle:*` policy (bare `openai.gpt-5.5` / `openai.gpt-5.4` / `openai.gpt-5.6-*` /
`openai.gpt-6-*` ids included) is unaffected.

## Step 3B: `gateway_config.{yaml,py,json}` (gateway users)

Format by framework: `llm_router` → `gateway_config.yaml` (LiteLLM); `framework` →
`gateway_config.py`; `voice_platform` → `gateway_config.json`; `api_gateway` → `gateway_config.yaml`.
OpenRouter branches on `code_migration.openrouter_path` (`same_model_runtime` → run Step 1M's CRIS
variant, the default same-model subroute; `same_model_mantle` → run Step 1M's Mantle variant, only
with a `mantle_selector`; `direct` → adapter; `litellm` → yaml; `keep_openrouter` → json; absent → litellm).

## Step 3C / 3E: agentic artifacts

Harness (`migration_approach == harness`): `harness.json`, `deploy_harness.sh`,
`incremental_migration.sh` (only if `harness_config.incremental_migration`). Strands
(`== strands`): `strands_agents.py`, `deploy_strands.sh`, `bridge_retarget.py` (only if
`strands_config.bridge_phase`). Both port from gcp unchanged (AgentCore is the target, agnostic of
source cloud). Include the GCP Strands runtime's generated `ai-migration/main.py` and
`ai-migration/pyproject.toml`; register and populate the runtime before deployment, as in that template.

## Step 3D: eval artifacts (opt-in)

`eval-prompts.jsonl`, `run-evaluation.sh`.

## Step 3F: `bedrock_monitoring.tf` (all paths)

Budget `limit_amount = ceil(projected_bedrock_monthly * 1.5)`, min 10, emitted as a computed
integer (seed `projected_bedrock_monthly` from `estimation-ai.json → cost_comparison.projected_bedrock_monthly`,
default 50). Cost-anomaly monitor `monitor_type = "DIMENSIONAL"`, `monitor_dimension = "SERVICE"`.
`aws_bedrock_inference_profile` requires the AWS provider `>= 5.66`.

## Write `generation-ai.json`

```jsonc
{
  "phase": "generate",
  "generation_source": "ai",
  "timestamp": "<ISO 8601>",
  "migration_plan": { "approach": "...", "phases": [], "models_to_migrate": [] },
  "step_by_step_guide": {},
  "rollback_plan": {
    "mechanism": "feature_flag",
    "flag_name": "AI_PROVIDER",
    "default_value": "azure_openai",
    "rollback_time": "...",
    "triggers": []
  },
  "monitoring": {},
  "production_readiness_checklist": [],
  "success_criteria": {},
  "recommendation": {}
}
```

`rollback_plan.mechanism` MUST be `"feature_flag"`; `flag_name` `AI_PROVIDER`; `default_value`
`azure_openai` (the pre-cutover provider — flip to `bedrock` to cut over, back to `azure_openai`
to roll back).

## Write `STARTUP_PROGRAMS.md`

AWS Activate tiers, branching on `preferences.json → startup_program_status`
(`eligible_founders`/`eligible_portfolio`/`has_credits`/`unknown`). Include the Generative AI
Accelerator section ONLY when `ai_monthly_spend` is high AND `agentic_profile.is_agentic`. Content
is AWS-only and ports from gcp unchanged.

## Step: Self-Check

- [ ] `AI_PROVIDER` default is `azure_openai` everywhere (adapter flag + rollback default).
- [ ] The mantle path emitted `migrate_to_mantle.sh` and NO provider adapter; the direct/gpt-oss
      path emitted the adapter and NO mantle script.
- [ ] `bedrock_monitoring.tf` present on every path; budget is a computed integer ≥ 10.
- [ ] No secret VALUE in any emitted file; credentials are env-var references.
- [ ] Bare proprietary GPT ids use Mantle; Astra runtime calls retain the validated `us.` /
      `global.` CRIS id. Chat/Responses and runtime artifact selection match the saved design.
- [ ] No **bare** proprietary GPT model ID (including bare `openai.gpt-5.5` / `openai.gpt-5.4`)
      paired with a Converse/`bedrock-runtime` path. GPT-5.6, GPT-6, GPT-5.5 and GPT-5.4 MAY use
      `migration_path: "runtime_openai_cris"` on `bedrock-runtime` with a CRIS id (`us.`/`in.`/`global.`
      for GPT-5.6 Terra and Luna; `us.`/`global.` only for GPT-5.6 Sol, GPT-6, GPT-5.5 and GPT-5.4) —
      this is NOT a violation.
- [ ] Plugin attribution strings say "Azure-to-AWS".
- [ ] `generation-ai.json` validates; `rollback_plan.mechanism == "feature_flag"`.

## Phase Completion

**Do NOT update `.phase-status.json`** — the parent `generate.md` handles phase completion after
the main-window validation step.

> **`_assert` has no teeth.** The self-check is prose the `rw` worker both produces and evaluates;
> CI binds it but never runs it. Judge correctness by the step-5 AI fixture oracle and a
> fresh-context run, never by "the artifacts were emitted."

## Status — build step 3 (AI route)

The AI Generate fragment. Wired into `generate.md` `_fragments`
(`_when aws-design-ai.json exists AND run_mode == decide_and_execute`). Its inputs come from
`design-ai.md` (step 2) and `estimate-ai.md` (step 3). Reachable end-to-end only once
`discover-app-code.md` (step 4) produces `ai-workload-profile.json` for a non-IaC estate.
