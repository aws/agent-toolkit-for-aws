---
_assemble: assemble-preferences
_of_phase: clarify
_reads:
  - global (fragment contribution)
  - compute (fragment contribution, when triggered)
  - database (fragment contribution, when triggered)
  - ai (fragment contribution, when ai-workload-profile.json exists)
_produces:
  - preferences.json
_knowledge:
  - { file: references/shared/schema-preferences.md }
  - { file: references/shared/schema-discover-ai.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
---

# Clarify — Assemble Preferences

> **Assembler unit.** The single creator of `preferences.json` and the owner of its final
> contract. See `clarify.md` for how it is composed into the phase.

**Schema reference**: `references/shared/schema-preferences.md`.

## This unit owns the conversation

Fragments compute rows. **The assembler is the only thing that talks to the user**, and it
runs three gates in order, plus the two GCP-specific mechanisms (fast paths, Full Flow
opt-out) that live in `clarify.md` and short-circuit before reaching this file. See
`clarify.md` § Step 2 for why presentation is centralised here.

## Step 2 (extraction detail): BigQuery / Deferred Analytics

One extraction step does not belong to any single fragment because it gates a report
callout, not a design constraint:

**BigQuery / analytics warehouse** — Set `bigquery_present` to **true** if **any** of: (a) a
resource in `gcp-resource-inventory.json` has `gcp_type` (or equivalent type field) starting
with `google_bigquery_`; (b) `billing-profile.json` lists a service/SKU that clearly indicates
**BigQuery** (e.g., service name or SKU contains `BigQuery`). Otherwise `bigquery_present` is
**false**. Record in `metadata.inventory_clarifications.bigquery_present`.

## Gate 1 — The Assumption Sheet (Mandatory Gate)

**When to run:** Always in wizard mode, after all triggered fragments return their rows —
whenever at least one row is DETECTED or PROPOSED.

**Skip Gate 1 only when** every active row is ESSENTIAL or N/A (rare — e.g., empty discovery
with Category A only). Proceed directly to Gate 2.

**HARD GATE — do NOT ask any essential question until the user responds to this sheet.**

Present the sheet in two sections (omit rows for questions that are ESSENTIAL or N/A). Keep
each consequence to one line — use the consequence text supplied by each row's fragment:

```
### Migration assumptions — confirm or correct

**Detected from your Terraform, billing, and code:**

| Setting | Value | Source | What it decides |
| ------- | ----- | ------ | --------------- |
| Region | us-west-2 (GCP us-west1) | gcp-resource-inventory.json | All AWS resources deploy here |
| Database availability | Single-AZ (Cloud SQL `ZONAL`) | Terraform `availability_type` | RDS single-AZ topology |
| Database size | up to 10 GB allocated (actual data may be less) | Terraform `disk_size` | Migration tool ceiling; script measures actual size |
| DB traffic / I/O | Steady / Low (dev-tier `db-f1-micro`) | Terraform tier + ZONAL | gp3 storage, no replicas |
| Cloud SQL HA | Zonal (1 instance) | billing-profile.json | No Aurora Multi-AZ failover |
| AI model | gemini-2.5-flash | ai-workload-profile.json | Bedrock mapping baseline |

**Assumed (documented defaults — correct anything that's wrong):**

| Setting | Assumed value | Consequence if left as-is |
| ------- | ------------- | ------------------------- |
| Multi-cloud | AWS-only | ECS Fargate eligible; multi-cloud would force EKS |
| Cloud Run spend | $100–$500/mo | Feeds migrate-vs-stay analysis |
| AI priority | Balanced | Sonnet-class default model |
| AI latency | Important (<2s) | Sonnet + streaming; <500ms would force Haiku/Nova |
| WebSockets | None (unverified — no code scan) | Standard ALB config |

Q27 (AWS Activate credits) is **not** on this sheet — it is asked in Gate 2 when AI
workloads are detected.

Reply:
1. **Confirm all** (or "looks good") — I'll record these and ask only the [N] essential
   questions.
2. **Change a setting** — name it precisely (**"availability: mission-critical"**, **"ai
   priority: cost"**, **"websockets: yes"**) or just describe it in plain words (**"our
   database going down would be really bad"** — I'll map it or ask the full question). You
   can fix several in one message.
3. **"ask me about [setting]"** — I'll ask the full question with all options for that item.
4. **"ask me everything"** — discard all assumptions and run the full question-by-question
   flow.
```

_Present these as selectable options via the structured question tool (e.g. AskUserQuestion)
when the IDE provides one; otherwise show the numbered list above verbatim. Free-text
corrections are always accepted in either mode — the menu supplements the override grammar,
it never replaces it._

**Computing [N]:** Count ESSENTIAL dispositions across all triggered fragments, plus any rows
converted to ESSENTIAL via user correction ("ask me about X"), plus conflict rows. Subtract
any ESSENTIAL questions that were already answered by a user correction on the sheet (e.g.,
user said `"availability: mission-critical"` — the availability question no longer needs
asking).

**Multi-instance Cloud SQL conflicts:** When instances disagree, replace the single-row
summary with a per-instance table and keep the conflicting question ESSENTIAL until resolved:

```
| Instance | availability_type | tier | disk_size (GB) |
| -------- | ----------------- | ---- | -------------- |
| google_sql_database_instance.main | ZONAL | db-f1-micro | 10 |
| google_sql_database_instance.analytics | REGIONAL | db-n1-standard-4 | 100 |

These instances disagree on availability. Which posture should we use for the migration design?
1\) Most conservative (highest HA) | 2\) Use [instance name] as primary | 3\) Ask me the full availability question
```

**Override handling** — when the user corrects a value (detected or assumed):

| User correction (examples)                       | Update constraint                                                             | Re-ask?                |
| ------------------------------------------------ | ----------------------------------------------------------------------------- | ---------------------- |
| `availability: mission-critical` / `multi-az-ha` | `availability: "multi-az-ha"`, `chosen_by: "user"`                            | No — value is explicit |
| `availability: significant` / `multi-az`         | `availability: "multi-az"`, `chosen_by: "user"`                               | No                     |
| `availability: dev` / `single-az`                | `availability: "single-az"`, `chosen_by: "user"`                              | No                     |
| `db size: <10GB` / `10-100GB` / etc.             | Set `db_size` to stated band, `chosen_by: "user"`                             | No if band is explicit |
| `region: [AWS region]`                           | Set `target_region`, `chosen_by: "user"`                                      | No                     |
| `model: [model name]`                            | Set `ai_model_baseline`, `chosen_by: "user"`                                  | No if maps cleanly     |
| `websockets: yes`                                | Set `websocket: "required"`, `chosen_by: "user"`                              | No                     |
| `spend: $5K-$20K`                                | Set `gcp_monthly_spend`, `chosen_by: "user"`                                  | No if band is explicit |
| `ai priority: cost` / `speed` / `quality`        | Set `ai_priority`, `chosen_by: "user"`                                        | No                     |
| `multi-cloud: yes`                               | `compute: "eks"`, `chosen_by: "user"`; Q8 → N/A; Q7b → N/A (App Engine → EKS) | No                     |
| "ask me about [setting]"                         | Convert that row to ESSENTIAL                                                 | Yes — full question    |
| Vague correction ("that's wrong")                | Convert that row to ESSENTIAL                                                 | Yes — full question    |

For each override: set `chosen_by: "user"` on the constraint (this removes the `source`
field since it's no longer extracted/default). For extracted rows, also remove the question
ID from `metadata.questions_skipped_extracted`; for assumed rows, remove it from
`metadata.questions_defaulted`.

**When the user confirms ("looks good"):** no further action needed — the constraint objects
already carry their `chosen_by` and `source` fields.

**"Ask me everything":** clear `questions_skipped_extracted` and `questions_defaulted`; set
all previously extracted/assumed constraints to pending; set `metadata.clarify_mode: "full"`
and run the **Full Flow variant** (below) instead of Gate 2.

**Constraint `source` field:** When writing a constraint with `chosen_by: "extracted"` or
`chosen_by: "default"`, include the `source` field on the constraint object itself:

- Extracted: raw provenance signal (e.g. `"terraform:availability_type=ZONAL"`,
  `"billing:region=us-west1"`, `"ai-profile:integration.pattern=direct_sdk"`)
- Default: `"default:<Qid>"` (e.g. `"default:Q16"`)

Omit `source` when `chosen_by` is `"user"` or `"derived"`.

After the user responds, write `preferences-draft.json` with all resolved values and
`metadata.wizard_stage: "essentials_pending"`, then proceed to Gate 2.

## Category E — Migration Posture (Disabled by Default)

_Fire when:_ User explicitly opts in.
_Default behavior when disabled:_ Apply conservative defaults — no HA upgrades, no
right-sizing.

**Superseded by `clarify-global.md`'s cost-optimization-appetite row for the right-sizing
half:** per `references/vendored/clarify/clarify-cost-appetite.md` § "What a consuming skill
supplies" item 1, a run that resolved that row to `aggressive` should behave as if it opted
into `right_sizing: true` here without asking Q-E2 separately. Q-E1 (HA upgrade opt-in)
remains a distinct opt-in.

If the user opts in, present after the essentials:

### Q-E1 — Should we recommend upgrading Single-AZ to Multi-AZ where possible?

> 1\) Yes — upgrade to Multi-AZ for higher availability | 2\) No — keep current topology

Interpret → `ha_upgrade`: 1 → `true`, 2 → `false`. Default: 2 → `false`.

### Q-E2 — Should we use billing utilization data to right-size instance types?

**Skip when** the cost-optimization-appetite row already resolved to `aggressive` — apply
`right_sizing: true` directly per the supersession rule above instead of asking.

> 1\) Yes — right-size based on utilization | 2\) No — match current capacity

Interpret → `right_sizing`: 1 → `true`, 2 → `false`. Default: 2 → `false`.

## Gate 2 — The Essential Questions

**Prerequisite:** Gate 1 sheet confirmation must be complete (user said "looks good" or
finished correcting) before asking anything. Do not re-show the full sheet here unless the
user asks for a recap.

> **COMPLIANCE SELF-CHECK (do this before emitting any question):** Verify both: (1) the
> Assumption Sheet was presented in a **previous turn**, and (2) the user has **responded**
> to it. If either is false, STOP — present the sheet and wait. Never combine the sheet and
> essential questions in a single message, and never ask a question that has a sheet row
> unless the user converted it via a correction or "ask me about X".

**BigQuery / deferred analytics (mandatory callout):** If `bigquery_present` is **true**,
output this block **once**, **before** any questions (same turn as the essentials), then
continue:

> **BigQuery / analytics warehouse:** Your discovery inputs include BigQuery. This skill
> **does not** select an AWS analytics or data-warehouse target (no Athena, Redshift, Glue,
> or EMR recommendation from the plugin). **Before** warehouse, data lake, SQL analytics, or
> BI cutover planning, engage your **AWS account team** and/or a **data analytics migration
> partner** to assess query patterns, data volumes, ETL/ELT, and downstream consumers.
> Design will mark these resources as **`Deferred — specialist engagement`**.

### Essentials Batches

Present the essential questions (from each fragment's disposition, plus any rows converted by
"ask me about X") in batches of **at most 4 per turn**, numbered from 1, with the question
text, context, and options from the fragment files. Typical total: 2–7.

**Batch composition:** core first (Q1/Q2/Q3/Q3.5/Q7 + conflicts, from `clarify-global.md`),
then AI/agentic (Q15, Q23–Q25, multi-workload confirmations, from `clarify-ai.md`). **Q27 is
not batched** — ask it as its own short follow-up after the last batch, per the presentation
rule in `clarify-ai.md` Q27 (it's a funding question, not a technical one). Write
`preferences-draft.json` between batches (same schema as `preferences.json` plus
`metadata.wizard_stage`). When more than one batch is needed, open each with a progress line:
"Batch [i] of [k]."

Open the first batch with:

```
That leaves [N] decisions only you can make — then we're ready to design.
You can answer in shorthand ("1A 2C 3 skip"), describe answers in plain words,
skip individual ones (I'll use the documented default), or say
"use defaults for the rest."

Question 1: [Q2 text with context and options]
Question 2: [Q7 text with context and options]
...
```

_Present each question's options via the structured question tool (e.g. AskUserQuestion)
when the IDE provides one — one tool call per batch, identical option text. Otherwise use the
lettered options in chat as shown. Shorthand and plain-word answers are accepted in either
mode._

**This ≤4 cap applies to wizard essentials only.** The Full Flow variant below keeps its
documented three-batch structure — the user explicitly opted into the long path and has
shorthand answering.

**Wait for the user's response.** Do NOT proceed to Design without a response or an explicit
"use defaults for the rest."

**"Use defaults for the rest" handling:** Apply documented defaults for all unanswered
essential questions **except** those marked "never assumed" in each fragment when a safe
default genuinely does not exist:

- Q2 (compliance) defaults to **unknown** — write `compliance: {value: ["unknown"], chosen_by:
  "default", source: "default:Q2"}`. Never record silent "no requirements"; `["unknown"]`
  behaves like "none" for service selection but triggers the report compliance caveat. See
  `references/vendored/clarify/clarify-compliance.md`.
- Q7 defaults to 4 (flexible).
- Q3 defaults to 2 ($1K–$5K) with a report caveat that spend was not confirmed.
- **Q27 must not be silently defaulted in wizard mode** when Category H fired — if the user
  skips it, record `startup_program_status: "unknown"` with `chosen_by: "default"` and
  `source: "default:Q27"`; downstream artifacts must use neutral Activate copy (both tiers, no
  "your status: eligible_*").
- Q3.5, Q23–Q25, and unresolved multi-instance conflicts fall back to their documented
  defaults (Q3.5 → 5; Q23 → framework-based; Q24 → session; Q25 → medium; conflicts → most
  conservative posture) with `chosen_by: "default"`.
  Then run the **Answer Recap** (below) with the defaulted rows included, then Category E
  opt-in, then Step 5.

**Interpret answers** using the interpret rules in each fragment file. Apply early-exit rules
triggered by answers (e.g., the multi-cloud row's correction to "yes" → `compute: "eks"`, Q8 →
N/A).

## Gate 3 — The Answer Recap (Check Your Answers)

After the last essential batch is answered and interpreted (and after Q27 when it fired),
play back what was recorded — the essentials are the only answers in the flow the user states
rather than confirms, and shorthand ("1A 2C") plus plain-word answers pass through an
interpretation step the user never sees. One compact table, questions asked in Gate 2 only
(sheet rows were already confirmed at Gate 1 — do not repeat them):

```
### What I recorded — last check before design

| Question | Your answer | Recorded as |
| -------- | ----------- | ----------- |
| Compliance (Q2) | "2A" | None |
| Cutover window (Q7) | "monthly is fine" | Monthly maintenance window |
| AI spend (Q15) | "about a grand" | $500–$2K/month |

Anything wrong? Name it ("cutover: weekly") — or say "looks good" and I'll proceed to design.
```

**Always wait.** Present the recap and **wait for the user's response** ("looks good" or a
correction) before continuing — interpretation is exactly where a misread silently becomes a
design constraint, and the batch opener invites shorthand and plain-word answers, so nearly
every real run involves interpretation. One extra turn at the single highest-stakes commit in
the flow is the intended cost. Corrections use the Gate 1 override grammar and set
`chosen_by: "user"`.

**Sequence (fixed — do not reorder or combine):**

1. Answer Recap → wait for the user's response
2. Category E opt-in (if `billing-profile.json` exists) → wait
3. Step 5 — write `preferences.json`

**"Use defaults for the rest" still gets a recap:** when the user defaults remaining
questions, include those rows with `(default applied)` in the "Your answer" column and the
defaulted value in "Recorded as" — bulk-defaulting is the highest-risk interpretation of all,
and this is the user's one chance to see what "the rest" actually meant. Then wait as above.

## Full Flow variant ("ask me everything")

**GCP-specific — `azure-to-aws` has no equivalent opt-out flow.** When the user opted out of
the wizard, run the progressive-batch flow: present ALL active questions (no dispositions) in
up to three batches — Strategic (Q1–Q7, minus Q4), Infrastructure (Q8–Q13b including Q11b
Graviton and Category B), AI (Q14–Q27, Q23–Q26 only if agentic) — writing
`preferences-draft.json`
between batches with `metadata.batches_completed` / `metadata.batches_remaining` (values:
`"strategic"`, `"infrastructure"`, `"ai"`). Per-question skip and "use defaults for the rest"
behave as documented. Set `metadata.clarify_mode: "full"`. The **Answer Recap** above runs
after the final batch here too (all answered questions as rows; skipped/defaulted ones
summarized in one line, not per-row — intentional compression so a 20+ question full-flow
recap stays scannable; the wizard already shows every defaulted essential as a `(default
applied)` row because that set is small. Do not silently drop answered questions into the
one-liner).

## Category E Opt-In

After the essentials are answered (but before writing final `preferences.json`), offer
Category E if `billing-profile.json` exists:

> "Would you also like HA upgrade and right-sizing recommendations based on your billing
> data? If not, I'll use conservative defaults (no upgrades, match current capacity)."

If user opts in, present Q-E1, and Q-E2 **unless** the cost-optimization-appetite row
already resolved to `aggressive` (then apply `right_sizing: true` without asking Q-E2).
Otherwise, apply Category E defaults (`ha_upgrade: false`, `right_sizing: false`).

## Answer Combination Triggers

| Scenario                                 | Key Answers                                                                        | Recommendation                                                                                  |
| ---------------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Early-stage funding path                 | Q3 = lower spend band                                                              | Entry-tier migration funding program review                                                     |
| Growth-stage funding path                | Q3 = higher spend band                                                             | Migration funding/support program review based on spend profile                                 |
| Managed platform preference              | Q7b = 1 (managed platform)                                                         | Elastic Beanstalk for App Engine compute targets                                                |
| Container orchestration pref             | Q7b = 2 (container orchestration)                                                  | ECS Fargate for App Engine targets (overrides default EB mapping)                               |
| Serverless pref                          | Q7b = 3 (serverless)                                                               | Lambda for App Engine targets (overrides default EB mapping)                                    |
| Must stay portable                       | Multi-cloud row = Yes                                                              | EKS only, no ECS Fargate; App Engine also routes to EKS (Q7b N/A, overrides default EB mapping) |
| Kubernetes-averse                        | Multi-cloud row = No + Q8 = Frustrated                                             | ECS Fargate strongly recommended                                                                |
| WebSocket app                            | Q9 = Yes                                                                           | ALB WebSocket config required                                                                   |
| Low-traffic Cloud Run                    | Q10 = Business hours + Q11 < $100                                                  | Recommend staying on Cloud Run                                                                  |
| Cloud SQL Postgres — dev/low HA          | Availability row = Inconvenient + Cloud SQL in inventory                           | **RDS PostgreSQL** single-AZ                                                                    |
| Cloud SQL Postgres — prod HA (RDS)       | Availability row = Significant Issue + Cloud SQL in inventory                      | **RDS PostgreSQL** Multi-AZ                                                                     |
| Cloud SQL Postgres — mission-critical    | Availability row = Mission-Critical + Cloud SQL in inventory                       | **Aurora PostgreSQL** Multi-AZ; apply Q12/Q13                                                   |
| Cloud SQL Postgres — global catastrophic | Availability row = Catastrophic + user_geography = Global + Cloud SQL in inventory | **Aurora PostgreSQL Global Database**                                                           |
| High I/O database (RDS path)             | Availability = Inconvenient/Significant + Q13 = High                               | **RDS** io2 or Provisioned IOPS                                                                 |
| High I/O database (Aurora path)          | Availability = Mission-Critical/Catastrophic + Q13 = High                          | Aurora I/O-Optimized                                                                            |
| Write-heavy global DB                    | Availability = Mission-Critical/Catastrophic + Q12 = Write-heavy/global            | Aurora DSQL architecture review (RDS path only: size writer; flag review)                       |
| Rapidly growing DB (RDS path)            | Availability = Inconvenient/Significant + Q12 = Rapidly growing                    | RDS with headroom on instance class                                                             |
| Rapidly growing DB (Aurora path)         | Availability = Mission-Critical/Catastrophic + Q12 = Rapidly growing               | Aurora Serverless v2                                                                            |
| Zero downtime required                   | Q7 = No downtime                                                                   | Blue/green + AWS DMS required (RDS or Aurora blue/green per availability row)                   |
| HIPAA compliance                         | Q2 = HIPAA                                                                         | BAA services only, specific regions                                                             |
| FedRAMP required                         | Q2 = FedRAMP                                                                       | GovCloud regions only                                                                           |
| CCPA / CPRA                              | Q2 = 7 (CCPA / CPRA)                                                               | Consumer privacy, logging/retention, data-inventory posture; confirm regions with legal review  |
| Gateway-only AI                          | Q14 = 2 only (LLM router/gateway)                                                  | Config change only; skip SDK migration                                                          |
| LangChain/LangGraph AI                   | Q14 includes 3                                                                     | Provider swap via ChatBedrock; 1–3 days                                                         |
| OpenAI Agents SDK                        | Q14 includes 5                                                                     | Highest AI effort; AgentCore (Harness/Runtime); 2–4 weeks                                       |
| Multi-agent + MCP                        | Q14 = 4 + 6                                                                        | AgentCore to unify orchestration + MCP (Gateway)                                                |
| Voice platform AI                        | Q14 includes 7                                                                     | Check native Bedrock support; Nova 2 Sonic if needed                                            |
| GPT-5.5 migration                        | Q19 = GPT-5.5                                                                      | Claude Opus 4.6 — Bedrock 17% cheaper on output; or Sonnet 5 for 68% savings                    |
| GPT-5.5 Pro migration                    | Q19 = GPT-5.5 Pro                                                                  | Nova 2 Pro — 95% cheaper on Bedrock                                                             |
| GPT-5.4 migration                        | Q19 = GPT-5.4                                                                      | Claude Sonnet 5 — ~36% cheaper blended; AWS consolidation                                       |
| GPT-5.4 Mini/Nano migration              | Q19 = GPT-5.4 Mini or Nano                                                         | Nova Lite/Micro — 87-94% cheaper on Bedrock                                                     |
| GPT-4 Turbo migration                    | Q19 = GPT-4 Turbo                                                                  | Claude Sonnet 5 — 80% cheaper on input                                                          |
| o-series migration                       | Q19 = o-series                                                                     | Claude Sonnet 5 with extended thinking                                                          |
| High-volume cost-critical AI             | Q18 = High + cost critical                                                         | Nova Micro or Haiku 4.5 + provisioned throughput                                                |
| Reasoning/agent workload                 | Q17 = Extended thinking                                                            | Claude Sonnet 5 extended thinking; Opus 4.6 for hardest                                         |
| Speech-to-speech AI                      | Q17 = Real-time speech                                                             | Nova 2 Sonic                                                                                    |
| RAG workload                             | Q17 = RAG optimization                                                             | Bedrock Knowledge Bases + Titan Embeddings                                                      |
| Vision workload                          | Q20 = Vision required                                                              | Claude Sonnet 5 (multimodal)                                                                    |
| Latency-critical AI                      | Q21 = Critical                                                                     | Haiku 4.5 or Nova Micro + streaming                                                             |
| Complex reasoning tasks                  | Q22 = Complex                                                                      | Claude Sonnet 5; Opus 4.6 for hardest                                                           |

## Step 5: Assemble and Write preferences.json

Assemble all resolved values — sheet confirmations, corrections, essential answers, and
defaults — into the final `$MIGRATION_DIR/preferences.json`. **Every constraint object MUST
include `prompt` and `design_consequence`** per `references/shared/schema-preferences.md`
(use the constraint catalog when the user did not see the verbatim question).

If `preferences-draft.json` exists, use it as the base — merge in the final answers, remove
the draft-specific metadata fields (`draft`, `wizard_stage`, `batches_completed`,
`batches_remaining`), and set `metadata.timestamp` to the current time. Write
`$MIGRATION_DIR/preferences.json`:

```json
{
  "metadata": {
    "migration_type": "full",
    "timestamp": "<ISO timestamp>",
    "discovery_artifacts": ["gcp-resource-inventory.json", "ai-workload-profile.json"],
    "questions_asked": ["Q2", "Q7", "Q15", "Q27"],
    "questions_defaulted": ["Q5", "Q9", "Q11", "Q11b", "Q16", "Q17", "Q18", "Q21", "Q22"],
    "questions_skipped_extracted": ["Q1", "Q6", "Q12", "Q13", "Q13b", "Q14", "Q19", "Q20"],
    "questions_skipped_early_exit": ["Q8"],
    "questions_skipped_not_applicable": ["Q3.5", "Q4", "Q10", "Q23", "Q24", "Q25", "Q26"],
    "category_e_enabled": false,
    "clarify_mode": "wizard",
    "inventory_clarifications": {}
  },
  "design_constraints": {
    "target_region": {
      "value": "us-east-1",
      "chosen_by": "extracted",
      "source": "inventory:region=us-east1",
      "prompt": "Detected: GCP region us-east1",
      "design_consequence": "All resources deploy in us-east-1; Bedrock model availability checked for this region",
      "question_id": "Q1"
    },
    "compliance": {
      "value": ["hipaa"],
      "chosen_by": "user",
      "prompt": "Do you have any compliance or regulatory requirements?",
      "design_consequence": "HIPAA drives BAA-eligible services, encryption mandatory, and us-east-1/us-west-2 region preference",
      "question_id": "Q2"
    },
    "gcp_monthly_spend": {
      "value": "$5K-$20K",
      "chosen_by": "extracted",
      "source": "billing:monthly_total=$8200",
      "prompt": "Detected: GCP monthly spend from billing-profile.json",
      "design_consequence": "$5K-$20K band sets dev-tier sizing baseline and credits eligibility context",
      "question_id": "Q3"
    },
    "availability": {
      "value": "multi-az",
      "chosen_by": "extracted",
      "source": "terraform:availability_type=REGIONAL",
      "prompt": "Detected: Cloud SQL REGIONAL → multi-AZ availability",
      "design_consequence": "multi-az drives RDS Multi-AZ or Aurora selection",
      "question_id": "Q6"
    },
    "cutover_strategy": {
      "value": "maintenance-window-weekly",
      "chosen_by": "user",
      "prompt": "When can you accept downtime for cutover?",
      "design_consequence": "Weekly maintenance window sets phased cutover timing in the migration plan",
      "question_id": "Q7"
    },
    "compute_model": {
      "value": "managed_platform",
      "chosen_by": "default",
      "source": "default:Q7b",
      "prompt": "What compute operational model do you prefer for your App Engine workloads? (default applied)",
      "design_consequence": "Assuming managed platform → App Engine maps to Elastic Beanstalk",
      "question_id": "Q7b"
    },
    "kubernetes": {
      "value": "ecs-fargate",
      "chosen_by": "default",
      "source": "default:Q8",
      "prompt": "How do you feel about Kubernetes? (default applied)",
      "design_consequence": "Assuming Fargate → no Kubernetes to operate",
      "question_id": "Q8"
    },
    "cpu_architecture": {
      "value": "graviton",
      "chosen_by": "default",
      "source": "default:Q11b",
      "prompt": "Target Graviton (ARM64) for eligible compute? (default applied)",
      "design_consequence": "Assuming Graviton → ARM64 instance families and Fargate/Lambda runtime platform",
      "question_id": "Q11b"
    },
    "database_traffic": {
      "value": "steady",
      "chosen_by": "extracted",
      "source": "inventory:db_tier=db-f1-micro",
      "prompt": "Detected: dev-tier Cloud SQL instance → steady traffic",
      "design_consequence": "Assuming steady traffic → size from current config, no read replicas",
      "question_id": "Q12"
    },
    "db_io_workload": {
      "value": "low",
      "chosen_by": "extracted",
      "source": "inventory:db_tier=db-f1-micro",
      "prompt": "Detected: dev-tier Cloud SQL instance → low I/O",
      "design_consequence": "Assuming low I/O → gp3 storage",
      "question_id": "Q13"
    },
    "db_size": {
      "value": "10-100GB",
      "chosen_by": "extracted",
      "source": "inventory:disk_size_gb=10",
      "prompt": "Detected: Cloud SQL disk_size=10GB",
      "design_consequence": "10-100GB → pgcopydb migration tooling",
      "question_id": "Q13b"
    }
  },
  "ai_constraints": {
    "ai_framework": {
      "value": ["direct"],
      "chosen_by": "extracted",
      "source": "ai-profile:integration.pattern=direct_sdk",
      "prompt": "Detected: direct SDK integration from ai-workload-profile.json",
      "design_consequence": "Direct SDK pattern → Converse API adapter with feature-flag cutover",
      "question_id": "Q14"
    },
    "ai_monthly_spend": {
      "value": "$500-$2K",
      "chosen_by": "user",
      "prompt": "Approximately how much do you spend on AI/ML per month?",
      "design_consequence": "$500-$2K band sets token volume and model tier assumptions",
      "question_id": "Q15"
    },
    "ai_priority": {
      "value": "balanced",
      "chosen_by": "default",
      "source": "default:Q16",
      "prompt": "What matters most for your AI workloads? (default applied)",
      "design_consequence": "Assuming balanced priority → Sonnet-class default model",
      "question_id": "Q16"
    },
    "ai_critical_feature": {
      "value": "none",
      "chosen_by": "default",
      "source": "default:Q17",
      "prompt": "Which AI capability is most critical? (default applied)",
      "design_consequence": "No specialized feature → Q16 priority decides the model",
      "question_id": "Q17"
    },
    "ai_token_volume": {
      "value": "low",
      "chosen_by": "default",
      "source": "default:Q18",
      "prompt": "What is your token volume and cost sensitivity? (default applied)",
      "design_consequence": "Assuming low volume → on-demand pricing, no provisioned throughput analysis",
      "question_id": "Q18"
    },
    "ai_model_baseline": {
      "value": "gemini-2.5-flash",
      "chosen_by": "extracted",
      "source": "ai-profile:models[0].model_id",
      "prompt": "Detected: primary production model from ai-workload-profile.json",
      "design_consequence": "Baseline model drives the Bedrock mapping and cost comparison",
      "question_id": "Q19"
    },
    "ai_vision": {
      "value": "text-only",
      "chosen_by": "extracted",
      "source": "ai-profile:capabilities_summary.vision=false",
      "prompt": "Detected: capabilities_summary shows no vision usage",
      "design_consequence": "Assuming text-only → full model catalog",
      "question_id": "Q20"
    },
    "ai_latency": {
      "value": "important",
      "chosen_by": "default",
      "source": "default:Q21",
      "prompt": "How important is AI response latency? (default applied)",
      "design_consequence": "Assuming <2s latency → Sonnet-class + streaming",
      "question_id": "Q21"
    },
    "ai_complexity": {
      "value": "moderate",
      "chosen_by": "default",
      "source": "default:Q22",
      "prompt": "How complex are your AI tasks? (default applied)",
      "design_consequence": "Assuming moderate complexity → Sonnet-class model",
      "question_id": "Q22"
    },
    "ai_capabilities_required": {
      "value": ["text_generation", "streaming"],
      "chosen_by": "derived",
      "prompt": "Derived from detected capabilities and your answers",
      "design_consequence": "Required capabilities union enforced in Bedrock model mapping and validation checklist"
    }
  },
  "startup_constraints": {
    "startup_program_status": {
      "value": "eligible_founders",
      "chosen_by": "user",
      "question_id": "Q27",
      "prompt": "Have you applied for AWS Activate credits?",
      "design_consequence": "Activate Founders ($5K) callout in report and STARTUP_PROGRAMS.md"
    }
  }
}
```

### Schema Rules

Full schema and constraint catalog: `references/shared/schema-preferences.md`.

1. Every entry in `design_constraints`, `ai_constraints`, and `startup_constraints` (when
   present) is an object with **`value`**, **`chosen_by`**, **`prompt`**, and
   **`design_consequence`** fields. Optional **`question_id`** when mapped to the Q1–Q27
   catalog. Optional **`source`** when `chosen_by` is `"extracted"` or `"default"`.
2. **`prompt`:** verbatim question from the fragment file when `chosen_by` is `"user"`;
   detection label when `"extracted"`; question + `" (default applied)"` when `"default"`;
   derivation label when `"derived"`.
3. **`design_consequence`:** one sentence from the fragment's Recommendation Impact for the
   selected answer, or the catalog template in `schema-preferences.md` with `[value]`
   substituted.
4. `chosen_by` values: `"user"` (explicitly answered or corrected on the sheet), `"default"`
   (documented default applied — includes sheet-confirmed defaults and "I don't know"
   answers), `"extracted"` (inferred from inventory), `"derived"` (computed from combination
   of answers + detected capabilities).
5. **`source` field on constraints:** Every constraint with `chosen_by: "extracted"` or
   `chosen_by: "default"` MUST include a `source` field. Extracted: raw provenance signal
   (prefix `terraform:`, `billing:`, `code:`, `inventory:`, `ai-profile:`, or artifact
   filename). Default: `"default:<Qid>"`. Omit `source` for `"user"` and `"derived"`. Report
   generation uses `source` prefixed `default:` to flag unverified assumptions.
6. Only write a key to `design_constraints` / `ai_constraints` if the answer produces a
   constraint. Absent keys mean "no constraint — Design decides."
7. Do not write null values. Do not omit `prompt` or `design_consequence` on any written
   constraint.
8. For billing-source inventories, `metadata.inventory_clarifications` records Category B
   answers.
9. `metadata.questions_skipped_early_exit` records questions skipped due to early-exit logic
   (e.g., Q8 skipped because the multi-cloud row resolved to "yes").
10. `metadata.questions_skipped_extracted` records questions resolved because inventory
    already provided the answer.
11. `metadata.questions_defaulted` records questions resolved by documented default — whether
    sheet-confirmed (wizard) or skipped (full flow / "use defaults").
12. `metadata.questions_skipped_not_applicable` records questions skipped because the
    relevant service wasn't in the inventory or their firing condition wasn't met.
13. `ai_constraints` section is present ONLY if Category F fired. Omit entirely if no AI
    artifacts exist.
14. `ai_constraints.ai_capabilities_required` is the UNION of detected capabilities from
    `ai-workload-profile.json` + critical feature from Q17 + vision from Q20. `chosen_by` is
    `"derived"`.
15. `ai_constraints.ai_framework` is an array (Q14 is select-all-that-apply). If
    auto-detected, `chosen_by` is `"extracted"` with `source`.
16. `metadata.clarify_mode` is one of `"wizard"`, `"full"`, `"fast_path"`,
    `"simple_hybrid"`.

After writing `preferences.json`, delete `$MIGRATION_DIR/preferences-draft.json` and
`$MIGRATION_DIR/preferences-superseded.json` if they exist (the superseded backup has served
its purpose once a new complete file exists).

## Defaults Table

Documented defaults for every question. Used by: PROPOSED sheet rows (wizard), per-question
skips, "use defaults for the rest", and the fast paths.

| Question                   | Default                                                                                                           | Constraint                                                                                                                                                                                           |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1 — Location              | 1 (single region)                                                                                                 | `target_region`: closest AWS region to GCP region                                                                                                                                                    |
| Q2 — Compliance            | unknown (unconfirmed)                                                                                             | `compliance: ["unknown"]` — treated as no-constraint for service selection; report caveat _(essential — defaulted only via "use defaults for the rest")_                                             |
| Q3 — GCP spend             | 2 ($1K–$5K)                                                                                                       | `gcp_monthly_spend: "$1K-$5K"` _(essential when no billing — same caveat rule as Q2)_                                                                                                                |
| Q3.5 — GCP CUDs            | 5 (none)                                                                                                          | `cud_status: "none"` _(essential when it fires — billing shows CUDs, so only defaulted via "use defaults for the rest")_                                                                             |
| Q4 — Funding stage         | _(skip in IDE mode)_                                                                                              | no constraint                                                                                                                                                                                        |
| Q5 — Multi-cloud           | 2 (AWS-only)                                                                                                      | no constraint                                                                                                                                                                                        |
| Q6 — Availability          | 2 (significant) — GCP-specific default; see `references/vendored/clarify/clarify-availability.md` § 2             | `availability: "multi-az"`                                                                                                                                                                           |
| Q7 — Maintenance           | 4 (flexible)                                                                                                      | `cutover_strategy: "flexible"`                                                                                                                                                                       |
| Q7b — Compute model        | 1 (managed platform)                                                                                              | `compute_model: "managed_platform"` (App Engine only; N/A if no App Engine, or if the multi-cloud row = yes → App Engine routes to EKS)                                                              |
| Cat B — Cloud SQL HA       | Zonal                                                                                                             | `metadata.inventory_clarifications`                                                                                                                                                                  |
| Cat B — Cloud Run count    | 1 service                                                                                                         | `metadata.inventory_clarifications`                                                                                                                                                                  |
| Cat B — Memorystore memory | estimate from usage                                                                                               | `metadata.inventory_clarifications`                                                                                                                                                                  |
| Cat B — Functions gen      | Gen 1                                                                                                             | `metadata.inventory_clarifications`                                                                                                                                                                  |
| Q8 — K8s sentiment         | 3 (Fargate)                                                                                                       | `kubernetes: "ecs-fargate"`                                                                                                                                                                          |
| Q9 — WebSocket             | 2 (no)                                                                                                            | no constraint                                                                                                                                                                                        |
| Q10 — Cloud Run traffic    | 3 (24/7)                                                                                                          | `cloud_run_traffic_pattern: "constant-24-7"`                                                                                                                                                         |
| Q11 — Cloud Run spend      | 2 ($100–$500)                                                                                                     | `cloud_run_monthly_spend: "$100-$500"`                                                                                                                                                               |
| Q11b — CPU architecture    | 1 (Graviton)                                                                                                      | `cpu_architecture: "graviton"` (or `"mixed"` if any service is incompatible; `"x86"` if no compatible compute) — usually auto-defaulted without asking; see `clarify-compute.md` Q11b decision table |
| Q12 — DB traffic           | 1 (steady)                                                                                                        | `database_traffic: "steady"`                                                                                                                                                                         |
| Q13 — DB I/O               | 2 (medium)                                                                                                        | `db_io_workload: "medium"`                                                                                                                                                                           |
| Q13b — DB size             | 5 (unknown)                                                                                                       | `db_size: "unknown"` → default to pgcopydb                                                                                                                                                           |
| Q14 — AI framework         | _(auto-detect)_                                                                                                   | `ai_framework` from code detection, fallback `["direct"]`                                                                                                                                            |
| Q15 — AI spend             | 2 ($500–$2K)                                                                                                      | `ai_monthly_spend: "$500-$2K"` _(essential — defaulted only via "use defaults for the rest")_                                                                                                        |
| Q16 — AI priority          | 5 (balanced)                                                                                                      | `ai_priority: "balanced"`                                                                                                                                                                            |
| Q17 — Critical feature     | 10 (none)                                                                                                         | no additional override                                                                                                                                                                               |
| Q18 — Volume + cost        | 1 (low + quality)                                                                                                 | `ai_token_volume: "low"`                                                                                                                                                                             |
| Q19 — Current model        | _(auto-detect)_                                                                                                   | `ai_model_baseline` from code detection                                                                                                                                                              |
| Q20 — Input types          | 1 (text only)                                                                                                     | no constraint                                                                                                                                                                                        |
| Q21 — AI latency           | 2 (important)                                                                                                     | `ai_latency: "important"`                                                                                                                                                                            |
| Q22 — Task complexity      | 2 (moderate)                                                                                                      | `ai_complexity: "moderate"`                                                                                                                                                                          |
| Q23 — Agentic approach     | _(framework-based auto-detect; see `clarify-ai.md`)_                                                              | `ai_constraints.agentic.migration_approach`                                                                                                                                                          |
| Q24 — Agent memory         | 2 (session)                                                                                                       | `ai_constraints.agentic.memory_requirement: "session"`                                                                                                                                               |
| Q25 — Task duration        | 2 (medium)                                                                                                        | `ai_constraints.agentic.task_duration: "medium"`                                                                                                                                                     |
| Q26 — Incremental          | path-based                                                                                                        | `incremental_migration`: `true` for Harness path, `false` for retarget                                                                                                                               |
| Q27 — Activate credits     | _(essential when Category H fires — ask in Gate 2; skip only via explicit answer or "use defaults for the rest")_ | `startup_program_status` per answer; skip → `"unknown"` with neutral downstream copy                                                                                                                 |
| Q-E1 — HA upgrade          | 2 (no)                                                                                                            | `ha_upgrade: false`                                                                                                                                                                                  |
| Q-E2 — Right-sizing        | 2 (no)                                                                                                            | `right_sizing: false`                                                                                                                                                                                |

## Validation Checklist

Before handing off to Design:

- [ ] In wizard mode, the Gate 1 Assumption Sheet was shown (detected + assumed sections) and
      the user responded before any essential question was asked
- [ ] Every constraint with `chosen_by: "extracted"` or `chosen_by: "default"` has a `source`
      field with the correct prefix (`terraform:`, `billing:`, `inventory:`, `ai-profile:`,
      or `default:<Qid>`)
- [ ] Essential questions (Q2, Q7, and conditional Q1/Q3/Q3.5/**Q27**/Q15/Q23–Q25/conflicts)
      were asked, answered, or explicitly defaulted via "use defaults for the rest"
- [ ] The Answer Recap was shown after the final Gate 2 batch (including defaulted rows on
      "use defaults for the rest") and the user responded to it before Category E /
      `preferences.json`
- [ ] If `bigquery_present` was **true**, the mandatory BigQuery specialist advisory was
      shown before questions — **or**, if `clarify.md` Step 0 option 1 (reuse preferences),
      the same advisory was shown after BigQuery detection
- [ ] `preferences.json` written to `$MIGRATION_DIR/`
- [ ] `design_constraints.target_region` is populated with `value` and `chosen_by`
- [ ] `design_constraints.compliance` is populated (never silently absent — the compliance
      question always fires per `references/vendored/clarify/clarify-compliance.md`)
- [ ] `design_constraints.availability` is populated when Cloud SQL PostgreSQL/MySQL is in
      inventory (asked, extracted, or defaulted — Design must not run with absent/null
      availability)
- [ ] If compute resources are present, `design_constraints.cpu_architecture` is set to
      `graviton`, `x86`, or `mixed` per the Q11b decision table
- [ ] Only keys with non-null values are present in `design_constraints`
- [ ] Every entry in `design_constraints` and `ai_constraints` has `value` and `chosen_by`
      fields
- [ ] Config gap answers recorded in `metadata.inventory_clarifications` (billing mode only)
- [ ] Early-exit skips recorded in `metadata.questions_skipped_early_exit`
- [ ] `ai_constraints` section present ONLY if Category F fired
- [ ] If Category F fired, `ai_constraints.ai_framework` is populated (from detection or Q14)
- [ ] If Category F fired, `ai_capabilities_required` is derived from detection + Q17 + Q20
- [ ] `ai_constraints.ai_framework` is an array (Q14 is multi-select)
- [ ] Output is valid JSON
- [ ] `preferences-draft.json` has been deleted (if it existed)
- [ ] `metadata.clarify_mode` is set to `"wizard"`, `"full"`, `"fast_path"`, or
      `"simple_hybrid"`

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** before checking.

**Re-entry guard:** If `aws-design.json` (or `aws-design-ai.json` / `aws-design-billing.json`)
exists and `phases.design` is `"completed"`: STOP unless the user explicitly confirms
re-running Clarify. Emit `GATE_FAIL | phase=clarify | field=aws-design.json |
reason=stale_downstream`.

**Checks (all must PASS):**

1. `preferences.json` exists and parses as JSON.
2. Validation Checklist items above all pass (including `metadata.clarify_mode`).
3. If `gcp-resource-inventory.json` contains `google_sql_database_instance` →
   `design_constraints.availability.value` is set (non-null, non-empty).
4. If `metadata.clarify_mode` is `"wizard"` → at least one constraint has a `source` field OR
   every active question was essential.
5. **No sheet/question mixing:** `metadata.questions_asked` contains no question ID that also
   appears in `metadata.questions_skipped_extracted` or `metadata.questions_defaulted`. (A
   question may move between lists only if the user converted its sheet row — in which case
   the override handling moved it to `questions_asked`.)
6. If compute resources are present (Cloud Run, Cloud Functions, GKE, GCE in
   `gcp-resource-inventory.json`, or billing-source compute) → `design_constraints
   .cpu_architecture.value` is set (`graviton` | `x86` | `mixed`), per the Q11b decision table
   in `clarify-compute.md` — written even when Q11b was auto-defaulted.
7. **Extraction consistency — Q13b** _(skip this check when `metadata.clarify_mode` is
   `"full"` — the user explicitly opted into the full question flow)_: If every
   `google_sql_database_instance` in `gcp-resource-inventory.json` carries an unambiguous disk
   size (`config.disk_size_gb` or legacy variants, all mapping to the same Q13b band) →
   `Q13b` must NOT appear in `metadata.questions_asked` unless `design_constraints.db_size
   .chosen_by` is `"user"` (the user converted the sheet row via "ask me about X" or corrected
   it). If instances map to **different** bands (e.g. an 8 GB dev instance and a 200 GB prod
   instance), the size is ambiguous — this check does NOT fire, and asking Q13b is the
   expected behavior (matching the `clarify-database.md` auto-detect rule "if multiple
   instances disagree, ask Q13b"). Otherwise: `GATE_FAIL | phase=clarify |
   field=metadata.questions_asked | reason=extractable_question_asked_Q13b`.
8. **Extraction consistency — Q19** _(skip when `metadata.clarify_mode` is `"full"`)_: If
   `ai-workload-profile.json` exists with `models[0].model_id` set at confidence ≥ 0.8 →
   `Q19` must NOT appear in `metadata.questions_asked` unless `ai_constraints
   .ai_model_baseline.chosen_by` is `"user"`. Otherwise: `GATE_FAIL | phase=clarify |
   field=metadata.questions_asked | reason=extractable_question_asked_Q19`. (Detect-confirm
   cards for sub-threshold or tied detection per `clarify-ai.md` are not affected — they fire
   only when confidence < 0.8.)

**On any FAIL:** Emit `GATE_FAIL | phase=clarify | field=<path> | reason=missing`. **Do NOT
modify artifacts to pass the gate.** **Do NOT update `.phase-status.json`.** Tell the user to
answer the missing question or re-run Clarify.

**On PASS:** Emit `HANDOFF_OK | phase=clarify | artifacts=preferences.json`.

## Step 6: Update Phase Status

Only after `HANDOFF_OK`. In the **same turn** as the output message below, use the Phase
Status Update Protocol (Write tool) to write `.phase-status.json` with `phases.clarify` set
to `"completed"`.

Output to user: "Phase 2 of 6 complete (Clarify). Remaining: Design → Estimate → Generate (+
optional Feedback). Next artifact: aws-design.json. Proceeding to Phase 3: Design AWS
Architecture."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from
inner workshop reprices._

## Scope Boundary

**This phase covers requirements gathering ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Detailed AWS architecture or service configurations
- Code migration examples or SDK snippets
- Detailed cost calculations
- Migration timelines or execution plans
- Terraform generation

**Your ONLY job: Understand what the user needs. Nothing else.**

## Status — build step 5 (restructure)

Implemented. This file absorbs everything the prior monolithic `clarify.md` did after
extraction — the Assumption Sheet, the essential-questions batching, the Answer Recap,
Category E, the Full Flow variant, the `preferences.json` write, the Defaults Table, the
Validation Checklist, and the Completion Handoff Gate — matching the responsibility split
`azure-to-aws`'s `clarify-assemble.md` already has, adapted to GCP's larger built-in
structure (fast paths, Full Flow opt-out, Category E) that Azure's assembler does not need.
No firing rule, default, or interpretation rule changed in this move.
