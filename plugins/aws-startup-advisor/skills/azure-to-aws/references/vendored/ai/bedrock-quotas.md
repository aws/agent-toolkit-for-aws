# Bedrock Quota Awareness — Migration Decision Logic

> Canonical Bedrock TPM/RPM quota-risk logic. Source-cloud agnostic: quotas are
> an AWS-account property, assessed from token volume and target model alone.
> Vendored into each consuming skill as
> `references/vendored/ai/bedrock-quotas.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.

For raw quota documentation, use the AWS MCP Server's `aws___search_documentation` / `aws___read_documentation` tools or see: [Quotas for Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html) | [How tokens are counted](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html)

---

## Why This Matters for Migrations

OpenAI and Gemini APIs have high default rate limits for paying customers (OpenAI Tier 4/5: 2M+ TPM). Bedrock default quotas start lower and scale with account history. The quota risk assessment below works **without an AWS account** — it uses the user's current token volume and selected model to flag whether a quota increase will be needed, so teams can plan the request into their migration timeline.

---

## The 5× Burndown Trap

Claude models (3.7+) on Bedrock consume quota at **5× the rate for output tokens**. This is the single most common surprise for teams migrating from OpenAI (which has no output multiplier).

**Effective TPM by workload type** (at 200K TPM quota on Claude):

| Workload Type      | Input:Output Ratio | Effective TPM | vs OpenAI 2M TPM           |
| ------------------ | ------------------ | ------------- | -------------------------- |
| RAG / long context | 80:20              | ~111K         | Need 18× increase to match |
| Balanced chat      | 60:40              | ~77K          | Need 26× increase to match |
| Code generation    | 20:80              | ~48K          | Need 42× increase to match |

Formula: `Effective TPM = TPM_quota / (input_ratio + output_ratio × 5)`

Nova, Llama, DeepSeek, and Mistral models have **1× burndown** (no multiplier). Output-heavy workloads that hit Claude quota limits may benefit from routing to these models for applicable tasks.

---

## Quota Risk Assessment

Apply during Design phase after model selection. Uses `ai_token_volume` from `preferences.json` and the selected model family.

| `ai_token_volume`         | Model Family                       | `quota_risk` | Surface to User                                                               |
| ------------------------- | ---------------------------------- | ------------ | ----------------------------------------------------------------------------- |
| `"high"` or `"very_high"` | Any                                | `"high"`     | "Request Bedrock quota increase before migration (allow 1–5 business days)"   |
| `"medium"`                | Claude (5× burndown)               | `"medium"`   | "Monitor TPM usage during parallel run; quota increase may be needed at peak" |
| `"medium"`                | Nova / Llama / other (1× burndown) | `"low"`      | No action                                                                     |
| `"low"`                   | Any                                | `"low"`      | No action                                                                     |

Include `quota_risk` in `aws-design-ai.json` → `ai_architecture`.

---

## `max_tokens` Reservation Trap

Bedrock deducts `max_tokens` from TPM quota **at request start**, before any tokens are generated. Unused quota is returned after response completes.

If code sets `max_tokens: 4096` (common OpenAI default) but typical responses are 200 tokens, each request reserves 20× more quota than needed — dramatically reducing concurrency.

**Migration action:** Set `max_tokens` to ~1.5× expected output length. This is a code change that should be flagged in the migration guide when `quota_risk` is `"medium"` or `"high"`.

---

## Cross-Region Inference as Quota Mitigation

Cross-region inference (CRIS) profiles have **separate, higher quotas** because traffic distributes across multiple regions. For production migrations with `quota_risk` = `"high"`:

- Recommend CRIS as the default deployment mode
- No code changes required (use the CRIS inference profile ID instead of the regional model ID)
- Trade-off: slightly higher latency variance, ~10% price premium in some regions

---

## Pre-Migration Quota Checklist

Surface these items in the production readiness checklist (generate phase) when `quota_risk` ≥ `"medium"`:

- [ ] Quota risk assessed (this can be done before having an AWS account — it's based on token volume and model selection)
- [ ] AWS account created and Bedrock model access enabled in target region
- [ ] Current TPM quota checked via Service Quotas console for target model + region
- [ ] Quota increase requested if peak TPM exceeds default (allow 1–5 business days)
- [ ] `max_tokens` set to ~1.5× expected output (not model maximum)
- [ ] Cross-region inference profile evaluated for high-volume workloads
- [ ] Retry configuration uses adaptive mode (`botocore.config.Config(retries={"mode": "adaptive"})`)
- [ ] CloudWatch alarm configured on `ThrottlingException` metric > 0

---

## How to Request a Quota Increase

Include this guidance in migration artifacts when `quota_risk` ≥ `"medium"`. Users may not have an AWS account yet when the plugin assesses risk — these instructions tell them what to do once they do.

**Where:** AWS Console → Service Quotas → Amazon Bedrock → search for the model name (e.g., "Claude Sonnet 4" or "tokens per minute")

**What to request:**

- Find the quota named like: `Tokens per minute for [Model Name]` or `Cross-region model inference tokens per minute for [Model Name]`
- Click "Request increase at account level"
- Enter desired value based on the effective TPM calculation above

**How to calculate the target value:**

```
Target TPM = (peak_tokens_per_minute_on_source_provider) × burndown_multiplier
```

Where `burndown_multiplier` = 5 for Claude models (because output tokens consume 5× quota), 1 for all others. If the user doesn't know their peak TPM, estimate from daily volume:

```
Estimated peak TPM = (daily_tokens / active_hours / 60) × 3  (3× for peak headroom)
```

**Timeline:** Allow 1–5 business days for approval. Request increases during the setup/provisioning stage of migration, not during cutover.

**Alternative — cross-region inference:** If the increase isn't approved in time or the requested value is very high, cross-region inference profiles provide higher aggregate capacity without a quota increase request (traffic distributes across regions automatically).

---

## Integration Points

| Phase    | File                       | What to do                                                                                                    |
| -------- | -------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Design   | `design-ai.md`             | Compute `quota_risk` per table above; include in `aws-design-ai.json`                                         |
| Estimate | `estimate-ai.md`           | If `quota_risk` = `"high"`, add to `complexity_factors[]`: "Bedrock quota increase required before migration" |
| Generate | `generate-artifacts-ai.md` | Add quota check step to `setup_bedrock.sh`; include checklist items above in production readiness             |
| Generate | `generate-ai.md`           | If `quota_risk` ≥ `"medium"`, add "Request quota increase" to Week 1 activities                               |
