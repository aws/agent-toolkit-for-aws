# Spec Refinement

The refinement loop: read where the labeler is wrong, edit the spec to fix it
*without breaking what already works*, and keep only edits that improve held-out
score.

This workflow can run standalone ("refine my spec against this dev set") or as
Step 5 of the full loop. It needs a dev split (refiner signal), a val split
(per-iteration gate), and - for the final number - a reserved test split.

## The refiner's job each iteration

You are given, for the current spec:

1. The **per-class breakdown** on val - which classes pass, which fail (the val
   job's `held_out_report.json`).
2. **The dev job's failures** - `<out>.failures.jsonl`: every dev row the job got
   wrong against the gold, plus two rows per gold class it got right (`correct:
   true`), each with the gold, the prediction and the labeler's own reasoning: the
   richest signal, since it shows *why* the labeler misroutes. Read failures from dev
   only, never from val (reading val rows would leak the steering signal). The job
   writes this file; the skill never re-scores the rows itself.
3. **What's already working** - correctly-labeled rows for healthy classes, so
   you can write positive carve-outs instead of accidentally flipping good rows.
4. The **dev-vs-val gap** per class. A large positive gap (dev ≫ val) means
   a rule is memorizing the batch and will hurt the test set - a candidate to
   delete, not keep.

You produce an edited spec, or you decline to edit.

## Rules (these are the guardrails; do not relax)

1. **At most 3 edits per iteration.** Small, attributable changes. Large
   rewrites are unattributable and regress silently.
2. **Protect passing classes.** Any class already at or above the gate must not
   be made worse. Prefer carve-outs ("when the text mentions X, prefer A over
   B") over broad rule changes.
3. **"Make no change" is valid.** If no edit is clearly supported by the
   confusion evidence, say so and stop. A spec that already works needs no edit.
4. **Ground language in the evidence.** Write carve-outs using phrases drawn
   from the actual misclassified texts, not abstract instructions.
5. **Delete overfit rules.** If a rule shows a large dev≫val gap, removing it
   is a legitimate edit.

## Loop control

- **Rotate val folds.** Before the loop, run `code_templates/seed_folds.py` Cell 2 (`kfold.build_kfold`) to build K
  stratified folds (default K=4) **from the dev+val rows only** - never the reserved
  `splits/test.jsonl`, which stays sealed for the final held-out gate. Pass a file of the
  dev and val rows (under `work/`) as `LABELED`, with `[FOLDS_OUT_DIR]` `<proj>/work/folds`; with a frozen split the guard refuses
  any test row in it (a seed with no frozen split: `[EXCLUDE]` its reserved test JSONL, whose rows the folds drop), and a file its `manifest.json` lists unchanged may be a dev or val round's input (no other mix of dev and val may). On iteration *i*, use
  fold `i % K` as val and the other folds as dev (the script pre-builds the
  `iterN_dev.jsonl` / `fold_N.jsonl` pairs and a manifest). Rotating val stops the
  refiner memorizing one split and averages out val-selection noise, which at high
  class counts (e.g. 151 intents, a few val rows each) makes a single val draw rank
  specs unreliably.
- After each edit, run **both** the dev and the val job with the new spec, each
  with its own fold as `EVAL_DATA`, so the job scores it. The dev failures drive the
  next edit; the val accuracy (`HeldOutAccuracy`) is the metric you gate and roll
  back on (`val_macro_f1` is recorded beside it for classification). Write
  each iteration's val predictions to `work/val_pred_iter_{N}.jsonl` (do not
  overwrite one file).
- Track every iteration's `{spec, val}` in a scores file, each spec in its own
  file under `work/` (`<proj>/work/labeling_spec_iter_0.md` initial/bare,
  `<proj>/work/labeling_spec_iter_1.md`, …; `spec_select.iter_spec_name(n)` (the SDK's `operators.spec.select`) produces
  the name), its path in the row's `spec`. Stop when the gate is met, val fails to
  improve for an iteration, or the iteration cap is reached (default 4).

## Selecting which spec ships

Do not decide by eye. Feed the per-iteration scores to
`code_templates/score_and_select.py` Cell 3 (`select_spec`), which applies both guardrails deterministically:

- **Best-iter rollback** - ship the spec with the highest val, never the last.
- **Val do-no-harm floor** - if the best refined spec does not beat the initial
  spec on the **val split** by at least `MIN_GAIN`, ship the initial spec
  (selection is on val, never the reserved test split).

```python
# score_and_select.py, Cell 1 (then run Cell 3)
SCORES = "scores.json"
DECISION_OUT = "decision.json"
```

`<proj>/scores.json` shape: `{"initial": {"spec": "work/labeling_spec_iter_0.md", "val": 0.88},
"iters": [{"spec": "work/labeling_spec_iter_1.md", "val": 0.92}, ...]}` - use the
iter-suffixed names so `decision.json` references the exact files.
`decision.json` echoes the shipped iter's basename as `shipped_spec_file`.

`val` is each iteration's `HeldOutAccuracy` from its val job's `<out>.summary.json`;
refinement rounds run one model, so there is no jury agreement to shortlist on and
the gold gate is the only selection.

## In-job search (`OPTIMIZER`, opt-in, off by default)

The labeling round with `STAGE = "optimize"`, `INPUT_DATA = <dev+val file>`, `EVAL_DATA = <the same file>` and `OPTIMIZER = '{"Mode": "protegi", "Elicitation": "plain"}'` runs the in-job search inside one refine-round job, in place of Steps 4-5's refine rounds, then labels the rows with the pick. Build the file from `<proj>/splits/dev.jsonl` and `val.jsonl` (each gold row is tagged `optimizer_split`; test is never sent). Needs classification, a local `EVAL_DATA` with at least 10 dev and 20 val gold rows, no `DEMOS` and no judge or panel. Send `"Elicitation": "plain"` (without it the request asks for confidence, run as plain unless `CONFIDENCE_METHOD` is stated or verbalized). Optional keys: `TeacherModel` (`{"ModelId": "<an id the service accepts>"}`; without it the service picks its default teacher; billed), `Seed`, `Parser` (`salvage`, `lenient`). The pick is `<out dir>/job/optimize/spec.md`; the summary's `Optimizer` block has the val gain (chosen on val, not a held-out gain) and the teacher's calls and tokens. Quote it as `references/offer-options.md` says, and never quote the optimize stage's held-out report (its gold is dev and val). ⏸ After the user's second yes, record it with the run's `optimizer_pick` values and adopt the pick; Step 6 then ships it with the `adopt_pick` template's `ship` action:

```bash
python <skill-root>/references/directory-management/scripts/run_log.py write --project-dir <proj> \
    --kind approval --step optimizer-adopt --iteration 0 --status approved \
    --field optimizer_pick_sha256='"<optimizer_pick.sha256>"' --field job_name='"<optimizer_pick.job_name>"'
```

then `code_templates/adopt_pick.py` with `[ACTION]` `adopt-job`, `[PROJECT_DIR]` `<proj>`, `[PICK]`
`<out dir>/job/optimize/spec.md` and `[APPROVAL]` the approval entry id.

### Cost of the in-job search

The search labels about `10*val + 21*min(dev, 32) + 42*min(dev, 64)` rows and makes 63
teacher calls: 21 workers over 3 rounds (3 in round 1, then 3 for each of the beam's 3
specs in rounds 2 and 3), each critiquing `min(dev, 32)` rows and making 2 candidates
scored on `min(dev, 64)` rows from 3 teacher calls, plus 10 val passes (a baseline and the
beam of 3 each round). A worker retries up to 3 attempts, which adds up to
`42*min(dev, 32)` rows and 126 teacher calls. The coefficients change if `Mode` or the
container's search constants change. `references/offer-options.md` says what to show at
the pause.

## Final gate

The per-iteration val score is the *steering* signal, not the *reported* number.
The reported number comes from the **reserved test partition** (never seen by the
refiner), scored by the corpus job (`EVAL_DATA = splits/test.jsonl`) with the shipped
spec (`references/full-loop.md`, Step 6).

## Why held-out, not training score

Refining against rows the labeler was tuned on rewards memorization: the spec looks
great and generalizes poorly. The loop only trusts a score from data the labeler did
not see; preserve that through any port.
