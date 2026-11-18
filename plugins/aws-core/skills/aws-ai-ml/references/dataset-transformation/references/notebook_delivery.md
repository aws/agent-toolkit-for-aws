# Notebook Delivery

Use this reference when the delivery choice in the workflow is a **notebook** — the user wants a shareable, rerunnable artifact rather than an inline transformation run.

The notebook delivery path produces a singular, multi-run Jupyter notebook
assembled from canonical code templates. Local-lane notebooks use the runtime
helpers in `<project-dir>/scripts/transform_helpers.py`; API-lane notebooks use
the capability-specific API templates. The user executes the notebook
themselves; the agent runs samples only for local-lane validation.

This file documents the **end-to-end procedure**. Cell-level templates live in
`notebook_structure.md`. Shared append and run-number semantics live in
`notebook_run_lifecycle.md`. For the local lane, pre-built script and
ManifestWriter integration live in `notebook_prebuilt_ops.md`. Read only the
references for the selected lane before generating cells.

## Table of Contents

- [When to Use Notebook Delivery](#when-to-use-notebook-delivery) — Pick-this-mode criteria
- [Coverage](#coverage) — Operations supported by the notebook flow
- [SDK and Telemetry Requirements](#sdk-and-telemetry-requirements) — shared SDK prerequisite + `set_attribution` rules
- [Append-vs-New-Notebook Decision](#append-vs-new-notebook-decision) — When to append vs create the notebook
- [Pre-Flight (Run Once Per Project)](#pre-flight-run-once-per-project) — Bootstrap of project-local helper scripts
- [Hub registration requires an S3 `OUTPUT_PATH` (strict)](#hub-registration-requires-an-s3-output_path-strict) — One upload per run; no manual upload in the Hub cell
- [Procedure](#procedure) — Step-by-step end-to-end generation flow
- [API Lane in Notebooks](#api-lane-in-notebooks) — Using the API lane from notebook cells
- [Local-Lane Worked End-to-End Example](#local-lane-worked-end-to-end-example-3-op-workflow-clean--dedup--schema_transform) — `clean → dedup → schema_transform` walkthrough

## When to Use Notebook Delivery

Pick notebook delivery when **any** of these apply:

- The user explicitly asks for a notebook.
- The transformation is part of a fine-tuning workflow where the user wants a rerunnable artifact alongside the training pipeline.
- The user needs a reviewable, shareable artifact for teammates.
- The user wants to iterate on a single transform interactively (any number of ops — the run-tracked notebook supports both single-op exploration and full multi-op workflows).

Otherwise, prefer the lane's inline flow: `spec_execution_flow.md` for local
execution or `api-execution-flow.md` for API execution.

## Coverage

The notebook delivery path supports **two execution modes**:

1. **Local lane** (when Step 0 routing selects the local lane; a language
   filter and PII redaction excepted): all 7 operations — `ingest`, `clean`,
   `filter`, `dedup`, `split`, `merge`, `schema_transform` — plus fused
   combinations. Operation cells come from `code_templates/` and use the
   runtime helpers in `transform_helpers.py`. The manifest entry count matches
   the script flow for the same spec.
2. **API lane** (the default for S3/Hub sources, when the user chooses it for a local source — see Step 0 routing — or for a language filter or PII redaction): uses the SageMaker DataTransformation API via the `DataPreparer` pySDK. Supports the built-in operations described by the live schema and `api-operator-configs.md`, the CodeGen two-job path (generate/sample, review, then a separate approved execution artifact), and direct BYOC for user/agent-authored `transformer.py`. See [API Lane in Notebooks](#api-lane-in-notebooks) for the notebook-specific cell layout.

## SDK and Telemetry Requirements

### chdir-to-project-root guard (mandatory)

Every Cell 1 (Setup) of every local run section starts with the
chdir-to-project-root guard in `../code_templates/transformation.py` Cell 1.
Copy the cell from the template rather than reconstructing it.

Jupyter sets the kernel's CWD to the notebook's parent directory (`<project-root>/notebooks/`). Without this guard, `from transform_helpers import init_manifest` fails because `sys.path.insert(0, "scripts")` resolves to `notebooks/scripts/`. The guard is **idempotent**: it checks the directory's basename (`os.path.basename(os.getcwd()) == "notebooks"`), not a level count, so re-running Cell 1 in the same kernel session does **not** chdir up multiple levels. All subsequent paths in the cell (and in every later cell of the run section) use `<project-root>`-relative paths thanks to this chdir.

### SageMaker SDK prerequisite

When a run imports `sagemaker` for Hub registration or API execution, complete
the shared `sdk-getting-started` workflow before assembling or running the
notebook, then verify the required imports in the target kernel. This
dataset-transformation workflow does not install the SDK, emit an install cell,
or copy SDK artifacts because those capabilities are owned by the upstream
dependency.

Every cell that imports `sagemaker.*` must set
`Attribution.SAGEMAKER_AGENT_PLUGIN`. The canonical local and API cells already
contain that attribution; preserve it while substituting placeholders.

If the notebook does not import the SageMaker SDK, omit the attribution lines.
If `hub_arn` is added in a later run, verify the shared SDK prerequisite before
appending that run; do not retroactively edit run 001.

## Append-vs-New-Notebook Decision

If `notebooks/<project-name>.ipynb` exists, append a
`## Dataset Transformation (Run N)` section where `N` is one greater than the
highest existing run. Otherwise create the notebook with its first run.

See `notebook_run_lifecycle.md` § "Append-Only Run Sections" for full semantics.

## Pre-Flight (Run Once Per Project)

Before generating local-lane notebook cells, ensure the four pre-built Python
files exist in the project's `scripts/` directory:

- `<project-dir>/scripts/transform_helpers.py`
- `<project-dir>/scripts/manifest_writer.py`
- `<project-dir>/scripts/dedup_filter.py`
- `<project-dir>/scripts/dataset_split.py`

If any are missing, copy them from the skill's `scripts/` directory using the bootstrap snippet documented in `notebook_prebuilt_ops.md` → "Bootstrap Procedure". The bootstrap is idempotent — existing copies are preserved (this protects user edits). Run the bootstrap **out-of-band** (the agent executes it as part of preparing the notebook); it is **not** added as a notebook cell. API-lane notebooks skip this local-helper bootstrap.

Pre-built scripts and the runtime helpers are copied into the project on first use, so the notebook is self-contained and portable.

### Hub registration requires an S3 `OUTPUT_PATH` (strict)

When the spec sets `hub_arn`, `OUTPUT_PATH` **MUST** be an `s3://` URI. This reference has no validated notebook workflow for Hub registration with a local `OUTPUT_PATH`. At spec creation time, if the user wants Hub registration but supplies a local output path, explain that requirement and ask them to choose an S3 destination before saving the spec.

The Hub registration cell template in `notebook_structure.md` enforces this rule: it reads `writer.final_output` (which `finalize()` already wrote) and raises `RuntimeError` when the value is not `s3://...`. Do **NOT** insert a `s3.upload_file(...)` / `aws s3 cp` call into the Hub cell to bridge a local output to an S3 URI — that duplicates the upload that `finalize()` is responsible for and re-introduces the `s3:/` ghost-folder bug. There is exactly one upload per run, performed by `finalize()`.

If a user with a working notebook later decides to add Hub registration, the correct migration is: change `OUTPUT_PATH` in `### Setup` to an `s3://` URI, re-run from `### Initialize Manifest` onward. Do not patch the Hub cell.

## Procedure

### 1. Determine the project directory

Use the `directory-management` skill to resolve `<project-dir>` and `<project-name>`. The notebook lives at `<project-dir>/notebooks/<project-name>.ipynb`.

### 2. Compute the next run number

Compute `NNN` per `notebook_run_lifecycle.md` → "Computing the next run
number". Take `max(existing) + 1` across all six sources documented there:

- Markdown cells matching `## Dataset Transformation \(Run (\d+)\)` in the existing notebook (if any).
- Code-cell `metadata.run` values in the existing notebook.
- `<project-dir>/scripts/run_*` directories (present when the project has prior **script-mode** runs — keeps notebook-mode and script-mode runs from colliding when both deliveries are mixed in the same project).
- `<project-dir>/data/transformed/run_*` directories.
- `<project-dir>/specs/transformation_spec_run_NNN.json` files.
- `<project-dir>/scripts/api_<capability>_job_J_run_NNN.py` files.

If no prior runs exist anywhere, `NNN = 1`.

### 3. Resolve the spec

For a local-lane run, the spec lives at
`<project-dir>/specs/transformation_spec_run_NNN.json`; the notebook setup cell
references that path. API-lane notebooks use the selected capability
template's configuration cells and do not add a local spec-path reference
unless that template defines one.

### 4. Run pre-flight (copy helper scripts if missing)

For the local lane, see "Pre-Flight" above and verify the four project-local
copies exist before generating cells; copy from the skill if any are missing.
For the API lane, skip the local-helper bootstrap. When the run imports the
SageMaker SDK, verify that the upstream `sdk-getting-started` prerequisite has
completed successfully.

### 5. Generate the run section cells

**API-lane runs:** if Step 0 routing selected the API lane and Step 2
revalidated it, the cell source is different — use one capability-specific API
template per operation/job as described under "## API Lane in Notebooks", not
the local templates below. Follow that assembly, then return to Step 6 to write
and validate the `.ipynb`. The rest of this step covers the local lane.

Read these references **before** writing cells:

- `notebook_structure.md` — full cell-by-cell template, including the markdown header, setup cell, manifest init cell, per-step cells (one per operation), finalize cell, and optional Hub registration cell.
- `notebook_structure.md` § "Notebook JSON Writing Guide" — Jupyter notebook JSON formatting (source-array conventions, escaping, metadata, nbformat). Apply these rules to **every** cell.
- `notebook_prebuilt_ops.md` — how `dedup`/`split` step cells import the project-local pre-built functions, and why the setup cell uses `sys.path.insert(0, "scripts")`.
- `notebook_run_lifecycle.md` — every code cell in the run gets `"metadata": {"run": NNN}`.
- `spec_execution_flow.md` → "LLM Operation Fusion" — fuse LLM-generated ops into a single step cell + single manifest entry. Pre-built ops (`dedup`, `split`) never fuse.
- `references/op_<name>.md` — per-op transform-function bodies, parameter conventions, and stats schemas.

For each operation in the spec (after fusion), generate a **markdown step heading + code cell**:

| Op category                                                              | Cells produced                                                                                                                                                                                              |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LLM-generated (`ingest`, `clean`, `filter`, `merge`, `schema_transform`) | One markdown heading (`### Step K: <op>`) plus Cell 4 from the matching operation template.                                                                                                                 |
| Pre-built (`dedup`, `split`)                                             | One markdown heading + one code cell that imports the function from the setup cell's namespace and calls it directly (`dedup_dataset(...)` / `split_dataset(...)`), followed by `record_step(writer, ...)`. |

Do **not** generate `%%writefile` cells, `subprocess.run([...])` calls, or
per-run `<op>_fn.py` scripts. The notebook-native flow copies cell-local
functions from canonical templates; the agent must not write to
`scripts/run_NNN/`.

In addition to the code cells above, **insert markdown cells at these boundaries** so the user sees a guided walkthrough rather than a wall of code (see `notebook_structure.md` → "Cell-by-Cell Template (per run section)" for the canonical layout):

1. **Run header** (cell 0): `## Dataset Transformation (Run N)` followed by a
   parameter bullet block for input, output, operation chain, and target
   format. For the local lane, include Hub registration; for the API lane,
   include the selected capability and whether or when it publishes output
   DataSet(s). An optional one-line description may follow.
2. **Before the setup cell**: `### Setup`.
3. **Before the manifest init cell**: `### Initialize Manifest`.
4. **Before each step's code cell**: `### Step K: <op_name>` for K = 1..N.
5. **Before the finalize cell** (always emitted): `### Finalize`.
6. **Before the Hub registration cell** (only when the spec sets `hub_arn`): `### Register with SageMaker Hub`.

Markdown cells use `"cell_type": "markdown"`, no `execution_count`, no `outputs`, and `"metadata": {}` (the `metadata.run` integer tag is for code cells only — see `notebook_run_lifecycle.md`).

After all step cells, append the **finalize cell** (`finalize(writer, final_path=OUTPUT_PATH, last_step_output=step_N_output)`) and, if the spec contains `hub_arn`, the **Hub registration cell**.

When **appending** to an existing notebook, all new cells are added **after** the last existing cell. Prior cells are **not** read, modified, or rearranged — they may be older or generated under different fusion rules; they remain as they are.

### 6. Validate the notebook JSON

Before writing the `.ipynb`, validate the JSON structure per `notebook_structure.md` § "Notebook JSON Writing Guide" → "Validation checklist":

- Each cell has `cell_type`, `execution_count`, `metadata`, `outputs`, `source` (code) or `cell_type`, `metadata`, `source` (markdown).
- `source` arrays have one string per line, each ending in `\n` (last line may omit `\n`).
- Quotes inside source strings escaped as `\"`.
- No trailing commas.
- 2-space indentation.
- Wrapper has `cells`, `metadata`, `nbformat: 4`, `nbformat_minor: 4`.
- Every code cell in this run has `"metadata": {"run": NNN}` with the integer run number.

Use a standard file-writing or notebook-capable tool.

### 7. Sample-test local-lane cells

For a **local-lane notebook only**, run a small sample through the generated
logic before handoff to confirm it executes cleanly. The agent does NOT run the
full transformation — only a 5–20 record sample. Skip this step for API-lane
notebooks; their cells submit service jobs rather than local sample logic.

Two acceptable approaches:

1. **In-namespace evaluation.** Extract the per-step cell bodies (the inline transform function + `run_record_transform` / `dedup_dataset` / `split_dataset` call), evaluate them in a temp `dict` namespace where `INPUT_PATH` points at a 5–20 record subset of the real input and `RUN_DIR` is `/tmp/sample_run_NNN/`. Confirm each step's `stats` dict comes back with non-zero `total` and a sensible `kept` count.
2. **Subprocess on a temp script.** Concatenate the cell bodies into a temporary `/tmp/sample_run_NNN.py` and run it with `python3`. Same expectations as above.

In **both** approaches the agent must NOT write into `<project-dir>/scripts/run_NNN/`. Those per-run directories are reserved for script-mode delivery; the notebook flow leaves them empty.

If a step fails, fix the inline transform function in the corresponding code cell, re-write the notebook, and re-run the sample. Report the failure and the fix in the Step 8 handover rather than hiding the broken intermediate state.

If no sample data is accessible (e.g. credentials not yet configured), present the notebook for review without sample output and call this out explicitly.

### 8. Hand the notebook over to the user

Tell the user:

- Where the notebook is: `<project-dir>/notebooks/<project-name>.ipynb`
- Which run was just appended/created: `## Dataset Transformation (Run N)`
- That the agent will NOT execute the full transformation — the user runs the cells themselves.

For a **local-lane** notebook, also state that the run section is idempotent
and provide the expected manifest path:
`<project-dir>/manifests/transformation_manifest_run_NNN.json`.

For an **API-lane** notebook, instead state that executing or re-executing a
submission cell can incur charges and create another job or DataSet version.
There is no local manifest; the service job ARN and capability-specific
artifacts are the run record. For CodeGen Job 1, remind the user that it
produces only generated source and a review sample, then stops before Job 2.

Deliver the notebook and report that it's ready for the user to review and run; the agent's delivery turn ends here — it does not script mid-notebook pauses.

### 9. Verify after the user runs the notebook (local lane)

Once the user confirms they've executed the notebook end-to-end:

1. Read `<project-dir>/manifests/transformation_manifest_run_NNN.json` and confirm `status` is `"completed"` and the number of `operations[]` entries matches the operation count for this run.
2. Read the field names of the final output (`final_output` in the manifest, which may be a string or a list for split-final runs). Offer to show 1–2 records; show them only if the user says yes (see `../overview.md` → "Showing records").
3. Report total record counts (input, output) sourced from the manifest's `total_input_records` / `total_output_records`.
4. Reference the manifest path in the summary — the manifest is the canonical record, not the chat summary.
5. Ask the user to confirm the output looks correct.

### 9b. Verify after the user runs the notebook (API lane)

For API-lane runs, use the service job and capability-specific artifacts
instead of a local manifest. After the user runs the applicable cells:

1. Confirm the job ARN and status.
2. For CodeGen Job 1, confirm the generated-source and sample artifact URIs,
   then enforce the review stop. It intentionally has no output DataSet.
3. For a built-in, direct-BYOC, or approved CodeGen Job 2 run, confirm the
   output DataSet ARN(s) and `ds.source` after completion, then follow
   `api-execution-flow.md` § "Progress + actionable failure": resolve the
   `report.json` URI and run
   `aws s3api head-object --bucket <report-bucket> --key <report-key> --expected-bucket-owner <account-id> --region <region>`
   to check only its `ContentLength`. Report the URI and size without
   downloading, parsing, or adding notebook output statements.

## API Lane in Notebooks

For API-lane runs, follow Procedure Steps 1–6 and 8 above. Skip the local-only
sample execution in Step 7. Produce the API notebook like this:

1. Read `api-execution-flow.md`, select one capability path per operation/job,
   and read only each selected template: `../code_templates/api_transformation.py`
   for a built-in, `../code_templates/api_codegen_generate.py` for CodeGen Job
   1, `../code_templates/api_codegen_execute.py` for a separately approved Job
   2, or `../code_templates/byoc_transformer.py` plus
   `../code_templates/api_byoc.py` for direct BYOC. Also read
   `notebook_structure.md` § "API Execution Cell Mapping" and
   `api-operator-configs.md`.
2. Assemble the run section as ordered job groups, emitting each selected
   template's cells in order and substituting every `[PLACEHOLDER]` (see
   `notebook_structure.md` § "Placeholder Convention"). Feed a completed
   group's output DataSet ARN into the next dependent group. If Split precedes
   another operation, use only the named-output or fan-out decision recorded in
   the Step 4 chain summary; never select the first output implicitly. Never
   concatenate capability alternatives for one job. A
   CodeGen Job 1 notebook must let Cell 2 derive the actual schema at runtime
   and stop before submission when a complete bounded sample or metadata proves
   a request-required field absent. A truncated JSONL sample warns because a
   sparse field may appear later. Follow the artifact retrieval and review gate in
   `api-execution-flow.md`. Direct BYOC cannot contain CodeGen.
   For user-supplied direct BYOC, preserve the supplied transformer source and
   copy it to `<project-dir>/scripts/transformer.py` if it is not already at
   that canonical path, but first follow the existing-file comparison and
   conflict decision in `api-execution-flow.md`.
   For explicitly requested agent-authored direct BYOC, populate its `%%writefile
   [PROJECT_DIR]/scripts/transformer.py` cell with the reviewed customized
   transformer, write the identical reviewed source to that path during
   artifact generation only after the same conflict check, and remove the
   trailing `# NOTEBOOK_ONLY` template marker from the magic line in the
   emitted notebook. For script delivery,
   omit that notebook-only cell and write the same file directly to disk before
   running the submitter.
   CodeGen Job 1 is initially the last group in an open run. After the user
   approves its source and sample, append the Job 2 heading and cells to that
   same final run section with the same run metadata, without changing any
   existing cell or adding another run header or spec. Do not start a later run
   while this review is pending. If the user rejects the candidate and approves
   a strengthened-spec rerun, do not append Job 2. Close that review by
   rejection, preserve its run unchanged, and create a new append-only run with
   the revised spec and fresh Job 1. Never use the rejected Job 1 ARN for Job 2.
3. **WRITE the assembled notebook to `<project-dir>/notebooks/<project-name>.ipynb` with the file-write tool** (Step 6's JSON-writing rules and validation checklist apply), validate its structure without evaluating or subprocess-running API cell bodies, then hand it over per Step 8. CodeGen's review sample is produced only by its service-side Job 1; built-in and direct-BYOC notebooks have no agent-run sample step. The deliverable is the written `.ipynb` file on disk, not a plan or code pasted into chat. An API-lane turn that ends without the notebook written to disk has **not** completed the task.
4. If the API input is a local file, do not hand over the notebook until its
   exact input object exists. After writing the notebook, obtain the separate
   API pre-handoff approval described in `api-execution-flow.md`; Step 4
   artifact approval and lane confirmation do not authorize the upload. After
   approval, derive the bucket from the confirmed exact URI, run
   `aws s3api head-bucket --bucket <bucket> --expected-bucket-owner <account-id> --region <region>`,
   then run
   `aws s3 cp <staged-source> <confirmed-exact-s3-uri> --region <region>`.
   The owner-pinned preflight requires `s3:ListBucket`; high-level `s3 cp`
   provides multipart support but cannot carry `ExpectedBucketOwner`. The
   accepted source, or converted JSONL, streams to the confirmed exact object
   without being materialized in agent memory. Confirm the upload completed,
   then hand over the notebook. Do not add an input-upload cell: the notebook's
   registration and submission cells consume that object but do not create it.

Cell layout follows `api-execution-flow.md`; operator configs follow `api-operator-configs.md`. Step 0 of `overview.md` selects the route and Step 2 revalidates it; routing is not deferred to notebook-generation time.

## Local-Lane Worked End-to-End Example: 3-op Workflow (clean → dedup → schema_transform)

### Setup

The user has a fine-tuning workflow and asks for a notebook to clean, dedup, and convert their support-ticket dataset to Llama SFT format. The `directory-management` skill resolves:

- `<project-dir>` = `/workplace/me/projects/support-tickets-sft`
- `<project-name>` = `support-tickets-sft`

A spec was saved to `<project-dir>/specs/transformation_spec_run_001.json`
with input `data/raw/tickets.jsonl`, output
`data/transformed/final_output.jsonl`, and operations
`clean → dedup → schema_transform`.

No `hub_arn` is set, so the optional Hub registration cell is omitted.

### Procedure walk-through

For the full cell-by-cell content, see `notebook_structure.md` § "Local-Lane Worked Example".
For the on-disk state after the run, see `notebook_run_lifecycle.md` § "Local-Lane Worked Example".

Summary of generated cells for this 3-op workflow at run_001 (notebook-native layout):

- 1 markdown run header: `## Dataset Transformation (Run 1)` (operation chain `clean → dedup → schema_transform` rendered as a parameter bullet, not in the heading)
- 1 markdown `### Setup` heading + 1 setup cell
- 1 markdown `### Initialize Manifest` heading + 1 manifest init cell
- 3 (`### Step K: <op_name>` markdown heading + step code cell) pairs — one per step, with `record_step(...)` after each
- 1 markdown `### Finalize` heading + 1 finalize cell calling `finalize(writer, ...)`
- (optional) 1 markdown `### Register with SageMaker Hub` heading + 1 Hub registration cell when `hub_arn` is set
  The exact cell count varies with N, D, and H — see `notebook_structure.md` → "Cell-by-Cell Template (per run section)" for the canonical emission order.

### Adding a follow-up run (run_002)

Two days later, the user asks: "Filter out tickets shorter than 50 characters using the existing data."

- Step 1: same `<project-dir>`.
- Step 2: existing notebook has `## Dataset Transformation (Run 1)` (in markdown and in `metadata.run`); `data/transformed/run_001/` exists. → `N = 2`.
- Step 3: spec saved at `specs/transformation_spec_run_002.json`. Input is run 001's final output (`data/transformed/final_output.jsonl` or `data/transformed/run_001/step_3_schema_transform.jsonl` per the user's preference).
- Step 4: pre-flight finds the four project-local helper scripts already exist — no copy needed.
- Step 5: notebook exists. Action: append. Generate run 2 from
  `transformation.py` Cells 1, 2, and 5 plus `filter_fn.py` Cell 4. Append
  after the last existing cell. Run 1 cells remain unchanged.
- Steps 6–9 same.

The notebook now holds runs 001 and 002 as separate, independently-rerunnable
local-lane sections. See `notebook_run_lifecycle.md` →
"Local-Lane Worked Example" for the full cell layout of a 2-run notebook.
