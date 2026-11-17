# Taxonomy Guidance - fix the label set before refining

No refinement can carve a stable rule for a class with almost no examples, or for
two classes that genuinely overlap. Fixing the taxonomy is cheaper and more
effective; check it before running the loop.

## Programmatic pre-check

`code_templates/inspect_inputs.py` Cell 4 (`taxonomy_gate.gate`) encodes the checks below as a deterministic gate: run
it before the first token-spending run (Step 0.6 in `references/full-loop.md`). It
flags absence-defined classes, seed coverage and imbalance, and lexically
overlapping class pairs, and returns a `proceed` / `review-before-spend` decision
(or `skip` for a non-classification task with no label set to check). The rest of
this doc is what to do with those flags; the gate only surfaces them.

**Overlap check is lexical.** It scores Jaccard token overlap of each class's name
and definition (`separability.method: "lexical"`). It catches near-duplicate wording
but misses synonyms with no shared tokens ("joy" vs "elation"), so a clean result
does not prove the classes are separable. If overlap matters, use the confusion pairs
from the first score (below).

## When to merge or restructure

Merge or restructure classes when, in the labeled seed:

- Any class has **fewer than ~10 labeled rows** - the refiner can't build a rule
  from <5 val rows after splitting.
- Two classes **systematically overlap** (e.g. "love" vs "joy", "neutral" vs a
  faint sentiment) - the confusion pairs will show them swapping both ways.
- The class balance is severe: `min(per_class) / max(per_class) < 0.25`.

## What merging buys

Collapsing genuinely-overlapping fine classes into a coarser, well-separated set
raises held-out macro-F1 with **no code change** - the gain is from removing an
unresolvable distinction, not from a better rule.

## How to handle it in the conversation

1. After the split + first score, inspect per-class counts and the confusion
   pairs.
2. If a class trips a rule above, **tell the user before refining**: name the
   under-sampled or overlapping classes and propose a merge or a request for
   more labeled examples.
3. Let the user decide - they own the taxonomy. ⏸ If they merge, update the spec's
   label set; a merge changes test labels, so it needs a new project and freeze
   (`references/full-loop.md`, Step 1).

## The ordinal exception

Inherently ordinal tasks (e.g. 5-point sentiment) err mostly off-by-one-tier, a
real accuracy ceiling that merging would paper over. Don't force a merge: report the
ceiling and, if the use case allows, offer an adjacent-tier-tolerant scoring policy. Distinguish "overlapping classes" (merge)
from "ordinal neighbors" (ceiling) using the confusion pairs: overlap swaps both
directions symmetrically; ordinal error clusters on adjacent tiers.
