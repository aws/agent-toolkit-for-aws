# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then copy the changed file over every vendored copy in the same change so the
copies stay byte-identical:

```sh
# from the repository root, for each vendored path listed below
cp plugins/aws-startup-advisor/skills/shared/<path> \
   plugins/aws-startup-advisor/skills/azure-to-aws/references/vendored/<path>
```

This repository has no automated sync task for these copies — keeping them
byte-identical is part of the change that touches the canonical file. Verify with
`md5sum` (or `md5 -q`) over the canonical file and every vendored copy before
opening a pull request; the hashes must match.

| Vendored path                           | Canonical source                                      |
| --------------------------------------- | ----------------------------------------------------- |
| `dsl/INTERPRETER.md`                    | `skills/shared/dsl/INTERPRETER.md`                    |
| `state/phase-status.schema.json`        | `skills/shared/state/phase-status.schema.json`        |
| `estimate/complexity-tiers.json`        | `skills/shared/estimate/complexity-tiers.json`        |
| `estimate/estimation-infra.schema.json` | `skills/shared/estimate/estimation-infra.schema.json` |
| `estimate/pricing-mode.md`              | `skills/shared/estimate/pricing-mode.md`              |
| `estimate/ri-sp-eligibility.md`         | `skills/shared/estimate/ri-sp-eligibility.md`         |
| `pricing/aws-infra-pricing.json`        | `skills/shared/pricing/aws-infra-pricing.json`        |
| `workshop/workshop-invariants.md`       | `skills/shared/workshop/workshop-invariants.md`       |
| `ai/ai-anthropic-to-bedrock.md`         | `skills/shared/ai/ai-anthropic-to-bedrock.md`         |
| `ai/ai-migration-guardrails.md`         | `skills/shared/ai/ai-migration-guardrails.md`         |
| `ai/ai-model-lifecycle.md`              | `skills/shared/ai/ai-model-lifecycle.md`              |
| `ai/ai-openai-to-bedrock.md`            | `skills/shared/ai/ai-openai-to-bedrock.md`            |
| `ai/bedrock-quotas.md`                  | `skills/shared/ai/bedrock-quotas.md`                  |
| `ai/design-ref-agentic-to-agentcore.md` | `skills/shared/ai/design-ref-agentic-to-agentcore.md` |
| `ai/design-ref-harness.md`              | `skills/shared/ai/design-ref-harness.md`              |
| `ai/sdk-capability-map.json`            | `skills/shared/ai/sdk-capability-map.json`            |
| `clarify/clarify-availability.md`       | `skills/shared/clarify/clarify-availability.md`       |
| `clarify/clarify-compliance.md`         | `skills/shared/clarify/clarify-compliance.md`         |
| `clarify/clarify-cost-appetite.md`      | `skills/shared/clarify/clarify-cost-appetite.md`      |
| `clarify/clarify-multicloud.md`         | `skills/shared/clarify/clarify-multicloud.md`         |
| `clarify/clarify-region.md`             | `skills/shared/clarify/clarify-region.md`             |
