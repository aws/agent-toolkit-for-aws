# Full loop, Steps 7a and 7b: the review hand-off and the fold

Loaded from `references/full-loop.md` after the corpus run (Step 7). Step 7a offers the review of
the routed rows to the user and hands the job's review set to human-in-the-loop; Step 7b folds
every returned export into the seed and checks it. Both carry the same ⏸ pauses and rules as
when they were part of `full-loop.md`; the step numbers are unchanged so the plan, the run log and
the other references point at them as before. Then continue with Step 8 in
`references/full-loop-delivery.md`.

## Step 7a - Offer review of the low-confidence tail

Do not silently auto-accept and do not review rows ad hoc in the conversation. The job
already routed: the review DataSet holds every row below the cutoff (`split:
low_confidence`) plus the pinned spot-check of the accepted band (`split: spot_check`;
19 rows for a 0.85 target, 29 for 0.90, 59 for 0.95, the smallest draw whose clean
one-sided Clopper-Pearson bound reaches the target). Present the choice even when no
row fell below the cutoff (the spot-check is still there): review the routed rows
(human annotation for the `RowsRouted` + `SpotCheckRows` rows of the review DataSet;
the counts come from `labeling_summary.json`), or proceed
with auto-accept (every row kept; routed rows stay marked by `routed` and
`confidence_score`).

A cold-start opt-out (`references/cold-start.md`) has no target and no spot-check:
the job routed on the fixed 0.85 bar, and the choice is review of those rows or
auto-accept; when no row fell below the bar there is nothing to review.

⏸ Wait for user. Route based on the choice:

The choice has exactly two answers, each an action, not a conversation: "Review
flagged records" means filling the hand-off spec and handing the review set to
human-in-the-loop; "Proceed with auto-accept" means continuing to Step 8. There is no
third path in which you settle the flagged rows yourself.

- **"Review flagged records"** - you MUST fill the hand-off spec and activate
  **human-in-the-loop** with it (the seam is defined in
  `references/input-output-contract.md`, "Human-in-the-loop hand-off"; the spec's
  fields are human-in-the-loop's input table):

  ```bash
  python scripts/hil_handoff.py --summary <proj>/labeling_summary.json \
      --spec <proj>/labeling_spec.md --dataset-name <name> --job-arn <job_arn> \
      --review-dataset-arn <review_dataset_arn> --labeled-dataset-arn <dataset_arn> \
      --text-fields <fields> --out <proj>/hil_handoff.json
  ```

  It fills `ProjectName`, `TaskDescription` (the row count, the spot-check named
  without saying which rows), `Recommendation` (the prediction field to write),
  `QuestionContext` (the label set and its one-line definitions from the spec, and
  nothing else of the spec), `Data.LowConfidence` (the review DataSet ARN; the
  review rows' S3 URI with `--review-rows-uri` when Hub finalization registered no
  review DataSet), `Data.Dataset` (the labeled DataSet ARN) and `Contract` (the
  hidden fields, the export's columns, the scoring rules and the exact fold command
  of Step 7b). Human-in-the-loop owns the review from here, including the review
  environment (local review or Studio). It shows the rows blind, exports `id` and the
  label per row, and stops there: the fold and overlay below apply the corrections,
  not its own Step 8. Do NOT adjudicate flagged rows in the
  chat: do not offer or perform "accept the jury majority", "accept with overrides",
  or "go through them one by one", and do not propose or decide labels for flagged
  rows yourself.

  If the user asks to settle flagged rows in the chat, do not list, suggest or
  decide labels: a label set in the chat has no reviewer, export or provenance,
  so it cannot be folded into the seed (Step 7b). Tell them human-in-the-loop's
  local review mode runs in this conversation with nothing to set up, then fill the
  hand-off spec.

  - **Blind rows.** No review row carries the model's answer: the job keeps it in
    `review.model_output.jsonl` for the fold (`references/input-output-contract.md`,
    "Human-in-the-loop hand-off"), and human-in-the-loop shows reviewers the input
    fields only (`human-in-the-loop/references/local-review-guide.md`, Step 3b). The
    spot-check rows look like every other review row.
  - **What to report.** The fold (Step 7b) counts the reviewed rows that confirmed
    and that corrected the model's label, the spot-check rows apart: their agreement
    rate is the human-alignment figure for the auto-accepted set, reported beside the
    certified bound.
  - **Cold start.** The review DataSet may hold sample rows people labeled already.
    `references/cold-start.md`, Step D, downloads the review rows (seed-sized) and
    the `seed_bootstrap` `overlay` action with `[REVIEW]` `<proj>/review.jsonl` drops those rows from
    that file and its side file, so pass `--review-rows <proj>/review.jsonl` in place
    of `--review-dataset-arn`: the hand-off then names the local file and counts its
    rows, and people are not asked to label a row twice.
  - **Plain labels** (a corpus run without `REVIEW_DATASET_NAME`) have no review
    set, and nothing routes them on the client. When the user wants a review of
    labels like these, the corpus run must carry `REVIEW_DATASET_NAME`: with no
    `EVAL_DATA` and no `TARGET` the job routes on the fixed 0.85 bar (the cold-start
    opt-out does this), and the hand-off reads that review set.

  When the export comes back, run Step 7b before anything else, then continue
  to Step 8.
- **"Proceed with auto-accept"** - continue to Step 8 unchanged.

## Step 7b - Fold every returned export (required, checked)

Run these steps for every human-in-the-loop export, as soon as it comes back and
before Step 8, not only when the corrections look systematic. The hand-off spec's `Contract.fold`, `Contract.overlay` and `Contract.check`
(Step 7a) carry the exact commands for this review set; use them, filling in its placeholders
(`<hil_export.jsonl>`, `<seed.jsonl>`, `<export label column>`) and, for a local review
export, adding `--export-id-field record_id` (Per-task fields, below). On a cold-start opt-out, which
has no seed and no split, `references/cold-start.md` (Opt-out) says which of these
steps apply.

### Fold, overlay and check

The labeled rows stay behind the API, so corrections are never merged on the client:
a dataset-transformation overlay by `id` on a view of the labeled DataSet applies them,
and its output becomes the DataSet's next version. The fold reads the job's side file
(`review.model_output.jsonl`) and the export, not the review rows. A hand-off built from a local review
file (`--review-rows`, the cold start) folds with `--sample <proj>/review.jsonl
APPEND <seed.jsonl>` instead, and its overlay and check take `<seed.jsonl>`:
`Contract.fold`, `Contract.overlay` and `Contract.check` carry the right form.

1. **Fold the export.** Each review row's id and `split` come from the side file
   (`routed: true` is `low_confidence`, `false` is `spot_check`), never from the
   export, and its label from the export. The rows go to
   `<proj>/review_seed.jsonl`, beside the side file.

   ```bash
   python scripts/fold_review.py hil \
       --model-output <proj>/review.model_output.jsonl \
       --job-summary <proj>/labeling_summary.json \
       --labels <hil_export.jsonl> --out <proj>/review_seed.jsonl \
       --id-field id --label-field <export label column> --project-dir <proj>
   ```

   `--project-dir` names the project whose run log records the fold (an `artifact` entry,
   step `seed-fold`, naming the seed and the fold report) and the spot-check verdict (an
   `analysis` entry, step `spot-check`); `check` records its verdict the same way.

   - Each folded row records its `provenance` (`spot_checked` for the `split: spot_check` rows, `human_verified` for the rest), the source export, the reviewer when the export names one, and the model's answer from the side file. Rows the reviewer marked unsure or skipped, or left without a label, are not added.
   - The folded rows carry no input text (the side file has none), so this fold does not `--append` to the seed; `hil` refuses `--append` without `--sample`. For a refinement re-run, which reads the text, download the review rows (seed-sized: the `hub_ops` `resolve` action, `[REF]` `<review_dataset_arn>`, `[OUT]` `<proj>/review.jsonl`, `DOWNLOAD = True`) and fold with `--sample <proj>/review.jsonl --append <seed.jsonl>` instead (`references/cold-start.md`, "Steady state"). A fold whose ids are partly in the seed already, or there with another label, is refused with exit 2.
   - Keep `review.model_output.jsonl`: without it there are no review ids to fold, no model answer to confirm or correct, and no spot-check verdict.
   - The report's `review_outcome` counts, per review reason (the row's `_review_reason`, `routed` when it has none), the rows whose human label confirmed the model's label and the rows that corrected it, by the job's row rule (`io_utils.task_correct`: exact match for qa and a 0.5 tolerance for llm_judge unless `--qa-match` / `--correct-tolerance` says otherwise); the spot-check verdict uses the same rule. `no_model_answer` counts the rows the model gave no answer for, and `not_scored` the rows whose prediction field no task rule scores (a summary), so each reason's counts add up to `model_output_joined`.
2. **Write the overlay.** The people's labels from the seed (the cold-start sample)
   and from `review_seed.jsonl` as overlay rows for the labeled DataSet: the id, the
   person's label under the prediction field, `provenance`, `_labeled_by: people` and
   the routing tag, and no input field (a patch on rows the DataSet already holds). A
   later `--seed` wins for an id, so the review's label replaces an earlier one. Pass
   `--seed <seed.jsonl>` only when the seed's rows are corpus rows (a cold start's
   sample, or a seed drawn from this corpus with its ids); a seed labeled outside the
   corpus has no rows in the labeled DataSet (`Check` would count them unmatched), so
   overlay only `review_seed.jsonl` then. The overlay enforces this: when
   `labeled_dataset.json` says the job labeled `EVAL_DATA` rows that are not corpus rows
   (`eval_rows_labeled_for_scoring` above 0), it leaves out every seed row that is not
   a review-fold row and says how many (`seed_rows_left_out`), so a colliding id never
   puts a person's label on an unrelated row. Those seed rows ship the model's labels;
   tell the user, and to overlay them, fix the seed's ids and re-run the corpus run.
   A customer's seed row with no provenance tag is a person's label, as the job takes
   it: the overlay writes it as `human_verified` (`untagged_as_human` in the report),
   unless its `source` names a model (`jury`, `model`, `resample:<model>`, or a Bedrock
   model id such as `us.anthropic.claude-sonnet-4-6`; a column such as `Reuters` or
   `en.wikipedia.org` is not one). The tag is `provenance`, else `_provenance`, else
   the legacy `_bootstrap` marker (`self` is the model's label); tags that disagree, or
   an unknown tag, leave the row out, as the job leaves such gold unscored. (Otherwise
   an untagged seed's dev and val rows would ship the model's labels.)

   `code_templates/seed_bootstrap.py` with

   | Placeholder | Value |
   |---|---|
   | `[ACTION]` | `overlay` |
   | `[SEED]` | `<seed.jsonl>,<proj>/review_seed.jsonl` (comma-separated, in order) |
   | `[DATASET]` | `<proj>/labeled_dataset.json` |
   | `[OUT]` | `<proj>/overlay.jsonl` |
   | `[ID_FIELD]` | `id` |

   Each `--seed` file is read under its own gold column: `GT_FIELD` when the file has
   it, else the task's default (`gt_label`, which the fold writes), else the corpus run's
   gold column (`label_field` in `labeled_dataset.json`, the customer's `category`, say).
   The report's `gold_fields` names each file's column. A file with rows but none of
   those columns is refused (exit 2), so a seed is never silently left out.

   It also writes `<proj>/overlay.handoff.json`: the dataset-transformation hand-off.
3. **Check the fold.** This is the step that proves 1 and 2 happened:

   ```bash
   python scripts/fold_review.py check --export <hil_export.jsonl> \
       --seed <proj>/review_seed.jsonl --labels <proj>/overlay.jsonl --id-field id \
       --label-field <export label column> --project-dir <proj>
   ```

   It exits 1 and names the ids when a decided row is missing from the fold's rows or
   its reviewer label is not in `overlay.jsonl`, and when no export row has the
   label column you named. Do not go on until it exits 0.
4. **Apply the overlay** (`overlay.handoff.json`). Show the user the plan and get a
   yes before anything is registered or run, as every job needs: the jobs are billed
   and not reversible, and they add a corrections DataSet and a new version of the
   labeled DataSet in the Hub. ⏸
   1. `Register`: the overlay rows as a DataSet (the `hub_ops` `register` action: `[LABELS]`
      `<proj>/overlay.jsonl`, `[NAME]` `<name>-corrections`, `[S3_PREFIX]`; seed-sized, local). For a
      later export the corrections DataSet exists already: set `APPEND = True` after the
      user's yes, as `register` asks.
   2. `DtView`: the `hub_ops` `dt-view` action (`[ARN]` `<dataset_arn>`, `[PROJECT_DIR]` `<proj>`) prints the
      job's first input, as for every dataset-transformation job: a view
      (`<name>-dt-input`) at the `.jsonl` in the labeling job's output folder (a job
      cannot size a folder input; it fails before it starts, S3 404). The job's output
      lands as a version of the view, not of the labeled DataSet; nothing is read. For
      a later export of the same review set, take the view of the labeled DataSet's
      latest version (the one `Promote` added; the hand-off's `LaterExport` says so,
      since its commands name `labeled_dataset.json`'s version): the overlay is rebuilt
      from the whole seed, and a row people labeled keeps its model answer, so it
      applies onto those rows.
   3. `Transform`: activate **dataset-transformation** for one CodeGen job with
      `AutoExecute` true, `InputDataConfig` [the view, the overlay DataSet] in that
      order, and `Specification` as its instruction. The code joins on `id`, moves the
      labeled row's prediction under `_model_output`, writes the overlay's prediction,
      `provenance`, `_labeled_by` and `_review_reason`, keeps every other row as it is,
      and returns `overlay_matched`, the number of labeled rows an overlay row matched.
      The two-job path cannot run it: its second job (BYOC) takes one input.
   4. `Check`: show the user the code the job ran (`TransformationCodeS3Uri` on the
      output), confirm in its `report.json` that the first input's record count equals
      the output's, and confirm that the full run's `overlay_matched` equals the
      overlay row count (`Inputs.OverlayRowCount`). `report.json` does not carry the
      code's stats; the job's CloudWatch log does, in each "Code execution complete"
      event (`aws logs filter-log-events --log-group-name
      /aws/sagemaker/Job/DataTransformation/ --log-stream-name-prefix <job name>/
      --filter-pattern '"Code execution complete"'`; `stats.overlay_matched`). Dataset transformation runs
      the code on a sample of each input first, where most ids do not meet: that event
      comes first, and its lower count is ignored. If the full run's `overlay_matched`
      is lower, that many corrections are not in the output (a seed labeled outside
      the corpus, for example): tell the user before `Promote`.
   5. `Promote`: the `hub_ops` `promote` action (`[FROM_ARN]` the `OutputDatasetArns` entry, `[TO_ARN]`
      the version the view was taken of, `[PROJECT_DIR]` `<proj>`) adds the labeled DataSet's
      next version: that version's document (`JobMetadata`, the report link),
      description and keywords, plus the job's `Transformation*` fields, pointed at
      the output's `.jsonl`; metadata only. It refuses when the labeled DataSet has a
      later version than `TO_ARN` (someone added one).

   The version `Promote` prints (`dataset_arn`) is the corrected deliverable (Step
   8b): one version above the job's, with the job's certificate on it. The view and
   the output on it are scratch, deleted in the hand-off cleanup (Step 8b), and
   `labeled_dataset.json` keeps `job_arn` and `index_uri`. Tell the user how many rows
   were folded, how many unsure rows were left out, and the confirmed and corrected
   counts, the spot-check rows apart.

### Spot-check verdict

The fold (step 1) also gives the spot-check verdict. It counts the `split: spot_check`
rows the reviewer corrected, plus those that came back unsure or skipped or did not
come back, so fold the complete export; a row whose reviewers disagree counts too,
reported apart as `spot_check.conflicts` (resolve it and re-run the check). At
`SpotCheckWithdrawAt` errors or more (7, for the 19, 29 and 59-row draws at 0.85,
0.90 and 0.95 alike) the spot-check fails: the summary says `spot_check_failed: true`
with `spot_check_errors` ("n of m"), and `hil` exits 3 after writing the seed. What
that means is the basis (`spot_check.basis`), which `--job-summary` settles from the
job's `Status`:

- **calibrated** (`Status: Certified`): the certificate is withdrawn
  (`certificate_withdrawn: true`). Say so in Step 8 ("certificate withdrawn", not
  certified) and never state the certified figure. The way back is the loop: fold the
  review into the seed (done here), refine the spec on the new failures (Step 5), and
  run the corpus job again (Step 7) for a fresh certificate and spot-check.
- **bar** (any other `Status`: the job routed on the fixed 0.85 bar): there was no
  certificate, so nothing is withdrawn and the summary has no
  `certificate_withdrawn`. The auto-accepted rows do not meet the bar: say so in Step
  8, and review more rows or run the loop again.

When the user turned the spot-check review off (the planning reference's
`review_high_confidence: false`), the job may still pin a spot-check and put it in
the review set. Pass `--spot-check-off` to `hil` (and to `hil_handoff.py`, so
`Contract.fold` carries it): those rows then give no verdict, a row that did not come
back is not a miss, the returned ones fold as usual, and the summary says
`spot_check_skipped`. The labels carry no accuracy promise.

Pass `--job-summary`: it sets the basis from the job's `Status`. Without it the basis
comes from the rows: `calib_accepted` in the side file (written on a certified run)
means `calibrated`; a `spot_check` row with a routing tag (`_review_reason`) but no
`calib_accepted` means `bar`; a `spot_check` row with neither is `unknown`, and the
verdict says what a failure means either way. Below the withdraw count, report the
count and the spot-check agreement rate (`spot_check.agreement_rate`, confirmed over
the rows that came back with a model answer): the certificate stands, or on the bar
basis the accepted rows pass the spot-check. The fold writes its report beside its
output (`<proj>/review_seed.fold.json`, or `<proj>/hil_seed.fold.json` after a fold
with `--sample`) with the fingerprint of the `--job-summary` it read; the run report
shows the agreement rate (or the withdrawal) only when that fingerprint matches the
current `labeling_summary.json`. A returned row with no model answer to compare is
counted as `spot_check.no_model_answer`, neither an error nor a confirmation, and the
verdict says to join the answers and re-run the fold.

### Per-task fields

For a task whose prediction is not `label`, pass the task's gold field to both
commands and its prediction field to `check`: ordinal `--gt-field gt_score
--pred-field score`, llm_judge `--gt-field gt_score --pred-field judge_score`, ner
`--gt-field gt_entities --pred-field entities`, qa `--gt-field gt_answers
--pred-field answer`, summarization `--gt-field gt_summary --pred-field summary`; the
hand-off spec's `Contract.fold` already carries the prediction field.
A local review export names rows `record_id` and carries the reviewer's label as
`corrected_completion` (the feedback row of the hand-off contract, `Contract.export`
in `hil_handoff.json`): pass `--export-id-field record_id --label-field
corrected_completion` to both commands; for another export, name its id and label
columns the same way. The export never carries `split`; the fold reads it from the
original review row.

### Label Studio exports

A Label Studio export from human-in-the-loop goes to both commands as it is. They read each task's id from its `data` (`--export-id-field` names that key when it is not the sample's id field), the label from each annotation's answer to the label config control that `--label-field` names, and the reviewer from the annotation. A skipped annotation counts as skipped, and an entity control with no span marked is an empty entity list. A task with several annotations (`maximum_annotations` above 1) folds once when they agree; when they disagree, `hil` leaves the id out of the seed and both commands list it under `conflicting_ids` (`check` exits 1), so adjudicate it in Label Studio and re-export, or set `maximum_annotations` to 1 for single-pass review.

When the corrections share a pattern the spec missed, recommend re-running the
refinement loop on the augmented seed (`references/cold-start.md`, "Steady state")
and state its cost (the Step 2-6 labeling runs). ⏸ Wait for the user's choice.
Otherwise continue to Step 8.

Run Step 8b only after the overlay job of Step 7b (step 4) has written its new
version, so the DataSet ARN you name carries the human-corrected labels.
