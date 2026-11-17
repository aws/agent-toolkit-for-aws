# Apply + Confidence

The final stage: take a hardened (gated) spec and label the rest of the corpus in
one labeling job, which tags every row with a confidence, picks the cutoff that
certifies the accuracy target on the auto-accepted rows, and routes the rest to a
human.

Runs standalone ("label the rest with this spec") or as Step 7 of the full loop. A
standalone run needs a labeled seed the frozen spec was measured on (the full loop's
`<proj>/splits/test.jsonl`, or the seed itself labeled by people); with none,
the labeling round stops before any job and points to `references/cold-start.md`,
unless the customer said yes to labels with no accuracy promise (`CONFIRM_NO_SEED`,
cold-start.md, Opt-out).

## Apply - the corpus run

The corpus run is one labeling job (`references/sdg-indexed-backend.md`) over the
whole corpus with the frozen spec: the labeling round with `STAGE = "corpus"`, the
command of `references/full-loop.md` Step 7. One input → one label, order preserved,
and no row is dropped: a row the job got no usable answer for keeps its id with a null
prediction and a `prediction_error`, and the submitter marks it `_failed` with
`_failed_reason`. Do not refine here - the spec is frozen; this stage only applies it.

The job votes the jury, scores the gold rows (`EVAL_DATA`), chooses the cutoff, pins the
spot-check, routes the rest, and registers the labels and the review set as two Hub
DataSets (`DATASET_NAME`, `REVIEW_DATASET_NAME`); the skill reads the result and
recomputes none of it. The corpus is never read client-side beyond its first rows
(`code_templates/inspect_inputs.py` Cell 2, `io_utils.head_rows`), and the labeled corpus stays behind the
API: the corpus run downloads the job's summary, held-out report, the review rows'
side file and its `report.html`, never its `labels.jsonl`. `OUT` is the deliverable
record, `labeled_dataset.json`: the labeled DataSet ARN, the review DataSet ARN and the
S3 URIs of the job's labels and review rows.

## Confidence - the jury

By default, confidence is **ensemble disagreement**, not a model's self-reported
probability (`CONFIDENCE_METHOD = stated`, below, is the opt-in exception). Several
distinct Bedrock models label each row independently inside the job (the job votes
the panel on a vote task with `Routing`); the share of the panel that agrees on the
winning label is the confidence:

- all agree → confidence 1.0
- majority agree → partial confidence (agreeing / panel size)
- all differ → low confidence.

Use a **cross-family** lineup so the votes are independent (same-family models tend
to share mistakes). `JURY_MODELS` takes 2 to 5 exact ids the service accepts, the
generation model first (`references/sdg-indexed-backend.md`, Limits).

### Vote tasks (classification, qa, ner)

The job votes the panel per row. Each labeled row carries the job's `confidence`
(the agreement, or with stated confidence the stated score below; also copied to
`confidence_score`, the name the skill's scripts read), `ballots` (`[{model, <prediction field>}]` for every juror that replied:
`label` for classification, `answer` for qa, `entities` for ner; the value is null when
its reply gave no valid answer; a refine round's read-back also keeps them as
`jury_votes`, with each value under `label`), `votes`, `n_responders`
and `panel_size`. A reply whose label is not in the spec's Label Set is no ballot, so
an off-list answer can neither win nor block a valid majority. The denominator is
always the configured panel, never the responders: 2 agreeing ballots on a 3-juror
panel score 2/3, never the 1.0 of a true 3-of-3. A low-agreement row is not dropped;
it is kept with its low confidence so the job routes it to review.

- **classification**: labels compared exactly against the Label Set.
- **qa**: answers compared after SQuAD normalization (an empty answer is the
  "unanswerable" ballot).
- **ner**: the vote is **per span**. The base entity list is the first juror's; each of
  its `(type, text)` spans scores the share of the panel that emitted an equal span,
  a span more than half the panel proposed but the base missed is added at that share,
  and a span only a minority proposed is not added. The row's `confidence` is the mean
  over shipped spans and `min_span_confidence` the weakest; a unanimous "no entities"
  row scores 1.0, not 0.0. See `references/task-types.md`.

**Jurors that stop answering.** The job does not count missing ballots itself, so the
submitter reads them off the rows: a juror missing on more than 5% of the voted rows
is reported as `degraded_jurors` in the run summary, as `confidence_shortfall` in the
run-log entry, and as a `JURY DEGRADED` warning on stderr. On the corpus run only the
review rows' ballots are on the client, so `jury_check` (summary, run-log entry and a
`NOTE` line) says which rows were checked; report that scope with a clean result too.
A degraded juror lowers every row's confidence, so more rows route to review; report
it and ask the user whether to swap it and rerun (billed) before reading the
coverage. ⏸

### Stated confidence (classification, opt-in)

`CONFIDENCE_METHOD = stated` (`Confidence.Method: stated`) asks each model for a 0 to
100 confidence with its label. Without it, or with `agreement`, confidence is the vote
share above.

- Each ballot carries `stated_confidence` (0 to 1, null when the reply gave none). A
  reply with a valid label and no confidence still votes.
- A jury row's `confidence` is the sum of `stated_confidence` over the ballots for the
  winning label (null counts 0), over the panel size; `agreement_confidence` keeps the
  vote share.
- The 0.75 agreement floor and the fixed 0.85 bar read `agreement_confidence`. The
  certified cutoff is chosen on `confidence`.
- A refine round's one model writes `stated_confidence` on the row; nothing routes on
  it.
- `StatedConfidenceMissing` in the summary counts the ballots (jury) or rows (one
  model) with no stated confidence; the run warns over a share
  (`references/troubleshooting.md`, Stated confidence missing). A missing one counts 0
  in the row score, so more rows route to review: check the spec's Output Schema asks
  for the job's keys, or ask the user whether to swap the model. ⏸

`stated_confidence` and `agreement_confidence` are model output
(`references/troubleshooting.md`, Reserved column name (refine round)).

### Opt-in confidence options (classification, off by default)

Each changes the labeler, the routing or the cost: offer one only as `references/offer-options.md` says. The service checks each combination at submit (CreateJob) and the run shows its message as it is; the labeling-round template's Cell 1 comments list what each setting needs.

| Flag | What changes | Needs |
|---|---|---|
| `CONFIDENCE_METHOD = verbalized` | one model labels and states a 0 to 1 `confidence_score`; no jury | classification |
| `CONFIDENCE_ESTIMATOR = judge\|panel`, `JUDGE_MODELS` | one model labels; a judge (default: the labeler's model) or the mean of 2 to 3 judges scores each row | `CONFIDENCE_METHOD = agreement` or `verbalized` |
| `CONFIDENCE_FLOOR_BYPASS` | drops the 0.75 floor (`MinAgreement` null; otherwise 0.75) | verbalized, judge or panel; not with recalibration |
| `CONFIDENCE_RECALIBRATION = "platt"`, `RECALIBRATION_FIT = <splits/val.jsonl>` | a Platt map fit on the val rows moves the floor; fit rows are never scored | both flags, verbalized, no `CONFIDENCE_ESTIMATOR`, a corpus run with `TARGET` and a local `EVAL_DATA`, and frozen val rows that are not corpus rows: the labeling round refuses before upload a fit row people labeled from the corpus or whose id is in a local `INPUT_DATA` (`references/troubleshooting.md`, Recalibration fit rows are corpus rows), and the job refuses any other at load, so it cannot run when the seed rows are corpus rows (a cold start) |

A corpus run with any of them labels with one model (`references/sdg-indexed-backend.md`, Panel); `JURY_MODELS` is ignored with a NOTE. A missing verbalized score sets `confidence_missing`, which the corpus run's review hand-off hides (`references/troubleshooting.md`, Run-time checks: Verbalized confidence missing, Reserved column name (option)). The report names the signal, the judges' calls and tokens, and the map with its effective floor.

### Numeric and generative tasks (ordinal, llm_judge, summarization)

These have no scalar label to vote. `ordinal` and `llm_judge` run one model that the
job resamples (the request names one model and `Routing`); `confidence` is the share
of the samples within tolerance of the shipped score (`samples`, `n_responders`,
`panel_size` on the row). `summarization` runs one model graded by `GRADERS`.
All three ship without an accuracy promise (`overview.md`, Limits): send them no
`TARGET`, and never quote a certified bound for them.

## Calibration - the job's certificate

Raw jury agreement *ranks* rows but is not a probability (0.8 agreement is not 80%
correct) or a guarantee. The job turns it into one when it has gold
(`EVAL_DATA`, the reserved test split or a people-labeled seed) and a target
(`TARGET`, 0.85 to 0.99): the share of the auto-accepted rows the customer wants
correct. The result is `labeling_summary.json`, which the submitter writes next to
`labeled_dataset.json` and the run report (`code_templates/run_report.py`) reads.

The job scores every gold row with the task's correctness rule (`HeldOutAccuracy`,
`HeldOutLowerBound95`, `HeldOutRows`; per-class figures in `held_out_report.json`), drops
the rows below the **agreement floor** of 0.75 (unless `CONFIDENCE_FLOOR_BYPASS`; with
`CONFIDENCE_RECALIBRATION` the floor reads the mapped confidence), and takes the **lowest**
confidence cutoff (`AcceptThreshold`) whose one-sided 95% lower bound on the accepted rows'
accuracy clears the target. The certificate is `AcceptedLowerBound95` on
`AcceptedHeldOutRows`; a null prediction among the accepted gold rows counts as an error.
The bound is not a guarantee against a noisy seed: gold that shares the models' wrong label
inflates it. A person may fix gold labels before the run (`references/label-review.md`,
`GOLDEN_REVIEW`); no model's label ever does. The arithmetic is the job's and its report
shows it.

`Status` says what the certificate is worth:

| `Status` | `StatusReason` | What ships |
|---|---|---|
| `Certified` | `spot_check_pending` | rows at or above `AcceptThreshold` auto-accept (`accepted: true`); the rest route; the spot-check is pinned |
| `NotCertified` | `target_not_met` | nothing auto-accepts: every row routes to review |
| `NotCertified` | `insufficient_eval_rows` | under 50 gold rows: every row routes |
| `NotCertified` | `no_eval_data` / `no_target` | no gold or no target: rows at or above the fixed 0.85 bar accept, with no accuracy promise |
| `NotCertified` | `task_not_certifiable` | ordinal, llm_judge, summarization: the 0.85 bar, no promise |
| `Partial` | (as above) | some rows have no labeled output (`RowsMissing`); re-attach or rerun before reading the certificate |

A target of 0.95 with under 100 gold rows gives a wide bound; the job and the
submitter warn. Use `EVAL_DATA = splits/test.jsonl` (Step 6's held-out split): the dev and
val splits chose the spec, so their rows would back the promise they helped pick. On a
standalone run the gold is the seed labeled by people.

**The spot-check.** A certified run, and a cold start with a target, pins a random
sample of the accepted rows (`SpotCheckRows`: 19 / 29 / 59 rows for a target of
0.85 / 0.90 / 0.95, fixed by the job id) into the review set as `split: spot_check`,
blind like every review row. `fold_review.py hil --job-summary` gives the verdict
when the export comes back: at `SpotCheckWithdrawAt` (7) or more errors the
certificate is withdrawn and the corpus job runs again after the fold. A run with
gold but no target still pins a spot-check sized for 0.90, and a failed one reads as
"the spot-check failed the bar". Full rule: `references/full-loop-review.md`, Step 7b.

**The 0.85 bar in votes.** A jury row's confidence is the agreeing jurors over the
panel size, so the fixed 0.85 bar of a run with no target is 3 of 3 on three jurors,
but 4 of 4 and 5 of 5 on four and five: every juror must agree, which is rarer on a
bigger panel, so more rows go to review. The labeling round warns when a
no-target corpus run has more than 3 models; tell the user before the run. With gold
and a `TARGET` the job fits the cutoff to the panel instead.

**Seed provenance.** The job certifies on gold a person produced. A gold row whose
`provenance` says a model wrote it (`auto_approved`, which an older seed's
`_bootstrap: self` maps to) is skipped before scoring, because it is correct by
construction and would inflate the bound. The job reads `provenance`, else
`_provenance`, else `_bootstrap`, and on an untagged row a `source` naming a model
(`jury`, `resample:<model>`, a Bedrock model id); the submitter sends a local seed's
gold rows with every one of those fields the row has. A seed made only of such rows certifies
nothing. Fit on rows people labeled: the customer's own seed or, on a cold start, the
random sample of `references/cold-start.md`.

**Per corpus.** The cutoff is chosen on this corpus's gold against this corpus's
confidence; never carry `AcceptThreshold` to another corpus, and never pass another
run's `labeling_summary.json` to the run report's `CALIBRATION` setting.

**One cutoff for every label.** The job sets one `AcceptThreshold` for
the whole corpus; there is no per-label cutoff, certified or hand-set. A skewed
label set can need one. When the labels' agreement differs a lot, tell the user the
single cutoff routes more of the easier label to review than it needs to. Do not
re-route rows on the client to get per-label behavior.

## Output and the review set

The labeled DataSet (registered under `DATASET_NAME`; the client holds its ARN, never its rows)
and the review DataSet (`REVIEW_DATASET_NAME`: the rows below the cutoff, `split: low_confidence`,
plus the spot-check, `split: spot_check`, blind and shuffled) are the job's; their shapes are in
`references/input-output-contract.md`, Outputs. A gold row that is also a corpus row ships the
person's label marked `_labeled_by: people` and is never routed or drawn for the spot-check. The
corpus run reads back only the review set's side file, `review.model_output.jsonl`, for the fold.
`RowsAccepted / RowsLabeled` is the coverage; `RowsRouted` plus `SpotCheckRows` is the review load.

Report to the user: the held-out accuracy and its lower bound, the certificate
(`Status`, the accepted rows' bound against the target), the coverage, how many rows
went to review, and the two DataSet ARNs. Then offer the review rather than deciding
for the user, as the Step 7a gate does (`references/full-loop.md`): fill the
hand-off spec with `hil_handoff.py` and activate **human-in-the-loop** (full-loop
Step 7a), or proceed with auto-accept. End a standalone run as the full loop does: after the
deliverables are verified (and registered), present the next-steps menu from
full-loop.md Step 11.

**Only the job routes.** The review set comes from the corpus job's `Routing`, never
from a client-side pass over the labels. A run without `REVIEW_DATASET_NAME`
has no review set; to review, run the corpus with it (with no `EVAL_DATA` and no
`TARGET` the job routes on the fixed 0.85 bar). The report shows the job's
`AcceptThreshold`.

## Honesty rule

Never present the jury agreement as accuracy. It is a confidence signal. The only
accuracy numbers the skill reports are the job's held-out figures on the reserved
test split (`HeldOutAccuracy` and its bound, macro-F1 for classification). Likewise,
only present the target as *met* when `labeling_summary.json` says `Status:
Certified` for THIS corpus's gold, and only until the spot-check verdict is in.
