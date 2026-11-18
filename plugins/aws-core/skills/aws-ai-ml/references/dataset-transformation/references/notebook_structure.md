# Dataset Transformation Notebook Structure

Canonical assembly map for one dataset-transformation run section in
`<project-dir>/notebooks/<project-name>.ipynb`.

The project uses one append-only notebook. Each run adds a
`## Dataset Transformation (Run N)` section without modifying earlier runs.
Read `notebook_delivery.md` for the generation procedure,
`notebook_run_lifecycle.md` for shared append and run-number semantics, and, for
the local lane, `notebook_prebuilt_ops.md` for project-local helper
bootstrapping.

## Template Sources

Executable notebook logic has one canonical home: `../code_templates/`.
Read the selected template and emit its `# Cell` sections in order. Do not
reconstruct or duplicate those cells in reference Markdown.

| Execution lane           | Template cells                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Local common flow        | `transformation.py`: Setup, manifest initialization, dedup, split, single-output finalize, split-output finalize, and Hub registration |
| Local `clean`            | `clean_fn.py` Cell 4                                                                                                                   |
| Local `filter`           | `filter_fn.py` Cell 4                                                                                                                  |
| Local `ingest`           | `ingest_fn.py` Cell 4                                                                                                                  |
| Local `merge`            | `merge_fn.py` Cell 4                                                                                                                   |
| Local `schema_transform` | `schema_transform_fn.py` Cell 4                                                                                                        |
| API built-in             | `api_transformation.py` Cells 0–7                                                                                                      |
| API CodeGen Job 1        | `api_codegen_generate.py` cells in order                                                                                               |
| API CodeGen Job 2        | `api_codegen_execute.py` cells in order                                                                                                |
| API direct BYOC          | `byoc_transformer.py` plus `api_byoc.py` cells as directed below                                                                       |

Cells 1–3 in each local operation template remain the script-delivery
implementation. Cell 4 is the notebook implementation of the same operation.
This keeps local script and notebook behavior in one operation-specific
template.

## Placeholder Convention

Substitute every placeholder before writing the notebook. Square-bracket
tokens are textual template tokens, not Python identifiers.

| Placeholder                                                     | Meaning                                         |
| --------------------------------------------------------------- | ----------------------------------------------- |
| `[RUN_NUMBER]`                                                  | Integer run number                              |
| `[STEP_NUMBER]`                                                 | One-based operation number                      |
| `[INPUT_LOCATION]`                                              | Spec input path or S3 URI                       |
| `[OUTPUT_LOCATION]`                                             | Spec output path or S3 URI                      |
| `[HUB_ARN_OR_NONE]`                                             | Quoted Hub ARN or `None`                        |
| `[EXPECTED_BUCKET_OWNER_OR_NONE]`                               | Quoted spec `expected_bucket_owner`, or `None` for the caller's own account |
| `[EXPECTED_BUCKET_OWNER]`                                       | Resolved 12-digit spec or caller account ID, without surrounding quotes |
| `[HUB_REGISTRATION_ROLE_ARN_OR_NONE]`                           | Quoted SageMaker-assumable role ARN for Hub registration, or `None` only when the environment supplies a valid default role |
| `[PREVIOUS_OUTPUT_OR_INPUT_PATH]`                               | `INPUT_PATH` or the previous step output        |
| `[LAST_STEP_OUTPUT]`                                            | Final intermediate output                       |
| `[ORIGINAL_INSTRUCTION]`                                        | Original spec instruction                       |
| `[INSTRUCTION_SUMMARY]`                                         | One-line operation summary                      |
| `[DATASET_NAME]`                                                | Hub dataset name matching `[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}` (maximum 63 characters), for example `legal-qa-transformed`; normalize spaces/underscores to `-`; used for CodeGen raw-S3 registration and job naming, and for direct-BYOC raw-S3 registration; empty for CodeGen Job 2 or direct-BYOC existing-ARN paths that derive their prefix from `[INPUT_DATASET_ARN]`. Built-in input names are supplied through `[API_INPUTS]` |
| `[CLEANING_SUMMARY]`                                            | Plain-language cleaning behavior                |
| `[FILTER_CRITERIA]`                                             | Filter predicate and summary                    |
| `[DETECTED_FORMAT]`                                             | Ingest format                                   |
| `[INPUT_FILES]`                                                 | Merge input-path list                           |
| `[TARGET_FORMAT_ID]`                                            | Resolved schema target                          |
| `[OUTPUT_COLUMNS]`                                              | Generated output-column list                    |
| `[DEDUP_MODE]`, `[DEDUP_THRESHOLD]`, `[DEDUP_FIELDS]`           | Dedup configuration                             |
| `[TRAIN_RATIO]`, `[VAL_RATIO]`, `[TEST_RATIO]`                  | Split ratios                                    |
| `[SPLIT_STRATEGY]`, `[STRATIFY_FIELD_OR_NONE]`, `[RANDOM_SEED]` | Split configuration                             |
| `[INPUT_S3_URI]`, `[OUTPUT_S3_URI]`                             | Exact CodeGen/direct-BYOC input S3 object and required output S3 prefix. The input is empty only for a direct-BYOC existing DataSet ARN; CodeGen Job 1 always uses its resolved exact backing object. Built-in inputs are supplied through `[API_INPUTS]` |
| `[API_INPUTS]`                                                  | Python list expression for ordered built-in inputs: one entry, or two for Merge; each dict sets either `DatasetArn` or an exact `S3Uri` plus `DataSetName` |
| `[INPUT_FORMAT]`                                                | Pre-detected API input format: `jsonl`, `csv`, `tsv`, or `parquet` |
| `[OPERATOR]`                                                    | Exact built-in wire-name content inserted inside the template's existing quotes |
| `[OPERATOR_CONFIG]`                                             | Python dict literal/expression using only the selected operator's keys and Python values from `api-operator-configs.md`; use that operator's documented shown/default values, not JSON `true` / `false` / `null` tokens |
| `[JOB_ARN]`                                                     | Background job ARN used for reattachment        |
| `[S3_URI_OF_SPEC]`                                              | Uploaded CodeGen specification                  |
| `[TRANSFORMATION_SPEC_TEXT]`                                    | Complete natural-language CodeGen specification serialized as a safe Python string expression with `repr(spec_text)` or equivalent |
| `[REQUIRED_INPUT_FIELDS]`                                       | Python list of str for spec-referenced input fields, e.g. `["prompt", "completion"]` |
| `[EXPECTED_OUTPUT_FIELDS]`                                      | Python list of str required on every sample record, e.g. `["prompt", "completion"]` |
| `[INPUT_DATASET_ARN]`                                           | Existing DataSet ARN; CodeGen Job 2 requires Job 1's ARN, direct BYOC leaves it empty only for raw-S3 registration, and built-ins use `[API_INPUTS]` |
| `[APPROVED_GENERATED_CODE_S3_URI]`                              | Reviewed CodeGen `transformer.py` URI           |
| `[USER_TRANSFORMATION_CODE_S3_URI]`                             | Direct-BYOC `transformer.py` URI                |
| `[PROJECT_DIR]`                                                 | Resolved project directory                      |
| `[TRANSFORMER_SOURCE]`                                          | Complete customized BYOC transformer            |

`[OUTPUT_S3_PATH]` is an obsolete alias. Normalize it to `[OUTPUT_S3_URI]`.
Only names listed above are template tokens. For example,
`spec_input=[INPUT_PATH]` in `transformation.py` is ordinary Python list
syntax around the `INPUT_PATH` variable, not an `[INPUT_PATH]` placeholder.

## Cell-by-Cell Template (per run section)

Emit cells in this order:

1. Run header Markdown with input, output, operation chain, target format, and
   lane-specific output behavior.
2. `### Setup` plus `transformation.py` Cell 1 for local execution, or the
   selected capability template's Cell 1 for API execution.
3. For local execution, `### Initialize Manifest` plus
   `transformation.py` Cell 2.
4. One step heading and selected operation-template cell per post-fusion
   operation. Use `transformation.py` Cell 3 for dedup and Cell 4 for split.
5. For local execution, `### Finalize` plus `transformation.py` Cell 5, or
   Cell 6 when split is final.
6. For local execution with `hub_arn`, `### Register with SageMaker Hub` plus
   `transformation.py` Cell 7.
7. For API execution, use the API mapping below instead of local manifest and
   finalize cells.

Before assembling a run that imports `sagemaker.*`, complete the shared
`sdk-getting-started` workflow and verify the required imports in the target
kernel. Dataset transformation does not emit an SDK install cell or copy SDK
artifacts; those are owned by the upstream dependency.

Every code cell has integer metadata `{"run": N}`. Markdown cells use empty
metadata.

### Run header

The first Markdown cell starts with `## Dataset Transformation (Run N)` and
then lists `Input`, `Output`, `Operations`, and `Target format`. A local-lane
header also lists `Hub registration`; an API-lane header instead lists the
selected capability and whether or when it publishes output DataSet(s)
(CodeGen Job 1 publishes none). Use an unpadded number in the heading and zero
padding in paths.

### Local setup and manifest

`transformation.py` Cell 1 owns the idempotent `chdir` guard, project-relative
paths, `sys.path.insert(0, "scripts")`, and helper imports. Do not install
packages in Setup and do not add another `chdir` later.

Cell 2 calls `init_manifest`, which immediately persists `status="partial"`.

### Local-lane step cell preconditions

Every local-lane operation step cell:

- follows `### Step K: <op>`;
- writes an intermediate result under `RUN_DIR`;
- calls `record_step(writer, ...)` exactly once;
- contains no `%%writefile`, `argparse`, `main()`, `subprocess.run`, package
  installation, or working-directory change.

LLM-driven operations use Cell 4 from their matching operation template.
Pre-built dedup and split use `transformation.py` Cells 3 and 4. Fuse compatible
LLM operations according to `spec_execution_flow.md`; never fuse dedup or split.

### Local finalize and Hub registration

Use `transformation.py` Cell 5 for a single output. When split is final, use
Cell 6 so source and destination lists remain positionally aligned.

Cell 7 registers every S3 destination in `writer.final_output`. For split-final
runs it uses the valid, length-bounded Hub names `<dataset-name>-train`,
`<dataset-name>-val`, and `<dataset-name>-test` so the splits remain separately
addressable. Outside SageMaker Studio, set
`HUB_REGISTRATION_ROLE_ARN` explicitly to a role trusted by
`sagemaker.amazonaws.com`; the caller role is not necessarily a valid
SageMaker execution role. The cell submits with `wait=False`, then polls the
same explicit Hub through `DataSet.get(..., hub_name=..., version=...)`; this
avoids switching to a separately derived default Hub during the SDK wait.
`finalize` owns the local/S3 copy; never add a second upload to the
registration cell.

## API Execution Cell Mapping

Read `api-execution-flow.md` and `api-operator-configs.md`, select exactly one
capability path per operation/job, and then read only each selected template:

- built-in → `../code_templates/api_transformation.py`;
- CodeGen Job 1 → `../code_templates/api_codegen_generate.py`;
- approved CodeGen Job 2 → `../code_templates/api_codegen_execute.py`;
- direct BYOC → `../code_templates/byoc_transformer.py` and
  `../code_templates/api_byoc.py`.

Never concatenate built-in, CodeGen, and direct-BYOC alternatives for the same
job. For a multi-step API workflow, emit ordered job groups, one template per
job, and pass each completed output DataSet ARN to the next group. Treat Split
as terminal unless the user selected one named output or approved a separate
downstream branch for every output; never assume `outputs[0]`. A dependent
group is not emitted or run while its predecessor remains in progress.

### Built-in operator

Emit `api_transformation.py` in cell order. Fill the exact operator Config from
`api-operator-configs.md`; keep the default except set it to False for
PiiRedaction (`WAIT = False`). A chained
operation uses the previous output DataSet ARN as its next input. Cell 7
finalizes the built-in job, including after a kernel restart where Cell 6
re-attached the saved job ARN.

### CodeGen Job 1 — generate and sample, then stop

Emit `api_codegen_generate.py` as a standalone artifact. Fill
`[TRANSFORMATION_SPEC_TEXT]` with the complete agreed request and populate
`[REQUIRED_INPUT_FIELDS]` from input fields named in that request and
`[EXPECTED_OUTPUT_FIELDS]` from outputs required on every record. The template
uses the pre-detected `[INPUT_FORMAT]` and an exact `[INPUT_S3_URI]` object to
derive the actual top-level fields at runtime with a bounded JSONL/CSV/TSV
sample or Parquet schema metadata, rejects proven field mismatches, warns when
a truncated JSONL sample cannot prove a sparse field absent, uploads the exact
visible text to `[S3_URI_OF_SPEC]`, submits with
`AutoExecute=False`, and validates the actual generated source and sample.
It defaults `WAIT = True`; for a requested background submission, set
`WAIT = False`, retain the printed input DataSet ARN and job ARN, then set
`JOB_ARN` to the job ARN and `WAIT = True` to attach and finish review without
registering another input version. The completed attachment recovers
`input_dataset_arn` from `JobConfigDocument.InputDataConfig`; carry that value
into CodeGen Job 2.
Follow the artifact retrieval and review gate in `api-execution-flow.md`. The
artifact contains no full-dataset execution cell, reads artifact URIs from
`DescribeJob.JobConfigDocument`, and does not expect an output DataSet from
this review-only job.

### CodeGen Job 2 — execute approved generated code

Follow the approval boundary in `api-execution-flow.md` before emitting
`api_codegen_execute.py`. Fill `[INPUT_DATASET_ARN]` with Job 1's retained or
recovered `input_dataset_arn` and
`[APPROVED_GENERATED_CODE_S3_URI]`, then set `USER_APPROVED = True`. Keep its
approval guard intact and do not append it to Job 1 before approval. After
approval, append a `### CodeGen Job 2 — Execute Approved Code` heading and the
Job 2 cells to the end of the still-final Job 1 run section. Preserve all
existing cells byte-for-byte, reuse that section's run number and code-cell
`metadata.run`, and do not add another `## Dataset Transformation` header or
Transformation Spec. Keep
`WAIT = False` for this long-running full-dataset run, surface the submitted job
ARN, and use its re-attachment cell to check or collect the result later.

### Direct BYOC — supplied or explicitly requested code

Follow the direct-BYOC source-selection rules in `api-execution-flow.md`. In
notebook mode, emit the directory-creation cell and the following
`%%writefile [PROJECT_DIR]/scripts/transformer.py` cell from `api_byoc.py`,
replacing `[TRANSFORMER_SOURCE]` with the complete reviewed transformer and
removing the trailing `# NOTEBOOK_ONLY` marker from the emitted magic line.
During artifact generation, also write the identical reviewed source to that
path; preserve or copy user-supplied source there if needed. First apply the
existing-file comparison and conflict decision from `api-execution-flow.md`;
never overwrite different user-owned contents without that decision. In script mode,
write the same file directly and omit that notebook-only cell. Then emit the
remaining direct-BYOC submitter cells with
`[USER_TRANSFORMATION_CODE_S3_URI]`. Direct BYOC contains no CodeGen step. Keep
`WAIT = False` for this long-running full-dataset run, surface the submitted job
ARN, and use its re-attachment cell to check or collect the result later.

Each capability template surfaces its job record. Full-dataset capabilities
also surface or retain output DataSet records; CodeGen Job 1 instead prints the
generated-source and sample artifact URIs and intentionally has no output
DataSet.

## Notebook JSON Writing Guide

Represent each source line as one string in the cell's `source` array. End each
line with `\n`, except optionally the last. Escape JSON characters, use
two-space indentation, omit trailing commas, and set `nbformat` and
`nbformat_minor` to `4`.

### Validation checklist

Before delivery:

- parse the completed file as JSON;
- confirm every cell has the fields required by its type;
- confirm every new code cell has integer `metadata.run`;
- confirm none of the documented placeholder names remain unresolved; preserve
  literal square-bracket values such as `[EMAIL]` in user instructions or
  transformer source;
- for a local-lane notebook, confirm operation-cell and manifest-entry counts
  match; API notebooks have no local manifest entries;
- confirm append mode preserved every prior cell byte-for-byte.

## Local-Lane Worked Example

A local `clean → dedup → schema_transform` run uses:

1. run header;
2. `transformation.py` Cells 1 and 2;
3. `clean_fn.py` Cell 4;
4. `transformation.py` Cell 3;
5. `schema_transform_fn.py` Cell 4;
6. `transformation.py` Cell 5;
7. optionally `transformation.py` Cell 7 after Finalize when `hub_arn` is set.

This mapping is the executable specification. The reference documents explain
decisions and parameters; the templates supply the code.
