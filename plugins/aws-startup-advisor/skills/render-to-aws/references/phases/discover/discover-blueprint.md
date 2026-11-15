---
_fragment: blueprint
_of_phase: discover
_contributes:
  - render-resource-inventory.json
  - render-resource-clusters.json
---

# Discover from Render Blueprint

This `rw` fragment is file-only: the main window already ran `parse-render-blueprint.py` (see `discover.md` "Pre-dispatch main-window actions", Step 2) and listed its output in the active attempt manifest. Read only the manifest-listed `transport: blueprint` capture under `$MIGRATION_DIR/live-capture/`; never run the parser, the Render CLI, or any other command, and never read `render.yaml` directly.

Verify before contributing: the capture is `render-blueprint-normalized` with `schema_version` `1.0`, its SHA-256 digest equals the manifest `digest`, `structural_validation.status` is `valid` (the pinned official schema was applied before normalization), and its sanitized `local_reference_validation` state is present. Semantic evidence is current only when `outcome` is `valid`, errors are empty, the normalized source path and digest match, and its manifest identity digest plus attempt/workspace/consent tuple match the active capture manifest. Local broken references and explicitly invalid semantic evidence block canonical normalization. Absent or stale semantic evidence remains recorded as requiring renewed consent but does not block Blueprint-only Discover; when the Blueprint contributes to the inventory, it blocks Generate until the main window obtains current digest-bound validation. If any check fails, stop this contribution and report `WORKER_BLOCKED` rather than repairing the capture. Preserve the source digest, placements, canonical identities, references, controls, and sanitized validation state. Never persist literal environment values.
