# Task types - classification, NER, summarization, QA, judge/ordinal

The skill labels several task shapes behind one route loop (split -> label -> score ->
refine -> gate -> apply). `TASK` (`TASK`) selects the shape on the labeling round
(`code_templates/labeling_round.py`; the job's `DatasetOptions.Type`, `labeling.<task>`) and the
scoring cell (`code_templates/score_and_select.py` Cell 2).
Splits, refine loop, held-out gate and confidence are shared; only the labeling
program the job runs (output contract), its correctness rule and the metrics
reported differ.

## The task table

Each task's prediction field and gold field live in the SDK's `sagemaker.ai_registry.data_preparer.auto_labeling.operators.job.request`
(`PREDICTION_FIELDS`, `GOLD_FIELDS`), read by the labeling round, the run report (`code_templates/run_report.py`)
and the scoring cell. The job scores the gold
itself (`HeldOutAccuracy` with the task's correctness rule, below); the scoring cell
re-scores a seed-sized file the job did not score, with every metric and no model
call. The loop steers on `HeldOutAccuracy` (val) for every task; the other metrics
are reported, never selected on.

| Task | `TASK` | Output per row | Job correctness rule | Reported metrics | Per-row confidence |
|---|---|---|---|---|---|
| Classification | `classification` | one label from a closed set | exact label (text-compared) | accuracy, macro-F1, per-class F1, confusion pairs | jury vote |
| NER / slots | `ner` | JSON `[{"type","text"}]` spans | same `(type, text)` span set | accuracy, entity micro-F1, per-type F1 | jury, per span |
| Summarization | `summarization` | free-text summary | none (graded by `GRADERS`) | the graders' good-rate (job only) | none (free text) |
| Extractive QA | `qa` | short answer span (string; empty = unanswerable) | SQuAD-normalized match, any gold answer | accuracy, token-F1, exact match | jury vote |
| LLM-as-a-judge | `llm_judge` | numeric score from a rubric spec | within tolerance of the gold | accuracy, QWK, Spearman, Pearson, MAE, adjacent | resample |
| Ordinal rating | `ordinal` | numeric rating on a fixed scale | rounds to the gold tier | accuracy, QWK, Spearman, Pearson, MAE, adjacent | resample |

**Multi-field input needs `TEXT_FIELDS`.** The default reads a single `text`
field. Any task whose rows are NOT a single `text` field must name the field(s) to
join or every prompt goes out empty - most commonly QA, whose input is
`TEXT_FIELDS = question,context`. An all-empty run is refused before any paid labeling
job; see `overview.md` for the full command. The table's rows are the fixed presets
(the six `TASK` shapes).

**Jury applicability (do not force a shape into classification).** The cross-model
jury only fits tasks with a discrete answer to VOTE - `classification`, `ner`,
`qa`. It does NOT apply to `summarization` (free text), `ordinal`, or `llm_judge`
(a continuous number). `ordinal` and `llm_judge` get per-row confidence from the job
**resampling** the one generation model (below and
`references/apply-and-confidence.md`); `summarization` has no per-row scalar
confidence, only the graders' good-rate. Routing summarization or ordinal through
`classification` to obtain a jury is a known failure mode - use their own `TASK`. These three ship without an accuracy promise
(`overview.md`, Limits): send them no `TARGET`.

## NER (typed span extraction)

Use when the goal is to pull typed entities/slots out of text - named entities,
form fields, transfer-instruction slots, PII fields.

- `LABEL_SET` is the set of **entity types**, not row labels.
- The spec defines each slot and its boundary rules (what to include/exclude,
  how to split full names, whether the currency symbol is separate from the amount).
- Output contract: `{"reasoning": ..., "entities": [{"type": <valid type>, "text":
  <exact surface string>}]}`, text-anchored so nothing relies on model-emitted
  character offsets. A span whose type is not in the Label Set is dropped before the
  vote.
- The job scores a row correct when its span set equals the gold's. A local
  re-score (the scoring cell, `TASK = "ner"`) adds span-level micro-F1 and per-type F1 (which
  slots the labeler misses). Per-type F1 is
  the analogue of per-class F1, so the refine loop reads it the same way.
- Confidence: jury per span (share of the panel emitting the same (type,text));
  the row's `confidence` is the mean over shipped spans and `min_span_confidence`
  the weakest, which the cutoff reads. A span a majority of jurors emitted but the
  first juror missed joins the shipped set at that share.

## Summarization (free-text)

Use when the output is a summary with no single correct string (clinical notes,
filings, support tickets).

- No closed label set - omit `LABEL_SET`. The spec's rules set the length.
- Output contract: `{"reasoning": ..., "summary": <the summary>}`.
- The job runs one model and grades a sample of at most 100 summaries with
  `GRADERS` (1 to 3 distinct model ids, none of them the labeling model,
  `Scoring.Graders`; required on every summarization job, refused for every other
  task) on three axes - faithfulness, relevance, completeness (1-5 each); the
  **good-rate** (`GoodRate`: a summary is good when every grader scored all three 4
  or more) is the primary. Summaries scoring below the threshold on any axis are the
  refiner's failures (hallucinated facts, dropped key points). There is no gold:
  the job refuses `EVAL_DATA` for this task.
- The graders run in the job only; the skill has no local judge, so a summarization
  file is not re-scored locally. Faithfulness is the axis a regulated domain cares
  about (no invented numbers).
- Reference-based ROUGE can be added as a cheap deterministic anchor alongside the
  judge, but the judge good-rate is the primary because surface overlap underrates
  a correct paraphrase.

## Extractive QA (answer span or abstain)

Use when each row is a question plus a context and the label is a short answer span copied from the context, or an empty answer when the context does not answer the question (SQuAD v2 style).

**QA rarely certifies on mixed answerable and unanswerable data.** The job certifies QA on one pooled exact-match rule and one cutoff for all rows, with no per-answer-kind certificate or relaxed match, and a pooled exact-match certificate rarely reaches a high target on a mixed corpus. Before the paid corpus run, tell the user that a corpus that mixes answerable and unanswerable questions will likely come back `NotCertified` (`target_not_met`) and auto-accept nothing, and offer a lower target (0.85 at the least) or labels with no accuracy promise. The job has one cutoff for every label too (`references/apply-and-confidence.md`, Calibration).

- Input needs `TEXT_FIELDS = question,context`. The gold field is `gt_answers`, a list of acceptable answers; `[]` means unanswerable.
- Output contract: `{"reasoning": ..., "answer": <the shortest exact answer span, or "" when unanswerable>}`.
- A local re-score (the scoring cell, `TASK = "qa"`) reports SQuAD token-F1 and exact match against the best gold answer.
- Confidence: a jury vote over SQuAD-normalized answers, so "Paris" and "the Paris." vote together; an empty answer is the "unanswerable" ballot.
- The job scores an answer correct on a SQuAD-normalized exact match against any gold answer (an empty answer is right only for an unanswerable gold), and certifies on that rule (`references/apply-and-confidence.md`, Calibration), so quote the certificate as an exact-match figure.

## Numeric scoring (llm_judge, ordinal)

Use when the output is a NUMBER, not a label: an LLM-as-a-judge rating from a
rubric (`llm_judge`, continuous) or an ordinal rating on a fixed scale (`ordinal`,
e.g. similarity 0-5). Both run the job's score program and are scored locally by
rank correlation against gold. The default `llm_judge` spec is an anchored rubric:
see **Judge tasks: the anchored rubric** below.

- **Field contract.** For `ordinal`, gold must be in the `gt_score` field and the
  prediction in the `score` field. Score the run with the scoring cell (`TASK = "ordinal"`)
  so it is graded by the ordinal rule (the prediction rounds to the gold tier), not
  exact match. It reads the
  preset fields, so pass `GT_FIELD = <name>` only when your gold lives elsewhere (a
  run where no row resolves gold fails loudly instead of scoring a silent 0.0).
- **Finish with the report.** An ordinal or llm_judge run is the same loop as any
  other task: label through the labeling round (the job scores the gold:
  ordinal is correct when the prediction rounds to the gold tier, llm_judge when it
  is within the tolerance of the gold), steer on the job's `HeldOutAccuracy`, and
  when the user wants the agreement metrics run the scoring cell (`TASK =
  "<ordinal|llm_judge>"`, `SPEC = <spec>`) on the seed-sized held-out split for QWK,
  Spearman and MAE (reported, never selected on; `SPEC` gives llm_judge the job's
  tolerance, 5% of the spec's scale; `[TOLERANCE]` overrides it), then run
  the run report (`code_templates/run_report.py`, `[PROJECT_DIR]` `<proj>`; full-loop Step 8, required for every task). Never rate rows yourself, in the
  chat or in a script you write, in place of these steps.
- Set the scale in the spec's Score Levels (`induce_spec.py`'s `SCORE_MIN` /
  `SCORE_MAX` write them); the job clamps every sample to it and bounds the
  prompt with it.
- **Output schema.** The job asks every model for one JSON object (`score`;
  `judge_score` for llm_judge), clamped to the scale. The spec side is in
  `references/labeling-spec-template.md` (Output Schema).
- Both steer on the job's `HeldOutAccuracy` (its row rule above). Quadratic weighted
  kappa, Spearman, Pearson, MAE and adjacent accuracy are reported by the scoring cell
  and never used to pick a spec: a rank metric can read 1.0 on a predictor that is
  off by one tier on every row.
- **String ordinal gold labels.** Ordinal ground truth is often TEXT tiers
  ("very negative", "negative", ...), not integers. The job compares a non-numeric
  gold as text against the number the model wrote, so such rows score wrong: map
  the tiers to their ranks in the seed BEFORE Step 1 (first Label Set entry = rank
  1), so every split carries numeric gold. For a local re-score of an existing file,
  the scoring cell's `--label-map '{"very negative": 1, "negative": 2, ...}'` or
  `SPEC` (ranks from the spec's **Label Set ORDER**) applies the same map. If a
  gold label is non-numeric and neither a `--label-map` entry nor a Label Set
  position covers it, scoring FAILS with a clear error naming the labels that need
  a mapping - it does not silently drop those rows. Lookups are case-insensitive.
- **Confidence is a resample, not a jury** (there is no label to vote): the job
  samples the one generation model several times (the request names that one
  model and `Routing`) and scores confidence as the share of
  samples within a tolerance of the shipped value; the tolerance is 5% of the
  spec's scale (exact agreement on a 1-5 scale, +/-5 on 0-100). The job runs
  `GENERATION_MODEL_ID` alone for these tasks; the submitter ignores
  `JURY_MODELS` and says so. The rows carry `samples`, `n_responders` and `panel_size`.

## Judge tasks: the anchored rubric

**The anchored rubric (default for `llm_judge`).** The spec is an anchored rubric (`references/labeling-spec-template.md`, Score Levels); `code_templates/induce_spec.py` (`TASK = "llm_judge"`) writes it (see `references/spec-induction.md`). It is the strongest lever on judge quality, so the labeling round with `TASK = "llm_judge"` warns before any spend when the spec has no anchored levels. For `ordinal` the rubric is optional.

How to choose:

- **`llm_judge`:**
  - **Spec.** Always use the anchored rubric.
  - **Model.** One model, named as `GENERATION_MODEL_ID`, an id the service accepts. A stronger model is the user's call: recommend it when closer agreement with the gold scores is worth its cost, and state it, with its cost multiple, in the HARD RULE #2 approval summary (`references/full-loop.md`).
  - **Confidence signal.** The job's resample agreement ranks rows for review. llm_judge has no accuracy promise (`overview.md`, Limits), so the job routes on the 0.85 bar and reports `NotCertified`; do not report a certified bound for it.
  - **Score scale.** If the judge's raw scores run high or low against the gold, map them onto the gold scale with a monotone fit on the dev split before checking agreement within a tolerance.
- **Judge-style classification (faithfulness, hallucination):** it is a `classification` run: the jury votes the verdict and the job certifies it. When the user's target is high (such as 0.95) and they want a stronger model, put it on the jury as one of the 2 to 5 `JURY_MODELS`, and state it, with its cost multiple, in the HARD RULE #2 approval summary (`references/full-loop.md`). By default a single model cannot certify (the job votes 2 to 5 jurors); the opt-in confidence options are the exception (`references/apply-and-confidence.md`).
- **One rubric sample per row.** Pairwise judging and extra samples cost more.

## The `TASK` family (the templates' `TASK` setting)

The lever templates take a `TASK` setting (the `TASK` flag). The labeling round auto-detects
the task when `TASK` is `None` (an explicit `TASK` overrides; an
`ask`-tier pick with confidence < 0.5 fails closed): see the full detection contract
in `references/full-loop.md` (Step 0.5). The scoring cell takes an explicit `TASK`.
`induce_spec.py` and `seed_folds.py` (folds, Cell 2; demos, Cell 3)
default to `classification`. The accepted values differ by template,
because not every task exercises every lever:

- the labeling round: `classification | ner | summarization | qa | llm_judge | ordinal`
  (the full set). The scoring cell: the same minus `summarization` (graded in the job).
  `llm_judge` and `ordinal` share the job's score program.
- `induce_spec.py`: `classification | ner | llm_judge | ordinal`. For `llm_judge` / `ordinal` it induces an anchored rubric (Score Levels with dev-row examples) and takes `SCORE_MIN`, `SCORE_MAX` and `ANCHORS_PER_LEVEL` (1 or 2) instead of `LABEL_SET`; the gold field defaults to `gt_score`. summarization and qa have no induction.
- `seed_folds.py` Cell 2: `classification | ner` (stratified folds are defined for these; summarization/qa/judge/ordinal use an injected judge or open output, not a fixed label/entity set).
- `GRADERS = <ids>` (`GRADERS`) on the labeling round (summarization only): 1 to 3 grader model ids.

NER-specific settings:

- `TASK = ner` — on `induce_spec.py`, the labeling round, the scoring cell and
  `seed_folds.py`. Selects the job's entity program
  (`labeling.ner`), the entity-F1 scorer, the per-span jury vote, and rarest-type
  stratified splits. The gt field is an entity list (`GT_FIELD = gt_entities`).
- `--annotation-scope {exhaustive,notable}` (`ANNOTATION_SCOPE`) — on `induce_spec.py` (ner only).
  **exhaustive** (default): induce rules to tag every mention that matches a type —
  no behavior change, use for exhaustively-annotated corpora (CoNLL). **notable**:
  induce a knowledge-base-linked scope rule (tag only notable entities; skip generic
  common-noun mentions) — use for selectively-annotated corpora (MultiNERD). Example value: `--annotation-scope notable`.
- `--per-type-tol <float>` (`PER_TYPE_TOL`) — on the select cell (`score_and_select.py` Cell 3). Per-type do-no-harm floor:
  reject a refined spec that regresses any passing type by more than the tolerance
  (e.g. `--per-type-tol 0.03`). No-op when per-type breakdowns are absent.

## Dependencies

The scoring cell makes no network or model call. Spec induction's
one-shot Converse call (the SDK operator `sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec.induce`,
which holds a boto3 `bedrock-runtime` client) is the only direct Bedrock call in the skill;
labeling, the confidence jury, the held-out score, the graders and the certificate run
inside the labeling job (`references/sdg-indexed-backend.md`). The anchored-rubric
helpers (`sagemaker.ai_registry.data_preparer.auto_labeling.operators.spec.rubric`)
make no network call either.
