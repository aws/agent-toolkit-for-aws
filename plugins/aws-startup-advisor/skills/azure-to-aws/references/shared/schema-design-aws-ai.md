# Schema — aws-design-ai.json (moved — see the canonical contract)

> **This file has been canonicalized.** The `aws-design-ai.json` contract that used to live
> here — including its single-scalar `metadata.ai_source` MUST-equal-`summary.ai_source`
> rule — has moved to `plugins/aws-startup-advisor/skills/shared/ai/schema-design-aws-ai.md`,
> which replaces that scalar with many-valued `metadata.ai_sources[]` / `metadata.gateways[]`
> mirroring `ai-workload-profile.schema.json` (#415) exactly. This skill reads the canonical
> contract through its own byte-identical vendored copy at
> `references/vendored/ai/schema-design-aws-ai.md` (see that directory's README for the
> vendored-parity gate, `mise run lint:vendored-parity`). This file is kept only as a redirect
> so a reference to this path does not 404; do not restate the contract here — edit the
> canonical source instead.
>
> `scripts/artifact-contracts.json`'s `aws-design-ai.json` entry for `azure-to-aws` now points
> at the vendored copy. This change is target-only: `design-ai.md` has not been repointed to
> emit the new shape in this change (deferred runtime-adoption work).
