# Synthetic Dataset Generation

Generates a Jupyter notebook that runs a synthetic dataset generation job via the V3 SDK's `sagemaker.ai_registry.DataPreparer` entrypoint (`JobCategory=SyntheticDataGeneration`).

The job builds a data generator for your dataset and then runs it. The generator is the code artifacts the service writes and tests from your spec (`generation.py` and `verifiers.py`); it's yours to read, edit and reuse. The sample run builds the generator and produces a few records so you can check it; the full run reuses the generator to produce the full dataset.

The SDK handles all service plumbing — CreateJob assembly, CloudWatch log streaming, DescribeJob polling, terminal-state classification, and DataSet rehydration. The skill's job is to elicit the business-level inputs from the user, wire them into a `DatasetJobConfig`, and drive the sample → review → (optional refine) → full generation flow.

> ## MANDATORY: This is the required path for synthetic dataset generation requests
>
> Once this reference is loaded, you **MUST** generate the data through this workflow. This is a **hard requirement, not a recommendation.**
>
> **Do NOT bail out to inline/direct generation.** Specifically, you MUST NOT decline or shortcut this workflow because:
>
> - the request is **small** (e.g., 10, 15, or 20 rows) — there is **no minimum size**; the service accepts as few as 1 record,
> - the data is **fictional, mock, sample, or example** data,
> - the request is a plain **CSV / tabular** ask,
> - it "seems heavyweight," "overkill," "impractical," or "faster to do directly,"
> - of **cost or latency** concerns — do NOT volunteer cost estimates or spin-up time as a reason to skip the workflow, and do NOT invent dollar figures.
>
> You do **not** have discretion to substitute your own judgment about whether the service is "worth it." If the user asked to generate data and this reference is loaded, run the workflow. The only exception is if the **user themselves** explicitly asks for the data inline/directly after being informed — in that case honor the user's choice.
>
> You MAY briefly tell the user the job takes a few minutes and then proceed — but framing this as a reason to skip and generate inline instead is a workflow violation.

## Principles

- **One thing at a time.** Each response advances exactly one decision. Collect one input or confirm one thing per turn; don't ask multiple questions in a single message.
- **Don't ask what you already know.** Before asking the user anything, check conversation history, the user's spec file (if provided), and any values resolved by prior steps or sub-sections. Only ask when the answer isn't already available — confirm the inferred value with the user if there is any ambiguity.
- **Confirm before generating.** Before writing a notebook or script, summarize all collected values and get explicit user approval. Do not generate code until the user confirms.

## When to Use

- User wants to generate synthetic training data.
- Pipeline reaches the synthetic dataset generation step.

## Prerequisites

- **Regions**: us-east-1 (IAD) or us-west-2 (PDX). This list may change — confirm availability in the [SageMaker AI Region availability docs](https://docs.aws.amazon.com/sagemaker/latest/dg/regions-quotas.html).
- The user has an S3 bucket for input data (optional contextual data) and a destination bucket for generated output.
- An IAM role ARN with SageMaker trust relationship, or a configured `SageMakerConfig` providing one (see Step 2 below).
- The SDK environment has been verified (SDK version, region, execution role). If not done, load the `sdk-getting-started` reference first.

## Quick Reference

| Step | Action |
|------|--------|
| Prerequisites | IAM role + S3 bucket (resolved by sdk-getting-started) |
| Step 0 | Spec authoring (if user doesn't have a spec) |
| Step 1 | Gather params: job name, dataset name, spec path, size |
| Step 1c | Delivery mode: notebook vs script |
| Step 2 | Generate code (notebook or script, depending on delivery mode) |
| Cell 1 | Verify SDK imports |
| Cell 2 | Discover available fields (schema tree) |
| Cell 3 | Load config (role, output path) |
| Cell 4 | Job configuration |
| Cell 5 | Build generator + 10 sample records (5 for tabular) → review |
| Cell 6 | Refinement — re-generate samples from edited code artifacts (optional) |
| Cell 7 | Full generation (reuses the generator) |

## Workflow

### Step 0: Spec Authoring or Refinement

Determine which starting state applies and route accordingly:

**Before routing, say exactly:**

> "Note: The delivered output may vary from constraints specified in the spec, such as distributions — expect close but not exact adherence."

**State A — Spec file already exists:**
Skip to Step 1. Use the existing spec as-is.

**State B — No spec file exists:**
Guide the user through spec creation. Read and follow `references/spec-authoring-workflow.md`.

### Step 1: Gather Generation Parameters

**Early tabular detection:** Before gathering parameters, analyze the user's initial prompt. If it contains tabular signals (column names with data types, value ranges, "rows", "features", "binary/multi-class target", "CSV", mention of XGBoost/LightGBM/BERT on tabular/traditional ML), surface the choice to the user:

**SHORTCUT — skip the question if intent is already clear:**

- If user explicitly requests an LLM output format (HF_Prompt_Completion, Bedrock_Converse, OpenAI_Messages, etc.) OR mentions SFT/DPO/RLVR → proceed with GenAI directly. Do NOT ask.
- If user explicitly says "CSV", "tabular", "XGBoost", "database seeding", or "Feature Store" → proceed with tabular directly. Do NOT ask.
- Only ask the question below when format intent is ambiguous (structured fields present but no clear format/training-technique signal).

> "Your request describes structured/tabular data (columns, types, value ranges). I can generate this two ways. **Tabular mode** outputs structured data in a tabular format of your choosing (CSV, Parquet, SQLite) — best for XGBoost, LightGBM, BERT on tabular, database seeding, Feature Store population. **GenAI mode** outputs JSONL in an LLM training format (prompt/completion, messages, etc.) — best for SFT, DPO, RLVR fine-tuning of language models. Which would you like?"

⏸ Wait for user to choose.

If user picks **tabular**: collect the tabular-specific params below, THEN proceed to Step 1b (Tabular Spec Preparation). Do NOT ask about LLM output formats or fine-tuning techniques.

**Tabular params to collect (in order):**

1. **Dataset name** — a name for the generated dataset.
2. **Full dataset size** — how many records (1-50000). Phrase as "How many records would you like in your final dataset?"
3. **Seed data (CDG gate)** — ask: "Do you have existing data to augment or match? (e.g., a CSV, SQLite database, or Parquet file in S3)"
   - If yes → collect the S3 URI, validate it exists (`aws s3 ls`). This becomes `INPUT_DATA_S3_URI`. The task is CDG.
   - If no → NCDG. The schema comes entirely from the spec. Leave `INPUT_DATA_S3_URI = ""`.
4. **Output format** — ask: "What output format? (CSV is default; also available: Parquet, SQLite)"
   - If user already stated format in their prompt → use it, don't re-ask.
   - Default to CSV if user says "doesn't matter" or no preference.

After collecting these → proceed directly to Step 1b with full context. When Step 1b returns, collect the **Job base name** (per-job input 1 below) before proceeding to Step 1c. Use defaults for models and MLflow unless the user mentioned them in their original request.

If user picks **GenAI**: proceed with normal Step 1 parameter gathering (output format, model selection, etc.).

Use cascading fallback: conversation → project files → ask one unresolved question at a time.

Collect the following:

**One-time setup (resolved by Cell 3 via SDK):**

5. **Output S3 URI** — Base S3 prefix for all generated output (must end with `/`). The bucket must be in the same region as the SageMaker endpoint. Resolved from `session.default_bucket()`. This prefix is shared across all Data Preparation primitives (synthetic dataset generation, dataset quality, dataset transformation) — downstream skills should reuse it so all pipeline outputs are co-located under a single IAM-scopeable prefix.
6. **Role ARN** — IAM role for the job (must trust `sagemaker.amazonaws.com`). Resolved from `get_execution_role()`.

**Per-job inputs:**

1. **Job base name** — A unique prefix (alphanumeric + hyphens, max ~40 chars to leave room for the SDK's timestamp suffix). If the `<descriptive_name>_data_spec.md` exists, that `<descriptive_name>` is a good candidate.
2. **Dataset name** — A name for the dataset being generated.
3. **Spec file S3 path** — Full S3 URI to the spec file (e.g., `s3://my-bucket/input/my-spec/my_data_spec.md`). Any `.txt` or `.md` file is accepted — no renaming required. The agent should detect that a file is a spec by its content or metadata, not by a fixed filename. If the user provides a local path instead of an S3 URI, offer to upload it using `aws s3 cp <local_path> s3://<bucket>/input/<job-base-name>/` and use the resulting S3 URI.
4. **Input data S3 URI** *(optional)* — Contextual data files for CDG (contextual data generation) workflows. Supported formats and limits: see `references/api-reference.md` → *Contextual data (CDG)*. For tabular use cases, `.sqlite`/`.db` files serve as seed databases — schema, FKs, and distributions are auto-discovered.
   1. **Check the spec** for file paths in the Input Data section.
   2. **If paths are present:** Ask the user — "Your spec references contextual data files. Is this a contextual data generation job?"
      - **If yes and paths are local:** Offer to upload using `aws s3 cp` (single file) or `aws s3 cp --recursive` (folder), then use the resulting S3 URI.
      - **If yes and paths are S3:** Run `aws s3 ls <URI> --recursive` and verify every referenced file exists at the expected key. If any are missing, do NOT proceed — offer to fix by either moving/renaming the S3 objects to match the spec, or updating the spec references to match the actual S3 structure. Mismatched paths cause the generator to silently skip files and hallucinate content.
      - **If no:** Run as NCDG (non-contextual data generation). Clear the `INPUT_DATA_S3_URI` parameter.
   3. **If no paths in the spec:** Ask the user if they have contextual data. If yes, collect the URI and validate as above. If no, run as NCDG.
5. **Full dataset size** — How many total records the user wants in their final dataset (1-50000). The skill will first generate a small sample for quality review (5 records for tabular, 10 for standard), then generate this full amount once the user approves. When asking the user, phrase it as: "How many records would you like in your final dataset?" Do NOT call it "number of samples" — that's confusing with the sample batch.

   **If the data is for fine-tuning, state the minimum in the same message you ask
   the size question.** Read
   `../dataset-quality/references/training-volume-requirements.md` and follow it —
   it carries the number, how to size for a planned split, and the carve-outs for
   non-training generation. Do not restate the minimum from memory.

   Give the minimum as a viability concern, not a sizing preference: below it,
   training is more likely to fail. "A few hundred is a good starting point" reads
   as a quality-vs-cost tradeoff, and a user may reasonably pick less without
   learning their number may not train at all. Quote the smallest size that clears
   the minimum for their setup and let them decide from there.

   **If the data is for fine-tuning and the user asks for more than ~20,000 records,
   confirm the count before generating.** Read `references/large-dataset-requests.md`
   and follow it — it carries the guidance (where gains flatten, which use cases justify large counts, when to suggest one
   job per document set). It is a confirmation, not a cap: the service accepts up to
   50,000, and once the user confirms, generate what they asked for.
6. **Generation and verification models** — Present the defaults and offer to change:

   > "For data generation I'll use **Claude Haiku 5.5**, for verification **Claude Sonnet 5**, and for code generation **Claude Sonnet 5**. These are the defaults — would you like to use different models, or proceed with these?"

   If the user wants to change, offer the models listed in `references/supported-models.md` and use the ID from the chosen model's row. Offer only the models marked Yes in its Code generation column for the code generation model.

   If the user confirms defaults, move on.

7. **MLflow tracking config** *(optional)* — Ask the user: **"Do you want to log this generation job's parameters and metrics to SageMaker managed MLflow?"**

    - **If no (default):** leave MLflow unset — do not pass `mlflow_config`. The job runs without MLflow tracking. Skip the rest of this step.
    - **If yes:** read `../manage-mlflow/references/app-discovery-workflow.md` to discover existing MLflow apps and let the user choose one (or create one if none exist); then read `references/mlflow-config-requirements.md` and validate the user's setup against it (app ARN region, and the execution-role permissions MLflow logging needs).

> **⚠️ Same-region requirement:** input and output buckets must share the SageMaker region. See `references/api-reference.md` → *Parameter constraints*.

If sdk-getting-started ran, the execution role and region are already validated. Cell 3 resolves them via the SDK at runtime — no config.yaml dependency.

If any required parameter is missing, ask the user. Don't ask for parameters you can infer from conversation context.

⏸ Wait for user.

### Step 1b: Tabular Spec Preparation

If the user's request may produce tabular output (CSV, Parquet, SQLite, a database seed, or structured rows matching a schema), **read `references/tabular-authoring.md` and follow it from the start.** That reference owns tabular detection, spec hardening with per-format directives, the hard-gate approval, and the hardened-spec upload.

If Step 1's early tabular detection already fired on the user's prompt, the reference skips its own detection and proceeds directly to spec hardening. Otherwise, the reference reads the user's spec file (if any) to decide. When the reference finishes (tabular path complete, user declined tabular, or no tabular signals detected), return here and proceed to Step 1c.

### Step 1c: Delivery Mode

Determine how the generated code will be delivered and executed. The skill supports the same pipeline through **two delivery modes**. Both modes produce identical results — the only difference is the executor.

- **Notebook delivery** — The agent generates a Jupyter notebook with cells the user runs. Default when the user explicitly asks for a notebook, or when called from a workflow that wants a rerunnable artifact.
- **Script delivery** — The agent writes a Python script and executes it directly. Fully autonomous; no user-run cells.

If the user already specified a preference (e.g., "give me a notebook", "just run it", "execute it") or a calling reference requested a delivery mode, skip the question and proceed with that choice.

Otherwise, ask:

> "Would you like me to run the pipeline directly, or generate a Jupyter notebook you can execute yourself?"

⏸ Wait for user.

**Confirm the plan before generation.** Summarize the collected inputs and wait for the user's go:

> "Here's the synthetic dataset generation setup:
>
> - **Dataset name:** [DATASET_NAME]
> - **Job base name:** [JOB_BASE_NAME]
> - **Spec file:** [SPEC_S3_URI]
> - **Input data (CDG):** [INPUT_DATA_S3_URI or 'none (NCDG)']
> - **Output format:** [OUTPUT_FORMAT]
> - **Full dataset size:** [NUM_SAMPLES] records
> - **Sample size (for review):** [SAMPLE_SIZE] records before full generation ([5 if tabular, 10 otherwise])
> - **Generation model:** [GENERATION_MODEL]
> - **Verification model:** [VERIFICATION_MODEL]
> - **Code generation model:** [CODE_GENERATION_MODEL]
> - **MLflow tracking:** [MLflow app ARN or 'none']
> - **Output prefix:** [OUTPUT_S3_URI]
> - **Delivery mode:** [notebook | script]"

Link to [SageMaker pricing](https://aws.amazon.com/sagemaker/ai/pricing/) rather than calculating a dollar estimate.

Ask for explicit approval. Stop until approved.

**If script delivery:**

- Ensure sdk-getting-started has run.
- Strip the `# NOTEBOOK_ONLY` `%pip install` line from Cell 1 and run its `pip` equivalent (`pip install 'sagemaker>=3.30.0,<4.0' boto3`) directly before writing or running the script. Do not embed install commands in the script itself.
- Write one script per pause, because a script cannot keep `sample_dataset` in memory while the user reviews the sample:
  - `scripts/synthetic_generation_sample.py`: Cells 1–5, ending with `print(sample_dataset.job_arn if WAIT else sample_job.job_arn)`. Report that ARN to the user; the next script needs it.
  - `scripts/synthetic_generation_full.py`: Cells 1–4 and Cell 7, written after the user approves the samples. In place of Cell 5, re-attach to the Cell 5 sample job: `sample_dataset = DataPreparer.attach("<sample job ARN>")`. Never re-run Cell 5 to get `sample_dataset`: that submits and pays for another sample job. A Cell 6 refinement script re-attaches the same way.
- After generating each script, ask the user whether they want to run it themselves with `python <script path>`, have the agent execute it and wait for completion before reporting back, or have the agent start it and return control before completion.

- **If the user picks running it themselves:** Leave `WAIT = True` in Cells 5, 6, 7 (default), so the user's own run shows the status panel. Wait for user to come back.
- **If the user picks executing and waiting:** Leave `WAIT = True` and execute the script. The cell blocks until the job completes and prints the DataSet info. For the sample script, continue to the sample-review prompt; for the full script, run the post-completion record verification.
- **If the user picks starting without waiting:** Set `WAIT = False` in Cells 5, 6, 7 when assembling the script, then execute. The script submits the job, prints its ARN, and ends; nothing polls. The user can say "check status" or "is it done?" later — follow `references/progress-check.md`. On a terminal `Completed`: for the sample script, `sample_dataset = DataPreparer.attach(job_arn)` and show the review prompt; for the full script, `full_dataset = DataPreparer.attach(job_arn)` and run the post-completion record verification.

**Checking status (script mode):**

- Use `DataPreparer.attach(job_arn, wait=False)` to get a Job handle, then call `.refresh()` for current status (`job.job_status`, `job.failure_reason`). Or follow `references/progress-check.md` for live record counts and partial output.

**If notebook delivery:** Proceed to Step 2 as written below.

### Step 2: Generate Notebook

Add the following as a markdown cell at the top of the generated notebook:

> ⚠️ This feature uses Amazon Bedrock for data generation. [Bedrock Service Terms](https://aws.amazon.com/service-terms/) and pricing apply.
>
> Models: [GENERATION_MODEL] (data generation), [VERIFICATION_MODEL] (verification), [CODE_GENERATION_MODEL] (code generation).
>
> Cost: Scales with dataset size and record complexity. Runs using deterministic-only verification cost less than runs using LLM-augmented verification.

**The disclosure cell above is for the generated notebook only. It is NOT a decision input. See the MANDATORY directive at the top of this reference.**

Save all generated artifacts under the project directory structure defined by the directory-management reference, if available.

- Ask the user if they have a notebook they want you to add the cells to, or if they want a new notebook.
- If existing notebook, append the cells.
- If new notebook, create `[title]_synthetic_generation.ipynb`.

#### 🚨 Code Generation Rules

- ✅ Use EXACTLY the imports and code shown in `code_templates/synthetic_generation.py`
- ❌ Do NOT add additional imports
- ❌ Do NOT create variables before they're needed
- ❌ Do NOT re-add the legacy `boto3.client("sagemaker", endpoint_url=...)` + `sagemaker.create_job(...)` pattern — DataPreparer owns this end-to-end

#### Code Template

Read `code_templates/synthetic_generation.py` for the complete per-cell code. The template is a Python file where each `# Cell N: Label` comment marks the start of a new cell. Split on these markers — everything between one marker and the next becomes one notebook cell (or one script section in script-delivery mode). Follow the per-cell instructions below for what to populate and when to pause.

#### Cell 1: Verify the SDK

> Write Cell 1 from the template in `code_templates/synthetic_generation.py`.

#### Cell 2: Discover Available Fields

> Write Cell 2 from the template in `code_templates/synthetic_generation.py`.

#### Cell 3: Configure Intelligent Defaults (verify or configure)

> Write Cell 3 from the template in `code_templates/synthetic_generation.py`.

**Instructions for Cell 3:**

- This cell resolves the execution role and default S3 bucket using the SDK (same pattern as mainline skills).
- `get_execution_role()` resolves from the caller's STS identity.
- `session.default_bucket()` returns `sagemaker-{region}-{account_id}` by convention.
- `ROLE_ARN`, `OUTPUT_S3_URI`, and `session` are available to all subsequent cells.

#### Cell 4: Job Configuration

> Write Cell 4 from the template in `code_templates/synthetic_generation.py`.

**Instructions for Cell 4:**

- Pre-fill `JOB_BASE_NAME`, `DATASET_NAME`, `SPEC_S3_URI`, `INPUT_DATA_S3_URI`, `NUM_SAMPLES`, `IS_TABULAR`, `GENERATION_MODEL`, `VERIFICATION_MODEL`, and `CODE_GENERATION_MODEL` from what the user provided in Step 1. Set `IS_TABULAR = True` if Step 1b confirmed tabular generation. The output format (CSV/Parquet/SQLite) is communicated via the spec text — the platform's modality classifier reads it from the task description, not from a config variable.
- `OUTPUT_S3_URI` and `ROLE_ARN` are already set from Cell 3 — do not ask the user for them.
- `SPEC_S3_URI` must be the **full S3 URI** to the spec file (not a directory prefix, not a bucket-relative key).
- `INPUT_DATA_S3_URI` is optional — only set it if the user has contextual data for CDG. Leave as `""` for NCDG.
- `MLFLOW_CONFIG` is optional — keep it `None` unless the user asked for MLflow tracking in Step 1 (input 7). If they did, fill in their MLflow app ARN. The same `MLFLOW_CONFIG` flows into the sample (Cell 5) and full (Cell 7) runs.
- Pass `session` to DataPreparer so it uses the same config-loaded session.
- Tell the user to review and confirm the configuration.

#### Cell 5: Sample Generation (10 records for review, or 5 for tabular)

> Write Cell 5 from the template in `code_templates/synthetic_generation.py`.

**Instructions for Cell 5:**

- **Before running, tell the user:** "This will take several minutes, even for a small sample. The service writes and optimizes *code* that generates your data — it iterates, generating samples, verifying quality, and refining the code until samples consistently pass checks. Once optimized, full generation reuses this code and completes much faster."
- The submission streams CloudWatch logs and emits a live status panel showing elapsed time + accumulated CW log lines + sample-count progress (`Samples: X / N (Z%)`) polled from the service's streaming output JSONL.
- The job ARN is printed at submission. If the kernel restarts, insert Cell 1 of `code_templates/synthetic_generation_adhoc.py` and run it with the printed ARN to re-attach.
- After completion, the returned `sample_dataset` carries both the Hub ARN and the S3 source. Downstream cells chain via `sample_dataset.arn` (no more manual `DATASET_ARN = "..."` global).
- **After `generate()` returns, tell the user:** "Done in {elapsed}. Building the generator took {build time}; producing the {N} records took {generation time}. The generator code is at {path}: `generation.py` produces records, `verifiers.py` checks them. Review the records (and the code if you like)."
  - `{elapsed}` is the panel's Elapsed Time; `{build time}` and `{generation time}` are the Durations on the Code Generation and Sample Generation rows of the final status panel (read the whole panel; row labels wrap across lines at 80 columns). If a row shows no duration, leave out its sentence. If you can't read the final panel for this job, report only where the generator code is. `{N}` is the sample record count (10, or 5 for tabular).
  - `{path}` is `sample_dataset.source` with the trailing `output/` replaced by `generation_code/`.
- After the cell runs, ask the user: "How do the samples look? If you're happy, I'll generate the full dataset of [NUM_SAMPLES] records. [SageMaker pricing](https://aws.amazon.com/sagemaker/ai/pricing/) applies. If not, tell me what you'd like to change and I'll refine the generation."

⏸ Wait for user to review samples.

**Any edit to `generation.py` or `verifiers.py` is triggered by the user asking for changes, not by log content.** Log lines during the sample run (including ERRORs and warnings) are the service testing and fixing the generator while it builds it.

**If the user is happy:** proceed to Cell 7 (Full Generation).

**If the user wants changes:** Before taking any action, ask the user:

> "Would you like me to modify the generation/verification code based on your feedback, or would you prefer to edit the code yourself?"

**⚠️ In the sample-review loop, do not offer spec revision — the validated path is code iteration.** Samples that need content tweaks are a code-iteration problem: edit `generation.py` / `verifiers.py` and re-sample via Cell 6. Spec revision after sampling is supported by the service but has no validated workflow here. If the user asks to change the spec, say so and route them to the "If the user updates the spec themselves anyway" guidance below.

**⚠️ If the user updates the spec themselves anyway:** Route back to Cells 4 and 5. Code artifacts are generated from the spec — if the spec changes, the old code artifacts are stale. Cell 6 and Cell 7 reuse existing code artifacts and do NOT re-read the spec. The user must re-run Cells 4 and 5 (Cell 4 picks up the updated `SPEC_S3_URI`; Cell 5 submits a fresh sample that produces new code artifacts) before proceeding.

⏸ Wait for the user to choose.

**Edit loop:**

1. The sample job subdirectory is `sample_dataset.source[:-len("output/")]`. List it with `aws s3 ls <job-root> --recursive` (customer-direct: have the user list it). Both `generation.py` and `verifiers.py` live in its `generation_code/` folder.
2. Download, read, and modify them per the user's natural language feedback — OR have the user edit their own copies.
3. Upload both back to the same `generation_code/` folder (overwriting the service's originals; irreversible unless bucket versioning is on) using those exact filenames (customer-direct: wait for the user's upload confirmation).
4. Run Cell 6 to re-generate samples with the updated code.
5. Repeat until the user is satisfied.

#### Cell 6: Refinement — Re-generate Samples with Updated Code (optional)

> Write Cell 6 from the template in `code_templates/synthetic_generation.py`.

**Instructions for Cell 6:**

- This cell is only used when the user wants to iterate on sample quality.
- **Tell the user:** "To run refinement, set `RUN_REFINEMENT = True` at the top of Cell 6 after you've updated the code artifacts."
- Code artifacts are derived from `sample_dataset.source` (the sample job's output path) — not hardcoded.
- The user modifies `generation.py` and `verifiers.py` at the path printed by Cell 5's sample run, then re-runs this cell.
- **⚠️ Warn the user:** Once code artifacts are modified (by either the agent or the customer), they are out of sync with the original data generation spec. From this point forward, the code artifacts — not the spec — are the source of truth for generation and verification logic.
- After running, ask the user again if they're happy with the samples.
- If the user wants further changes, repeat the download → modify → upload → re-run cycle. You can re-run Cell 6 — DataPreparer auto-names each submission (base name + UTC timestamp + counter) so consecutive runs won't collide.
- Once satisfied, proceed to Cell 7 for full generation.

⏸ Wait for user.

#### Cell 7: Full Generation

> Write Cell 7 from the template in `code_templates/synthetic_generation.py`.

**Instructions for Cell 7:**

- This cell runs the full generation with the user's target `NUM_SAMPLES`.
- If the user iterated on samples (Cell 6 ran), this reuses the user-edited `CodeArtifacts`. Otherwise it reuses the service-generated `CodeArtifacts` from the sample run. The spec is only consumed by Cell 5 — it is not re-read here.
- **Before running, tell the user:** "This reuses the latest generator (your edited one if you refined it) and goes straight to producing [NUM_SAMPLES] records."
- Generation jobs can take significant time depending on dataset size. The live status panel shows `Samples: X / Y (Z%)` progress the whole time.
- **Kernel restart recovery:** The job ARN is printed at submission time. If the kernel restarts or the connection drops, insert Cell 1 from `code_templates/synthetic_generation_adhoc.py` as a new cell in the user's notebook, replacing `[JOB_ARN]` with the actual ARN and `[DATASET_VAR]` with the variable name expected by downstream cells (`sample_dataset` for Cell 5 recovery, `refined_dataset` for Cell 6, `full_dataset` for Cell 7). This reconnects to the running job with the same Rich progress panel and returns the DataSet when complete. Tell the user to note the ARN from the submission output before long runs.
- `full_dataset.arn` is the Hub content ARN you pass to the dataset-quality reference as the next step, OR into `ModelTrainer(input_data_config=[InputData(channel_name="train", data_source=full_dataset.source)])` for fine-tuning.
- If the service fails Hub finalization (rare), DataPreparer raises `DataPreparerJobFailedError` with `failure_reason="HUB_FINALIZATION_FAILED"`. The compute output is still valid on S3 and accessible via the failed job's `JobConfigDocument`; see `DatasetJobConfig.print_schema` for fields.
- **Post-completion record verification.** After `preparer.generate()` returns:
  1. Read `total_samples` from `report.json` at the job output root.
  2. Count rows in the output samples file (in the `output/` subdirectory).
  3. Report both to the user: "**Generation complete: {total_samples} records** (report.json) / **{row_count} rows** (from the output samples file). Dataset ARN: {full_dataset.arn}."
  4. If `total_samples < 0.8 × NUM_SAMPLES` or the output samples file is missing entirely, this is a **partial generation** — tell the user: "**{total_samples}/{NUM_SAMPLES} records generated ({percent}%).**"
  5. Report the Bedrock tokens the job used, from `token_usage_report.json` at the job output root.

  See `references/reading-synthetic-dataset-generation-job-logs.md` for how to interpret the outcome.

⏸ Wait for user.

### Handling Progress Check Requests

When the user asks about job progress, status, or how many records have been generated (e.g., "how many samples generated?", "how many records have been created?", "what's the status?", "how many samples do we have so far?"), read `references/progress-check.md` and follow it.

### Handling Stop Requests

When the user asks to cancel or stop a running synthetic dataset generation job (e.g., "stop the job", "cancel", "abort", "kill it", "the spec is wrong, stop it", "this is taking too long — stop"), read `references/stop-job.md` and follow it.

<!-- markdownlint-disable-file MD029 -->
