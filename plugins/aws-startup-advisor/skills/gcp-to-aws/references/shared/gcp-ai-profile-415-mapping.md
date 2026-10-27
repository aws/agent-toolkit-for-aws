# Legacy GCP AI profile to #415 mapping

The GCP boundary adapter (`scripts/gcp-ai-profile-adapter.py`) converts the legacy GCP-shaped `ai-workload-profile.json` into an `ai-workload-profile` document that validates against the vendored #415 schema (`references/contracts/ai-workload-profile.schema.json`, byte-identical to the canonical copy). BMA accepts only the #415 shape. This file is the only place the mapping is defined.

The mapping is deterministic. The same legacy input always produces the same #415 output. Any legacy value the table cannot represent stops the conversion with `GcpProfileNotRepresentable`, names the legacy field path, and writes nothing.

## Mapping table

| Legacy field | #415 field | Rule | Named error |
| --- | --- | --- | --- |
| `schema_version` (absent in legacy) | `schema_version` | Always `"1.0"`. A legacy object that already has `schema_version`, `ai_sources`, or `gateways` is not legacy input. | `LEGACY_SHAPE_UNEXPECTED` |
| `models[].service` | `ai_sources[].provider`, `ai_sources[].source_service` | `vertex_ai_generative` and `vertex_ai_embeddings` map to `google` / `vertex_ai`. `openai_api` maps to `openai` / `openai_api`. `azure_openai` maps to `openai` / `azure_openai`. `anthropic_api` maps to `anthropic` / `anthropic_api`. `openrouter_api` is a gateway, not a source (see gateway rows). | `LEGACY_SERVICE_UNMAPPED` |
| `summary.ai_source` | Cross-check only | `gemini`, `openai`, `anthropic` must equal the provider set of the observed sources. A mismatch fails. `both` and `other` derive each source from its models. An unknown value fails. | `LEGACY_AI_SOURCE_UNREPRESENTABLE` |
| `models[].model_id` | `ai_sources[].models[]`, `model_observations[].normalized_model` | `normalized_model` is the lowercased id and must match the #415 `normalizedModel` pattern. `raw_model` is the verbatim id. Duplicates of the same normalized model within one source merge their evidence. | `LEGACY_MODEL_ID_INVALID` |
| `models[].model_id` | `model_families`, `model_observations[].model_family` | Prefix rule on the normalized id (mirrors `SOURCE_MODEL_FAMILY` in `bma-runtime.py`): `claude*` gives `claude`; `gemini*` gives `gemini`; `imagen*` gives `imagen`; `gpt*`, `o1*`, `o3*`, `o4*` give `gpt`; `text-embedding*` gives `embedding`. Any other id fails by name. | `LEGACY_MODEL_FAMILY_UNKNOWN` |
| `models[].detected_via` and `models[].evidence[].source` | `model_observations[].evidence[].provenance` | `code` gives `code`. `terraform` gives `iac`. `live_gcloud` gives `live_api`. Any `*_usage_api` gives `usage_api`. `user_confirmed` or `user` gives `user_confirmed`. Any other value fails. One evidence entry is emitted per detected method. | `LEGACY_PROVENANCE_UNKNOWN` |
| `detection_signals[]` (`method`, numeric `confidence`) | `model_observations[].evidence[].confidence` | The confidence for a provenance is the maximum score among signals whose method maps to that provenance. At least 0.9 gives `high`. 0.7 to 0.89 gives `medium`. Below 0.7 gives `low`. `confirmed` is never derived. No matching numeric signal fails. | `LEGACY_CONFIDENCE_MISSING` |
| `models[].evidence[]` (`file` and `line`, or `resource`) | `model_observations[].evidence[].detail` | `"file:line"` when both are present, otherwise `resource`. Omitted when neither applies. | none |
| `summary.ai_source` with no observed direct model, and `metadata.profile_source` `iac_vertex` | `ai_sources[]` with `model_evidence: not_observed`, `models: []`, `model_observations: []` | Only when `ai_source` is `gemini`, `openai`, or `anthropic`. The family comes from `ai_source` (`gemini`, `gpt`, `claude`) and the service from the same provider mapping. `both` and `other` fail. Absent `ai_source` fails. | `LEGACY_AI_SOURCE_UNREPRESENTABLE` for `both` or `other`; `LEGACY_IAC_FAMILY_UNKNOWN` for absent |
| `models[]` with `service` `openrouter_api` | `gateways[]` with `product: openrouter`, `type: llm_router` | Present only when at least one such model exists. `integration.gateway_type` must be `llm_router`, otherwise the conversion fails. | `LEGACY_GATEWAY_UNREPRESENTABLE` |
| `openrouter_api` model ids of the form `<prefix>/<model>` | `gateways[].upstreams[]` | `anthropic/` gives `anthropic` / `anthropic_api`. `openai/` gives `openai` / `openai_api`. `google/` gives `google` / `vertex_ai`, matching the merged #415 fixture. Grouped by provider, source_service, then family. | none for resolved ids |
| Any `openrouter_api` model id without a known `<prefix>/` | `gateways[].upstream_evidence: unresolved`, `upstreams: []` | The whole gateway is unresolved when any upstream prefix is missing or unknown. No upstream is invented. | none |
| `integration.pattern`, `primary_sdk`, `frameworks`, `languages`, `capabilities_summary` | `.bma-input/ai-workload-sidecar.json` → `integration_context` (same keys) | Not representable in #415. Copied verbatim into the GCP-owned sidecar when `integration` has any of these keys. `sdk_version` and `gateway_type` are not carried. `gateway_type` is validated against the gateway rows instead. | none |
| `models[].service`, `models[].model_id`, `models[].capabilities_used`, `models[].usage_context` (for models with either capability or usage field) | `.bma-input/ai-workload-sidecar.json` → `model_context[]` | Not representable in #415. Copied per model as `{service, model_id, capabilities_used, usage_context}`, keeping only the fields present. | none |
| `infrastructure[]` | `.bma-input/ai-workload-sidecar.json` → `infrastructure[]` | Not representable in #415. Copied verbatim when non-empty. Must be an array, otherwise `LEGACY_SHAPE_UNEXPECTED`. | `LEGACY_SHAPE_UNEXPECTED` |
| `current_costs` | `.bma-input/ai-workload-sidecar.json` → `observed_costs` | Not representable in #415. Merged into any existing `observed_costs` per `schema-discover-ai.md` § Usage-API merge: per-provider rows, totals recomputed, a different provider is summed under `source: "mixed"` with `breakdown[]`, the same provider is replaced and the displaced row goes to `conflicting_sources[]`. Copied verbatim when no `observed_costs` exists. Must be an object, otherwise `LEGACY_SHAPE_UNEXPECTED`. | `LEGACY_SHAPE_UNEXPECTED` |
| `metadata.profile_source` and `summary.inferred_from_iac` | `.bma-input/ai-workload-sidecar.json` → `profile_origin` | Not representable in #415. Reduced to `{terraform_primary}`, true when `profile_source` is `iac_vertex` or `inferred_from_iac` is true. Omitted when neither field is present. | none |
| `metadata.*` (other keys), `detection_signals` as a whole | none | Provenance only, beyond the rows above. | none |
| Any non-object `models[]` entry, or `summary`, `integration`, `detection_signals` of the wrong type | none | Input shape check. | `LEGACY_SHAPE_UNEXPECTED` |
| Converted document fails the vendored #415 schema | none | Final gate before any write. The error reports the first failing field path. | `SCHEMA_415_INVALID` |

## Provenance and gateway notes

- `model_evidence` is `observed` only when at least one direct model exists for that source. Otherwise the source is `not_observed` and keeps its family, as in the table.
- `upstream_evidence` is `observed` only when every OpenRouter model id carries a known provider prefix. Otherwise it is `unresolved` with no upstreams.
- OpenRouter models are never written as a direct `ai_sources` entry. The #415 gateway object has no evidence field, so per-model legacy evidence for OpenRouter upstreams is not carried.

## Decisions

- Nothing populated fails closed for sidecar-carried fields. Those values go through the temporary sidecar so GCP outputs stay the same.
- `metadata` is provenance only beyond `profile_source`. The Terraform-primary condition travels as the sidecar `profile_origin.terraform_primary` boolean, so delegated GCP runs keep the legacy Profile origin and IaC-only wording. Direct BMA runs still derive it from #415 evidence provenance.
- The converted document is written to `.bma-input/ai-workload-profile.json`, and the sidecar to `.bma-input/ai-workload-sidecar.json`. Both sit in a hidden internal directory the GCP run does not publish. The public GCP `ai-workload-profile.json` keeps its legacy content.
- When BMA discovery already wrote `.bma-input/ai-workload-profile.json`, the converted document is merged into it, never written over it: `ai_sources` union by `(provider, source_service)`, `models`, `model_observations`, and `evidence` union in order of first appearance, `gateways` union by `(product, type)` with upstreams and families unioned the same way, `model_evidence` recomputed from the merged `models`. The merged document is validated against the vendored #415 schema. In the sidecar, BMA-owned `workloads`, `agentic_profile`, and `tool_manifest` are left untouched, `observed_costs` is merged per provider, and only the GCP-owned `integration_context`, `infrastructure`, `model_context`, and `profile_origin` are replaced.
- Follow-up: the temporary sidecar (`observed_costs`, `integration_context`, `infrastructure`, `model_context`) folds into #415 under a new schema version. See `schema-discover-ai.md` in bedrock-migration-assessment.

## Error codes

`LEGACY_SIDECAR_INVALID` is raised when an existing `.bma-input/ai-workload-sidecar.json` is not a `BMA_GCP_AI_SIDECAR` v1 document. `EXISTING_415_INVALID` is raised when an existing `.bma-input/ai-workload-profile.json` is not a #415 document. Each code is raised as `GcpProfileNotRepresentable` with the legacy field path. The CLI prints the code, field path, and message to stderr and exits 1. It writes no output file.
