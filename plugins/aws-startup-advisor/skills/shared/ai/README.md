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
| `bedrock-quotas.md`                  | TPM/RPM quota-risk assessment (works without an AWS account)   |
| `ai-openai-to-bedrock.md`            | OpenAI-protocol (incl. Azure OpenAI) → Bedrock model selection |
| `ai-anthropic-to-bedrock.md`         | Anthropic SDK → Bedrock Converse client swap                   |
| `design-ref-harness.md`              | AgentCore Harness design reference                             |
| `design-ref-agentic-to-agentcore.md` | Strands Agents + AgentCore Runtime design reference            |
| `sdk-capability-map.json`            | SDK method → capability lookup used by app-code discovery      |
| `bedrock-pricing-cache.md`           | Provider-neutral Bedrock model and service pricing             |

Deliberately NOT here: a source-cloud's own mapping guide (e.g. gcp-to-aws's
`ai-gemini-to-bedrock.md`) and its `schema-discover-ai.md`, both of which are
written against one provider's SDK surface.

**Consumer contract.** A skill that consumes Bedrock pricing must vendor
`references/vendored/ai/bedrock-pricing-cache.md` from this canonical set. Source-cloud
and AWS infrastructure caches remain skill-owned; pricing fallback policy remains at
`references/shared/pricing-fallback.md` in each consuming skill.
