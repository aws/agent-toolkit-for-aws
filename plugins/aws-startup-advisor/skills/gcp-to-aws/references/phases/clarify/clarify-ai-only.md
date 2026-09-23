# AI-Only Migration — Clarify Requirements

**Standalone flow** — Used when ONLY `ai-workload-profile.json` exists (no infrastructure or billing artifacts). Infrastructure stays on GCP; only AI/LLM calls move to AWS Bedrock.

Produces the same `preferences.json` output but with `design_constraints` limited to region and compliance, `startup_constraints` populated, and `ai_constraints` fully populated. Questions are presented in **two progressive batches** with an intermediate save — partial answers persist across sessions.

---

## Step 0: Prior Run Check

Check `$MIGRATION_DIR/` for existing state:

**Case 1 — Completed preferences exist** (`preferences.json` present):

> "I found existing migration preferences from a previous run. Would you like to:"
>
> 1. Re-use these preferences and skip questions
> 2. Start fresh and re-answer all questions

- If 1: skip to Step 3 (Validation), proceed with existing file.
- If 2: delete `preferences.json`, continue to Step 1.

**Case 2 — Draft preferences exist** (`preferences-draft.json` present, no `preferences.json`):

> "I found a partial set of answers from a previous session (1 of 2 batches completed). Would you like to:"
>
> 1. Resume from where you left off — I'll pick up the remaining questions
> 2. Start fresh and re-answer all questions

- If 1: load the draft, skip Batch 1 in Step 2, present Batch 2 directly.
- If 2: delete `preferences-draft.json`, continue to Step 1.

**Case 3 — No prior state**: Continue to Step 1.

---

## Step 1: Present AI Detection Summary

> **AI-Only Migration Detected**
> Your project has AI workloads but no infrastructure artifacts (Terraform, billing). I'll focus on migrating your AI/LLM calls to AWS Bedrock while your infrastructure stays on GCP.
>
> **AI source:** [from `summary.ai_source`]
> **Models detected:** [from `models[].model_id`]
> **Capabilities in use:** [from `integration.capabilities_summary` where true]
> **Integration pattern:** [from `integration.pattern`] via [from `integration.primary_sdk`]
> **Gateway/router:** [from `integration.gateway_type`, or "None (direct SDK)"]

---

## Step 1.5: Fast-Path Check

If `migration-preview.json` exists and `ai_complexity_signal == "likely_simple"` (single model, non-agentic, no multi-provider, no multi-model routing):

> "Your AI migration looks straightforward — one model swapping to Bedrock. I only need 5 quick answers to complete your migration plan."

Present **only Q1.5, Q2, Q3, Q4, Q11** (Q1 framework is extracted; Q5 model is extracted; Q6 capabilities are extracted; Q7–Q10 use defaults). **Q1.5 (compliance) and Q11 (Activate status) are never dropped from the fast path** — "never dropped" means always PRESENTED: the fast-path question set must include them; they are never silently omitted or auto-answered. An explicit user "use defaults for the rest" still applies their documented defaults (compliance → `["unknown"]` + report caveat — never a silent "none", matching full-flow Q2 semantics; Activate → `unknown` + neutral copy) — that is the sanctioned default path, same as full-flow Q27. After answering, skip directly to Step 3.

If `ai_complexity_signal` is `"standard"` or `"complex"`, or `migration-preview.json` is absent, continue to Step 1.75 (mini assumption sheet), then Step 2.

---

## Step 1.75: Mini Assumption Sheet (before Batch 1)

Before asking anything, present what discovery already answered and what will be assumed, as a compact confirm-or-edit sheet (same contract as the full Clarify wizard's Step 2.5 — sheet first, questions after the user responds):

```
### AI migration assumptions — confirm or correct

**Detected from your code:**
| Setting | Value | Source |
| ------- | ----- | ------ |
| Framework | [e.g. Direct SDK] | ai-workload-profile.json |
| Primary model | [e.g. gpt-4o] | code scan (confidence [x]) |
| Input types | [e.g. text only] | capabilities_summary |

**Will be assumed unless you correct them:**
| Setting | Assumed value | Consequence |
| ------- | ------------- | ----------- |
| Usage volume | Low | On-demand pricing, no provisioned-throughput analysis |
| Response speed | Important (<2s) | Sonnet-class + streaming |
| Task complexity | Moderate | Sonnet-class model |

Reply "looks good" to continue to the remaining questions, correct any line
("model: gemini-2.5-pro"), or describe the issue in plain words.
```

Questions resolved on this sheet are **not** re-asked in the batches below; record them with `chosen_by: "extracted"` (detected rows) or `"default"` (assumed rows, sheet-confirmed), and skip their entries in Batch 1/2. Rows the user corrects become `chosen_by: "user"`. Rows with no detection signal stay in the batches as normal questions.

---

## Step 2: Ask Questions in Progressive Batches (Q1–Q11, incl. Q1.5)

Questions are presented in two batches with a save after the first. The user can skip individual questions (defaults applied), say **"use defaults for the rest"** to apply defaults for all remaining questions and proceed immediately, or answer normally.

### Batch 1 — AI Strategy & Setup (Q1–Q5 + Q1.5)

Present with this intro:

```
Before designing your Bedrock migration, I have two short sections of questions.
You can answer each, skip individual ones (I'll use sensible defaults),
or say "use defaults for the rest" at any point.

Let's start with your AI strategy and current setup.

--- AI Strategy & Setup ---
```

## Q1 — AI framework or orchestration layer (select all that apply)

Same decision logic, auto-detect signals, and interpretation as Q14 in `clarify-ai.md`.

Auto-detect: No framework → 1, LiteLLM/OpenRouter/Kong/Apigee → 2, LangChain/LangGraph → 3, CrewAI/AutoGen → 4, OpenAI Agents SDK → 5, MCP/A2A → 6, Vapi/Bland.ai/Retell → 7.

_Skip when:_ `integration.pattern`, `integration.gateway_type`, and `integration.frameworks` together give a definitive answer — including a definitive no-framework signal (`pattern: "direct_api"` with empty `frameworks` and null `gateway_type` → 1). Use extracted values with `chosen_by: "extracted"` and do not present this question. Ask only when the signals are missing or contradict each other.

> 1\) No framework — direct API calls | 2\) LLM router/gateway | 3\) LangChain / LangGraph | 4\) Multi-agent framework | 5\) OpenAI Agents SDK | 6\) MCP/A2A | 7\) Voice platform

Interpret → `ai_framework` array. Default: auto-detect, fallback `["direct"]`.

## Q1.5 — Do you have any compliance or regulatory requirements? (select all that apply)

Compliance gates Bedrock regions, models, and logging **even though your infrastructure stays on GCP** — customer data flows to AWS the moment model calls do. Same answer options and decision logic as Q2 in `clarify-global.md`; the impacts below are the Bedrock-specific subset that applies on this path.

> Even with infrastructure staying on GCP, your prompts and completions will be processed on AWS. Compliance requirements determine which Bedrock regions, models, and configurations are available.
>
> 1\) None | 2\) SOC 2 / ISO 27001 | 3\) PCI DSS | 4\) HIPAA | 5\) FedRAMP / Government | 6\) GDPR / Data residency | 7\) CCPA / CPRA | 8\) I don't know
>
> _(Multiple selections allowed)_

| Answer            | Bedrock Impact                                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| None              | Full model catalog, any Bedrock region; `global.` inference profiles allowed                                                                                                                                                    |
| SOC 2 / ISO 27001 | CloudTrail on Bedrock API calls; encryption at rest for Knowledge Bases and logs                                                                                                                                                |
| PCI DSS           | No cardholder data in prompts without tokenization; CloudTrail + scoped IAM; dedicated logging config                                                                                                                           |
| HIPAA             | BAA required before PHI in prompts; BAA-eligible Bedrock models only; **Guardrails PII masking does NOT apply to CloudWatch logs — original content is logged; encrypt with KMS + restrict IAM**; us-east-1/us-west-2 preferred |
| FedRAMP           | GovCloud Bedrock only (us-gov-east-1/us-gov-west-1) — materially smaller model catalog; verify target model availability before committing the migration                                                                        |
| GDPR              | EU Bedrock regions (eu-west-1, eu-central-1); **geographic (`eu.`) inference profiles only — `global.` profiles route outside the EU boundary**; document cross-border transfer from GCP EU                                     |
| CCPA / CPRA       | Prompt/completion retention policy; deletion workflow for logged content; CloudTrail audit logging                                                                                                                              |

Interpret → `design_constraints.compliance` array (same format as the full flow). An explicit user answer of 1 records `["none"]` with `chosen_by: "user"`. **Skip/default records `["unknown"]`** (never a silent "none" — full-flow Q2 semantics: behaves like "none" for service selection) with `chosen_by: "default"`, `source: "default:Q1.5"` — and append the caveat "Compliance requirements were not confirmed by the user" to `metadata.report_caveats[]` (create the array if absent) so downstream reports surface it. Cross-check with Q4: a GDPR answer constrains the target region jointly with cross-cloud latency.

## Q2 — What matters most for your AI application?

> 1\) Best quality/reasoning | 2\) Fastest speed | 3\) Lowest cost | 4\) Specialized capability (→ Q10\) | 5\) Balanced | 6\) I don't know

| Answer   | Model Impact                                        |
| -------- | --------------------------------------------------- |
| Quality  | Claude Sonnet 5 primary; Opus 4.8 for hardest tasks |
| Speed    | Claude Haiku 4.5; also Nova Micro/Lite              |
| Cost     | Claude Haiku 4.5 or Nova Micro                      |
| Special  | Deferred to Q10                                     |
| Balanced | Claude Sonnet 5                                     |

Interpret → `ai_priority`. Default: 5 → `"balanced"`.

## Q3 — Monthly AI spend on OpenAI or Gemini?

> 1\) < $500 | 2\) $500–$2K | 3\) $2K–$10K | 4\) > $10K | 5\) Don't know

Interpret → `ai_monthly_spend`. Default: 2 → `"$500-$2K"`.

## Q4 — Cross-cloud API call concerns

Unique to AI-only: infrastructure stays on GCP while AI calls route to AWS.

> 1\) Latency critical — AI in hot path | 2\) Latency acceptable — async/users can wait | 3\) Concerned about egress costs | 4\) Want to test first — parallel running

| Answer           | Impact                                         |
| ---------------- | ---------------------------------------------- |
| Latency critical | VPC endpoint; closest region to GCP deployment |
| Acceptable       | Standard endpoint; region by cost              |
| Egress concerned | PrivateLink; egress cost analysis              |
| Test first       | Phased migration; parallel running guidance    |

Interpret → `cross_cloud`. Default: 2 → `"latency-acceptable"`.

## Q5 — Current model in use?

Establishes baseline Bedrock recommendation. Override hierarchy: Q10 special features > Q2 priority > Q7/Q8 volume/latency > Q5 baseline.

_Skip when:_ `models[].model_id` is populated in `ai-workload-profile.json` **with confidence ≥ 0.8** (the same threshold as full-flow Q19) — auto-detect with `chosen_by: "extracted"` and do not present this question. The detected models are already shown in the Step 1 summary. Below 0.8, present the question with the detected model(s) offered as the suggested answer. With 2+ detected models, record `ai_model_baseline` as an array (one entry per model).

> 1\) Gemini Flash | 2\) Gemini Pro | 3\) GPT-3.5 Turbo | 4\) GPT-4/4 Turbo | 5\) GPT-4o | 6\) GPT-5.4/Mini/Nano | 7\) GPT-5.6 Sol/Terra/Luna | 8\) GPT-5/5.x (older) | 9\) GPT-5.5/Pro | 10\) o-series | 11\) Claude (Anthropic SDK) | 12\) Other/Multiple | 13\) Don't know

| Source        | Baseline Recommendation        | Pricing Context                    |
| ------------- | ------------------------------ | ---------------------------------- |
| Gemini Flash  | Claude Haiku 4.5 ($1/$5)       | Strong savings                     |
| Gemini Pro    | Claude Sonnet 5 ($2/$10)       | Comparable tier                    |
| GPT-5.6 (any) | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-5.5       | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-5.4       | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-3.5 Turbo | GPT-5.6 Luna; or Haiku 4.5     | Luna 36% cheaper, 77% under Haiku  |
| GPT-4/4 Turbo | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| GPT-4o        | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| GPT-5.4 Mini  | GPT-5.6 Luna; or Nova Lite     | Mini not on Bedrock — offer both   |
| GPT-5.4 Nano  | GPT-5.6 Luna; or Nova Micro    | Nano not on Bedrock — offer both   |
| GPT-5.x Pro   | GPT-5.6 Sol; or Nova 2 Pro     | Pro not on Bedrock — offer both    |
| GPT-5/5.1/5.2 | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| o-series      | GPT-5.6 Sol/Terra; or Sonnet 5 | Not on Bedrock — offer both        |
| Claude (any)  | Same model on Bedrock          | Client swap only — no model change |

**Same-model rows first.** GPT-5.6 / 5.5 / 5.4 run on Bedrock, so those sources map to themselves. Cost is ~10% ABOVE OpenAI standard (Bedrock in-region is priced at OpenAI's data-residency tier), so the case is AWS commitments, governance, and residency — not savings, and not parity. They are `bedrock-mantle` / Responses-only and in-region only; see `references/shared/openai-on-bedrock.md`. For sources with no Bedrock equivalent, present both a same-vendor upgrade and a cross-family option rather than pre-picking.

Override examples: GPT-4 + Q2=cost → Haiku; Flash + Q10=extended thinking → Sonnet; GPT-4o + Q10=speech → Nova 2 Sonic; GPT-5.5 + Q2=cost → Sonnet 5.

Interpret → `ai_model_baseline`. Default: auto-detect, fallback Q2 priority-based.

### Batch 1 → Save Draft and Present Batch 2

After the user responds to Batch 1:

1. Interpret all Batch 1 answers (apply interpret rules above; apply defaults for skipped questions).
2. Write `$MIGRATION_DIR/preferences-draft.json` with Batch 1 answers:

```json
{
  "metadata": {
    "draft": true,
    "batches_completed": ["ai-strategy"],
    "batches_remaining": ["ai-technical"],
    "migration_type": "ai-only",
    "timestamp": "<ISO timestamp>",
    "discovery_artifacts": ["ai-workload-profile.json"],
    "questions_asked": ["Q1", "Q2", ...],
    "questions_defaulted": [...]
  },
  "design_constraints": { ... },
  "ai_constraints": { ... }
}
```

1. Present Batch 2:

```
Got it — your AI strategy preferences are saved.

Last section — 6 questions about your technical requirements, then we're ready to design.
You can answer each, skip individual ones, or say "use defaults for the rest."

--- Technical Requirements ---
```

**"Use defaults for the rest" handling:** If the user says this during Batch 1, apply defaults for all unanswered Batch 1 questions and all Batch 2 questions, then skip directly to Step 3. **Skip the Batch 1 draft save on this path** — assembly happens in the same turn, so a draft would serve no crash-recovery purpose.

### Batch 2 — Technical Requirements (Q6–Q11)

## Q6 — What input types must the model accept: text only, images (vision), or audio/video?

_Skip when:_ `integration.capabilities_summary` in `ai-workload-profile.json` has definitive values for `vision` AND (`speech_to_text` or `text_to_speech`) — derive from capabilities with `chosen_by: "extracted"` and do not present this question. Only ask if capabilities are unknown or ambiguous (all false with no evidence either way).

> 1\) Text only | 2\) Vision required | 3\) Audio/Video inputs

| Answer      | Impact                                                                                                          |
| ----------- | --------------------------------------------------------------------------------------------------------------- |
| Text only   | Full model catalog                                                                                              |
| Vision      | Claude Sonnet or Haiku (both support multimodal vision); Nova Micro excluded (text-only)                        |
| Audio/Video | Nova 2 Sonic (audio); Nova Reel v1 for video (Legacy — EOL Sep 30, 2026); Claude excluded for audio/video input |

Interpret → `ai_vision`. Default: 1 → no constraint.

## Q7 — Monthly AI usage volume

**Auto-resolve (skip the question):** If `openai-usage-profile.json` exists with non-zero usage, compute total monthly tokens = Σ `usage_by_model[].input_tokens + output_tokens`, map to the tiers below (< 1M → `"low"`, 1–10M → `"medium"`, 10–100M → `"high"`, > 100M → `"very_high"`), record the extraction (`chosen_by: "extracted"`, `source: "openai-usage-profile:usage_by_model"`), and tell the user: "Resolved from your OpenAI usage data: [N tokens/month → tier]." Ask Q7 only if the profile is absent or `partial_window` makes the volume unreliable.

> 1\) < 1M tokens | 2\) 1–10M | 3\) 10–100M | 4\) > 100M | 5\) Don't know

| Answer    | Impact                                             |
| --------- | -------------------------------------------------- |
| Low       | On-demand; no provisioned throughput               |
| Medium    | On-demand with prompt caching analysis             |
| High      | Provisioned throughput analysis; prompt caching    |
| Very high | Provisioned throughput required; capacity planning |

Interpret → `ai_token_volume`: 1 → `"low"`, 2 → `"medium"`, 3 → `"high"`, 4 → `"very_high"`. Default: 2 → `"medium"`.

## Q8 — Response speed importance

Present with concrete anchors: Critical = autocomplete/live chat; Important = chat assistant; Flexible = reports/batch.

> 1\) Critical (< 500ms) | 2\) Important (< 2s) | 3\) Flexible (2–10s)

| Answer    | Impact                                                       |
| --------- | ------------------------------------------------------------ |
| Critical  | Haiku/Nova Micro; streaming required; provisioned throughput |
| Important | Sonnet 5 with streaming; standard on-demand                  |
| Flexible  | Any model; batch inference for cost savings                  |

Interpret → `ai_latency`. Default: 2 → `"important"`.

## Q9 — AI task complexity

Present with concrete examples: Simple = classify/extract/summarize; Moderate = analyze+JSON/few-shot; Complex = multi-turn reasoning/tool use/agentic.

> 1\) Simple | 2\) Moderate | 3\) Complex

| Answer   | Impact                                                                |
| -------- | --------------------------------------------------------------------- |
| Simple   | Haiku/Nova Micro sufficient; significant cost savings                 |
| Moderate | Sonnet 5 recommended; Haiku may suffice with prompt engineering       |
| Complex  | Sonnet 5 required; extended thinking considered; Opus 4.8 for hardest |

Interpret → `ai_complexity`. Default: 2 → `"moderate"`.

## Q10 — Specialized features needed

Same decision logic as Q17 in `clarify-ai.md`.

> 1\) Function calling | 2\) Ultra-long context (> 300K) | 3\) Extended thinking | 4\) Prompt caching | 5\) RAG optimization | 6\) Agentic workflows | 7\) Real-time speed | 8\) Image generation | 9\) Conversational speech | 10\) None

Interpret → `ai_critical_feature`. Default: 10 → no override.

## Q11 — Have you applied for AWS Activate credits?

> **Numbering note:** AI-only Q11 ≡ full-flow **Q27** (startup programs). It is unrelated to the full flow's Q11 (Cloud Run spend) or Q11b (Graviton) — the two flows number independently.

Same rationale, eligibility rules, and answer semantics as Q27 in `clarify-ai.md`. AI-only migrations are exactly the workloads Activate credits offset — Bedrock usage (Claude, Llama, Nova) is credit-eligible. **Never infer funding stage or Activate tier from Q3 spend** (Q27 rule applies here unchanged).

> AWS Activate credits offset Bedrock costs during and after migration — including Claude, Llama, and Nova models. Eligible startups can get $5K–$200K depending on funding stage.
>
> 1. Yes — already have AWS Activate credits
> 2. No — haven't applied yet (self-funded or pre-VC)
> 3. No — VC/accelerator-backed but haven't applied
> 4. I don't know

| Answer                     | Recommendation Impact                                                                                                 |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Already have credits       | Note credit balance in migration plan; flag Bedrock usage as credit-eligible                                          |
| No — self-funded           | Flag **AWS Activate Founders** (up to $5,000, self-service): aws.amazon.com/startups/credits — apply before migrating |
| No — VC/accelerator-backed | Flag **AWS Activate Portfolio** (up to $200,000): requires Activate Provider Org ID from your VC/accelerator          |
| Don't know                 | Surface both tiers; recommend checking with investors/accelerator for Org ID                                          |

Escalations (adapted to AI-only signals): if `ai_monthly_spend` is `">$10K"`, also flag **AWS Credits for AI Startups** ($200,000+, invite-only — contact your AWS Account Manager). If `ai_monthly_spend` is `"$2K-$10K"` or `">$10K"` AND the workload is agentic (Q1 includes 4/5/6 or Q10 = 6), also flag **AWS Generative AI Accelerator** (up to $1M credits, 8-week cohort): aws.amazon.com/startups/generative-ai/accelerator

Interpret → `startup_program_status`: 1 → `"has_credits"`, 2 → `"eligible_founders"`, 3 → `"eligible_portfolio"`, 4 → `"unknown"`. Default: 4 → `"unknown"` — downstream artifacts must use neutral Activate copy (both tiers, no "your status: eligible_*").

### Batch 2 Complete

After the user responds to Batch 2, interpret all Batch 2 answers and proceed to Step 3.

---

## Step 3: Assemble and Write preferences.json

Assemble all interpreted answers from both batches into the final file. If `preferences-draft.json` exists, use it as the base — merge in Batch 2 answers, remove draft-specific metadata fields (`draft`, `batches_completed`, `batches_remaining`), and set `metadata.timestamp` to the current time.

Write `$MIGRATION_DIR/preferences.json`:

**Schema — AI-only structure:**

| Field                      | Path                                         | Notes                                                                                                                                                                                                                                           |
| -------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `migration_type`           | `metadata.migration_type`                    | `"ai-only"` — downstream skips infra phases                                                                                                                                                                                                     |
| `discovery_artifacts`      | `metadata.discovery_artifacts`               | `["ai-workload-profile.json"]`                                                                                                                                                                                                                  |
| `questions_asked`          | `metadata.questions_asked`                   | Q IDs presented AND answered by the user. A presented question resolved via "use defaults for the rest" goes in `questions_defaulted` only — the three lists stay disjoint (clarify.md gate check)                                              |
| `questions_defaulted`      | `metadata.questions_defaulted`               | Array of Q IDs where defaults used                                                                                                                                                                                                              |
| `questions_extracted`      | `metadata.questions_extracted`               | Array of Q IDs skipped via auto-detect                                                                                                                                                                                                          |
| `target_region`            | `design_constraints.target_region`           | Derived, precedence: Q1.5 compliance (fedramp → us-gov-west-1, gdpr → eu-west-1, hipaa → us-east-1) > GCP region from discovery when captured > Q4 cross-cloud pref > fallback us-east-1. `chosen_by: "derived"`; prompt names the rule applied |
| `compliance`               | `design_constraints.compliance`              | From Q1.5 — gates Bedrock regions/models                                                                                                                                                                                                        |
| `startup_program_status`   | `startup_constraints.startup_program_status` | From Q11 — same field as full-flow Q27                                                                                                                                                                                                          |
| `ai_framework`             | `ai_constraints.ai_framework`                | From Q1                                                                                                                                                                                                                                         |
| `ai_priority`              | `ai_constraints.ai_priority`                 | From Q2                                                                                                                                                                                                                                         |
| `ai_monthly_spend`         | `ai_constraints.ai_monthly_spend`            | From Q3                                                                                                                                                                                                                                         |
| `cross_cloud`              | `ai_constraints.cross_cloud`                 | From Q4 (unique to AI-only)                                                                                                                                                                                                                     |
| `ai_model_baseline`        | `ai_constraints.ai_model_baseline`           | From Q5                                                                                                                                                                                                                                         |
| `ai_vision`                | `ai_constraints.ai_vision`                   | From Q6                                                                                                                                                                                                                                         |
| `ai_token_volume`          | `ai_constraints.ai_token_volume`             | From Q7                                                                                                                                                                                                                                         |
| `ai_latency`               | `ai_constraints.ai_latency`                  | From Q8                                                                                                                                                                                                                                         |
| `ai_complexity`            | `ai_constraints.ai_complexity`               | From Q9                                                                                                                                                                                                                                         |
| `ai_critical_feature`      | `ai_constraints.ai_critical_feature`         | From Q10                                                                                                                                                                                                                                        |
| `ai_capabilities_required` | `ai_constraints.ai_capabilities_required`    | Derived from `capabilities_summary`                                                                                                                                                                                                             |

Each constraint carries the FULL clarify.md field shape — `value`, `chosen_by` (`user`|`extracted`|`default`|`derived`), `prompt`, `design_consequence`, and `source`/`question_id` per the clarify.md source-field rules. (The short `{ value, chosen_by }` form shown above is an abbreviation, not the schema.) No nulls. All schema rules from `clarify.md` apply, with two AI-only bindings: `metadata.clarify_mode` is `"fast_path"` when Step 1.5 fired, `"full"` for the two-batch flow; and this flow's `questions_extracted` is the full flow's `questions_skipped_extracted` (downstream consumers accept both names).

After writing `preferences.json`, delete `$MIGRATION_DIR/preferences-draft.json` if it exists.

---

## Step 4: Update Phase Status

Before phase completion, enforce output gate:

- `preferences.json` must exist.
- `preferences.json.metadata.migration_type` must equal `"ai-only"`.

If either check fails: STOP and output: "AI-only clarify output validation failed. Fix `preferences.json` before completing Phase 2."

Use the Phase Status Update Protocol (read-merge-write) to update `.phase-status.json` in the same turn as the output message:

- Set `phases.clarify` to `"completed"`
- Set `current_phase` to `"design"`

Output: "Clarification complete. Proceeding to Phase 3: Design AI Migration Architecture."
