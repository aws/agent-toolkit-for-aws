---
_assemble: assemble-add-capabilities
_of_phase: add-capabilities
_reads:
  - current runtime + selected capabilities + native-vs-BYO choices (collected inline in add-capabilities.md)
_produces:
  - capabilities-recommendation.md
---

# Add Capabilities — Assemble the recommendation

> **Assembler unit.** The Add Capabilities branch asks the current runtime and
> the capabilities needed, resolves native-vs-bring-your-own per capability,
> verifies volatile facts, and writes `capabilities-recommendation.md` inline
> within `add-capabilities.md` (Step 5). This unit records the artifact-level
> contract for the branch: it is the single creator of
> `capabilities-recommendation.md`, and its postconditions (declared on the
> phase) are the branch's completion gate. This is a self-contained sidebar
> branch — no runtime scoring, no handoff; it ends after writing the file. See
> `add-capabilities.md` § Step 5 for the document contents.
