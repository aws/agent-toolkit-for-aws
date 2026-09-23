---
_assemble: assemble-confirm
_of_phase: confirm
_reads:
  - winner-specific runtime and model/path confirmations (collected inline in confirm.md)
_produces:
  - confirm.json
---

# Confirm — Assemble confirm.json

> **Assembler unit.** Confirm reads the scoring result, asks only what the
> winning runtime needs (deployment model, AgentCore services, co_recommend
> pick, native-vs-gateway tool choices), and writes `confirm.json` inline within
> `confirm.md` (Step 5). This unit records the artifact-level contract for
> the phase: it is the single creator of `confirm.json`, and its postconditions
> (declared on the phase) are the phase's completion gate. See `confirm.md`
> § Step 5 for the confirm.json shape (`deployment_model`, `agentcore_services`,
> `chosen_runtime` when co_recommend, `tool_choices`, and accepted `model_decision`).
> `model_decision.accepted` records strategy acceptance; `verification_status`
> independently records whether the exact model/path was invocable in the target account.
