# Generate Phase: AI Migration Plan

> Loaded by generate.md when estimation-ai.json exists.

**Execute ALL steps in order. Do not skip or optimize.**

## Prerequisites

Read from `$MIGRATION_DIR/`:

- `aws-design-ai.json` (REQUIRED) — AI architecture design from Phase 3
- `estimation-ai.json` (REQUIRED) — AI cost estimates from Phase 4
- `ai-workload-profile.json` (REQUIRED) — AI workload profile from Phase 1
- `preferences.json` (REQUIRED) — User migration preferences from Phase 2

If any required file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

## Part 1: Fast-Track Timeline

Check `preferences.json` → `ai_constraints.ai_framework` to determine the migration path. Describe effort by MECHANISM (what changes, how many files/lines) and duration by PHASE SEQUENCE — never calendar week/hour estimates (uncalibrated; see `shared/migration-complexity.md` § Provenance):

**Gateway users (config-only path — shortest)** — `ai_framework` includes `llm_router`, `api_gateway`, `voice_platform`, or `framework`:

| Gateway Type                      | Migration Action                                              | Effort            |
| --------------------------------- | ------------------------------------------------------------- | ----------------- |
| LLM Router (LiteLLM, OpenRouter)  | Change model string to `bedrock/<model_id>`                   | 1 config line     |
| API Gateway (Kong, Apigee)        | Add Bedrock upstream + SigV4 signing                          | 1-2 config files  |
| Voice Platform (Vapi, Bland.ai)   | Check native Bedrock support, update dashboard                | Dashboard config  |
| Framework (LangChain, LlamaIndex) | Swap provider import (e.g., `ChatBedrock` for `ChatVertexAI`) | 1-5 lines of code |

**OpenAI SDK users via Mantle (config path for a Responses source; small reshape for a Chat Completions source)** — `ai_framework` = `direct` AND `ai_source` = `openai` AND `migration_path` **starts with** `mantle` (`mantle`, `mantle_openai_responses`):

- Point the client at `https://bedrock-mantle.{region}.api.aws/openai/v1` — note the `openai/v1` segment for proprietary GPT models; a bare `/v1` 404s
- Swap the credential for a Bedrock API key or the auto-refreshing token provider — **not** the existing OpenAI key
- Update the model string to the Bedrock model ID (`openai.gpt-*` for a same-model move)
- Grant the `bedrock-mantle:*` actions; `bedrock:InvokeModel` does not authorize these models
- **Config-only ONLY if the source already calls `responses.create`.** A Chat Completions source must reshape to Responses — small and mechanical, but it is a code change, so do not present this path as "no code changes" without checking the detected surface
- Test in staging, validate responses

Match the `migration_path` prefix, not the exact string: Design writes the more specific `mantle_openai_responses` for a same-model OpenAI migration, and an equality test against `mantle` would misroute those runs into the adapter path below.

**Direct SDK users (adapter path — the long pole)** — `ai_framework` = `direct` AND (`ai_source` != `openai` OR `migration_path` = `converse`):

- **Phase 1:** Enable Bedrock access, create IAM role, develop provider adapter with feature flag, unit test
- **Phase 2:** Deploy to staging, run A/B comparison, measure latency/quality/cost, tune prompts
- **Phase 3:** Gradual rollout (10% → 50% → 100%), monitor, disable source provider after 48h stable

**Duration drivers:** multiple models (adapter + evaluation per model), framework integration, custom inference pipeline (the longest driver), and — when alongside infra migration — alignment with the infra deployment stage.

---

## Part 2: Step-by-Step Migration Guide

Based on `ai-workload-profile.json` → `integration.pattern` and `integration.languages`, generate SDK migration examples.

**Migration patterns to include (matched to detected language and source):**

| Source SDK              | Target                            | Key Change                                                                                                                                                                                             |
| ----------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| OpenAI SDK (same model) | Mantle Responses API              | Base URL → `.../openai/v1`, Bedrock token/API key (not an OpenAI key), `openai.gpt-*` model ID. Config-only **if** already on `responses.create`; a Chat Completions source must reshape to Responses. |
| Vertex AI (Python)      | boto3 Bedrock Converse API        | `GenerativeModel.generate_content()` → `bedrock.converse()`                                                                                                                                            |
| Vertex AI (JS)          | @aws-sdk/client-bedrock-runtime   | `model.generateContent()` → `client.send(new ConverseCommand())`                                                                                                                                       |
| Vertex AI (Go)          | aws-sdk-go-v2 bedrockruntime      | `aiplatform` → `bedrockruntime.Converse()`                                                                                                                                                             |
| Vertex AI (Java)        | AWS SDK BedrockRuntimeClient      | `GenerativeModel` → `BedrockRuntimeClient.converse()`                                                                                                                                                  |
| OpenAI SDK              | boto3 Bedrock Converse API        | `client.chat.completions.create()` → `bedrock.converse()` (if Mantle unavailable)                                                                                                                      |
| LiteLLM                 | LiteLLM config change             | `model="gpt-4o"` → `model="bedrock/anthropic.claude-sonnet-5"`, or keep the GPT family via the mantle endpoint when the source model is on Bedrock                                                     |
| LangChain               | langchain_aws                     | `ChatOpenAI`/`ChatVertexAI` → `ChatBedrock`                                                                                                                                                            |
| LlamaIndex              | llama_index.llms.bedrock_converse | `Vertex` → `BedrockConverse`                                                                                                                                                                           |

For each detected language and pattern, generate before/after code examples using actual model IDs from `aws-design-ai.json`.

Include streaming migration (`converse_stream`) if `capabilities_summary.streaming = true`.

Include embeddings migration (Titan Embeddings v2 via `invoke_model`) if `capabilities_summary.embeddings = true`.

---

## Part 3: Rollback Plan

**Feature flag strategy:** `AI_PROVIDER` env var controls routing:

- `vertex_ai` (default) — existing provider
- `bedrock` — switch to Bedrock
- `shadow` — send to both, return source response (for comparison)

**Rollback triggers:** quality below threshold, P95 latency > 2x baseline, error rate > 1% for 5 min, cost per request > 3x source.

**Rollback steps:** Set `AI_PROVIDER=vertex_ai` (instant), verify source traffic, monitor 1 hour, investigate, re-attempt.

---

## Part 4: Monitoring and Observability

**Key metrics and alert thresholds:**

| Metric            | Alert Threshold                | Severity |
| ----------------- | ------------------------------ | -------- |
| Error rate        | > 5% for 2 min → auto-rollback | Critical |
| Latency P95       | > 3x baseline for 5 min        | High     |
| Daily cost        | > 2x projected                 | Medium   |
| Token usage trend | > 120% of estimate             | Low      |
| Response quality  | < 90% of source score          | High     |

**Dashboard panels:** Request volume by provider, latency comparison (P50/P95/P99), error rates, token usage, cost tracking, quality scores.

---

## Part 5: Production Readiness Checklist

- [ ] Bedrock model access enabled
- [ ] IAM role with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`
- [ ] Provider adapter deployed and tested in staging
- [ ] A/B test with >= 100 representative prompts
- [ ] Response quality >= 90% of source baseline
- [ ] Latency P95 within 2x of source baseline
- [ ] Error rate < 0.1% in staging
- [ ] Monitoring dashboards and alerting active
- [ ] Rollback procedure documented and tested
- [ ] Cost estimates validated against staging usage

---

## Part 6: Success Criteria

| Category | Criteria            | Target                             |
| -------- | ------------------- | ---------------------------------- |
| Quality  | Response quality    | >= 90% of source baseline          |
| Quality  | Capability coverage | 100% of `ai-workload-profile.json` |
| Latency  | P50                 | Within 1.5x of source              |
| Latency  | P95                 | Within 2x of source                |
| Cost     | Monthly             | Within 20% of `estimation-ai.json` |
| Cost     | Per request         | Within 30% of source per-request   |

---

## Output

Write `generation-ai.json` to `$MIGRATION_DIR/`.

**Schema — top-level fields:**

| Field                            | Type   | Description                                                                                      |
| -------------------------------- | ------ | ------------------------------------------------------------------------------------------------ |
| `phase`                          | string | `"generate"`                                                                                     |
| `generation_source`              | string | `"ai"`                                                                                           |
| `timestamp`                      | string | ISO 8601                                                                                         |
| `migration_plan`                 | object | `duration_drivers[]`, `approach`, `phases[]` (name, sequence, activities), `models_to_migrate[]` |
| `step_by_step_guide`             | object | `languages[]`, `primary_pattern`, `files_to_modify[]`, `dependency_changes`                      |
| `rollback_plan`                  | object | `mechanism`, `flag_name`, `default_value`, `rollback_time`, `triggers[]`                         |
| `monitoring`                     | object | `dashboards[]`, `alerting_rules[]` (severity, condition, action)                                 |
| `production_readiness_checklist` | array  | String checklist items (at least 5)                                                              |
| `success_criteria`               | object | `quality`, `latency`, `cost` sub-objects with targets                                            |
| `recommendation`                 | object | `approach`, `confidence`, `key_risks[]`                                                          |

## Validation Checklist

- [ ] `migration_plan.models_to_migrate` covers all models from `aws-design-ai.json`
- [ ] `step_by_step_guide.languages` matches `ai-workload-profile.json` languages
- [ ] `step_by_step_guide.files_to_modify` matches `aws-design-ai.json` code_migration
- [ ] `rollback_plan.mechanism` is `"feature_flag"`
- [ ] `success_criteria` covers quality, latency, and cost

## Generate Phase Integration

The parent orchestrator (`generate.md`) uses `generation-ai.json` to:

1. Gate Stage 2 artifact generation — `generate-artifacts-ai.md` requires this file
2. Provide AI migration context to `generate-artifacts-docs.md` for MIGRATION_GUIDE.md
3. Set phase completion status in `.phase-status.json`

## Part 7: Generate STARTUP_PROGRAMS.md

Always generate `$MIGRATION_DIR/STARTUP_PROGRAMS.md` when `preferences.json` contains `ai_monthly_spend` or `startup_program_status`. This artifact summarizes applicable AWS startup programs based on **Q27** (`startup_program_status`) and workload type — **not** GCP or AI spend bands alone.

**Content rules (all amounts from AWS official sources only):**

```markdown
# AWS Startup Programs for Your Migration

Based on your migration profile, here are the AWS programs most relevant to you.
Credits apply to Bedrock usage (Claude, Llama, Nova, and other third-party models).

## AWS Activate Credits

AWS Activate provides promotional credits to offset AWS costs including Amazon Bedrock.
Apply at: https://aws.amazon.com/startups/credits/

### Which tier applies to you

| Your situation                          | Package                     | Credits        | How to apply                                                           |
| --------------------------------------- | --------------------------- | -------------- | ---------------------------------------------------------------------- |
| Self-funded, no VC/accelerator          | Activate Founders           | Up to $5,000   | Apply directly at aws.amazon.com/startups/credits — no Org ID needed   |
| VC or accelerator-backed (pre-Series B) | Activate Portfolio          | Up to $200,000 | Get your Activate Provider Org ID from your VC/accelerator, then apply |
| Ready to scale post-Activate-Portfolio  | AWS Credits for AI Startups | $200,000+      | Invite-only — talk with your AWS Account Manager                       |

**Activate eligibility (Founders & Portfolio):** Pre-Series B, founded in the last 10 years, AWS Account on Paid Tier Plan, and either new to Activate Credits or requesting more credits than previously received.
Credits expire within 1–2 years. Apply when you're ready to ramp up AWS usage.

[Conditional — only if ai_monthly_spend is "$2K-$10K" or ">$10K" AND agentic_profile.is_agentic == true:]

## AWS Generative AI Accelerator

An adjacent cohort program for agentic AI startups, distinct from the AWS Activate credits-hub funnel above. Highly selective. The 2025 global cohort selected 40 startups; consult the program page for the next cohort cycle.

- **Credits:** Up to $1,000,000 in AWS credits
- **Program:** 8-week cohort with mentorship, technical support, and go-to-market resources
- **Best for:** Startups with production agentic workloads and significant AI spend
- **Apply:** https://aws.amazon.com/startups/generative-ai/accelerator/

[End conditional]

### Your profile

[Conditional block — render exactly one branch from `startup_program_status.value` inside the generated file:]

- **`eligible_founders`:** **Startup status:** eligible for **Activate Founders** (self-funded / pre-VC, not yet applied). **Recommended action:** Apply for Activate Founders ($5,000) before ramp-up.
- **`eligible_portfolio`:** **Startup status:** likely eligible for **Activate Portfolio** (VC/accelerator-backed, not yet applied). **Recommended action:** Get Activate Provider Org ID from your investor, then apply.
- **`has_credits`:** **Startup status:** AWS Activate credits already on account. **Recommended action:** Confirm credits are active before `terraform apply`.
- **`unknown`:** **Startup status:** not confirmed in Clarify. **Recommended action:** Review both tiers above; self-funded → Founders, VC/accelerator-backed → Portfolio. Do **not** label a single tier as "yours" until confirmed.

- **AI monthly spend:** [from `ai_monthly_spend`]

## How to use credits during this migration

1. Apply for AWS Activate **before** running `terraform apply` — credits apply automatically to new charges
2. Credits cover eligible AWS services including Fargate, Aurora, S3, CloudWatch, and Bedrock models (both Amazon first-party and third-party foundation models)
3. **Credits do NOT cover upfront Savings Plans or Reserved Instance fees.** If the Estimate phase recommended Savings Plans for cost optimization, those commitments must be paid separately — credits apply to on-demand usage only.
4. Monitor your balance: AWS Console → Billing → Credits
5. Credits do not apply retroactively — apply before incurring costs

## Next steps

- [ ] Apply for AWS Activate at https://aws.amazon.com/startups/credits/
- [ ] If VC/accelerator-backed: get your Activate Provider Org ID from your investor
- [ ] Apply credits before running terraform apply
      [- [ ] Apply for AWS Generative AI Accelerator: https://aws.amazon.com/startups/generative-ai/accelerator/ (if agentic and high spend)]
```

**Generation rules:**

- Always include the Activate decision table (both Founders and Portfolio rows).
- Only include the Generative AI Accelerator section when `ai_monthly_spend` is `"$2K-$10K"` or `">$10K"` AND `agentic_profile.is_agentic == true`
- If `startup_program_status.value == "has_credits"`: replace the "Apply for AWS Activate" steps with "You already have AWS Activate credits — ensure they are applied to your account before running terraform apply"
- If `startup_program_status.value == "unknown"`: **never** write `your status: eligible_founders`, `your status: eligible_portfolio`, or "Eligible Founders tier" in this file or the migration report — use neutral copy per the `unknown` branch above
- If `startup_program_status.value == "eligible_founders"`: may recommend Founders specifically; still mention Portfolio exists for VC-backed teams
- If `startup_program_status.value == "eligible_portfolio"`: may recommend Portfolio specifically; still mention Founders for self-funded teams
- Do NOT include any credit amounts not sourced from official AWS pages (aws.amazon.com)
- Do NOT reference MAP, IW Migrate, or ISV Workload Migration Program — these are enterprise/partner programs, not startup self-service paths
- After writing, run `scripts/validate-startup-program-artifacts.py` with `--migration-dir $MIGRATION_DIR` (see `validate-artifacts.md` check 16)
