---
_assemble: assemble-estimate
_of_phase: estimate
_reads:
  - design.json + cached rate anchors (combined inline in estimate.md)
_produces:
  - estimate.json
---

# Estimate — Assemble estimate.json

> **Assembler unit.** The Estimate phase reads `design.json`, applies the layered
> pricing source (cached anchors), computes a coarse
> monthly magnitude, and writes `estimate.json` inline within `estimate.md`
> (Step 4). This unit records the artifact-level contract for the phase: it is
> the single creator of `estimate.json`, and its postconditions (declared on the
> phase) are the phase's completion gate. See `estimate.md` § Step 4 for the
> estimate.json shape (monthly_magnitude_usd, pricing_source, assumptions, note)
> and the magnitude-only determinism caveat.
