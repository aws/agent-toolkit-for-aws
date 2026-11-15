# Shared AI references (canonical)

Plugin-neutral, source-cloud-agnostic AI migration content. Each file here is the
single source of truth and is vendored into every consuming skill at
`references/vendored/ai/<same name>`, which must stay byte-identical to it.
**Edit here, never in a vendored copy**, then copy the changed file over every
vendored copy in the same change. This repository has no automated sync task;
verify with `md5sum` (or `md5 -q`) over the canonical file and each vendored copy
before opening a pull request.

| File                                 | What it owns                                                   |
| ------------------------------------ | -------------------------------------------------------------- |
| `ai-model-lifecycle.md`              | Bedrock Active/Legacy/EOL registry + the 90-day exclusion rule |
| `ai-migration-guardrails.md`         | Shared constraints for every agentic migration path            |
| `bedrock-endpoint-policy.md`         | `bedrock-runtime` default / `bedrock-mantle` selector rule, `mantle_selector` enum, public endpoint matrix |
| `bedrock-quotas.md`                  | TPM/RPM quota-risk assessment (works without an AWS account)   |
| `ai-openai-to-bedrock.md`            | OpenAI-protocol (incl. Azure OpenAI) → Bedrock model selection |
| `ai-anthropic-to-bedrock.md`         | Anthropic SDK → Bedrock Runtime Messages (default) / Converse alternative |
| `ai-gemini-to-bedrock.md`            | Gemini (incl. Vertex AI) → Bedrock model selection             |
| `ai-openrouter-to-bedrock.md`        | OpenRouter gateway → per-upstream Bedrock routing              |
| `design-ref-harness.md`              | AgentCore Harness design reference                             |
| `design-ref-agentic-to-agentcore.md` | Strands Agents + AgentCore Runtime design reference            |
| `sdk-capability-map.json`            | SDK method → capability lookup used by app-code discovery      |
| `ai-capability-catalog.json`         | Target-only source-provider/gateway capability catalog (schema_version, provider/gateway status, no implemented-adapter claim) |
| `bedrock-pricing-cache.md`           | Provider-neutral Bedrock model and service pricing             |
| `models/bedrock-model-registry.json` | **Source of truth** for model-selection data: one record per Bedrock model (shared facts, canonical capability vocabulary, `selection_status`) plus per-provider views. Edit this file, then run `tools/build-model-catalogs.py` and `tools/sync-vendored.py`. Contract: `scripts/contracts/model-registry.schema.json` |
| `models/anthropic-bedrock.json`, `models/openai-bedrock.json` | **Rendered** per-provider catalogs read by agent-advisor's selectors. Do not edit by hand: `mise run lint:model-catalogs` fails when they differ from the registry. Contract `scripts/contracts/model-selection-catalog.schema.json`; `tools/model-catalog-drift.py` checks them against `ai-model-lifecycle.md` |
| `token-volume-tiers.json`            | The `ai_token_volume` tiers: Clarify Q7's bands, their token bounds, and how Estimate prices a tier |
| `schema-design-aws-ai.md`            | Target-only `aws-design-ai.json` contract; `metadata.ai_sources[]`/`gateways[]` mirror `ai-workload-profile.schema.json` exactly |
| `schema-estimate-ai.md`               | Target-only `estimation-ai.json` contract; `cost_by_source[]` traces per-source/per-model cost back to `aws-design-ai.json` |
| `schema-generate-ai.md`               | Target-only `generation-ai.json` contract; `artifacts_by_source[]` traces per-source/per-model generated artifacts back to `estimation-ai.json` |

The Gemini and OpenRouter guides are source-cloud agnostic (the Bedrock target
depends on the upstream model, not the source cloud), so they are canonical here
and vendored like the OpenAI and Anthropic guides. A consuming skill's own
runtime routing may still point at an adapter-local copy (gcp-to-aws keeps
`references/design-refs/ai-gemini-to-bedrock.md` for its Gemini adapter)
until the extraction stages repoint it; that is a separate decision from this
shared guide existing.

Deliberately NOT here: a source-cloud's `schema-discover-ai.md`, which is written
against one provider's SDK surface.

**Consumer contract.** A skill that consumes Bedrock pricing must vendor
`references/vendored/ai/bedrock-pricing-cache.md` from this canonical set. Source-cloud
and AWS infrastructure caches remain skill-owned; pricing fallback policy remains at
`references/shared/pricing-fallback.md` in each consuming skill.
