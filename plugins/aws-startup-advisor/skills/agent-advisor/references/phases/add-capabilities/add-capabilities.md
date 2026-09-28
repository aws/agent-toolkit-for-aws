---
_phase: add-capabilities
_title: "Add Capabilities (branch)"
_kind: sidebar
_requires_phase: intake
_trigger: { _when: "intake is done AND entry_point == add_capabilities" }
_input: workspace
_assemble:
  _file: phases/add-capabilities/add-capabilities-assemble.md
_produces:
  - capabilities-recommendation.md
_preconditions:
  - _check_phase_completed: intake
    _on_failure: _halt_and_inform
_postconditions:
  - _check_file_exists: capabilities-recommendation.md
    _on_failure: _halt_and_inform
  - _assert: "A completed recommendation enabling Registry records its intended Region and current-run verified Registry availability. Cached or unavailable Regions cannot satisfy this check; if the user instead omits a requested Registry, record that decision."
    _on_failure: _halt_and_inform
  - _assert: "capabilities-recommendation.md lists the current runtime, the services to enable (with what/why + Identity-is-free), the native-vs-bring-your-own outcome per capability, integration pointers for the current runtime, a suggested enablement order, and the freshness footer (MCP-verified vs cached)"
    _on_failure: _halt_and_inform
---

# Phase: Add Capabilities (branch)

Reached when the Turn-1 entry point is `add_capabilities`: the user already runs
an agent on AWS and wants to add AgentCore services. **No runtime scoring** —
services run on any runtime. This is a self-contained branch: it does NOT pass
through Clarify / Confirm / Design / Estimate / Generate.

## Step 0 — Create the run directory

Generate a run id from the current time as `MMDD-HHMM`. Create the run directory under the
**user's current working directory** (run `pwd` and anchor to it) — NOT the plugin install tree:
`<cwd>/.agent-advisor/<run_id>/`, plus `<cwd>/.agent-advisor/.gitignore` containing `*` (so run
state is never committed). Call this directory `$RUN_DIR`.

## Step 1 — Current runtime

Ask which runtime they run on now: AgentCore / ECS / EKS / Lambda / other. (If the user already
stated it in their opening message, skip this question.)

## Step 2 — Capabilities needed (multi-select)

Identity, Gateway, Memory, Policy, Observability, Managed KB, Code Interpreter, Browser,
Web Search, Sandbox. For each selected, load the relevant section of
`${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/agentcore.md`.
Also offer AWS Agent Registry when the user requests a shared catalog, resource discovery, or
approval-based governance. Use the service card's conditional-service guidance: a single agent
can need Registry, while multiple agents alone do not justify it. Load the Registry section
when selected and keep the recommendation conditional until Step 4 verifies its Region.

## Step 3 — Native vs bring-your-own

If they already use a third-party tool for a capability (Tavily/Pinecone/Browserbase/etc),
present: switch to AgentCore native, or keep existing and connect via Gateway.

## Step 4 — Volatile facts

Load `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/freshness.md`. This
branch has no winning runtime profile, so verify the relevant "Hard limits" facts from
`agentcore.md` directly (per freshness.md Procedure step 1). Follow its anti-fabrication rule:
only list a fact as MCP-verified if you actually called the MCP this run; otherwise it's cached.
If Registry is selected, apply freshness.md's AWS Agent Registry availability procedure,
including identifying its intended Region and handling unavailable or unverified Regions.
This check also applies when the existing runtime is ECS, EKS, Lambda, or another runtime;
this branch does not pass through Design's Region check.

## Step 5 — Output

Write the recommendation to `$RUN_DIR/capabilities-recommendation.md` (so the user can keep and
share it — consistent with the main skill's `recommendation.md`). Include:

- **Current runtime** and the capabilities requested.
- **Services to enable** — for each: what it does, why it fits, and (Identity) that it's free.
- **Native vs bring-your-own** outcome per capability (from Step 3): which go AgentCore-native
  and which stay third-party fronted via Gateway.
- **Integration on the current runtime** — concrete setup pointers (IAM/task-role changes, SDK
  calls, endpoints) for the user's runtime; note these services are standalone and require no
  runtime/compute change.
- **Suggested enablement order.**
- **Freshness footer** (per `freshness.md`: generation date, which facts were MCP-verified vs
  cached).

Then give a short in-chat summary and point the user to `$RUN_DIR/capabilities-recommendation.md`.
This branch does not score runtimes or hand off — it ends here. Set
`phases.add_capabilities` = completed (state → `complete`).
