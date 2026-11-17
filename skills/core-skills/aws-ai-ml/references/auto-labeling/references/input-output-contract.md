# Auto-Labeling - Input/Output Contract

Defines what the skill consumes and produces, and how it connects to the other
skills in a plan. The `planning` skill uses this to order auto-labeling
correctly.

## Inputs

| Input | Required | Shape | Source |
|---|---|---|---|
| Unlabeled corpus | yes | JSONL, one record per line; a text field (default `text`) holds the content to classify. Accepted as a **local path, `s3://` URI, or versioned `DataSet` HubContent ARN** (`INPUT_DATA`; a remote corpus stays in its bucket and is labeled in place, Hub doors below). Row limit: `overview.md`, Limits. An `id` is optional (a row without one gets its position as text, `"17"`), but no two rows may share one: the job's gold join, the review set and the fold all key on it. The client reads only the first row of the corpus, so the job checks the ids at load; a local seed split is read whole and its bad ids refused before upload. | the user, synthetic data generation output, or a dataset registered by dataset quality |
| Labeling spec | yes | one-page Markdown describing the task, the label set, and a rule per class | the user, or drafted in-skill when they have none (see `references/spec-authoring.md`) |
| Labeled seed | optional | JSONL with a ground-truth field (default `gt_label`) on a subset of rows. **No seed is fine** - the cold-start path bootstraps one (see below). | ground-truth intake, or bootstrapped in-skill (cold start) |
| Task type (`TASK`) | optional | one of classification / ner / summarization / qa / llm_judge / ordinal; the detector (`code_templates/inspect_inputs.py` Cell 3) suggests it from the labeled seed's ground-truth (`gt_*`) field - its strongest signal (corpus head sample on cold start) - confirmed at the gate | inferred, user-confirmed |
| Execution role + S3 prefix | yes | an account that can run labeling jobs, an execution role trusting `sagemaker.amazonaws.com`, a writable S3 prefix | `sdk-getting-started` / config |

The task types, their limits and each task's prediction and gold fields: `overview.md` (Limits) and `references/task-types.md` (the task table).

### Ground-truth intake (upstream dependency)

This skill does not itself decide whether a user's labels are trustworthy. That
is resolved before it runs, in one of three ways:

- **User brings ground truth** - labels they are confident in. These are
  verified with the user, then passed in as the labeled seed.
- **User has insufficient ground truth (<100 rows)** - people label a random sample of the corpus as on a cold start (`references/cold-start.md`, Steps A to C), and its rows join the user's own rows in the seed. The seed is never built by having someone confirm labels the model gave, because a reviewer who sees the model's label tends to keep it.
- **User has NO seed at all (cold start)** - the skill draws a random sample of the corpus, people label every row of it through human-in-the-loop, and the skill folds the returned labels into the seed. No prior GT-intake step is required; see `references/cold-start.md` and the human-in-the-loop hand-off below.

In each case, the skill consumes the (real or bootstrapped) seed via the task's gold
field (`gt_label` for classification; the per-task fields are listed above). It treats
the gold field as evaluation-only - see the guardrail below.

## Outputs

| Output | Shape | Consumed by |
|---|---|---|
| `labeling_spec.md` | hardened Markdown spec (best-scoring iteration) | the user; downstream fine-tuning as a labeling rubric |
| `held_out_report.json` | the labeling job's score on the gold it was given, in the skill's shape: `primary` / `primary_name` (accuracy, the number the refine loop steers on; `good_rate` for summarization), `accuracy`, `macro_f1` (classification), `lower_bound_95`, `breakdown`, `confusion_pairs`, `counts`, and the job's summary under `job`; the SDK's `operators.job.round.read_round` writes it | the refine loop (val); `dataset-quality` as a quality signal |
| `labeling_summary.json` | the corpus job's certificate and counts (`Status`, `StatusReason`, `AcceptThreshold`, `AcceptedLowerBound95`, `SpotCheckRows`, `RowsLabeled` / `RowsAccepted` / `RowsRouted`, ...; `references/apply-and-confidence.md`, Calibration) | the run report, `hil_handoff.py`, `fold_review.py hil --job-summary` |
| the labeled DataSet (`labeled_dataset.json`: `dataset_arn`, `review_dataset_arn`, the S3 URI of the job's `labels.jsonl`, the job ARN) | one row per input, input order: the original fields + the task's prediction field, `reasoning`, `confidence_score`, the vote fields (`ballots`, also kept as `jury_votes`), `accepted` / `routed`, `provenance`; a row the job got no answer for keeps its id with a null prediction and `_failed`. **The rows stay behind the API and are read by ARN.** After a review, the people's corrections become the DataSet's next version (full-loop Step 7b). | **the headline output**: fine-tuning / DI / model-customization downstream; `dataset-transformation` |
| review set (the review DataSet; on the client only its side file `review.model_output.jsonl`) | every row below the cutoff or `_failed` (`split: low_confidence`) plus the pinned spot-check of the accepted rows (`split: spot_check`), blind: `id`, the input fields, `split`, `_review_reason`; the model's answers in the side file, which only the fold reads. The report takes the counts from the summary (`RowsRouted`, `SpotCheckRows`). | `human-in-the-loop`, by the review DataSet ARN; `fold_review.py hil` |
| the labeling run's entries in `<project-dir>/run-log.jsonl` (written by the labeling round through the shared run-log writer, `../../directory-management/overview.md` § *Run Log*) | one `job` entry per labeling job (`arn`, type, region, named `s3_paths`, best-effort `tokens` / `cost_usd`; a refine round's is `status: scratch`) and one `artifact` entry (`labeling_run: true`) naming them, with the planning run-report contract (`report_s3_paths`, `run_report`) and the run's `invocation`; the SDK's `operators.job.run_log` puts them back together | the run report (`code_templates/run_report.py`), `emit_delivery.py --from-run-log`, the planning skill's report |
| Labeled DataSet ARN | the corpus job's labeled DataSet, registered by the job itself (`DATASET_NAME`), and after a review its next version through the `hub_ops` `promote` action (full-loop Step 7b) | downstream steps, by ARN |

Run-time checks: `references/troubleshooting.md`. Spec-file naming: `references/full-loop.md`, Step 5.

### Planning integration (auto-labeling as a data-producing pre-step)

Under the `planning` skill, auto-labeling is ordered as a **DataGeneration / Labeling step that
PRODUCES the dataset** a later fine-tuning / DI / model-customization step consumes. The labeling
round emits the run-report contract in its run-log `artifact` entry (`report_s3_paths` +
`run_report`), so the planning skill's `report.html` renders the step with the spec, input data,
job metadata and labeled-dataset S3 paths, the mechanism the synthetic-dataset-generation skill
uses. The per-task prediction and gold fields are the task table in `references/task-types.md`;
`reasoning`, `confidence_score` and the `_failed` contract are the same across tasks, and the
held-out report's `primary_name` is `accuracy` for every task scored against gold (`good_rate`
for summarization).

## Hub doors (versioned DataSet in / out)

Beyond local paths and `s3://` URIs, the skill reads and writes **versioned `DataSet` HubContent**,
the handle synthetic data generation output and dataset quality use. The labeling job stays S3 or
ARN in; the Hub work happens at the skill's edges through `code_templates/hub_ops.py` (one `ACTION`
per run; the settings and commands are in its table and in `references/full-loop-delivery.md` Step 8b).
Its optional placeholders: `[HUB_NAME_OVERRIDE]` names a hub other than the account's AI Registry hub
(leave it `None` for the default, as the labeling round does for its output); `[REPORT]` is the run's
`held_out_report.json` and `[PROVENANCE]` the `corpus.jsonl.provenance.json` sidecar `resolve` wrote,
both attached to a `register`.

| Door | `hub_ops` action | In | Out |
|---|---|---|---|
| Input | `resolve` | a local path, `s3://` URI or DataSet ARN (pinned to the referenced version) | `corpus/corpus.jsonl` for a local file; for a remote ref a **`corpus.ref.json` pointer** (`source_s3_uri`, `etag`, `size`, `hub_arn`, `hub_version`) plus `head.jsonl` (the first rows only) and a `.provenance.json` sidecar. The corpus stays in the customer's bucket; `DOWNLOAD = True` is for a client-readable file (a seed, a sample) only, never the corpus. |
| Output, a local labeled file | `register` | the overlay rows of Step 7b or a whole-corpus cold-start sample (`LABELS`), `NAME`, `S3_PREFIX`, optional `REPORT`, `PROVENANCE`, `LABEL_SET` | a new version of the `<name>-labeled` DataSet under a per-run prefix `labeled/<name>/<run-id>/` (never overwriting a prior version's bytes), schema 4.0.0, provenance in `HubContentDescription` |
| Output, the corpus labels | none: the job registers them | `DATASET_NAME`, `REVIEW_DATASET_NAME`; each refine round under the scratch name `<name>-<stage>-<run id>` | the labeled and review DataSets; the corrected labels become the labeled DataSet's next version through `promote` (Step 7b) |
| Cleanup | `scratch` (`DELETE = True`) | the run log's `status: scratch` entries, the `<name>-dt-input` views | the scratch versions deleted after the user's yes; the S3 files stay |

Rules the doors keep: `NAME` comes from the conversation, never a filename. `register`'s **append
guard** compares the existing entry's provenance markers before any upload and aborts on a
lineage mismatch; even on a match, appending is **opt-in** (`APPEND`), so confirm with the user
whether this run is a new version or a separate dataset. ⏸ A Hub failure after the local and S3
outputs complete is a warning (`hub_registered: false`) and never fails the run; an unverifiable
lineage is never appended. The service runs a validation job on every import under the caller's
role (register under a role the service trusts for a clean `ValidationManifest`). IAM, under the
customer's role: `DescribeHubContent` in, `ImportHubContent` out, `CreateHub` on fresh accounts only.

## Hard rule: ground truth never enters the prediction path

`gt_label` is carried through the pipeline for scoring only. The labeler and the
refiner must never read it when producing a prediction.

## Human-in-the-loop hand-off (the seam `planning` orchestrates)

Auto-labeling and `human-in-the-loop` connect through files, not a shared runtime,
so a plan can sequence them deterministically. The round-trip:

1. **The labeling job → the review DataSet.** The corpus job routes: its review
   DataSet (`REVIEW_DATASET_NAME`; the rows stay there and human-in-the-loop reads
   them by ARN) holds every row
   below the cutoff or `_failed` (`split: low_confidence`, `_review_reason: low
   confidence`) and the pinned spot-check of the accepted rows (`split: spot_check`,
   `_review_reason: calibration`), shuffled by the job id so position does not reveal
   a spot-check. Every row is blind: it carries `id`, the input fields, `split` and
   `_review_reason` only, and the model's answer, confidence and vote fields are in
   `review.model_output.jsonl`, one line per review row, `{"id", "pred_field",
   "model_output"}` (with `calib_accepted` on a certified run), which only the fold
   reads. The corpus run downloads the side file only: it carries every review row's
   id and, in `routed` (true for `low_confidence`, false for `spot_check`), its split,
   so the fold needs no review rows. `io_utils.BLIND_FIELD_SET` is the one list
   of model-output fields a review row never shows; human-in-the-loop hides the same
   set (with `split`, `_review_reason` and the job's routing fields:
   `io_utils.REVIEW_HIDDEN_FIELDS`, the `Contract.hidden_fields` of the hand-off).
   Only the job routes: do not re-derive the split from the labels.
2. **auto-labeling → human-in-the-loop: the hand-off spec.** `hil_handoff.py
   --summary labeling_summary.json --spec labeling_spec.md --dataset-name <name>
   --job-arn <job_arn> --review-dataset-arn <arn>` fills human-in-the-loop's input: `ProjectName`,
   `TaskDescription` (the row count, the spot-check named without saying which rows),
   `Recommendation` (the prediction field to write), `QuestionContext` (the label set
   and its one-line definitions), `Data` (`LowConfidence`: the review DataSet ARN, or
   `--review-rows-uri` / `--review-rows` for a local or S3 file; `Dataset`: the
   labeled DataSet ARN) and `Contract`: the hidden fields (`BLIND_FIELD_SET`, the
   prediction field, `split`, `_review_reason`), the export columns (the row's `id`
   unchanged, as `record_id` from a local review; the value under the prediction
   field, `corrected_completion` from a local review; `status` completed or
   skipped), and that `split` is not written back: the fold reads it from the
   original review row. What reviewers see is set in
   `human-in-the-loop/references/local-review-guide.md`, Step 3b.
3. **human-in-the-loop → corrections → auto-labeling folds them back.** Human-in-the-loop returns one row per reviewed record keyed by the same `id`. Human-in-the-loop shows the rows blind, exports the id and the label, and stops there: for an auto-labeling review set it does not apply the corrections (its own edit hand-off). `fold_review.py hil --model-output review.model_output.jsonl --job-summary labeling_summary.json --labels <hitl_export> --out review_seed.jsonl --id-field id [--export-id-field record_id --label-field corrected_completion]` takes each review row's id and split from the side file, joins the export on the id field (as strings) and emits seed rows (rows carry `gt_label`, `_bootstrap: hil`, `provenance` (`spot_checked` for calibration rows, else `human_verified`), `source_export`, and `annotator` when the export names one). Returns marked unsure or skipped (`verdict` or `status`) are not absorbed; the report counts them as `sample_unresolved`. Those rows carry no input text, so they are not appended to the seed; a refinement re-run downloads the review rows (seed-sized) and folds with `--sample review.jsonl --append <seed.jsonl>` (full-loop Step 7b). The corrections then reach the labels through the `seed_bootstrap` `overlay` action (`SEED` `<seed.jsonl>,review_seed.jsonl`) (the id, the person's label, `provenance`, `_labeled_by` and the routing tag; no input field; each `--seed` file read under its own gold column, `--gt-field`, else the task's default, else `labeled_dataset.json`'s `label_field`; when `labeled_dataset.json`'s `eval_rows_labeled_for_scoring` is above 0, the job found seed rows that are not corpus rows, so the overlay keeps only the review fold's rows and reports `seed_rows_left_out`) and one dataset-transformation CodeGen job over [a a `hub_ops` `dt-view` of the labeled DataSet, the overlay DataSet]; the `hub_ops` `promote` action adds its output as the labeled DataSet's next version (`overlay.handoff.json`): the labeled rows are never on the client. The job returns `overlay_matched` (in its CloudWatch log's "Code execution complete" event, not `report.json`), which must equal the overlay row count on the full run. `fold_review.py check --seed review_seed.jsonl --labels overlay.jsonl` proves the overlay carries every reviewer label. The export must carry each row's `id` from the review DataSet through unchanged; a Label Studio export keeps it in each task's `data`, and the fold reads that export as it is (full-loop Step 7b). An export keyed on another name joins zero rows unless `--export-id-field` names it. When a non-empty export joins zero rows, or no export row has the label column (`--gt-field` / `--label-field`), `fold_review hil` exits 2 and writes no seed (an id-space or column mismatch, not an empty review); rows that join with a null label are skipped as unlabeled.
   - Each folded row gets the model's answer back from the side file (an older review file's `_model_output` is put back too). Without the side file there are no review ids to fold, no model answer to confirm or correct, and no spot-check verdict.
   - The fold takes `split` (and so each row's `provenance` and the spot-check verdict) from the job (the side file's `routed`, or the review row with `--sample`), never from the export, so an export that drops or changes `split` folds the same way. With `--job-summary labeling_summary.json` the verdict's basis comes from the job's `Status` (`calibrated` on a certified run, else `bar`), and 7 or more spot-check errors withdraw the certificate.
   - The report's `review_outcome` counts, per review reason, the rows whose human label confirmed the model's label and the rows that corrected it, by the job's row rule (`io_utils.task_correct`) at its defaults. `no_model_answer` counts the rows the model gave no answer for, and `not_scored` the rows whose prediction field no task rule scores (a summary), so each reason's counts add up to `model_output_joined`.

Contract for the planner: the labeling job **produces** the review DataSet (a human-in-the-loop input, described by the spec `hil_handoff.py` fills) and auto-labeling **consumes** the human-in-the-loop export back (via `fold_review hil`). Human-in-the-loop never needs to understand labeling internals. This is the steady-state feedback path. A cold start uses the same seam with its unlabeled sample (the `seed_bootstrap` `sample` action) in place of `review.jsonl` (`references/cold-start.md`).

## Placement in a plan

- Auto-labeling runs **after** ground-truth intake when a confirmed seed exists. **With no seed (cold start)** it runs first and produces the seed itself: it loops with `human-in-the-loop` (the file seam above, with the cold-start sample in place of the review DataSet) to bootstrap one, so a plan places `auto-labeling → human-in-the-loop → auto-labeling` rather than requiring a prior GT step. It authors the labeling spec itself when the user has none (`references/spec-authoring.md`), or consumes the spec the user brings.
- Its labeled DataSet (`dataset_arn`) is a valid **input to `dataset-transformation`**
  (convert to a SageMaker training format) and its `held_out_report.json` is a
  quality signal for `dataset-quality`.
- It does not require `model-selection` or `finetuning-technique` - labeling is
  upstream of the training-format decision.
