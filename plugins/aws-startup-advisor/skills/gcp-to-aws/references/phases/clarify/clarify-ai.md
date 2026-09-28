---
_fragment: ai
_of_phase: clarify
_contributes:
  - preferences.json (ai_constraints section, startup_constraints.startup_program_status)
---

# Category F — AI/Bedrock (If `ai-workload-profile.json` Exists)

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing on the wizard path.** It reads the AI workload profile,
> resolves what it can, assigns a disposition per row, and returns rows.
> `clarify-assemble.md` presents them. (The "ask me everything" Full Flow variant in
> `clarify.md` presents these questions directly in batches — see that file — because the
> user explicitly opted out of the sheet-first wizard.)

_Fire when:_ `ai-workload-profile.json` exists in `$MIGRATION_DIR/`.

No canonical shared file governs this category — `azure-to-aws`'s `clarify-ai.md` asks a
closely parallel but independently-maintained question set for the same reason
`clarify-ai-only.md` on both skills does: AI/Bedrock model selection, capability matching,
and agentic-framework questions are close in shape between GCP and Azure sources, but every
answer option and consequence line here was authored against GCP-sourced signals
(`ai-workload-profile.json`'s `integration.pattern`/`gateway_type`, Vertex/Gemini detection).
Unifying this category into a shared file is future scope, not part of this restructure —
see `references/vendored/clarify/` for the categories that already are shared (region,
compliance, availability, cost-appetite, multi-cloud).

---

## AI Context Summary

Before presenting questions, show:

> **AI Context Summary:**
> **AI source:** [from `summary.ai_source`: "Gemini", "OpenAI", "Both", or "Other"]
> **Profile origin:** [from `metadata.profile_source`: if `iac_vertex` or `summary.inferred_from_iac` is true, state that Terraform was the primary signal and application code did not fully characterize the workload]
> **Models detected:** [from `models[].model_id`; if empty, say **None inferred from code or IaC** — the following questions will pin down models and frameworks]
> **Capabilities in use:** [from `integration.capabilities_summary` where true; if all false or pattern is `unknown`, say **Not inferred — confirm below**]
> **Integration pattern:** [from `integration.pattern`; if `unknown`, say **Unknown (IaC-only)**] via [from `integration.primary_sdk`, or **not determined**]
> **Gateway/router:** [from `integration.gateway_type`, or "None (direct SDK)"]
> **Frameworks:** [from `integration.frameworks`, or "None"]

---

## Q14 — Framework auto-detection signals

**Auto-detect signals** — scan IaC and application code before asking:

---

## Multi-Workload Confirmation Table (if `workloads[]` has ≥ 2 entries)

**Fire when:** `ai-workload-profile.json` contains a non-empty `workloads[]` array with 2 or more entries. This replaces the per-workload Q16–Q22 loop with a single confirmation table.

Before presenting Q16–Q22, show the detected workloads and proposed Bedrock targets:

> **Detected AI Workloads:**
>
> | # | Model                   | SDK Method                   | Capability        | Confidence | Proposed Bedrock Target       |
> | - | ----------------------- | ---------------------------- | ----------------- | ---------- | ----------------------------- |
> | 1 | gemini-2.5-flash        | generateContent              | text_generation   | medium     | [text-class per Q16 priority] |
> | 2 | gemini-2.5-flash        | generateContent (structured) | structured_output | high       | [same text-class as row 1]    |
> | 3 | imagen-3.0-generate-001 | generateImages               | image_generation  | high       | [image-class model]           |
>
> **For each row, you can:**
>
> - **Accept** — keep the proposed mapping
> - **Edit** — change the capability or Bedrock target
> - **Drop** — this isn't an AI workload (false positive)
>
> _(v1: merge and split actions are planned for v2)_
>
> _Do you accept all mappings? Or type the row number to edit._

**Timing:** This table fires AFTER existing global/infra questions complete (Q1–Q15 and Q14–Q15 AI globals). It does not replace or conflict with the primary Clarify orchestrator or its auto-extraction — those run first, and their answers feed into the capability confirmation.

**Behavior:**

1. **High-confidence rows (confidence = `high`):** Pre-fill Bedrock target from `capability → Bedrock model` mapping. Do NOT ask Q16–Q22 for these rows unless the user edits.

2. **Medium/low-confidence rows:** Ask at most 2 questions per row:
   - "Is the detected capability correct?" (confirm or select from: text_generation, structured_output, image_generation, embedding, speech_to_text, text_to_speech, document_extraction, image_analysis, speech_transcription, unknown)
   - "What matters most for this workload?" (Q16 priority: quality/speed/cost/balanced)

3. **Target mapping** (default, overridden by user edits — look up actual model IDs from design-refs tables, not hardcoded names):

   | Capability           | Target Class                                   | Notes                                                                                                                                                  |
   | -------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
   | text_generation      | Text/reasoning class                           | Apply Q16–Q19 override hierarchy                                                                                                                       |
   | structured_output    | Text/reasoning class (same as text_generation) | Uses same Bedrock target as text_generation for that workload's priority tier — structured output is a mode, not a different model                     |
   | image_generation     | Image generation class                         | e.g., Stable Image Core (cost) / Ultra (quality)                                                                                                       |
   | embedding            | Embedding class                                | e.g., Titan Embed Text v2                                                                                                                              |
   | speech_to_text       | Speech-to-text class                           | e.g., Transcribe                                                                                                                                       |
   | text_to_speech       | Text-to-speech class                           | e.g., Polly                                                                                                                                            |
   | document_extraction  | Traditional-AI (non-LLM) class                 | GCP Document AI detected — no Q16–Q22 questions; routes to Design's `ai.md` rubric (Textract / Bedrock Data Automation), not a Bedrock model pick      |
   | image_analysis       | Traditional-AI (non-LLM) class                 | GCP Vision API detected — no Q16–Q22 questions; routes to Design's `ai.md` rubric (Rekognition / Bedrock Data Automation), not a Bedrock model pick    |
   | speech_transcription | Traditional-AI (non-LLM) class                 | GCP Speech-to-Text detected — no Q16–Q22 questions; routes to Design's `ai.md` rubric (Transcribe / Bedrock Data Automation), not a Bedrock model pick |
   | unknown              | Ask Q16–Q22 for this workload                  | Falls back to full questionnaire                                                                                                                       |

4. **After confirmation — persist workloads[] to preferences.json (REQUIRED):**

   Immediately after the user confirms (accepts all, or finishes editing individual rows), write the final `workloads[]` array to `preferences.json`. This is the **single source of truth** for all downstream phases (Design, Estimate, Generate). Do NOT rely on `ai-workload-profile.json` downstream — it contains the raw Discover output before user edits/drops.

   **Write rules:**
   - Read existing `preferences.json` (preserving all non-AI fields written by earlier Clarify categories)
   - Add or overwrite the top-level `workloads` key with the confirmed array
   - Each entry MUST include: `workload_id`, `model_id`, `sdk_method`, `capability`, `capability_confidence`, `structured_output`, `call_sites`, `target_bedrock_model`, and the user's `priority`/`latency_tier` selections (use defaults `"balanced"`/`"standard"` for high-confidence rows that were auto-accepted)
   - Dropped rows are excluded from `workloads[]` — they do not appear
   - Write the file atomically (write to `.tmp`, then rename) to prevent partial writes on failure
   - If write fails: STOP. Output: "Failed to persist workloads to preferences.json — do not proceed to Design."

   **Single-workload case:** If only 1 workload exists (confirmation table skipped), persist it to `workloads[]` after Q16–Q22 completes, using the same schema. Design always reads `workloads[]` regardless of count.

   **Zero-workload case:** If no AI workloads detected and user doesn't report any, write `"workloads": []` to preferences.json. Design emits empty `design_blocks[]` for this case.

5. **Question budget:** 4 global questions (Q14, Q15, framework, spend) + at most 2 per medium/low workload. For an app with 3 high-confidence workloads: 4 questions total, 0 per-workload. For an app with 2 high + 1 medium: 4 + 2 = 6 questions max.

**Single-workload fallback:** If `workloads[]` has exactly 1 entry or is empty, skip the confirmation table and proceed with the existing Q16–Q22 flow below.

**Known limitations (v1):**

- Gateway calls (LiteLLM, OpenRouter) and custom HTTP calls to AI endpoints are not yet detected as separate workloads — they may be miscategorized or missed. Planned for v2.
- Merge and split actions are not supported in v1. Users who need to combine or split workloads should edit individual rows.

---

## Q14 — What AI framework or orchestration layer are you using? (select all that apply)

**Auto-detect signals** — scan IaC and application code before asking:

- No AI framework imports, raw HTTP calls to OpenAI/Gemini endpoints → 1
- LiteLLM imports or config files → 2
- OpenRouter base URL in code/config → 2
- PortKey, Helicone, Martian SDK imports → 2
- Kong AI Gateway, Apigee AI config files → 2
- Custom proxy class wrapping the AI client → 2
- LangChain/LangGraph imports → 3
- LangChain/LlamaIndex with provider-agnostic model config → 3
- CrewAI imports, `Crew` and `Agent` class definitions → 4
- AutoGen imports, `ConversableAgent` patterns → 4
- Custom multi-agent loop with dispatcher logic → 4
- OpenAI Agents SDK / Swarm imports → 5
- Custom while-loop agent with tool-call parsing → 5
- `mcp.server` / `mcp.client` imports, MCP config JSON files → 6
- A2A protocol config or SDK imports → 6
- Vapi, Bland.ai, Retell SDK imports → 7
- Nova Sonic / Nova 2 Sonic or Whisper integration in code → 7

_Skip when:_ Auto-detection fully resolves the framework(s). Use detected value(s) with `chosen_by: "extracted"`.

**Partial detection — confirm, don't re-ask (preferred over the full taxonomy):** When detection produced signals but not full resolution (e.g. one framework import found alongside unexplained raw HTTP calls), present a confirm card instead of the full option list:

> I detected **[framework, e.g. LangChain]** ([evidence, e.g. `langchain` in requirements.txt]) — plus some direct API calls I couldn't attribute.
>
> 1. **That's right** — LangChain plus some direct calls
> 2. **Edit** — show me all framework options
> 3. **Just [detected framework]** — the direct calls are part of it

Accept → record detected value(s) with `chosen_by: "user"` (confirmed). Edit → fall through to the full question below. Only present the full taxonomy cold when detection found **no** signals at all.

> How your AI calls reach the model determines migration effort. Gateway users can often migrate by changing a single config line.
>
> 1. No framework — direct API calls to OpenAI/Gemini
> 2. LLM router/gateway (LiteLLM, OpenRouter, PortKey, Kong, Apigee)
> 3. LangChain / LangGraph
> 4. Multi-agent framework (CrewAI, AutoGen, custom)
> 5. OpenAI Agents SDK / custom agent loop
> 6. MCP servers or A2A protocol
> 7. Voice/conversational agent platform (Vapi, Retell, Bland.ai)
>
> _(Multiple selections allowed)_

| Answer                             | Recommendation Impact                                                                                     | Migration Effort  | Timeline                                             |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------- | ---------------------------------------------------- |
| 1) No framework — direct API calls | Swap SDK calls to Bedrock SDK; evaluate AgentCore (Harness) if planning agentic                           | Low               | 1–3 weeks depending on call sites                    |
| 2) LLM router/gateway              | Add Bedrock as provider in gateway config; no app code changes; verify SigV4 auth                         | Minimal           | Hours to 1–3 days                                    |
| 3) LangChain / LangGraph           | Provider swap via `ChatBedrock`; chains/graphs/tools preserved; validate tool schemas                     | Low               | 1–3 days; 1 week if complex graphs                   |
| 4) Multi-agent framework           | Path 1: Keep framework, swap LLM provider (lower effort). Path 2: Migrate to Bedrock multi-agent (deeper) | Medium            | Path 1: 3–5 days; Path 2: 2–4 weeks                  |
| 5) OpenAI Agents SDK               | Highest effort; tightly coupled to OpenAI API; recommend AgentCore (Harness, or Runtime for code loops)   | High              | 2–4 weeks                                            |
| 6) MCP / A2A                       | AgentCore supports MCP natively (Gateway exposes tools as MCP); A2A interop; recommend AgentCore          | Low–Medium        | 3–5 days MCP; 1–2 weeks A2A                          |
| 7) Voice platform                  | If platform supports Bedrock natively → config change; otherwise evaluate Nova 2 Sonic                    | Minimal to Medium | Hours if native; 2–3 weeks if Nova 2 Sonic migration |

> **Never recommend classic Bedrock Agents (`bedrock-agent`) as a migration target.** It is in maintenance mode and closed to new customers as of July 30, 2026 ([AWS announcement](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-service-availability/)). Agentic targets are AgentCore Harness (config-based, default) or AgentCore Runtime (code-defined loops) — consistent with Q23–Q26.

### Combination Logic

| Combination                          | Approach                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 1 only                               | Simplest path — direct SDK migration                                                                   |
| 2 only                               | Quick win — gateway config change, skip SDK migration steps                                            |
| 2 + any other                        | Gateway swap is the quick win; assess framework migration as separate workstream                       |
| 3 + 1                                | Two workstreams: LangChain provider swap (fast) + direct call migration (slower)                       |
| 4 + 6                                | Complex — multi-agent with MCP tooling; recommend AgentCore to unify orchestration and tools           |
| 5 + anything                         | 5 is the long pole; plan timeline around Agents SDK migration; other layers may be quick wins          |
| Multiple frameworks (3+4, 3+5, etc.) | Assess independently; prioritize by traffic volume or business criticality; consolidate post-migration |

If answer includes 2 and no other selections, skip or abbreviate SDK migration steps. If answer is 1 only, proceed with standard model migration flow.

Interpret → `ai_framework` array (multiple selections → array of all selected values). Default: auto-detect from code, fallback `["direct"]`.

---

## Q15 — Approximately how much are you spending on your AI/LLM providers per month?

**Personalize the wording:** substitute the detected provider names from `ai-workload-profile.json` → `models[].provider` when available (e.g. "on OpenAI" or "on OpenAI and Gemini, per your detected usage"). Do not assume providers the profile did not detect.

> 1. < $500/month
> 2. $500–$2,000/month
> 3. $2,000–$10,000/month
> 4. $10,000/month
> 5. I don't know

| Answer               | Recommendation Impact                                                                                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| < $500/month         | Low token-volume baseline for Bedrock cost comparison; Bedrock free tier may cover initial testing                                                                                                         |
| $500–$2,000/month    | Mid band for Bedrock savings comparison and token-volume derivation                                                                                                                                        |
| $2,000–$10,000/month | Higher band — Bedrock cost savings prominently featured; Savings Plans analysis; if agentic workload detected → flag **AWS Generative AI Accelerator** (cohort program — see program page for eligibility) |
| > $10,000/month      | High band — provisioned throughput analysis; if agentic workload detected → also flag **AWS Generative AI Accelerator** (cohort program — see program page for eligibility)                                |
| I don't know         | Use mid-band estimate with ±25% accuracy caveat in `estimation-ai.json`                                                                                                                                    |

**Do not map spend bands to AWS Activate Founders vs Portfolio.** Funding stage is not inferable from monthly AI spend — ask **Q27** instead.

Interpret → `ai_monthly_spend`. Default: 2 → `"$500-$2K"`.

---

## Q16 — What matters most for your AI workloads?

Present with concrete anchors: Quality = legal analysis/code gen; Speed = autocomplete/live chat; Cost = classification/tagging at scale; Specialized = specific feature (→ Q17); Balanced = all-rounder.

> 1. Best quality/reasoning — accuracy matters most, willing to pay more
> 2. Fastest speed — response time is the primary constraint
> 3. Lowest cost — high volume, budget tight, good-enough quality at scale
> 4. Specialized capability — rely on a specific feature (covered in Q17)
> 5. Balanced — no single dimension dominates
> 6. I don't know

| Answer                 | Recommendation Impact                                                                                                                                                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Best quality/reasoning | Claude Sonnet 5 (latest, highest reasoning in Sonnet family) — primary; Claude Opus 4.8 for the most demanding reasoning tasks (same headline on-demand $5/$25 as Opus 4.6 on standard Bedrock pricing); Claude Opus 4.6 remains a valid alternative |
| Fastest speed          | Claude Haiku 4.5 — lowest latency in Claude family; also consider Amazon Nova Micro/Lite for cost-optimized speed                                                                                                                                    |
| Lowest cost            | Claude Haiku 4.5 or Amazon Nova Micro — lowest cost per token                                                                                                                                                                                        |
| Specialized capability | Deferred to Q17 to determine which model                                                                                                                                                                                                             |
| Balanced               | Claude Sonnet 5 as default balanced recommendation                                                                                                                                                                                                   |

Interpret → `ai_priority`. Default: 5 → `"balanced"`.

---

## Q17 — What is your MOST CRITICAL specialized AI feature?

> 1. Function calling / Tool use
> 2. Ultra-long context (> 300K tokens)
> 3. Extended thinking / Chain-of-thought
> 4. Prompt caching
> 5. RAG optimization
> 6. Agentic workflows
> 7. Real-time speed (< 500ms)
> 8. Multimodal with image generation
> 9. Real-time conversational speech
> 10. None — standard features are sufficient

| Answer                               | Recommendation Impact                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Function calling / Tool use          | Claude Sonnet 5 — best-in-class tool use on Bedrock via structured JSON tool schemas; supports parallel tool calls and multi-turn tool use                                                                                                                                                                                                                                         |
| Ultra-long context (> 300K tokens)   | Claude Sonnet/Opus 4.6 long-context SKUs where available (standard on-demand for 4.6 matches base tier in US East N. Virginia per [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)); or Llama 4 Scout (10M), Llama 4 Maverick (1M), Nova 2 Pro/Lite (1M) for very large native context windows                                                                    |
| Extended thinking / Chain-of-thought | Claude Sonnet 5 with extended thinking mode; Claude Opus 4.8 for most complex reasoning                                                                                                                                                                                                                                                                                            |
| Prompt caching                       | Claude Sonnet 5 with prompt caching enabled; cost savings analysis included. **Caveat:** caching only helps for long, repeated context (system prompts, documents). Per-model minimum token thresholds (~1K–4K tokens) and TTL apply — short prompts won't cache. Verify current minimums at docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html before recommending. |
| RAG optimization                     | Amazon Bedrock Knowledge Bases recommended alongside model; Titan Embeddings for vector store                                                                                                                                                                                                                                                                                      |
| Agentic workflows                    | Claude Sonnet 5 with AgentCore (Harness); multi-agent orchestration guidance included                                                                                                                                                                                                                                                                                              |
| Real-time speed (< 500ms)            | Claude Haiku 4.5 or Nova Micro; streaming response guidance included                                                                                                                                                                                                                                                                                                               |
| Multimodal with image generation     | Claude Sonnet 5 (vision) + Stability AI for generation (Core cost-first / Ultra quality-first)                                                                                                                                                                                                                                                                                     |
| Real-time conversational speech      | Amazon Nova 2 Sonic recommended for speech-to-speech; latency guidance included                                                                                                                                                                                                                                                                                                    |
| None                                 | Default recommendation from Q16 priority stands                                                                                                                                                                                                                                                                                                                                    |

Interpret → `ai_critical_feature`. Default: 10 → no override.

---

## Q18 — What's your AI usage volume and cost tolerance?

**Volume half auto-resolves:** If `openai-usage-profile.json` exists with non-zero usage AND `metadata.partial_window` is `false` (a partial window is not a monthly volume — ask normally in that case), derive the volume tier from Σ `usage_by_model[].input_tokens + output_tokens` (< 1M → `"low"`, 1–10M → `"medium"`, > 10M → `"high"`) and ask ONLY the cost-tolerance half ("Your usage data shows [tier] volume. Is budget tight enough to prioritize cost control over model quality? [Y/N]"). Record `ai_token_volume` from the data (`chosen_by: "extracted"`, `source: "openai-usage-profile:usage_by_model"`), not the answer.

> 1. Low volume + quality priority — small-scale, quality matters most
> 2. Medium volume + balanced — moderate production use, balanced approach
> 3. High volume + cost critical — high scale, budget is tight, need cost control

| Answer                        | Recommendation Impact                                                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Low volume + quality priority | On-demand Claude Sonnet; no provisioned throughput needed                                                     |
| Medium volume + balanced      | On-demand Claude Sonnet or Haiku depending on Q16; Savings Plans analysis                                     |
| High volume + cost critical   | **Provisioned throughput strongly recommended**; Claude Haiku or Nova Micro; prompt caching analysis included |

Interpret → `ai_token_volume`: 1 → `"low"`, 2 → `"medium"`, 3 → `"high"`. Default: 1 → `"low"`.

---

## Q19 — Which Gemini or OpenAI model are you currently using?

**Auto-detect signal:** If `ai-workload-profile.json` exists and `models[0].model_id` is set with detection confidence ≥ 0.8, map to the matching Q19 answer and **skip Q19**. Set `ai_model_baseline` with `chosen_by: "extracted"`. If multiple models detected with similar confidence, ask Q19. If `openai-usage-profile.json` exists, prefer its top model by token volume (`usage_by_model[0].model`) as the baseline — billed usage is stronger evidence than code detection — and mention the runner-up models to the user rather than re-asking.

_Skip when:_ Primary model fully resolved from discovery. Use detected value with `chosen_by: "extracted"`.

**Partial detection — confirm, don't re-ask:** When models were detected but below the confidence bar, or several tie, present a confirm card listing only the detected candidates — never the full catalog:

> I found **[model_id 1]** and **[model_id 2]** in your code. Which is your primary production model?
>
> 1. [model_id 1]
> 2. [model_id 2]
> 3. Something else — show all options

**Cold path — family first, then branch:** When nothing was detected, do NOT present the full option list below in one message. Ask a short family question first — "Which provider family is your primary model? 1. Gemini 2. OpenAI GPT 3. OpenAI o-series (reasoning) 4. Other / not sure" — then present only the matching subset of the options below. The full list remains the reference catalog for interpretation.

Establishes baseline Bedrock recommendation. **Override hierarchy:** Q17 special features (hard override) > same-model availability on Bedrock > Q16 priority > Q18/Q21 volume and latency > Q19 source model (baseline only).

**Same-model availability outranks Q16.** When Q19 identifies a model that is available on Bedrock (GPT-5.6 Sol / Terra / Luna, GPT-5.5, GPT-5.4 — see `references/shared/openai-on-bedrock.md`), the recommendation is that same model, and a `balanced`/unset Q16 must not move it to another family. `Q16 = cost` adds a cheaper alternative alongside it rather than replacing it. Only a Q17 hard feature override the source model cannot serve displaces it.

> 1. Gemini 3.5 Flash (GA — current flagship Flash model)
> 2. Gemini 3.5 Flash Thinking (thinking budget enabled)
> 3. Gemini 3.1 Pro
> 4. Gemini 3.1 Flash-Lite (high-volume, low-cost)
> 5. Gemini 2.5 Flash (standard, no thinking budget)
> 6. Gemini 2.5 Flash Thinking (thinking budget enabled — variable output pricing)
> 7. Gemini 2.5 Pro
> 8. Gemini 3 Pro / 3.1 Pro Preview
> 9. Gemini Flash (2.0 Flash) or Gemini Flash 1.5 _(EOL Sep 2025 — flag for source model upgrade)_
> 10. Gemini Pro 1.5 _(EOL Sep 2025 — flag for source model upgrade)_
> 11. GPT-3.5 Turbo
> 12. GPT-4 / GPT-4 Turbo
> 13. GPT-4o
> 14. GPT-5.4 / GPT-5.4 Mini / GPT-5.4 Nano
> 15. GPT-5 / GPT-5.x (older)
> 16. GPT-5.5 / GPT-5.5 Pro
> 17. o-series (o1, o3)
> 18. GPT-5.6 Sol / Terra / Luna
> 19. Other / Multiple models
> 20. I don't know

| Source Model                   | Baseline Bedrock Recommendation                                                                                                                                                 | Pricing Context                                                                                                                                                                                                                                                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gemini 3.5 Flash (GA)          | Nova Lite ($0.06/$0.24) — 94% cheaper                                                                                                                                           | Gemini 3.5 Flash is $1.50/$9.00 — 5x more expensive than old 2.5 Flash; Nova Lite is the cost-equivalent; very strong migration case                                                                                                                                                                                   |
| Gemini 3.5 Flash Thinking      | Claude Sonnet 5 with extended thinking ($2/$10)                                                                                                                                 | At the listed $1.50/$9.00 rates, Gemini has lower input and output unit prices than Sonnet 5. Consider Sonnet for capability requirements; compare each model's billed thinking tokens and quality before claiming workload savings                                                                                    |
| Gemini 3.1 Flash-Lite          | Nova Micro ($0.035/$0.14) — 88% cheaper; or Nova Lite ($0.06/$0.24) — 76% cheaper                                                                                               | Gemini 3.1 Flash-Lite is $0.25/$1.50; strong Bedrock cost case                                                                                                                                                                                                                                                         |
| Gemini 2.5 Flash (standard)    | Nova Lite ($0.06/$0.24) — 88% cheaper                                                                                                                                           | Gemini 2.5 Flash is $0.30/$2.50; Nova Lite is the cost-equivalent; strong migration case                                                                                                                                                                                                                               |
| Gemini 2.5 Flash Thinking      | Claude Sonnet 5 with extended thinking ($2/$10)                                                                                                                                 | At the listed $0.30 input and $3.50/M upper output rate, Gemini is ~$1.37/M blended vs Sonnet 5 at ~$4.67/M (2:1 input/output). Sonnet is a capability alternative, not a cost saving at equal token volumes; profile each model's billed thinking tokens                                                              |
| Gemini 2.5 Pro                 | Nova 2 Pro ($1.38/$11) — 9% cheaper; or Nova Pro ($0.80/$3.20) — 62% cheaper                                                                                                    | Gemini 2.5 Pro is $1.25/$10; migration case is cost + AWS consolidation                                                                                                                                                                                                                                                |
| Gemini 3 Pro / 3.1 Pro         | Claude Sonnet 5 ($2/$10) — agentic reliability; or Nova 2 Pro ($1.38/$11) — cost                                                                                                | Gemini 3.1 Pro is $2/$12 — Sonnet 5 at $2/$10 is ~13% cheaper blended, a modest edge; the migration case is agentic reliability and AWS ecosystem more than cost. Be honest: Gemini 3.1 Pro leads on general benchmarks.                                                                                               |
| Gemini Flash 1.5 / 2.0 (older) | Nova Lite ($0.06/$0.24) or Nova Micro ($0.035/$0.14) — **flag Gemini 1.5 Flash as EOL (Sep 2025); recommend upgrading source model to 3.5 Flash before or alongside migration** | Strong Bedrock cost savings; 1.5 Flash is past EOL so migration is doubly urgent                                                                                                                                                                                                                                       |
| Gemini Pro 1.5 (older)         | Claude Sonnet 5 ($2/$10) — **flag Gemini 1.5 Pro as EOL (Sep 2025); recommend upgrading source model to 3.1 Pro before or alongside migration**                                 | 1.5 Pro is past EOL; migration to Bedrock and source model upgrade should be planned together                                                                                                                                                                                                                          |
| GPT-5.6 Sol / Terra / Luna     | **The same model on Bedrock** (`openai.gpt-5.6-sol` / `-terra` / `-luna`)                                                                                                       | Bedrock in-region is at OpenAI's data-residency-tier rate — about 10% above OpenAI standard, so a small cost increase, not a saving. Default recommendation on risk grounds; no behavior delta. Mantle/Responses only, in-region only. The 1M context tier costs 2.0x input / 1.5x output.                             |
| GPT-5.5                        | **GPT-5.5 on Bedrock** (`openai.gpt-5.5`)                                                                                                                                       | Same model — Bedrock in-region is $5.50/$33 (~10% over OpenAI std $5/$30). If the user's priority is cost and a model change is acceptable, offer Sonnet 5 ($2/$10, 68% cheaper) or Opus 4.8 ($5/$25, 20% cheaper) as alternatives — not as the default.                                                               |
| GPT-5.4                        | **GPT-5.4 on Bedrock** (`openai.gpt-5.4`)                                                                                                                                       | Same model — Bedrock in-region is $2.75/$16.50 (~10% over OpenAI std $2.50/$15). Sonnet 5 ($2/$10) is ~36% cheaper blended — a real saving, but a model change; offer it as the cost alternative, not the default.                                                                                                     |
| GPT-3.5 Turbo                  | GPT-5.6 Luna ($0.22/$1.32) — same vendor, far better quality; or Claude Haiku 4.5 ($1/$5)                                                                                       | Luna is 30% cheaper than GPT-3.5 **and** 75% cheaper than Haiku 4.5. Present both; Luna is usually the better framing.                                                                                                                                                                                                 |
| GPT-4 / GPT-4 Turbo            | GPT-5.6 Terra (same vendor, newer tier); or Claude Sonnet 5 ($2/$10)                                                                                                            | Not on Bedrock — a model change is unavoidable. GPT-4 Turbo is $10/$30, so Sonnet is 72% cheaper; Terra keeps prompt idioms. Offer both.                                                                                                                                                                               |
| GPT-4o                         | GPT-5.6 Terra (same vendor, newer tier); or Claude Sonnet 5 ($2/$10)                                                                                                            | Not on Bedrock. GPT-4o is $2.50/$10 — Sonnet 5 at $2/$10 is ~7% cheaper blended, so cost is roughly neutral for the cross-family move. Offer both.                                                                                                                                                                     |
| GPT-5.4 Mini                   | GPT-5.6 Luna ($0.22/$1.32); or Nova Lite ($0.06/$0.24)                                                                                                                          | Mini is not on Bedrock. Nova Lite is cheapest; Luna keeps the vendor. Offer both.                                                                                                                                                                                                                                      |
| GPT-5.4 Nano                   | GPT-5.6 Luna ($0.22/$1.32); or Nova Micro ($0.035/$0.14)                                                                                                                        | Nano is not on Bedrock. Nova Micro is cheapest; Luna keeps the vendor. Offer both.                                                                                                                                                                                                                                     |
| GPT-5.4 Pro / GPT-5.5 Pro      | GPT-5.6 Sol (same vendor, flagship reasoning); or Nova 2 Pro ($1.375/$11)                                                                                                       | Pro variants are not on Bedrock. Nova 2 Pro is 94% cheaper than the $30/$180 Pro rate; Sol keeps the vendor. Offer both.                                                                                                                                                                                               |
| GPT-5 / GPT-5.1 / GPT-5.2      | GPT-5.6 Terra (same vendor, newer tier); or Claude Sonnet 5 ($2/$10)                                                                                                            | Not on Bedrock. GPT-5 / 5.1 are ~11% cheaper than Sonnet 5 at source, GPT-5.2 is ~25% more expensive (both measured against Sonnet 5's blended rate), so cost is a wash for GPT-5 / 5.1 and favors Bedrock for GPT-5.2; the cross-family case is capability/consolidation — and they are on a vendor deprecation path. |
| o-series (o1, o3)              | GPT-5.6 Sol or Terra (same vendor); or Claude Sonnet 5 with extended thinking / DeepSeek-R1                                                                                     | Not on Bedrock. o1 at $15/$60 → Nova 2 Pro 85% cheaper; o3 at $2/$8 → DeepSeek-R1 32% cheaper. Offer a same-vendor and a cross-family option.                                                                                                                                                                          |

**Override examples:** GPT-4 + Q16=cost → Haiku; Flash + Q17=extended thinking → Sonnet; GPT-4o + Q17=speech → Nova 2 Sonic; GPT-3.5 + Q22=complex → Sonnet; GPT-5 + Q16=balanced → Sonnet; Gemini 2.5 Flash Thinking + Q16=cost → evaluate Nova Lite only if it meets the required capabilities and quality bar; do not select Sonnet 5 for expected savings solely because the source uses full thinking mode.

**Same-model examples (Q16 does not displace these):** GPT-5.5 + Q16=balanced → **GPT-5.5 on Bedrock**; GPT-5.5 + Q16=cost → **GPT-5.5 on Bedrock**, with Sonnet 5 offered as a 68%-cheaper alternative the user can accept or decline; GPT-5.6 Luna + Q16=cost → **Luna on Bedrock** (already cheaper than Haiku 4.5; only Nova undercuts it); GPT-5.4 + Q17=speech → Nova 2 Sonic (Q17 hard override wins — the source model cannot serve speech-to-speech).

> Claude Sonnet 5 figures use $2/$10 — the launch rate, made the standard price on Sep 1, 2026 (the scheduled increase to $3/$15 was cancelled). Earlier revisions priced Sonnet 5 at $3/$15; any cached estimate built on that rate overstates Sonnet 5 by a third.

Interpret → `ai_model_baseline`. Default: auto-detect from code, fallback Q16 priority-based.

---

## Q20 — What input types must the model accept: text only, images (vision), or audio/video?

**Auto-detect signal:** Read `integration.capabilities_summary`:

| Signal                                           | Extract                                                                    | Skip Q20?                      |
| ------------------------------------------------ | -------------------------------------------------------------------------- | ------------------------------ |
| `vision: true`                                   | `ai_vision: "vision-required"`                                             | Yes — `chosen_by: "extracted"` |
| `speech_to_text: true` or `text_to_speech: true` | `ai_vision: "audio-video"`                                                 | Yes                            |
| all false / text only                            | `ai_vision: "text-only"`                                                   | Yes                            |
| `image_generation: true` and `vision: false`     | note in `ai_capabilities_required`; skip Q20 (image output ≠ vision input) | Yes                            |

_Skip when:_ Modalities fully resolved from `capabilities_summary`. Use detected value with `chosen_by: "extracted"`.

> 1. Text only
> 2. Vision required — model must process images
> 3. Audio/Video inputs needed

| Answer             | Recommendation Impact                                                                                                  |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| Text only          | Full model catalog available; cheapest/fastest text model per Q16 priority                                             |
| Vision required    | Claude Sonnet or Haiku (both support multimodal vision); Nova Micro excluded (text-only)                               |
| Audio/Video inputs | Amazon Nova 2 Sonic (audio); Nova Reel v1 for video (Legacy — EOL Sep 30, 2026); Claude excluded for audio/video input |

Interpret → `ai_vision`. Default: 1 → no constraint.

---

## Q21 — How important is AI response speed?

Present with concrete anchors: Critical = autocomplete/live chat/real-time transcription; Important = chat assistant/search augmentation; Flexible = report generation/batch analysis.

> 1. Critical (< 500ms) — users staring at a loading spinner
> 2. Important (< 2s) — quick response expected, brief pause acceptable
> 3. Flexible (2–10s) — users can wait, background/async acceptable

| Answer             | Recommendation Impact                                                                             |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| Critical (< 500ms) | Claude Haiku 4.5 or Nova Micro; streaming required; provisioned throughput for consistent latency |
| Important (< 2s)   | Claude Sonnet 5 with streaming; standard on-demand acceptable                                     |
| Flexible (2–10s)   | Any model; batch inference considered for cost savings at high volume                             |

Interpret → `ai_latency`. Default: 2 → `"important"`.

---

## Q22 — How complex are your AI tasks?

Present with concrete examples: Simple = classify/extract/summarize; Moderate = analyze+JSON/few-shot; Complex = multi-turn reasoning/tool use/agentic.

> 1. Simple (classification, short summaries, extraction)
> 2. Moderate (analysis, structured content, few-shot)
> 3. Complex (multi-step reasoning, tool use, agentic workflows)

| Answer   | Recommendation Impact                                                                     |
| -------- | ----------------------------------------------------------------------------------------- |
| Simple   | Claude Haiku 4.5 or Nova Micro sufficient; significant cost savings vs larger models      |
| Moderate | Claude Sonnet 5 recommended; Haiku may suffice with prompt engineering                    |
| Complex  | Claude Sonnet 5 required; extended thinking considered; Claude Opus 4.8 for hardest tasks |

Interpret → `ai_complexity`. Default: 2 → `"moderate"`.

---

## Category G — Agentic Workflows (If `agentic_profile` exists in `ai-workload-profile.json`)

_Fire when:_ `ai-workload-profile.json` contains `agentic_profile` with `is_agentic: true`.

_Skip entirely when:_ `agentic_profile` is absent from `ai-workload-profile.json`.

---

## Agentic Context Summary

Before presenting Category G questions, show:

> **Agentic Context Summary:**
> **Framework:** [from `agentic_profile.framework`]
> **Agents detected:** [from `agentic_profile.agent_count`] ([list `agents[].agent_id`])
> **Orchestration pattern:** [from `agentic_profile.orchestration_pattern`]
> **Tools:** [from `agentic_profile.tool_count`] tools detected
> **Memory:** [from `agentic_profile.has_memory`; if true, backend: `agentic_profile.memory_backend`]
> **Human-in-the-loop:** [from `agentic_profile.has_human_in_loop`]

---

## Q23 — How do you want to migrate your agent system?

**Auto-detect signals** — recommend default based on `agentic_profile.framework`:

- `gateway_type` is `"llm_router"` and evidence is **LiteLLM** → Default to **1 (retarget)**. Already abstracted from the model provider — migration is a config change (swap model IDs), not a code rewrite. Set `migration_approach: "retarget"` automatically and skip Q23 unless the user explicitly asks to evaluate Harness or Strands.
- `gateway_type` is `"llm_router"` and evidence is **OpenRouter** → Default to **1 (retarget)** only when the underlying model is an OpenAI model with a Mantle target (same-model Mantle move, per `design-ai.md`'s OpenRouter guidance). Otherwise surface the full option set — an OpenRouter → Mantle move changes the base URL, credential type, and model-ID format, so it is not the same one-line change LiteLLM users get. Set `migration_approach: "retarget"` with `chosen_by: "extracted"` only in the Mantle-eligible case; otherwise ask Q23.
- `langgraph`, `crewai`, `autogen` → Default to 1 (retarget). These frameworks support Bedrock as a model provider with minimal code changes.
- `openai_agents` → Surface all options. OpenAI Agents SDK is tightly coupled to OpenAI API; retarget is harder. Note partial retarget (HTTP-compatible routing to Bedrock) as a bridge.
- `strands` → Already AWS-native. Recommend 2 (Harness) for managed deployment or note "already on target framework."
- `custom` → Surface all options. Custom loops vary widely in complexity.

_Skip when:_ Auto-detection fully resolves AND user has no preference signal. Use detected default with `chosen_by: "extracted"`.

> Your agent system can migrate to AWS in different ways, each with different effort and risk:
>
> 1. **Retarget** — Keep your current framework ([framework name]), swap the model layer to Bedrock. Fastest path, lowest risk. Your orchestration code stays the same.
> 2. **AgentCore Harness** — Declare your agent as configuration (model + tools + prompt). Get managed runtime, memory, identity, and observability. Good for simpler agents or incremental migration. _(GA — all commercial regions where AgentCore is available)_
> 3. **Strands native** — Rewrite orchestration using AWS Strands SDK on AgentCore. Most AWS-integrated, highest effort. Best for teams wanting full AWS-native multi-agent capabilities.
> 4. **I'm not sure** — Help me decide based on my workload.

| Answer               | When it fits                                                                                                                               | Effort range                                                     | Risk                           |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | ------------------------------ |
| 1) Retarget          | Working system, team knows the framework, need to ship fast. LangGraph/CrewAI/AutoGen with Bedrock model provider support.                 | 1–3 weeks depending on agent count, tool count, test coverage    | Low — orchestration unchanged  |
| 2) AgentCore Harness | Simple single-agent, OpenAI Assistants migration, want managed runtime, or incremental migration (run existing models on AWS infra first). | 3–10 days depending on tool complexity and memory requirements   | Low — config-based, reversible |
| 3) Strands native    | OpenAI Agents SDK or custom loops where retarget doesn't work well, multi-agent systems, team willing to refactor for AWS-native benefits. | 2–6 weeks depending on agent count, graph complexity, tool count | Medium — orchestration rewrite |
| 4) Undecided         | —                                                                                                                                          | —                                                                | —                              |

**For OpenAI Agents SDK users:** Note that a partial retarget (HTTP-compatible routing to Bedrock while keeping OpenAI SDK orchestration) is a valid short-lived bridge before committing to 2 or 3. This is not a fourth path — it's a Phase 0 step within 2 or 3.

**If answer is 4:** Recommend 1 (retarget) as default for LangGraph/CrewAI/AutoGen users. Recommend 2 (Harness) for OpenAI Assistants or simple single-agent patterns. Recommend 3 (Strands) only if user explicitly wants AWS-native multi-agent and accepts refactor cost.

Interpret → `ai_constraints.agentic.migration_approach`: 1 → `"retarget"`, 2 → `"harness"`, 3 → `"strands"`, 4 → `"undecided"` (treated as `"retarget"` in Design unless overridden). Default: auto-detect based on framework.

---

## Q24 — Do your agents need to remember context across sessions?

> 1. No — each request is independent, no memory needed
> 2. Within a session — conversation history during a single interaction, but fresh start each time
> 3. Across sessions — remember user preferences, past interactions, accumulated knowledge between separate conversations

| Answer          | Recommendation Impact                                                                                                                                                                                                                                           |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No memory       | Standard stateless invocation. No AgentCore Memory needed.                                                                                                                                                                                                      |
| Within session  | AgentCore Harness sessions are stateful by default (microVM per session). No additional config needed for Harness path. For retarget path: existing framework memory (e.g., LangGraph checkpointer) continues to work.                                          |
| Across sessions | AgentCore Memory service recommended. Persists knowledge, user preferences, and interaction history across sessions. For retarget path: evaluate existing memory backend migration (Redis → ElastiCache, Postgres → RDS, vector store → OpenSearch Serverless). |

Interpret → `ai_constraints.agentic.memory_requirement`: 1 → `"none"`, 2 → `"session"`, 3 → `"cross_session"`. Default: 2 → `"session"`.

---

## Q25 — How long do your agent tasks typically run?

> 1. Quick (< 30 seconds) — simple tool calls, single-turn responses
> 2. Medium (30 seconds – 5 minutes) — multi-step reasoning, several tool calls
> 3. Long (5 minutes – 1 hour) — complex research, multi-agent collaboration, iterative refinement
> 4. Very long (1+ hours) — extended autonomous work, large-scale data processing

| Answer    | Recommendation Impact                                                                                                                                                    |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Quick     | Standard invocation. Any deployment model works.                                                                                                                         |
| Medium    | AgentCore Runtime recommended for managed scaling. Harness sessions handle this natively.                                                                                |
| Long      | AgentCore Runtime strongly recommended (supports up to 8-hour sessions). Serverless alternatives (Lambda) will timeout.                                                  |
| Very long | AgentCore Runtime required (8-hour max session). If tasks exceed 8 hours: recommend breaking into sub-tasks with session chaining, or evaluate custom compute (ECS/EKS). |

Interpret → `ai_constraints.agentic.task_duration`: 1 → `"quick"`, 2 → `"medium"`, 3 → `"long"`, 4 → `"very_long"`. Default: 2 → `"medium"`.

---

## Q26 — Do you want to migrate incrementally?

> 1. Yes — run my existing models (OpenAI/Gemini) on AWS infrastructure first, then swap to Bedrock models later when I'm confident
> 2. No — do a full model swap to Bedrock in one go
> 3. I'm not sure

| Answer            | Recommendation Impact                                                                                                                                                                                                                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Yes (incremental) | AgentCore Harness multi-model switching: deploy on Harness with existing OpenAI/Gemini model (API key in AgentCore Identity), then override `--model-id` per invocation to A/B test Bedrock. Swap default when confident. Works for both Harness and retarget paths. |
| No (full swap)    | Standard migration: swap model layer directly to Bedrock. Faster to complete but higher risk per deployment.                                                                                                                                                         |
| Not sure          | Default to incremental if using Harness path (it's free — multi-model switching is built in). Default to full swap if retarget path with LangChain/LangGraph (simpler to test with framework's built-in model switching).                                            |

Interpret → `ai_constraints.agentic.incremental_migration`: 1 → `true`, 2 → `false`, 3 → auto-select based on `migration_approach`. Default: `true` for Harness path, `false` for retarget path.

---

## Category G Combination Logic

| Combination                             | Design Impact                                                                    |
| --------------------------------------- | -------------------------------------------------------------------------------- |
| 1 (retarget) + 3 (cross-session memory) | Retarget model layer + migrate memory backend to AWS (Redis → ElastiCache, etc.) |
| 2 (harness) + 1 (no memory)             | Simplest Harness config — model + tools + prompt, no memory setup                |
| 2 (harness) + 3 (cross-session memory)  | Harness + AgentCore Memory service                                               |
| 2 (harness) + 4 (very long tasks)       | Flag: 8-hour session limit. Recommend task decomposition or session chaining.    |
| 3 (strands) + 3 (cross-session memory)  | Strands SessionManager + AgentCore Memory                                        |
| Any + 1 (incremental)                   | Include incremental migration script in Generate artifacts                       |

---

## Category H — Startup Programs (Always fires when Category F fires)

_Fire when:_ `ai-workload-profile.json` exists (same trigger as Category F). **Q27 is ESSENTIAL** in wizard mode — ask in the Step 4 essentials batch after Q15 (and after Q26 if agentic). Do not place Q27 on the assumption sheet; funding stage cannot be defaulted from spend.

---

## Q27 — Have you applied for AWS Activate credits?

**Presentation:** Ask Q27 as its own short follow-up **after** the technical AI essentials are answered — not mixed into the same numbered batch. It is a funding question, not a technical one; separating it keeps the technical batch focused and makes clear that skipping it never affects the architecture (only the credits guidance). One-line lead-in: "Last one, and it's about money rather than tech:".

**Rationale:** AWS Activate credits apply directly to Bedrock usage (including Claude, Llama, Nova, and other third-party models). Surfacing eligibility at the migration decision moment helps startups reduce the cost of the migration itself. This takes 30 seconds to answer and can unlock $5K–$200K in credits.

**Activate eligibility:** Pre-Series B, founded in the last 10 years, AWS Account on Paid Tier Plan, and either new to Activate Credits or requesting more credits than previously received.

> AWS Activate credits offset Bedrock costs during and after migration — including Claude, Llama, and Nova models. Eligible startups can get $5K–$200K depending on funding stage.
>
> 1. Yes — already have AWS Activate credits
> 2. No — haven't applied yet (self-funded or pre-VC)
> 3. No — VC/accelerator-backed but haven't applied
> 4. I don't know

| Answer                     | Recommendation Impact                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Already have credits       | Note credit balance in migration plan; flag Bedrock usage as credit-eligible                                                                                   |
| No — self-funded           | Flag **AWS Activate Founders** (up to $5,000, self-service): aws.amazon.com/startups/credits — apply before starting migration to offset Bedrock testing costs |
| No — VC/accelerator-backed | Flag **AWS Activate Portfolio** (up to $200,000): requires Activate Provider Org ID from your VC/accelerator — contact them for the Org ID before applying     |
| Don't know                 | Surface both tiers; recommend checking with investors/accelerator for Org ID                                                                                   |

If `ai_monthly_spend` is `">$10K"`: also flag **AWS Credits for AI Startups** ($200,000+, invite-only for startups ready to scale post-Activate-Portfolio — contact your AWS Account Manager; aws.amazon.com/startups/credits).

If `ai_monthly_spend` is `"$2K-$10K"` or `">$10K"` AND `agentic_profile.is_agentic == true`: also flag **AWS Generative AI Accelerator** (up to $1M credits, 8-week cohort — adjacent cohort program, distinct from the credits-hub funnel): aws.amazon.com/startups/generative-ai/accelerator

Interpret → `startup_program_status`: 1 → `"has_credits"`, 2 → `"eligible_founders"`, 3 → `"eligible_portfolio"`, 4 → `"unknown"`. Default: 4 → `"unknown"`.

---

## Preferences Output — `ai_constraints.agentic`

Category G answers are stored in `preferences.json` → `ai_constraints.agentic`:

```json
{
  "ai_constraints": {
    "agentic": {
      "migration_approach": "retarget|harness|strands|undecided",
      "memory_requirement": "none|session|cross_session",
      "task_duration": "quick|medium|long|very_long",
      "incremental_migration": true
    }
  }
}
```

**Field contract (consumed by Design phase):**

- `migration_approach` — Routes Design to the correct path: `"retarget"` uses existing model-swap flow, `"harness"` loads `vendored/ai/design-ref-harness.md`, `"strands"` loads `vendored/ai/design-ref-agentic-to-agentcore.md`
- `memory_requirement` — Determines whether AgentCore Memory is included in design
- `task_duration` — Determines AgentCore Runtime recommendation and session limit warnings
- `incremental_migration` — Determines whether incremental migration artifacts are generated

## Status — build step 5 (restructure)

Implemented. Frontmatter and fragment framing added for consistency with the other
`clarify-*.md` fragments; no change to firing rules, question text, defaults, or
interpretation. The wizard path's presentation moved to `clarify-assemble.md`; the Full Flow
("ask me everything") variant continues to present these questions directly, unchanged, as
documented in `clarify.md`.
