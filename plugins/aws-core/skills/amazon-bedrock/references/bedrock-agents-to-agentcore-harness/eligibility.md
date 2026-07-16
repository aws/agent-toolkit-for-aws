# Eligibility rubric

Check each condition against the discovery manifest. A **hard-stop** means the agent has a feature with no validated AgentCore Harness path — stop the migration, name the failing condition, and suggest the manual alternative. Do not migrate the eligible parts of an ineligible agent: a half-migrated agent is worse than a clear "not yet."

State the result of *every* condition to the user, not just the first failure — they need the full picture to decide what to fix.

For an **inline agent**, evaluate these same conditions against the fields of the `InvokeInlineAgent` payload (the manifest built from it) rather than a stored agent — e.g. multimodal input from the payload's model/inputs, collaboration/orchestration from its config. The rubric is identical; only the source of the fields differs.

## Hard-stop conditions

### 1. Multimodal input
**Signal:** the agent processes images or audio (vision model for image input, or documented image/audio handling). The validated harness path is text-only.
**Alternative:** keep on Bedrock until a multimodal path is validated. (This is a true hard-stop — don't offer a degraded "migrate anyway with image/audio dropped" path, which would contradict the hard-stop rule above.)

### 2. Multi-agent collaboration
**Signal:** `agentCollaborationMode` is `SUPERVISOR` or `SUPERVISOR_ROUTER`. The supervisor is out of scope — do **not** flatten collaborators into its prompt, wire them as sub-agents, or migrate it alone (dangling references).
**Alternative:** each collaborator is an ordinary Bedrock agent; any that doesn't itself collaborate can be migrated on its own (run this skill once per collaborator). Only the supervisor layer is excluded.

### 3. Unreachable knowledge base
**Signal:** an associated KB is in an account/region the credentials cannot reach — so `bedrock-agent-runtime:Retrieve` can't reproduce its retrieval.
**Alternative:** grant cross-account/region access, then re-run.
**Not the KB *type*:** every type (`VECTOR`/`MANAGED`/`KENDRA`/`SQL`) is reachable via `Retrieve` and eligible; type only picks the wiring (see [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).

### 4. Custom orchestration
**Signal:** `orchestrationType` is `CUSTOM_ORCHESTRATION` (custom orchestration Lambda). The harness runs its own loop; that control flow has no equivalent and would be silently dropped.
**Alternative:** re-express the logic as harness tools/prompt as a fresh design, or keep on Bedrock.

## Eligible — do not mistake these for blockers

- **DRAFT-only agent** (no published version) — common; treat DRAFT as the source (see [discovery.md](references/bedrock-agents-to-agentcore-harness/discovery.md)).
- **Mixed action-group schema styles** (`functionSchema` and OpenAPI in one agent).
- **Managed KB with non-default retrieval config, code interpreter, session memory** — all have harness targets (see [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).
- **An agent with a guardrail** — eligible overall; the guardrail capability just can't be carried.

(Eligible to migrate, but whose *capability* the harness can't reproduce — classify **cannot** and surface to the user: **Return-of-Control action groups** and the **guardrail**. See [mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md).)
