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
| `question_id`        | string | no       | Catalog ID (`Q1`–`Q13b`) when mapped; omit for derived unions                                                                                                                                                                           |
| `source`             | string | no       | Raw provenance signal. Required when `chosen_by` is `"extracted"` (prefix `terraform:`, `billing:`, `code:`, `inventory:`, `ai-profile:`, or artifact filename) or `"default"` (`"default:<Qid>"`). Omit for `"user"` and `"derived"`. |

**Do not write null values.** Omit keys that produce no constraint.

For `gcp_monthly_spend`, `cloud_run_monthly_spend`, and `cud_status`, the string
`"unknown"` records an explicit unknown answer without inventing a fact.
Retain `chosen_by: "user"` when the user said they do not know. Consumers must
not convert unknown spend to zero, a default monetary band, or a measured bill.

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
  "design_constraints": {
    "<key>": {
      "value": "<answer or default>",
      "chosen_by": "user|default|extracted|derived",
      "prompt": "<question text shown>",
      "design_consequence": "<one line: what this decides>",
      "question_id": "<Qn — optional>",
      "source": "<provenance — optional>"
    }
  },
  "ai_constraints": { "...": "..." },
  "startup_constraints": { "...": "..." },
  "sizing_exemptions": ["1000000000000000001", "acme-prod:orders-db"]
}
```

`ai_constraints` and `startup_constraints` appear only after the AI handoff merged them from bedrock-migration-assessment.
`sizing_exemptions` optional (Q-E0 veto in `clarify-assemble.md`): resources the user named as
having a known upcoming load change, resolved by Clarify to a GCE `config.id` **string** or a
Cloud SQL `"<project>:<name>"` key — never a display name. Design keeps each at its declared size
with `declared_reason: "user_exempt"`. Omit the key when nothing was named; never write an empty
array in place of "no exemptions".

---

## Constraint catalog (prompt + consequence templates)

Use when assembling Step 5. Replace `[value]` with the interpreted constraint.

| Key                         | `question_id`      | Default `prompt` (user-asked)                                      | `design_consequence` template                                                                                                                                                                                                                                           |
| --------------------------- | ------------------ | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `target_region`             | Q1                 | Where are your users located?                                      | All resources deploy in `[value]`; Bedrock model availability checked for this region                                                                                                                                                                                   |
| `compliance`                | Q2 (AI-only: Q1.5) | Do you have any compliance or regulatory requirements?             | `[value]` drives baseline controls (CloudTrail, Config, Security Hub) and eligible regions; AI-only path additionally gates Bedrock models/regions (design-ai Step 0.7). `["unknown"]` = not confirmed: no-constraint for service selection, but report caveat required |
| `cost_optimization`         | Q-E0               | How aggressively should we right-size your AWS design versus your current capacity? | `[value]` (`conservative` / `balanced` / `aggressive`) sets whether Compute Engine and Cloud SQL are sized from measured Cloud Monitoring utilization (`design-refs/compute.md` § Measured sizing) and the step cap below like-for-like; changes nothing without utilization data |
| `gcp_monthly_spend`         | Q3                 | Approximately how much are you spending on GCP per month in total? | `[value]` band sets dev-tier sizing baseline and credits eligibility context                                                                                                                                                                                            |
| `funding_stage`             | Q4                 | What is your funding stage?                                        | `[value]` informs Activate credits tier guidance                                                                                                                                                                                                                        |
| `availability`              | Q6                 | What level of uptime does your application require?                | `[value]` drives RDS single-AZ vs Multi-AZ vs Aurora selection                                                                                                                                                                                                          |
| `cutover_strategy`          | Q7                 | When can you accept downtime for cutover?                          | `[value]` sets phased cutover windows and rollback timing in the migration plan; `zero-downtime` also makes Generate print the named HOLD `zero-downtime-requested` (GCP-local reason code) and require `ACCEPT_OFFLINE_DOWNTIME=yes` for the offline copy                                                                                                                                                                                         |
| `kubernetes`                | Q8                 | How do you feel about Kubernetes?                                  | `[value]` selects EKS vs ECS Fargate vs mixed posture                                                                                                                                                                                                                   |
| `cloud_run_traffic_pattern` | Q10                | How does traffic to your Cloud Run services vary?                  | `[value]` drives Fargate hours / scaling estimate                                                                                                                                                                                                                       |
| `release_strategy`          | Q10b               | How do you release new versions of your containerized services?    | `[value]` selects ECS Express Mode (`canary`) or a standard ECS service (`rolling` / `blue_green`) for Fargate web services |
| `compute_shape`             | Q10c               | Does this service receive HTTP(S) traffic through a load balancer? | `[value]` per service (`http_service` / `worker` / `tcp_or_grpc_passthrough`) gates ECS Express Mode eligibility; recorded only when the inventory cannot derive it |
| `cloud_run_monthly_spend`   | Q11                | Roughly how much do you spend on Cloud Run per month?              | `[value]` cross-checks compute cost model                                                                                                                                                                                                                               |
| `database_traffic`          | Q12                | How does database traffic vary?                                    | `[value]` influences RDS instance class and autoscaling assumptions                                                                                                                                                                                                     |
| `db_io_workload`            | Q13                | What is your database I/O intensity?                               | `[value]` affects storage IOPS and instance tier                                                                                                                                                                                                                        |
| `db_size`                   | Q13b               | What is your database size?                                        | `[value]` selects pg_dump vs pgcopydb and storage allocation; `>500GB` and `unknown` make Generate mark the data step HOLD (DMS is not generated)                                                                                                                                                                                                     |

The `ai_constraints` and `startup_constraints` keys are not in this catalog: bedrock-migration-assessment's Clarify writes them (its own `references/shared/schema-preferences.md` catalog), and `bma-handoff.py accept` merges them into this file (`references/shared/ai-handoff.md`).

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
