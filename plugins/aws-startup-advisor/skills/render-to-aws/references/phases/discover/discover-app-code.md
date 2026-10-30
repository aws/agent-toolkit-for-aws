---
_fragment: app-code
_of_phase: discover
_contributes:
  - render-resource-inventory.json
  - { file: ai-workload-profile.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
  - { file: render-ai-discovery.json, _when: "provider-neutral AI evidence reaches the documented threshold" }
---

# Discover application evidence

This `rw` fragment is file-only: the main window already ran `scan-render-application.py` (see `discover.md` "Pre-dispatch main-window actions", Step 2) and listed its output in the active attempt manifest. Read only the manifest-listed `transport: application` capture under `$MIGRATION_DIR/live-capture/`; never run the scanner, traverse the workspace yourself, or execute source.

Verify before contributing: `schema_version` is `1.0`, the SHA-256 digest equals the manifest `digest`, and the capture carries only the closed top-level set `files`, `skipped`, `signals`, `fingerprint`, `ai_profile`, and `ai_discovery`. The scanner traversed bytewise without VCS-ignore dependence, inspected only the closed source, manifest, Dockerfile, and Procfile set, skipped symlinks, secret-named, generated, dependency, binary, oversized, raced, or root-escaping files, and recorded metadata-only skip reasons; a capture that contains source snippets or environment-variable values is invalid and stops this contribution.

Content fingerprints and safe infrastructure/process symbols are recorded without snippets. Environment-variable names may be evidence; values may not. AI evidence is scored from known dependencies, imports, SDK construction, calls, endpoints, frameworks, and names. At score 70 or greater with SDK construction or method-call evidence, the scan carries both `ai_profile` and `ai_discovery`; otherwise both are `null`. Exactly one of them present is invalid. `ai_profile` conforms to the shared #415 contract: providers are `openai`, `anthropic`, or `google` with a `source_service` (`openai_api`, `azure_openai`, `anthropic_api`, `gemini_api`, `vertex_ai`); OpenRouter appears only as a gateway (`product: openrouter`, `type: llm_router`) with observed or unresolved upstreams, never as a provider; each source carries explicit `model_evidence`; every evidence entry has provenance `code`, a `confirmed` or `medium` confidence, and a `path:line` detail. `ai_discovery` is the Render-internal graph with deterministic identities and complete reachability. Neither artifact carries an execution block; the deferral state is recorded in `ai_track`.
