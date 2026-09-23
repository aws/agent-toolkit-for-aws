---
_assemble: assemble-design
_of_phase: design
_reads:
  - scoring-result.json (per agent_session unit)
  - confirm.json (platform_decision, user overrides)
  - workload-classes.md (for non-agent units)
  - service cards (winning runtime's documentation)
_produces:
  - design.json
---

# Design — Assemble design.json

> **Assembler unit.** The Design phase reads the scoring result and Confirm
> choices, loads the winning runtime's service card, refreshes volatile facts,
> runs the lock-in / I/O-wait / FedRAMP / region gates, and assembles the
> recommendation into `design.json` inline within `design.md` (Step 5). This
> unit records the artifact-level contract for the phase: it is the single
> creator of `design.json`, and its postconditions (declared on the phase) are
> the phase's completion gate. See `design.md` § Step 5 for the design.json shape
> (verdict, chosen_runtime, deployment_model, agentcore_services,
> model_recommendation, scores, eliminated, the gate notes, handoff_required).

The assembler produces ONE `units[]` entry per inventory unit: agent units derive their verdict,
deployment_model, and agentcore_services from scoring plus confirm, while model_recommendation
comes only from the matching model-recommendation.json entry plus the accepted model_decision;
the complete model contract includes parity/compatibility, architecture impacts,
evaluation/rollout gates, and the separate live verification result when present;
non-agent units derive their verdict from workload-classes rules (with rationale citing the rule
id like "W2: batch → AWS Batch"). It then assembles the `platform` block from confirm.json's
platform_decision and the units' coupling. Finally, it writes the primary unit's fields at
design.json's top level (legacy mirror).
