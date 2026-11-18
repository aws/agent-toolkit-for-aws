# Demo Modes - configuring the few-shot approach

Few-shot demonstrations are labeled examples in the prompt. Demos come ONLY from the labeled seed the customer
provides (their K-per-class budget) - never from val or test - so this is fair
few-shot, not leakage. This file is the config surface: pick a mode per run.

## The two modes

| Mode | What the prompt gets | When to use | Relative strength |
|---|---|---|---|
| `none` (zero-shot) | spec + label set only | a run with no seed rows to draw demos from (a standalone apply of a frozen spec) | weakest |
| `fixed` (default) | the same K demos/class for every row | the default for any task with a labeled seed | the first demo per class captures most of the few-shot gain |

The labeling job takes one demo set for the whole run (the request's `Demos`, at
most 100 rows), so every row sees the same demos. There is no per-row retrieval
mode: it would read and embed the whole corpus client-side, which the skill does
not do (`references/sdg-indexed-backend.md`).

## How to choose (agent guidance)

Pick the mode automatically from the data - do not make the user choose:

- **Default: `fixed`, 1-2 demos/class** whenever a labeled seed exists: the first
  demo per class captures most of the gain, with no embedding model.
- **Many classes.** The 100-demo cap bounds K: with 60 classes, K is 1. Past
  that, the lever is the spec's decision rules (`references/spec-induction.md`),
  not more demos.
- **No labeled seed** (user has only a spec / use-case description) → build one
  first (`references/cold-start.md`); that seed then gets `fixed` like any other.
- **User asks for a specific K** → honor it, within the cap.

Demo count: more than ~2-3/class rarely helps and bloats the prompt. Start at 1-2.

## How to run each mode

The labeling round (`code_templates/labeling_round.py`) draws the demos itself: `DEMOS`
(`DEMOS`) names the labeled rows
to draw from (the DEV split only) and `DEMOS_PER_CLASS = K` (`DEMOS_PER_CLASS`) how many per class (K
rows per entity type on ner). The rows it draws are left out of that job's gold, so
a demo is never scored; they stay in the input, so a corpus row that is also a demo is
still labeled. `code_templates/seed_folds.py` Cell 3 (`demos.select_demos`, `DEMOS_MODE = "fixed"`)
previews the same draw.

```python
# fixed (recommended default): the job embeds K demos per class (labeling_round.py, Cell 1)
SPEC = "spec.md"; STAGE = "val"; INPUT_DATA = "splits/val.jsonl"
EVAL_DATA = "splits/val.jsonl"; DEMOS = "splits/dev.jsonl"; DEMOS_PER_CLASS = 2
OUT = "work/val_pred.jsonl"; PROJECT_DIR = "<proj>"; LABEL_SET = '[...]'; TEXT_FIELDS = "text"; ...
```

Preview what the job will draw (`seed_folds.py`, Cell 1 with `[DEMOS_OUT]` the preview file, then run Cell 3):

```python
LABELED = "splits/dev.jsonl"; DEMOS_MODE = "fixed"; DEMOS_PER_CLASS = 2; DEMOS_OUT = "work/demos.jsonl"
```

```python
# none (zero-shot): no demos (labeling_round.py, Cell 1)
SPEC = "spec.md"; STAGE = "val"; INPUT_DATA = "splits/val.jsonl"
EVAL_DATA = "splits/val.jsonl"; OUT = "work/val_pred.jsonl"; PROJECT_DIR = "<proj>"; LABEL_SET = '[...]'
TEXT_FIELDS = "text"; ...
```

## No-leakage rule (do NOT relax)

Demos must come only from the labeled **seed / dev** rows - never from the val
partition being scored or the reserved test partition. During refinement, draw
demos from the dev fold, not the val fold (`DEMOS = splits/dev.jsonl`). On the
corpus run, draw from the dev split too; the gold (`EVAL_DATA = splits/test.jsonl`)
stays disjoint. Always verify demos ∩ scored-partition = ∅; the submitter drops a
drawn demo from the job's gold so the check holds by construction.
