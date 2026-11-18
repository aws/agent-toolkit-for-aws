# Notebook Run Lifecycle

This reference documents the **run-tracking model** for the singular project notebook at `<project-dir>/notebooks/<project-name>.ipynb`. The notebook accumulates runs over time as discrete, append-only sections — each delimited by a markdown header and tagged on every code cell.

The append-only section, run-number, header, and `metadata.run` conventions
apply to both lanes. Local paths, manifests, idempotency guarantees, and re-run
scenarios apply only to local-lane sections. Re-executing API submission cells
can incur charges and create another job or DataSet version; see
`notebook_delivery.md` for the API handoff contract.

Read this together with:

- `notebook_structure.md` — cell-by-cell template for a single run.
- `notebook_prebuilt_ops.md` — how dedup/split/manifest-writer scripts appear in run sections.
- `notebook_delivery.md` — the end-to-end procedure that produces and appends runs.

## Table of Contents

- [Why a Singular, Multi-Run Notebook](#why-a-singular-multi-run-notebook) — Rationale for one notebook per project
- [Run Numbering](#run-numbering) — How `NNN` is computed and sourced
- [The `## Dataset Transformation (Run N)` Header Convention](#the--dataset-transformation-run-n-header-convention) — Markdown header format
- [Cell Metadata Tag: `"run": N`](#cell-metadata-tag-run-n) — Per-cell run tagging
- [Append-Only Run Sections](#append-only-run-sections) — Immutability rules for prior runs
- [Local-Lane Idempotency Guarantees](#local-lane-idempotency-guarantees) — Re-running a local section safely
- [Local-Lane Re-Run Scenarios](#local-lane-re-run-scenarios) — Common local workflows and their handling
- [Local-Lane Worked Example](#local-lane-worked-example-run_001--run_002-in-one-notebook) — `run_001` + `run_002` walkthrough

## Why a Singular, Multi-Run Notebook

The skill keeps **one** notebook per project and accumulates runs as new sections rather than creating `<project-name>_v2.ipynb`, `<project-name>_run002.ipynb`, etc. This:

- For local-lane sections, mirrors the script flow's per-run isolation
  (`data/transformed/run_NNN/`,
  `manifests/transformation_manifest_run_NNN.json`) without creating per-run
  script directories.
- Keeps the user's full transformation history reviewable in a single artifact.
- Preserves every prior section without rewriting it.

There is **no max-runs limit** — a notebook may accumulate `## Dataset Transformation (Run 1)`, `## Dataset Transformation (Run 2)`, ... indefinitely.

## Run Numbering

Runs are numbered with a zero-padded 3-digit integer, starting at `001`
(`run_001`, `run_002`, `run_003`, and so on).

For the local lane, the same run number is used everywhere the run is
referenced on disk. API notebooks use the same number in the section header and
code-cell metadata but have no local run outputs or manifest:

| Artifact                     | Path                                                           |
| ---------------------------- | -------------------------------------------------------------- |
| Spec                         | `<project-dir>/specs/transformation_spec_run_NNN.json`         |
| Per-run scripts directory    | `<project-dir>/scripts/run_NNN/` (script mode only)            |
| API submission script        | `<project-dir>/scripts/api_<capability>_job_J_run_NNN.py`      |
| Per-run intermediate outputs | `<project-dir>/data/transformed/run_NNN/`                      |
| Manifest                     | `<project-dir>/manifests/transformation_manifest_run_NNN.json` |
| Notebook section header      | `## Dataset Transformation (Run N)`                            |
| Notebook code-cell tag       | `"metadata": {"run": NNN}`                                     |

### Computing the next run number

When the agent prepares a new run, it computes `NNN` as `max(existing) + 1` by
scanning six sources and taking the max across all of them, then adding 1:

1. Markdown cells in `<project-dir>/notebooks/<project-name>.ipynb` matching `## Dataset Transformation \(Run (\d+)\)` (regex) — e.g. `## Dataset Transformation (Run 1)`.
2. `metadata.run` values on code cells in the same notebook.
3. Subdirectories under `<project-dir>/scripts/` matching `run_\d{3}`.
4. Subdirectories under `<project-dir>/data/transformed/` matching `run_\d{3}`.
5. Files under `<project-dir>/specs/` matching
   `transformation_spec_run_(\d{3}).json`.
6. Files under `<project-dir>/scripts/` matching
   `api_[a-z0-9_]+_job_\d+_run_(\d{3}).py`.

If the notebook does not yet exist or no prior runs are found in any source, the next run is `1` (filenames still zero-pad to `run_001`).

**Cross-check rule:** If sources disagree (e.g. notebook shows runs up to 003 but `scripts/` only has `run_001`), the agent uses the highest number from any source as `max` so a new run never reuses an old number, then warns the user about the inconsistency and offers to investigate.

## The `## Dataset Transformation (Run N)` Header Convention

Every run begins with a **markdown cell** whose source starts with:

```
## Dataset Transformation (Run N)
```

The run number `N` is **integer, not zero-padded** — `(Run 1)`, `(Run 2)`, `(Run 27)` — to match human reading conventions. Filenames and on-disk artifacts (`scripts/run_001/`, `manifests/transformation_manifest_run_001.json`) still use the zero-padded `run_NNN` form — only the markdown header drops the padding.

The header is followed by bullets for input, output, operation chain, target
format, and lane-specific output behavior: local Hub registration or the API
capability and its output-DataSet behavior. `notebook_structure.md` defines the
canonical header fields.

Sub-headers (`###`) inside a run section are used for cell- and step-level titles (`### Setup`, `### Step 1: Clean`); they do not start a new run.

The header acts as both a visual delimiter (for the user reading the notebook) and a programmatic marker (for the agent re-opening the notebook to compute the next run number).

## Cell Metadata Tag: `"run": N`

In addition to the Markdown header, every code cell that belongs to a run
carries an integer `run` key in metadata, for example
`"metadata": {"run": 1}`.

Notes:

- The value is the **integer** run number, not the zero-padded string. (`1`, not `"001"` or `1.0`.)
- Markdown cells (including the run-section header) do **not** require the tag — the header text is the source of truth for them.
- Cells that exist outside any run section (e.g. a top-of-notebook intro cell) have no `run` key.

The tag is what lets the agent surgically re-attach to a specific run section when re-opening the notebook — it can list cells with `metadata.run == 2` to find every cell belonging to run 2 without parsing source text.

## Append-Only Run Sections

**New runs are added as new sections; prior sections are NEVER modified.**

When the agent appends a `## Dataset Transformation (Run 2)` section to a notebook that already contains `## Dataset Transformation (Run 1)`:

- All cells of the prior run are preserved verbatim — markdown header, config cell, step cells, finalize cell, and any optional cells (e.g. Hub registration).
- Run 2's cells are appended **after** the last cell of run 1.
- The agent does not re-order, delete, or rewrite any run-1 cell, even if newer
  fusion rules or op-type heuristics would generate it differently.

This append-only contract makes the notebook history safe to share with
teammates. It does not make API submission cells idempotent or safe to rerun.

A CodeGen Job 1 section remains the current open run while it waits at the
review gate. After approval, append only the CodeGen Job 2 heading and cells to
the end of that same final section, preserving every existing cell byte-for-byte
and retaining the same run number and code-cell `metadata.run`. Do not add a
second run header or spec. Do not start another run while a CodeGen review is
pending; if later run sections already follow it, stop and ask how the user
wants to resolve the interrupted continuation rather than inserting or
reordering cells. If the user rejects Job 1 and approves a strengthened-spec
rerun, close the pending review by rejection without appending Job 2. Preserve
that run unchanged and append a new run with the revised spec and fresh Job 1;
never carry the rejected Job 1 ARN into Job 2.

### Identifying existing runs on re-open

When the agent is asked to add a new run to an existing notebook, it MUST identify all prior runs first. See § "Computing the next run number" for the algorithm. The same procedure runs on every notebook re-open.

If sources disagree, see the **Cross-check rule** under "Computing the next run number" above.

## Local-Lane Idempotency Guarantees

Each local-lane run section is **self-contained and idempotent** — re-executing
all cells in that section produces the same on-disk state, with no corruption.

| Action                                                                       | What guarantees idempotency                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Re-running the Setup cell                                                    | The chdir guard is idempotent (checks basename, not level count). `os.makedirs(..., exist_ok=True)` is safe to repeat.                                                                                                                                                  |
| Re-running a step cell that calls `run_record_transform(...)`                | The output path is fixed (`data/transformed/run_NNN/step_K_<type>.jsonl`); the function overwrites that file.                                                                                                                                                           |
| Re-running a pre-built op cell (`dedup_dataset(...)` / `split_dataset(...)`) | Same fixed output path; the function overwrites the file.                                                                                                                                                                                                               |
| Re-running the ManifestWriter init cell                                      | `transform_helpers.init_manifest(...)` creates a new `ManifestWriter` and writes a `status='partial'` manifest. The previous `writer` Python object is discarded.                                                                                                       |
| Re-running a step cell that calls `record_step(writer, step=K, ...)`         | `ManifestWriter.write()` does **read-modify-write**: it loads the on-disk manifest and replaces the entry for step K with the newly computed statistics. Re-executing the same step refreshes the manifest without producing a duplicate entry.                         |
| Re-running the finalize cell (`finalize(writer, ...)`)                       | Same read-modify-write semantics; status is the only field that changes if the manifest already had `partial`.                                                                                                                                                          |
| Re-running the optional Hub registration cell                                | Idempotency depends on the SageMaker AI Registry behavior. In general this is **not** safe to re-run on its own — the user may end up with duplicate `DataSet` entries. The cell should be guarded (e.g. `if not writer.hub_content_arn:`) when re-runnability matters. |

If the existing manifest is invalid JSON or is not a JSON object,
`ManifestWriter.write()` stops and preserves the file unchanged. Report the
corrupt path for manual recovery; never silently replace it and lose prior run
history.

**Cross-run isolation:** Because each run's `RUN_NUM`, paths, and `writer` are scoped to its own cells, re-running run 001 after run 002 has completed only rewrites run 001's outputs and manifest. Run 002's outputs (`data/transformed/run_002/`) and manifest are untouched.

## Local-Lane Re-Run Scenarios

### Scenario 1 — User re-runs all cells (Restart Kernel & Run All)

Each run section restores its own state in order:

1. Run 001's Setup cell sets `RUN_NUM = 1`, chdir guard fires (idempotent), creates `data/transformed/run_001/`.
2. Run 001's Initialize Manifest cell creates a fresh `writer` with `status='partial'`.
3. Run 001's step cells re-execute inline transform functions and overwrite the same step JSONL outputs. Same input → same output (deterministic transforms). Each `record_step(writer, ...)` call persists the manifest via read-modify-write (step-deduped).
4. Run 001's finalize cell copies the last step output to `OUTPUT_PATH` and sets `status='completed'`.
5. Run 002's Setup cell sets `RUN_NUM = 2`; run 002 proceeds the same way.

Final on-disk state matches what the notebook produced originally. No corruption.

### Scenario 2 — User re-runs a single run section (e.g. cells in `## Dataset Transformation (Run 1)` only)

Works correctly. Each run section is self-contained:

- Its Setup cell re-establishes `RUN_NUM`, paths, and creates directories.
- Its Initialize Manifest cell re-creates the writer scoped to `run_001`.
- Its step cells touch only `data/transformed/run_001/` and `manifests/transformation_manifest_run_001.json`.

Run 002's on-disk state is **not affected** because none of run 001's cells reference run 002 paths.

### Scenario 3 — User re-runs a prior run section after later runs have run

Same as Scenario 2: only the prior run's per-run artifacts are rewritten. Later runs that consumed the prior run's final output as their input may now want to be re-run too, but this is the user's call — the agent does not auto-rerun later sections.

If the user needs the project's top-level `OUTPUT_PATH` to reflect a specific run's result, they re-run that run's finalize cell (which copies its last step output to `OUTPUT_PATH`).

## Local-Lane Worked Example: `run_001` + `run_002` in One Notebook

The notebook below has accumulated two runs. Run 001 was a 3-op workflow (clean → dedup → schema_transform); run 002 was a 1-op filter applied to run 001's output. Cells are listed top-to-bottom; metadata is shown for code cells. Markdown heading cells (e.g., `### Setup`, `### Step 1: clean`) are omitted for brevity — see `notebook_structure.md` for the full interleaved layout.

| Cell | Type     | `metadata.run` | Source (abridged)                                                                                             |
| ---- | -------- | -------------- | ------------------------------------------------------------------------------------------------------------- |
| 0    | markdown | —              | `## Dataset Transformation (Run 1)` + parameter bullets (input, output, operations)                           |
| 1    | markdown | —              | `### Setup`                                                                                                   |
| 2    | code     | `1`            | Setup: chdir guard, imports, `RUN_NUM = 1`, paths, `os.makedirs(...)`                                         |
| 3    | markdown | —              | `### Initialize Manifest`                                                                                     |
| 4    | code     | `1`            | `writer = init_manifest(...)`                                                                                 |
| 5    | markdown | —              | `### Step 1: clean`                                                                                           |
| 6    | code     | `1`            | `def clean_record(record): ...` + `run_record_transform(...)` + `record_step(writer, step=1, ...)`            |
| 7    | markdown | —              | `### Step 2: dedup`                                                                                           |
| 8    | code     | `1`            | `dedup_dataset(step_1_output, step_2_output, ...)` + `record_step(writer, step=2, ...)`                       |
| 9    | markdown | —              | `### Step 3: schema_transform`                                                                                |
| 10   | code     | `1`            | `def schema_transform_record(record): ...` + `run_record_transform(...)` + `record_step(writer, step=3, ...)` |
| 11   | markdown | —              | `### Finalize`                                                                                                |
| 12   | code     | `1`            | `finalize(writer, final_path=OUTPUT_PATH, last_step_output=step_3_output)`                                    |
| 13   | markdown | —              | `## Dataset Transformation (Run 2)` + parameter bullets                                                       |
| 14   | markdown | —              | `### Setup`                                                                                                   |
| 15   | code     | `2`            | Setup: chdir guard, imports, `RUN_NUM = 2`, paths (input is run 001's final output)                           |
| 16   | markdown | —              | `### Initialize Manifest`                                                                                     |
| 17   | code     | `2`            | `writer = init_manifest(...)`                                                                                 |
| 18   | markdown | —              | `### Step 1: filter`                                                                                          |
| 19   | code     | `2`            | `def filter_record(record): ...` + `run_record_transform(...)` + `record_step(writer, step=1, ...)`           |
| 20   | markdown | —              | `### Finalize`                                                                                                |
| 21   | code     | `2`            | `finalize(writer, final_path=OUTPUT_PATH, last_step_output=step_1_output)`                                    |

On disk, the two specs and manifests retain their run numbers,
`data/transformed/run_001/` contains the clean, dedup, and schema outputs,
`data/transformed/run_002/` contains the filter output, and the singular
notebook contains both sections. The four project-local helpers remain under
`scripts/`. See `project_layout.md` for the canonical path list.

When the agent next adds run 003, it appends cells 22+ after cell 21. Cells 0–21 are not touched.
