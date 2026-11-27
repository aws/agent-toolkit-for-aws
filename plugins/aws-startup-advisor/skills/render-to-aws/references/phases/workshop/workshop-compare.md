---
_fragment: compare
_of_phase: workshop
_contributes:
  - scenarios/index.json
---

# Compare workshop scenarios

Verify every manifest digest and reject any scenario whose inventory fingerprint differs from the index baseline. Compare at most five validated scenarios in byte-sorted scenario-ID order using identical columns: label, changed paths, selected-target changes, like-for-like known-cost floor, Balanced known-cost floor, Premium and Optimized totals, unpriced count, right-sizing delta, region note, complexity tier, and recommendation outcome.

Label floor totals as floors whenever unpriced lines exist. Flag target or recommendation flips and name the selector rule that caused each flip. Never compare a stale or partially written snapshot, never imply regional repricing, and never show a calculator link because `calculator_url` is null. Name any proposed eviction before it occurs.
