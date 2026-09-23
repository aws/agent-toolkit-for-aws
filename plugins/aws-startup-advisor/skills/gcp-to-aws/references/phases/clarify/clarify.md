# Phase 2: Clarify Requirements

**Phase 2 of 6** — Confirm assumptions and ask only essential questions before design begins, then interpret answers into ready-to-apply design constraints.

> **HARD GATE — Clarify before Design:** Do not load `references/phases/design/design.md` (or any later phase) until this phase finishes **and** `$MIGRATION_DIR/.phase-status.json` records `phases.clarify` as `"completed"`. Writing `preferences.json` without updating phase status is a protocol violation. If the user asks to skip questions, use documented defaults and still complete this phase (including phase status).

The output — `preferences.json` — is consumed directly by Design and Estimate without any further interpretation.

The question catalog spans **six named categories (A–F)** plus agentic (G) and startup-program (H) questions — Q1–Q27 plus conditional prompts. The default flow is the **Assumption-Sheet Wizard**: values extracted from discovery and documented defaults are presented in a single confirm-or-edit sheet (with the design consequence of each assumption), and only the **essential questions** (typically 2–7) are asked directly. The full question-by-question flow remains available via **"ask me everything."** A standalone **AI-Only** flow exists for migrations that only move AI/LLM calls to Bedrock.

## Category Reference Files

| File                  | Category                                  | Questions                  | Loaded When                                     |
| --------------------- | ----------------------------------------- | -------------------------- | ----------------------------------------------- |
| `clarify-global.md`   | A — Global/Strategic                      | Q1–Q7                      | Always                                          |
| `clarify-compute.md`  | B — Config Gaps, C — Compute              | Q7b–Q11b                   | Compute or billing-source resources present     |
| `clarify-database.md` | D — Database                              | Q12–Q13b                   | Database resources present                      |
| `clarify-ai.md`       | F — AI/Bedrock, G — Agentic, H — Programs | Q14–Q27                    | `ai-workload-profile.json` exists               |
| `clarify-ai-only.md`  | _(standalone)_                            | Q1–Q11 (+ Q1.5 compliance) | AI-only migration (no infrastructure artifacts) |

---

## Step 0: Prior Run Check

Check `$MIGRATION_DIR/` for existing state:

**Case 1 — Completed preferences exist** (`preferences.json` present):

**Compatibility check (run BEFORE offering reuse):** The existing file may predate the current flow, and the Completion Handoff Gate forbids patching artifacts to pass — so an incompatible file offered for reuse dead-ends at `GATE_FAIL`. Check:

1. **Schema currency** — `metadata.clarify_mode` is present; every constraint has `value`, `chosen_by`, `prompt`, and `design_consequence`; every constraint with `chosen_by: "extracted"` or `"default"` has a `source` field; `design_constraints.cpu_architecture` is present when compute resources exist in the current inventory.
2. **Discovery match** — the file's `metadata.discovery_artifacts` is consistent with what exists in `$MIGRATION_DIR` now: if `ai-workload-profile.json` exists but the file has no `ai_constraints` (or the reverse), or the inventory has database/compute resources whose required constraints (`availability`, `db_size`) are absent, the file is stale relative to current discovery.

**If both pass**, offer:

> "I found existing migration preferences from a previous run. Would you like to:"
>
> 1. Re-use these preferences and skip questions
> 2. Start fresh and re-answer all questions

- If 1: Run Step 2 item 6 only (BigQuery detection) on current discovery artifacts. If `bigquery_present` is **true**, output the Step 4 **BigQuery / deferred analytics** advisory block once (even though questions are skipped), then skip to Validation Checklist with the existing `preferences.json`.
- If 2: rename `preferences.json` to `preferences-superseded.json` (do not delete — prior answers are unrecoverable otherwise), continue to Step 1.

**If either check fails**, do NOT offer plain reuse — it would fail the gate. Instead:

> "I found preferences from a previous run, but they predate the current flow (missing: [list]). Would you like to:"
>
> 1. Keep your previous answers where they're still valid — I'll confirm them on the assumption sheet and only ask what's new or missing
> 2. Start fresh and re-answer all questions

- If 1: rename the old file to `preferences-superseded.json`, seed the wizard from it — carry each still-valid constraint value forward with its original `chosen_by` (backfilling `prompt`/`design_consequence`/`source` from the current catalog), treat missing constraints as unresolved — and continue to Step 1 (the wizard fills the gaps; carried-forward values appear on the Assumption Sheet for confirmation).
- If 2: rename to `preferences-superseded.json`, continue to Step 1.

**Case 2 — Draft preferences exist** (`preferences-draft.json` present, no `preferences.json`):

> "I found a partial set of answers from a previous session. Would you like to:"
>
> 1. Resume from where you left off — I'll pick up the remaining questions
> 2. Start fresh and re-answer all questions

- If 1: load the draft. If `metadata.wizard_stage` is present, resume at that stage (`"sheet_pending"` → re-present the Assumption Sheet; `"essentials_pending"` → re-present unanswered essential questions). If the draft has the legacy `metadata.batches_completed` field instead (pre-wizard flow), tell the user the flow has changed and offer: keep answered values and continue with the wizard for the rest, or start fresh.
- If 2: delete `preferences-draft.json`, continue to Step 1.

**Case 3 — No prior state**: Continue to Step 1.

---

## Step 1: Read Inventory and Determine Migration Type

Read `$MIGRATION_DIR/` and check which discovery outputs exist:

- `gcp-resource-inventory.json` + `gcp-resource-clusters.json` — infrastructure discovered
- `ai-workload-profile.json` — AI workloads detected
- `billing-profile.json` — billing data parsed

At least one discovery artifact must exist to proceed.

### Migration Type Detection

- **Full migration**: `gcp-resource-inventory.json` or `billing-profile.json` exists (may also have `ai-workload-profile.json`)
- **AI-only migration**: ONLY `ai-workload-profile.json` exists (no infrastructure or billing artifacts)

**If AI-only**: Read `clarify-ai-only.md` NOW and follow that flow. Skip all remaining steps below.

> **HARD GATE — AI-Only Path:** You MUST read `clarify-ai-only.md` before presenting any questions. The question text, answer options, and interpretation rules are ONLY in that file — they are NOT in this file. Do NOT fabricate questions from the summaries above.

### Discovery Summary

Present a discovery summary:

**If `gcp-resource-inventory.json` exists:**

> **Infrastructure discovered:** [total resources] GCP resources across [cluster count] clusters
> **Top resource types:** [list top 3–5 types]

**If `ai-workload-profile.json` exists:**

> **AI workloads detected:** [from `models[].model_id`]
> **Capabilities in use:** [from `integration.capabilities_summary` where true]
> **Integration pattern:** [from `integration.pattern`] via [from `integration.primary_sdk`]

**If `billing-profile.json` exists:**

> **Monthly GCP spend:** $[total_monthly_spend]
> **Top services by cost:** [top 3–5 from billing data]

---

## Step 1.5: Fast-Path Gate (Simple Stacks)

**After presenting the Discovery Summary**, check `$MIGRATION_DIR/migration-preview.json` for fast-path eligibility:

```
IF migration-preview.json exists
   AND eligible_for_clarify_fast_path == true
THEN offer infra fast-path (3 questions)
ELSE IF eligible_for_clarify_simple_path == true
THEN offer simple hybrid path (~6 questions)
ELSE proceed to Step 2 (Assumption-Sheet Wizard)
```

### Infra fast-path (no AI)

**If `eligible_for_clarify_fast_path`**, present this offer before any questions:

> "Your stack looks straightforward — [primary_resource_count] resource(s), no database, no AI detected.
>
> Want to use smart defaults and answer just 3 questions (target region, compliance requirements, maintenance window)?
>
> **[Yes — 3 questions]** / **[No — ask me everything]**"

**If user chooses Yes:**

1. Ask only: **Q1** (region), **Q2** (compliance), **Q7** (maintenance window) — from `clarify-global.md`.
2. Apply documented defaults for ALL other questions. Record each in `metadata.questions_defaulted`.
3. Still run the BigQuery advisory if `bigquery_present` is true.
4. Write `preferences.json` with `metadata.clarify_mode: "fast_path"`. Skip Steps 2–4.

### Simple hybrid path (simple infra + lightweight AI)

**If `eligible_for_clarify_simple_path`**, present:

> "Your stack looks straightforward with lightweight AI ([model IDs from profile]) — no agentic framework detected.
>
> Want a short question set (~6 questions) instead of the full flow? I'll use discovery for region, database sizing, and model detection.
>
> **[Yes — short path]** / **[No — ask me everything]**"

**If user chooses Yes:**

1. Run **Step 2 extraction** (mandatory — do not skip).
2. Run **Step 2.5 Assumption Sheet** (mandatory — wait for user response).
3. Ask only questions **not** resolved by extraction (after any user corrections):
   - **Q2** (compliance) — always ask
   - **Q7** (maintenance window) — always ask
   - **Q16** (AI priority) — from `clarify-ai.md`
   - **Q21** (AI latency) — from `clarify-ai.md`
   - **Q3** (GCP spend) — only if billing did not extract it
   - **Q1** (region) — only if region extraction ambiguous (multiple GCP regions)
4. Apply documented defaults for all other unanswered questions. Record in `metadata.questions_defaulted`.
5. Write `preferences.json` with `metadata.clarify_mode: "simple_hybrid"`. Skip Step 4 — go to Category E opt-in (if applicable) then Step 5.

**Agentic hard block:** If `agentic_profile.is_agentic == true`, **never offer** infra fast-path or simple hybrid path. Agentic workloads require Q23–Q26 (asked as essential questions in the wizard).

**If user chooses No, or neither path is eligible:** Continue to Step 2 (the wizard is the default full flow).

---

## Step 2: Extract Known Information

Before generating the Assumption Sheet, scan the inventory to extract values that are already known:

1. **GCP regions** — Extract all GCP regions from the inventory. Map to the closest AWS region as a suggested default for Q1.
2. **Resource types present** — Build a set of resource types: compute (Cloud Run, Cloud Functions, GKE, GCE), database (Cloud SQL, Spanner, Memorystore), storage (Cloud Storage), messaging (Pub/Sub).
3. **Billing SKUs** — If `billing-profile.json` exists, check if any SKU reveals storage class, HA configuration, or other answerable questions.
4. **Billing-only mode** — If `billing-profile.json` exists and `gcp-resource-inventory.json` does NOT exist, check `billing-profile.json → services[]` for Category B question matching.
5. **AI framework detection** — If `ai-workload-profile.json` exists, check `integration.gateway_type` and `integration.frameworks` for auto-detection of Q14 answer.
6. **BigQuery / analytics warehouse** — Set `bigquery_present` to **true** if **any** of: (a) a resource in `gcp-resource-inventory.json` has `gcp_type` (or equivalent type field) starting with `google_bigquery_`; (b) `billing-profile.json` lists a service/SKU that clearly indicates **BigQuery** (e.g., service name or SKU contains `BigQuery`). Otherwise `bigquery_present` is **false**.
7. **Database size auto-detect (Q13b)** — For each `google_sql_database_instance`, read `config.disk_size_gb` (canonical per `schema-discover-iac.md`; also accept legacy `config.disk_size` or `gcp_config.disk_size_gb` from older inventories). This is **allocated capacity — an upper bound on actual data size** (Cloud SQL's minimum allocation is 10 GB, so small dev databases still read as 10). The band is safe for tool selection (never underestimates), but present it on the sheet as allocated — "up to [N] GB (allocated)" — and accept a user's downward correction without pushback. Map to Q13b band and **resolve Q13b** when unambiguous:

| Disk size (GB) | `db_size` value | Resolve Q13b?                  |
| -------------- | --------------- | ------------------------------ |
| < 10           | `"<10GB"`       | Yes — `chosen_by: "extracted"` |
| 10 – 99        | `"10-100GB"`    | Yes — `chosen_by: "extracted"` |
| 100 – 499      | `"100-500GB"`   | Yes — `chosen_by: "extracted"` |
| ≥ 500          | `">500GB"`      | Yes — `chosen_by: "extracted"` |

If multiple instances disagree, mark Q13b as an essential question. Record in `metadata.inventory_clarifications.db_size_gb` when extracted.

1. **Q6 from Cloud SQL HA** — For each `google_sql_database_instance`, read `availability_type` (or `config.availability_type`):

| GCP value  | `availability` extracted |
| ---------- | ------------------------ |
| `ZONAL`    | `"single-az"`            |
| `REGIONAL` | `"multi-az"`             |

Resolve Q6 only when **all** Cloud SQL PostgreSQL/MySQL instances agree on the same mapped value. **`multi-az-ha` and `multi-region` are never auto-extracted** — those require Q6 user answers (Mission-Critical / Catastrophic). Cloud SQL `REGIONAL` maps to `multi-az` (RDS Multi-AZ), not `multi-az-ha` (Aurora). Record in `metadata.inventory_clarifications.cloud_sql_ha`. When `availability_type` is missing on any instance, or instances disagree, mark Q6 as an essential question.

1. **Q12/Q13 dev-tier defaults** — When **all** Cloud SQL instances match dev pattern (`db-f1-micro`, `db-g1-small`, or `tier` contains `micro`/`small` with `availability_type: ZONAL`), extract and **resolve Q12 and Q13**. When instances mix dev and prod tiers, do not extract — mark Q12 and Q13 as essential questions.

```
database_traffic: "steady" — chosen_by: "extracted"
db_io_workload: "low" — chosen_by: "extracted"
```

1. **Q3 GCP spend from billing** — If `billing-profile.json` exists, map `summary.total_monthly_spend` to spend band and **resolve Q3** when unambiguous:

| Monthly USD   | `gcp_monthly_spend` |
| ------------- | ------------------- |
| < 1,000       | `"<$1K"`            |
| 1,000–4,999   | `"$1K-$5K"`         |
| 5,000–19,999  | `"$5K-$20K"`        |
| 20,000–99,999 | `"$20K-$100K"`      |
| ≥ 100,000     | `">$100K"`          |

1. **Q1 region extraction** — When inventory has a **single** GCP region among PRIMARY compute/database resources, map to closest AWS region and **resolve Q1** with `target_region` `chosen_by: "extracted"`. When multiple regions, suggest default but mark Q1 as an essential question.

1. **Q19 primary model** — If `ai-workload-profile.json` exists and `models[0].model_id` is set with confidence ≥ 0.8, map to Q19 answer and **resolve Q19**. Set `ai_model_baseline` with `chosen_by: "extracted"`.

1. **Q20 input modalities** — If `integration.capabilities_summary` exists:

| Signal                               | Extract                                                                           | Resolve Q20?                                                |
| ------------------------------------ | --------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `vision: true`                       | `ai_vision: "vision-required"`                                                    | Yes                                                         |
| `image_generation: true` (no vision) | note in `ai_capabilities_required`; Q20 may still ask unless text-only path clear | Partial — resolve if only text + image gen via separate API |
| all false / text only                | `ai_vision: "text-only"`                                                          | Yes                                                         |

When `image_generation: true` and `vision: false`, set `ai_capabilities_required` derived from profile and resolve Q20 (image output is not vision _input_).

1. **Q9 WebSocket scan** — Only when application code was **actually analyzed**. Treat code as analyzed when **any** of: (a) `discover-app-code.md` ran and found source files; (b) `ai-workload-profile.json` → `metadata.sources_analyzed.application_code == true`; (c) a companion app directory was scanned. Scan for WebSocket usage: `websocket`, `WebSocket`, `socket.io`, `@nestjs/websockets`, FastAPI WebSocket, `ws` package imports. If code was analyzed and **no matches**, extract `websocket: false` and **resolve Q9**. If matches found, mark Q9 as an essential question to confirm.
   **If no application code was available** (Terraform-only workspace, no code discovery), do **NOT** extract Q9 — Q9 becomes a **proposed-default sheet row** (see Step 3 catalog), flagged so the user can correct it. Absence of a code scan is not evidence of no WebSockets.

1. **Q10 Cloud Run traffic** — If Cloud Run `min_instance_count` / `min_instances` > 0 in Terraform config, extract `cloud_run_traffic_pattern: "constant-24-7"` and resolve Q10. Otherwise Q10 becomes a proposed-default sheet row.

1. **Multi-instance Cloud SQL conflicts** — When multiple `google_sql_database_instance` resources **disagree** on values used for Q6, Q12/Q13, or Q13b (e.g. one ZONAL and one REGIONAL; mixed dev/prod tiers; different disk sizes):
   - Do **not** extract a single global value or propose a default for the affected question(s)
   - Record per-instance values in `metadata.inventory_clarifications.cloud_sql_instances[]` (address, `availability_type`, `tier`, `disk_size_gb`)
   - In Step 2.5, show a **per-instance breakdown** (see below) instead of a single summary row
   - Mark the affected question(s) as essential, or let the user pick a global posture during Step 2.5 confirmation

Record all extracted values in `metadata.inventory_clarifications` where applicable. Questions fully resolved by extraction appear as **Detected** rows on the Assumption Sheet with `chosen_by: "extracted"` and are listed in `metadata.questions_skipped_extracted`.

**After Step 2 completes, proceed to Step 3 (build the sheet), then Step 2.5 (present it). Do not ask any question before the sheet is confirmed.**

---

## Step 3: Question Disposition Catalog

### Category Firing Rules

| Category | Name               | Firing Rule                                                                    | Reference File        | Questions                                                                                                                                                                                            |
| -------- | ------------------ | ------------------------------------------------------------------------------ | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A**    | Global/Strategic   | **Always fires**                                                               | `clarify-global.md`   | Q1 (location), Q2 (compliance), Q3 (GCP spend), Q3.5 (CUDs), Q4 (skipped), Q5 (multi-cloud), Q6 (uptime), Q7 (maintenance)                                                                           |
| **B**    | Configuration Gaps | `billing-profile.json` exists AND `gcp-resource-inventory.json` does NOT exist | `clarify-compute.md`  | Cloud SQL HA, Cloud Run count, Memorystore memory, Functions gen                                                                                                                                     |
| **C**    | Compute Model      | Compute resources present (Cloud Run, Cloud Functions, GKE, GCE, App Engine)   | `clarify-compute.md`  | Q7b (compute model), Q8 (K8s sentiment), Q9 (WebSocket), Q10 (Cloud Run traffic), Q11 (Cloud Run spend), Q11b (Graviton/ARM64 — see decision table; auto-defaults `cpu_architecture` when not asked) |
| **D**    | Database Model     | Database resources present (Cloud SQL, Spanner, Memorystore)                   | `clarify-database.md` | Q12 (DB traffic pattern), Q13 (DB I/O), Q13b (DB size)                                                                                                                                               |
| **E**    | Migration Posture  | **Disabled by default** — requires explicit user opt-in                        | _(inline below)_      | HA upgrades, right-sizing                                                                                                                                                                            |
| **F**    | AI/Bedrock         | `ai-workload-profile.json` exists                                              | `clarify-ai.md`       | Q14–Q22                                                                                                                                                                                              |
| **G**    | Agentic            | `agentic_profile.is_agentic == true`                                           | `clarify-ai.md`       | Q23–Q26                                                                                                                                                                                              |
| **H**    | Startup Programs   | Fires with Category F                                                          | `clarify-ai.md`       | Q27                                                                                                                                                                                                  |

**If no IaC, billing data, or code is available** (empty discovery): only Category A is active. All service-specific categories are skipped.

### HARD GATE — Read Category Files Before Proceeding

> **STOP. You MUST read each active category's file NOW, before building the sheet or asking any question.**
>
> The exact question wording, answer options, context rationale, and interpretation rules exist ONLY in the category files. The catalog below defines only each question's **disposition** (essential vs sheet row), its **default**, and its **consequence line**. Do NOT fabricate question text from this file.
>
> | Active Category | File to Read          |
> | --------------- | --------------------- |
> | A (always)      | `clarify-global.md`   |
> | B or C          | `clarify-compute.md`  |
> | D               | `clarify-database.md` |
> | F, G, H         | `clarify-ai.md`       |

### Disposition Catalog

> **Maintenance note:** The defaults and consequence lines below mirror the `Default:` lines in the category files. When a category file changes a default or adds an answer option, update the matching catalog row **in the same commit**. (Long-term, consequence strings may move into the category files to eliminate this duplication — see PR discussion.)

Every question in an **active** category gets exactly one disposition:

- **DETECTED** — Step 2 resolved it. Sheet row, `chosen_by: "extracted"`.
- **PROPOSED** — Documented default applied. Sheet row with consequence line, `chosen_by: "default"`.
- **ESSENTIAL** — No safe default. Asked directly in Step 4.
- **N/A** — Category or firing condition not met. Listed in `metadata.questions_skipped_not_applicable`.

| Q     | Disposition rule                                                                                                                 | Default (when PROPOSED)              | Consequence line for the sheet                                                                                                                                                                                                                  |
| ----- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1    | DETECTED when single-region extraction succeeded; **ESSENTIAL** when multiple regions or no inventory                            | —                                    | All AWS resources deploy to this region; drives latency and service availability                                                                                                                                                                |
| Q2    | **ESSENTIAL — always**                                                                                                           | —                                    | — (gates security baseline, regions, and service catalog; never assumed)                                                                                                                                                                        |
| Q3    | DETECTED when billing extraction succeeded; **ESSENTIAL** when no billing data                                                   | —                                    | Anchors the AWS-vs-GCP savings comparison and dev-tier sizing baseline                                                                                                                                                                          |
| Q3.5  | **ESSENTIAL** when it fires (billing shows active CUDs); N/A otherwise                                                           | —                                    | — (billing already shows active commitments; assuming "none" would be wrong)                                                                                                                                                                    |
| Q4    | N/A in wizard mode (funding not inferred from spend); optional in full flow                                                      | —                                    | —                                                                                                                                                                                                                                               |
| Q5    | PROPOSED                                                                                                                         | 2 — AWS-only                         | Assuming AWS-only → ECS Fargate eligible; if multi-cloud portability is required, all containers go to EKS instead                                                                                                                              |
| Q6    | DETECTED when all Cloud SQL instances agree; **ESSENTIAL** on conflict/missing; PROPOSED when no Cloud SQL signal but DB present | 2 — `multi-az`                       | Assuming Multi-AZ RDS → automatic failover, roughly 2x single-AZ database cost; say "single-az" for dev-grade, "mission-critical" for Aurora (**unconfirmed default — roughly halves or doubles the database estimate; flagged in the report**) |
| Q7    | **ESSENTIAL — always**                                                                                                           | —                                    | — (cutover strategy selects DMS vs pg_dump/pgcopydb and the entire migration runbook shape; never assumed)                                                                                                                                      |
| Q7b   | PROPOSED when App Engine present and Q5 ≠ multi-cloud; N/A otherwise                                                             | 1 — `managed_platform`               | Assuming managed platform → App Engine maps to Elastic Beanstalk; say "container orchestration" for ECS Fargate or "serverless" for Lambda                                                                                                      |
| Cat B | PROPOSED (each prompt, billing-only mode)                                                                                        | Zonal / 1 service / estimate / Gen 1 | Fills config gaps billing can't answer; corrections here change sizing inputs                                                                                                                                                                   |
| Q8    | PROPOSED (only when GKE present and Q5 ≠ multi-cloud)                                                                            | 3 — `ecs-fargate`                    | Assuming Fargate → no Kubernetes to operate; answer "EKS" to preserve your K8s investment                                                                                                                                                       |
| Q9    | DETECTED when code scan found none; ESSENTIAL when scan found matches (confirm); PROPOSED when no code was analyzed              | 2 — no WebSockets                    | Assuming no WebSockets → standard ALB config; correct this if you have realtime/persistent-connection features (**unverified — no code scan**)                                                                                                  |
| Q10   | DETECTED when `min_instances > 0`; PROPOSED otherwise                                                                            | 3 — `constant-24-7`                  | Assuming 24/7 traffic → conservative (higher) AWS estimate; business-hours-only workloads may be cheaper staying on Cloud Run                                                                                                                   |
| Q11   | PROPOSED                                                                                                                         | 2 — `$100-$500`                      | Feeds the migrate-vs-stay analysis for Cloud Run; correct if spend is materially different                                                                                                                                                      |
| Q11b  | PROPOSED when compatible compute is present; otherwise N/A                                                                       | 1 — Graviton                         | Default ARM64 targets reduce compute cost; use the decision table in `clarify-compute.md` for compatibility caveats                                                                                                                             |
| Q12   | DETECTED when dev-tier; ESSENTIAL on mixed tiers; PROPOSED otherwise                                                             | 1 — `steady`                         | Assuming steady traffic → size from current config, no read replicas                                                                                                                                                                            |
| Q13   | DETECTED when dev-tier; ESSENTIAL on mixed tiers; PROPOSED otherwise                                                             | 2 — `medium`                         | Assuming medium I/O → gp3 storage; high-IOPS workloads would need io2/Provisioned IOPS                                                                                                                                                          |
| Q13b  | DETECTED when disk size unambiguous; ESSENTIAL on conflict; PROPOSED otherwise                                                   | 5 — `unknown`                        | Unknown size → pgcopydb selected as migration tool (safe at any scale); verify before cutover                                                                                                                                                   |
| Q14   | DETECTED when auto-detection resolves; PROPOSED otherwise                                                                        | `["direct"]`                         | Framework determines AI migration effort (gateway = config change; Agents SDK = weeks)                                                                                                                                                          |
| Q15   | **ESSENTIAL** when Category F fires                                                                                              | —                                    | — (anchors Bedrock savings comparison and token-volume derivation; no discovery signal exists)                                                                                                                                                  |
| Q16   | PROPOSED                                                                                                                         | 5 — `balanced`                       | Assuming balanced priority → Sonnet-class default model; say "cost" or "speed" to shift the model family                                                                                                                                        |
| Q17   | PROPOSED                                                                                                                         | 10 — none                            | Assuming no specialized feature → Q16 priority decides the model; name a feature (tool use, long context, RAG…) to override                                                                                                                     |
| Q18   | PROPOSED                                                                                                                         | 1 — `low`                            | Assuming low volume → on-demand pricing, no provisioned throughput analysis                                                                                                                                                                     |
| Q19   | DETECTED when model confidence ≥ 0.8; PROPOSED otherwise                                                                         | Q16-priority-based                   | Baseline model drives the Bedrock mapping and cost comparison                                                                                                                                                                                   |
| Q20   | DETECTED from `capabilities_summary`; PROPOSED otherwise                                                                         | 1 — text only                        | Assuming text-only → full model catalog; vision or audio inputs restrict the model set                                                                                                                                                          |
| Q21   | PROPOSED                                                                                                                         | 2 — `important`                      | Assuming <2s latency → Sonnet-class + streaming; sub-500ms requirements would force Haiku/Nova                                                                                                                                                  |
| Q22   | PROPOSED                                                                                                                         | 2 — `moderate`                       | Assuming moderate complexity → Sonnet-class; simple classification workloads could use cheaper Haiku/Nova                                                                                                                                       |
| Q23   | **ESSENTIAL** when Category G fires (unless auto-detection resolves it per `clarify-ai.md` Q23 skip rule)                        | framework-based auto-detect          | — (migration approach routes the entire agentic design path)                                                                                                                                                                                    |
| Q24   | **ESSENTIAL** when Category G fires                                                                                              | 2 — `session`                        | — (memory requirement changes the AgentCore architecture)                                                                                                                                                                                       |
| Q25   | **ESSENTIAL** when Category G fires                                                                                              | 2 — `medium`                         | — (task duration gates runtime selection and session limits)                                                                                                                                                                                    |
| Q26   | PROPOSED when Category G fires                                                                                                   | path-based (see `clarify-ai.md`)     | Incremental migration → A/B test Bedrock per-invocation before committing; full swap is faster but riskier                                                                                                                                      |
| Q27   | **ESSENTIAL** when Category H fires (same trigger as Category F)                                                                 | —                                    | — (self-funded vs VC-backed vs already has credits — never inferred from spend; gates Founders vs Portfolio guidance)                                                                                                                           |

**Multi-workload confirmation table** (`clarify-ai.md`, fires when `workloads[]` ≥ 2): unchanged — it runs during Step 4 as part of the AI essentials, after the sheet is confirmed. Its high-confidence rows behave like DETECTED sheet rows; medium/low-confidence rows behave like essential questions (max 2 per row).

### Early-Exit Rules

Apply before finalizing dispositions:

- **Q5 answered/overridden to "multi-cloud"** — Immediately record `compute: "eks"`. Q8 **and Q7b** become N/A (early-exit); App Engine follows the container path to **EKS**, overriding the default EB mapping.
- **Q7b N/A** — App Engine (`google_app_engine_application`) not present in inventory, or Q5 resolved to multi-cloud (App Engine → EKS, same override as Q8).
- **Q10/Q11 N/A** — Cloud Run not present.
- **Q12/Q13/Q13b N/A** — Cloud SQL (PostgreSQL or MySQL) not present in inventory.
- **Q8 N/A** — No GKE in inventory, or Q5 resolved to multi-cloud.
- **Q14 auto-detected** — If `integration.gateway_type` is non-null OR `integration.frameworks` is non-empty, DETECTED with `chosen_by: "extracted"`.

---

## Step 2.5: Assumption Sheet (Mandatory Gate)

**When to run:** Always in wizard mode, after Step 2 extraction and Step 3 disposition — whenever at least one row is DETECTED or PROPOSED.

**Skip Step 2.5 only when** every active question is ESSENTIAL or N/A (rare — e.g., empty discovery with Category A only). Proceed directly to Step 4.

**HARD GATE — do NOT ask any essential question until the user responds to this sheet.**

Present the sheet in two sections (omit rows for questions that are ESSENTIAL or N/A). Keep each consequence to one line — use the catalog wording from Step 3:

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

Q27 (AWS Activate credits) is **not** on this sheet — it is asked in Step 4 when AI workloads are detected.

Reply:
1. **Confirm all** (or "looks good") — I'll record these and ask only the [N] essential questions.
2. **Change a setting** — name it precisely (**"availability: mission-critical"**, **"ai priority: cost"**, **"websockets: yes"**) or just describe it in plain words (**"our database going down would be really bad"** — I'll map it or ask the full question). You can fix several in one message.
3. **"ask me about [setting]"** — I'll ask the full question with all options for that item.
4. **"ask me everything"** — discard all assumptions and run the full question-by-question flow.
```

_Present these as selectable options via the structured question tool (e.g. AskUserQuestion) when the IDE provides one; otherwise show the numbered list above verbatim. Free-text corrections are always accepted in either mode — the menu supplements the override grammar, it never replaces it._

**Computing [N]:** Count ESSENTIAL dispositions for all active categories, plus any rows converted to ESSENTIAL via user correction ("ask me about X"), plus conflict rows. Subtract any ESSENTIAL questions that were already answered by a user correction on the sheet (e.g., user said `"availability: mission-critical"` — Q6 no longer needs asking).

**Multi-instance Cloud SQL conflicts:** When instances disagree, replace the single-row summary with a per-instance table and keep the conflicting question ESSENTIAL until resolved:

```
| Instance | availability_type | tier | disk_size (GB) |
| -------- | ----------------- | ---- | -------------- |
| google_sql_database_instance.main | ZONAL | db-f1-micro | 10 |
| google_sql_database_instance.analytics | REGIONAL | db-n1-standard-4 | 100 |

These instances disagree on availability. Which posture should we use for the migration design?
1\) Most conservative (highest HA) | 2\) Use [instance name] as primary | 3\) Ask me the full Q6 question
```

**Override handling** — when the user corrects a value (detected or assumed):

| User correction (examples)                       | Update constraint                                                             | Re-ask?                   |
| ------------------------------------------------ | ----------------------------------------------------------------------------- | ------------------------- |
| `availability: mission-critical` / `multi-az-ha` | `availability: "multi-az-ha"`, `chosen_by: "user"`                            | No — value is explicit    |
| `availability: significant` / `multi-az`         | `availability: "multi-az"`, `chosen_by: "user"`                               | No                        |
| `availability: dev` / `single-az`                | `availability: "single-az"`, `chosen_by: "user"`                              | No                        |
| `db size: <10GB` / `10-100GB` / etc.             | Set `db_size` to stated band, `chosen_by: "user"`                             | No if band is explicit    |
| `region: [AWS region]`                           | Set `target_region`, `chosen_by: "user"`                                      | No                        |
| `model: [model name]`                            | Set `ai_model_baseline`, `chosen_by: "user"`                                  | No if maps cleanly to Q19 |
| `websockets: yes`                                | Set `websocket: "required"`, `chosen_by: "user"`                              | No                        |
| `spend: $5K-$20K`                                | Set `gcp_monthly_spend`, `chosen_by: "user"`                                  | No if band is explicit    |
| `ai priority: cost` / `speed` / `quality`        | Set `ai_priority`, `chosen_by: "user"`                                        | No                        |
| `multi-cloud: yes`                               | `compute: "eks"`, `chosen_by: "user"`; Q8 → N/A; Q7b → N/A (App Engine → EKS) | No                        |
| "ask me about [setting]"                         | Convert that row to ESSENTIAL                                                 | Yes — full question       |
| Vague correction ("that's wrong")                | Convert that row to ESSENTIAL                                                 | Yes — full question       |

For each override: set `chosen_by: "user"` on the constraint (this removes the `source` field since it's no longer extracted/default). For extracted rows, also remove the question ID from `metadata.questions_skipped_extracted`; for assumed rows, remove it from `metadata.questions_defaulted`.

**When the user confirms ("looks good"):** no further action needed — the constraint objects already carry their `chosen_by` and `source` fields.

**"Ask me everything":** clear `questions_skipped_extracted` and `questions_defaulted`; set all previously extracted/assumed constraints to pending; set `metadata.clarify_mode: "full"` and run the **Legacy Full Flow** (see Step 4, Full Flow variant).

**Constraint `source` field:** When writing a constraint with `chosen_by: "extracted"` or `chosen_by: "default"`, include the `source` field on the constraint object itself:

- Extracted: raw provenance signal (e.g. `"terraform:availability_type=ZONAL"`, `"billing:region=us-west1"`, `"ai-profile:integration.pattern=direct_sdk"`)
- Default: `"default:<Qid>"` (e.g. `"default:Q16"`)

Omit `source` when `chosen_by` is `"user"` or `"derived"`. See constraint examples in Step 5.

After the user responds, write `preferences-draft.json` with all resolved values and `metadata.wizard_stage: "essentials_pending"`, then proceed to Step 4.

---

## Category E — Migration Posture (Disabled by Default)

_Fire when:_ User explicitly opts in.
_Default behavior when disabled:_ Apply conservative defaults — no HA upgrades, no right-sizing.

If the user opts in, present after the essentials:

### Q-E1 — Should we recommend upgrading Single-AZ to Multi-AZ where possible?

> 1\) Yes — upgrade to Multi-AZ for higher availability | 2\) No — keep current topology

Interpret → `ha_upgrade`: 1 → `true`, 2 → `false`. Default: 2 → `false`.

### Q-E2 — Should we use billing utilization data to right-size instance types?

> 1\) Yes — right-size based on utilization | 2\) No — match current capacity

Interpret → `right_sizing`: 1 → `true`, 2 → `false`. Default: 2 → `false`.

---

## Step 4: Ask the Essential Questions

**Prerequisite:** Step 2.5 sheet confirmation must be complete (user said "looks good" or finished correcting) before asking anything. Do not re-show the full sheet here unless the user asks for a recap.

> **COMPLIANCE SELF-CHECK (do this before emitting any question):** Verify both: (1) the Assumption Sheet was presented in a **previous turn**, and (2) the user has **responded** to it. If either is false, STOP — present the sheet and wait. Never combine the sheet and essential questions in a single message, and never ask a question that has a sheet row unless the user converted it via a correction or "ask me about X".

**BigQuery / deferred analytics (mandatory callout):** If Step 2 set `bigquery_present` to **true**, output this block **once**, **before** any questions (same turn as the essentials), then continue:

> **BigQuery / analytics warehouse:** Your discovery inputs include BigQuery. This skill **does not** select an AWS analytics or data-warehouse target (no Athena, Redshift, Glue, or EMR recommendation from the plugin). **Before** warehouse, data lake, SQL analytics, or BI cutover planning, engage your **AWS account team** and/or a **data analytics migration partner** to assess query patterns, data volumes, ETL/ELT, and downstream consumers. Design will mark these resources as **`Deferred — specialist engagement`**.

### Essentials Batches

Present the essential questions (from the Step 3 disposition, plus any rows converted by "ask me about X") in batches of **at most 4 per turn**, numbered from 1, with the question text, context, and options from the category files. Typical total: 2–7.

**Batch composition:** core first (Q1/Q2/Q3/Q3.5/Q7 + conflicts), then AI/agentic (Q15, Q23–Q25, multi-workload confirmations). **Q27 is not batched** — ask it as its own short follow-up after the last batch, per the presentation rule in `clarify-ai.md` Q27 (it's a funding question, not a technical one). Write `preferences-draft.json` between batches (same schema as `preferences.json` plus `metadata.wizard_stage`). When more than one batch is needed, open each with a progress line: "Batch [i] of [k]."

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

_Present each question's options via the structured question tool (e.g. AskUserQuestion) when the IDE provides one — one tool call per batch, identical option text. Otherwise use the lettered options in chat as shown. Shorthand and plain-word answers are accepted in either mode._

**This ≤4 cap applies to wizard essentials only.** The Full Flow variant below keeps its documented three-batch structure — the user explicitly opted into the long path and has shorthand answering.

**Wait for the user's response.** Do NOT proceed to Design without a response or an explicit "use defaults for the rest."

**"Use defaults for the rest" handling:** Apply documented defaults for all unanswered essential questions **except** those marked "never assumed" in the catalog when a safe default genuinely does not exist:

- Q2 defaults to **unknown** — write `compliance: {value: ["unknown"], chosen_by: "default", source: "default:Q2"}`. Never record silent "no requirements"; `["unknown"]` behaves like "none" for service selection but triggers the report compliance caveat.
- Q7 defaults to 4 (flexible).
- Q3 defaults to 2 ($1K–$5K) with a report caveat that spend was not confirmed.
- **Q27 must not be silently defaulted in wizard mode** when Category H fired — if the user skips it, record `startup_program_status: "unknown"` with `chosen_by: "default"` and `source: "default:Q27"`; downstream artifacts must use neutral Activate copy (both tiers, no "your status: eligible_*").
- Q3.5, Q23–Q25, and unresolved multi-instance conflicts fall back to their documented defaults (Q3.5 → 5; Q23 → framework-based; Q24 → session; Q25 → medium; conflicts → most conservative posture) with `chosen_by: "default"`.
  Then run the **Answer Recap** (below) with the defaulted rows included, then Category E opt-in, then Step 5.

**Interpret answers** using the interpret rules in the category files. Apply early-exit rules triggered by answers (e.g., Q5 correction to multi-cloud → `compute: "eks"`, Q8 → N/A).

### Answer Recap (Check Your Answers)

After the last essential batch is answered and interpreted (and after Q27 when it fired), play back what was recorded — the essentials are the only answers in the flow the user states rather than confirms, and shorthand ("1A 2C") plus plain-word answers pass through an interpretation step the user never sees. One compact table, questions asked in Step 4 only (sheet rows were already confirmed at Step 2.5 — do not repeat them):

```
### What I recorded — last check before design

| Question | Your answer | Recorded as |
| -------- | ----------- | ----------- |
| Compliance (Q2) | "2A" | None |
| Cutover window (Q7) | "monthly is fine" | Monthly maintenance window |
| AI spend (Q15) | "about a grand" | $500–$2K/month |

Anything wrong? Name it ("cutover: weekly") — or say "looks good" and I'll proceed to design.
```

**Always wait.** Present the recap and **wait for the user's response** ("looks good" or a correction) before continuing — interpretation is exactly where a misread silently becomes a design constraint, and the batch opener invites shorthand and plain-word answers, so nearly every real run involves interpretation. One extra turn at the single highest-stakes commit in the flow is the intended cost. Corrections use the Step 2.5 override grammar and set `chosen_by: "user"`.

**Sequence (fixed — do not reorder or combine):**

1. Answer Recap → wait for the user's response
2. Category E opt-in (if `billing-profile.json` exists) → wait
3. Step 5 — write `preferences.json`

**"Use defaults for the rest" still gets a recap:** when the user defaults remaining questions, include those rows with `(default applied)` in the "Your answer" column and the defaulted value in "Recorded as" — bulk-defaulting is the highest-risk interpretation of all, and this is the user's one chance to see what "the rest" actually meant. Then wait as above.

### Full Flow variant ("ask me everything")

When the user opted out of the wizard, run the progressive-batch flow: present ALL active questions (no dispositions) in up to three batches — Strategic (Q1–Q7, minus Q4), Infrastructure (Q8–Q13b incl. Q11b Graviton + Category B), AI (Q14–Q27, Q23–Q26 only if agentic) — writing `preferences-draft.json` between batches with `metadata.batches_completed` / `metadata.batches_remaining` (values: `"strategic"`, `"infrastructure"`, `"ai"`). Per-question skip and "use defaults for the rest" behave as documented. Set `metadata.clarify_mode: "full"`. The **Answer Recap** above runs after the final batch here too (all answered questions as rows; skipped/defaulted ones summarized in one line, not per-row — intentional compression so a 20+ question full-flow recap stays scannable; the wizard already shows every defaulted essential as a `(default applied)` row because that set is small. Do not silently drop answered questions into the one-liner).

### Category E Opt-In

After the essentials are answered (but before writing final `preferences.json`), offer Category E if `billing-profile.json` exists:

> "Would you also like HA upgrade and right-sizing recommendations based on your billing data? If not, I'll use conservative defaults (no upgrades, match current capacity)."

If user opts in, present Q-E1–Q-E2 (defined in **Category E — Migration Posture** above). Otherwise, apply Category E defaults (`ha_upgrade: false`, `right_sizing: false`).

---

## Answer Combination Triggers

| Scenario                                 | Key Answers                                                   | Recommendation                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Early-stage funding path                 | Q3 = lower spend band                                         | Entry-tier migration funding program review                                                     |
| Growth-stage funding path                | Q3 = higher spend band                                        | Migration funding/support program review based on spend profile                                 |
| Managed platform preference              | Q7b = 1 (managed platform)                                    | Elastic Beanstalk for App Engine compute targets                                                |
| Container orchestration pref             | Q7b = 2 (container orchestration)                             | ECS Fargate for App Engine targets (overrides default EB mapping)                               |
| Serverless pref                          | Q7b = 3 (serverless)                                          | Lambda for App Engine targets (overrides default EB mapping)                                    |
| Must stay portable                       | Q5 = Yes multi-cloud                                          | EKS only, no ECS Fargate; App Engine also routes to EKS (Q7b N/A, overrides default EB mapping) |
| Kubernetes-averse                        | Q5 = No + Q8 = Frustrated                                     | ECS Fargate strongly recommended                                                                |
| WebSocket app                            | Q9 = Yes                                                      | ALB WebSocket config required                                                                   |
| Low-traffic Cloud Run                    | Q10 = Business hours + Q11 < $100                             | Recommend staying on Cloud Run                                                                  |
| Cloud SQL Postgres — dev/low HA          | Q6 = Inconvenient + Cloud SQL in inventory                    | **RDS PostgreSQL** single-AZ                                                                    |
| Cloud SQL Postgres — prod HA (RDS)       | Q6 = Significant Issue + Cloud SQL in inventory               | **RDS PostgreSQL** Multi-AZ                                                                     |
| Cloud SQL Postgres — mission-critical    | Q6 = Mission-Critical + Cloud SQL in inventory                | **Aurora PostgreSQL** Multi-AZ; apply Q12/Q13                                                   |
| Cloud SQL Postgres — global catastrophic | Q6 = Catastrophic + Q1 = Global + Cloud SQL in inventory      | **Aurora PostgreSQL Global Database**                                                           |
| High I/O database (RDS path)             | Q6 = Inconvenient/Significant + Q13 = High                    | **RDS** io2 or Provisioned IOPS                                                                 |
| High I/O database (Aurora path)          | Q6 = Mission-Critical/Catastrophic + Q13 = High               | Aurora I/O-Optimized                                                                            |
| Write-heavy global DB                    | Q6 = Mission-Critical/Catastrophic + Q12 = Write-heavy/global | Aurora DSQL architecture review (RDS path only: size writer; flag review)                       |
| Rapidly growing DB (RDS path)            | Q6 = Inconvenient/Significant + Q12 = Rapidly growing         | RDS with headroom on instance class                                                             |
| Rapidly growing DB (Aurora path)         | Q6 = Mission-Critical/Catastrophic + Q12 = Rapidly growing    | Aurora Serverless v2                                                                            |
| Zero downtime required                   | Q7 = No downtime                                              | Blue/green + AWS DMS required (RDS or Aurora blue/green per Q6)                                 |
| HIPAA compliance                         | Q2 = HIPAA                                                    | BAA services only, specific regions                                                             |
| FedRAMP required                         | Q2 = FedRAMP                                                  | GovCloud regions only                                                                           |
| CCPA / CPRA                              | Q2 = 7 (CCPA / CPRA)                                          | Consumer privacy, logging/retention, data-inventory posture; confirm regions with legal review  |
| Gateway-only AI                          | Q14 = 2 only (LLM router/gateway)                             | Config change only; skip SDK migration                                                          |
| LangChain/LangGraph AI                   | Q14 includes 3                                                | Provider swap via ChatBedrock; 1–3 days                                                         |
| OpenAI Agents SDK                        | Q14 includes 5                                                | Highest AI effort; AgentCore (Harness/Runtime); 2–4 weeks                                       |
| Multi-agent + MCP                        | Q14 = 4 + 6                                                   | AgentCore to unify orchestration + MCP (Gateway)                                                |
| Voice platform AI                        | Q14 includes 7                                                | Check native Bedrock support; Nova 2 Sonic if needed                                            |
| GPT-5.5 migration                        | Q19 = GPT-5.5                                                 | Claude Opus 4.6 — Bedrock 17% cheaper on output; or Sonnet 5 for 68% savings                    |
| GPT-5.5 Pro migration                    | Q19 = GPT-5.5 Pro                                             | Nova 2 Pro — 95% cheaper on Bedrock                                                             |
| GPT-5.4 migration                        | Q19 = GPT-5.4                                                 | Claude Sonnet 5 — ~36% cheaper blended; AWS consolidation                                       |
| GPT-5.4 Mini/Nano migration              | Q19 = GPT-5.4 Mini or Nano                                    | Nova Lite/Micro — 87-94% cheaper on Bedrock                                                     |
| GPT-4 Turbo migration                    | Q19 = GPT-4 Turbo                                             | Claude Sonnet 5 — 80% cheaper on input                                                          |
| o-series migration                       | Q19 = o-series                                                | Claude Sonnet 5 with extended thinking                                                          |
| High-volume cost-critical AI             | Q18 = High + cost critical                                    | Nova Micro or Haiku 4.5 + provisioned throughput                                                |
| Reasoning/agent workload                 | Q17 = Extended thinking                                       | Claude Sonnet 5 extended thinking; Opus 4.6 for hardest                                         |
| Speech-to-speech AI                      | Q17 = Real-time speech                                        | Nova 2 Sonic                                                                                    |
| RAG workload                             | Q17 = RAG optimization                                        | Bedrock Knowledge Bases + Titan Embeddings                                                      |
| Vision workload                          | Q20 = Vision required                                         | Claude Sonnet 5 (multimodal)                                                                    |
| Latency-critical AI                      | Q21 = Critical                                                | Haiku 4.5 or Nova Micro + streaming                                                             |
| Complex reasoning tasks                  | Q22 = Complex                                                 | Claude Sonnet 5; Opus 4.6 for hardest                                                           |

---

## Step 5: Assemble and Write preferences.json

Assemble all resolved values — sheet confirmations, corrections, essential answers, and defaults — into the final `$MIGRATION_DIR/preferences.json`. **Every constraint object MUST include `prompt` and `design_consequence`** per `references/shared/schema-preferences.md` (use the constraint catalog when the user did not see the verbatim question).

If `preferences-draft.json` exists, use it as the base — merge in the final answers, remove the draft-specific metadata fields (`draft`, `wizard_stage`, `batches_completed`, `batches_remaining`), and set `metadata.timestamp` to the current time. Write `$MIGRATION_DIR/preferences.json`:

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

1. Every entry in `design_constraints`, `ai_constraints`, and `startup_constraints` (when present) is an object with **`value`**, **`chosen_by`**, **`prompt`**, and **`design_consequence`** fields. Optional **`question_id`** when mapped to the Q1–Q27 catalog. Optional **`source`** when `chosen_by` is `"extracted"` or `"default"`.
2. **`prompt`:** verbatim question from the category file when `chosen_by` is `"user"`; detection label when `"extracted"`; question + `" (default applied)"` when `"default"`; derivation label when `"derived"`.
3. **`design_consequence`:** one sentence from the category file's Recommendation Impact for the selected answer, or the catalog template in `schema-preferences.md` with `[value]` substituted.
4. `chosen_by` values: `"user"` (explicitly answered or corrected on the sheet), `"default"` (documented default applied — includes sheet-confirmed defaults and "I don't know" answers), `"extracted"` (inferred from inventory), `"derived"` (computed from combination of answers + detected capabilities).
5. **`source` field on constraints:** Every constraint with `chosen_by: "extracted"` or `chosen_by: "default"` MUST include a `source` field. Extracted: raw provenance signal (prefix `terraform:`, `billing:`, `code:`, `inventory:`, `ai-profile:`, or artifact filename). Default: `"default:<Qid>"`. Omit `source` for `"user"` and `"derived"`. Report generation uses `source` prefixed `default:` to flag unverified assumptions.
6. Only write a key to `design_constraints` / `ai_constraints` if the answer produces a constraint. Absent keys mean "no constraint — Design decides."
7. Do not write null values. Do not omit `prompt` or `design_consequence` on any written constraint.
8. For billing-source inventories, `metadata.inventory_clarifications` records Category B answers.
9. `metadata.questions_skipped_early_exit` records questions skipped due to early-exit logic (e.g., Q8 skipped because Q5=multi-cloud).
10. `metadata.questions_skipped_extracted` records questions resolved because inventory already provided the answer.
11. `metadata.questions_defaulted` records questions resolved by documented default — whether sheet-confirmed (wizard) or skipped (full flow / "use defaults").
12. `metadata.questions_skipped_not_applicable` records questions skipped because the relevant service wasn't in the inventory or their firing condition wasn't met.
13. `ai_constraints` section is present ONLY if Category F fired. Omit entirely if no AI artifacts exist.
14. `ai_constraints.ai_capabilities_required` is the UNION of detected capabilities from `ai-workload-profile.json` + critical feature from Q17 + vision from Q20. `chosen_by` is `"derived"`.
15. `ai_constraints.ai_framework` is an array (Q14 is select-all-that-apply). If auto-detected, `chosen_by` is `"extracted"` with `source`.
16. `metadata.clarify_mode` is one of `"wizard"`, `"full"`, `"fast_path"`, `"simple_hybrid"`.

After writing `preferences.json`, delete `$MIGRATION_DIR/preferences-draft.json` and `$MIGRATION_DIR/preferences-superseded.json` if they exist (the superseded backup has served its purpose once a new complete file exists).

---

## Defaults Table

Documented defaults for every question. Used by: PROPOSED sheet rows (wizard), per-question skips, "use defaults for the rest", and the fast paths.

| Question                   | Default                                                                                                           | Constraint                                                                                                                                                                                           |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1 — Location              | 1 (single region)                                                                                                 | `target_region`: closest AWS region to GCP region                                                                                                                                                    |
| Q2 — Compliance            | unknown (unconfirmed)                                                                                             | `compliance: ["unknown"]` — treated as no-constraint for service selection; report caveat _(essential — defaulted only via "use defaults for the rest")_                                             |
| Q3 — GCP spend             | 2 ($1K–$5K)                                                                                                       | `gcp_monthly_spend: "$1K-$5K"` _(essential when no billing — same caveat rule as Q2)_                                                                                                                |
| Q3.5 — GCP CUDs            | 5 (none)                                                                                                          | `cud_status: "none"` _(essential when it fires — billing shows CUDs, so only defaulted via "use defaults for the rest")_                                                                             |
| Q4 — Funding stage         | _(skip in IDE mode)_                                                                                              | no constraint                                                                                                                                                                                        |
| Q5 — Multi-cloud           | 2 (AWS-only)                                                                                                      | no constraint                                                                                                                                                                                        |
| Q6 — Uptime                | 2 (significant)                                                                                                   | `availability: "multi-az"`                                                                                                                                                                           |
| Q7 — Maintenance           | 4 (flexible)                                                                                                      | `cutover_strategy: "flexible"`                                                                                                                                                                       |
| Q7b — Compute model        | 1 (managed platform)                                                                                              | `compute_model: "managed_platform"` (App Engine only; N/A if no App Engine, or if Q5 = multi-cloud → App Engine routes to EKS)                                                                       |
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
| Q27 — Activate credits     | _(essential when Category H fires — ask in Step 4; skip only via explicit answer or "use defaults for the rest")_ | `startup_program_status` per answer; skip → `"unknown"` with neutral downstream copy                                                                                                                 |
| Q-E1 — HA upgrade          | 2 (no)                                                                                                            | `ha_upgrade: false`                                                                                                                                                                                  |
| Q-E2 — Right-sizing        | 2 (no)                                                                                                            | `right_sizing: false`                                                                                                                                                                                |

---

## Validation Checklist

Before handing off to Design:

- [ ] In wizard mode, the Step 2.5 Assumption Sheet was shown (detected + assumed sections) and the user responded before any essential question was asked
- [ ] Every constraint with `chosen_by: "extracted"` or `chosen_by: "default"` has a `source` field with the correct prefix (`terraform:`, `billing:`, `inventory:`, `ai-profile:`, or `default:<Qid>`)
- [ ] Essential questions (Q2, Q7, and conditional Q1/Q3/Q3.5/**Q27**/Q15/Q23–Q25/conflicts) were asked, answered, or explicitly defaulted via "use defaults for the rest"
- [ ] The Answer Recap was shown after the final Step 4 batch (including defaulted rows on "use defaults for the rest") and the user responded to it before Category E / `preferences.json`
- [ ] If `bigquery_present` was **true**, the Step 4 BigQuery specialist advisory was shown before questions — **or**, if Step 0 option 1 (reuse preferences), the same advisory was shown after BigQuery detection
- [ ] `preferences.json` written to `$MIGRATION_DIR/`
- [ ] `design_constraints.target_region` is populated with `value` and `chosen_by`
- [ ] `design_constraints.availability` is populated when Cloud SQL PostgreSQL/MySQL is in inventory (asked, extracted, or defaulted — Design must not run with absent/null availability)
- [ ] If compute resources are present, `design_constraints.cpu_architecture` is set to `graviton`, `x86`, or `mixed` per the Q11b decision table
- [ ] Only keys with non-null values are present in `design_constraints`
- [ ] Every entry in `design_constraints` and `ai_constraints` has `value` and `chosen_by` fields
- [ ] Config gap answers recorded in `metadata.inventory_clarifications` (billing mode only)
- [ ] Early-exit skips recorded in `metadata.questions_skipped_early_exit`
- [ ] `ai_constraints` section present ONLY if Category F fired
- [ ] If Category F fired, `ai_constraints.ai_framework` is populated (from detection or Q14)
- [ ] If Category F fired, `ai_capabilities_required` is derived from detection + Q17 + Q20
- [ ] `ai_constraints.ai_framework` is an array (Q14 is multi-select)
- [ ] Output is valid JSON
- [ ] `preferences-draft.json` has been deleted (if it existed)
- [ ] `metadata.clarify_mode` is set to `"wizard"`, `"full"`, `"fast_path"`, or `"simple_hybrid"`

---

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** before checking.

**Re-entry guard:** If `aws-design.json` (or `aws-design-ai.json` / `aws-design-billing.json`) exists and `phases.design` is `"completed"`: STOP unless the user explicitly confirms re-running Clarify. Emit `GATE_FAIL | phase=clarify | field=aws-design.json | reason=stale_downstream`.

**Checks (all must PASS):**

1. `preferences.json` exists and parses as JSON.
2. Step 5 validation checklist items all pass (including `metadata.clarify_mode`).
3. If `gcp-resource-inventory.json` contains `google_sql_database_instance` → `design_constraints.availability.value` is set (non-null, non-empty).
4. If `metadata.clarify_mode` is `"wizard"` → at least one constraint has a `source` field OR every active question was essential.
5. **No sheet/question mixing:** `metadata.questions_asked` contains no question ID that also appears in `metadata.questions_skipped_extracted` or `metadata.questions_defaulted`. (A question may move between lists only if the user converted its sheet row — in which case the override handling moved it to `questions_asked`.)
6. If compute resources are present (Cloud Run, Cloud Functions, GKE, GCE in `gcp-resource-inventory.json`, or billing-source compute) → `design_constraints.cpu_architecture.value` is set (`graviton` | `x86` | `mixed`), per the Q11b decision table in `clarify-compute.md` — written even when Q11b was auto-defaulted.
7. **Extraction consistency — Q13b** _(skip this check when `metadata.clarify_mode` is `"full"` — the user explicitly opted into the full question flow)_: If every `google_sql_database_instance` in `gcp-resource-inventory.json` carries an unambiguous disk size (`config.disk_size_gb` or legacy variants, all mapping to the same Q13b band) → `Q13b` must NOT appear in `metadata.questions_asked` unless `design_constraints.db_size.chosen_by` is `"user"` (the user converted the sheet row via "ask me about X" or corrected it). If instances map to **different** bands (e.g. an 8 GB dev instance and a 200 GB prod instance), the size is ambiguous — this check does NOT fire, and asking Q13b is the expected behavior (matching the `clarify-database.md` auto-detect rule "if multiple instances disagree, ask Q13b"). Otherwise: `GATE_FAIL | phase=clarify | field=metadata.questions_asked | reason=extractable_question_asked_Q13b`.
8. **Extraction consistency — Q19** _(skip when `metadata.clarify_mode` is `"full"`)_: If `ai-workload-profile.json` exists with `models[0].model_id` set at confidence ≥ 0.8 → `Q19` must NOT appear in `metadata.questions_asked` unless `ai_constraints.ai_model_baseline.chosen_by` is `"user"`. Otherwise: `GATE_FAIL | phase=clarify | field=metadata.questions_asked | reason=extractable_question_asked_Q19`. (Detect-confirm cards for sub-threshold or tied detection per `clarify-ai.md` are not affected — they fire only when confidence < 0.8.)

**On any FAIL:** Emit `GATE_FAIL | phase=clarify | field=<path> | reason=missing`. **Do NOT modify artifacts to pass the gate.** **Do NOT update `.phase-status.json`.** Tell the user to answer the missing question or re-run Clarify.

**On PASS:** Emit `HANDOFF_OK | phase=clarify | artifacts=preferences.json`.

## Step 6: Update Phase Status

Only after `HANDOFF_OK`. In the **same turn** as the output message below, use the Phase Status Update Protocol (Write tool) to write `.phase-status.json` with `phases.clarify` set to `"completed"`.

Output to user: "Phase 2 of 6 complete (Clarify). Remaining: Design → Estimate → Generate (+ optional Feedback). Next artifact: aws-design.json. Proceeding to Phase 3: Design AWS Architecture."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._

---

## Scope Boundary

**This phase covers requirements gathering ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Detailed AWS architecture or service configurations
- Code migration examples or SDK snippets
- Detailed cost calculations
- Migration timelines or execution plans
- Terraform generation

**Your ONLY job: Understand what the user needs. Nothing else.**
