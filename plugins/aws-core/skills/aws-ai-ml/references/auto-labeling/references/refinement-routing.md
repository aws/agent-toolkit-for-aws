# Refinement Routing - when to refine vs. accept

Refinement on too thin a signal overfits; skipping it when a class is clearly
failing leaves accuracy on the table. This reference encodes the decision for the
agent and the `planning` skill.

## The decision

**Global val-size floor (check first).** If the val partition has fewer than
~5 rows per class on average, **do not refine at all**: the val signal is too
noisy to rank specs, and a refined spec that "wins" on this draw routinely loses on
held-out (the val do-no-harm floor and val-fold rotation guard against that, never the
reserved test split). Ship the initial spec and tell the user reliable refinement needs more
labeled examples (raise K), or use `code_templates/seed_folds.py` Cell 2 to pool folds for a
larger effective val. Only use the table below once the floor is cleared.

After the val job has scored the current spec (`HeldOutAccuracy`, the steering
metric; `val_macro_f1` and the per-class figures ride along in `<proj>/scores.json`),
choose one:

| Condition | Action |
|---|---|
| Val accuracy **≥ gate** AND no class below gate | **Accept.** Do not refine. Go straight to the held-out gate + apply. |
| A class is **below gate** AND the confused classes have **≥5 val rows** between them | **Refine.** There is enough evidence to carve a rule. |
| A class is below gate BUT confused classes have **<5 val rows** | **Do not refine - surface it.** Too little signal; the refiner would memorize. Tell the user the class is under-sampled and recommend more labeled examples or merging classes. |
| Spec already refined and val score **did not improve** last iteration | **Stop.** Ship the best-seen spec. |

You check the val-size floor and the confused-class row count above before
refining; the select cell (`code_templates/score_and_select.py` Cell 3) takes no row or class counts. It enforces the
rollback and the do-no-harm floor (best-iter rollback + val do-no-harm floor) - use it
to pick the shipped spec rather than deciding by eye. See `references/spec-refinement.md`
"Selecting which spec ships".

## Gate defaults by task

The gate is the val accuracy a spec must reach to be accepted without further
refinement. Suggested starting points:

| Task | Gate |
|---|---|
| Topic / intent classification | 0.85 |
| NLI-style relational | 0.80 |

These are defaults, not laws. If the user has a quality bar, use theirs.
(Thresholds shown are for classification; NER, QA and ordinal / judge jobs score
their own correctness rule into the same `HeldOutAccuracy`, and summarization is
graded by its graders - see `references/task-types.md` and `references/input-output-contract.md`.)

## Why this lives in the plan, not just the skill

The `planning` skill relies on this internal refine/accept gate, so a plan does not
insert a separate "improve labels" step or run labeling before a confirmed seed
exists. Consequences for a plan:

- Auto-labeling is **self-gating** - it decides internally whether to refine.
  A plan should not add a manual "review and improve the spec" task around it.
- Auto-labeling **must follow** ground-truth intake (a confirmed seed must
  exist), except on a cold start, where auto-labeling runs first and builds the seed
  through human-in-the-loop (`references/cold-start.md`). It authors the spec itself when the user has none
  (`references/spec-authoring.md`), so a separate spec-creation step is not a
  prerequisite.
- Its outputs (the labeled DataSet ARN, `held_out_report.json`) are inputs to
  `dataset-transformation` and a signal for `dataset-quality`.

## The non-negotiable

Whatever the routing decision, the **reported** quality number always comes from
the reserved test partition, and the spec that ships is the best-scoring one on
held-out data - never the last one tried, never a training-set score.
