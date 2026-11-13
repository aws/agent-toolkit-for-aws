# Design

Chooses a Bedrock target, endpoint, and client API for every workload and writes `$MIGRATION_DIR/aws-design-ai.json` in the provider-neutral contract `references/vendored/ai/schema-design-aws-ai.md` (JSON Schema: `references/contracts/aws-design-ai.schema.json`). Infrastructure stays where it runs; only the AI calls move. This skill writes that contract's shape; the contract's Status section describes what gcp-to-aws and azure-to-aws emit today.

**Execute every step in order.** The inputs are `ai-workload-profile.json`, `preferences.json`, and, when Discover wrote them, `migration-preview.json` and the usage profiles in `$MIGRATION_DIR`. Do not scan code again, and do not read files outside `$MIGRATION_DIR` and this skill.

## Step 0: Plan

```bash
python3 <SKILL_BASE>/scripts/design-ai.py plan $MIGRATION_DIR
```

On a non-zero exit, stop and tell the user:

| `error`                   | What to tell the user                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------- |
| `preferences_not_found`   | Clarify has not finished; resume at Clarify.                                          |
| `preferences_not_ai_only` | `preferences.json` was not written by this skill's Clarify; re-run Clarify.           |
| `profile_*`               | The profile no longer validates; quote `detail` and re-run Discover.                  |
| any other value           | Quote `detail`.                                                                       |

On success the JSON has:

- `rows[]`: one entry per `design_blocks[]` row, in order, with `workload_id`, `model_id`, `provider`, `source_service`, `source_api`, `capability`, `capability_confidence`, `confidence_warning`, `fronted_by` (gateways in front of the source), `mantle_requests` (the Clarify Q10.5 entries that apply to this workload, in policy order), and `mantle.lane`.
- `guides[]`: load every file listed, each with the Read tool. Do not copy, concatenate, or write them anywhere through the shell. Each is a vendored rubric or this skill's `references/shared/openai-on-bedrock.md`.
- `constraints`: the Clarify answers this phase reads, with each documented default filled in for a key Clarify did not write.
- `projection`: the profile's `ai_sources[]` and `gateways[]`. Copy them into `metadata` verbatim.
- `not_designed[]`: sources whose model was not observed. They get no row; name each in the summary and say Discover must record the model before it can be designed.
- `tiered_strategy_required` and `quota_risk_floor`.

If `rows[]` is empty, write `aws-design-ai.json` with the required fields, empty arrays, and `halt: {"reason": "no observed model to design", "blocking": [...]}` naming each `not_designed[]` source with `kind: "model_not_observed"`. Tell the user and stop.

## Step 1: Region and compliance

Read `constraints.target_region` and `constraints.compliance`.

1. Check every candidate Bedrock model with `aws___get_regional_availability` (AWS MCP Server) in the target Region, and set `metadata.regional_validation` to `"checked"`. If the call fails, use the static table in `ai-migration-guardrails.md` and set `"fallback_static"`.
2. A model the Region does not carry adds a `regional_warnings[]` entry `{service, target_region, nearest_available, impact}`. It does not block the design.
3. Apply compliance as hard filters before choosing models. Skip only `none`, `unknown`, or absent. `unknown` keeps the report caveat in the summary.

| Compliance       | Constraint                                                                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `hipaa`          | BAA-eligible Bedrock models only; verify each with `aws___search_documentation`. Invocation logs keep original content, so require KMS and restricted IAM on the log group. Prefer us-east-1 or us-west-2.   |
| `fedramp`        | GovCloud only (us-gov-east-1, us-gov-west-1); every candidate missing there gets a `regional_warnings[]` entry.                                                                                               |
| `gdpr`           | EU Regions only (eu-west-1, eu-central-1); `eu.` inference profiles or in-Region ids, never `global.` or another geography's profile. Exclude a candidate with no `eu.` profile.                              |
| `pci`            | No cardholder data in prompts without tokenization; CloudTrail on Bedrock calls; scoped IAM, never `bedrock:*`.                                                                                             |
| `soc2` / `ccpa`  | CloudTrail audit logging. CCPA adds a retention policy and a deletion workflow for logged content, and excludes models whose Status in `bedrock-pricing-cache.md` is `restricted` with a retention opt-in.   |

Every constraint that changed a model or Region is recorded in `regional_warnings[]` or in the row's `capability_gaps[]`, and the summary names each regime that shaped the design.

## Step 2: Choose a target per row

Apply `bedrock-pricing-cache.md`'s target policy and the lifecycle restrictions in `ai-model-lifecycle.md` before every choice. A `restricted (…)` model is never chosen unless the user asks for that frontier model by name, and then its data-retention opt-in is stated in the same sentence.

A Claude target from any source follows the target contract for that model in `ai-anthropic-to-bedrock.md` (Opus 5.5, Haiku 5.5): carry its request, inference-profile, and tokenizer requirements into the row's rationale and `capability_gaps[]`.

1. **By capability:**

   | `capability`                                         | Target                                                                    |
   | ---------------------------------------------------- | ------------------------------------------------------------------------- |
   | `text_generation`, `structured_output`, `unknown`    | A text model, chosen by the order in item 2                                |
   | `embedding`                                          | Amazon Titan Text Embeddings V2                                           |
   | `image_generation`                                   | Stability AI: Stable Image Core for cost, Ultra for quality               |
   | `speech_to_text`                                     | Amazon Transcribe: `target_aws_service: "transcribe"`, no `bedrock_models[]` row; Nova 2 Sonic only for speech-to-speech |
   | `text_to_speech`                                     | Amazon Polly: `target_aws_service: "polly"`, no `bedrock_models[]` row; Nova 2 Sonic only for speech-to-speech |

2. **Text models, in this order:**
   1. A Q10 `ai_critical_feature` the source model cannot serve, within the eligible pool.
   2. The same model on Bedrock, when it is eligible and the Region carries it. An `ai_priority` of `balanced` or `cost` does not move it to another family; `cost` adds the cheapest adequate model as an alternative in the rationale (`ai-openai-to-bedrock.md` Tier 2).
   3. `ai_priority`, then `ai_token_volume` and `ai_latency`, then `ai_complexity` and `ai_vision`, using the provider guide's tables.
   4. The source model as the baseline.

3. **Provider guide:** use the guide for the row's `provider` (`openai`: `ai-openai-to-bedrock.md`; `anthropic`: `ai-anthropic-to-bedrock.md`; `google`: `ai-gemini-to-bedrock.md`). A row whose `fronted_by` lists `openrouter` also follows `ai-openrouter-to-bedrock.md`: map each upstream model separately and keep a direct call and a gateway call of the same provider as different rows. Another provider has no guide: choose by item 2 and say so in the rationale.
4. **No same-model target:** when the guide says to present two options (for example OpenAI Tier 1), ask the user once, listing every such row with both options and their trade-offs, before writing the design. Record the chosen option in the rationale.
5. Treat a mapping as compatibility-guided, not 1:1 parity: every row with `model_change: true` needs prompt, tool-calling, and eval validation before cutover, stated in its rationale.

## Step 3: Endpoint and client API per row

`bedrock-runtime` is the default (`bedrock-endpoint-policy.md`). Use the row's `mantle.lane` from Step 0:

| `lane`              | Endpoint and what to write                                                                                                                                                                                                                                                                             |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `runtime`           | `bedrock-runtime`. Write `endpoint_assumption`.                                                                                                                                                                                                                                                        |
| `mantle`            | When the target keeps the source's protocol (a GPT target for an OpenAI source, a Claude target on the Messages API for an Anthropic source), use `mantle.mantle_path` with `mantle_selector` = `mantle.selector` and `mantle_requirement` copied from `mantle.requirement` field for field. Name `also_requested` selectors in the rationale. A cross-family target has no Mantle path: keep `bedrock-runtime` and disclose the selector as below. |
| `in_region_check`   | Mantle as above only when `bedrock-runtime` serves the target in that Region through a CRIS profile alone (the CRIS-only gate in `ai-openai-to-bedrock.md`). Otherwise `bedrock-runtime` with the in-Region model id; when no in-Region id exists there, add a `regional_warnings[]` entry.           |
| `api_conflict`      | The selector needs an API the source does not call: Responses for `background_inference`, `web_search`, and `server_side_tools`, Messages for `workspaces`. Ask the user: move the client to that API on Mantle (`mantle_openai_responses` or `mantle_messages`, with the matching `required_client_api`), or keep the source API on `bedrock-runtime` and disclose the selector. Never write a Mantle row on an API the selector cannot use. |
| `provider_mismatch` | `projects` on a non-OpenAI source or `workspaces` on a non-Anthropic source. Keep `bedrock-runtime`, disclose the selector, and tell the user to correct Q10.5.                                                                                                                                         |
| `no_mantle_path`    | Only OpenAI and Anthropic models have Mantle paths, embedding, image, and audio calls have none, and an Anthropic model has no Responses path for a Responses-only selector. Keep `bedrock-runtime` and disclose the selector.                                                                                                                                                  |
| `api_unknown`       | The source API is not recorded (a framework call, or a 1.0 profile). Ask the user which API the call uses, then apply the matching lane.                                                                                                                                                               |

- **Disclose** means: the row keeps `bedrock-runtime`, writes `endpoint_assumption`, and names the selector, its `source`, and its `evidence` in `capability_gaps[]` and the rationale. A recorded requirement is never dropped silently.
- **`mantle_only_model_or_api`** is never in Clarify. When the chosen model or API exists only on `bedrock-mantle` per `ai-openai-to-bedrock.md` and `openai-on-bedrock.md`, write the Mantle path for the source API with `mantle_requirement: {"workload_id": "<id>", "selector": "mantle_only_model_or_api", "source": "catalog", "evidence": "<catalog file and row>"}`.
- **`endpoint_assumption`** is exactly: `No Mantle-only requirement was recorded for <ids>; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.`, where `<ids>` are the workload ids on that row, joined by a comma and a space, with no quotes or backticks.
- **`migration_path` and `required_client_api`:** a same-model GPT target on `bedrock-runtime` is `runtime_openai_cris` with a CRIS-prefixed id and the source's own API (`responses` or `chat_completions`); `converse` only for a Converse-only need such as Guardrails. An Anthropic SDK source is `runtime_messages` with `messages`. A cross-family text target is `converse` with `converse`. An embedding or image target is `direct` with `invoke`. A bare `openai.gpt-*` id is a Mantle id and never goes on a non-Mantle row.
- Two workloads with the same source model and target share one row, unless only one of them takes Mantle: then write one Mantle row and one non-Mantle row.

## Step 4: Assessment, price, and quota per row

1. **Price:** read the target's rate for the selected inference option from `bedrock-pricing-cache.md` and the guide, and the source's rate from the guide. When `migration-preview.json` has measured spend for the source, cite it in the rationale. A rate the cache does not publish is `"unverified"`, never an estimate. Fill `source_provider_price`, `bedrock_price`, and `price_comparison`.
2. **`honest_assessment`:** the same eligible model is `strong_migrate`, justified by zero behavior change and AWS commitments, not by an assumed saving. Otherwise: Bedrock cheaper is `strong_migrate`; within 25% and `ai_priority` not `cost` is `moderate_migrate`; the source more than 25% cheaper with `ai_priority` `cost` is `weak_migrate` or `recommend_stay`. `recommend_stay` needs a non-cost blocker in `honest_assessment_reason` (a Region with no suitable model, a Realtime API dependency, an Assistants feature with no Bedrock equivalent, or an unsupported API surface). The top-level `honest_assessment` is the weakest row value.
3. **`quota_risk`:** apply `bedrock-quotas.md` § Quota Risk Assessment and its Observed on-demand peak rule, reading the peaks from the usage profiles in `$MIGRATION_DIR`. When `quota_risk_floor` is `"high"`, every row is `"high"`.
4. **`model_change`:** `false` only when the target is the source model itself.

## Step 5: Strategy and warnings

- **`tiered_strategy`:** when `tiered_strategy_required` is true, write the three-tier plan from the provider guide's volume section (roughly 60% simple traffic on a small model, 30% on a mid model, 10% on the frontier model) and note Intelligent Prompt Routing when the tiers stay in one model family. Otherwise `null`.
- **`multi_model_warnings[]`**, each `{type, message}`:
  - `embeddings_reindex`: an embedding row and a text row. Re-embed the whole vector store and check the index dimension before cutover.
  - `cascade_pair`: a small model (`*-mini`, `*-nano`, `*-lite`, Haiku) and a flagship model of the same provider. Test the replacement pair together.
  - `multi_model_tiered`: more than three distinct source models. Migrate and validate one at a time.
  - `image_separate`: an image row and a text row. Image quality needs human evaluation.
  - `speech_separate`: a speech row. It targets other AWS services with other pricing and APIs.

## Step 6: Architecture

- **`capability_mapping`:** for each capability that is `true` in `integration.capabilities_summary`, `{parity: "full" | "partial" | "none", notes}`. Batch and fine-tuning are `partial`; a capability no target serves is `none`. A 1.0 profile has no `integration`: map only what the rows show.
- **`code_migration`:** `primary_pattern` equals `integration.pattern` (`direct_sdk` for a 1.0 profile), `framework`, `files_to_modify[]` from the rows' `call_sites` (`[]` for a 1.0 profile), and `dependency_changes`. A row fronted by OpenRouter adds `openrouter_path`: `same_model_runtime` for a same-model `runtime_openai_cris` row, `same_model_mantle` for a Mantle row, `direct` for a cross-family row, or `litellm` / `keep_openrouter` when the user chose to keep a router.
- **`infrastructure`:** `[]`. This skill reads no infrastructure.
- **`services_to_migrate[]`:** one entry per source service, `{source_service, aws_service, effort, notes}`.
- **`agentic_design`:** when the profile has `agentic_profile`, `{"migration_approach": "undecided"}`: keep the framework and change only the model layer, and say in the summary that an AgentCore Harness or Strands design is not in this skill yet. Otherwise `null`.
- **`design_blocks[]`:** one per row, with the row's `workload_id`, `model_id`, `capability`, `capability_confidence`, and `confidence_warning` copied as given, exactly one of `target_bedrock_model` and `target_aws_service` set, and a rationale a customer can read.
- `metadata.bedrock_models_selected` lists each `target_bedrock_model` once.

## Step 7: Write and check

Write `$MIGRATION_DIR/aws-design-ai.json` with `phase: "design"`, `focus: "ai"`, `timestamp`, and `source_profile: "ai-workload-profile.json"`, then:

```bash
python3 <SKILL_BASE>/scripts/design-ai.py check $MIGRATION_DIR
```

Fix every reported `errors[]` entry and run the check again until it prints `"ok": true`. Do not complete Design while it fails. The check enforces the contract, the verbatim projection, the row order, the endpoint rules in Step 3, and the assessment, quota, and warning rules above; it cannot judge the model choice itself, so Steps 2 and 4 stay your responsibility.

## Step 8: Present the summary

In under 25 lines:

1. The overall assessment, flagged prominently when it is `weak_migrate` or `recommend_stay`, with the reason.
2. A table per row: source model, Bedrock target, endpoint (`bedrock-mantle (<selector>, <source>)` or `bedrock-runtime`), price comparison, assessment.
3. The integration pattern and migration complexity.
4. Capability gaps, including every disclosed Mantle requirement and every `not_designed[]` source.
5. The compliance regimes applied, or the caveat when compliance was not confirmed.
6. That Estimate and Generate are not in this skill yet.
