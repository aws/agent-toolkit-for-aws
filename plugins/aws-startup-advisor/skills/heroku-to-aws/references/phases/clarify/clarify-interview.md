---
_fragment: interview
_of_phase: clarify
_contributes:
  - preferences.json (interpreted answers; created here, finalized by the assembler)
---

# Clarify Phase: Adaptive Interview

> Self-contained interview sub-file. Runs the prior-run check, determines fast-path
> eligibility, selects the active question set, and presents the questions in
> progressive batches — interpreting answers into `preferences.json` fields. The
> final assembly, validation checklist, handoff gate, and phase-status update are
> owned by the assembler (`clarify-assemble.md`).

**Execute ALL steps in order. Do not skip or deviate.**

---

## Step 0: Prior Run Check

Check `$MIGRATION_DIR/` for existing state:

**Case 1 — Completed preferences exist** (`preferences.json` present):

> "I found existing migration preferences from a previous run. Would you like to:"
>
> 1. Re-use these preferences and skip questions
> 2. Start fresh and re-answer all questions

- If 1: Skip to Validation Checklist with the existing `preferences.json`.
- If 2: Delete `preferences.json`, continue to Step 1.

**Case 2 — No prior state**: Continue to Step 1.

---

## Step 1: Read Inventory and Determine Fast-Path Eligibility

Read `$MIGRATION_DIR/heroku-resource-inventory.json`. This artifact must exist (produced by Phase 1: Discover).

### Discovery Summary

Present a discovery summary:

> **Apps discovered:** [total_apps_discovered] Heroku apps
> **Resource types:** [count formations], [count addons], [count spaces], [count pipelines]
> **Top add-on services:** [list top 3–5 add-on services by frequency]
> **Heroku generation:** [Cedar/Fir/Mixed — summarize `heroku_generation` across apps]

**If `billing_profile.available == true`:**

> **Monthly Heroku spend:** $[total_monthly_cost] ([billing_period])
> **Top cost categories:** [top 3 from line_items by cost]

### Fast-Path Gate

After the Discovery Summary, evaluate fast-path eligibility:

```
IF total_apps_discovered < 5
   AND no resource with resource_type == "space" exists
   AND no resource with config.addon_service == "heroku-kafka" exists
THEN eligible for fast-path (3–5 questions)
ELSE full question flow (12–15 questions)
```

**If fast-path eligible**, present:

> "Your stack looks straightforward — [N] app(s), no Private Spaces, no Kafka.
>
> Want to use smart defaults and answer just 4–6 questions? I'll apply sensible defaults for the rest.
>
> **[Yes — short path]** / **[No — ask me everything]**"

**If user chooses Yes:**

1. Ask only: **Q1** (region), **Q2** (compliance), **Q3** (availability), **Q4** (maintenance window), **Q12c** (compute target recommendation), **Q12d** (EB deploy method, only if the resolved compute plan includes EB) — and optionally **Q11** (Fir intent, only if Fir detected).
2. Apply documented defaults for ALL other questions. Record each in `metadata.questions_defaulted`.
3. Write `preferences.json` with `metadata.clarify_mode: "fast_path"`. Skip Steps 2–3 batch loop.
4. Proceed to Step 4 (Validation Checklist).

**Fast-path default values applied when skipping questions:**

- `migration_urgency`: `routine`
- `migration_approach`: `full_cutover`
- `migration_method`: `pg_dump_restore`
- `containerization_status`: `buildpack_only`
- `database_ha`: matches Q3 availability
- `redis_ha`: `true`
- `dns_strategy`: `route53`
- `log_retention_days`: `30`
- `cost_optimization`: `balanced`
- `container_registry`: `ecr`

Users are informed: "Smart defaults applied: full cutover approach, pg_dump for database migration, routine urgency, buildpack-only containerization status. Say 'I want to change something' to override any of these."

**If user chooses No, or stack is not eligible:** Continue to Step 2.

---

## Step 2: Determine Active Questions

Before generating questions, scan the inventory to determine which questions apply:

### Conditional Question Rules

| Question                             | Condition to Include                                             | Skip When                                 |
| ------------------------------------ | ---------------------------------------------------------------- | ----------------------------------------- |
| Q1 — Target AWS region               | Always                                                           | Never                                     |
| Q2 — Compliance                      | Always                                                           | Never                                     |
| Q3 — Availability posture            | Always                                                           | Never                                     |
| Q4 — Maintenance window              | Always                                                           | Never                                     |
| Q5 — Environment naming              | Always                                                           | Never                                     |
| Q5b — Migration urgency              | Always                                                           | Never                                     |
| Q6 — Database HA                     | Postgres add-on present                                          | No Postgres in inventory                  |
| Q6b — Migration approach             | Postgres add-on present                                          | No Postgres in inventory                  |
| Q6c — DB migration method            | Postgres add-on present                                          | No Postgres in inventory                  |
| Q7 — Redis HA                        | Redis add-on present                                             | No Redis in inventory                     |
| Q8 — Kafka retention                 | Kafka add-on present                                             | No Kafka in inventory                     |
| Q9 — VPC subnet IDs                  | Private Space with peering detected BUT subnet IDs not available | No Private Space or subnets already known |
| Q9b — VPC ID                         | Peering detected but VPC ID not found in Terraform               | VPC ID already available or no peering    |
| Q10 — DNS strategy                   | Always                                                           | Never                                     |
| Q11 — Fir intent                     | At least one app has `heroku_generation == "fir"`                | No Fir-generation apps                    |
| Q12b — Containerization status       | Always                                                           | Never                                     |
| Q12c — Compute target recommendation | Always                                                           | Never                                     |
| Q12d — EB deploy method              | Resolved Q12c compute plan includes Elastic Beanstalk            | All-Fargate or all-EKS compute plan       |
| Q12 — Container registry             | Always                                                           | Never                                     |
| Q13 — Log retention                  | Always                                                           | Never                                     |
| Q14 — Alerting preference            | Always                                                           | Never                                     |
| Q15 — Cost optimization              | Always                                                           | Never                                     |

### Extraction Rules (answer from the inventory before asking)

Before planning batches, resolve what `heroku-resource-inventory.json` already answers. Extracted questions are NOT asked — they appear as **Detected** rows on the Assumption Sheet (Step 2.5) and are recorded in `metadata.questions_skipped_extracted`, with the raw signal in `metadata.inventory_clarifications`.

| Q                       | Extraction signal                                                                                                                                                                                                 | Resolves to                                                                                                                                    | When NOT to extract                                                             |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Q1 — Region             | Private Space `region` (e.g. `virginia` → `us-east-1`, `oregon` → `us-west-2`, `dublin` → `eu-west-1`, `frankfurt` → `eu-central-1`); Common Runtime apps: `us` → suggest `us-east-1`, `eu` → suggest `eu-west-1` | `global.target_region` — **Detected** for Private Spaces (explicit region); **Proposed default** for Common Runtime (a suggestion, not a fact) | Mixed regions across apps/spaces — ask Q1                                       |
| Q6 — Database HA        | Heroku Postgres plan tier: `standard-*` → no HA follower (`database_ha: false` proposed); `premium-*` / `private-*` / `shield-*` → HA included (`database_ha: true` detected)                                     | `data.database_ha`                                                                                                                             | Multiple Postgres add-ons with mixed tiers — ask Q6 with a per-add-on breakdown |
| Q7 — Redis HA           | Redis plan tier: `premium-*` and above → HA (`redis_ha: true` detected); `mini`/hobby tiers → no HA (proposed `false`)                                                                                            | `data.redis_ha`                                                                                                                                | Mixed tiers — ask Q7                                                            |
| Q12b — Containerization | App stack field: `container` stack → `containerization_status: "dockerfile"` detected; buildpack stacks (`heroku-22`, `heroku-24`) → `buildpack_only` detected                                                    | `compute.containerization_status`                                                                                                              | Mixed stacks across apps — ask Q12b                                             |

**Tier-derived HA is a strong signal, not a requirement statement:** the plan tier says what the customer HAS, not what they NEED. Present tier-derived rows on the sheet with the source shown ("your `standard-0` plan has no HA follower") so the user can correct if their target posture differs from their current one — this mirrors Q3 (availability posture), which is always asked and never extracted.

### Step 2.5: Assumption Sheet (Mandatory Gate)

**HARD GATE — do NOT ask any batch question until the user responds to this sheet.** Skip the sheet only when nothing was extracted AND no documented default applies (rare).

Present detected values and to-be-assumed defaults as one confirm-or-edit sheet:

```
### Migration assumptions — confirm or correct

**Detected from your Heroku inventory:**

| Setting | Value | Source | What it decides |
| ------- | ----- | ------ | --------------- |
| Region | us-east-1 (Private Space: virginia) | space config | All AWS resources deploy here |
| Database HA | Included (premium-0 plan) | Postgres plan tier | RDS Multi-AZ topology |
| Containerization | Buildpacks only (heroku-24) | app stack | Fargate via buildpack-to-image path |

**Assumed (documented defaults — correct anything that's wrong):**

| Setting | Assumed value | Consequence if left as-is |
| ------- | ------------- | ------------------------- |
| Migration approach | Full cutover | Single cutover event; say "interim/data-first" for phased |
| DB migration method | pg_dump/restore | Fine under ~100GB; larger needs replication tooling |
| Cost optimization | Balanced | No aggressive Spot/reservation assumptions |

Reply:
1. **Confirm all** (or "looks good") — I'll ask only the [N] remaining questions.
2. **Change a setting** — name it ("database ha: no") or describe it in plain words ("we can't take downtime") — I'll map it or ask the full question. Several fixes in one message is fine.
3. **"ask me about [setting]"** — I'll ask the full question with all options.
4. **"ask me everything"** — discard assumptions, run the full batch flow.
```

_Present these as selectable options via the structured question tool (e.g. AskUserQuestion) when the IDE provides one; otherwise the numbered list verbatim. Free-text corrections are always accepted — the menu never replaces them._

Questions resolved on the sheet (confirmed or corrected) are excluded from the batches. User corrections move the question ID from `questions_skipped_extracted`/`questions_defaulted` to `questions_asked`.

---

After determining active questions, organize them into **three progressive batches**:

| Batch | Name                      | Questions              | Content                                                                                                                                               |
| ----- | ------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1** | Global / Strategic        | Q1–Q5, Q5b, Q12c, Q12d | Region, compliance, availability, maintenance, environment naming, migration urgency, compute target recommendation, EB deploy method when applicable |
| **2** | Data / Network            | Q6, Q6b, Q6c, Q7–Q10   | Database HA, migration approach, DB migration method, Redis HA, Kafka retention, VPC subnets, DNS strategy                                            |
| **3** | Operational / Conditional | Q11, Q12b, Q12–Q15     | Fir intent, containerization status, container registry, log retention, alerting, cost optimization                                                   |

**Batch 2 is active** if ANY of: Postgres present, Redis present, Kafka present, Private Space detected, or DNS question is needed (always true → Batch 2 always fires with at least Q10).

**Batch 3 is always active** (Q12–Q15 always fire; Q11 fires only if Fir detected).

Record the ordered list of active batches and count questions per batch after filtering. **Exclude questions resolved on the Assumption Sheet** (extracted, defaulted-and-confirmed, or corrected) — batches contain only the questions the user must actually answer.

---

## Step 3: Present Questions in Progressive Batches

### Batch Loop

For each active batch, execute steps 3a–3c:

#### 3a. Present Batch

Use a conversational tone with brief context explaining why each question matters. Number questions within each batch starting from 1. **Cap each turn at 4 questions** — when a batch has more, split it and open each part with "Batch [i] of [k]". Open the first batch with: "That leaves [N] decisions only you can make — then we're ready to design." _Use the structured question tool (e.g. AskUserQuestion) when available, identical option text otherwise; shorthand answers ("1A 2C 3 skip") are accepted in either mode._

**Batch 1 — Global / Strategic (always first):**

```
Before designing your AWS architecture, I have a few sections of questions
to tailor the migration plan. You can answer each, skip individual ones
(I'll use sensible defaults), or say "use defaults for the rest" at any point.

Let's start with your strategic requirements.

--- Global / Strategic ---

[Present active questions Q1–Q5]
```

**Batch 2 — Data / Network (if active):**

```
Got it — strategic preferences saved.

Next up: [N] questions about your data services and networking.
You can answer each, skip individual ones, or say "use defaults for the rest."

--- Data / Network ---

[Present active questions Q6–Q10]
```

**Batch 3 — Operational / Conditional:**

```
[Data/Network preferences saved.]

Last section — [N] questions about operations and platform choices, then we're ready to design.
You can answer each, skip individual ones, or say "use defaults for the rest."

--- Operational / Conditional ---

[Present active questions Q11–Q15]
```

#### 3b. Wait for Response

Wait for the user's response to the current batch. Do NOT present the next batch or proceed to Design without a response or an explicit "use defaults for the rest."

**"Use defaults for the rest" handling:** If the user says this at any point:

1. Apply documented defaults for all unanswered questions in the current batch.
2. Apply documented defaults for all questions in remaining batches.
3. Record each defaulted answer with `source: "default"`.
4. Skip directly to Step 4 (write final `preferences.json`).

#### 3c. Interpret Batch Answers and Validate

For each answered question, apply the interpretation rule. For skipped questions within the batch, apply the documented default.

**Input Validation:** If the user provides a response that does not match the valid options for a question:

1. Reject the input.
2. Present an error message indicating the valid options.
3. Re-prompt the same question without advancing.

Example:

> "That's not a valid option for [question topic]. Please choose from: [list valid options]"

**Subnet ID validation (Q9):** If the user provides subnet IDs that do not match the format `subnet-[17 hex characters]`:

> "Invalid subnet ID format. Expected format: `subnet-xxxxxxxxxxxxxxxxx` (subnet- followed by 17 hexadecimal characters). Please provide 1–6 valid subnet IDs, comma-separated."

Re-prompt Q9 until valid input is provided.

**VPC ID validation (Q9b):** If the user provides a VPC ID that does not match the format `vpc-[17 hex characters]`:

> "Invalid VPC ID format. Expected format: `vpc-xxxxxxxxxxxxxxxxx` (vpc- followed by 17 hexadecimal characters). Please provide your existing AWS VPC ID."

Re-prompt Q9b until valid input is provided.

---

## Question Catalog

### Batch 1: Global / Strategic

#### Q1 — Target AWS Region

> Which AWS region should your infrastructure be deployed to?
>
> 1. us-east-1 (N. Virginia) — lowest latency to East Coast, most services available
> 2. us-west-2 (Oregon) — West Coast, good general-purpose choice
> 3. eu-west-1 (Ireland) — Europe, good for EU-based users
> 4. eu-central-1 (Frankfurt) — Central Europe, German data residency
> 5. ap-southeast-1 (Singapore) — Asia-Pacific
> 6. ap-northeast-1 (Tokyo) — Japan
> 7. Other — specify a valid AWS region code

**Interpret:**

- 1 → `target_region: "us-east-1"`
- 2 → `target_region: "us-west-2"`
- 3 → `target_region: "eu-west-1"`
- 4 → `target_region: "eu-central-1"`
- 5 → `target_region: "ap-southeast-1"`
- 6 → `target_region: "ap-northeast-1"`
- 7 → validate user-provided region code; `target_region: "<user value>"`

**Default:** 1 → `target_region: "us-east-1"`

**Valid options:** Any valid AWS region code (e.g., `us-east-1`, `eu-west-1`, `ap-southeast-2`). Reject non-existent region codes.

---

#### Q2 — Compliance Requirements

> Do you need to meet any compliance frameworks?
>
> 1. None — no specific compliance requirements
> 2. SOC 2 — service organization controls
> 3. HIPAA — healthcare data protection
> 4. PCI DSS — payment card data
> 5. Multiple — specify which ones

**Interpret:**

- 1 → `compliance: "none"`
- 2 → `compliance: "soc2"`
- 3 → `compliance: "hipaa"`
- 4 → `compliance: "pci"`
- 5 → `compliance: [user-specified array]`

**Default:** 1 → `compliance: "none"`

**Design impact:** HIPAA → BAA-eligible services only; PCI → encryption at rest and in transit mandatory; SOC 2 → audit logging required.

---

#### Q3 — Availability Posture

> What availability level does your production workload need?
>
> 1. Single-AZ — development/staging, cost-optimized (no redundancy)
> 2. Multi-AZ — production standard (automatic failover within a region)
> 3. Multi-AZ HA — mission-critical (Aurora, enhanced monitoring, aggressive failover)
> 4. Multi-Region — catastrophic tolerance (global distribution, highest cost)

**Interpret:**

- 1 → `availability: "single-az"`
- 2 → `availability: "multi-az"`
- 3 → `availability: "multi-az-ha"`
- 4 → `availability: "multi-region"`

**Default:** 2 → `availability: "multi-az"`

**Design impact:**

- `single-az` or `multi-az` → RDS PostgreSQL
- `multi-az-ha` or `multi-region` → Aurora PostgreSQL
- Applies to all data services (Postgres, Redis, Kafka broker distribution)

---

#### Q4 — Maintenance Window

> When should AWS perform maintenance operations (patches, minor upgrades)?
>
> 1. Weekday off-hours (Tue–Thu, 02:00–06:00 UTC)
> 2. Weekend early morning (Sat–Sun, 02:00–06:00 UTC)
> 3. Sunday pre-dawn (Sun 03:00–05:00 UTC) — recommended
> 4. Flexible — no preference, use AWS defaults

**Interpret:**

- 1 → `maintenance_window: {"day": "tuesday-thursday", "hour_utc": 3}`
- 2 → `maintenance_window: {"day": "saturday-sunday", "hour_utc": 3}`
- 3 → `maintenance_window: {"day": "sunday", "hour_utc": 4}`
- 4 → `maintenance_window: "flexible"`

**Default:** 4 → `maintenance_window: "flexible"`

---

#### Q5 — Environment Naming

> What should the primary environment be called in AWS resource naming and tags?
>
> 1. production
> 2. prod
> 3. live
> 4. Other — specify

**Interpret:**

- 1 → `environment_naming: "production"`
- 2 → `environment_naming: "prod"`
- 3 → `environment_naming: "live"`
- 4 → `environment_naming: "<user value>"`

**Default:** 1 → `environment_naming: "production"`

---

#### Q5b — Migration Approach

> _Fires only when Heroku Postgres add-on is present in inventory._
>
> How would you like to sequence the migration?
>
> 1. Full cutover — migrate database and application together in one maintenance window (simpler, single downtime event)
> 2. Database first — migrate the database to AWS now, keep the app on Heroku temporarily while you prepare the compute migration (requires a target exit date)
>
> ⚠️ Option 2 requires network access from Heroku to your AWS database during the transition period, granted to a bounded allowlist of addresses (never the open internet) with TLS enforced first. If your app runs in a Private Space, that means VPC peering or the space's stable outbound IPs; on the Common Runtime it means a static-egress proxy add-on. Access is revoked once the app migrates off Heroku.

**Interpret:**

- 1 → `migration_approach: "full_cutover"`
- 2 → `migration_approach: "interim_cutover_data_first"`

**Default:** 1 → `migration_approach: "full_cutover"`

**If user selects 2:**

1. Ask follow-up: "What's your target date to complete the app migration off Heroku? (YYYY-MM-DD format)"
2. Validate ISO 8601 date format. If invalid, re-prompt.
3. Set `target_exit_date: "<validated date>"`
4. Set `interim_cutover: true`
5. Set `ktlo_warning: "Heroku is in sustaining engineering. Hybrid operation should be bounded to weeks, not quarters."`

**Design impact:** Option 2 → MIGRATION_GUIDE.md includes the "Interim Database Exposure" section (TLS prerequisite gate, then a scoped CIDR allowlist applied via Terraform) and a "Platform Risk" callout.

---

#### Q12c — Compute Target Recommendation

> _Fires always. This question recommends a compute target per dyno formation, then asks whether to accept or override that recommendation._

**Before asking, compute the recommendation from `heroku-resource-inventory.json`:**

1. Build one recommendation row for each `resource_type == "formation"` using `{heroku_app}:{process_type}` as the formation key.
2. Ignore `release` process types for persistent compute; they are deploy-time hooks.
3. If `process_type != "web"` AND `quantity > 1`, recommend `ecs-fargate` for that formation with `chosen_by: "system_forced"` because EB SingleInstance cannot preserve horizontal worker capacity and EB Worker tier is SQS-daemon based, not a Heroku persistent-worker equivalent.
4. For all other formations, recommend `elastic_beanstalk` by default because it preserves the Heroku-like managed platform model. Add reason text from available signals:
   - web dynos → "managed LoadBalanced EB environment preserves PaaS-style web delivery"
   - non-web `quantity == 1` → "SingleInstance WebServer environment preserves the persistent worker process model"
   - lower dyno tiers (`eco`, `basic`, `standard-*`) → "lower operational burden than direct container orchestration"
   - `operational.containerization_status == "containerized"` when already known → "Fargate activation cost is lower if direct container control is preferred"
5. Derive the recommendation summary:
   - If all non-release rows recommend EB → `recommendation.value: "elastic_beanstalk"`, `confidence: "high"`
   - If any row is system-forced to Fargate while others remain EB → `recommendation.value: "mixed"`, `confidence: "high"`
   - If the user explicitly chooses all-Fargate or EKS below → record that user choice as the default with no system recommendation override, except scaled non-web EB downgrades remain forbidden.

**Present the computed recommendation before the choices. Example wording:**

> Based on your Heroku formations, I recommend:
>
> - `web` → Elastic Beanstalk: managed PaaS-style web environment
> - `worker x3` → ECS Fargate: EB cannot horizontally scale persistent workers
>
> Elastic Beanstalk remains the default for EB-compatible dynos. Fargate is used where the Heroku formation requires horizontal non-web capacity.
>
> Which compute target plan should we use?
>
> 1. Use this recommendation — EB default with per-formation Fargate overrides where needed (default)
> 2. Use Elastic Beanstalk for all EB-compatible formations; keep system-forced Fargate overrides for scaled non-web workers
> 3. Use ECS Fargate for all dyno formations
> 4. Use EKS — team has Kubernetes expertise and wants full K8s control
> 5. EKS acceptable — team can operate K8s, prefers managed node groups to reduce burden
> 6. Set per-formation targets manually

**Interpret:**

- 1 → `design_constraints.compute_target: { "default": "elastic_beanstalk", "overrides": [<system_forced Fargate overrides>], "chosen_by": "system_recommended", "recommendation": { "value": "elastic_beanstalk|mixed", "confidence": "high|medium|low", "reasons": [<summary reasons>] } }`
- 2 → same as 1, but `chosen_by: "user"` and `recommendation.reasons` MUST include "user selected EB for all EB-compatible formations". Scaled non-web `quantity > 1` formations remain `system_forced` Fargate overrides.
- 3 → `design_constraints.compute_target: { "default": "ecs-fargate", "overrides": [], "chosen_by": "user", "recommendation": { "value": "ecs-fargate", "confidence": "high", "reasons": ["user selected direct managed containers for all dyno formations"] } }`
- 4 → `design_constraints.compute_target: { "default": "eks-managed", "overrides": [], "chosen_by": "user", "recommendation": { "value": "eks-managed", "confidence": "high", "reasons": ["user selected Kubernetes control"] } }`
- 5 → `design_constraints.compute_target: { "default": "eks-or-ecs", "overrides": [], "chosen_by": "user", "recommendation": { "value": "eks-or-ecs", "confidence": "medium", "reasons": ["user can operate Kubernetes but prefers managed node groups"] } }`
- 6 → ask a short follow-up listing each formation and write `overrides[]` for user-selected deviations from the default. Do not allow EB for scaled non-web formations unless the user first changes the Heroku quantity to 1 or accepts a manual non-generated exception; generated artifacts must keep those formations on Fargate.

**Default:** 1 — use the computed recommendation. "I don't know" maps to 1, not to a blind EB-only default.

**Design impact:** Design resolves each formation from `compute_target.default` plus matching `overrides[]`. EB-compatible web dynos map to LoadBalanced EB environments. EB-compatible persistent non-web dynos with `quantity == 1` map to SingleInstance WebServer environments. Persistent non-web dynos with `quantity > 1` map to Fargate to preserve horizontal worker count. `"ecs-fargate"` maps formations to Fargate services. `"eks-managed"` or `"eks-or-ecs"` maps formations to EKS Deployments. Non-formation resources (Postgres, Redis, Kafka, add-ons) are unaffected.

**Fir intent precedence:** If Q11 (Fir intent = "self_managed_eks_ecs") and Q12c conflict, the compute target plan takes precedence for non-Fir formations. Fir workloads remain deferred in v1 regardless of this setting.

#### Q12d — Elastic Beanstalk Deployment Mechanism

> _Fires only when the resolved compute target plan includes Elastic Beanstalk: `design_constraints.compute_target.default` is `"elastic_beanstalk"`, the field is absent, or any per-formation override resolves to `"elastic_beanstalk"`._
>
> How do you want to deploy code changes to Elastic Beanstalk?
>
> 1. GitHub Actions — deploy from your existing workflow using OIDC role assumption, no AWS-managed pipeline (default)
> 2. AWS CodePipeline — AWS-managed pipeline triggered on GitHub push; requires one-time GitHub connection authorization in the AWS console
> 3. Manual CLI — no automated pipeline; deploy via the EB/AWS CLI as documented in `MIGRATION_GUIDE.md`

**Interpret:**

- 1 → `design_constraints.eb_deploy_method: { "value": "github_actions", "chosen_by": "user" }`
- 2 → `design_constraints.eb_deploy_method: { "value": "codepipeline", "chosen_by": "user" }`
- 3 → `design_constraints.eb_deploy_method: { "value": "manual", "chosen_by": "user" }`

**Default:** 1 → `design_constraints.eb_deploy_method: { "value": "github_actions", "chosen_by": "default" }`

**Generate impact:** `"github_actions"` emits `.github/workflows/deploy-eb.yml`; `"codepipeline"` emits `terraform/pipeline.tf`; `"manual"` emits neither automation artifact and keeps the CLI path in `MIGRATION_GUIDE.md`.

---

### Batch 2: Data / Network

#### Q6 — Database HA Preference

> _Fires only when Heroku Postgres add-on is present in inventory._
>
> For your PostgreSQL database(s), what high-availability configuration do you want on AWS?
>
> 1. Single-AZ — matches typical Heroku standard plans, lowest cost
> 2. Multi-AZ — automatic failover to standby replica (RDS Multi-AZ)
> 3. Multi-AZ HA — Aurora with read replicas and fast failover
> 4. Match global availability posture — use same tier as Q3 answer

**Interpret:**

- 1 → `database_ha: "single-az"`
- 2 → `database_ha: "multi-az"`
- 3 → `database_ha: "multi-az-ha"`
- 4 → `database_ha: <value from Q3 availability>`

**Default:** 4 → matches Q3 availability answer

**Design impact:**

- `single-az` or `multi-az` → RDS PostgreSQL
- `multi-az-ha` → Aurora PostgreSQL

---

#### Q6b — Migration Approach

> _Fires only when Heroku Postgres add-on is present in inventory._
>
> How do you want to phase the migration?
>
> 1. Full cutover — migrate database and application together in one maintenance window
> 2. Data-first (interim cutover) — migrate database to AWS first, keep application on Heroku temporarily while you containerize and prepare compute migration
>
> ⚠️ Note: Option 2 requires interim network access from Heroku to your RDS instance, granted to a bounded allowlist of addresses (never the open internet) with TLS enforced first — via Private Space VPC peering or stable outbound IPs, or a static-egress proxy add-on on the Common Runtime. Heroku is in sustaining engineering — hybrid operation should be bounded to weeks, not quarters.

**Interpret:**

- 1 → `migration_approach: "full_cutover"`
- 2 → `migration_approach: "interim_cutover_data_first"` — also triggers follow-up for target exit date

**If 2 selected, immediately ask:**

> When do you plan to complete the full migration (move compute off Heroku)?
> Please provide a target date (YYYY-MM-DD format).

Validate: must be valid ISO 8601 date, must be in the future.

**On valid date:** Set `target_exit_date: "<date>"`, `interim_cutover: true`, `ktlo_warning: "Heroku is in sustaining engineering. Hybrid operation should be bounded to weeks, not quarters."`

**Default:** 1 → `migration_approach: "full_cutover"`

**Design impact:** Option 2 triggers the interim database exposure section in MIGRATION_GUIDE.md (TLS prerequisite gate, then a scoped CIDR allowlist applied via Terraform), a Platform Risk callout, and post-migration lockdown emphasis.

---

#### Q6c — Database Migration Method

> _Fires only when Heroku Postgres add-on is present in inventory._
>
> How would you like to migrate your PostgreSQL data to AWS?
>
> Estimated database size from your plan: ~[derive from postgres plan table max storage]
> (If you know your actual database size, tell me and I'll adjust the recommendation.)
>
> 1. pg_dump / pg_restore — simplest method, requires application downtime during migration (recommended for databases under ~10GB)
> 2. AWS DMS (Database Migration Service) — bulk migration with shorter downtime window for large databases (recommended for databases over ~10GB)
>    ⚠️ Note: DMS cannot do continuous replication with Heroku Postgres (Heroku does not grant the REPLICATION role). This is a one-time bulk copy with a final cutover window.
> 3. Bucardo — trigger-based replication for near-zero downtime (requires additional EC2 infrastructure)
> 4. WAL-G — WAL-based replication for minimal downtime on large databases (requires additional EC2 infrastructure)

**Interpret:**

- 1 → `migration_method: "pg_dump_restore"`
- 2 → `migration_method: "dms"`
- 3 → `migration_method: "bucardo"`
- 4 → `migration_method: "wal_g"`

**Default:** 1 → `migration_method: "pg_dump_restore"`

**Size-based recommendation logic:**

- If estimated DB size < 10GB → recommend 1 (pg_dump_restore)
- If estimated DB size ≥ 10GB and user accepts brief downtime → recommend 2 (dms)
- If user requires near-zero downtime regardless of size → recommend 3 or 4

**Estimating size:** Use the postgres plan table's maximum storage capacity for the detected plan tier as the estimated size. **Note: This is an upper-bound estimate — your actual database may be much smaller than the plan allows.** If your actual data is well below the plan maximum (e.g., 2 GB actual on a 64 GB plan), override downward to get a more appropriate method recommendation. If user provides actual size, use that instead and record `source: "user_override"` for the size estimate.

**Design impact:** Determines which data migration procedure section appears in MIGRATION_GUIDE.md. DMS selection triggers the CDC limitation warning.

---

#### Q7 — Redis HA

> _Fires only when Heroku Redis (Key-Value Store) add-on is present in inventory._
>
> Should your Redis cluster on AWS include Multi-AZ with automatic failover?
>
> 1. Yes — Multi-AZ with automatic failover (higher availability, ~2x cost)
> 2. No — single-node, no replication (matches Heroku mini/premium-0 without HA)

**Interpret:**

- 1 → `redis_ha: true`
- 2 → `redis_ha: false`

**Default:** 1 → `redis_ha: true` (if source plan has HA enabled), otherwise 2 → `redis_ha: false`

---

#### Q8 — Kafka Retention

> _Fires only when Heroku Kafka (Apache Kafka on Heroku) add-on is present in inventory._
>
> How long should Kafka messages be retained on AWS MSK?
>
> 1. 1 day — minimal retention, lowest storage cost
> 2. 3 days — short-term replay
> 3. 7 days — standard retention (matches Heroku default)
> 4. 14 days — extended replay window
> 5. 30 days — long retention for analytics/audit
> 6. Custom — specify number of days

**Interpret:**

- 1 → `kafka_retention_days: 1`
- 2 → `kafka_retention_days: 3`
- 3 → `kafka_retention_days: 7`
- 4 → `kafka_retention_days: 14`
- 5 → `kafka_retention_days: 30`
- 6 → `kafka_retention_days: <user value>` (validate: integer 1–365)

**Default:** 3 → `kafka_retention_days: 7`

---

#### Q9 — VPC Subnet IDs

> _Fires only when Private Space with VPC peering is detected AND subnet IDs are not available from the API._
>
> Your Heroku Private Space has VPC peering configured. I need your AWS subnet IDs to reference the existing VPC instead of creating a new one.
>
> Please provide 1–6 subnet IDs (comma-separated) in the format: `subnet-xxxxxxxxxxxxxxxxx`
>
> Example: `subnet-0a1b2c3d4e5f67890, subnet-1a2b3c4d5e6f78901`

**Interpret:** Parse comma-separated values, trim whitespace, validate each matches `^subnet-[0-9a-f]{17}$`.

**Validation:** If any ID does not match the format, reject and re-prompt:

> "Invalid subnet ID format. Expected format: `subnet-xxxxxxxxxxxxxxxxx` (subnet- followed by 17 hexadecimal characters). Please provide 1–6 valid subnet IDs."

**Accept:** 1–6 valid subnet IDs → `subnet_ids: [<validated array>]`

---

#### Q9b — VPC ID

> _Fires only when VPC peering is detected but the VPC ID could not be found in Terraform._
>
> I detected VPC peering for your Private Space but couldn't find the AWS VPC ID in your Terraform files. Please provide your existing AWS VPC ID.
>
> Format: `vpc-xxxxxxxxxxxxxxxxx`

**Interpret:** Validate matches `^vpc-[0-9a-f]{17}$`.

**Validation:** If format doesn't match, reject and re-prompt:

> "Invalid VPC ID format. Expected format: `vpc-xxxxxxxxxxxxxxxxx` (vpc- followed by 17 hexadecimal characters). Please provide your existing AWS VPC ID."

**Accept:** Valid VPC ID → `existing_vpc_id: "<validated value>"`

---

#### Q10 — DNS Strategy

> How do you want to manage DNS for your migrated services?
>
> 1. Route 53 — migrate DNS to AWS for full integration (health checks, failover routing)
> 2. External DNS — keep current DNS provider, update records manually during cutover

**Interpret:**

- 1 → `dns_strategy: "route53"`
- 2 → `dns_strategy: "external"`

**Default:** 1 → `dns_strategy: "route53"`

---

### Batch 3: Operational / Conditional

#### Q11 — Fir Intent

> _Fires ONLY when at least one app has `heroku_generation == "fir"` in the inventory._
>
> I detected Fir-generation app(s) in your Heroku account. Fir runs on Kubernetes with ARM/Graviton and Cloud Native Buildpacks — these workloads may already run on AWS infrastructure, which can reduce your compute migration lift.
>
> What's your compute migration intent for these Fir workloads?
>
> 1. Exit Heroku entirely — re-platform all Fir workloads to AWS (ECS/Fargate, standard containers)
> 2. Self-managed EKS/ECS — move to Kubernetes or ECS on AWS with your own orchestration

**Interpret:**

- 1 → `fir_intent: "exit_heroku"`
- 2 → `fir_intent: "self_managed_eks_ecs"`

**Default:** 1 → `fir_intent: "exit_heroku"`

**Note:** Cutover timing (full vs data-first) is handled by the migration_approach question (Q5b), not this question. This question only determines the compute destination for Fir workloads.

**Design impact:** Both options result in full Fir workload migration to AWS. Option 2 indicates the user wants to manage their own Kubernetes/ECS orchestration rather than using the skill's standard Fargate mapping.

---

#### Q12b — Containerization Status

> Is your application already containerized (has a Dockerfile)?
>
> 1. Yes — Dockerfile exists, ready for AWS compute deployment
> 2. No — uses Heroku buildpacks only, no Dockerfile yet
> 3. Partial — some services have Dockerfiles, others use buildpacks

**Interpret:**

- 1 → `containerization_status: "containerized"`
- 2 → `containerization_status: "buildpack_only"`
- 3 → `containerization_status: "partial"`

**Default:** 2 → `containerization_status: "buildpack_only"`

**Design impact:** Options 2 and 3 trigger a "Containerization Prerequisites" section in the MIGRATION_GUIDE.md with Procfile→Dockerfile guidance for common buildpacks (Ruby, Node.js, Python, Go, Java). Does not change design mappings. EB and Fargate Docker paths both require a Dockerfile/source bundle; EKS also requires containerization.

---

#### Q12 — Container Registry

> Where should container images be stored for your containerized workloads?
>
> 1. Amazon ECR — fully integrated with ECS/Fargate override paths, no cross-account config needed
> 2. Existing registry — you already have a container registry (Docker Hub, GitHub Container Registry, etc.)

**Interpret:**

- 1 → `container_registry: "ecr"`
- 2 → `container_registry: "external"`

**Default:** 1 → `container_registry: "ecr"`

---

#### Q13 — Log Retention

> How long should application logs be retained in CloudWatch Logs?
>
> 1. 7 days — short retention, lowest cost
> 2. 14 days — standard short-term
> 3. 30 days — typical production retention
> 4. 90 days — extended for debugging and compliance
> 5. 365 days — long-term compliance/audit
> 6. Custom — specify number of days

**Interpret:**

- 1 → `log_retention_days: 7`
- 2 → `log_retention_days: 14`
- 3 → `log_retention_days: 30`
- 4 → `log_retention_days: 90`
- 5 → `log_retention_days: 365`
- 6 → `log_retention_days: <user value>` (validate: integer 1–3653)

**Default:** 3 → `log_retention_days: 30`

---

#### Q14 — Alerting Preference

> How do you want to handle alerting and on-call notifications?
>
> 1. CloudWatch Alarms + SNS — native AWS alerting (email, SMS, Lambda triggers)
> 2. PagerDuty — integrate with existing PagerDuty setup
> 3. OpsGenie — integrate with existing OpsGenie setup
> 4. None for now — I'll configure alerting later

**Interpret:**

- 1 → `alerting: "cloudwatch"`
- 2 → `alerting: "pagerduty"`
- 3 → `alerting: "opsgenie"`
- 4 → `alerting: "none"`

**Default:** 1 → `alerting: "cloudwatch"`

---

#### Q15 — Cost Optimization Aggressiveness

> How aggressively should we optimize for cost vs. operational safety?
>
> 1. Conservative — match current capacity closely, prioritize stability over savings
> 2. Balanced — reasonable right-sizing with safety margins (recommended)
> 3. Aggressive — minimize cost, accept tighter margins and potential scaling events

**Interpret:**

- 1 → `cost_optimization: "conservative"`
- 2 → `cost_optimization: "balanced"`
- 3 → `cost_optimization: "aggressive"`

**Default:** 2 → `cost_optimization: "balanced"`

---

## Defaults Table

| Question                  | Default                                 | Constraint                                                                                                  |
| ------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Q1 — Region               | 1 (us-east-1)                           | `target_region: "us-east-1"`                                                                                |
| Q2 — Compliance           | 1 (none)                                | `compliance: "none"`                                                                                        |
| Q3 — Availability         | 2 (multi-az)                            | `availability: "multi-az"`                                                                                  |
| Q4 — Maintenance          | 4 (flexible)                            | `maintenance_window: "flexible"`                                                                            |
| Q5 — Env naming           | 1 (production)                          | `environment_naming: "production"`                                                                          |
| Q6 — Database HA          | 4 (match Q3)                            | `database_ha: <Q3 value>`                                                                                   |
| Q6b — Migration approach  | 1 (full cutover)                        | `migration_approach: "full_cutover"`                                                                        |
| Q6c — DB migration method | 1 (pg_dump)                             | `migration_method: "pg_dump_restore"`                                                                       |
| Q7 — Redis HA             | 1 (yes)                                 | `redis_ha: true`                                                                                            |
| Q8 — Kafka retention      | 3 (7 days)                              | `kafka_retention_days: 7`                                                                                   |
| Q9 — Subnet IDs           | _(no default — must ask if applicable)_ | —                                                                                                           |
| Q9b — VPC ID              | _(no default — must ask if applicable)_ | —                                                                                                           |
| Q10 — DNS                 | 1 (Route 53)                            | `dns_strategy: "route53"`                                                                                   |
| Q11 — Fir intent          | 1 (exit Heroku)                         | `fir_intent: "exit_heroku"`                                                                                 |
| Q12b — Containerization   | 2 (buildpack_only)                      | `containerization_status: "buildpack_only"`                                                                 |
| Q12c — Compute target     | 1 (use computed recommendation)         | `design_constraints.compute_target.default: "elastic_beanstalk"` plus any `system_forced` Fargate overrides |
| Q12d — EB deploy method   | 1 (GitHub Actions)                      | `eb_deploy_method: "github_actions"` when resolved compute plan includes EB                                 |
| Q12 — Registry            | 1 (ECR)                                 | `container_registry: "ecr"`                                                                                 |
| Q13 — Log retention       | 3 (30 days)                             | `log_retention_days: 30`                                                                                    |
| Q14 — Alerting            | 1 (CloudWatch)                          | `alerting: "cloudwatch"`                                                                                    |
| Q15 — Cost optimization   | 2 (balanced)                            | `cost_optimization: "balanced"`                                                                             |

**Important:** Q9 and Q9b have no default — they are only asked when Private Space peering exists and required data is missing. If they fire, they must be answered (the system cannot proceed without subnet/VPC information for existing VPC references).

When all active batches are answered (or defaults applied for the rest), control passes to
the assembler (`clarify-assemble.md`) to write and validate `preferences.json`.
