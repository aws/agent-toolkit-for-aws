---
_assemble: assemble-discover
_of_phase: discover
_reads:
  - detected code signals (scanned inline in discover.md Step 1)
_produces:
  - context-signals.json
---

# Discover — Assemble detected signals

> **Assembler unit.** The Discover phase scans the provided code path for
> framework / model / session / platform / Temporal signals and writes them to
> `context-signals.json` inline within `discover.md` (Step 2). This unit records
> the artifact-level contract for the phase: it is the single creator of
> `context-signals.json`, and its postconditions (declared on the phase) are the
> phase's completion gate. See `discover.md` § Step 2 for the mapping onto
> scoring keys and the determinism-boundary caveat (only high-confidence signals
> are written; everything else is left for Clarify).

**Unit confirmation (ONLY when the draft has more than one unit):** present the draft
inventory with AskUserQuestion — one option per proposed action (accept as-is / merge
two units / split a unit / rename) plus free-text via "Other". Apply the user's edits,
re-check the grouping rule, then write `units[]`. A single-unit draft is recorded
SILENTLY — no question, no mention (collapse invariant: single-unit runs see zero new
interaction).
