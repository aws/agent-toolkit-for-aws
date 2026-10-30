---
_fragment: live
_of_phase: discover
_contributes:
  - render-resource-inventory.json
  - render-resource-clusters.json
---

# Discover from live capture

This `rw` fragment is file-only: CLI/REST capture and normalization already ran in the main window before dispatch (see `discover.md` "Pre-dispatch main-window actions", Steps 1 and 3); the rules below describe the captures it reads, not commands it runs. Read only the active attempt-bound files under `$MIGRATION_DIR/live-capture/`. Verify manifest, consent digest, workspace ownership, ownership-index digest, category schema, parent digest, file digest, bounds, and status before contributing. Preserve transport-specific `null`, array, `{data}`, wrapper, stream, cursor, HTTP-status, metric, and capability outcomes.

CLI capture is restricted to the exact Render 2.30.0 table. Unsupported categories, flags, templates, versions, and every mutation reject before the category process starts. Every child-category request must resolve through the active attempt-bound ownership index before `Popen`, and any returned project, service, Workflow, version, or task parent must match the requested indexed parent. The child uses `shell=False`, closed stdin, timeout termination followed by a two-second kill bound, and only `PATH`, `HOME`, locale, and reviewed credential-free certificate/proxy variables. `RENDER_API_KEY` and all token/credential variables are absent.

REST capture constructs fixed-origin allowlisted GETs only and rejects every redirect before following it. Events and populated Build Sources are active closed projections; unknown envelopes or fields fail as capability drift. REST workspace, PostgreSQL, Key Value, and service-instance rows are inactive unreviewed contracts and fail before network access as `unsupported_contract`; use the reviewed Render CLI 2.30.0 projections as the canonical discovery sources for those surfaces. Do not run Render, access the network, prompt, or accept a capture from another attempt.
