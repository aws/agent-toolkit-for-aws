# Label review: find label problems and resolve them with the user

Use this when the trial run's disagreements look like label problems, not spec gaps, or the user asks whether the seed labels are right (classification only). `scripts/review_labels.py` runs a review-only CreateJob (`Config.Review`) and downloads its `review/` files; no label changes until the user decides. Say first that no held-out gain is measured for it and each listed item costs one human decision.

## Step 1 - Run the checks, and estimate the judge

```bash
python scripts/review_labels.py --seed <proj>/work/review_seed.jsonl --spec <proj>/work/labeling_spec_iter_<N>.md \
  --text-fields <fields> --generation-model-id <the trial run's model> --project-dir <proj> \
  --preds <proj>/work/dev_pred_iter_<N>.jsonl --preds <proj>/work/val_pred_iter_<N>.jsonl \
  --judge-model-id <judge> --estimate-only --s3-prefix <s3://...> --role-arn <role> --run-id <id> \
  --region <the trial run's region>
```

Take the trial run's role, S3 prefix, region, text fields and generation model from the run log.

`--seed`: with a frozen split, its current rows (before each review, `cat <proj>/splits/dev.jsonl <proj>/splits/val.jsonl > <proj>/work/review_seed.jsonl`; a test row or a label unlike the split's stops the run); else the labeled seed minus `split: test` rows. Recommend a judge by an id the service accepts (an unlisted id is refused at the estimate job); the user confirms it at the ⏸ below. The estimate job (and a checks-only run, no `--judge-model-id`) makes no model call, so it bills no tokens; it is still a labeling job the account runs and registers a scratch DataSet, so say so and get the user's yes before submitting it, as for every job. `--preds` and the optional `--rules` (a `keyword_rules.json` from the spec, `{"lists": [{"label", "keywords", "quote"}]}`) are local files; the script names any cap it refuses. Files and `decisions.csv` (pre-filled from the run log) go to `<proj>/audit/`. Price `judge.estimate` from https://aws.amazon.com/bedrock/pricing/ (on-demand, the judge's region; prices change, so say the date you read them), named, with output at `output_tokens_total_with_reserve` when given (a ceiling).

⏸ Show `report.md`'s counts per check and the Guideline judge items of `references/offer-options.md`. Wait for the user's explicit approval, else go to Step 2. Record it, naming the printed `run_log_entry`: `python <skill-root>/references/directory-management/scripts/run_log.py write --project-dir <proj> --kind approval --step label-review --iteration 0 --status approved --field estimate='"<entry id>"'` (golden scope: `--step golden-review`).

Then rerun without `--estimate-only`. One approval covers one judged job, used at submit; the script refuses a judged run with no unused approval for that estimate, and under one `--run-id` changed inputs or a rerun of a Failed or Stopped judged job (`--resubmit` or a new `--run-id`, with a new approval). The job fails by name if every judge call fails or every reply is unreadable (exit 1), or on an access, expired-token, validation or not-found error (exit 3; on the first two, fix the role's Bedrock access). Some failed calls or unreadable replies only warn: say how many rows were not judged.

A review job can run long. Pass `--no-wait` (with `--run-id`): the command submits the job, prints its name, ARN and status, and exits while it runs. Once the run log has the job's `submitting` entry (the command prints the job's name), end the turn and tell the user which job was submitted. To collect it, rerun the same command with the same `--run-id`: it re-attaches to the job (reading its status from `DescribeJob`), uploads nothing and needs no new approval. `--resubmit` starts a second, billed job.

## Step 2 - The user decides

Give the user `<proj>/audit/contradictions.csv` (read only) and the top of `report.md`. In `decisions.csv` the user picks `guidelines_correct` (relabel its conflicting rows), `label_correct` (keep them; `sop_wording`, required, adds a sentence to the spec) or `neither` (`if_neither` holds the right label; wording in `sop_wording`), and may override rows in `overrides` (`r12=a;r13=keep`). A blank decision changes nothing; a deleted row restores the run log's decision. A `neither` with no label, no sentence and no override is not applied (it is listed in `invalid_decisions`). ⏸ Wait for the filled file. Then run Step 3 with `--dry-run` and show the counts per decision, the rows relabeled and `invalid_decisions`. With a frozen split, say that `splits/dev.jsonl` and `splits/val.jsonl` are overwritten and rehashed, and that apply first copies them to `<proj>/work/review_jobs/<run-id>-split-before/` (undo: `python scripts/apply_label_decisions.py --project-dir <proj> --undo <run-id>`, with the review's `--run-id`; after an undo, blank those items' rows in the next review's `decisions.csv`, which pre-fills them from the run log). ⏸ Wait for the user's explicit approval.

## Step 3 - Save the next iteration

```bash
python scripts/apply_label_decisions.py --project-dir <proj> --spec <proj>/work/labeling_spec_iter_<N>.md \
  --seed <proj>/work/review_seed.jsonl --decided-by <the user's handle>
```

It writes `labeling_spec_iter_<N+1>.md`, `seed_iter_<N+1>.jsonl` and the changelog next to the spec, the relabels into a frozen split's `dev.jsonl` and `val.jsonl` (rehashed), and each decision to the run log. Refused, writing nothing: a spec, seed or split changed since Step 1 (rerun it), an override outside its item, a test row, a decision on an older item version. Not applied, and listed: an item with a label outside the label set, a row two items set differently. The split is written last: if that fails, the split is left as it was and nothing is kept. Tell the user the counts and `invalid_decisions`, then rerun the loop's Step 2 with the new spec. Say that val scores after this review read high and are not comparable with earlier ones: an accepted relabel moves val gold toward the model's earlier answer. The test certificate is unaffected (test rows are never relabeled here).

## Golden rows - a person resolves the flagged ones (optional, before the corpus run)

Golden rows (`splits/test.jsonl`) set the corpus run's cutoff and certificate. Only a person relabels one. Offer it per `references/offer-options.md` (Golden-row review).

1. Run Step 1 with `--scope golden --seed <proj>/splits/test.jsonl` and no `--preds`; files go to `<proj>/audit/golden/`. This scope needs its own estimate and ⏸ approval before the judge: one approval covers one judged job over one set of rows, and the golden scope is a separate paid job over the test rows.
2. `python scripts/golden_review.py route --eval <proj>/splits/test.jsonl --routed <proj>/audit/golden/routed.jsonl --text-fields <fields> --project-dir <proj>` writes the blind `<proj>/golden_review/review.jsonl` and `golden_review.json`.
3. ⏸ Show the Golden-row review items of `references/offer-options.md` with the script's `routed_rows` and `routed_per_check`; wait for the user's explicit approval.
4. Hand `review.jsonl` to the **human-in-the-loop** skill; each relabel must name its reviewer.
5. `python scripts/golden_review.py apply --manifest <proj>/golden_review/golden_review.json --export <hil_export.jsonl> --project-dir <proj>` (a local review export adds `--export-id-field record_id --export-label-field corrected_completion`).
6. Run the corpus run with `EVAL_DATA = <proj>/golden_review/golden_reviewed.jsonl` and `GOLDEN_REVIEW = <proj>/golden_review/golden_review.json`.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Label review for non-classification tasks (NER, extraction, generation). Guidance only: people review those labels through the human-in-the-loop skill (`references/full-loop-review.md`, Step 7a); no model labels or relabels rows outside a labeling job.
