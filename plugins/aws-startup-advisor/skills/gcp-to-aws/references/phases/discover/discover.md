# Phase 1: Discover GCP Resources

Lightweight orchestrator that delegates to domain-specific discoverers. Each sub-discovery file is self-contained — it scans for its own input, processes what it finds, and exits cleanly if nothing is relevant.
**Execute ALL steps in order. Do not skip or deviate.**

## Sub-Discovery Files

- **discover-iac.md** → `gcp-resource-inventory.json` + `gcp-resource-clusters.json` (if Terraform found); may also write `ai-workload-profile.json` when **Vertex-strong** (see `discover-iac.md` Step 7d)
- **discover-live.md** → `gcp-resource-inventory.json` + `gcp-resource-clusters.json` from the user's authenticated `gcloud` CLI (read-only, consent-gated); merges into the IaC inventory with drift when both run
- **discover-app-code.md** → `ai-workload-profile.json` when AI confidence ≥ 70% (may **merge** with an existing `iac_vertex` profile)
- **discover-billing.md** → `billing-profile.json` (if billing data found)
- **discover-openai-api.md** → `openai-usage-profile.json` from the OpenAI Admin API (read-only, consent-gated); fills `ai-workload-profile.json` → `current_costs` with real spend when that profile exists

Multiple artifacts can be produced in a single run — they are not mutually exclusive.

## Step 0: Initialize Migration State

0. **Orientation (fresh runs only):** When this is a new migration (no existing `.migration/` runs, or the user chooses Fresh below), open your first response with this block — before any scanning output. Skip it entirely when resuming an existing run (the breadcrumb in the resume message covers position).

   > **Here's how this works.** Six phases: I scan your Terraform, app code, or billing data; confirm a few assumptions with you; then design the AWS architecture, price it, and generate everything. Your part is small — most answers come from your own files; you'll typically confirm one summary sheet and answer 2–7 questions. At the end you get a migrate-or-stay recommendation with costs, Terraform for the in-scope workloads, and step-by-step migration scripts. You can stop at any point — progress is saved and I'll resume where you left off.

   Do not pad it, restate it later, or block on it — continue directly into discovery in the same turn.

1. Check for existing `.migration/` directory at the project root.
   - **If existing runs found:** List them with their phase status and ask:
     - `[A] Resume: Continue with [latest run]`
     - `[B] Fresh: Create new migration run`
     - `[C] Cancel`
   - **If resuming:** Set `$MIGRATION_DIR` to the selected run's directory. Read its `.phase-status.json` and skip to the appropriate phase per the State Machine in SKILL.md.
   - **If fresh or no existing runs:** Continue to step 2.
2. Create `.migration/[MMDD-HHMM]/` directory (e.g., `.migration/0226-1430/`) using current timestamp (MMDD = month/day, HHMM = hour/minute). Set `$MIGRATION_DIR` to this new directory.
3. Create `.migration/.gitignore` file (if not already present) with exact content:

   ```
   # Auto-generated migration state (temporary, do not commit)
   *
   !.gitignore
   ```

   This prevents accidental commits of migration artifacts.

4. Write `.phase-status.json` with exact schema:

   ```json
   {
     "migration_id": "[MMDD-HHMM]",
     "run_id": "[fresh random UUID from uuidgen]",
     "owning_skill": "GCP_TO_AWS",
     "last_updated": "[ISO 8601 timestamp]",
     "current_phase": "discover",
     "phases": {
       "discover": "in_progress",
       "clarify": "pending",
       "design": "pending",
       "estimate": "pending",
       "workshop": "pending",
       "generate": "pending",
       "feedback": "pending"
     }
   }
   ```

   `run_id` is minted once here: run `uuidgen` (or an equivalent random UUID source) and write its output verbatim; never copy a value from an example or a previous run. It is never changed or reused across runs; unlike `migration_id` it carries no timestamp, so it uniquely identifies this run for telemetry and for the plugin-to-web handoff. `owning_skill` is always `GCP_TO_AWS`. If another skill invoked this run (llm-to-bedrock does, for Assess), also set `initiated_by` to that skill's identifier, e.g. `"initiated_by": "LLM_TO_BEDROCK"`.

5. Confirm both `.migration/.gitignore` and `.phase-status.json` exist before proceeding to Step 1.

## Step 1: Scan for Input Sources and Run Sub-Discoveries

Scan the project directory for each input type. Only load sub-discovery files when their input files are present.

**1a. Check for Terraform files:**
Glob for: `**/*.tf`, `**/*.tfvars`, `**/*.tfstate`, `**/.terraform.lock.hcl`

- If found → Load `references/phases/discover/discover-iac.md`
- If not found → Skip. Log: "No Terraform files found — skipping IaC discovery."

**1b. Check for source code / dependency manifests:**
Glob for: `**/*.py`, `**/*.js`, `**/*.ts`, `**/*.jsx`, `**/*.tsx`, `**/*.go`, `**/*.java`, `**/*.scala`, `**/*.kt`, `**/*.rs`, `**/requirements.txt`, `**/setup.py`, `**/pyproject.toml`, `**/Pipfile`, `**/package.json`, `**/go.mod`, `**/pom.xml`, `**/build.gradle`

- If found → Load `references/phases/discover/discover-app-code.md`
- If not found → Skip. Log: "No source code found — skipping app code discovery."

**1c. Check for billing data:**
Glob for: `**/*billing*.csv`, `**/*billing*.json`, `**/*cost*.csv`, `**/*cost*.json`, `**/*usage*.csv`, `**/*usage*.json`

**Exclude `.migration/**` from these globs** — migration run artifacts (e.g. `openai-usage-profile.json`, `openai-capture/`) must never be re-ingested as billing input.

- If not found → Skip. Log: "No billing files found — skipping billing discovery."
- If found AND **no** Terraform files from 1a → Load `references/phases/discover/discover-billing.md` (billing is the primary source — needs full processing for the billing-only design path).
- If found AND Terraform files **were** found in 1a → Use lightweight extraction below. Do **not** load `discover-billing.md`.

**Lightweight billing extraction (when IaC is the primary source):**

When Terraform is present, billing data is supplementary — only service-level costs and AI signal detection are needed. Extract via a script to avoid reading the raw file into context.

1. Use Bash to read only the **first line** of the billing file to identify column headers.
2. Write a script to `$MIGRATION_DIR/_extract_billing.py` (or `.js` / shell — use whatever runtime is available) that:
   - Reads the billing CSV/JSON file
   - Groups line items by service description, sums cost per service
   - Extracts top 3 SKU descriptions per service by cost
   - Scans service and SKU descriptions (case-insensitive) for AI keywords: `vertex ai`, `ai platform`, `bigquery ml`, `generative ai`, `gemini`, `document ai`, `vision ai`, `speech-to-text`, `natural language`, `dialogflow`, `translation`
   - Outputs JSON to stdout matching the schema in step 4
3. Run the script: try `python3 _extract_billing.py` first. If `python3` is not found, try `python _extract_billing.py`. If neither is available, delete the script and fall back to loading `references/phases/discover/discover-billing.md`.
4. Write the script's JSON output to `$MIGRATION_DIR/billing-profile.json` with this exact schema:

   ```json
   {
     "summary": { "total_monthly_spend": 0.00 },
     "services": [
       {
         "gcp_service": "Cloud Run",
         "monthly_cost": 450.00,
         "top_skus": [
           { "sku_description": "Cloud Run - CPU Allocation Time", "monthly_cost": 300.00 }
         ]
       }
     ],
     "ai_signals": { "detected": false }
   }
   ```

   Services sorted descending by `monthly_cost`. Only include services with cost > 0.

5. Delete the script file after successful execution.

**Critical:** Do **not** Read the billing file with the Read tool. Do **not** load `discover-billing.md` or `schema-discover-billing.md`.

**1d. Live discovery (gcloud CLI):**
Runs AFTER 1a–1c sub-discoveries complete, so its IaC merge sees their output.

- If `$MIGRATION_DIR/live-capture/manifest.json` already exists (a prior capture,
  e.g. a resumed run) → Load `references/phases/discover/discover-live.md` and
  execute from its Step 3 (parse the existing captures; skip consent/preflight/
  capture — they already happened).
- Else if Terraform files were found in 1a → offer ONCE as an optional cross-check:
  "I found Terraform covering your infrastructure. Want me to cross-check it
  against your live GCP project via your authenticated gcloud CLI (read-only,
  with your consent)? This catches resources managed outside Terraform."
  On yes → Load `references/phases/discover/discover-live.md`. On no → continue
  (do not re-ask this run).
- Else if NO Terraform was found (regardless of whether 1b/1c found app code or
  billing files — those cannot produce an infrastructure inventory) → offer live
  discovery as the primary infrastructure source: "No Terraform detected — I can
  discover your project's infrastructure directly via your authenticated gcloud
  CLI (read-only, with your consent). Proceed?" On yes → Load
  `references/phases/discover/discover-live.md`. On no → continue with whatever
  1b/1c produced (billing-only design path remains the fallback).
- If, after the offer, NO sub-discovery produced or will produce any artifact
  (nothing found by 1a–1c AND live was declined or unavailable) → STOP and
  output: "No GCP sources detected. Provide at least one source type (Terraform
  files, application code, or billing exports), or re-run and accept live
  discovery."

**1e. OpenAI usage discovery (Admin API):**
Runs AFTER 1a–1d complete, so its merge sees any `ai-workload-profile.json`.
Load `references/phases/discover/discover-openai-api.md` when EITHER condition
holds; otherwise skip silently:

- `ai-workload-profile.json` exists with `summary.ai_source` of `openai` or
  `both`
- No billing files were found in 1c AND the user mentions OpenAI usage/spend

The sub-file's Step 0 consent gate is the single consent point for this source
— do not pre-ask here (loading the file only presents the gate; declining `[B]`
exits cleanly and must not be re-asked this run). If
`$MIGRATION_DIR/openai-capture/manifest.json` already exists (a resumed run),
execute from its Step 3 (parse the existing captures; consent and capture
already happened). This source supplements billing files — both may run in the
same run.

## Step 2: Check Outputs

After all loaded sub-discoveries complete, check what artifacts were produced in `$MIGRATION_DIR/`:

1. Check for output files:
   - `gcp-resource-inventory.json` — IaC discovery succeeded
   - `gcp-resource-clusters.json` — IaC discovery produced clusters
   - `ai-workload-profile.json` — App code discovery (confidence ≥ 70%) and/or IaC Vertex-strong inference (`discover-iac.md` Step 7d)
   - `billing-profile.json` — Billing data parsed
   - `openai-usage-profile.json` — OpenAI Admin API usage captured
2. **If NO artifacts were produced** (sub-discoveries ran but produced no output): STOP and output: "Discovery ran but produced no artifacts. Check that your input files contain valid GCP resources and try again."
3. **Route output gate (fail closed):** For each triggered sub-discovery route, require the expected artifact(s) before completion:
   - If `discover-iac.md` ran -> require `gcp-resource-inventory.json` and `gcp-resource-clusters.json`
   - If `discover-app-code.md` ran:
     - If its Step 4 exit gate applied (overall AI confidence **below** 70%) **and** no `ai-workload-profile.json` exists -> **allow completion** (app-code route may produce no AI profile).
     - If Step 4 exit applied with confidence below 70% **but** `ai-workload-profile.json` exists with `metadata.profile_source` = `"iac_vertex"` -> **allow completion** (IaC-inferred profile retained).
     - If execution continued to Steps 5–8 (confidence **≥** 70%) -> **require** `ai-workload-profile.json`.
   - If `discover-live.md` ran AND capture happened (`$MIGRATION_DIR/live-capture/manifest.json` exists) -> require `gcp-resource-inventory.json` and `gcp-resource-clusters.json`, with `live_metadata` present in the inventory. (If the user declined consent or gcloud was unavailable, the sub-file exited cleanly — no artifact required.)
   - If full `discover-billing.md` ran OR lightweight billing extraction ran -> require `billing-profile.json`
   - If `discover-openai-api.md` ran AND capture happened (`$MIGRATION_DIR/openai-capture/manifest.json` exists) -> require `openai-usage-profile.json`; when `ai-workload-profile.json` also exists, require `metadata.sources_analyzed.openai_usage_api` = `true` in it. (If the user declined consent or had no Admin key, the sub-file exited cleanly — no artifact required.)
   - If any triggered route is missing its required artifact(s): STOP and output: "Discover route [name] did not produce required artifacts. Resolve the sub-discovery failure before completing Phase 1."

## Step 3: Migration Preview

Load and execute `references/phases/discover/discover-preview.md` to compute the migration preview. This produces `migration-preview.json` and the preview chat block. Skip only if Step 2 found no artifacts (already STOPped).

## Completion Handoff Gate (Fail Closed)

Load `shared/handoff-gates.md`. **Re-read from disk** every artifact below before checking.

**Re-entry guard:** If `preferences.json` exists and `phases.clarify` is `"completed"`: STOP unless the user explicitly confirms re-running Discover. Emit:

```
GATE_FAIL | phase=discover | field=preferences.json | reason=stale_downstream
```

**Checks (all must PASS):**

1. At least one discovery artifact exists (`gcp-resource-inventory.json`, `ai-workload-profile.json`, or `billing-profile.json`). `openai-usage-profile.json` does NOT satisfy this check on its own — it is a supplement (spend and volumes, no integration or capability detail; see SKILL.md Prerequisites) and cannot anchor a run by itself.
2. Route output gates from Step 2 all pass.
3. If any discovery artifact exists → `migration-preview.json` exists with `complexity_signal` set.

**On any FAIL:** Emit `GATE_FAIL | phase=discover | field=<path> | reason=<missing|invalid|stale_downstream>`. **Do NOT modify artifacts to pass the gate.** **Do NOT update `.phase-status.json`.** Tell the user which sub-discovery to re-run.

**On PASS:** Emit `HANDOFF_OK | phase=discover | artifacts=<comma-separated list of files verified>`.

## Step 4: Update Phase Status

Only after `HANDOFF_OK`. In the **same turn** as the output message below, use the Phase Status Update Protocol (read-merge-write) to update `.phase-status.json`:

- Set `phases.discover` to `"completed"`
- Set `current_phase` to `"clarify"`
- Keep all other phase values unchanged unless already advanced by a resumed run

Output to user — build message from whichever artifacts exist:

- If `gcp-resource-inventory.json` exists: "Discovered X total resources across Y clusters."
- If live discovery ran: "Live discovery captured N resources from project [id]." Plus, when IaC also ran: "Drift check: A resources live but not in Terraform, B in Terraform but not live, C config conflicts (live values used)." Plus, when `live_metadata.unmapped_asset_types` is non-empty: "Skipped M unmapped asset types (top: X, Y, Z) — full list in live_metadata."
- If `ai-workload-profile.json` exists: "Detected AI workloads (source: [ai_source])."
- If `billing-profile.json` exists: "Parsed billing data ($Z/month across N services)."
- If `openai-usage-profile.json` exists: "Captured OpenAI usage via Admin API ($X/month across M models)." Plus, when `metadata.capture_warnings` is non-empty: "W usage endpoints failed — affected categories are unknown, not zero (see profile metadata)."

Append the preview block from Step 3 to the output message below.

Format: "Phase 1 of 6 complete (Discover). [artifact summaries joined by space] [preview block from discover-preview.md Step 6]"

Then: "Remaining: Clarify → Design → Estimate → Generate (+ optional Feedback). Next required step: Phase 2 — Clarify. Load `references/phases/clarify/clarify.md` now. Do not load Design, Estimate, or Generate until Clarify completes and `.phase-status.json` marks `phases.clarify` as `completed`."

_Breadcrumbs are emitted only after outer-run `HANDOFF_OK` — never on `GATE_FAIL`, never from inner workshop reprices._

## Output Files

**Discover phase writes files to `$MIGRATION_DIR/`. Possible outputs (depending on what sub-discoverers find):**

1. `gcp-resource-inventory.json` — from discover-iac.md
2. `gcp-resource-clusters.json` — from discover-iac.md
3. `ai-workload-profile.json` — from discover-app-code.md (confidence ≥ 70%, optionally merged) and/or discover-iac.md Step 7d (Vertex-strong IaC only)
4. `billing-profile.json` — from discover-billing.md
5. `openai-usage-profile.json` — from discover-openai-api.md (plus `openai-capture/` raw captures inside the gitignored run directory; the transient `.openai-admin-env` key file is deleted by that sub-file's Step 4 and is never a phase output)
6. `migration-preview.json` — from discover-preview.md (always written when any artifact exists)

**No other files must be created:**

- No README.md
- No discovery-summary.md
- No EXECUTION_REPORT.txt
- No discovery-log.md
- No documentation or report files

All user communication via output messages only.

## Error Handling

- **Missing `.migration` directory**: Create it (Step 0)
- **Missing `.migration/.gitignore`**: Create it automatically (Step 0) — prevents accidental commits
- **No input files found for any sub-discoverer**: STOP with error message (Step 2)
- **Sub-discoveries ran but produced no artifacts**: STOP with error message (Step 3)
- **Sub-discoverer fails**: STOP and report exact failure point and which sub-discoverer failed
- **Output file validation fails**: STOP and report schema errors
- **Extra files created (README, reports, etc.)**: Failure. Discover must produce ONLY the JSON artifact files.

## Scope Boundary

**This phase covers Discover & Analysis ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: Inventory what exists in GCP. Nothing else.**
