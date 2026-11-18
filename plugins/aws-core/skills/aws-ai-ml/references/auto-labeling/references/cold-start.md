# Cold start - no labeled seed

The full loop (`references/full-loop.md`) assumes a small labeled seed already exists (its Step 0). This is the path when the customer has **none**. People label a random sample of the corpus, that sample becomes the seed, and the normal loop runs from it. No row the model labeled is ever gold here: a seed built from the model's own confident rows certifies accuracy that its labels do not have.

Same **HARD RULE** as the full loop: run the steps yourself (no wrapper script), and stop for approval before any at-scale, token-spending run. Steps A to C start no labeling run: the sample costs human labels (and one `Split` job that spends no model tokens), and the first token-spending run is back in `references/full-loop.md`.

**BINDING RULE: build the seed first; label the corpus without one only on the customer's opt-out.** When there is no labeled data you MUST build a seed with Steps A to C before any at-scale labeling, and then run the normal loop off that seed (Step D). The only other path is the opt-out below, on the customer's explicit yes to labels that carry no accuracy promise. Recognizing that there is no labeled seed and then labeling the corpus from general knowledge, or on any other path that skips building a seed, is an **error**, not a faster route: it produces un-measured labels and bypasses the confidence jury and the held-out gate. There is no "just label it from what the model already knows" shortcut.

The labeling round (`code_templates/labeling_round.py`) enforces this rule. A run that shows no labeled seed (no `EVAL_DATA`, no `DEMOS` in use, and no `decision.json`, `splits/manifest.json` or `held_out_report.json` next to `OUT` or `SPEC` or one level up) stops before any job, points here, and says how many reviewed rows a promise needs. Only the opt-out below passes `CONFIRM_NO_SEED`. See `references/troubleshooting.md`, "Run-time checks".

**The corpus stays behind the API.** On a cold start no script reads the corpus on the client beyond its first rows (`code_templates/inspect_inputs.py` Cell 2, `corpus/head.jsonl`). The random sample is drawn by a `dataset-transformation` `Split` job, not by streaming the corpus through the sandbox.

## Opt-out - labels with no accuracy promise

If the customer will not have people label a sample, offer this path instead of stopping. With no seed there is no split, refinement, held-out score or certificate, so nothing measures the labels.

1. Run full-loop Steps 0 to 0.6, and take the labeling instructions from the customer: their spec, or one drafted with them (`references/spec-authoring.md`). With no seed to refine it against, that spec labels the corpus as written.
2. The HARD RULE #2 summary (`references/full-loop.md`) states that these labels carry no accuracy promise. The customer's yes there is the opt-out; without it, nothing is labeled.
3. Label the whole corpus as a standalone corpus run (`references/apply-and-confidence.md`) with `CONFIRM_NO_SEED = True` and **no `EVAL_DATA` and no `TARGET`**, so every label ships with its confidence. The flag records the customer's yes; without it the run stops before any job. With no gold and no target the job accepts rows at the fixed 0.85 bar, routes the rest to the review DataSet, pins no spot-check (there is no promise to check) and reports `Status: NotCertified` (`no_eval_data`).
4. Offer the routed rows for review with full-loop Step 7a: the review set is the rows below the bar (`split: low_confidence` only). When the export comes back, run full-loop Step 7b with these changes:
   - **Fold:** `Contract.fold` as written: it reads the job's side file and writes `<proj>/review_seed.jsonl` without `--append`, and there is no seed to append to.
   - **Overlay:** the `seed_bootstrap` `overlay` action with `[SEED]` `<proj>/review_seed.jsonl` alone, then apply it as Step 7b does (a dataset-transformation overlay by id on a view of the labeled DataSet, whose output the `hub_ops` `promote` action adds as the DataSet's next version). The labels stay behind the API.
   - **Check:** `fold_review.py check` with `--seed <proj>/review_seed.jsonl` and `--labels <proj>/overlay.jsonl`.
   - **Skip the refinement re-run because:** there is no seed or split to add the rows to. If the customer later builds a seed (Steps A to C), the folded rows can join its dev split only: they are the least-sure rows, not a random sample, so they never become val, test or gold rows.
5. Never set `TARGET`, and never state an accuracy figure or promise, in the chat or in the report (the run report shows the `NotCertified` status as it is).

## Step A - Draw a random sample of the corpus

Run full-loop Steps 0 (the first-row read and the size estimate) and 0.1 (the SDK is installed) first, so people never label a sample for a run that cannot go ahead. With no spec, draft one (`references/spec-authoring.md`): the people labeling the sample work from its label set and definitions. Get the suggested `TASK` before anyone labels, since it decides what they label (a class, entity spans, an answer, a summary or a score). Run the detector on the corpus head: `code_templates/inspect_inputs.py` Cell 3, with
`[SPEC]` the spec and `[TASK_SAMPLE]` `corpus/head.jsonl`.

(`corpus/head.jsonl`, the corpus's first rows, is written by the `hub_ops` `resolve` action (pointer mode) for an `s3://` or DataSet corpus and by Step 0's inspect cell otherwise; with no seed, the spec carries most of the signal.)

**Size the sample.** The sample is 200 rows, or 400 when the target is 0.95 or higher, or every row when the corpus is smaller (the `seed_bootstrap` `sample` action applies this rule; a task that ships without an accuracy promise, `overview.md` Limits, keeps 200 rows at any target). `N` is the corpus row count from Step 0 (`estimated_rows`, or the exact count when the Split job reports it).

**Draw it with a `Split` job.** The job's first input is a `hub_ops` `dt-view` of the corpus (`[ARN]` for a DataSet, `[S3_URI]` `<corpus>` and `[NAME]` `<name>` for an object; `[PROJECT_DIR]` `<proj>`): a view at the corpus object, registered without reading it, so nothing the job writes lands as a version of the customer's corpus; the hand-off cleanup deletes the view (full-loop Step 8b). Route the split through `dataset-transformation` (`dataset-transformation/references/routing-and-guardrails.md`; the operator: `dataset-transformation/references/api-execution-flow.md`, "Built-in operations", and `dataset-transformation/references/api-operator-configs.md`, `Split`): the built-in `Split` operator, `Method: random`, a fixed `Seed`, and `Ratios` that give the sample part about 1.25 × the size above (so the draw below has enough rows; a corpus at or below the size is sampled whole with no job). The job registers two DataSets, the sample part and the remainder, and spends no model tokens; it still needs the user's approval before it runs, as every job does (billed, and it registers the two parts as DataSets in the Hub, which can be deleted later). ⏸ Then trim the sample part to the exact size and keep only the id and the input fields:

`code_templates/seed_bootstrap.py` with

| Placeholder | Value |
|---|---|
| `[ACTION]` | `sample` |
| `[INPUT]` | the sample part: `s3://` URI or local JSONL |
| `[OUT]` | `<sample.jsonl>` |
| `[TEXT_FIELDS]` | `<fields>` |
| `[TARGET]` | `<target>` |
| `[TASK]` | `<task>` |
| `[CORPUS_ROWS]` | `<N>` |

(`<fields>`: the input fields the spec labels from, comma-separated, the list the labeling runs get as `TEXT_FIELDS`; `<target>`: the user's accuracy target, 0.90 if none; `<task>`: the detected task; `--corpus-rows <N>`: the corpus count the Split job sampled from, so the report can tell a part from the whole corpus.) The draw is uniform at random with a fixed `--seed`, so the same input and `SAMPLE_SEED` give the same sample. Each row keeps only its id and the input fields, so the labelers never see a model label. A row with no `id`, or a null one, gets its position in the corpus as text (`"17"`), the id the labeling job gives it; that position is known only when `--corpus-rows` says the input is the whole corpus. The draw stops (a refusal, nothing written) on an input above the row limit (`overview.md`, Limits), and on ids the labels could not join back by: two rows that share an id, an id-less row in a sample of a larger corpus (give the corpus ids first), or a row without a non-default `--id-field`. The rows it reads are reported as `client-read:`; they are the sample part, never the corpus.

Two fields of the sample's report change what comes next:

- `whole_corpus: true`: the sample is every row of the corpus (`--corpus-rows` at or below the sample size), so people label all of it, and Step C ends the cold start. The people's labels are then the labeled dataset: no model label ships and there is no certificate.
- `warning`: the target is above what this sample can certify even if every model label is right, in test alone (about a quarter of the sample, the only rows independent of a refined spec). It states both requirements (val and test for a spec that ships unchanged, test alone for a refined one) and the highest target each can reach. A `whole_corpus` sample gives no `warning`, since there is no certificate.

## Step B - People label every row

Hand `<sample.jsonl>` to the **human-in-the-loop** skill to have people label every row from the spec's label set and definitions. They see the id and input fields only; no label is shown or proposed (`human-in-the-loop/references/local-review-guide.md`, Step 3b). Ask human-in-the-loop to put the row count, the target that set it, the detected task and the sample report's `whole_corpus` or `warning` (when present) into its Step 2 approval, so the user confirms them before anyone labels. It returns the rows with a human label per id.

## Step C - Fold the labels into the seed and check the fold

Fold the export into the seed (join on the id field; point `LABEL_FIELD` at the export's label column):

```bash
python scripts/fold_review.py hil --sample <sample.jsonl> \
    --labels <hil_export.jsonl> --out <seed.jsonl> \
    --id-field id --label-field <export label column> --project-dir <proj>
```

Then check the fold against the sample:

```bash
python scripts/fold_review.py check --export <hil_export.jsonl> \
    --seed <seed.jsonl> --sample <sample.jsonl> --id-field id \
    --label-field <export label column> --project-dir <proj>
```

- **What it checks.** It exits 1 and names the ids when a sample row has no label in the export, is marked unsure or skipped, or has two different labels, and when a decided row of the export is missing from the seed (it writes nothing). Do not continue to Step D until it exits 0.
- **When it names rows.** Do not drop them: the rows people found hard are part of the random sample, and a seed without them is easier than the corpus, so its certificate would be too high. Get one label for each (from people or the spec owner), put it in the export in place of the row's earlier rows, and run both commands again.
- **Other field names.** For a task whose gold field is not `gt_label`, or an export keyed by another id column, give both commands the `GT_FIELD`, `--export-id-field` and `LABEL_FIELD` values full-loop Step 7b lists.
- **Gold.** Every seed row is a sample row with a person's label as its gold (`provenance: human_verified`), so the whole seed counts as gold for the job's certificate (`references/apply-and-confidence.md`, Seed provenance).

When the sample is the whole corpus (Step A), the cold start ends here. The corpus is no larger than the sample, so it is client-readable; put the people's labels on its rows and deliver them as `labels.jsonl`:

`code_templates/seed_bootstrap.py` with `[ACTION]` `merge`, `[LABELS]` `<sample.jsonl>`, `[SEED]` `<seed.jsonl>`,
`[OUT]` `<proj>/labels.jsonl` and `[PRED_FIELD]` `label`.

(The sample IS the corpus here, id and input fields; for a task whose gold field is not `gt_label`, add the `GT_FIELD` value and use the `--pred-field` value full-loop Step 7b lists.) Tell the user that every row carries a person's label, that no model label ships, and that there is no held-out score, certificate or refined spec. Otherwise continue with Step D.

## Step D - Run the loop from the seed

Continue with `references/full-loop.md` from **Step 1 (split)**, with `<seed.jsonl>` as the labeled seed. Step 1 splits on the seed's gold field (`gt_label`, or the `GT_FIELD` that Step C used) and clusters on the input fields Step A kept (`<fields>`). A drafted spec's rules are a first pass (`references/spec-authoring.md`), so Step 1b induces rules from the seed's dev split and keeps them only if they beat the spec without them on val (`references/spec-induction.md`). The rest of the loop (refine → gate → apply) runs as written, with three additions.

**Split at random.** Add `--strategy random` to Step 1's `cluster_split.py` command (still pass `GT_FIELD` and `TEXT_FIELDS`; the random split reads neither). The val and test rows that back the certificate must stay a random sample of the corpus. The default cluster split stratifies on the people's labels and sends small (cluster, label) groups to dev, so on many-class seeds val and test come out easier than the corpus and the certificate fires more often than the labels deserve.

**Addition 1: the corpus count in the summary.**

- **What it says.** The HARD RULE #2 summary also says how many corpus rows lie outside the sample.
- **Why.** Only those rows ship the model's labels, so on a corpus barely bigger than the sample the loop's runs label a handful of rows.

**Addition 2: the people's labels on the sample rows.** The corpus run labels the sample rows too (the corpus is its input). The job already ships a person's label on every row that is also a gold row (`EVAL_DATA = splits/test.jsonl`): those rows come back `_labeled_by: people` with the model's answer under `_model_output`. The dev and val rows are not gold for the corpus job. The labeled corpus stays behind the API, so as soon as the corpus run has finished, and before the hand-off, write the people's labels as an overlay onto the labeled DataSet. The job may have routed a dev or val sample row, and people labeled it already, so first download the review rows (seed-sized; the corpus run downloads only their side file) and let `--review` drop those rows:

the `hub_ops` `resolve` action (`[REF]` `<review_dataset_arn>`, `[OUT]` `<proj>/review.jsonl`, `DOWNLOAD = True`),
then `code_templates/seed_bootstrap.py` with `[ACTION]` `overlay`, `[SEED]` `<seed.jsonl>`, `[DATASET]`
`<proj>/labeled_dataset.json`, `[OUT]` `<proj>/overlay.jsonl` and `[REVIEW]` `<proj>/review.jsonl`.

- **What ships.** Once applied (full-loop Step 7b, step 4: a dataset-transformation overlay by id on a view of the labeled DataSet, whose output the `hub_ops` `promote` action adds as the DataSet's next version), each sample row ships with the person's label instead of the model's. Step 7b rewrites the same overlay with the reviewed rows added, so the overlay is applied once, after the review.
- **How the row is marked.** The overlay row carries the id, the person's label, `provenance: human_verified` and `_labeled_by: people`; the transform moves the model's answer under `_model_output`. No input field is in the overlay: it is a patch, built from the seed alone.
- **No second review.** The job never routes a gold row or draws it for the spot-check. A dev or val row the job routed is dropped from `review.jsonl` and its side file by `--review` (the report prints `review_rows_dropped`), so people are not asked to label it twice; the Step 7a hand-off then passes `--review-rows <proj>/review.jsonl`, the local file, in place of the review DataSet ARN.
- **When it refuses.** The overlay exits 2 when the seed has no human row or `labeled_dataset.json` names no `dataset_arn`. A seed id with no row in the labeled DataSet does not fail the transform (the job runs its code on a sample of each input first, where most ids do not meet), and the client cannot check it, since it holds no corpus row: the seed's ids are the sample's, drawn from this corpus, so they name its rows.
- **Other tasks.** For a task whose gold field is not `gt_label`, pass it the `GT_FIELD` and `--pred-field` values that full-loop Step 7b lists.

**No recalibration map.** The seed rows are corpus rows, and the job refuses `RECALIBRATION_FIT` rows that are corpus rows, so `CONFIDENCE_RECALIBRATION` does not apply on a cold start (the labeling round refuses it before upload).

**Addition 3: the certificate at `<target>`** (`references/apply-and-confidence.md`, Calibration).

- **The promise.** The corpus run's `TARGET = <target>` with `EVAL_DATA = splits/test.jsonl` is the accuracy promise: the job certifies the auto-accepted rows on the test split's people-labeled gold. Some task types ship without one (`overview.md`, Limits); send them no `TARGET`.
- **Why test alone.** The dev split chose the demos and the induced rules, and val chose the spec that ships, so their rows would back a promise they helped pick. Test is about a quarter of the sample: the Step A `warning` says when that is too few rows for the target (the job reports `insufficient_eval_rows` under 50 gold rows and certifies nothing).
- **The spot-check.** The job pins the spot-check from the accepted rows that are not test (eval) rows, so dev and val sample rows can be drawn. `overlay --review` drops those from the review set, since people labeled them already, and scores each with its known label against the model's answer (`review.known_spot_check.json` beside `review.jsonl`); the fold counts them, so the spot-check keeps its 19, 29 or 59 rows. Step 7b's verdict withdraws the certificate at 7 errors.

## Steady state - keep strengthening from human-in-the-loop review

On a full run, the review hand-off → human-in-the-loop → `fold_review.py hil` path folds the reviewed low-confidence rows back in as seed, so the next refinement round sees the corrected examples. To re-enter:

1. Hand the corpus job's review set (the review DataSet: the rows below the cutoff and the pinned spot-check) to human-in-the-loop (full-loop Step 7a).
2. Fold the export back (full-loop Step 7b, which also applies the corrections as a dataset-transformation overlay onto the labeled DataSet and gives the spot-check verdict). The refinement reads the rows' text, which the side-file fold does not carry, so for a re-run download the review rows (seed-sized: the `hub_ops` `resolve` action, `[REF]` `<review_dataset_arn>`, `[OUT]` `<proj>/review.jsonl`, `DOWNLOAD = True`) and fold with `fold_review.py hil --sample <proj>/review.jsonl ... --append <seed.jsonl>` (one atomic append onto the existing seed), then write the overlay and run `fold_review.py check` until it exits 0.
3. Re-run the refinement loop on the same split, with the reviewed rows added to dev only.
   - **What to do.** Append the folded rows (`review_seed.jsonl`, without their `split`, `provenance` and `_bootstrap` fields, and without rows whose id is already in dev, val or test; the annotator and `source_export` columns may stay) to `<proj>/splits/dev.jsonl`, run the `split_freeze` `rehash` action (`[SPLITS_DIR]` `<proj>/splits`, `[REASON]` `"human-in-the-loop fold"`) (it refuses a near-copy of a test row: drop it, since test is immutable, and tell the user how many folded rows `rehash` refused as near-copies of test rows and that they stay out of dev), and go back to `references/full-loop.md` **Step 2** (or `references/refinement-routing.md` to decide whether a fresh refinement round is warranted).
   - **Keep the split.** Do not split the augmented seed again. The routed rows are the hard ones, not a random sample; a fresh split would move them, and dev rows the refiner has read, into val and test, which must stay a random sample the refiner never saw (the held-out score and the certificate come from them).
   - **The certificate.** The next corpus run still certifies on the same test split (`EVAL_DATA = splits/test.jsonl`); a further pass of the planning flow is a new project (its Review Loop).
   - **What the round gains.** The corrected rows now carry gold labels, so error analysis sees the failures it previously got wrong.
   - **Do no harm.** The select cell's (`code_templates/score_and_select.py` Cell 3) best-iter rollback + val do-no-harm floor still gate the result, so a round that does not help ships the prior spec.

Rows annotated in human-in-the-loop review re-enter refinement and drive a better spec, rather than being reviewed and forgotten.
