# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then bring every vendored copy back in sync:

```sh
# from the repository root
python3 plugins/aws-startup-advisor/tools/sync-vendored.py          # copies skills/shared/<path> over every vendored copy
python3 plugins/aws-startup-advisor/tools/sync-vendored.py --check  # what CI runs (mise run lint:vendored-parity)
```

CI fails when a vendored copy differs from its canonical source, has no canonical source,
is listed in the table below but missing on disk, or is on disk but not listed below. So an
edit to a `skills/shared/` file this skill vendors, or a deleted copy, cannot merge
unnoticed. What CI cannot see is a **new** `skills/shared/` file that no skill vendors yet —
if this skill needs one, add the copy **and** a row in the table below.

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
