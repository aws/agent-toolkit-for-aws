# Spec Induction (cold-start the rules from the labeled seed)

When the spec has a label set and one-line definitions but **no decision rules**
(or weak ones), and a labeled seed exists, induce the rules from the seed before
labeling: write them up front from the labeled examples, then let the refinement
loop sharpen them. This is the skill's strongest lever on real policy tasks.

## What induction does and does not do

- Induction takes the **label set as input** and writes the **rules**. It never
  invents labels.
- The label set + one-line definitions come from the user's spec, or from the
  in-skill authoring step when they had none (`references/spec-authoring.md`).

## When to run it

Run induction when ALL of these hold:

- a labeled seed is available (a few rows per class), AND
- the provided spec has no rules / only label definitions, OR labels are inconsistent
  on a first pass (a sign the rules are too thin).

Skip it when the provided spec already has good, specific rules - go straight to the
refine loop. Induction is A/B-gated (below), so it can only help, but skipping saves a
Bedrock call.

## How (leakage-safe A/B)

1. **Use the frozen split** (`references/full-loop.md`, Step 1): `splits/dev.jsonl` is the
   INDUCE pool and `splits/val.jsonl` the SELECT pool.
2. **Induce rules** from dev only: `code_templates/induce_spec.py`, with

   | Placeholder | Value |
   |---|---|
   | `[SEED]` | `splits/dev.jsonl` (the INDUCE pool) |
   | `[LABEL_SET]` | `'["TP","FP"]'` |
   | `[TASK_HINT]` | `"Classify auto parts: TP = defeats emissions controls, FP = compliant."` |
   | `[TEXT_FIELDS]` | `text` |
   | `[OUT]` | `work/induced_spec.md` |
   | `[PROJECT_DIR]`, `[REGION]`, `[SKILL_ROOT]` | the project, the model's region, the active skill root |
   | `[MODEL]` | the reflection model: an inference profile id from `aws bedrock list-inference-profiles REGION <region> --query 'inferenceProfileSummaries[].inferenceProfileId'` (a current Claude Sonnet profile writes the best rules) |
   | `[SCORE_MIN]`, `[SCORE_MAX]` | `llm_judge` / `ordinal` only: the low and high ends of the score scale, e.g. `1`, `5` (required there; else `None`) |

   On a rerun of induction after the user accepted the reply-keys line
   (`references/offer-options.md`), set `REPLY_KEYS_LINE = True`; it is off by default.
   Write the induced candidate and every A/B intermediate under `work/`, never as an
   `*_induced.md` beside `*_labeling_spec.md`: the customer sees only the final spec.
3. **A/B on val**: label `splits/val.jsonl` with the provided spec and with
   `work/induced_spec.md` (the labeling round); each job reports its own
   `HeldOutAccuracy` in `held_out_report.json` (no local re-score).
4. **Keep the winner** with `code_templates/score_and_select.py` Cell 3 and `MIN_GAIN = 0.03`: the induced spec
   ships only if it beats the provided spec by at least 0.03 on the SELECT pool, on
   each val job's `HeldOutAccuracy` (the job's row rule for the task; the scoring cell
   reports the same number as `primary`, with macro-F1, QWK, Spearman and the other
   metrics beside it, reported and never selected on); otherwise the provided spec
   ships. (Set `MIN_GAIN = 0.03` explicitly; the
   template's bare default is smaller.)
5. Promote the winner to the full loop's starting spec, `<proj>/work/labeling_spec_iter_0.md`
   (refinement then writes `labeling_spec_iter_1.md`, …); the other A/B
   intermediates can be discarded. The customer reviews only the shipped iter,
   copied to `<label-field>_labeling_spec.md`.

The TEST set is never touched in induction or A/B. seed ∩ test = 0.

## Why it works

Where the provided spec is generic, induction writes the discriminating rules the
data shows. Where the spec is already strong, the A/B
keeps the original. The A/B runs on your own held-out seed, so the win is measured on
your data.

## Numeric judge tasks: induce an anchored rubric

For `llm_judge` (and optionally `ordinal`), induction writes an **anchored rubric** (`references/labeling-spec-template.md`, Score Levels), the default spec structure for a judge. There is no label set to pass; pass the scale and the numeric gold field instead:

```python
# induce_spec.py, Cell 1
TASK = "llm_judge"; SEED = "splits/dev.jsonl"
GT_FIELD = "gt_score"; SCORE_MIN = 1; SCORE_MAX = 5; ANCHORS_PER_LEVEL = 2
TEXT_FIELDS = "article,candidate"; OUT = "work/induced_spec.md"
TASK_HINT = "Rate the summary of the source article for overall quality."
```

- **Anchors come from `dev` only.** Each dev row goes to the score level nearest its gold score, and the rows closest to each level are the anchors (the SDK's `operators.spec.rubric`). They are quoted into the spec, so a val or test row used as an anchor would leak its own gold into the prompt.
- **Missing levels are reported.** A level with no dev row near it is defined from the scale alone; the template warns so you can add seed rows at that score. A 0-100 scale is cut into 5 bands, one level per band.
- **The same A/B applies.** Label `val` with the provided spec and the induced rubric and keep the induced one only if it wins on the step 4 metric.
- **The default for `llm_judge`.** It is the default judge spec structure (`references/task-types.md`, **Judge tasks**). the labeling round with `TASK = "llm_judge"` warns, before any spend, when the spec has no anchored Score Levels.
- **ordinal is optional.** An ordinal spec whose gold labels are text tiers still needs its Label Set order (`references/task-types.md`), so keep the Label Set there and add Score Levels only for numeric gold.
