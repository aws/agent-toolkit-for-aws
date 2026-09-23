---
_fragment: ai
_of_phase: clarify
_contributes:
  - preferences.json (workloads[], ai_constraints, ai_* keys, startup_program_status)
---

# Clarify — AI Workloads (Categories F / G / H)

> **This fragment asks nothing.** It reads `ai-workload-profile.json`, resolves what it can,
> assigns a disposition per row, and returns rows plus the workloads confirmation table.
> `clarify-assemble.md` owns the whole conversation — it presents the assumption sheet (Gate 1),
> the ESSENTIAL questions (Gate 2), and the recap (Gate 3). Fragments never talk to the user.

Fires when `ai-workload-profile.json` exists. The Azure port of gcp's `clarify-ai.md`, adapted to
the `azure_openai | openai | anthropic | both | other` source vocabulary.

## Step 1: Extract before proposing

Read from `ai-workload-profile.json`:

| Read                                                    | From                       | Use                                                            |
| ------------------------------------------------------- | -------------------------- | -------------------------------------------------------------- |
| `summary.ai_source`                                     | summary                    | which provider migrated; personalizes wording ("Azure OpenAI") |
| `models[]`, `workloads[]`                               | top level                  | the confirmation table (Gate 1) and per-workload rows          |
| `integration.pattern`, `.gateway_type`, `.frameworks[]` | integration                | Q14 framework auto-detect                                      |
| `integration.capabilities_summary`                      | integration                | Q20 modalities                                                 |
| `agentic_profile`                                       | top level                  | whether Category G fires at all                                |
| `current_costs.monthly_ai_spend`                        | current_costs (if present) | Q15 default (else PROPOSED default)                            |

Present an **AI Context Summary** row for the assembler to show: `ai_source`, profile origin,
models detected, capabilities, integration pattern + SDK, gateway/router, frameworks.

## Step 2: The rows

### Category F — AI / Bedrock (fires when `ai-workload-profile.json` exists)

- **Q14 — AI framework / orchestration.** DETECTED from `integration` when a framework is found,
  else PROPOSED. Default `["direct"]`. → `ai_framework[]` (multi-select).
- **Q15 — Monthly AI spend.** DETECTED from `current_costs` if present, else PROPOSED. Default
  `"$500-$2K"`. → `ai_monthly_spend`.
- **Q16 — What matters most.** PROPOSED, default `"balanced"`. → `ai_priority`
  (`cost|quality|speed|balanced`).
- **Q17 — Most critical specialized feature.** PROPOSED, default none. → `ai_critical_feature`
  (e.g. `ultra_long_context`, `realtime`, `vision`, none).
- **Q18 — Usage volume + cost tolerance.** PROPOSED, default `"low"`. → `ai_token_volume`
  (`low|medium|high|very_high`). Drives the estimate token tiers.
- **Q19 — Which model do you use today.** DETECTED from `models[]` when confidence is high, else
  PROPOSED. → `ai_model_baseline`. **Azure catalog:** Azure OpenAI deployments — GPT-4o, GPT-4.1,
  GPT-4.1 mini/nano, o3, o4-mini, GPT-5.x. (No Gemini — azure has no `gemini` source.)
- **Q20 — Input modalities.** DETECTED from `capabilities_summary.vision`, else PROPOSED
  text-only. → `ai_vision`.
- **Q21 — Response speed.** PROPOSED, default `"important"`. → `ai_latency`.
- **Q22 — Task complexity.** PROPOSED, default `"moderate"`. → `ai_complexity`.

### Category G — Agentic (fires ONLY when `agentic_profile.is_agentic == true`)

Provider-agnostic; ports from gcp unchanged. Present an **Agentic Context Summary**
(framework, agents, orchestration, tools, memory, HITL), then:

- **Q23 — Migration approach.** PROPOSED, default `"undecided"`. →
  `ai_constraints.agentic.migration_approach` (`retarget|harness|strands|undecided`). This routes
  Design: `harness` → `vendored/ai/design-ref-harness.md`; `strands` →
  `vendored/ai/design-ref-agentic-to-agentcore.md`; `retarget`/`undecided` → model-swap only.
- **Q24 — Cross-session memory.** PROPOSED, default `"session"`. →
  `ai_constraints.agentic.memory_requirement` (`none|session|cross_session`).
- **Q25 — Task duration.** PROPOSED, default `"medium"`. →
  `ai_constraints.agentic.task_duration` (`quick|medium|long|very_long`).
- **Q26 — Incremental migration.** PROPOSED, default `false`. →
  `ai_constraints.agentic.incremental_migration`.

### Category H — Startup Programs (fires whenever Category F fires)

- **Q27 — AWS Activate credits.** **ESSENTIAL** — the one essential AI row. Asked in the Gate-2
  essentials batch (after Q15, and after Q26 when agentic), **never placed on the assumption
  sheet** (funding stage cannot be defaulted from spend). Default `"unknown"`. →
  `startup_program_status` (`eligible_founders|eligible_portfolio|has_credits|unknown`).

## The Multi-Workload Confirmation Table

Fires when `workloads[]` has **≥ 2 entries** — it replaces the per-workload Q16–Q22 loop with one
table the assembler presents at Gate 1:

| # | Model | SDK Method | Capability | Confidence | Proposed Bedrock Target |
| - | ----- | ---------- | ---------- | ---------- | ----------------------- |

Per row: **Accept / Edit / Drop.** High-confidence rows pre-fill the Bedrock target and skip
Q16–Q22; medium/low ask ≤ 2 questions each. The capability→target proposal uses the same mapping
`design-ai.md` will apply; traditional-AI capabilities (`document_extraction`, `image_analysis`,
`speech_transcription`) show the Azure source (Azure AI Document Intelligence / Vision / Speech)
and route to `design-refs/ai.md` (Textract / Rekognition / Transcribe), not a Bedrock model.

**REQUIRED persist (the downstream source of truth).** After confirmation, write the final
`workloads[]` to **`preferences.json`** — not `ai-workload-profile.json`. Design reads it from
`preferences.json` because Clarify may have edited, dropped, or re-confirmed rows. Each persisted
entry carries: `workload_id`, `model_id`, `sdk_method`, `capability`, `capability_confidence`,
`structured_output`, `call_sites`, `target_bedrock_model`, plus user `priority` (default
`"balanced"`) and `latency_tier` (default `"standard"`). Dropped rows are excluded. Atomic write
(`.tmp` → rename); on failure STOP. Single-workload (exactly 1) or empty: skip the table, use
Q16–Q22, and write `"workloads": []` when none.

## Step 3: Rows returned

```jsonc
{
  "ai_framework": ["direct"], // DETECTED | PROPOSED
  "ai_monthly_spend": "$500-$2K", // DETECTED | PROPOSED
  "ai_priority": "balanced", // PROPOSED
  "ai_critical_feature": null, // PROPOSED
  "ai_token_volume": "low", // PROPOSED
  "ai_model_baseline": "gpt-4o", // DETECTED | PROPOSED
  "ai_vision": false, // DETECTED | PROPOSED
  "ai_complexity": "moderate", // PROPOSED
  "startup_program_status": null, // ESSENTIAL — value null until answered (the Gate-2 completion gate)
  "ai_constraints": { // agentic block present ONLY when agentic_profile.is_agentic
    "agentic": {
      "migration_approach": "undecided",
      "memory_requirement": "session",
      "task_duration": "medium",
      "incremental_migration": false
    }
  },
  "workloads": [] // the confirmed array (persist rule above)
}
```

A value taken from its default stays **PROPOSED** — never promoted to DETECTED (DETECTED means
read from the estate; Design's rationale and the report distinguish "you chose" from "we assumed").

## Who consumes these

| Field                                                                                  | Consumer                                            |
| -------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `workloads[]`, `ai_priority`, `ai_critical_feature`, `ai_latency`, `ai_model_baseline` | `design-ai.md` model selection + override hierarchy |
| `ai_constraints.agentic.migration_approach`                                            | `design-ai.md` Step 0.6 agentic routing             |
| `ai_token_volume`, `ai_monthly_spend`                                                  | `estimate-ai.md` token tiers + ROI                  |
| `startup_program_status`, `ai_monthly_spend`                                           | `generate-artifacts-ai.md` STARTUP_PROGRAMS.md      |

## Status — build step 3 (AI route)

The AI Clarify fragment. Wired into `clarify.md` `_fragments` (`_when ai-workload-profile.json
exists`) and `clarify-assemble.md` `_reads` + `_knowledge` (schema-discover-ai.md). Its producer
`discover-app-code.md` lands in step 4; until then it fires only for an IaC-detected AI profile.
The `clarify-ai-only.md` standalone route is deferred (plan §19.9c).
