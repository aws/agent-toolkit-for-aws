# Auto-Labeling

Turn an unlabeled corpus + a short labeling spec into trustworthy labels. The
skill refines the spec against held-out data (so accuracy is *measured*, not
asserted) and tags every prediction with a confidence score.

This overview is a **router**. Read the reference workflow for the path the
user needs, then follow it. Do not label inline from general knowledge - the
reference workflows encode the guardrails that make the numbers hold.

## What it labels

Text, in six task types. `references/task-types.md` has the `TASK` table: each type's flag value, output, scorer and per-row confidence.

| Task                 | Example                                                                                         |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| Classification       | Sort each support ticket into refund, shipping, account or other.                               |
| Named entities (NER) | Tag every person, company and place named in a news article.                                    |
| Extractive QA        | Copy the answer to each question from its passage, or leave it empty when the passage has none. |
| Summarization        | Write a one-sentence summary of each news article.                                              |
| Ratings              | Rate each product review from 1 to 5 stars.                                                     |
| LLM-as-judge         | Score how faithful each generated answer is to its source document, on a 1 to 5 rubric.         |

## Limits

Tell the user these five limits before you ask anything about their data, because each one can rule the job out or change what they get:

- **Text only.** Rows are labeled from their text fields. Labeling images is under Out of Scope below.
- **One label per row.** A classification row gets one label from the label set; several labels per row is under Out of Scope below. Separate label columns, such as topic and sentiment, are fine (What the skill produces).
- **Up to 50,000 rows per job.** The labeling job refuses a bigger corpus at load, before any model call. The labeling round estimates the row count from the first row and the file size and warns over the cap, counting a local `EVAL_DATA` file's gold rows that are not corpus rows (they are labeled too, to score them). A bigger dataset is sampled down, or split into files of at most 50,000 rows, each labeled as its own project with its own accuracy promise.
- **Some task types get no accuracy promise.**
  - Ratings (`ordinal`) get none.
  - LLM-as-judge scores (`llm_judge`) get none.
  - Summaries (`summarization`) get none.
  - For these, report the held-out score instead.
- **An accuracy promise needs human-labeled rows.**
  - With none, people first label a small random sample of the corpus (`references/cold-start.md`).
  - **What a promise is.** A certified lower bound on the accuracy of the auto-accepted rows, which the labeling job computes on the held-out gold (`references/apply-and-confidence.md`, Calibration).

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Labeling images or other non-text inputs, including rows whose label depends on an image
- Several labels per row (multi-label classification)

## SDK environment prerequisite

Before any template or script runs, including the first-row read of the inputs, check whether
`sdk-getting-started` has already run in this session (region and role are in conversation
context). If it has not, activate `sdk-getting-started` first and complete it. Every template and
script in this capability imports the SDK, so run them with the Python `sdk-getting-started`
installed into; a failed import means the SDK is not installed, not that it is unavailable in
this environment ("the SDK is not available here" is a misdiagnosis): run `sdk-getting-started`'s
install to completion rather than reporting a capability limitation or hand-rolling a partial
`pip install`.

## Non-negotiables

These hold for every labeling request, including a one-liner, whether or not a workflow reference has been loaded:

- **The corpus never comes to the client.** The only corpus read is its first row (the
  inspect cell's one ranged read: field names and a size estimate). Never download, copy,
  stream, count, sample, filter or open the corpus, or a file that holds it (one file with
  labeled and unlabeled rows is the corpus): no `aws s3 cp`, no `aws s3 sync`, no
  `aws s3api get-object` without `--range`, no `aws s3api select-object-content`, no
  `hub_ops` `resolve` with `DOWNLOAD = True` on it, not even "to check" and then delete
  the copy. Never search the disk (for example `find /`) for a copy of the user's data;
  use the inputs the user named. The row count is the inspect cell's `estimated_rows`,
  then the job's summary. Whether the seed's rows are corpus rows is the user's to answer
  (the Step 7 HARD RULE #2 summary asks), and `eval_rows_labeled_for_scoring` reports it
  after the run. The seed (the gold) is small and client-readable, and so are the review
  rows a person reviews.
- **The task detector runs first** (`code_templates/inspect_inputs.py` Cell 3), and each
  task runs through its own `TASK` (the Binding routing rule below).
- **Which spec ships is decided by score, not by eye.** Ship the spec with the
  highest val score (the val job's `HeldOutAccuracy`) across ALL refinement
  iterations (best-iter rollback, NOT the last one tried). If that spec does not
  beat the INITIAL spec on val by `MIN_GAIN`, ship the initial spec (val
  do-no-harm floor; selection is on val, never the reserved test split).
  The select cell (`code_templates/score_and_select.py` Cell 3) makes this call. Never answer "which spec do I get?" with
  "the last iteration" or "whichever looks best".
- **You author the full five-part spec, not a partial one.** With no spec, draft
  one WITH the user and state all five parts: Input Data; Labelled Seed; Label Set
  - one-line definitions (Score Levels instead, for `llm_judge` and a numeric
  `ordinal` scale); Labelling Rules; and the **Output Schema**
  (`references/labeling-spec-template.md`, Output Schema). Naming the label set
  alone is not a spec.
- **Never report the run done without the artifacts on disk.** The run is complete
  only when `labeled_dataset.json` exists and names the labeled DataSet ARN (the
  corpus run's deliverable; its labels stay behind the API) and, if a held-out eval
  ran, `held_out_report.json`. Before saying the labeling finished, confirm a
  labeling round this run wrote those files. Do NOT say "the labeled
  dataset is registered" / "the report is ready" unless you produced them: claiming
  success on artifacts you did not create is an error, for every `TASK`.
  The run also ends with the run report (`code_templates/run_report.py`, full-loop Step 8, required for every task).
  Keep the project directory and its artifacts where `directory-management` puts
  it, so the user and later steps can find them.
- **No labeled seed → you MUST build one first, unless the customer opts out.** When the corpus has no labeled data / no seed / no examples, you MUST follow the cold-start playbook (`references/cold-start.md`): people label a random sample of the corpus, and that sample seeds the normal split → refine → gate loop, which still gates the at-scale corpus run on explicit user approval. If the customer will not label that sample, the only other path is the playbook's opt-out (`references/cold-start.md`, Opt-out), on their explicit yes to labels with no accuracy promise. You MUST NOT label the corpus from general knowledge or any off-path shortcut: labeling without a seed and without that yes is an error of the same class as relabeling off the labeling job.
- **Labeling job unavailable (the service is down or refuses the job) → you MUST HALT; never inline-relabel.**
  Labeling MUST route through the labeling round (`code_templates/labeling_round.py`), which submits the labeling
  job (`DataPreparer`). If that job cannot run (the account cannot run labeling jobs, job
  rejected, V3 SDK/role missing, or AccessDenied from SageMaker, S3 or Bedrock while you
  check the account), you MUST halt and tell the user plainly (e.g. "this account can't
  run the labeling job, so I can't label here; fix the account's access or use an account that can run
  labeling jobs"). You MUST NOT write a labeling script or inline-label the corpus from
  general knowledge with a direct Bedrock/Converse call or any off-path shortcut.
  Recognizing the job cannot run and then labeling inline is an error: it ships
  un-scored, un-juried labels, the highest-risk failure mode.
- **Flagged rows are never settled in the chat.** The corpus job routes them: on
  review, fill the hand-off spec with `hil_handoff.py` and hand the job's review set
  to human-in-the-loop (full-loop Step 7a).
- **Every returned review export is folded and checked** (`fold_review.py hil`,
  then `fold_review.py check` until it exits 0; full-loop Step 7b) before the
  report.

## Principles

1. **Measure, don't assert.** Never report a quality number that was not
   produced by scoring predictions against a held-out split the labeler did not
   see. If the user declines a held-out eval (e.g. to save cost), comply, but say
   plainly there is then NO measured accuracy, and STILL keep confidence tagging on
   (Principle 1b). Never present un-evaluated labels as trustworthy.
1b. **Confidence tagging is the floor - keep it even under "just do it" pressure.**
   On a corpus run of a vote task (`classification`, `ner`, `qa`) with
   `REVIEW_DATASET_NAME`, `JURY_MODELS` makes the labeling job run a cross-model
   jury (voted inside the job with `Routing`), so each row gets a confidence
   (`confidence_score`, with the jurors' `ballots`) and low-confidence rows route to
   a human; `ordinal` and `llm_judge` get their confidence from resampling one model
   instead (`references/apply-and-confidence.md`). The full loop runs the jury by
   default; a vote-task corpus run without `JURY_MODELS` emits no confidence, and a
   refine round (no `REVIEW_DATASET_NAME`) runs one model and routes nothing. Even under "just label it cheap / skip eval
   / just do it" pressure you MUST keep `JURY_MODELS` on. You may skip the
   held-out gate to save cost, but then tell the user that scoring is skipped and
   that low-confidence rows are still flagged for a spot-check. Dropping BOTH scoring and
   confidence and calling the result done is an error. The opt-in confidence options
   (`references/apply-and-confidence.md`) give a single-model run a confidence; they
   replace the jury only when the user accepts them at the approval pause.
2. **Confirm before the expensive step - HARD STOP.** Before the FIRST command
   that labels at scale (any labeling round), you MUST stop,
   summarize what `references/full-loop.md` HARD RULE #2 lists (on a standalone
   apply run too), and get an explicit "yes" from the user. Do not proceed on
   assumed approval; launching a labeling run without a fresh user yes is an error.
3. **Run each `scripts/` command as its own step; never batch the loop.** Do NOT
   write a wrapper script (e.g. `auto_label_workflow.py`) that chains the loop and
   runs it in one shot - that skips the Principle 2 gate. The one exception is a
   script the user asks for after the Principle 2 yes (`references/full-loop.md`,
   HARD RULE #4).

## Prerequisites

- **Dependencies.** The non-LLM scripts (scoring, routing, folds) make no model call;
  they run on the V3 SDK's `sagemaker.ai_registry.data_preparer.operators`.
  **Exception:** the cluster-aware split (`cluster_split.py`, owned by
  `dataset-transformation`) needs `sentence-transformers` + `scikit-learn`. Without
  them the split falls back to a plain label-stratified split, which leaks
  semantically similar rows across partitions and inflates the held-out number (the
  script records the fallback in its manifest and warns on stderr). Labeling, the
  confidence jury, the held-out score and the certificate run inside **one
  labeling job** (the SageMaker `DataPreparer` job service, V3 SDK); the one
  single-invoke LLM call, spec induction, goes through boto3
  `bedrock-runtime` inside the SDK operator `sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec.induce`. Requires: the V3 SDK, an
  account that can run labeling jobs, a writable S3 prefix, and an IAM role that trusts
  `sagemaker.amazonaws.com` for the job, with Bedrock access. Dependencies: the
  `sagemaker` build that ships `sagemaker.ai_registry.data_preparer.auto_labeling.operators`
  (`sdk-getting-started` installs it) and
  `sagemaker>=3.7.0` for telemetry attribution. See
  `references/sdg-indexed-backend.md` for the backend contract and
  `references/task-types.md` for per-task dependency notes.
- The SDK environment is verified (region, execution role). This is a hard
  prerequisite: the SDK environment prerequisite section applies (`references/full-loop.md`
  Step 0.1), and every command runs with the Python `sdk-getting-started` installed
  into. Never fall back to direct
  Bedrock or labeling from general knowledge when the SDK is missing.
- An unlabeled corpus as JSONL (one record per line), within the row limit in
  Limits above. **Input modes:** `INPUT_DATA` takes a local path, an `s3://` URI, or a
  `corpus.ref.json` pointer. A remote corpus (`s3://` / `DataSet` ARN) resolved with
  the `hub_ops` `resolve` action (pointer mode, the default) stays in the customer's bucket and
  is labeled in place, with no download or re-upload; a local corpus is uploaded to
  the skill's prefix byte for byte, and only its first row is read on the client.
- A one-page labeling spec (Markdown). This skill owns the spec end to end: if the
  user has none, draft it with them (`references/spec-authoring.md`, template +
  sample included); you MUST state all five parts to the user, not just the label
  set (Non-negotiables above). The **decision rules** are the accuracy lever: if the spec has no/weak
  rules and a labeled seed exists, induce them from the seed
  (`references/spec-induction.md`), then the refine loop hardens them.
- Ground-truth intake (verifying user GT, or sample-label-confirm for <100 GT)
  is handled upstream. This skill consumes whatever labeled seed exists; see
  `references/input-output-contract.md`.

## Routing

Determine intent, then load exactly one workflow reference:

| User intent | Workflow | Reference |
|---|---|---|
| "label this corpus end-to-end" / "I have unlabeled data + a few examples" | **Full loop** (default) | `references/full-loop.md` |
| "I have no labeled data / no examples at all" / no seed | Cold start - **you MUST bootstrap a seed** (people label a random sample), then run the loop, or take the opt-out (no accuracy promise) when the customer will not label it; **never** label the corpus from general knowledge | `references/cold-start.md` |
| "refine my spec against this dev set" / "my labels are inconsistent" | Spec refinement only | `references/spec-refinement.md` |
| "label the rest with this frozen spec" / "apply this spec" | Apply + confidence | `references/apply-and-confidence.md` |
| "when should refinement run?" / planning a labeling step | Routing rules | `references/refinement-routing.md` |
| "are my labels right?" / "find label errors" | Label review | `references/label-review.md` |

If the user is ambiguous, default to the **full loop** - it subsumes the others
(refine → gate → apply) and is the safe choice.

## What the skill produces

Every run emits, under the project directory, `labeling_spec.md` (the hardened spec the customer
reviews, filled from `references/labeling-spec-template.md`; one `<label-field>_labeling_spec.md`
per label column), `held_out_report.json`, the corpus job's `labeling_summary.json`, the
deliverable record `labeled_dataset.json` (the labeled DataSet ARN, the review DataSet ARN and the
S3 URI of the job's labels; the rows stay behind the API and are read by ARN), the review set's
side file `review.model_output.jsonl` and `hil_handoff.json`, the labeling run's run-log entries,
the per-iteration specs under `work/` (`labeling_spec_iter_{N}.md`), `report.html` and a
reproducible delivery artifact (`scripts/emit_delivery.py`). **The headline output is the labeled
DataSet**; with several label columns the DEFAULT deliverable is the MERGED dataset (one row per
source record, every label column joined on the record id), which you MUST offer (full-loop.md
Step 8b), keeping the per-column datasets available too. Each output's shape and consumer: `references/input-output-contract.md`, Outputs.

## Working directory layout

The run lays its files out under the project directory defined by the
`directory-management` reference. Two slots hold the data a run operates on: the
resolved source **`corpus/`** (`corpus.jsonl` for a local corpus, or a
`corpus.ref.json` pointer when a remote `s3://` / ARN corpus was resolved in
pointer mode, the default, and left in its bucket) and its **`splits/`** (dev/val/test
partitions from `dataset-transformation`'s `cluster_split.py`). The delivery
artifact lands under `scripts/` (script mode) or `notebooks/` (notebook mode).
These fixed slots let a later reader re-run the labeling from what is on disk.

## Backend

Labeling runs through the **synthetic data generation service (`DataPreparer`) in labeling mode**:
one labeling job per stage, one input row → one output label, input order preserved, and the
output joins back to the input by id; the service runs its own labeling program, so the skill
submits no code. The corpus run and the dev/val stages are `code_templates/labeling_round.py` with
its settings (`references/full-loop.md` Step 2 and Step 7 have the tables); every model id must be
one the service accepts **verbatim** (it matches exact ids, not families, and its refusal at
`CreateJob` names the allowed list). The contract, limits and re-attach rule:
`references/sdg-indexed-backend.md`.

**If the labeling job cannot run, STOP:** the Non-negotiables HALT bullet above applies.
**Endpoint troubleshooting:** `references/troubleshooting.md`.

## Task types (TASK)

**The loop is fixed across every task type; only the task changes.** The task is auto-detected
(`code_templates/inspect_inputs.py` Cell 3, run first; an `ask`-tier pick with confidence < 0.5
fails closed), `TASK` overrides, and classification is the outcome only when the spec or data
signal it. **Binding routing rule:** every task MUST run through its own `TASK` value; you MUST NOT
hand-roll a bespoke scoring script or force a non-default shape into `classification`
(summaries → `TASK = summarization`, graded by `GRADERS`; ratings → `TASK = ordinal`, string
tiers through `LABEL_MAP`). The cross-model jury does NOT apply to `summarization`, `ordinal` or
`llm_judge`. The task table, each task's conventions and the detection contract:
`references/task-types.md` and `references/full-loop.md` Step 0.5.

## The accuracy lever: induce + refine the rules

On real labeling tasks the biggest lever is the **decision rules** in the spec.
When the spec is generic, induce rules from the labeled seed
(`code_templates/induce_spec.py`), then harden them in the refinement loop. Induction is
A/B-gated on your own held-out seed, so it ships only when it beats the provided
spec on your data. Full mechanics: `references/spec-induction.md`.

For `llm_judge` the default spec is an **anchored rubric** (`references/labeling-spec-template.md`, Score Levels), and `induce_spec.py` with `TASK = "llm_judge"` writes it. Which judge model to run: `references/task-types.md`, **Judge tasks**.

## Picking the lever: demos or induced rules (measure, don't guess)

No single lever wins on every dataset: balanced demos help many-class intent, demos
from near-miss dev rows help hard binaries, and rule induction helps recall-collapse
cases. Measure instead of assuming: run the candidate on a dev job, score val, and
keep it only when it beats the base spec by `MIN_GAIN` (the select cell, the
refinement loop's do-no-harm floor). The candidates, all sourced ONLY from the
labeled seed (never val/test, so still fair few-shot):

- `none` (base) - provided spec, zero demos.
- `demos_fixed` - 1-2 balanced demos/class (`DEMOS = splits/dev.jsonl
  DEMOS_PER_CLASS N`; `code_templates/seed_folds.py` Cell 3 previews them); the first demo
  per class captures most of the demo gain.
- `induce` - decision rules induced from seed errors (`induce_spec.py`); the
  biggest lever on rule-heavy policy tasks.

A lever ships only if it earns its place on val, so trying one can only help.
Full guidance: `references/demo-modes.md`.

## Confidence

For the tasks with a discrete answer (`classification`, `ner`, `qa`), the corpus
job runs a **jury**: two to five distinct Bedrock models vote per row (per span for
`ner`), and the agreement fraction is the confidence (on `classification`,
`CONFIDENCE_METHOD = stated` scores rows by the jurors' stated confidence instead).
The job then picks the accept cutoff that certifies the target on the held-out gold
and routes the remainder to a human reviewer. Details and the model lineup:
`references/apply-and-confidence.md`. For the numeric and free-text tasks, see the
jury note under Task types above.

## Critical guardrails (do NOT relax)

1. **Refiner contract** - at most 3 spec edits per iteration; protect any class
   already at or above the gate; "make no change" is a valid iteration.
2. **No ground truth in the prediction path** - `gt_label` is carried for
   scoring only; the labeler must never read it when predicting.

## References

- `references/input-output-contract.md` - exact input/output shapes.
- `references/full-loop.md` - the end-to-end workflow (default); Steps 7a-7b in `references/full-loop-review.md`, Steps 8-9 in `references/full-loop-delivery.md`.
- `references/cold-start.md` - the no-labeled-seed path.
- `references/spec-refinement.md` - the refinement loop in isolation.
- `references/approval-summary.md` - the HARD RULE #2 checklist: what the approval pause shows.
- `references/offer-options.md` - when to offer each opt-in option at the approval pause, and what to show.
- `references/refinement-routing.md` - when refinement should fire vs. accept.
- `references/label-review.md` - label review and the user's decisions.
- `references/apply-and-confidence.md` - frozen-spec labeling + jury confidence.
- `references/spec-authoring.md` - draft the label set + definitions in-skill.
- `references/labeling-spec-template.md` - the spec template to fill.
- `references/sample-labeling-spec-classification.md` - worked example spec (multi-class intent).
- `references/spec-induction.md` - induce the decision rules from the labeled seed.
- `references/sdg-indexed-backend.md` - the indexed (1-to-1) generator contract.
- `references/taxonomy-guidance.md` - when to merge classes before running.
- `references/demo-modes.md` - few-shot config: none / fixed, and how many demos.
- `references/task-types.md` - the full `TASK` set.
- `references/troubleshooting.md` - run-time checks, read on demand.
- `code_templates/` - the deterministic steps the agent runs over the V3 SDK's
  auto-labeling operators (`sagemaker.ai_registry.data_preparer.auto_labeling.operators`),
  one template per step, filled from its placeholder table (`references/full-loop.md`):
  - `inspect_inputs.py` - the first row of a local, `s3://` or DataSet input (Cell 2);
    detect `TASK` from the spec + the labeled seed (Cell 3); upfront separability
    pre-check for a spec with a Label Set (Cell 4).
  - `seed_folds.py` - K stratified val folds for rotation during refinement (Cell 2);
    preview the fixed few-shot demos the job will draw from the dev split (Cell 3).
  - `induce_spec.py` - draft/refine the one-page spec from the seed (a Bedrock reflection
    model); the anchored rubric for `llm_judge` / `ordinal`.
  - `labeling_round.py` - submit one labeling job per stage, and read it back.
  - `score_and_select.py` - re-score a seed-sized local predictions file against gold,
    every metric, no model call (Cell 2; the job scores its own gold: this is for files
    it did not score); best-iter rollback + val do-no-harm floor, which spec ships (Cell 3).
  - `hub_ops.py` - the Hub doors: resolve an input without downloading it, register the
    overlay rows, the dataset transformation view, output and promote, and the scratch cleanup.
  - `split_freeze.py` - freeze the Step 1 split once, check it, accept dev and val edits.
  - `seed_bootstrap.py` - the cold-start sample, the merge onto a local file, the overlay.
  - `adopt_pick.py` - adopt the in-job search's pick after the user's recorded yes; ship it.
  - `run_report.py` - roll the run artifacts into report.html and report.md.
- `scripts/` - what has no SDK home: the human-in-the-loop fold and hand-off, the label
  review, and the delivery artifact, run as commands (the router's Packaged scripts rule
  applies). The helpers:
  - `cluster_split.py` - not in this skill's `scripts/`: owned by `dataset-transformation`.
  - `hil_handoff.py` - fill the human-in-the-loop hand-off spec.
  - `io_utils.py` - the human-in-the-loop scripts' glue: the project's run-log writer, the SDK-missing message.
  - `fold_review.py` - `hil`: fold the labels people returned into the seed; `check`: prove the fold.
  - `emit_delivery.py` - emit a reproducible delivery artifact (script or notebook) from the
    labeling-round template and the run's recorded invocation.
  - `review_labels.py` - the label review job (`Config.Review`).
  - `apply_label_decisions.py` - apply the user's review decisions.
  - `golden_review.py` - golden-row review for `GOLDEN_REVIEW`.
