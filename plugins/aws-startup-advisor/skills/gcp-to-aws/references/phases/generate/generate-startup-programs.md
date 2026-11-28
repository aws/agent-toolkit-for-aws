# Generate: STARTUP_PROGRAMS.md

Loaded by `generate.md` Stage 2. Moved here from the former AI migration plan file when the AI track moved to bedrock-migration-assessment.

Always generate `$MIGRATION_DIR/STARTUP_PROGRAMS.md` when `preferences.json` contains `ai_monthly_spend` or `startup_program_status`. This artifact summarizes applicable AWS startup programs based on `startup_program_status` (bedrock-migration-assessment Clarify Q11, merged into `preferences.json` by the AI handoff) and workload type — **not** GCP or AI spend bands alone.

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
- Only include the Generative AI Accelerator section when `ai_monthly_spend` is `"$2K-$10K"` or `">$10K"` AND `ai-workload-profile.json` has `agentic_profile.is_agentic == true`
- If `startup_program_status.value == "has_credits"`: replace the "Apply for AWS Activate" steps with "You already have AWS Activate credits — ensure they are applied to your account before running terraform apply"
- If `startup_program_status.value == "unknown"`: **never** write `your status: eligible_founders`, `your status: eligible_portfolio`, or "Eligible Founders tier" in this file or the migration report — use neutral copy per the `unknown` branch above
- If `startup_program_status.value == "eligible_founders"`: may recommend Founders specifically; still mention Portfolio exists for VC-backed teams
- If `startup_program_status.value == "eligible_portfolio"`: may recommend Portfolio specifically; still mention Founders for self-funded teams
- Do NOT include any credit amounts not sourced from official AWS pages (aws.amazon.com)
- Do NOT reference MAP, IW Migrate, or ISV Workload Migration Program — these are enterprise/partner programs, not startup self-service paths
- After writing, run `scripts/validate-startup-program-artifacts.py` with `--migration-dir $MIGRATION_DIR` (see `validate-artifacts.md` check 16)
