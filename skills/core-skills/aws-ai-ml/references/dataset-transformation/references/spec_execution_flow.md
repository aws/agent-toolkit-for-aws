# Spec-Driven Transformation Operations

The following operations extend the Dataset Transformation skill with spec-driven data preparation capabilities. Each operation can be invoked as part of a Transformation Spec workflow or independently by the agent.

> **Delivery mode scope.** This file documents the **script delivery** flow — the agent executes each step end-to-end. For **notebook delivery** (where the agent generates inline-function code cells that the user runs), read `references/notebook_delivery.md` first; it pairs with `references/notebook_structure.md`, `references/notebook_run_lifecycle.md`, and `references/notebook_prebuilt_ops.md`. The two modes share the **same** project layout, the **same** intermediate outputs, and the **same** manifest contract — only the executor differs. The "Operation Type Inference", "LLM Operation Fusion", "Recommended Operation Ordering", and "Transformation Manifest" sections below apply to **both** delivery modes. The "Notebook Delivery Variant" section at the end of this file maps Phase A and Phase B onto notebook cells.

## Table of Contents

- [Transformation Spec](#transformation-spec) — Input schema for the workflow
- [Transformation Execution Flow](#transformation-execution-flow) — Two-phase workflow: Generation then Execution
- [Operation Type Inference](#operation-type-inference) — Keyword-based operation dispatch
- [Transformation Manifest](#transformation-manifest) — Output schema written after execution

## Transformation Spec

The Transformation Spec schema (fields: `input`, `output`, `hub_arn`, `operations`) is defined in `transformation_spec_schema.md`.

## Transformation Execution Flow

When executing a Transformation Spec, the workflow runs in two phases: **Generation** (produce all scripts upfront) then **Execution** (run them sequentially). This lets the user review the full plan before anything runs. The phases below describe the **script delivery** flow; the equivalent notebook-mode behavior is described in "Notebook Delivery Variant" at the end of this file (same manifest contract, same intermediate outputs, but transformation logic lives inline in code cells rather than in per-run script files).

### Phase A — Generation

1. **Parse the spec** — Read the Transformation Spec JSON containing `input`, `output`, `operations`, and optionally `hub_arn`. The `input` field supports S3 URIs, local file paths, or SageMaker Hub dataset ARNs. If an input is a Hub dataset ARN (matches `arn:aws:sagemaker:*:hub-content/*`), parse its Hub, DataSet name, and version, then run `aws sagemaker describe-hub-content --hub-name <hub-name> --hub-content-type DataSet --hub-content-name <dataset-name> --hub-content-version <version>` and use the returned S3 data location.
2. **Create run directory** — Create an isolated `run_NNN/` directory under `<project-dir>/data/transformed/` for intermediate outputs. Find the next available run number by scanning existing `run_*` directories and incrementing. Also create `<project-dir>/scripts/run_NNN/` for any generated scripts.
3. **Generate all scripts** — For each operation in the spec:
   a. Infer the operation type from the `instruction` field.
   b. For script-based operations (dedup, split): identify the pre-built script and determine parameters.
   c. For LLM-generated operations (ingest, merge, clean, filter, schema_transform): generate the Python function using reference code as guidance and save it to `<project-dir>/scripts/run_NNN/`.
4. **Dependency pre-check** — After all scripts are generated, verify the full set of required Python dependencies are importable in the agent's environment. Do a plain `import` check for everything used by pre-built scripts (e.g., `pandas`, `ftfy`) and LLM-generated code (by inspecting the imports of the generated files). If the spec contains a `hub_arn` field, additionally verify the V3 SageMaker SDK is available for dataset registration in Step 9 by importing `sagemaker.ai_registry.dataset.DataSet`.

   **The agent verifies imports but does NOT install missing packages.** If any dependency is missing, stop and present the user with the install commands to run manually, then wait for confirmation before re-verifying.

   For standard packages, show only the pinned install commands from `dependencies.md` (e.g., `pip install pandas==2.3.3 ftfy==6.3.1`). Never show an unpinned `pip install <package>`.

   For the V3 SageMaker SDK (when `hub_arn` is set), stop and route to the
   upstream `sdk-getting-started` workflow. Do not copy its implementation,
   artifact paths, or install commands into dataset transformation. After the
   user confirms that prerequisite completed, re-verify by importing
   `sagemaker.ai_registry.dataset.DataSet` before proceeding to Step 5.
5. **Present full execution plan** — Show the user: list of operations in order, which script each will use, any generated code for review, and confirmed dependencies.
6. **Wait for user confirmation** before proceeding to execution.

### Phase B — Execution

**Manifest discipline — read this before executing anything:**

- The manifest at `<project-dir>/manifests/transformation_manifest_run_NNN.json` is the **canonical, ground-truth record** of every transformation run. The user, downstream skills, and evaluation tooling all read this file — they do not read chat.
- Writing the manifest is **mandatory**, not optional. A run that produced files but no manifest is an **incomplete run**.
- A markdown summary table in chat does **NOT** replace the manifest. If you find yourself describing steps in prose without calling `writer.add_operation(...)` and `writer.write()`, stop and write the manifest first.
- The number of `writer.add_operation(...)` calls equals the number of distinct script invocations in this run. Fuse LLM-driven operations (see `LLM Operation Fusion` below) so the manifest entry count matches the actual scripts you ran.

Before starting execution, import `ManifestWriter` from
`scripts/manifest_writer.py` and construct it with `project_dir`, `run_number`,
`spec_input`, and `final_output`.

#### Step 7 — Execute operations sequentially

For each operation:

- Invoke the script with the appropriate input, chaining the previous step's output.
- Write the step output to the run directory (for example, `step_1_clean.jsonl`).
- Parse the script's `--json` output to get statistics.
- Record the operation with `writer.add_operation`, supplying `step`,
  `op_type`, the original `instruction`, input and output counts,
  `output_path`, and operation `parameters`.

**Record-count contract:** `input_records` counts **non-blank JSONL lines that
the parser attempted to load** — clean object parses plus malformed or
non-object values that are reported and dropped. `output_records` counts
records successfully emitted after the operation. These are NOT raw line
counts. Do NOT pass `wc -l` output here, because blank lines and trailing
whitespace would inflate the input count.

Source the counts from the script's `--json` stats whenever it reports them:

| Script                                          | `input_records` source                                     | `output_records` source                         |
| ----------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------- |
| LLM ingest (`ingest_fn.py`)                     | `stats["records"] + stats["malformed"]` (parsed + dropped) | `stats["records"]`                              |
| LLM clean (`clean_fn.py`)                       | `stats["total_records"]`                                   | `stats["transformed_records"]`                  |
| LLM filter (`filter_fn.py`)                     | `stats["total"]`                                           | `stats["kept"]`                                 |
| LLM merge (`merge_fn.py`)                       | `stats["total_records"]`                                   | `stats["transformed_records"]`                  |
| LLM schema transform (`schema_transform_fn.py`) | `stats["total_records"]`                                   | `stats["transformed_records"]`                  |
| `dedup_filter.py`                               | `stats["input_records"]` (processed + invalid UTF-8)       | `stats["output_records"]`                       |
| `dataset_split.py`                              | `stats["input_records"]` (valid + malformed attempted)     | `stats["output_records"]` (sum of split counts) |

If a script omits a record-level count, count non-blank lines directly
with Python file iteration. Count every non-blank line whether it parses
or not; never use `wc -l`.

**MANDATORY: Write the manifest to disk NOW, before presenting results or continuing.** This ensures progress is saved if the run crashes. Do NOT defer this to the end.

```python
writer.set_status("partial")
writer.write()
```

**Anti-pattern (do NOT do this):** running the script, presenting a chat summary table of step counts, and skipping `writer.add_operation(...)` / `writer.write()` because "the user can see what happened". The user cannot — the manifest is the record. If `writer.write()` has not been called, the step is unrecorded.

- Present before/after statistics to the user, then continue to the next operation — the whole operation plan was approved once at the Phase A review (step 6), so do **not** pause for a per-operation confirmation here.

**Repeat this sequence for every operation. The manifest must be written to disk after EACH operation, not just at the end.**

#### Step 8 — Copy final result

Copy the last step's output to the `output` destination. If the final operation
produced multiple files, the spec's `output` must be a directory/prefix ending
in `/`; for example, `split` writes
`split_train.jsonl`/`split_val.jsonl`/`split_test.jsonl` beneath that prefix.
Copy **all** of them and record `final_output` in the manifest as a **list** of
destination paths. If only a single file is produced, `final_output` is a
string.

#### Step 9 — Dataset registration (if `hub_arn` present)

After the final output is copied to the `output` destination, check if the spec contains a `hub_arn` field. If present, register the dataset using the SageMaker AI Registry.

When `final_output` is a single file, register that one file. When `final_output` is a list (e.g., from a `split` final step), register **each file separately** — one dataset entry per split, using the base dataset name suffixed by the split filename (`<dataset-name>-train`, `<dataset-name>-val`, and `<dataset-name>-test`). Truncate the base before adding the suffix so every name remains at most 63 characters. The resulting ARNs are recorded as a list in `hub_content_arn`, in the same order as `final_output`.

Before filling `[DATASET_NAME]`, normalize the project or use-case name to the
Hub content-name pattern `[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}`: replace spaces,
underscores, and other non-alphanumeric runs with `-`, strip leading/trailing
hyphens, truncate to 63 characters, then strip any trailing hyphen introduced
by truncation. Reject an empty result. For example, `legal_qa transformed`
becomes `legal-qa-transformed`.

For each file to register:

**Determine S3 URI for registration.** Dataset registration requires an S3 URI.

- If `output` is already an S3 URI (`s3://...`), use it directly.
- If `output` is a local path, upload the final result to S3 first using
  `transform_helpers.copy_file`.

For a local output, use:

```python
from transform_helpers import copy_file

s3_uri = f"s3://{bucket}/{key}"
# local→S3 upload via boto3; pass the spec's expected_bucket_owner (None = caller's account)
copy_file(local_path, s3_uri, spec.get("expected_bucket_owner"))
```

`copy_file` handles every direction (local↔S3, S3↔S3) through one call, so
script mode and notebook mode share the same upload code path.

**Register in SageMaker AI Registry.** Use the registration pattern in
`../code_templates/transformation.py` Cell 7: set telemetry attribution,
derive `hub_name` from the confirmed `hub_arn`, call
`DataSet.create(name=<dataset_name>, source=s3_uri, wait=False,
hub_name=<hub_name>, role=<hub_registration_role_arn>)`, and capture the
returned name and version. Poll the same explicit Hub with
`DataSet.get(name=..., version=..., hub_name=...)` until `Available` or
`ImportFailed`, and capture the returned ARN. Use the normalized
`[DATASET_NAME]` derived above. Outside SageMaker Studio, supply a
SageMaker-assumable registration role explicitly; the caller's IAM role is not
necessarily trusted by `sagemaker.amazonaws.com`.

**Handle the result.**

- **On success**:
  - Single-file runs: `writer.set_hub_content_arn(dataset_arn)`
  - Multi-file runs (split): collect ARNs in order and set the list: `writer.set_hub_content_arn([arn_train, arn_val, arn_test])`
- **On failure** (exception raised):
  Set the run status to `"failed"`, inform the user of the error, and stop. The transformed data files are still available on disk for manual retry. For multi-file runs, if any single file fails to register, do not set partial ARNs.

**Output the dataset ARN to the user.** If registration succeeded, present the
ARN so downstream skills (finetuning, evaluation) can reference it directly.

#### Step 10 — Finalize manifest

Set final status and write:

```python
writer.set_status("completed")
manifest_path = writer.write()
```

**Verify before presenting the summary:** the file at `<project-dir>/manifests/transformation_manifest_run_NNN.json` MUST exist on disk and contain `"status": "completed"` plus exactly one `operations[]` entry per script invocation in this run. If the file is missing or has fewer entries than scripts you executed, you skipped the Step 7 record or write action somewhere — go back and add the missing `writer.add_operation(...)` + `writer.write()` calls before continuing. Do NOT present the summary first and write the manifest "later".

#### Step 11 — Present run summary

Show input source and record count, each operation with input→output record counts and records removed, final output destination, Hub content ARN (if registered) or Hub registration error (if failed), and **the manifest file path**. The summary must reference the on-disk manifest, not stand in for it.

**Formatting rule**: Present the run summary as a key-value list, not a markdown table. Tables with empty headers render poorly in terminal environments.

## Operation Type Inference

Infer the operation type from the `instruction` field using these keyword patterns. For each type, read the listed reference when it's time to generate or run code.

| Keywords                                                                                                                  | Inferred Type           | Strategy                                                                    | Reference                                               |
| ------------------------------------------------------------------------------------------------------------------------- | ----------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------- |
| ingest, load, import, convert format, detect format                                                                       | `ingest`                | LLM-generated                                                               | `references/op_ingest.md`                               |
| transform, convert schema, reformat, map columns, to {OpenAI\|SFT\|DPO\|RLVR\|Nova} format                                | `schema_transform`      | LLM-generated                                                               | `references/op_schema_transform.md`                     |
| merge, combine, concatenate, join datasets                                                                                | `merge`                 | LLM-generated                                                               | `references/op_merge.md`                                |
| clean, normalize, fix text, whitespace, encoding                                                                          | `clean`                 | LLM-generated                                                               | `references/op_clean.md`                                |
| deduplicate, dedup, remove duplicates                                                                                     | `dedup`                 | Script (`scripts/dedup_filter.py`)                                          | `references/op_dedup.md`                                |
| filter, remove records, quality score, curate                                                                             | `filter`                | LLM-generated                                                               | `references/op_filter.md`                               |
| filter by language, keep only `<language>` rows, drop non-`<language>` rows                                               | (none — not a local op) | LanguageFilter on the API; follow the above-`API_CEILING` validation-gap path | `references/api-operator-configs.md` → "LanguageFilter" |
| redact PII, remove PII, mask personal data, drop rows with PII (not dropping a named column, which is `schema_transform`) | (none — not a local op) | PiiRedaction on the API; follow the above-`API_CEILING` validation-gap path   | `references/api-operator-configs.md` → "PiiRedaction"   |
| split, train/test, partition, divide                                                                                      | `split`                 | Script (`scripts/dataset_split.py`)                                         | `references/op_split.md`                                |

When keywords are ambiguous, use the full instruction context to disambiguate.

### LLM Operation Fusion

When two or more **LLM-generated** operations appear in the same workflow (any combination of `clean`, `filter`, plus `ingest`/`merge`/`schema_transform` when they touch the same data and produce the same record shape), the agent **MUST fuse them into ONE Python script** that applies all transformations in a single pass.

**LLM-driven operations include:** whitespace normalization, encoding fixes (ftfy), emoji removal, regex replacement, malformed-line removal, structural validation, content filtering, schema field remapping.

**One fused script means:**

- One Python file under `<project-dir>/scripts/run_NNN/` (e.g., `clean_fn.py`) that does everything in order.
- One subprocess invocation.
- One intermediate output file under `<project-dir>/data/transformed/run_NNN/` (e.g., `step_1_clean.jsonl`).
- **One** `writer.add_operation(...)` call covering the fused operations. The `instruction` field should describe all of them ("Remove malformed JSON, normalize whitespace"). The `op_type` is the dominant LLM type (typically `clean`).

**Why this matters:**

- It avoids redundant I/O — re-reading and re-writing the same dataset for every operation triples or quadruples runtime on large files.
- It keeps statistics aligned — combined "records removed" and "records modified" counts make sense in one pass.
- It matches the user's mental model: "clean my data" is one logical step, not five.

**What does NOT fuse:**

- **Built-in script ops** — `dedup` (`scripts/dedup_filter.py`) and `split` (`scripts/dataset_split.py`) — always run as their own subprocess, with their own manifest entry. Do not generate your own dedup or split logic inside the fused script. When the spec sets `expected_bucket_owner`, pass it as `--expected-bucket-owner <account-id>` to each of them (and to `build_training_set.py`).
- **Operations on different data** — if a `merge` step takes multiple inputs and produces a single combined dataset, that's its own pre-fusion step.

### Combined Instructions with Dedup

This is a special case of the fusion rule above. When an LLM-generated operation (clean, filter, etc.) is combined with `dedup` in the same instruction or workflow:

1. Fuse the LLM-driven portion (clean / filter / regex / etc.) into a single script → intermediate file (one manifest entry).
2. Execute `dedup_filter.py` on the intermediate output → final output (one manifest entry).
3. Total manifest entries = number of fused-LLM-script invocations + number of built-in-script invocations. For a typical "clean + dedup" workflow this is **2**, regardless of how many LLM-driven cleaning operations the user listed.

**Worked example — workflow with malformed-line removal + whitespace + encoding fix + dedup:**

The user's `operations` list has 4 instructions, but the manifest has **2 entries**:

| Manifest step | op_type | Script                                               | Covers                                                    |
| ------------- | ------- | ---------------------------------------------------- | --------------------------------------------------------- |
| 1             | `clean` | `scripts/run_001/clean_fn.py` (LLM-generated, fused) | Remove malformed JSON, normalize whitespace, fix encoding |
| 2             | `dedup` | `<skill-scripts-dir>/dedup_filter.py`                | Remove exact duplicates                                   |

Phase B invokes the fused clean script once, records one `clean` operation,
writes partial status, then invokes `dedup_filter.py` once, records one `dedup`
operation, and writes completed status. `<skill-scripts-dir>` is replaced with
the loaded skill's absolute `scripts/` path.

See `references/op_dedup.md` for full CLI usage and parameters.

### Recommended Operation Ordering (Fusion Rules)

When a workflow applies multiple cleaning/filtering operations to the same data, use this ordering. Each rule encodes a correctness or cost requirement that operations later in the list rely on.

1. **Structural validation** — Remove malformed JSON, empty required fields. Downstream parsing assumes valid JSON.
2. **Text normalization** (`clean`) — Fix encoding, whitespace, line endings. Downstream comparisons assume normalized text; otherwise records that should match (e.g., differing only in trailing whitespace, or differing only by mojibake variants) are treated as distinct.
3. **Deduplication** (`dedup`) — Run on cleaned text.
4. **Quality filtering** (`filter`) — Apply on clean, deduplicated data. Filtering before dedup wastes scoring on records about to be discarded; filtering before cleaning produces unstable scores driven by surface noise.

#### Conflict Policy

Before confirming any user-supplied operation order, the agent MUST:

1. Scan the user's order against the rules above.
2. If any rule is violated, HALT before spec confirmation.
3. Quote the violated rule verbatim.
4. Explain the concrete impact in terms of the user's data — sample a few records to ground the explanation, and describe what you found in counts and patterns without quoting record content (see `../overview.md` → "Showing records").
5. Recommend the correct order.
6. Ask for explicit confirmation: the user decides whether to proceed with the recommended order or keep their stated order.
7. Wait for explicit confirmation before executing either path.

If the user reorders independent operations that don't violate a rule, respect their order without pushback.

#### Worked Example

**User:** Execute the spec with input
`s3://my-bucket/support_tickets.jsonl`, output
`s3://my-bucket/clean.jsonl`, and operations `dedup → clean`.

**Agent:** Before I run this, I need to flag an ordering conflict with a documented fusion rule in `references/spec_execution_flow.md` → "Recommended Operation Ordering":

> **Text normalization** (`clean`) — Fix encoding, whitespace, line endings. Downstream comparisons assume normalized text; otherwise records that should match (e.g., differing only in trailing whitespace, or differing only by mojibake variants) are treated as distinct.

Concrete impact on your dataset: I sampled 5 records from `support_tickets.jsonl` and three of them are the same complaint that differ **only** in trailing whitespace and a mojibake variant of one character. With your requested order (`dedup` then `clean`):

- Step 1 `dedup` compares raw text. The three records hash to three different values because of the whitespace/encoding differences, so all three pass through.
- Step 2 `clean` then normalizes them into identical text — i.e., duplicates that survived dedup.

With the recommended order (`clean` then `dedup`), step 1 normalizes the text first, and step 2 then collapses the three records into one.

I'd recommend swapping the order to `["clean", "dedup"]`. Do you want me to proceed with the recommended order (`clean` → `dedup`), or keep your stated order (`dedup` → `clean`) despite the impact above?

⏸ Wait for explicit confirmation before executing either path.

---

The same template applies to every fusion-rule conflict (`clean` before `dedup`, `dedup` before `filter`, etc.): quote the rule, sample the user's data to explain the concrete impact, recommend the corrected order, ask for confirmation.

## Transformation Manifest

After execution, write
`<project-dir>/manifests/transformation_manifest_run_NNN.json`. The schema is
implemented by `scripts/manifest_writer.py` and includes spec inputs, final
outputs, totals, run directory, optional Hub ARN, status, and one operation
entry per invocation.

When the final operation produces multiple outputs, `final_output` and
`hub_content_arn` are positionally aligned lists of the same length.

Key fields:

- `spec_input`, `final_output`, `hub_content_arn` — each is a **string or list of strings**. Use a list when the source or sink comprises multiple files.
- `status` — `completed` | `partial` | `failed`.
- Per-operation `input_records` / `output_records` / `records_removed` are recorded for every step.

**Input record counts mean attempted non-blank JSONL lines, not raw lines.**
Blank lines are excluded; invalid-UTF-8, malformed, or non-object values that
the parser attempted to load are included. Output record counts include only
records successfully emitted. Local files and S3 objects use the same strict
per-line UTF-8 decoding, so an invalid byte is counted and skipped rather than
replaced. Do not populate either field from `wc -l`. See the Step 7 record
action above for the per-script source of truth and a fallback `count_records()`
helper.

## Notebook Delivery Variant

When the workflow's delivery choice is **notebook** (see `overview.md` →
Workflow step 3), Phases A and B above are not executed by the agent
end-to-end. Instead, they are mapped onto cells in the singular project
notebook at `<project-dir>/notebooks/<project-name>.ipynb` that the **user**
runs.

The on-disk artifacts differ from script mode in one key way:
notebook-native runs do not create `scripts/run_NNN/<op>_fn.py` files.
Transformation logic comes from operation-template cells. Intermediate outputs
and the manifest are identical to script mode.

### Phase A in notebook mode — operation-template cells

In script mode the agent writes per-op files under
`<project-dir>/scripts/run_NNN/` and invokes them via subprocess. In notebook
mode the agent copies Cell 4 from the matching operation template, or the
dedup/split cells from `transformation.py`. There is no `%%writefile`,
subprocess call, or per-run script file.

Pre-built ops (`dedup`, `split`) call their functions directly (imported in the Setup cell from project-local copies). Fusion of LLM operations (per "LLM Operation Fusion" above) is mirrored exactly: one fused step cell with a single inline function that applies all fused operations in one pass, one `record_step(writer, ...)` call — same manifest entry count as script mode.

The Phase A user-confirmation step (step 6 above) is replaced by the notebook review handoff: the agent presents the generated notebook for the user to read before running any cell. See `references/notebook_delivery.md` step 8.

### Phase B in notebook mode — execution as cells the user runs

In notebook delivery mode, Phase B is executed by the user running notebook cells; the agent only generates them. Manifest discipline is identical to script mode — each step cell calls `record_step(writer, ...)` which persists the manifest with `status='partial'` after every step. See `notebook_delivery.md` and `notebook_structure.md`.

### Directory layout — differences from script mode

For the full project layout, see `project_layout.md`. Key differences in notebook mode:

- `<project-dir>/scripts/run_NNN/` directories are **not created** — transformation logic lives inline in notebook cells.
- `<project-dir>/scripts/` hosts only the pre-built project-local helper copies (listed in `project_layout.md`), not per-run generated scripts.
- `<project-dir>/notebooks/<project-name>.ipynb` is the singular project notebook (notebook mode only).

### Cross-references

- `references/notebook_delivery.md` — End-to-end procedure for generating and appending notebook runs (the notebook-mode counterpart to this file).
- `references/notebook_structure.md` — Cell-by-cell layout for a single run section.
- `references/notebook_run_lifecycle.md` — Run numbering, append-only semantics, idempotency guarantees.
- `references/notebook_prebuilt_ops.md` — How `dedup` / `split` / `ManifestWriter` are integrated into notebooks.
