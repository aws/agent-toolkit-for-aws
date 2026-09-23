---
_phase: design
_title: "Design AWS Architecture"
_requires_phase: clarify
_input:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - preferences.json
_knowledge:
  - { file: knowledge/design/fast-path-services.json }
  - { file: references/shared/schema-design-aws.md }
  - { file: knowledge/design/azure-region-map.json }
  - { file: knowledge/design/appservice-eb-sizing.json, _when: "the inventory contains a Microsoft.Web/serverfarms resource" }
  - { file: knowledge/design/vm-ec2-sizing.json, _when: "the inventory contains a Microsoft.Compute/virtualMachines or virtualMachineScaleSets resource, or an AKS node pool whose vm_size must be resolved" }
  - { file: knowledge/design/aks-eks-sizing.json, _when: "the inventory contains a Microsoft.ContainerService/managedClusters resource" }
  - { file: knowledge/design/flexible-server-rds-sizing.json, _when: "the inventory contains a Microsoft.DBforPostgreSQL/* or Microsoft.DBforMySQL/* resource" }
  - { file: knowledge/design/cosmos-dynamodb-conversion.json, _when: "the inventory contains a Microsoft.DocumentDB/databaseAccounts resource whose kind is GlobalDocumentDB — the Core (SQL) API only" }
  - { file: knowledge/design/disk-ebs-sizing.json, _when: "the inventory contains a Microsoft.Compute/disks resource" }
  - { file: knowledge/estimate/rightsizing-thresholds.json, _when: "observed utilization exists — an RDfA rollup or az monitor metrics — so a size can be MEASURED rather than looked up" }
  - { file: references/shared/schema-design-aws-ai.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
  - { file: references/design-refs/ai.md, _when: "ai-workload-profile.json exists AND (summary.ai_source is 'other' or absent, OR any workloads[] capability is document_extraction, image_analysis, or speech_transcription)" }
  - { file: references/vendored/ai/ai-openai-to-bedrock.md, _when: "ai-workload-profile.json exists AND summary.ai_source is azure_openai, openai, or both" }
  - { file: references/vendored/ai/ai-anthropic-to-bedrock.md, _when: "ai-workload-profile.json exists AND summary.ai_source is anthropic or both" }
  - { file: references/vendored/ai/ai-migration-guardrails.md, _when: "ai-workload-profile.json exists AND agentic_profile.is_agentic is true" }
  - { file: references/vendored/ai/design-ref-agentic-to-agentcore.md, _when: "agentic_profile.is_agentic is true AND ai_constraints.agentic.migration_approach is strands" }
  - { file: references/vendored/ai/design-ref-harness.md, _when: "agentic_profile.is_agentic is true AND ai_constraints.agentic.migration_approach is harness" }
  - { file: references/vendored/ai/bedrock-quotas.md, _when: "ai-workload-profile.json exists" }
  - { file: references/vendored/ai/ai-model-lifecycle.md, _when: "ai-workload-profile.json exists" }
_fragments:
  - _id: infra
    _trigger: { _always: true }
    _file: phases/design/design-infra.md
  - _id: ai
    _trigger: { _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
    _file: phases/design/design-ai.md
_assemble:
  _file: phases/design/design-assemble.md
_produces:
  - aws-design.json
  - aws-design-ai.json
_advances_to: estimate
_re_entry_guard:
  _stale_if_completed: estimate
  _stale_artifact: estimation-infra.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: clarify
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [azure-resource-inventory.json, azure-resource-clusters.json, preferences.json]
    _on_failure: _unrecoverable
  - _validate_json: [azure-resource-inventory.json, azure-resource-clusters.json, preferences.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: aws-design.json
    _on_failure: _halt_and_inform
  - _validate_json: aws-design.json
    _on_failure: _halt_and_inform
  - _assert: "aws-design.json has phase == 'design' and a valid timestamp; services[] is present (empty only if every resource was deferred or skipped)"
    _on_failure: _halt_and_inform
  - _assert: "every services[] entry has service_id, azure_id, azure_type, aws_service, aws_config, confidence, and rationale; confidence is one of deterministic, measured, inferred, billing_inferred"
    _on_failure: _halt_and_inform
  - _assert: "every entry whose confidence is 'deterministic' matches a row in the Direct Mappings table, and no pattern constraint changed its aws_service — a pattern may narrow rubric candidates and may never override a deterministic mapping"
    _on_failure: _halt_and_inform
  - _assert: "every cluster in azure-resource-clusters.json appears in clusters[] with pattern_id, pattern_status, a cluster-level rationale, and constraints_imposed; target_architecture is a real string when pattern_status is 'recognized' and is null otherwise — a plausible architecture string written while design-refs/patterns.md is absent is the failure this checks for"
    _on_failure: _halt_and_inform
  - _assert: "no Microsoft.Web/sites resource has an entry in services[], deferred[], or pending_rubric[] unless preferences.json records an explicit isolation split for its plan — function apps included; the compute line belongs to the Microsoft.Web/serverfarms plan, and every serverfarms entry carries hosted_app_azure_ids and sizing_source"
    _on_failure: _halt_and_inform
  - _assert: "every resource in the inventory is accounted for EXACTLY ONCE: mapped in services[], deferred in deferred[], held in pending_rubric[] because its rubric file is absent, or recorded in warnings[] as a skip or as an edge-bearing config source that was consumed"
    _on_failure: _halt_and_inform
  - _assert: "iac_metadata.untranslated_types is empty; a type Discover could not name is treated as cost-bearing and STOPs the design, because the skill cannot demonstrate that a resource it could not identify is free"
    _on_failure: _halt_and_inform
  - _assert: "every deferred[] entry carries aws_service 'Deferred — specialist engagement' and a reason, and carries NO confidence field — a deferral did not come from a rubric"
    _on_failure: _halt_and_inform
  - _assert: "AWS App Runner does not appear as a target anywhere in aws-design.json"
    _on_failure: _halt_and_inform
  - _assert: "every entry whose confidence is 'measured' cites the utilization evidence that backed it"
    _on_failure: _halt_and_inform
  - _assert: "WHEN ai-workload-profile.json exists: aws-design-ai.json exists, validates, and has metadata.ai_source equal to the profile's summary.ai_source. WHEN the profile is absent the AI fragment does not run and this is vacuously satisfied"
    _on_failure: _halt_and_inform
  - _assert: "WHEN aws-design-ai.json exists: every design_blocks[] row has exactly one of target_bedrock_model / target_aws_service non-null (XOR), and every document_extraction/image_analysis/speech_transcription row has target_bedrock_model null, a non-null target_aws_service, and honest_assessment 'not_applicable' — per references/shared/schema-design-aws-ai.md"
    _on_failure: _halt_and_inform
  - _assert: "WHEN aws-design-ai.json exists AND summary.ai_source is azure_openai or openai: every source model that is available on Bedrock and carried by the target region maps to itself with model_change false — not to a Claude/Nova substitute; and no proprietary openai.gpt-* model ID is paired with a converse/bedrock-runtime migration path"
    _on_failure: _halt_and_inform
  - _assert: "WHEN aws-design-ai.json exists: regional_warnings[] and multi_model_warnings[] are present (empty is fine); agentic_design is present only when agentic_profile.is_agentic is true; and App Runner appears nowhere"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - "terraform/**"
  - MIGRATION_GUIDE.md
  - estimation-infra.json
---

# Phase 3: Design AWS Architecture

## Orientation

Turn the inventory, the clusters, and the confirmed preferences into
`aws-design.json`. Two product goals have to hold at once, and they pull against each
other the moment a workload-level decision disagrees with a per-resource one:

1. **Holistic** — the output describes workloads, not independent rows.
2. **Pre-determined where there is no ambiguity** — an unambiguous service is not
   routed through a rubric that could reason its way to a different answer.

The precedence order below is what reconciles them.

## Precedence order

1. **Skip Mappings** — not a target at all.
2. **Specialist gates → `Deferred`.** "We do not know" must never be overridden by
   anything below it.
3. **Eliminators** — hard technical blockers. Lambda's 15-minute ceiling is physics,
   not a preference.
4. **Direct Mappings → `deterministic`** — the pre-determined recommendations.
5. **Pattern constraint** — the holistic layer, applied to whatever is left.
6. **Six-criteria rubric** — chooses _within_ the pattern's candidate set:
   Eliminators, Operational Model, User Preference, Feature Parity, Cluster Context,
   Simplicity, applied in order, first match wins.
7. **Preferred-target substitution.**
8. **Post-selection** — right-sizing from measured utilization, then CPU
   architecture.

> **INVARIANT: a pattern may never change a `deterministic` mapping's target. It may
> only choose among rubric candidates.**

If a pattern could override a fast-path row, the `deterministic` tier would stop
meaning anything and its user-facing label ("Standard pairing") would be false. So a
genuine pattern/fast-path conflict is evidence the row does not belong in Direct
Mappings — the fix is to demote the row, never to let the pattern win.

Right-sizing is **post-selection, not a seventh criterion.** The six criteria select
a _service_ and never touch capacity; adding a seventh would break "apply in order,
first match wins". Each rubric file gets an additive `## Right-Sizing` section,
structurally parallel to `## CPU Architecture`.

## Status — build step 5 (both passes, partial)

**Pass 1 and pass 2 both run.** `knowledge/design/fast-path-services.json` carries the
disposition table; eight rubrics are on disk — `compute.md`, `database.md`,
`networking.md`, `messaging.md`, `analytics.md`, `storage.md`, `identity.md` and
`fast-path.md`. A resource routed by `index.md` to a category file that is **not** on disk
still halts rather than being improvised; `ai.md` is on disk (the AI-workload rubric);
only `licensing.md`, `gpu-hpc.md` and `patterns.md` are still to come.

**Check the filesystem, not this paragraph.** A status list in prose goes stale the moment a
file lands, and the halt decision reads from disk. If this list and `ls` disagree, `ls` is
right and this list is the bug.

| Lands in | What                                                                                                                                                                                      |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| step 4   | `patterns.md` and the cluster-level `data-pipeline` gate. Clustering itself is real; only pattern RECOGNITION is outstanding, so every cluster carries `pattern_status: "catalog_absent"` |
| step 5   | The remaining eight category files, and the `knowledge/design/*.json` sizing tables wired through `_knowledge` `_when` guards                                                             |
| step 6   | The AI design route                                                                                                                                                                       |

**A missing SIZING table is treated more softly than a missing RUBRIC file, on purpose.**
Without `appservice-eb-sizing.json` the design still names Elastic Beanstalk and states a
dev-tier instance size as a default; without `compute.md` it would have to invent the
service choice. The first degrades a number's precision, the second fabricates the answer.

The `_postconditions` encode the FINISHED contract, so some still fail by construction —
a halted design does not account for every resource. That is intended: the gate reports
the skill's gap loudly rather than letting a plausible mapping pass for a real one.

## Step: Run the phase

1. Order clusters by tier: network/identity/secrets → data → compute → edge.
2. Run each fragment whose `_trigger` holds.
3. Run `design-assemble.md`.
4. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop.
