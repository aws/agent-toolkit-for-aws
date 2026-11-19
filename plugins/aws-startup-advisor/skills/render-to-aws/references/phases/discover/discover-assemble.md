---
_assemble: assemble-discovery
_of_phase: discover
_reads:
  - blueprint
  - live
  - app-code
  - billing
_produces:
  - render-resource-inventory.json
  - render-resource-clusters.json
  - { file: ai-workload-profile.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
  - { file: render-ai-discovery.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
---

# Assemble discovery

This `rw` assembler is file-only. The main-window pre-work already ran `normalize-render-capture.py` (see `discover.md` "Pre-dispatch main-window actions", Step 3) and recorded `status: ok` in `$MIGRATION_DIR/live-capture/normalize-result.json`; the assembler never runs it. The assembler reads `render-resource-inventory.json`, `render-resource-clusters.json`, and, when present, `ai-workload-profile.json` and `render-ai-discovery.json`, and cross-checks them against the manifest-listed captures the fragments read:

- `normalize-result.json` carries this attempt's `attempt_id` and `status: ok`, and its `inventory_digest` and `clusters_digest` equal the SHA-256 of the exact artifact bytes on disk.
- `discovery_sources` equals the set of manifest transports mapped to `render_cli`, `render_rest`, `render_blueprint`, `application`, and `billing`.
- `clusters.inventory_fingerprint` equals the SHA-256 of the canonical inventory bytes.
- Every manifest `digest` matches its capture file.
- The AI artifacts exist if and only if the application capture carries `ai_profile`; both AI output paths are always passed to the normalizer, which writes or removes them atomically in the same transaction as the inventory and clusters, so no stale AI artifact can survive a non-AI rerun.

If any cross-check fails, do not patch an artifact: report `WORKER_BLOCKED` and leave the files unchanged for the main window's diagnostic.

The normalizer implements the following contract, which the assembler verifies in its outputs. It accepts only manifest-listed files whose digests match. Live manifests additionally require active attempt/workspace/consent/ownership bindings; local-only manifests require a deterministic local identity, null Render workspace/consent/ownership fields, and no CLI/REST captures. Additive producers are reconciled with field-specific precedence: REST then CLI live state for current operational configuration, Blueprint for declared repository/build/topology intent, application evidence for safe inference, metrics for utilization, and billing for current spend. Every disagreement is recorded in `drift[]` with both values/sources, the winner, and the stable precedence reason.

Transport absence, Postgres/Key Value shape differences, disk non-inference, serving versus newest deploy, cron build versus run, instance/cold-wake state, and metric outcomes are preserved. Populated Build Sources and immutable artifacts are promoted with service, production, and environment-promotion edges. Workflow, version, task, run, and attempt identities stay distinct and an unobserved current version is never inferred.

Identities follow the NFC/SHA-256 algorithms in `deterministic-identities.md`: normalized duplicates and collisions are rejected, every unordered collection is byte-sorted, edge kinds are closed, and every resource is accounted for in exactly one cluster or the explicit unclustered list. `ai-workload-profile.json` validates against the vendored shared #415 contract and `render-ai-discovery.json` against `schema-render-ai-discovery.json` before artifacts are replaced. The `ai_track.profile_digest` recorded at Clarify is the SHA-256 of the exact bytes written to `ai-workload-profile.json`. The main window re-reads the artifacts before its completion gate.
