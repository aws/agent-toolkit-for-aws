# Spec authoring (in-skill)

Auto-labeling owns its labeling spec end to end: the label set, the one-line
definitions, the decision rules, and the output contract. When the user has no
spec, draft one here with them; do not depend on a separate spec-creator skill.

A labeling spec has five parts (full template: `references/labeling-spec-template.md`;
worked example: `references/sample-labeling-spec-classification.md`):

- **Input Data** - the unlabeled corpus (source, input field, size, domain).
- **Labelled Seed** - the K-per-class labeled rows (source, ground-truth field,
  default `gt_label`). Required for the full loop and refinement; absent for
  apply-only (frozen spec + confidence). See `references/input-output-contract.md`.
- **Label Set** - a flat, mutually exclusive list of class names, each with a
  one-line definition of when it applies (Score Levels instead for `llm_judge` and a
  numeric `ordinal` scale, below). If two labels can both apply to one
  record, that is a taxonomy problem, see `references/taxonomy-guidance.md`.
- **Labelling Rules** - one short decisive-signal rule per label, plus a
  disambiguation line where two labels are easily confused. These can start
  minimal: induction writes them from the seed and the refinement loop hardens
  them against held-out failures (see below).
- **Output Schema**: the labeling job's own reply format, restated
  (`references/labeling-spec-template.md`, Output Schema).

For a numeric judge task (`llm_judge`, optionally `ordinal`) the Label Set is replaced by **Score Levels**, an anchored rubric (`references/labeling-spec-template.md`, Score Levels). It is the default structure for an `llm_judge` spec; draft the level definitions with the user, then let `code_templates/induce_spec.py` (`TASK = "llm_judge"`) pick the anchors and write the rationales (`references/spec-induction.md`, "Numeric judge tasks").

## When the user has no spec

Gather the label set and a one-line definition per label through a short
conversation: what is being labeled, why, and the classes. Infer what you can
from the JSONL first.

**Start from the template, keep ALL required content.** Read
`references/labeling-spec-template.md` and write `labeling_spec.md` by filling
it in - do NOT free-form a spec from scratch. The downstream scripts parse this
structure, so dropping a required piece breaks the pipeline. Match the template's
heading hierarchy exactly: keep every section the template has, and fill these
three required top-level sections (two with subsections):

1. **`## Input Data`** - source path, input field name, corpus size (record the
   row count here; above the row limit in `overview.md` Limits, do not author a
   spec to run as-is, and tell the customer what full-loop Step 0 says); and under it
   **`### Labelled Seed`** - seed path, ground-truth field (`gt_label`), size
   (required for the full loop and refinement).
2. **`## Labelling Configuration`** - and under it **`### Label Set`** (the flat
   class list, one-line definition each) and **`### Labelling Rules`** (a first
   pass; induction/refine harden these later).
3. **`## Output Schema`** per `references/labeling-spec-template.md`, plus the
   deterministic verification block.

Write the spec file from the draft; the user approves it in the HARD RULE #2 summary
(`references/full-loop.md`) before any labeling run. (Worked example:
`references/sample-labeling-spec-classification.md`.)

The rules need not be complete on the first draft. Two paths fill them:

- **Induction** (`references/spec-induction.md`): if a labeled seed exists and
  the rules are thin, induce them from the seed and A/B against the draft, keeping
  the winner.
- **Refinement** (the full loop): the loop hardens and expands the rules against
  held-out failures over a few rounds.

So the first draft need only get the label set + definitions right and an honest
first attempt at each rule. The accuracy comes from the **rules** (induced, then
refined), the validated part of the skill; drafting the label set is a convenience
that gets a usable spec in front of that loop.

## When the user already has a spec

Consume it as-is. Map its sections to the five parts above; if it carries the
label set and definitions, return to the full loop (`references/full-loop.md`) at
the step that sent you here, inducing or refining the rules from Step 1b on.

## Every label needs a definition (confirm with the user)

A spec the customer already has (an SOP, a policy doc, a runbook) often never names the labels they want. Before any labeling run, check that each label in `LABEL_SET` appears in the spec. The labeling round does the same check (case-insensitive whole word) and prints `WARNING: label(s) ... are never mentioned in the spec`, but by then the run is about to spend, so do it here first.

For each missing label you MUST:

1. Draft a one-line definition of when the label applies, from the spec text and, when one exists, the labeled seed (what the seed rows with that label have in common).
2. Add the drafted definitions to the spec's `### Label Set`, one line per label, marked as drafted.
3. Show them to the user in the HARD RULE #2 summary (`references/full-loop.md`) and get an explicit yes before any labeling run. A drafted definition is not confirmed until the user says so; the user owns what the labels mean.

If the user cannot define a label, that is a taxonomy problem, not a wording one (`references/taxonomy-guidance.md`).

## After the spec exists

Return to `references/full-loop.md` at the step that sent you here (Step 0).
