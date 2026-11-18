## Iterative Synthetic Data Generation loop — benchmark split

**When this applies:** the split is requested by the **iterative Synthetic Data Generation training
plan** to create the loop's initial `seed` / `dev` / `test` benchmark splits
(the plan's data-preparation step). It does NOT change how a normal, ad-hoc
split request is handled — that still follows the lane routing in `op_split.md`
(and `routing-and-guardrails.md`).

**Split roles** (what each partition is for, so the sizing and the held-out
discipline make sense):

- **`seed`** — the `synthetic-dataset-generation` input and the inject source for the loop.
- **`dev`** — used for error analysis, generation selection, and the
  per-iteration termination decision.
- **`test`** — held out, **report-only**; never used to steer the loop.

**Execution lane:** produce a **stratified** split (never the default random
split). Follow the stratified lane routing documented in `op_split.md` and
`routing-and-guardrails.md`: on the **local** lane run `dataset_split.py --strategy stratified
--stratify-field <field>`; on the **API** lane the loop's split runs via the
**BYOC path** (the built-in `Split` operator does stratified, but not the loop's
fixed ratios, degrade ladder, ≥ 20-per-split floor, and stratified-not-random
verification): the local
agent **authors a script** — in the format BYOC expects, exposing
`transform_dataset(inputs: dict[str, str], output_dir: str) -> dict` — that
**takes inspiration from the co-located `scripts/dataset_split.py`**
`split_dataset(...)` logic (reuse its seeded shuffle, per-class partitioning,
and `class_distribution` reporting; do NOT re-derive stratification from
scratch) **and additionally bakes in everything this loop requires** so the one
script does the whole job: the fixed ratios, the degrade-ladder mode selection,
the ≥ 20-per-split floor, and the stratified-not-random verification described
below. `dataset_split.py` is the split **engine** only — it does not know the
loop's fixed ratios, has no row-count degrade ladder, and enforces no ≥ 20
floor — so the agent's BYOC script must add those on top rather than assume the
engine provides them. BYOC then runs that script on the API lane (see
`api-execution-flow.md` → "Direct BYOC path" for the entry-point contract and job
submission); reusing the same core split logic means the local and API lanes
partition identically. Follow the loop-specific
policy below exactly;

> treat every ⚠️ step below as a HARD GATE: if a check fails, **STOP and fix
> the input or the field, do not proceed with a bad split.** A random or
> under-floor split does not error on its own; the only thing standing between
> it and a corrupted run is you performing these checks.

### Fixed ratios and thresholds (do not ask the user for these)

The loop's split policy is fixed:

- **seed ≈ 20%**, **dev ≈ 30–40%** (use ~0.35), **test ≈ 40–50%** (use ~0.45).
- **≥ 20 examples in EVERY split** — a hard floor.
- Degrade-ladder row thresholds: **≥ 100 rows** → three-way; **≥ 40 rows** →
  two-way (seed + dev, no test); **< 40 rows** → shared (seed = dev).

### Step 1 — inspect a sample to choose the strategy

Read a sample (≈50 rows) of the input and count the total parseable rows.

- If a **discrete label field** is present on EVERY sampled row and has low
  cardinality (a real class label — `label`, `category`, `class`, `intent`,
  `answer`, `target` — not free text), split **stratified on that field**.
- If there is **no discrete label**, inspect the target values before choosing a
  splitter. For a mostly-unique free-text target (free-form QA / extraction /
  generation), the bundled `cluster_split.py` deliberately switches to
  `info.strategy: "random"` because target-value stratification is not
  meaningful. That random fallback does **not** satisfy this loop's semantic
  leakage barrier. **STOP and say so**; obtain a stable semantic grouping field,
  or use an external group-aware partitioner that keeps semantic groups in only
  one split. Do not route this case to `cluster_split.py` and then accept its
  known free-text random fallback.
- For a non-free-text target without a usable discrete label, use the
  co-located **`cluster_split.py`** — the `dataset-transformation`-owned local
  cluster splitter documented under "Shared Cluster Splitter" in `op_split.md`
  (it embeds, KMeans-clusters, and stratifies on `(cluster_id, label)`). The loop
  does **not** author its own clustering. ⚠️ A plain random or single-field split
  here leaks semantically-similar rows across seed/dev/test and inflates the
  held-out score. If its embedding dependencies are unavailable and it falls
  back to label-only, **STOP and say so** rather than shipping a leaky split — a
  leaky split is worse than no split.
- Never trust tool defaults: `dataset_split.py` defaults to `--strategy
  random`. You MUST pass `--strategy stratified --stratify-field <label>`
  explicitly; omitting the strategy gives a random split with no error.

### Step 2 — pick the degrade mode from the row count

Pick the degrade mode from the total row count. Each degraded mode below carries
a warning you **MUST carry forward and surface to the user at the single Step 7
confirmation** — do not open a separate confirmation pause here; Step 7 is the
one gate for this split:

- **≥ 100 rows → three-way** `seed` / `dev` / `test` at ~0.20 / 0.35 / 0.45.
- **≥ 40 but < 100 rows → two-way**, `seed` + `dev` only (no test). Raise seed
  to `max(20 / total_rows, 0.20)` so seed still clears the ≥ 20 floor, and give
  dev the rest. **Warn:** "Without a held-out test split we cannot measure true
  generalization; the dev score may be optimistic."
- **< 40 rows → shared** `seed` = `dev` (the same rows used as `synthetic-dataset-generation` input and as
  the dev signal; no real partition). **Warn:** "High risk of over-fitting to
  seed/dev; the model may not generalize."

### Step 3 — run the stratified split ONCE, then leave it fixed

⚠️ **Create the split exactly once, at this setup step, and never re-derive
it.** The loop is resumable and reuses these same three files for every
iteration and every resume (the plan records their paths). If you re-run the
split on a resume you will produce a _different_ partition, leaking former
`test` rows into `seed` and silently invalidating every downstream score. On
resume, **read the existing `seed.jsonl` / `dev.jsonl` / `test.jsonl`; do not
regenerate them.**

Run the stratified split with the ratios from Step 2 and the label field from
Step 1.

### Step 4 — ⚠️ verify the split is genuinely stratified, not a silent random fallback

`dataset_split.py` and cluster splitters can **degrade to a random split** when
the stratify field doesn't match the data — but the degradation is **observable,
not fully silent**. When the field is absent from _every_ record,
`dataset_split.py` **raises `ValueError`** (loud, pre-split). When it is present
but sparse (a class with fewer than 2 samples), the script still runs but
surfaces it: rows with no value bucket under a `__MISSING__` class and the stats
report the fallback (`strategy` stays `"stratified"` with the fallback flagged).
So verify via those signals rather than assuming a clean split. For any mode that
used the stratified engine (three-way and two-way — the shared mode is exempt
because it does no partition), you MUST confirm ALL of the following on the
split's reported `class_distribution`
before accepting it, and **STOP** on any failure:

1. **No `stratification_fallback` flag** is set.
2. **No `__MISSING__` bucket** appears in any split's class distribution — its
   presence means the stratify field was absent from some rows and those rows
   were bucketed as their own pseudo-class, degrading the stratification. Reject
   even a _mixed_ `{pos, neg, __MISSING__}` distribution, not only an
   all-missing one.
3. **More than one real class bucket** (`n_buckets > 1`). A split that collapsed
   to a single class is not a genuine stratification.

If any check fails, the field name is wrong or stratification wasn't applied —
fix the field/strategy and re-run; do NOT proceed with a random split.

**Cluster path (`cluster_split.py`).** When Step 1 routed the free-form /
no-discrete-label case to `cluster_split.py`, that script does **not** report
`dataset_split.py`'s `class_distribution`; its `manifest.json` records
`info.strategy`, `info.n_buckets`, and (on failure) `fallback_reason` instead.
Verify the cluster split with the equivalent checks and **STOP** on any failure:

1. **`info.strategy == "cluster"`** (not `"random"` or `"label"`) — a `"random"`
   strategy means the gold was free-text/mostly-unique and no real stratification
   happened; reaching this result means Step 1 misclassified a free-text target
   that should have stopped before splitting. `"label"` means it fell back to a
   label-stratified split. Treat either as the random-fallback failure above
   unless the label fallback was explicitly intended.
2. **No `fallback_reason`** present in the manifest.
3. **`info.n_buckets > 1`** — a single bucket is not a genuine cluster split.
4. Honor the script's own stderr failures (it raises when a cluster split would
   silently reduce to random) and the `partially_stratified` warning.

### Step 5 — ⚠️ enforce the ≥ 20-per-split floor on the ACTUAL counts

After splitting, count the rows actually written to each non-empty split and
confirm **every split has ≥ 20 rows**. The degrade mode is chosen by _total_
row count, but a skewed stratified split can still leave one split under the
floor. If any split has between 1 and 19 rows, **STOP**: drop to a coarser
degrade mode (fewer splits) or get more data — do not proceed.

### Step 6 — write the plan's role names

Write the outputs as **`seed.jsonl` / `dev.jsonl` / `test.jsonl`** (the plan's
roles), not the engine's internal `split_train/val/test.jsonl` names — rename
them. In two-way mode there is no `test.jsonl`; in shared mode `seed.jsonl` and
`dev.jsonl` hold identical content.

**Cluster path (`cluster_split.py`).** This script emits `dev.jsonl` /
`val.jsonl` / `test.jsonl` and is driven by `--dev-frac` / `--val-frac`
(defaults `0.5` / `0.25`; `test` takes the remaining `1 − dev − val`) — NOT the
plan's `seed`/`dev`/`test` roles or `dataset_split.py`'s names. It always writes
all three files and has no two-way/shared switch, so the degrade mode from
Step 2 is produced by choosing the fractions and then keeping/renaming the right
outputs:

- **Three-way (≥ 100 rows).** Run `--dev-frac 0.20 --val-frac 0.35` (the
  script's `dev` → loop **seed**, its `val` → loop **dev**, remaining `test`
  ≈ 0.45 → loop **test**). Then rename `dev.jsonl → seed.jsonl`,
  `val.jsonl → dev.jsonl`, and keep `test.jsonl`.
- **Two-way (≥ 40 but < 100 rows).** Set `seed_frac = max(20 / total_rows, 0.20)`
  per Step 2, then run `--dev-frac <seed_frac> --val-frac <1 − seed_frac>`.
  **Expect a non-empty `test.jsonl` regardless of the fractions:** on a
  stratified/cluster split, `cluster_split.py`'s `_three_way` deliberately
  reserves a test row from _every_ bucket of size ≥ 3 (it caps the val cut at
  `n − 1`), so `test` holds roughly one row per such bucket — potentially many
  rows, not a 1–2 row rounding remnant. This is expected, not an error. Rename
  `dev.jsonl → seed.jsonl` and `val.jsonl → dev.jsonl`, then **fold ALL of
  `test.jsonl` into `dev.jsonl`** (append every row) so two-way keeps no separate
  test partition and no rows are dropped. Then confirm `seed.jsonl` clears the
  ≥ 20 floor.
- **Shared (< 40 rows).** The seed and dev roles are the same rows, so do not
  partition for them: run the splitter only to materialize the set (or skip it
  and use the labeled input directly), then write `seed.jsonl` and `dev.jsonl`
  as **identical content**. There is no `test.jsonl`.

Do not accept the script's default `0.5/0.25` fractions or its raw output names
for the loop — they produce mis-proportioned and mis-named splits. In every mode
still run Step 4's cluster acceptance checks and Step 5's ≥ 20-per-split floor on
the splits you actually keep.

### Step 7 — ⚠️ propose the split to the user and confirm before proceeding (the ONE gate)

This is the **single confirmation** for the benchmark split — the loop opens no
other approval pause for it. Before the split is used by any downstream step,
**surface the proposed split to the user** in one checkpoint:

- the chosen strategy and stratify field;
- the degrade mode picked in Step 2 **and its warning** (the two-way "no held-out
  test" or the shared-mode over-fitting warning, when that mode was chosen);
- the per-split row counts — showing every split clears the **≥ 20-per-split
  floor** (Step 5) — and, for a stratified split, the per-split class
  distribution.

⏸ Wait for explicit confirmation. If the user rejects it, fix the field,
strategy, or degrade mode and re-run Step 3 (creating the split once, as above);
do NOT silently proceed on an unconfirmed split.

### Step 8 — record the split locations in run state

After the split is confirmed, record each split's paths in `run_state.splits` —
`{seed, dev, test}` each with its `local` and `s3` location (omit `test` in
two-way mode; `seed` and `dev` point at the same file in shared mode). The
loop's resume logic reads these to reuse the existing splits instead of
re-creating them (see Step 3); if they are not recorded, a resume re-runs the
split and leaks `test` rows into `seed`.

---

## Iterative Synthetic Data Generation loop — prepare evaluation dataset (tag + system prompt + Verl + merge)

**When this applies:** the loop scores `seed` + `dev` in ONE evaluation job, and
scores the held-out `test` split in a separate (async) job. To make both
possible you tag all three splits, transform them to the Verl eval format, and
produce **two** merged files: one combining **seed + dev**, and one combining
**seed + dev + test**. The eval jobs then join per-example predictions back by
`id`/`index` and partition them by `split`.

**Mechanism — BYOC, run server-side (do NOT do this locally).** The local agent
**authors a `transform_dataset(inputs: dict[str, str], output_dir: str) -> dict`
script** — in the format BYOC expects — that performs the tag → system-prompt
insert → Verl reshape → merge, reusing `scripts/transform_helpers.py` for
streaming JSONL I/O rather than re-deriving it. BYOC then runs that script on the
cloud (see `api-execution-flow.md` → "Direct BYOC path" for the entry-point contract and
job submission). The steps below are the contract that script must implement.

⚠️ **Stamp all THREE of `id`, `index`, and `split` on every row — they are
load-bearing join keys, not cosmetic, and error-analysis needs each for a
different reason:**

- **`id`** — the scored predictions (`details_*.parquet`) carry it; error-analysis
  joins predictions to benchmark annotations and to the _prior_ iteration's
  analysis (for regressed/persisted/resolved trends) on `id`. The
  model-evaluation scorers read the row's top-level `id`, so it MUST be present or
  they fall back to a positional default and the trend join breaks.
- **`index`** — benchmark annotations are keyed by `index`, and
  `error-analysis`'s `load_inputs.py` **rejects** any annotation record missing
  it. Stamp `id` and `index` with the **same** stable value so both joins line up.
- **`split`** — routes partition failures: `seed` → `inject`, `dev` →
  `spec_edit`/`seed_target`.

A skipped, duplicated, or misplaced value on any of the three silently breaks the
iteration's joins. So follow these steps exactly:

### Step 0 — resolve the system prompt (LOCAL, before building the BYOC job)

The system prompt is **decided once in step 7 of the plan** and recorded in
`run_state.json` — this transform is a **consumer**, never a producer, because
`synthetic-dataset-generation`, fine-tuning, and evaluation must all share the identical prompt. Resolve it
**on the local side** (the BYOC container has no run dir, so it cannot re-walk
run-dir-relative paths — resolve here and pass the resulting text into the job):

- Look at `run_state.json` `derived_config.system_prompt_path`:
  - If it is **`null`/empty** → **no system prompt is inserted**; skip the insert
    entirely (step 7 decided none is needed).
  - If the key is **absent** → likewise skip; treat a missing key the same as `null`.
  - If it is **set** → read the text from that path, resolved **relative to the run
    dir** (or as-is if absolute), mirroring
    `planning/scripts/run_frontier_eval.py`'s `find_system_prompt`, and insert it.

Pass the resolved text into the BYOC job as an **input** (an S3 object in the
`inputs` mapping, or inlined in the script's config) — never as a run-dir path
the container is expected to resolve. When it was null/empty/absent, pass nothing
and the script inserts nothing.

### Step 1 — stamp a stable, unique, positional key (into both `id` and `index`) and split tag

Process `seed` first, then `dev`, then `test`, with a **single continuous
counter** so keys are globally unique across every merge:

- For each seed row, in order the key is `"seed-00000"`, `"seed-00001"`, … (the
  format is `{split}-{counter:05d}`); write it into **both `id` and `index`**
  (same value), and set `split = "seed"`.
- Then continue the SAME counter into dev: if seed had S rows, the first dev row
  is `"dev-{S:05d}"` (the continuous counter, zero-padded to 5 digits — e.g.
  `dev-00100` when S=100), and `split = "dev"`.
- Then continue the SAME counter into test, tagged `split = "test"`.
- ⚠️ Do NOT restart the counter between splits and do NOT skip a number. Every
  row gets exactly one key, written identically to `id` and `index`; keys must be
  unique across all three splits so the seed+dev and seed+dev+test merges never
  collide. Row order is explicitly NOT the join key — the stamped value is.

### Step 2 — insert the system prompt (if step 0 resolved one) and reshape to Verl

If step 0 resolved a system prompt (i.e. it was **not** `null`), insert that
**same** text into every record as the system message, consistently across all
three splits — the model is evaluated with the identical prompt it was trained
and generated with. If step 0 resolved nothing, insert nothing.

Then reshape every record to the **Verl** eval format:

- Put the stamped key in **both the top-level `id` and top-level `index`** fields
  (same value). The model-evaluation scorers read top-level `id` and carry it into
  the scored report (the prediction↔annotation and prior-iteration joins run on
  it); `error-analysis`'s `load_inputs.py` keys annotations on `index` and rejects
  records without it. Also mirror the key in **`extra_info.index`**.
- Put the split tag in **`extra_info.split`** (create `extra_info` if absent),
  and also keep a top-level `split` field.
- ⚠️ **Do NOT put the key in `data_source`.** In Verl, `data_source` is the
  _source name_ used for reward routing and per-source score aggregation, not a
  row key — writing a unique per-row value there defeats reward-function selection
  and clobbers any real source name the row already carried. Leave any existing
  `data_source` untouched.

Beyond the tag, the system-prompt insert, and the Verl field placement, leave
each record's content unchanged — no dedup, no filtering, no other field
transforms.

### Step 3 — create the two merged files

Concatenate the stamped, reshaped rows **in split order** into two Verl files:

- **seed + dev** → the combined eval job's input. Record its total
  (`= seed count + dev count`).
- **seed + dev + test** → carries all three splits with metadata. Record its
  total (`= seed + dev + test count`).

Because the stamped keys are globally unique across all three splits (step 1),
the same rows compose into both files without collision, and predictions from
either job partition cleanly back by `split`.

### Step 4 — ⚠️ verify the round-trip after evaluation

After an eval job returns, before you split its predictions back by `split`:
confirm the **prediction count equals the merged file's row count** (seed + dev
for the combined job; seed + dev + test for the held-out job), and that `id`,
`index`, and `split` **round-trip** on a few sampled rows (the values you stamped
came back unchanged). If they did not survive scoring, **STOP and fix the
eval-output
contract** — do not guess the split partition by row position.

### Step 5 — record the merged-file locations, and re-tag on any split re-creation

Record **where the two merged files live** so a resume reuses them instead of
rebuilding: write their `local` (and `s3`, if uploaded) paths into
`run_state.splits` — e.g. `run_state.splits.eval_seed_dev` and
`run_state.splits.eval_seed_dev_test`, each `{local, s3}`, alongside the raw
`{seed, dev, test}` entries the benchmark-split step already records. Without
this, a resume cannot find the merged eval inputs and re-runs the whole tag →
prompt → Verl → merge pipeline.

⚠️ **If the underlying `seed`/`dev`/`test` splits are ever re-created** (new rows,
a re-run, a changed ratio), the stamped `id`/`index` keys no longer describe the
current data — so **re-tag from scratch and write the merged files to a FRESH
path**, then update the `run_state.splits` eval entries to point at it. Never
reuse a previous merged file or overwrite it in place: stale predictions carrying
the old keys would join against the new rows and silently mis-partition. The
merged eval files are valid only for the exact split contents they were stamped
from.
