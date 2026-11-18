# Full Loop - label, refine, gate, apply

The default workflow. Bootstrap a seed → refine the spec against held-out data →
gate on a reserved test partition → apply the hardened spec to the whole corpus
with confidence. Follow the steps in order. The deterministic steps run via
`scripts/`; the judgement steps (refining the spec) are yours to perform.

Every labeling step is **one labeling job** (the labeling round,
`code_templates/labeling_round.py`, which submits a `CreateJob` with
`DatasetOptions.Type: labeling.<task>` through the V3 SDK's auto-labeling operators;
the contract: `references/sdg-indexed-backend.md`). The job labels, votes the jury,
scores against the gold you send as `EvaluationData`, calibrates the cutoff, pins the
spot-check and routes to review; the skill submits it and reads its artifacts back
through the Hub entry. A refine round is a job over the dev or val split
(`STAGE = "dev"` / `STAGE = "val"`), registered under a run-unique scratch name; the
corpus run (`STAGE = "corpus"`) is the deliverable. The labeling job is the only
labeling path: the skill never labels a row itself, and there is no client-side
vote, no client calibration and no fallback.

**How the code templates run.** The deterministic steps that are not human-in-the-loop
(inspect, folds, induce, the labeling round, score and select) are `code_templates/*.py`
files: copy the template into the project as `<proj>/scripts/<template>_<stage or
step>.py`, fill every `[PLACEHOLDER]` in its Cell 1 from the step's table (a
setting the step does not use keeps its default), and run it with the Step 0.1
interpreter. Each template names its cells; run only the cells the step calls for (a
`None` setting skips its cell). This reference names each template setting as it is
(`TARGET`, `TEXT_FIELDS`, ...); the run log's invocation records them under its own key
names (`target`, `text_fields`, ...). Lines ending in `# NOTEBOOK_ONLY` run only in a
notebook; script mode drops them. Each template's Cell 0 is the notebook's title and a
short note for the user; what each cell does, and which operator it calls, is in the
step that runs it. Everything that reads customer rows prints `client-read:`.

> **HARD RULE - confirm before you spend, and run the steps yourself.**
>
> 1. **Walk the steps individually.** Run each `scripts/` command and each template as its own
>    step; never a wrapper script that chains Steps 1-7 in one shot (that bypasses the gate).
>    The one exception: after the item 2 yes, the user asks for one script (item 4).
> 2. **Stop for approval before the FIRST token-spending run.** After Step 1 (split) and before
>    ANY labeling round, show the approval summary of `references/approval-summary.md`: the
>    corpus size, the spec, the split, the model line (every id the service accepts verbatim), a
>    rough cost, the **accuracy target** `<target>` (default 0.90; 0.85 to 0.99), the DataSet
>    names, the unpassed text columns, the seed's ids, that the runs are billed and not
>    reversible, and an opt-in option only as `references/offer-options.md` says.
>    ⏸ Wait for an explicit yes.
> 3. **Do not proceed on assumed approval.** If the user has not said yes, stop and ask
>    (`overview.md` Principle 2).
> 4. **A yes at the item 2 pause approves the default run** (in a planning `PLAN.md`, the hard
>    stop at Confirm and approve the run); do not ask again before it. If the user asks for one
>    script, write it: it runs the steps in order through the labeling-round template, prints each
>    step's result, halts on the first failure and stops at each later pause. Through the corpus
>    run, only an opt-in option or a billed run the summary did not price needs its own yes; the
>    later pauses (Step 7a's review choice, the re-refine offer, registration, Step 8b's deletion)
>    still wait for their answer.

## Step 0 - Gather inputs (cascading fallback)

You need: the unlabeled corpus path, the labeling spec, the text field name, and
the labeled seed. Take them from the conversation and the project files; this gathers
names only and runs nothing. The inspect cell imports the SDK, so `sdk-getting-started` has
run first (Step 0.1). **Then read one row of each input, nothing more:** run `code_templates/inspect_inputs.py` Cell 2
(`inspect_input.inspect`) with `python`:

| Placeholder | Value |
|---|---|
| `[CORPUS]` | the corpus: local path, `s3://` URI or DataSet ARN (`None` to skip it) |
| `[SEED]` | the labeled seed: local path, `s3://` URI or DataSet ARN (`None` to skip it) |
| `[GUIDELINES]` | the spec / guidelines file, when there is one (its label set picks the label field) |
| `[TEXT_FIELDS]` | the comma-separated fields the spec passes to the labeler, when known |
| `[REGION]` | the inputs' region |

It reads the first row of each file (one ranged read of an `s3://` object; `client-read:`
on stderr says so) and prints the field names, `proposed_text_fields`, the seed's
`proposed_label_field` and `task_shape`, `estimated_rows` (object size over the first
row's size; the job's summary makes it exact) and warnings (a corpus field the seed
lacks, no `id` field). With `TEXT_FIELDS` it also lists `unpassed_text_fields`, text
columns the labeler would never see (a title, a question): the HARD RULE #2 summary asks
whether each goes in. If the user approves the pause without answering about a listed
column, leave it out of `TEXT_FIELDS` and tell the user. It also lists
`reserved_text_fields`, names the job reserves (such as `source`) and refuses in
`TEXT_FIELDS`: say which and why; if the label can depend on one, ask the user to copy
it to a new name (such as `evidence`) in the corpus and the seed. The corpus is **not readable on the client beyond its first
row**: do not stream it, count it, sample it or `cat` it - the labeling job reads it
in the service. The seed is small and client-readable (the split, induction and demo
steps read it; each says `client-read:` with the row count), but nothing in this loop
quotes a row of either file to the user. The labeled corpus stays behind the API too:
the corpus run downloads the job's summary, held-out report and review rows, never its
`labels.jsonl`, and the deliverable is the labeled DataSet ARN (Step 7).

Resolve a non-local corpus (`s3://` / `DataSet` ARN) with the `hub_ops` template's `resolve`
action (`code_templates/hub_ops.py`; `[ACTION]` `resolve`, `[REF]` the `s3://` URI or ARN,
`[OUT]` `corpus/corpus.jsonl`, `[PROJECT_DIR]` `<proj>`) and
keep the result in the project's **`corpus/`** slot. Two cases:

- **Remote corpus (`s3://` / ARN): keep it off the sandbox.** Run
  the `resolve` action with `DOWNLOAD = False` (the default; never set `DOWNLOAD = True` for the corpus). It
  writes a **`corpus/corpus.ref.json`** pointer and **`corpus/head.jsonl`** (the first
  two rows: the shape, never a sample) - never the corpus body. Pass the corpus to
  the labeling round's `INPUT_DATA` as the user named it: a DataSet ARN as that ARN (it
  goes to the job as `InputDatasetArn`), an `s3://` URI as that URI or the
  `corpus.ref.json` path; the job labels the corpus in place from the customer's
  bucket. See the `input-output-contract` reference for the pointer fields.
- **Local corpus:** the `resolve` action copies it through to
  **`corpus/corpus.jsonl`** as before, and `INPUT_DATA` is that local path; the
  submitter uploads the file under `S3_PREFIX` as it is, without parsing it (the
  job checks its ids and text fields at load). A local corpus is still the
  customer's data: read its first row (above) and nothing else. Its re-attach check
  uses the file's path, size and modification time, never its bytes.

Step 1 writes the partitions to the sibling **`splits/`** slot. See the layout in
the `directory-management` reference.

**Check the corpus size first, and STOP above the row limit** (`overview.md`, Limits). The inspect cell's `estimated_rows` is the only count you take before the job: when it is above the limit, STOP and tell the customer the estimate and the two ways forward that Limits gives (the job itself refuses a larger file at load, so the paid run would fail anyway). Never count the rows by reading the corpus.

If there is no spec, draft one in-skill (see `references/spec-authoring.md`):
gather the label set + one-line definitions with the user, then continue here.
If the label set looks unstable (tiny or overlapping classes), read
`references/taxonomy-guidance.md` first - fixing the taxonomy is cheaper than any
amount of refinement.

> **No labeled seed? Bootstrap one, or take the cold-start opt-out; never label from general knowledge.**
> This loop assumes a small labeled seed already exists: it is what Step 1 splits into dev/val/test. If the customer has NONE, you MUST switch to `references/cold-start.md` and bootstrap a seed there (people label a random sample of the corpus), then return here at Step 1 with that seed. Its opt-out, for a customer who will not label the sample, is the only path without a seed. You MUST NOT proceed to label the corpus from general knowledge or skip the bootstrap otherwise: labeling the corpus without a seed and without that opt-out is an error, not a shortcut.

## Step 0.1 - The SDK is installed (before any template, script or model call runs)

Labeling runs on the synthetic data generation service via the SageMaker Python SDK
(`sagemaker.ai_registry.DataPreparer`; the labeling request is pinned to schema `2.0.0`, the one
that carries `DatasetOptions`). Every template and script imports it, from Step 0's inspect cell
on, so `sdk-getting-started` has run in this session before that cell (`overview.md`, SDK
environment prerequisite), and every `python` command in this loop runs with the Python
`sdk-getting-started` installed into. If an import fails, that is a hard STOP: the SDK is not
installed yet; it is not a capability limitation to report and stop on, and "the SDK is not
available in this environment" is a misdiagnosis. Activate `sdk-getting-started` and run its
install to COMPLETION (its setup doc owns the recipe; do not improvise a partial `pip install`),
then rerun; if the import still fails after completing `sdk-getting-started`, STOP and report
the install error: do not label another way. Never switch to direct Bedrock, a hand-written
classifier or labeling from general knowledge: that produces un-scored, un-juried labels.

## Step 0.5 - Detect the task type

Most runs are classification, but the skill also does NER, summarization,
extractive QA, and LLM-judge / ordinal scoring (see `references/task-types.md`).
The loop is fixed; detection sets only which task - see `overview.md`.

**Detection is the default, not a manual step.** Omit `TASK` and the task is
auto-detected; `TASK` is an explicit **override** that always wins. A
low-confidence pick (the `ask` tier, confidence < 0.5) is refused with a clear
error rather than silently defaulting to classification - pass an explicit
`TASK` to proceed. The labeling round detects from the spec + the
gold rows it is given (`EVAL_DATA`, else `DEMOS`; never the corpus); the scoring cell
takes an explicit `TASK` (pass the task the run used, from its run-log entry). Detection is deterministic and logged to stderr as `[task-detector] ...`, and
`code_templates/inspect_inputs.py` Cell 3 (`detect_task.detect`) runs the same detection standalone.

**Run the detector first anyway, to lead the confirm gate**, so you can state the
detected task + reason at the Step 2 hard-stop confirm gate (and set Step 1's
`GT_FIELD`) rather than discovering it from the run log: `code_templates/inspect_inputs.py`
Cell 3, with

| Placeholder | Value |
|---|---|
| `[SPEC]` | the spec |
| `[TASK_SAMPLE]` | the labeled seed (`<seed.jsonl>`); on cold start, the corpus head file |
| `[DETECT_OUT]` | `<proj>/task_detection.json`, or `None` to print only |

Point the detector at the **labeled seed**, not the corpus: the seed's ground-truth
column (`gt_label` / `gt_entities` / `gt_score` / ...) is its STRONGEST signal (the
high-confidence "adopt" tier, no user round trip), and the seed carries every input
column the corpus has. The unlabeled corpus has no `gt_*` column, which forces a
lower-confidence spec-text fallback. Only **cold start** (no seed yet) passes a corpus
head sample instead - see `references/cold-start.md`.

It prints `{task, confidence, reason, signals, decision}`. Follow the `decision`:

- **adopt** (confidence >= 0.85): use the suggested `task` as `TASK` on every
  command below (and Step 1's `GT_FIELD`); state it + the reason at the Step 2
  confirm gate.
- **confirm** (0.5-0.85): adopt the suggested `task` as the default, but call it
  out explicitly at the gate (the detected task and the reason) so the user can
  change it.
- **ask** (< 0.5): the signal is too weak; ask the user which task before proceeding.

If `signals.image_field` is set, say at the Step 2 confirm gate that only the text
fields are labeled and the image is not read (`overview.md`, Out of Scope). A run with
no `EVAL_DATA` and no `DEMOS` (the cold-start opt-out) has only the spec to detect from,
so pass `TASK` explicitly there.

**You MUST route each task through its own `TASK` - do not hand-roll a scoring
script and do not force a non-default shape into `classification`:**

- **`summarization`** (free-text summary): no `LABEL_SET`, no gold (no `EVAL_DATA`:
  the job refuses one); every summarization job, dev and val rounds included, needs
  `GRADERS` (1 to 3 models, none of them the labeling model, that grade a sample of
  at most 100 summaries against their own source text; the job's `GoodRate`). The
  spec states the length.
- **`ordinal`** (numeric rating on a fixed scale): the scale lives in the spec's
  `### Score Levels`; when the gold ratings are STRING tiers, pass the scoring cell
  `--label-map '{"very negative": 1, ...}'` or `SPEC` so ranks
  come from the Label Set order (see `references/task-types.md`).

Summarization and ordinal have no discrete label to vote (`references/task-types.md`,
Jury applicability).

## Step 0.6 - Taxonomy separability gate (classification)

Before spending on a full run, check the label set is separable: overlapping,
absence-defined or barely-covered classes cannot be rescued by refinement, and
catching them here is free (the programmatic form of
`references/taxonomy-guidance.md`): `code_templates/inspect_inputs.py` Cell 4
(`taxonomy_gate.gate`), with

| Placeholder | Value |
|---|---|
| `[SPEC]` | the spec |
| `[LABELED]` | the labeled seed (optional) |
| `[GT_FIELD]` | the seed's gold field (`gt_label`) |
| `[TASK]` | the detected task |
| `[GATE_OUT]` | `<proj>/taxonomy_gate.json`, or `None` to print only |

It prints `{verdict, decision, issues, ...}`. When `decision` is
`review-before-spend`, surface the flagged classes (overlapping pairs,
absence-defined, missing or under-sampled) at the Step 2 confirm gate and let the
user merge, restructure, or add examples first. The user owns the taxonomy, so
this never blocks on its own; it makes the problem visible before the spend.
The overlap check is skipped for `TASK = ordinal` (adjacent tiers are expected
neighbors, not confusions).

**Only classification needs this gate.** A non-classification task
(summarization / qa / ner / llm_judge, or an ordinal spec that carries only a
numeric scale) has no Label Set to check, so pass the detected `TASK` through:
the gate then returns `decision: "skip"` and you proceed to the run. The overlap
check is lexical (`separability.method: "lexical"`, `references/taxonomy-guidance.md`):
it compares shared words, not meaning, so a clean lexical result is a weaker
"separable" signal.

## Step 1 - Split

Split the labeled seed into **dev / val / test** partitions with
`cluster_split.py`, owned by `dataset-transformation` (flags, dependencies and
fallbacks: `dataset-transformation/references/op_split.md` → "Shared Cluster Splitter").
Invoke it by its skill-root path, below. The split is cluster-aware, stratified and
seeded, so each partition is representative and reproducible. The **test partition is
reserved**: never shown to the labeler or the refiner, and the only thing the final F1
is measured on.

> **Routing.** The seed split follows the `dataset-transformation` routing contract
> (`dataset-transformation/references/routing-and-guardrails.md`) like any split:
> routing keys on **source location first, then size**, and the chosen path is confirmed
> with the user. A **local** seed file at/under `LOCAL_CAP` runs the local
> `cluster_split.py` below; an **S3/Hub** source (or a local file the user sends to the
> API) runs on the DataTransformation API: the `Split` operator with `Method=stratified`
> and `StratifyField` the gold field, on a `hub_ops` `dt-view` of the seed (`[ARN]` for a
> DataSet, `[S3_URI]` and `[NAME]` for an object; nothing is read) so the job's output
> does not land as a version of the seed. Do not send `Method=cluster`: run live, the
> DataSets it registers point at files that do not exist. Above `API_CEILING` refuse.

```bash
python <skill-root>/references/dataset-transformation/scripts/cluster_split.py --labeled <seed.jsonl> --gt-field <gold field> --text-fields <fields> --out-dir <proj>/splits
```

`<gold field>` is the seed's gold column: `gt_label` for classification, otherwise the task's own (`references/input-output-contract.md`, Inputs). `<fields>` is the comma-separated list of input fields the spec labels from, the same list the labeling runs get as `TEXT_FIELDS`. Without it, a seed whose input fields are not among `cluster_split.py`'s defaults is clustered on each row's whole JSON, gold label included.

After an API `Split`, download each split DataSet to `<proj>/splits/{dev,val,test}.jsonl`
(the `hub_ops` `resolve` action with `[REF]` the ARN, `[OUT]` the path and `DOWNLOAD = True`; the seed is small), since
freeze and the guard read local files. Then freeze the split, the only split the loop makes:
`code_templates/split_freeze.py` with

| Placeholder | Value |
|---|---|
| `[ACTION]` | `freeze` |
| `[SPLITS_DIR]` | `<proj>/splits` |
| `[TEXT_FIELDS]` | `<fields>` |
| `[LABEL_FIELD]` | `<gold field>` |
| `MOVE_NEAR_DUPLICATES` | `True` only after the user chose it (below) |

It records each split's ids and file hash in `<proj>/splits/split_state.json` and
refuses splits that share an id or a near-duplicate text; `--move-near-duplicates` moves
the val or test member of each pair into dev first (say how many, and that test is then
no longer a plain random sample). When freeze refuses near-duplicates, show the count and
the example pair it prints, and ask the user to choose between `--move-near-duplicates`
and a fresh split; never pass the flag without that answer. ⏸ Rows that share a long field
(one document with several summaries, one context with several questions) are reported
as pairs, and the flag can then nearly empty val and test, so say so before the user
chooses. Each split then has one job, and every step that
reads a split file, or a file built from one, checks it:

| Split | Used for | Never used for |
|---|---|---|
| dev (train) | spec refinement, candidate mining, demos | the gate or the certificate |
| val | candidate selection, the held-out gate | demos, examples, the certificate |
| test | the corpus run's cutoff and certificate, the reported metrics | anything a model or the agent learns from or chooses on |

kfold folds (listed in their `manifest.json`) and the in-job search take dev and val rows together; test never.

A script that reads a row of a split its step may not read stops before any upload,
and so does any step when a split file
changed after the freeze. Every read of a test row is a run-log entry (kind
`analysis`, status `test-read`) with its step. Never re-split: dev and val edits go
through the `split_freeze` template's `rehash` action (Step 3a).

The validated split is the `cluster` strategy. Read `info.strategy` in `<proj>/splits/manifest.json`: `label` means the split fell back to label-only stratification, and `info.fallback_reason` says why (usually that `sentence-transformers` and `scikit-learn` are not installed; `overview.md`, Prerequisites). Say so in the HARD RULE #2 summary. Installing the two packages changes the user's environment, so it is the user's call.

## Step 1b - Induce rules if the spec is weak (optional, A/B-gated)

> **Covered by the HARD RULE #2 yes.** Step 1b's A/B runs the labeling round
> on the val split (commands below), which spends tokens. Run it only after the
> item 2 approval, and only when that summary priced it; otherwise pause for it. Do
> not run Step 1b labeling speculatively.

If the spec has only label definitions and **no decision rules** (or labels come
out inconsistent), induce the rules from the seed before labeling. This is the
skill's biggest lever on policy tasks.

The A/B is held-out and do-no-harm: induce rules from `dev` with
`code_templates/induce_spec.py`; label `val` with BOTH the provided and induced specs
(the labeling round) and read each job's `HeldOutAccuracy`; then
`code_templates/score_and_select.py` Cell 3 with `MIN_GAIN = 0.03` ships the induced spec only if it beats
the provided one on `val`. Exact commands are in `references/spec-induction.md`;
the canonical `<proj>/scores.json` shape is the Step 5 block below.

For `llm_judge` (and optionally `ordinal`) induction writes an anchored rubric (`references/labeling-spec-template.md`, Score Levels) instead of label rules: `induce_spec.py` with `TASK = "llm_judge"`, `SCORE_MIN = <lo>`, `SCORE_MAX = <hi>`. This is the default structure for a judge spec, so propose it (under this step's STOP gate) whenever an `llm_judge` spec has no `### Score Levels` section; the A/B metric is the one `references/spec-induction.md` (step 4) names. See `references/spec-induction.md`, "Numeric judge tasks".

Use the winning spec (from the decision) as the starting spec for Steps 2-5. Skip
this step when the provided spec already has good, specific rules. Induction can only
help: if it does not beat the provided spec by the margin, the provided spec is kept.

## Step 2 - Label dev and val

> **Covered by the HARD RULE #2 yes; do not run without it.** Step 2 spends model
> tokens at scale (the first step that does if Step 1b was skipped). Before any
> labeling round here:
>
> 1. **Preflight: the SDK imports** (Step 0.1); if it does not, activate
>    `sdk-getting-started` and retry.
> 2. Check that the user gave the HARD RULE #2 yes for this run. If not, stop and
>    get it; do not proceed on assumed approval, and do not batch Steps 2-7 ahead of
>    it (`overview.md`, Principle 2). Do not ask again once it is given (HARD RULE #4).

Label **both** the dev rows and the val rows with the current spec: one labeling
job per split (see `references/sdg-indexed-backend.md`). The split's gold rides
along as `EvaluationData`, so the job scores itself; the skill reads the job's
`failures.jsonl` (dev: the refiner's error view) and `HeldOutAccuracy` (val: the
steering metric) back.

> **Labeling mode unavailable? HALT - never inline-relabel.** Every labeling call
> MUST route through the labeling round (`code_templates/labeling_round.py`). If the job cannot run (the causes are
> in `references/troubleshooting.md`, "Labeling mode unavailable"), you MUST halt and
> tell the user plainly, as `overview.md` says; you MUST NOT label the rows from general
> knowledge with a direct Bedrock/Converse call or any other shortcut. There is no
> client-side labeling path to fall back to.

> **Reuse Step 1b's val, do not re-buy it.** If Step 1b ran the bake-off, it
> already labeled and scored **val** for the winning lever/spec. Carry that
> `work/val_pred_iter_0.jsonl` / `work/val_pred_iter_0.held_out_report.json` forward as this iteration's val
> (iter_0 = the initial spec) instead of paying to relabel the same rows. You still
> label **dev** here for the error signal.

Two roles:

- **dev predictions** - the refiner reads the *errors* here (the confusion
  pairs) to decide what to fix.
- **val predictions** - the steering metric the loop gates on. Val is held out
  from the refiner's error view, so improving val means the edit generalizes.

Run `code_templates/labeling_round.py` (all its cells) for the dev job, with the
settings below; a setting not listed keeps its default. The run log's invocation
records them under its own key names (`spec`, `stage`, ...), which the delivery
artifact and the review scripts read.

| Placeholder | Value |
|---|---|
| `[SPEC]` | `<spec.md>` |
| `[STAGE]` | `dev` |
| `[INPUT_DATA]` | `<splits/dev.jsonl>` |
| `[EVAL_DATA]` | `<splits/dev.jsonl>` |
| `[OUT]` | `<proj>/work/dev_pred_iter_<N>.jsonl` |
| `[PROJECT_DIR]` | `<proj>` |
| `[RUN_ID]` | `<run id>` |
| `[RUN_LOG_ITERATION]` | `<N>` |
| `[DATASET_NAME]` | `<name>` |
| `[GENERATION_MODEL_ID]` | `<id>` |
| `[TEXT_FIELDS]` | `<fields>` |
| `[TASK]` | the Step 0.5 task (`None` detects it) |
| `[LABEL_FIELD]` | the gold field when it is not the task's default |
| `[DEMOS]`, `[DEMOS_PER_CLASS]` | `<splits/dev.jsonl>`, `<k>` (few-shot only) |
| `[OPTIMIZER]` | the in-job search, when offered (`references/spec-refinement.md`) |
| `[S3_PREFIX]` | `<prefix>` |
| `[ROLE_ARN]` | `<role>` |
| `[REGION]` | the job's region |
| `[SKILL_ROOT]` | the active `aws-ai-ml` skill root (the shared run-log writer) |

The val job is the same template with `STAGE = "val"`, `INPUT_DATA` and `EVAL_DATA` set to
`<splits/val.jsonl>`, and `OUT = "<proj>/work/val_pred_iter_<N>.jsonl"`. `<prefix>` is
the run's S3 prefix (`s3://bucket/autolabel/PROJECT/`).

**Submit, then end the turn.** The template's `WAIT` stays `False` (its placeholder is `[WAIT]`): Cell 3 submits the job
(or re-attaches to it) and prints its name, ARN, status and `RUN_ID`, and Cell 4 stops
while the job runs. Once the job record (`job.json` in the round's staging folder,
`_sdg_work/<RUN_ID>/<STAGE>/` beside `OUT`) exists you may end the turn: tell the user which job was submitted, its ARN and when, and
that nothing more is billed until it ends. To collect it, run the same template again
with the same `RUN_ID` and `STAGE` (on the user's next message, or when they ask): it
reads the job's status from `DescribeJob`, submits nothing, and once the job has ended
reads the result and writes the round's files. Set `WAIT = True` only when the user asks
to wait for the job in this turn.

Pass the same `DEMOS` (from dev) to dev, val and the corpus run (Step 7), as
`references/demo-modes.md` says: a val round or corpus run without them would steer
on, and ship, zero-shot labels for a spec refined under few-shot.

What the submitter does with a local split:

- **Uploads** the rows **without their gold** (the label field and every `gt_*` field
  stripped) as the job's input, the gold as `EvaluationData` (id + gold only;
  `LABEL_FIELD` names the gold field when it is not the task's default), and the
  demos drawn from `DEMOS` as `demos.jsonl`. Demo rows stay in the input but out of
  the job's gold (the job refuses a demo that is also an eval row), so every row of
  the split is labeled. Demos come from the **dev** split only, never val or test.
- **Registers** each round under the scratch name `<name>-<stage>-<run id>`, never the
  deliverable's name (a reused name appends a version to the existing entry), so the
  hand-off cleanup (Step 8b) can delete them all.
- **Writes** beside `OUT`: `<out>.summary.json` (the job's `labeling_summary.json`),
  `<out>.failures.jsonl` (every row the job got wrong against the gold, plus two rows
  per class it got right, each with the gold and the prediction) and
  `<out>.held_out_report.json` (`accuracy`, `primary` / `primary_name`, the per-class
  breakdown and confusion pairs when the job reported them), and prints a JSON summary
  (`held_out_accuracy`, `macro_f1`, `dataset_arn`, `job_arn`, `run_log_entry`).

Use **one `RUN_ID` per refinement iteration** (e.g. `iter-<N>`): the id goes into
the scratch names, and re-running with the same `RUN_ID` and `STAGE` re-attaches
to the job already submitted instead of paying twice.

> **Retain per-iteration predictions.** Write each iteration's dev and val
> predictions to `work/dev_pred_iter_{N}.jsonl` / `work/val_pred_iter_{N}.jsonl` (N =
> the iteration; iter_0 = the initial spec), NOT a single overwritten file, so each
> round's predictions stay beside its spec under the names Step 3 and label review read.

## Step 3 - Read the scores

The jobs scored the splits: read what they wrote beside `OUT`.

- **dev**: `work/dev_pred_iter_<N>.failures.jsonl` is the refiner's error view (every
  row the job got wrong, uncapped and with its full text, plus two rows per gold class
  it got right, `correct: true`; each with the gold and the prediction), and
  `work/dev_pred_iter_<N>.held_out_report.json` carries the per-class breakdown and
  the confusion pairs (which class is mistaken for which).
- **val**: `work/val_pred_iter_<N>.held_out_report.json` carries `accuracy` (the
  job's `HeldOutAccuracy`), its 95% lower bound and, for classification, `macro_f1`
  when the job reported it. **`HeldOutAccuracy` is the steering metric** the loop
  gates on and tracks for best-iter rollback: it is the figure the corpus run's
  certificate is about. Record `macro_f1` in `<proj>/scores.json` as well (`val_macro_f1`).
- **summarization**: there is no gold, so the round's figure is the graders'
  `GoodRate` (the share of graded summaries scored 4 or more on faithfulness,
  relevance and completeness by every grader; `primary_name: good_rate` in
  `<out>.held_out_report.json`), and `<out>.failures.jsonl` holds the graded
  summaries that fell short, with each grader's scores. Steer on `GoodRate`; a
  round whose sample came back mostly incomplete (`GradeIncompleteRows`) is not a
  comparable figure: rerun it.

`code_templates/score_and_select.py` Cell 2 (`scoring.score`) re-scores a seed-sized local prediction file against its split
(`[PRED]` the file, `[GT]` the split, `[TASK]` the task; `[SCORE_OUT]` where it writes `score.json`; for ordinal or llm_judge text labels,
`[LABEL_MAP]` the label-to-rank JSON, e.g. `'{"very negative": 1, "negative": 2}'`) when you need a metric the job did not
report. Leave `GT_FIELD` at `None` unless the gold lives in a field other than the task's
(`gt_label`, `gt_entities`, `gt_answers`, `gt_score`). It makes no model call and refuses
a file over 5,000 rows. The seed is client-readable; the read is reported as `client-read:`.

## Step 3a - Seed label fixes (optional)

Steps 2-3 are the trial run. When the disagreements look like label problems, offer the label
review (`references/label-review.md`; it writes the relabels into the split). If the
user fixes dev or val labels by hand, or adds labeled rows to dev, edit
`<proj>/splits/dev.jsonl` and `val.jsonl` in place and accept them, then rerun from Step 2:

`code_templates/split_freeze.py` with `[ACTION]` `rehash`, `[SPLITS_DIR]` `<proj>/splits` and `[REASON]`
`"<what the user changed>"` (`ALLOW_VAL_REMOVAL = True` when the user removed val rows on purpose).

It refuses any test change, a moved row, a new val row, a removed val row (unless
`--allow-val-removal`) and a near-copy of another split's row. A test label fix, a taxonomy
merge or a new test sample needs a new project and freeze. Otherwise continue to Step 4.

## Step 4 - Decide: refine or stop

Consult `references/refinement-routing.md`. In short: if **val** `HeldOutAccuracy`
is already at or above the gate, **stop and go to Step 6**. If a class is failing
and there is enough val signal to carve a rule (≥5 val rows in the confused
classes), refine. If the signal is too thin, do not refine - say so and stop.

## Step 5 - Refine the spec (loop)

Follow `references/spec-refinement.md`. Each iteration: read the **dev** failures
(`failures.jsonl`), make **at most 3 edits**, then re-label dev + val with a new
`RUN_ID` and read both jobs' scores (Steps 2-3). Keep the spec with the best
**val** `HeldOutAccuracy` seen, not the last one tried. Loop until the val gate is
met, val stops improving, or you hit the iteration cap (default 4). Then continue.

**Spec file naming.** Write each iteration's spec to its own file under `work/`, in
the data-prep skills' `iter_{N}` convention: the initial/bare spec is
`<proj>/work/labeling_spec_iter_0.md`, each refined candidate `<proj>/work/labeling_spec_iter_1.md`,
`<proj>/work/labeling_spec_iter_2.md`, … Record each in `<proj>/scores.json` as its row's `spec`
path, so the select cell and the report name the exact file.
`spec_select.iter_spec_name(n)` (the SDK's `operators.spec.select` module) produces these names (multi-column:
`<field>_labeling_spec_iter_{n}.md`).

**`<proj>/scores.json` shape.** The trajectory key is `iters` (not `iterations`);
the select cell hard-fails on any other key rather than silently shipping the
initial spec. `initial` is `iter_0`; each refined candidate is one entry in `iters`,
which may be empty for an intentional no-iteration run. Add an optional per-type/per-class `breakdown` map to each row
to enable the `--per-type-tol` floor (NER / many-class). Minimal correct file:

```json
{"initial": {"spec": "work/labeling_spec_iter_0.md", "val": 0.885, "val_macro_f1": 0.87},
 "iters": [
   {"spec": "work/labeling_spec_iter_1.md", "val": 0.921, "val_macro_f1": 0.90},
   {"spec": "work/labeling_spec_iter_2.md", "val": 0.880, "val_macro_f1": 0.86}]}
```

`val` is the job's `HeldOutAccuracy` on the val split (the steering metric);
`val_macro_f1` is recorded, not steered on.

## Step 6 - Held-out gate (measure, do not select)

The spec was already chosen in Step 5, on **val** alone. Test is never used to
pick between specs; it is scored once, as the reported number.

The reserved test partition is scored **inside the corpus run**: Step 7 passes
`EVAL_DATA = <splits/test.jsonl>`, and the job measures the val-selected spec on test, writes
`HeldOutAccuracy` and the accepted rows' certified bound into its summary, and the
submitter writes `<proj>/held_out_report.json` from it. There is no separate test
job: ship the val-selected spec as `<proj>/labeling_spec.md` and report the number the
corpus run gives, as-is.

- Do **not** re-pick initial vs refined based on test. That leaks test into
  selection and biases the reported number; test is reserved so nothing you tuned
  ever saw it.
- If test comes in far below the val score that selected the spec (beyond split
  noise, > ~0.10 macro-F1), the refinement likely over-fit val. Surface it as a
  **review flag** (`spec_select.heldout_review_flag`) in the report for a human
  to judge - do **not** silently swap specs. Over-fit protection belongs on the val
  side (rotate val folds with `code_templates/seed_folds.py` Cell 2), not on test.

`code_templates/score_and_select.py` Cell 3 (`select_spec`) picks which iter ships (on val) and records its basename in the
decision as `shipped_spec_file` (e.g. `labeling_spec_iter_1.md`):

| Placeholder | Value |
|---|---|
| `[SCORES]` | `<proj>/scores.json` |
| `[DECISION_OUT]` | `<proj>/decision.json` |
| `[PROJECT_DIR]` | `<proj>` |
| `[PER_TYPE_TOL]` | the per-type floor, when the rows carry a `breakdown` (NER / many-class); else `None` |
| `[SKILL_ROOT]` | the active `aws-ai-ml` skill root |

`MIN_GAIN` stays at its default 0.02 unless the step says otherwise (Step 1b: 0.03). Copy that file to the
final `<proj>/labeling_spec.md` (or `<label-field>_labeling_spec.md` per column), the one spec
the customer reviews; the `<proj>/work/labeling_spec_iter_*.md` files stay as the record of
each round.

After `adopt-job` (the in-job search), do not rerun the select cell: run
`code_templates/adopt_pick.py` with `[ACTION]` `ship`, `[PROJECT_DIR]` `<proj>` and `[OUT]`
`<proj>/labeling_spec.md`, which refuses a spec that is not the approved bytes.

## Step 7 - Apply to the full corpus with confidence

Hand off to `references/apply-and-confidence.md`: the **corpus run** is one labeling
job over the whole corpus with the hardened spec, the jury, the reserved test split
as gold and the accuracy target. The job labels every row, votes the jury, scores
the test rows, picks the confidence cutoff that certifies the target on the
auto-accepted rows, pins the spot-check, routes the rest to review, and registers two
DataSets: the labels (`DATASET_NAME`) and the review set (`REVIEW_DATASET_NAME`).

Run `code_templates/labeling_round.py` (all its cells; submit, then end the turn and
collect it later, as in Step 2) with the Step 2 settings and these
changes; `<rest>` is `S3_PREFIX`, `ROLE_ARN`, `RUN_ID` as in Step 2, plus the same
`DEMOS` / `DEMOS_PER_CLASS` as Step 2 when demos are in use, and `GRADERS`
(`GRADERS = <id>[,<id>]`) for summarization.

| Placeholder | Value |
|---|---|
| `[SPEC]` | `<proj>/labeling_spec.md` |
| `[STAGE]` | `corpus` |
| `[INPUT_DATA]` | the corpus: `corpus/corpus.jsonl`, `corpus/corpus.ref.json`, `s3://` or ARN |
| `[EVAL_DATA]` | `<splits/test.jsonl>` |
| `[TARGET]` | `<target>` |
| `[OUT]` | `<proj>/labeled_dataset.json` |
| `[DATASET_NAME]` | `<name>` |
| `[REVIEW_DATASET_NAME]` | `<name>-review` |
| `[GENERATION_MODEL_ID]` | `<id>` |
| `[JURY_MODELS]` | `<id1>,<id2>[,<id3>...]` |
| `[TEXT_FIELDS]` | `<fields>` |
| `[GRADERS]` | summarization only: `<id>[,<id>]`, 1 to 3 grader model ids, none of them the labeling model; else `None` |
| `[GOLDEN_REVIEW]` | the `golden_review.py` manifest of a reviewed `EVAL_DATA` (`references/label-review.md`); else `None` |
| `[CONFIDENCE_METHOD]` | `stated` or `verbalized` (classification) only when the user chose it (`references/offer-options.md`); else `None` (agreement) |
| `[CONFIDENCE_ESTIMATOR]`, `[JUDGE_MODELS]` | `judge` or `panel`, and `<id>[,<id>]` (the judges; none = the labeling model), when chosen; else `None` |
| `[CONFIDENCE_RECALIBRATION]`, `[RECALIBRATION_FIT]` | `platt` and `<splits/val.jsonl>`, with `verbalized` only (`references/apply-and-confidence.md`); else `None` |
| `[HUB_NAME]` | `OutputDataConfig.HubName`: `None` for the account's AI Registry hub; a hub name only when the user named another hub |

`EVAL_DATA` is the whole `<proj>/splits/test.jsonl`: with a frozen split the run refuses a gold
file that leaves out a test row, except the reviewed copy of Golden rows with
`GOLDEN_REVIEW` (`references/label-review.md`, optional).

The labeled corpus stays behind the API: the submitter never downloads the job's
`labels.jsonl` (it stays at the job's S3 output and in the labeled DataSet), nor the
review rows (human-in-the-loop reads them by the review DataSet ARN). It writes
`labeled_dataset.json` (the deliverable record), `labeling_summary.json` (the job's
certificate), `held_out_report.json`, `job_report.html` and `review.model_output.jsonl`
(the model's answers on the review set, which the fold reads, Step 7b); fields:
`references/input-output-contract.md`, Outputs. Downstream steps take `dataset_arn`,
and people's corrections reach the labels as a dataset-transformation overlay (Step
7b). Tell the user the held-out accuracy (`HeldOutAccuracy`
and its lower bound), the certificate (`Status`, the accepted rows' bound against
the target, the coverage `RowsAccepted / RowsLabeled`), how many rows went to review
(`RowsRouted` plus `SpotCheckRows`: a spot-check row is an accepted row, so
`RowsRouted` does not count it), and the two DataSet ARNs (`dataset_arn`, `review_dataset_arn`).

The corpus job registers `DATASET_NAME` and `REVIEW_DATASET_NAME` itself, and Hub
adds a version to a name that exists. So before CreateJob the submitter stops when
either name is taken (nothing uploaded or submitted): ask the user whether to pick
another name or add a version on purpose, and only then re-run with `APPEND`. ⏸

The job scores each test row against the corpus row with the same id when the test
row's text fields are that row's (whitespace aside). A test row whose id is not a
corpus id (a seed the customer labeled outside this corpus), or whose id is a corpus
id but whose text is another row's, is labeled by the job too, from its text fields,
so it can be scored, and is then dropped: it is not in the labeled DataSet, the review
set or the row counts, the corpus row with that id keeps the model's label, and
`held_out_report.json` counts it as `eval_rows_labeled_for_scoring`. Those rows cost
their share of the jury's calls, so put them in the HARD RULE #2 cost. The job fails
when they and the corpus pass 50,000 rows, and a test row that is not a corpus row and
lacks a text field is not scored. The HARD RULE #2 summary asks the user whether the
seed's ids are this corpus's ids for the same rows, or ids the corpus does not use: a test row with another corpus row's id and no text field to compare is
scored against that row and ships its gold there. The submitter says so before the run and, after it, names how many
gold rows the job scored when it is fewer than were sent. The certificate is only as
good as the seed's likeness to the corpus: a seed drawn from another mix of rows
certifies a number measured on that mix.

A test row with no `id` is sent as `seed-<position>`, never as its position: a corpus
row with no id is its position in the job, so a gold row numbered the same way and
lacking a text field would be scored against an unrelated corpus row and ship its gold
there as a person's label. When those rows are also corpus rows (one file with labeled
and unlabeled rows), the file goes to the job whole, as below.
When the corpus's ids are integers, a test row's id written as a whole-number float
(`300.0`, as a pandas export writes it) is sent as `300`, so it joins its corpus row.
On a classification run, the submitter compares the local gold's labels with
`LABEL_SET` before anything is uploaded: above 5% of the gold rows outside it (for
example `CARD_ARRIVAL` for `card_arrival`), it refuses and names the values, because the
job compares labels exactly and every such row would score wrong; below that it warns.
Gold given as an `s3://` object or a DataSet ARN goes to the job unread, so the
submitter cannot drop demo rows from it, warn under 50 gold rows, name rows with no
text field or id, or check labels against the label set; it says so. To get those
checks, download the (seed-sized) gold with
the `hub_ops` `resolve` action (`[REF]` it, `[OUT]` `<proj>/work/gold.jsonl`, `DOWNLOAD = True`) and
pass the file.

**One file with labeled and unlabeled rows.** That file is the corpus: it is never
downloaded, filtered or rewritten on the client (Non-negotiables). Pass the same `s3://`
URI as both `INPUT_DATA` and `EVAL_DATA`, with `LABEL_FIELD` the field that holds the
people's labels. The job labels every row, scores the rows that carry a gold value
against their own labels, and ships those rows with the people's labels; the labeling
round prints a NOTE that says so, and the job's summary warns that the unlabeled rows
"have no <label field> value and were not scored", which is expected. A file on the user's own disk is first uploaded unread
(`aws s3 cp <file> <S3_PREFIX>input/<file name>`) and passed by that URI.

Each row needs an `id` written in the file, so a gold row joins its own corpus row. When
the inspect cell reports no `id` field, ask the user to choose one of these, and say
what each costs:

- The user adds an `id` to every row and uploads the file again (free).
- A `dataset-transformation` job writes `id` = the row's position into a copy of the
  file in the service (billed; the client reads no row): run it on a `hub_ops` `dt-view`
  of the file, then pass its output as both `INPUT_DATA` and `EVAL_DATA`.
- The file runs as it is: the gold rows are labeled again under job ids and scored as
  rows of their own, and the people's labels do not ship on them.

On a cold start, the corpus run labels the sample rows too. Write the people's labels
as the overlay for them as soon as the run has finished, before anything below
(`references/cold-start.md`, Step D).

The target (`TARGET`, 0.85 to 0.99) is the share of auto-accepted rows the job
certifies correct (a one-sided 95% Clopper-Pearson bound on the test rows it
accepted). With fewer than 50 gold rows the job certifies nothing
(`NotCertified`, `insufficient_eval_rows`) and routes every row; a target of 0.95
with under 100 gold rows gives a wide bound (the submitter warns). Omit `TARGET`
only for labels with no accuracy promise: the job then routes on the fixed 0.85 bar
and reports `NotCertified`. The run report reads the cutoff the job used from
`labeling_summary.json` (`AcceptThreshold`).

The jury (`JURY_MODELS`, 2 to 5 models, the generation model first) votes on the
discrete tasks (classification, ner, qa); its confidence is the agreement. Ordinal
and llm_judge run one model the job resamples, and summarization one model graded by
`GRADERS`; these three ship without an accuracy promise (`overview.md`, Limits), so
send them no `TARGET`. For ordinal STRING-tier gold, score with the scoring cell's
`--label-map` (or `SPEC`), as `references/task-types.md` says.

## Steps 7a to 9 - review, fold, report, registration and delivery

These steps are their own pages, so a refine-only session does not load them:

- **Step 7a** (offer the review of the routed rows, hand the review set to human-in-the-loop) and
  **Step 7b** (fold every returned export, required and checked): `references/full-loop-review.md`.
  A corpus run that routed rows goes there before Step 8.
- **Step 8** (the run report), **Step 8b** (register the labeled dataset in the Hub), **Step 8c**
  (the reproducible delivery artifact) and **Step 9** (planning run-report integration):
  `references/full-loop-delivery.md`. Every run ends with Step 8.

Then Step 10 and Step 11 below.

## Step 10 - Verify the deliverables before saying "done"

The run is finished only when the artifacts actually exist. Before you tell the
user the labeling is complete, confirm on disk:

- `<proj>/labeled_dataset.json` exists and names `dataset_arn` (the deliverable: the
  labeled DataSet; its rows stay behind the API).
- `<proj>/labeling_summary.json` exists (the job's certificate), and
  `<proj>/held_out_report.json` when the corpus run had gold.
- the corpus run's `dataset_arn` (and `review_dataset_arn` when it routed) are in the
  run's summary.

If a file is missing, a labeling round did not complete: go back and
run it (`overview.md`, Non-negotiables, "Never report the run done").

## Step 11 - Offer next steps

After the deliverables are verified (and registered, if the user said yes), tell
the user the labeled DataSet ARN and offer three next steps: convert the labels to a
training format, evaluate the dataset's quality, or fine-tune on it.

⏸ Wait for the user's choice, then:

- **Convert to a training format:** activate **dataset-transformation**
  with the DataSet ARN and the target training format as context. Its first input is
  a `hub_ops` `dt-view` of `<dataset_arn>`, not the labeled DataSet (the output would
  land as its next version, and the job cannot read the labeling job's output folder),
  and the conversion is a CodeGen job: `SchemaConversion` refuses a `Custom` DataSet
  ("Cannot convert from Custom"). Register the output under a new name with
  the `hub_ops` `register-output` action (`[FROM_ARN]` the `OutputDatasetArns` entry, `[NAME]` `<name>`),
  then offer the hand-off cleanup (Step 8b) for the view it left.
- **Evaluate dataset quality:** activate **dataset-quality** with the
  DataSet ARN; pass `held_out_report.json` as the measured-accuracy signal
  when the held-out gate ran (omit it, and say so, when scoring was skipped).
- **Fine-tune:** activate **finetuning** with the DataSet ARN
  as the training data.

If the job registered no DataSet, offer the same choices with the job's labels S3 URI
(`labels_s3_uri` in `labeled_dataset.json`) in place of the ARN.

<!-- markdownlint-disable-file MD028 MD033 -->
