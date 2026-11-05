---
_fragment: refresh
_of_phase: workshop
_contributes:
  - scenarios/index.json
---

# Refresh workshop scenario

If no scenario index exists, capture `scenario-001` from the current preferences, design, and estimate. Fingerprint the exact raw inventory bytes and store it as baseline and active; copy artifacts byte-for-byte into the scenario directory and record their SHA-256 digests.

Before every change, recompute the raw inventory fingerprint. On mismatch, abort with “Inventory changed since baseline. Re-run Discover before workshop reprice.” Apply only the selected preference patch and record only paths that differ from baseline. Run Design and Estimate as artifact-only inner operations: bypass only single-active-phase state transitions, not validation, selectors, evidence thresholds, or pricing freshness. The inner run emits no `HANDOFF_OK`, does not alter backbone completion/current phase/run mode, and does not recursively offer workshop.

Validate the new preferences, design, and estimate before assigning the next monotonic `scenario-NNN` ID. Snapshot atomically, compute artifact digests, update active scenario, and ensure working artifacts equal the active snapshot. If adding a sixth scenario, warn and name the oldest nonbaseline inactive victim before eviction; never evict baseline without explicit reset consent. Retain workshop in progress and proceed to compare.
