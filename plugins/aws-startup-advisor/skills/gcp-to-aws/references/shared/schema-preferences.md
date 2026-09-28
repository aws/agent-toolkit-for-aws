# Schema: preferences.json

Clarify phase output. Consumed by Design, Estimate, and Generate (report Appendix `appendix-config`).

---

## Wrapper object (required fields)

Every key in `design_constraints`, `ai_constraints`, and `startup_constraints` (when present) MUST be an object with:

| Field                | Type   | Required | Description                                                                                                                                                                                                                            |
| -------------------- | ------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `value`              | any    | yes      | Interpreted constraint value (same types as before)                                                                                                                                                                                    |
| `chosen_by`          | string | yes      | `"user"` \| `"default"` \| `"extracted"` \| `"derived"`                                                                                                                                                                                |
| `prompt`             | string | yes      | Question shown to the user, or a short detection label when skipped                                                                                                                                                                    |
| `design_consequence` | string | yes      | One sentence: how this choice shaped the AWS design, estimate, or plan                                                                                                                                                                 |
| `question_id`        | string | no       | Catalog ID (`Q1`–`Q27`) when mapped; omit for derived unions                                                                                                                                                                           |
| `source`             | string | no       | Raw provenance signal. Required when `chosen_by` is `"extracted"` (prefix `terraform:`, `billing:`, `code:`, `inventory:`, `ai-profile:`, or artifact filename) or `"default"` (`"default:<Qid>"`). Omit for `"user"` and `"derived"`. |

**Do not write null values.** Omit keys that produce no constraint.

### `prompt` by `chosen_by`

| `chosen_by` | `prompt` content                                                                               |
| ----------- | ---------------------------------------------------------------------------------------------- |
| `user`      | Verbatim question text from the active category file (blockquote body, without answer options) |
| `extracted` | Detection label, e.g. `"Detected: Cloud SQL ZONAL → single-AZ availability"`                   |
| `default`   | Question text + `" (default applied)"`                                                         |
| `derived`   | `"Derived from detected capabilities and your answers"` or the specific derivation rule        |

### `design_consequence`

Use the **Recommendation Impact** row for the selected answer from the category file when the user answered. For extracted/default/derived, use the catalog below or synthesize one sentence tied to the actual `value`.

---

## Top-level shape

```json
{
  "metadata": { "...": "..." },
  "design_constraints": { "<key>": { "value", "chosen_by", "prompt", "design_consequence", "question_id?", "source?" } },
  "ai_constraints": { "...": "..." },
  "startup_constraints": { "...": "..." }
}
```

`ai_constraints` omitted when no AI artifacts. `startup_constraints` optional (Q27).

---

## Constraint catalog (prompt + consequence templates)

Use when assembling Step 5. Replace `[value]` with the interpreted constraint.

| Key                         | `question_id`      | Default `prompt` (user-asked)                                      | `design_consequence` template                                                                                                                                                                                                                                           |
| --------------------------- | ------------------ | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `target_region`             | Q1                 | Where are your users located?                                      | All resources deploy in `[value]`; Bedrock model availability checked for this region                                                                                                                                                                                   |
| `compliance`                | Q2 (AI-only: Q1.5) | Do you have any compliance or regulatory requirements?             | `[value]` drives baseline controls (CloudTrail, Config, Security Hub) and eligible regions; AI-only path additionally gates Bedrock models/regions (design-ai Step 0.7). `["unknown"]` = not confirmed: no-constraint for service selection, but report caveat required |
| `gcp_monthly_spend`         | Q3                 | Approximately how much are you spending on GCP per month in total? | `[value]` band sets dev-tier sizing baseline and credits eligibility context                                                                                                                                                                                            |
| `funding_stage`             | Q4                 | What is your funding stage?                                        | `[value]` informs Activate credits tier guidance                                                                                                                                                                                                                        |
| `availability`              | Q6                 | What level of uptime does your application require?                | `[value]` drives RDS single-AZ vs Multi-AZ vs Aurora selection                                                                                                                                                                                                          |
| `cutover_strategy`          | Q7                 | When can you accept downtime for cutover?                          | `[value]` sets phased cutover windows and rollback timing in the migration plan                                                                                                                                                                                         |
| `kubernetes`                | Q8                 | How do you feel about Kubernetes?                                  | `[value]` selects EKS vs ECS Fargate vs mixed posture                                                                                                                                                                                                                   |
| `cloud_run_traffic_pattern` | Q10                | How does traffic to your Cloud Run services vary?                  | `[value]` drives Fargate hours / scaling estimate                                                                                                                                                                                                                       |
| `cloud_run_monthly_spend`   | Q11                | Roughly how much do you spend on Cloud Run per month?              | `[value]` cross-checks compute cost model                                                                                                                                                                                                                               |
| `database_traffic`          | Q12                | How does database traffic vary?                                    | `[value]` influences RDS instance class and autoscaling assumptions                                                                                                                                                                                                     |
| `db_io_workload`            | Q13                | What is your database I/O intensity?                               | `[value]` affects storage IOPS and instance tier                                                                                                                                                                                                                        |
| `db_size`                   | Q13b               | What is your database size?                                        | `[value]` selects pg_dump vs pgcopydb vs DMS and storage allocation                                                                                                                                                                                                     |
| `ai_framework`              | Q14                | Which AI frameworks are you using?                                 | `[value]` determines migration effort (retarget vs Harness vs Strands)                                                                                                                                                                                                  |
| `ai_monthly_spend`          | Q15                | Approximately how much do you spend on AI/ML per month?            | `[value]` band sets token volume and model tier assumptions                                                                                                                                                                                                             |
| `ai_priority`               | Q16                | What matters most for your AI workloads?                           | `[value]` drives Bedrock model selection (quality vs cost vs latency)                                                                                                                                                                                                   |
| `ai_critical_feature`       | Q17                | Which AI capability is most critical?                              | `[value]` gates model shortlist and capability validation                                                                                                                                                                                                               |
| `ai_token_volume`           | Q18                | What is your token volume and cost sensitivity?                    | `[value]` sets usage projection and optimization levers                                                                                                                                                                                                                 |
| `ai_model_baseline`         | Q19                | What is your primary production model today?                       | `[value]` is the quality/latency baseline for Bedrock comparison                                                                                                                                                                                                        |
| `ai_vision`                 | Q20                | What input types does your AI use?                                 | `[value]` requires vision-capable Bedrock models when not text-only                                                                                                                                                                                                     |
| `ai_latency`                | Q21                | How important is AI response latency?                              | `[value]` adds P95 latency success criteria and model filtering                                                                                                                                                                                                         |
| `ai_complexity`             | Q22                | How complex are your AI tasks?                                     | `[value]` affects recommended model size and agentic path                                                                                                                                                                                                               |
| `startup_program_status`    | Q27 (AI-only: Q11) | Are you eligible for AWS startup programs?                         | `[value]` triggers Activate credits callout in report and docs                                                                                                                                                                                                          |
| `ai_capabilities_required`  | —                  | Derived from detected capabilities and your answers                | Union of required capabilities (`[value]`) enforced in Bedrock model mapping                                                                                                                                                                                            |

---

## Report consumption (`appendix-config`)

Generate phase reads **every** constraint object and renders:

| Column                | Source                                                                  |
| --------------------- | ----------------------------------------------------------------------- |
| Question / assumption | `prompt`                                                                |
| Your choice           | formatted `value`                                                       |
| Source                | `chosen_by` → User answer / Extracted / Default / Derived               |
| Source signal         | `source` (only for Extracted/Default rows; omit column cell for others) |
| Design consequence    | `design_consequence`                                                    |

Sort rows: user-answered first, then extracted, then default, then derived. Include `startup_constraints` when present. Rows where `source` starts with `"default:"` are unverified assumptions — render in a visually distinct style.

If legacy `preferences.json` lacks `prompt` / `design_consequence` (pre-schema-extension runs), fall back to the catalog table above keyed by constraint name — do not leave the appendix empty.

---

## Validation (Clarify Step 5 self-check)

Before marking Clarify complete:

1. Every written constraint has `value`, `chosen_by`, `prompt`, and `design_consequence`.
2. No empty strings for `prompt` or `design_consequence`.
3. `question_id` present when the constraint maps to a catalog question.
4. `source` present on every constraint where `chosen_by` is `"extracted"` or `"default"`. Omit for `"user"` and `"derived"`.
