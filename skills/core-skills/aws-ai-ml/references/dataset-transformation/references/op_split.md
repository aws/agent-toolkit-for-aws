## Table of Contents

- [Split Operation (Script-Based)](#split-operation-script-based)
  - [How It Works](#how-it-works)
  - [CLI Usage](#cli-usage)
  - [Parameters](#parameters)
  - [Edge Cases and Fallbacks](#edge-cases-and-fallbacks)
  - [Output Statistics (JSON)](#output-statistics-json)
  - [Manifest Recording](#manifest-recording)
- [Shared Cluster Splitter](#shared-cluster-splitter)
- [Notebook Mode](#notebook-mode)
  - [Step cell template](#step-cell-template)
  - [Special handling: multi-file output in the finalize cell](#special-handling-multi-file-output-in-the-finalize-cell)
  - [Cross-references](#cross-references)

## Split Operation (Script-Based)

**When to use:** The instruction describes partitioning a dataset into train/validation/test sets.

**Strategy:** depends on the execution lane and the split type:

- **Local lane** (when Step 0 routing selects it — see `routing-and-guardrails.md`): the pre-built `scripts/dataset_split.py` handles **both** `random` and `stratified` — invoke it directly; do NOT generate custom splitting logic.
- **API lane:**
  - **`random`** → the built-in **`Split`** operator (`Method: random`): a single `transform(...)` call (see `api-execution-flow.md` → "Built-in operations").
  - **`stratified`** → the built-in **`Split`** operator with `Method: stratified` and `StratifyField: <field>` (see `api-operator-configs.md`). The operator's `Method` accepts `random`, `stratified`, and `cluster`. For a local, ad-hoc split run `dataset_split.py --strategy stratified --stratify-field <field>`. **Note — the iterative Synthetic Data Generation loop:** its seed/dev/test benchmark split uses this **same** stratification logic but runs via **BYOC (not CodeGen)** on the API lane; its fixed ratios, degrade ladder, ≥ 20-per-split floor, and stratified-not-random verification — plus the BYOC `transform_dataset(...)` authoring contract — live in `op_split_sdg_loop.md` (pointed to from the "Iterative Synthetic Data Generation loop — benchmark split" section below). Read that file before producing a loop benchmark split; do not re-derive those requirements here.

**Trigger phrases:** "split", "train/val/test", "train/test", "partition", "divide", "80/20", "stratify", or any instruction that describes dividing records into disjoint sets.

### Standalone split proposals

Read this file before proposing ratios or showing split code. When the user has
a labeled dataset and asks the agent to design a train/eval/holdout split,
propose a concrete three-way stratified split instead of asking the user to
supply the design. When the row count is not yet known, use **80/10/10** as the
provisional recommendation:

- 80% train preserves most examples for fitting;
- 10% val (evaluation) supports model and prompt iteration;
- 10% test (holdout) remains untouched for an unbiased final measurement.

Stratify on the stated label field so each partition preserves the class mix.
Explain both the ratio and strategy rationale, and say the ratios should be
revisited if a split would have too few examples per class. Proposal and
show-only-code requests do not authorize execution: show the correct local or
API artifact for the route, then keep waiting for approval to run it.

When the user asks for **train/eval/holdout**, preserve those names in the
proposal and in any API `Ratios` object:
`{"train": 0.8, "eval": 0.1, "holdout": 0.1}`. Do not silently rename eval to
only `val` or holdout to only `test`; if a downstream consumer requires
`val`/`test`, state that mapping explicitly.

### How It Works

Records are partitioned using Python's `random` module, seeded for reproducibility. Two strategies are supported:

| Strategy     | Description                                                     | Use Case                                                    |
| ------------ | --------------------------------------------------------------- | ----------------------------------------------------------- |
| `random`     | Uniform random sampling.                                        | Default — balanced classes or unlabeled data.               |
| `stratified` | Preserves class distribution across splits using a label field. | Labeled data where splits must match the overall class mix. |

Output files are written to the step subdirectory (`<run_dir>/step_N_split/`) using these filenames:

- `split_train.jsonl`
- `split_val.jsonl`
- `split_test.jsonl` (only when 3-way split)

These are intermediate filenames within the run directory. The final output location is controlled by the spec's `output` field — see `spec_execution_flow.md` for how split files are copied to the destination.

### CLI Usage

- Default 80/20 random:
  `python3 <skill-scripts-dir>/dataset_split.py input.jsonl --output-dir <run_dir>/step_N_split --json`
- Custom ratios: add `--ratios 0.9 0.1`.
- Stratified: add `--strategy stratified --stratify-field label`.
- Reproducible custom seed: add `--seed 123`.
- Preview without writing files: use `--preview --json`.

### Parameters

| Parameter          | Default                       | Description                                                                                                 |
| ------------------ | ----------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `--output-dir`     | (required unless `--preview`) | Directory to write split files.                                                                             |
| `--ratios`         | `0.8 0.2`                     | Split ratios. Two values → train/val only. Three values → train/val/test. Must sum to 1.0 and all positive. |
| `--strategy`       | `random`                      | `random` or `stratified`.                                                                                   |
| `--stratify-field` | —                             | Field name to stratify on. **Required** when `--strategy stratified`.                                       |
| `--seed`           | `42`                          | Random seed for reproducibility.                                                                            |
| `--preview`        | off                           | Report split statistics without writing files.                                                              |
| `--json`           | off                           | Emit statistics as JSON to stdout.                                                                          |

### Edge Cases and Fallbacks

- **Small dataset** — If `total < len(ratios)` (e.g., 2 records with a 3-way split), all records are placed in train and val/test are empty. Report this to the user.
- **Stratification fallback** — If any class in `--stratify-field` has fewer than 2 samples, the script falls back to random splitting for the entire dataset. The output still reports `"strategy": "stratified"` but includes `"stratification_fallback": true` to indicate the fallback occurred.
- **Empty input** — Empty output files are still written for each split, with `records: 0`.
- **Malformed or non-object JSONL lines** — Invalid JSON and valid JSON values
  that are not objects are skipped during load, reported on stderr, and
  included in `malformed` and `input_records`; they are not counted toward
  `total`, `output_records`, or any split. This includes lines that are not
  valid UTF-8; local files and S3 objects use the same strict per-line
  decoding.

## Iterative Synthetic Data Generation loop — benchmark split

**When this applies:** ONLY when the **iterative Synthetic Data Generation
training plan** dispatches the loop's initial `seed` / `dev` / `test` benchmark
split (the plan's data-preparation step). A normal, ad-hoc split request does
**not** read this — it still follows the lane routing above.

The loop's fixed ratios, the degrade-ladder mode selection, the ≥ 20-per-split
floor, and the ⚠️ stratified-not-random verification (all HARD GATES), plus the
BYOC `transform_dataset(...)` authoring contract, live in `op_split_sdg_loop.md`.
Read that file before producing a loop benchmark split.

## Iterative Synthetic Data Generation loop — prepare evaluation dataset (tag + system prompt + Verl + merge)

**When this applies:** ONLY when the loop prepares its evaluation dataset — tag
all three splits, insert the system prompt, reshape to the Verl eval format, and
produce the two merged files (seed + dev, and seed + dev + test). A normal split
request does **not** read this.

The full eval-set contract — the load-bearing `id` / `index` / `split` join-key
discipline, the BYOC `transform_dataset(...)` mechanism, and the
re-tag-on-recreate / fresh-path rule — lives in `op_split_sdg_loop.md`. Read that
file before preparing the loop's eval set.

### Output Statistics (JSON)

Example: `{"total":10000,"malformed":5,"input_records":10005,"output_records":10000,"strategy":"random","seed":42,"ratios":[0.8,0.2],"splits":{"train":{"records":8000},"val":{"records":2000}}}`.

For stratified splits, each split entry also includes a `class_distribution` map, and a top-level `class_distribution` reflects the overall dataset:

Stratified output also includes per-split and top-level
`class_distribution` maps.

### Manifest Recording

Because split produces multiple outputs, record the step directory rather than
a single file. `parameters` contains strategy, ratios, seed, and a map of split
names to record counts. The output count is the sum of all split counts.

## Shared Cluster Splitter

`scripts/cluster_split.py` is a **local** dev/val/test splitter owned by this reference and used by other skills: `auto-labeling` runs it in `references/full-loop.md` → "Step 1 - Split", and the iterative Synthetic Data Generation plan (`planning/references/iterative-sdg-training-plan.md`) uses it for the benchmark split. Invoke it by skill-root path: `<skill-root>/references/dataset-transformation/scripts/cluster_split.py`. It does **not** change this reference's `Split` routing above.

- **What it does:** embeds each row's text fields with `sentence-transformers/all-MiniLM-L6-v2`, KMeans-clusters the embeddings, then stratifies on `(cluster_id, <gt-field>)` so every partition sees the full spread of both semantic neighborhoods and labels. Numeric gold with more than 5 distinct values (`NUMERIC_GOLD_BINS`) is stratified by quantile bin instead of raw value when it is a score: `--gold-kind score`, or under the default `--gold-kind auto` fractional gold or integer gold in a field named with `score` or `rating` (`gt_score`). Integer gold in any other field (`gt_label`, `category`, `intent`, `class_id`) stays exact class strata, and with `auto` the script warns when the field name gave no hint; pass `--gold-kind class` or `--gold-kind score` to say which it is. Seeded, so it is reproducible. `test` is reserved for final measurement.
- **Key flags:** `--labeled <jsonl>` and `--out-dir <dir>` (required); `--gt-field` (default `gt_label` — rarely matches real data, always pass it); `--strategy cluster|label` (default `cluster`); `--gold-kind auto|class|score` (default `auto`; `class` keeps every gold value as its own stratum, `score` bins numeric gold); `--text-fields` (default `text,premise,hypothesis,dialogue,content`); `--dev-frac` / `--val-frac` (defaults `0.5` / `0.25`, `test` gets the rest); `--seed` (default `42`).
- **Dependencies, network access, and fallbacks:** the `cluster` strategy needs
  `sentence-transformers` + `scikit-learn`, which are optional and are not
  supplied by the SageMaker SDK; install only the pinned versions in
  `dependencies.md`. Before running it, tell the user that first
  use may download `sentence-transformers/all-MiniLM-L6-v2` from
  `huggingface.co` and confirm that outbound model download is acceptable. If
  the runtime requires an approved internal model source, use that instead of
  direct external download. If outbound access is unavailable or undesired,
  use `--strategy label`; this avoids the download but gives up
  semantic-cluster leakage protection.
  Without the optional packages the script falls back to label-only
  stratification, warns on stderr, and records `fallback_reason`; with fewer
  than 6 rows it uses label-only stratification directly. Label-only
  stratification fails loudly if `--gt-field` is absent from every row. When
  the gt field is free text (near-unique per row), it switches to a random split
  that honors the fractions and records `strategy: "random"`.
- **Output:** `dev.jsonl`, `val.jsonl`, `test.jsonl`, and `manifest.json` under `--out-dir`. The manifest records the output paths, fractions, and seed, plus an `info` block with the `strategy` actually used, `n_buckets`, and `fallback_reason` when it fell back. Check `info.strategy` and `info.n_buckets > 1` before trusting the split.
- **Lane selection:** this script is for the local lane. For an API-lane cluster split, use the `Split` operator with `Method=cluster` (see `api-operator-configs.md`). Never run this script through CodeGen/BYOC — the sandbox cannot load its ML dependencies.
- **Routing & fallback caveat:** routing follows the contract in `routing-and-guardrails.md` (same `LOCAL_CAP` / `API_CEILING` as every split and op) — apply the `API_CEILING` gate first; below it, source location determines the lane default and `LOCAL_CAP` informs the local recommendation. A **local** file at/under `LOCAL_CAP` is recommended for this local script when the user confirms local; an **S3/Hub** source or any user-confirmed API route uses the `Split` operator `Method=cluster` there. Above `API_CEILING`, refuse a whole-file local run and recommend sharding or sampling; a whole-file managed API run may proceed only as clearly labeled best effort after explicit confirmation. The one cluster-specific difference: API-lane `Method=cluster` does **not** reproduce this script's cluster→stratified fallback, so read the API job's report/manifest for the strategy that actually ran rather than assuming the fallback fired.

## Notebook Mode

### Cell preconditions

See `notebook_structure.md` → "Local-lane step cell preconditions" for the shared rules. This op uses the **direct function-call pattern** — `split_dataset` is imported in Cell 1's Setup and called directly in the step cell. The step cell heading is `### Step K: split`. The relevant path variables from Cell 1's Setup are `INPUT_PATH`, `OUTPUT_PATH`, `RUN_DIR`, plus a per-step `split_dir` derived from `RUN_DIR`.

Cell 1 import line:

```python
from dataset_split import split_dataset
```

`dataset_split.py` is a pre-built script the project owns at `<project-dir>/scripts/dataset_split.py` (copied from the skill on first use; see `notebook_prebuilt_ops.md` → "Bootstrap Procedure"). The notebook never regenerates it and never invokes it via `subprocess.run([...])`. There is no `%%writefile` cell.

> See `notebook_structure.md` § "Placeholder Convention" for `K` / `<prev>` substitution rules.
>
> **`final_output` as a list:** when `split` is the **final** step of a run, the finalize cell calls `finalize(writer, final_path=[...], last_step_output=[...])` with a **list** of destination paths (one per split file) instead of a single string. When `split` is **not** the final step, the standard single-file finalize is used. See "Special handling: multi-file output in the finalize cell" below.

### Step cell template

Use `../code_templates/transformation.py` Cell 4. It calls `split_dataset`,
records the output directory and per-split counts, and calls `record_step`
once. Fill the strategy, ratios, optional stratification field, seed, input,
step number, and original instruction.

`split_dataset` returns `{total, malformed, train_count, val_count, test_count, paths: {"train": ..., "val": ..., "test": ...}, input_records, output_records, ...}`. `total` and `output_records` count valid JSON-object records. `input_records` is `total + malformed`, so every invalid-UTF-8, malformed, or non-object non-blank line that was attempted and dropped remains visible. Split is record-preserving for valid JSON-object records: every valid record lands in exactly one split.

The `output_path` is the **directory** `step_{K}_split/`, not a single file — see the script flow's "Manifest Recording" section above for the contract.

### Special handling: multi-file output in the finalize cell

When `split` is the last operation, use
`../code_templates/transformation.py` Cell 6. It supplies positionally aligned
source and destination lists to `finalize`. The Transformation Spec's `output`
must be a directory/prefix ending in `/`; a file path such as
`s3://bucket/result.jsonl` is rejected rather than being treated as a
directory.

`finalize` accepts `str | list[str]` for both `final_path` and `last_step_output`. When both are lists they must be the same length; each `last_step_outputs[i]` is copied to `final_outputs[i]`, the writer's `final_output` is set to the destination list, status is set to `"completed"`, and the manifest is written. Passing a list signals to downstream consumers (Hub registration, manifest readers) that the final output is multi-destination.

When `split` is **not** the final op (e.g. follow-up `schema_transform` reads only the train split), use the standard single-file finalize and have the next step's code cell point at the specific split file it needs (e.g., `stats["paths"]["train"]`).

### Manifest fields recorded by `record_step`

Same as the script flow's "Manifest Recording" section above:

| Argument         | Source / value                                                                                                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `step`           | Step number K within this run                                                                                                                                                        |
| `op_type`        | `"split"`                                                                                                                                                                            |
| `instruction`    | Original instruction from the spec                                                                                                                                                   |
| `input_records`  | Extracted from `stats["input_records"]` (`stats["total"] + stats["malformed"]`)                                                                                                      |
| `output_records` | Extracted from `stats["output_records"]` (sum of valid records across the split files; equal to `stats["total"]`)                                                                    |
| `output_path`    | `f"{split_dir}/"` — directory, **not** a single file                                                                                                                                 |
| `parameters`     | `{"strategy", "ratios", "seed", "splits": {name: count}}`. Stratified runs additionally include the helper's `class_distribution` keys when those are present in the returned stats. |

### Cross-references

- `notebook_prebuilt_ops.md` — self-contained bootstrap procedure that copies `dataset_split.py` into the project's `scripts/` directory on first use, plus the canonical step-cell pattern (including stratified usage).
- `notebook_structure.md` — full cell-by-cell template, including the multi-file finalize variant referenced above.
- `notebook_run_lifecycle.md` — run numbering, append-only semantics, `metadata.run` tag, idempotency guarantees.
- `notebook_delivery.md` — end-to-end procedure that produces and appends a run section.
