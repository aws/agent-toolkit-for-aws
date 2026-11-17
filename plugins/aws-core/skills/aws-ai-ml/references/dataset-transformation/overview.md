# Dataset Transformation Agent

Generates and executes spec-driven data preparation workflows (ingest, schema transform, clean, filter, text quality filter, language filter, PII redaction, merge, split, dedup) over datasets destined for SageMaker training or evaluation.

## When to Use

- User needs code for transforming datasets for SageMaker model training or evaluation.
- A dataset requires processing, cleaning, or formatting before training or evaluation.
- A Transformation Spec JSON is provided by an upstream skill (planning, dataset-quality).
- Workflow includes a review step where the user confirms generated code before execution.

## Mandatory Route Dispatch

For any request to run, set up, or prepare to run a transformation, the first
action is to read `references/routing-and-guardrails.md`. If the user has not
already chosen the local lane or API lane, stop before any implementation work.
Below `API_CEILING`, the first reply must contain the selected/default route,
the recommendation and reason, and exactly one lane-confirmation question.
Above `API_CEILING`, disclose that no whole-file path is validated by this
workflow and recommend sharding or sampling. Never offer a whole-file local
run; a managed API run may be offered only as clearly labeled best effort with
explicit confirmation. The routing reply is a hard stop and must contain only
those required routing details. Before
that answer, the routing reference permits only a metadata-only size probe; do not
inspect data content, build a spec, or write, show, test, or run transformation
code or commands. If the user already chose a lane below the ceiling, reuse
that choice without asking again and continue with that lane.

For `LanguageFilter` and `PiiRedaction`, also read
`references/api-operator-configs.md` before the first reply. This is mandatory
for route-only, show-only, and Data Quality hand-off requests. They always use
the API lane and must
never be replaced with local language detection, regular expressions, NER, or
other local substitutes. After the lane is confirmed,
`references/api-execution-flow.md` owns API capability selection. For every split request,
including a proposal or show-only artifact, read `references/op_split.md` before
responding.

## Principles

1. **Advance one decision or collect one small group of related inputs per turn, then pause for confirmation.** Each response moves exactly one step forward, ends with a question, and waits for the user before continuing. Group inputs that jointly define one artifact or decision (such as a spec's input, operations, and output); do not combine unrelated questions, skip ahead, or narrate what you just did.
2. **Don't read files until you need them.** Only read reference files when you've reached the step that requires them and the user has confirmed the direction. Never read ahead.
3. **Default output format is JSONL** unless the user explicitly requests another.
4. **Schema transform is an operation, not a separate workflow.** It composes with other operations in a transformation workflow like any other op.
5. **Only transform existing data — never invent unavailable content.** A
   user-requested field may be computed solely from values already present in
   each record. If a required field's value cannot be derived from the source,
   inform the user that the data is insufficient; do not fabricate it.
6. **Transformation Runs.** Every transformation request — including single-op requests like "normalize whitespace", "remove duplicates", "fix encoding", or "drop malformed JSON lines" — is a recorded transformation run, never an unrecorded one-off. There is no shortcut that skips the spec or the run record because a request "sounds trivial." The local lane records ordered `operations` plus run status through `scripts/manifest_writer.py`; the API lane records the `job_arn` plus capability-specific service artifacts and, when produced, output DataSets. See the local and API execution references.

## Prerequisites

Local execution (script and notebook) does not require SageMaker SDK setup;
operation-specific Python dependencies are verified during pre-flight. The
**API lane** additionally requires:

- A dataset registered as a DataSet (`DatasetArn`). Raw `s3://` input is registered at runtime as part of taking the API lane — not a manual prerequisite (see `references/api-execution-flow.md`).
- An S3 bucket for output.
- An IAM role ARN with a SageMaker trust relationship, or a configured `SageMakerConfig` providing one.
- An AWS Region where the DataTransformation API is available. Resolve this through `sdk-getting-started` and the live SDK rather than treating a hardcoded Region list as authoritative.
- The SageMaker SDK (`DataPreparer`) installed via `sdk-getting-started` before this workflow runs.

### Python and model dependencies

- `pandas` is required by local ingest and filter templates. The SageMaker SDK
  environment normally supplies it, but local execution still verifies the
  import and asks the user to install it when absent.
- `ftfy` is required for the local clean template's Unicode-repair behavior.
  It is not supplied by the SageMaker SDK.
- `sentence-transformers` and `scikit-learn` are optional dependencies for the
  local cluster-aware split. They are not supplied by the SageMaker SDK. First
  use may download `sentence-transformers/all-MiniLM-L6-v2` from
  `huggingface.co`; disclose that network access before execution and offer the
  label-only strategy when it is not acceptable.
- `pyarrow` is required by CodeGen Job 1 for Parquet schema inspection. It is
  also optional for Parquet inputs in the iterative SDG training-set resolver,
  where pandas is the fallback. It is not supplied by the SageMaker SDK.
- `boto3` is a dependency of the SageMaker SDK rather than an extra package
  introduced by this capability. CodeGen Job 1 uses the session S3 client for
  its bounded schema read; other generated API templates use PySDK S3 helpers.
  The shared local runtime imports `boto3` only when an S3 URI is used, so
  local-only execution does not require the SageMaker SDK. It retains `boto3`
  for streaming reads, object existence checks, and managed S3-to-S3 copies.
  Upload and download operations overlap with PySDK helpers but remain here to
  avoid introducing a SageMaker SDK dependency into local execution.

Verify imports before execution and do not install packages silently. Any
required AppSec approval for third-party packages or external model downloads
must be recorded before enabling them in a restricted runtime.

## Showing records

These rules apply to every operation, on the local lane and the API lane, in
script and notebook delivery. Datasets hold the user's own rows, which can
include personal data. Operation outputs, previews, CodeGen samples, job
outputs, `report.json` (including `row_outcomes`), job logs, and failure
messages can all contain or echo them.

- By default, report only counts, field names, file paths, and S3 URIs. Do not
  print or quote record content, even when a tool or job response contains it.
- Show record text only when the user asks to see records, and then at most
  2–3, each value truncated. Say once that the output holds the user's
  original rows.
- When an operation has a sample or preview option, it must report counts by
  default and include records only when explicitly requested.
- Never write record content into specs, scripts, notebooks, or manifests;
  they are saved artifacts. Never write credentials or tokens into them
  either.

## Integration Dependencies

These capabilities participate in the transformation workflow:

- **Upstream:** `planning` supplies sequencing and artifact contracts; `directory-management` supplies the project directory; `sdk-getting-started` supplies API-lane SDK, Region, role, and endpoint setup; `human-in-the-loop` can supply reviewed corrections to apply.
- **Downstream:** `auto-labeling`, `dataset-quality`, and `synthetic-dataset-generation` consume transformed datasets, manifests, split outputs, or the shared cluster splitter.

## Transformation Spec

Every run is driven by a Transformation Spec — a JSON document with `input`,
`output`, an ordered list of natural-language `operations`, and optional
local-lane `hub_arn`. For the full spec schema, see
`references/transformation_spec_schema.md`.

When the transformation is for **model training**, resolve the target format using the reference file `../dataset-quality/references/strategy_data_requirements.md`. The required format depends on both the **model type** (Open Weights like Llama/Qwen vs Nova) and the **finetuning technique** (SFT, DPO, RLVR, RLAIF) — make sure to match on both dimensions. If either the model type or technique is not yet known, ask the user before resolving the format.

### Evaluation Data Formats

When the transformation is for **model evaluation**, resolve the target format using this order:

1. Try fetching the live documentation at https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html to get the latest evaluation dataset schema definitions.
2. **If the fetch fails** (e.g., no internet access, VPC environment), fall back to the offline copy at `references/sagemaker_dataset_formats.md`. Inform the user that the format schemas are from an offline copy and may be outdated.

Use whichever source you successfully access as the source of truth for the target format. Do not rely on memorized schemas.

## Workflow

The workflow is the same regardless of whether a spec is provided upfront.

0. **Route execution intent before spec work.**

   Apply the mandatory route dispatch above before loading or building a
   Transformation Spec or inspecting dataset content. Its metadata-only size
   probe remains permitted.
   `references/routing-and-guardrails.md` is the single source of truth for the
   response shape, source/size recommendation, show-only exception, validation disclosure,
   warnings, cost, and reversibility. Include its fuzzy-dedup default or
   unresolved PII-actions note when applicable.

   **Spec-authoring-only exception:** when the user asks only to create or
   design a Transformation Spec—not to run, set up, or generate executable
   artifacts—skip Step 0 and use Step 1.

   **Show-only artifact exception:** use the complete exception in
   `references/routing-and-guardrails.md`. A shown artifact never confirms its
   lane for a later run.

   **Iterative Synthetic Data Generation loop exception:** the calling plan
   must provide the execution lane. Treat that plan-selected lane as already
   confirmed and proceed without asking the user on each iteration. Still
   disclose an above-ceiling validation gap and enforce every lane-specific
   guardrail.

   ⏸ Wait for the user's lane confirmation.

1. **Load or build the spec.**

   **Iterative Synthetic Data Generation loop dispatch (check first after Step 0).**
   When the plan calls this capability for its benchmark split or combined
   seed+dev evaluation-set preparation, skip the spec-building dialogue and
   continue with the plan-confirmed lane. Read and apply
   `references/op_split_sdg_loop.md`; it owns the fixed split, verification,
   tagging, merge, and BYOC requirements.

   **Spec-authoring-only dispatch.** When the user asks
   only to create, build, or design a Transformation Spec—not to run it—stay in Step 1
   and follow `references/spec_creation_flow.md`. Collect the missing input, operations,
   and output together as one small related group (omit values already known). Do not
   enter Step 0 or ask for execution size or lane until the user asks to run the spec.

   **Split dispatch.** The mandatory route dispatch already requires
   `references/op_split.md` for every split request. A labeled dataset should
   normally use its stratified three-way train/eval/holdout proposal; do not
   answer from a bare random 80/20 default.

   For all other requests, proceed with the normal spec flow below.

   For this step, you need: input dataset path(s), output destination, and a list of operations — either as a pre-built Transformation Spec or as natural-language intent. If the user already provided a complete spec, summarize it and proceed — but still work through the steps in order. Each step has its own skip-if-already-known guard, so settled items fall through quickly.

   Users often don't know which operations exist. When a user describes a dataset or a plain-English goal, proactively surface what the skill can do — e.g. "For this dataset I can deduplicate (exact or near), split into train/val/test, convert schema to an SFT/DPO format, filter low-quality rows, or merge it with another dataset." Recommend a concrete transformation workflow from their goal rather than waiting for them to name an operation.

   - Spec provided → summarize its input, output, ordered operations, and
     local-lane Hub registration when present. For the API lane, summarize the
     selected capability's output-DataSet behavior instead. Then ask for
     confirmation. Let the host choose the presentation format.

     ⏸ Wait for user.

   - No spec → read `references/spec_creation_flow.md`, build one with the user, save to `<project-dir>/specs/transformation_spec_run_NNN.json` (where NNN is the next available run number).

   This is a transformation run — see Principles § "Transformation Runs".

2. **Check execution eligibility and revalidate the confirmed lane.**

   Step 0 must already have selected and confirmed the lane. If it did not,
   return there before content inspection, spec execution, or code generation.
   `references/routing-and-guardrails.md` remains authoritative; Step 2 only
   checks whether newly available metadata changes its recommendation.

   Determine source and file size from the confirmed spec and available
   metadata. The row count is not a routing threshold; use it only for the
   ≥10K-record estimate and output accounting.

   - For S3 or Hub inputs, use object metadata such as `ContentLength`. Do not
     stream, download, or parse the dataset client-side merely to count rows;
     use the completed job report's record counts.
   - For local inputs, use filesystem metadata for size. Parse a local CSV,
     Parquet, or other non-JSONL input for a pre-run row count only when it is at
     or below `LOCAL_CAP` and the count is needed. Otherwise use execution
     output/report counts.
   - Treat failed probes as non-blocking telemetry: report the error, preserve
     the route derived from the user's source and known size, and do not invent
     a copy or shell workaround.

   Reapply the routing reference's validation boundary, operator limits,
   warnings, cost/reversibility disclosures, background option, and local
   registration note. If the facts change the recommendation, ask the user to
   confirm the new lane and wait; otherwise continue with the existing
   confirmation.

   For the API lane, read `references/api-execution-flow.md` and
   `references/api-operator-configs.md`; those references own built-in,
   direct-BYOC, and two-job CodeGen selection. Before artifact generation,
   require the confirmed spec's `output` to be an `s3://` prefix. If a supplied
   API spec has `hub_arn`, do not silently ignore it: explain that full API jobs
   publish their output DataSet automatically while CodeGen Job 1 publishes
   none, then ask the user to remove the local-only field or select a different
   route. For the local lane, continue with `references/spec_execution_flow.md`.

3. **Choose delivery.**

   For this step, you need: a delivery preference (script vs notebook). If the user already specified one (e.g., "give me a notebook") or a calling skill (e.g. fine-tuning) requested a delivery mode, skip the question and proceed to step 4 with that choice.

   The skill supports script and notebook delivery on both lanes. On the local
   lane, script delivery writes per-run scripts under `scripts/run_NNN/`;
   notebook delivery keeps operation logic in notebook cells and reuses the
   committed helpers under `scripts/`. Both local delivery modes use
   `data/transformed/run_NNN/` and
   `manifests/transformation_manifest_run_NNN.json`. API delivery uses service
   job records instead of a local manifest.

   - **Script delivery** — on the local lane, read
     `references/spec_execution_flow.md`; on the API lane, read
     `references/api-execution-flow.md` and use its selected capability
     template. The agent executes the applicable flow; there are no user-run
     cells.
   - **Notebook delivery** — read `references/notebook_delivery.md` and
     `references/notebook_structure.md`. The agent assembles a singular project
     notebook (`notebooks/<project-name>.ipynb`) with append-only
     `## Dataset Transformation (Run N)` sections; the user runs the cells.
     Read `references/notebook_run_lifecycle.md` for shared append and run-number
     semantics; read the pre-built-helper reference only for the local lane.
     Default when the user explicitly asks for a notebook, when called from
     fine-tuning workflows that want a rerunnable artifact alongside training,
     or for exploratory iteration on the same dataset.

   Ask the user to choose direct script execution or a Jupyter notebook they
   can execute. Let the host choose the wording and presentation.

   ⏸ Wait for user.

4. **Confirm Configuration.**

   For this step, you need: a confirmed Transformation Spec, a chosen delivery
   mode, the project directory, the run number, and either the local-lane
   Hub-registration decision or the API capability's output-DataSet behavior.
   If all of these have already been confirmed in this session, skip directly
   to artifact generation.

   **Operation ordering validation (MANDATORY before confirmation):** For the
   local lane, check the spec's operation order against the "Recommended
   Operation Ordering" rules in `references/spec_execution_flow.md`. For the
   API lane, follow the one-operation-per-job and chaining rules in
   `references/api-execution-flow.md`. If a rule is violated, explain the
   concrete impact, recommend the corrected order, and ask the user whether to
   adopt it or retain their stated order. Do not silently change the workflow.

   Before generating any artifacts, summarize the resolved spec path, delivery
   mode, project directory, run number, and the lane-specific output behavior:
   local Hub-registration choice or API output-DataSet behavior. Then request
   explicit confirmation. Let the host choose the presentation format.

   Then ask the user to approve artifact generation or request changes. New run-numbered artifacts are reversible because they do not replace earlier files; handle direct-BYOC canonical-file collisions in Step 5. API-lane execution is a separate confirmation because it can incur charges and create AWS resources.

   This is the canonical artifact/configuration confirmation point. It does not
   replace the proposed-spec approval in
   `references/spec_creation_flow.md` Step 5.

   ⏸ Wait for user confirmation.

5. **Generate Artifact.**

   For this step, you need: a confirmed Transformation Spec, a confirmed delivery mode, and the project directory + run number from Step 4. If artifact generation and any requested execution have already completed, skip directly to Step 6. Otherwise, reuse any completed artifact without regenerating it and continue through the remaining approval and execution steps.

   **Before generating or executing anything, read the corresponding reference file(s) in full:**

   - Local script delivery → read `references/spec_execution_flow.md` in full.
   - API script delivery → read `references/api-execution-flow.md` and the
     selected capability references/templates it directs you to.
   - Notebook delivery → read `references/notebook_delivery.md` and
     `references/notebook_structure.md` in full, then read only the
     lane-specific references they direct you to.

   Do NOT write a Python script, call `python3`, run `subprocess`, or invoke any
   cleaning/transformation code until the applicable reference has been read.
   Its lane-specific workflow contract and step boundaries are not optional.
   Skipping this read is a contract violation. If you find yourself writing
   code without having read the reference, stop and read it first.

   **API script submission gate (HARD STOP):** Generate or resolve the API
   script artifact without executing its side-effecting calls. After
   substituting placeholders, write each selected service-job capability to
   `<project-dir>/scripts/api_<capability>_job_J_run_NNN.py` as specified in
   `references/api-execution-flow.md`. Before any staging upload,
   `DataSet.create(...)`, or `DataPreparer.transform(...)`,
   summarize the selected capability and configuration, input and output
   locations, new AWS resources or versions, possible charges, reversibility,
   and foreground/background choice. Ask the user to approve that exact
   submission and wait. Step 4 artifact approval and lane confirmation are not
   submission approval. For CodeGen, this gate authorizes Job 1 only; Job 2
   still requires the separate generated-code review approval. Notebook
   delivery does not use this agent-side service submission gate because the
   user runs its cells. A local input still requires the notebook pre-handoff
   approval and agent-side staging upload after artifact generation and before
   delivery; follow `references/notebook_delivery.md`.

   Then execute the flow:

   - Local script delivery → run the two-phase workflow (Generation, then
     Execution) per `spec_execution_flow.md`; write the local manifest.
   - API script delivery → execute the selected built-in, CodeGen, or
     direct-BYOC path per `api-execution-flow.md`; use service run records.
   - Notebook delivery → generate (or append) the run section per `notebook_delivery.md`. The agent does NOT execute the full workflow in this mode. It validates a small sample only for the local lane; API notebooks receive structural validation, and CodeGen Job 1 produces its service-side review sample when run.

   For API CodeGen script delivery, run Job 1 only and end the turn for review.
   For API CodeGen notebook delivery, emit only the Job 1 artifact and hand it
   over; the user runs its cells and then reviews the service-generated source
   and sample. See `references/api-execution-flow.md` § "CodeGen two-job path".
   For supplied transformer source, follow that reference's direct-BYOC path.

   This is a transformation run — see Principles § "Transformation Runs".

6. **Verify.**

   For a local-lane run, verify the final output and on-disk manifest per
   `references/spec_execution_flow.md` or `references/notebook_delivery.md`.
   For this step, you need the final output path and the on-disk manifest path.
   If verification has already been performed and confirmed for this run, skip
   it. Otherwise, confirm the manifest exists at
   `<project-dir>/manifests/transformation_manifest_run_NNN.json`, report the
   total record count and output field names, reference the manifest path, and
   ask the user to confirm the result. Offer to show 1–2 output records; show
   them only if the user says yes. The local manifest is the canonical run
   record; if it is missing, complete `references/spec_execution_flow.md`
   Phase B before continuing.

   For an API-lane run, use the capability-specific verification in
   `references/api-execution-flow.md`. CodeGen Job 1 records its job ARN,
   generated-source URI, and sample URI but has no output DataSet; full runs
   record the job ARN and output DataSet(s). API runs have no local manifest.

   ⏸ Wait for user.

## Target Format Resolution

Any operation that needs to know the concrete target schema (primarily `schema_transform`, but also format-aware cleaning or filtering) must resolve it through `references/target_format_resolution.md`. It covers training vs evaluation paths, live AWS docs lookup with a cached fallback, and custom-format handling.

Do not rely on memorized schemas.

## Project Layout

Both local-lane delivery modes use the canonical project layout under
`<project-dir>/` — `specs/`, `scripts/` (with per-run `run_NNN/` subdirs),
`data/raw/`, `data/transformed/run_NNN/`, `manifests/`, and (notebook mode
only) `notebooks/<project-name>.ipynb`. API script delivery writes its
submission artifact as `scripts/api_<capability>_job_J_run_NNN.py`; API runs still
use service records instead of local transformed-data directories or
manifests. Direct BYOC keeps its reviewed editable source at
`scripts/transformer.py`, and CodeGen uses permission-restricted transient
review copies under `review/<codegen-job-name>/`; neither replaces the service
run record.

For the canonical project layout, see `references/project_layout.md`.

## References

Top-level workflow:

- `references/transformation_spec_schema.md` — Full Transformation Spec schema (fields, types, semantics).
- `references/project_layout.md` — Canonical project layout across local and API lanes and both delivery modes.
- `references/dependencies.md` — Pinned versions and install commands for the third-party Python packages local execution uses.
- `references/spec_creation_flow.md` — Building a Transformation Spec interactively with the user.
- `references/spec_execution_flow.md` — Local-lane script delivery flow: workflow phases, manifest discipline, fusion rules, and operation ordering.
- `references/target_format_resolution.md` — Resolving training and evaluation target formats.
- `references/sagemaker_dataset_formats.md` — Offline copy of SageMaker evaluation dataset formats.

Notebook delivery:

- `references/notebook_delivery.md` — End-to-end procedure for generating and appending notebook runs.
- `references/notebook_structure.md` — Cell-by-cell layout for a single run section.
- `references/notebook_run_lifecycle.md` — Shared run numbering and append-only semantics, plus local-lane idempotency guarantees.
- `references/notebook_prebuilt_ops.md` — How `dedup`, `split`, and `ManifestWriter` are integrated into notebooks (project-local copies of skill scripts).

API lane (CreateJob DataTransformation):

- `references/routing-and-guardrails.md` — Local-lane/API-lane routing, the validated whole-file boundary, the size thresholds (`LOCAL_CAP`, `API_CEILING`), and their provenance.
- `references/api-execution-flow.md` — API-lane telemetry (required) and built-in operation / CodeGen / custom code (BYOC) execution via the `DataPreparer` pySDK.
- `references/api-operator-configs.md` — Per-operator API Config schemas generated from the live runtime schema, engine defaults, and the LanguageFilter and PiiRedaction policies and evidence.
- `references/operator-name-mapping.md` — Intent/synonym → API operator name mapping; the dedup/filter disambiguation dialogue.
- SDK prerequisites are documented inline in the `## Prerequisites` section above; SDK install, execution role, region, and S3 details live in the shared `../sdk-getting-started/` reference.
- `code_templates/api_transformation.py` — built-in-operator API template only.
- `code_templates/api_codegen_generate.py` — CodeGen Job 1: generate code and a sample with `AutoExecute=False`, then stop for review.
- `code_templates/api_codegen_execute.py` — CodeGen Job 2: execute only the explicitly approved generated artifact.
- `code_templates/byoc_transformer.py` — direct BYOC `transformer.py` service-contract skeleton for user/agent-authored code.
- `code_templates/api_byoc.py` — direct BYOC submitter for that authored and uploaded `transformer.py`; it never calls CodeGen.
  Read exactly the template(s) for the selected API capability path; do not concatenate
  the built-in, CodeGen, and direct-BYOC alternatives into one executable artifact.
- `code_templates/ingest_fn.py`, `code_templates/clean_fn.py`, `code_templates/filter_fn.py`, `code_templates/merge_fn.py`, `code_templates/schema_transform_fn.py` — the committed `# Cell`-formatted script-mode skeletons for the five LLM-driven local ops. Each op's reference points at its template; copy it unchanged except the regions marked `# --- EDIT: ... ---`.

Per-operation references (used by both delivery modes — same function bodies, CLI flags, and stats schemas):

- `references/op_ingest.md`, `references/op_clean.md`, `references/op_filter.md`, `references/op_dedup.md`, `references/op_split.md`, `references/op_merge.md`, `references/op_schema_transform.md`.

> **Writing transform scripts:** each LLM-driven op (`ingest`, `clean`, `filter`, `merge`, `schema_transform`) has its complete script-mode skeleton committed as the `# Cell`-formatted `code_templates/<op>_fn.py`. Its `op_*.md` reference points at that template: read it and copy it unchanged except the regions marked `# --- EDIT: ... ---`. The `# Cell N` markers are plain comments — the copied file still runs as a standalone `python3 <op>_fn.py` CLI script, and `test/template_structure/test_template_structure.py` validates the `# Cell` structure. Pre-built ops (`dedup`, `split`) have ready-made scripts under `scripts/` instead.

## Iterative Synthetic Data Generation Training-Set Resolution

Materialize the single dataset one iterative Synthetic Data Generation iteration trains on by running the committed script `scripts/build_training_set.py` — do **not** re-derive its workflow. The caller passes the already-decided `--mode` (`replace` vs `accumulate`); the script imports dataset-transformation utilities as libraries and defines its training-row validation primitives locally. Never invoke dependent skills interactively inside the unattended loop. Workflow stages and dedup defaults are documented in the script's module docstring.

```
python3 scripts/build_training_set.py <run_dir> --iteration N --mode replace|accumulate \
        [--include-iterations 1,3] [--max-samples 4000] [--s3 s3://bucket/prefix/]
```

Writes `<run_dir>/iter_{N}/train/training_set_iter_{N}.jsonl` plus its manifest. When `--s3 s3://bucket/prefix/` is passed it also uploads the result and prints the S3 URI to register with `DataSet.create(...)` as one iteration-scoped dataset; without `--s3` the output stays local and no URI is produced.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Transforming image, audio, or video datasets. The validated workflows here cover text-based JSONL, CSV, and Parquet datasets.

## Gotchas

- **Routing and lane-specific safeguards:** use `references/routing-and-guardrails.md`. For local-output registration and lineage, use `references/spec_execution_flow.md` Step 9.
- **LanguageFilter and PiiRedaction:** both require the API lane. Their field, policy, limit, preview, and evidence contracts live in `references/api-operator-configs.md`; use `references/operator-name-mapping.md` to distinguish PII-in-text redaction from a named-column change.
- **Dedup threshold tuning**: The default similarity threshold for deduplication is 0.7 (Jaccard similarity). Lower values = more aggressive dedup. If results seem too aggressive or too lenient, adjust the threshold in the operation instruction (e.g., "deduplicate with 0.85 threshold").
  > **Note:** The 0.7 default applies to both local-lane fuzzy dedup and the API-lane FuzzyDedup operator (`JaccardThreshold`). See `references/api-operator-configs.md` for the full operator config schema.
