# Render AI discovery graph

`render-ai-discovery.json` is the Render-internal AI discovery graph. It retains the richer workload, call-site, relationship, and fingerprint evidence that `scan-render-application.py` collects. It is not the shared contract. The shared, consumer-facing artifact is `ai-workload-profile.json`, which conforms to the maintainer-pinned ai-workload-profile contract (`scripts/contracts/ai-workload-profile.schema.json`, issue #415; vendored byte-identically at `references/contracts/ai-workload-profile.schema.json`). Both artifacts are projections of the same scan; neither chooses an AWS target or executes a migration.

## Relationship to the shared profile

The shared profile is a closed Draft-07 document with `schema_version`, `ai_sources[]`, and `gateways[]`. Render projects its internal provider families onto the shared identities: `openai` → provider `openai` / `source_service` `openai_api`; `azure_openai` → provider `openai` / `source_service` `azure_openai`; `anthropic` → `anthropic` / `anthropic_api`; `google_gemini` → `google` / `gemini_api`; `google_vertex_ai` → `google` / `vertex_ai`. OpenRouter is representable only as a gateway (`product: openrouter`, `type: llm_router`), never as a provider. `amazon_bedrock` is already an AWS target and is kept only in this internal graph. Each `ai_sources[]` entry carries an explicit `model_evidence` (`observed` or `not_observed`), and every evidence entry carries `provenance: code` with a `path:line` detail and a confidence of `confirmed` (the file also carries SDK construction or a method call for the same provider) or `medium` (inferred). When OpenRouter upstreams are observed, each upstream mirrors the merged `ai_sources[]` entry exactly (same families, same full model list), as the shared contract's consumers require. The deferral record (`deferred_shared_ai_engine`, profile path, profile digest, reason, resume path) lives in phase state `ai_track`, not in either artifact.

## Canonical encoding and identity

Normalize every retained string to Unicode NFC and encode canonical JSON as UTF-8 with sorted object keys, compact separators, and one trailing newline. Hashes use SHA-256 lowercase hexadecimal and are rendered as `sha256:<64-hex>`.

Generated IDs use the first 24 hex characters of these full canonical hashes:

- workload: `workload\0<normalized workspace-relative component>\0<capability>` → `aiw-<24hex>`
- provider: `provider\0<provider family>` → `aip-<24hex>`
- model: `model\0<provider id>\0<observed model identifier>` → `aim-<24hex>`
- gateway: `gateway\0<gateway family>\0<normalized endpoint hostname or "-">` → `aig-<24hex>`
- evidence: `evidence\0<workspace-relative path>\0<method>\0<symbol-or-env-name>` → `aie-<24hex>`
- call site: `call-site\0<workload id>\0<workspace-relative path>\0<symbol>\0<ordinal>` → `aic-<24hex>`
- relationship: `relationship\0<type>\0<from id>\0<to id>` → `air-<24hex>`

The graph `fingerprint` is the SHA-256 of canonical JSON containing all graph fields except `fingerprint`, with every semantically unordered array already sorted. The `discovery_id` is `aidisc-` plus the first 24 fingerprint hex characters. Reject duplicate normalized identity inputs, duplicate IDs, and any collision; never suffix or silently merge them.

Sort every collection by the UTF-8 bytes of its ID. Sort scalar enum arrays by normalized UTF-8 bytes. Relationships use `(type UTF-8 bytes, from_id UTF-8 bytes, to_id UTF-8 bytes, id UTF-8 bytes)`. Object keys use canonical JSON ordering.

## Reachability and cardinality

Every `provider_id`, `model_id`, `gateway_id`, and `evidence_id` referenced by a workload or call site must resolve to exactly one corresponding object. Every relationship endpoint must resolve to exactly one declared ID. Every provider, model, gateway, evidence item, and call site must be reachable from at least one workload; unreferenced objects fail validation. Each call site belongs to exactly one workload. Models and gateways may be absent, but a graph has at least one workload, provider, evidence item, and call site.

## Leakage prohibitions

Retain workspace-relative paths, symbols, SDK/provider/model identifiers, endpoint hostnames, environment-variable names, safe numeric usage evidence, and bounded capability facts only. Never retain environment-variable values, prompts, responses, document contents, source snippets, credentials, tokens, connection strings, user/account/workspace identifiers, email addresses, arbitrary URLs, or remote error text.

The schema intentionally has no target-model, Bedrock, adapter, price, estimate, Terraform, or generated-output fields. Existing direct Bedrock usage is still represented as an observed source provider in this graph, not as a migration decision. Infrastructure migration continues; downstream phases must not import or invoke `gcp-to-aws`, choose an AI target, estimate AI cost, emit an adapter, or generate AI Terraform. AI execution is deferred until `bedrock-migration-assessment` consumes the shared contract.
