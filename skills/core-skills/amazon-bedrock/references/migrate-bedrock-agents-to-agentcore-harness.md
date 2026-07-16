# Bedrock Agents to AgentCore Harness

Migrate a Bedrock Agent into an AgentCore **Harness** (the managed agent loop) using the **AgentCore CLI**. The skill drives the CLI to scaffold and deploy; it never hand-rolls boto3 infrastructure the CLI owns. Remeber that this skill can be used for performing the migration AND helping the user answer any migration related questions even if they don't want to perform the migration.

Reference files, scripts and templates are available in [references](references/bedrock-agents-to-agentcore-harness/)

**Inline agents.** This guidance also migrates a Bedrock **inline** agent (one invoked via `InvokeInlineAgent` with its configuration supplied per-request rather than persisted as a stored agent). An inline agent has no `agentId`, so it takes a modified entry path: **its `InvokeInlineAgent` request payload *is* the source manifest.** Concretely — **skip Phase 0's agent-region confirm and all of Phase 1 (identity resolution) and Phase 2's fetch (`fetch_bedrock_agent.py` needs an `--agent-id` an inline agent doesn't have)**; instead, take the user-supplied `InvokeInlineAgent` payload, extract its components (`foundationModel`, `instruction`, `actionGroups`, `knowledgeBases`, `guardrailConfiguration`, prompt overrides), write them into `./out/source-agent.json` in the manifest shape ([bedrock-agents-to-agentcore-harness/discovery.md](references/bedrock-agents-to-agentcore-harness/discovery.md)), then **enter at Phase 3**. Every phase from Phase 3 on — eligibility gates, component mapping, deploy — applies unchanged, since they operate on the manifest, not on how it was obtained.

Two ideas run through every phase:

- **gate** — a hard checkpoint the migration must pass before continuing. Some gates are eligibility (a source feature with no validated harness path); others are user approval (account, region, cost). A failed gate stops the migration and is reported, never worked around silently.
- **mirror** — preserve user-visible *behavior*, not Bedrock-Agents *structure*: keep what the agent does, drop only what the harness now does for you (see [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)).

This skill makes AWS API calls throughout (STS, Bedrock Agent reads, deploys). The **AWS MCP server is recommended** for streamlined access, but is not required — every step also works with the AWS CLI and boto3 as described here.

## Capture the request first

The triggering request *is* the input. Extract whatever the user gave — agent **id/name/ARN**, **region**, **profile/account** — and **confirm** it in the phases below rather than re-asking. Identity resolution (Phase 1) runs *after* preflight, since listing agents to disambiguate a name needs a confirmed account + region first.

**Fail fast.** If the request *already* names a hard-stop disqualifier (multi-agent, custom orchestration, multimodal), say so and stop before preflight — always with that condition's specific alternative from [bedrock-agents-to-agentcore-harness/eligibility.md](references/bedrock-agents-to-agentcore-harness/eligibility.md), never a bare "not supported." Phase 3 still runs the full gate for everything that clears this.

## Phases

Finish each phase and summarize before the next.

### Phase 0 — Preflight (environment gates)

Establish the migration runs against the account, region, and CLI the user intends — before touching the source agent.

1. Confirm the **CLI** is present and current per [bedrock-agents-to-agentcore-harness/cli.md](references/bedrock-agents-to-agentcore-harness/cli.md). Stop if it is missing or a required command/flag is absent.
2. Resolve AWS credentials and run `aws sts get-caller-identity`. **Echo the account id, caller ARN, and resolved region back to the user and ask them to confirm or correct** before proceeding. Never assume the default profile is the right one.
3. Confirm the **source agent's region** here (if the user supplied one, confirm rather than re-ask). The harness must deploy there — but the CLI defaults elsewhere, so you set it explicitly before the first deploy (Phase 6; see deploy.md's region trap).

Completion criterion: the user has confirmed `(account, region)` and the CLI passed its checks.

### Phase 1 — Identify the source agent

**Inline agents skip this phase** (they have no `agentId`; see "Inline agents" above — take the payload and enter at Phase 3).

Resolve a concrete `(agentId, agentVersion, aliasId)` from whatever the user gave (id, name, ARN, or nothing). If the user gave a name fragment, gave nothing, or **asks to see what's available**, list the agents in the confirmed region (`bedrock-agent:ListAgents`) and present them for the user to pick from. Default to the **production alias's** numbered version, not DRAFT — unless the user has only DRAFT or asks for it explicitly. See [bedrock-agents-to-agentcore-harness/discovery.md](references/bedrock-agents-to-agentcore-harness/discovery.md) for resolution rules and the DRAFT-only case.

Completion criterion: the user has confirmed the exact `(account, region, agentId, agentVersion, aliasId)` tuple.

### Phase 2 — Discovery

Snapshot the agent into one manifest (`./out/source-agent.json`) — via the bundled `scripts/fetch_bedrock_agent.py` (needs python3 + boto3), or the `aws bedrock-agent` fallback when boto3 is absent. Both paths and the manifest shape are in [bedrock-agents-to-agentcore-harness/discovery.md](references/bedrock-agents-to-agentcore-harness/discovery.md). **For an inline agent** the fetch script does not apply (no `agentId`) — build the manifest from the `InvokeInlineAgent` payload instead, per "Inline agents" above and discovery.md's inline note.

Read the manifest and present a **concise, human-readable inventory** — a scannable list or small table (model; action groups by name + type; KBs + type; guardrail; memory; collaboration), not a prose paragraph.

Also capture the source's **security posture** so the migration can preserve it (see [bedrock-agents-to-agentcore-harness/deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md)): its **inbound invocation posture** (which principals hold `bedrock-agent-runtime:InvokeAgent`, plus any resource-based policy on the agent) and its `idleSessionTTLInSeconds`. These set the bar Phase 6 must match, not loosen.

Completion criterion: manifest written and inventory presented.

### Phase 3 — Eligibility gate

Check the manifest against the eligibility rubric in [bedrock-agents-to-agentcore-harness/eligibility.md](references/bedrock-agents-to-agentcore-harness/eligibility.md). Any **hard-stop** condition (multimodal input, multi-agent collaboration, unreachable KB, custom orchestration) ends the migration here.

If a gate fails: **stop**, tell the user exactly which condition failed and why, and suggest manual alternatives.

Completion criterion: every hard-stop condition checked and explicitly cleared, or the migration stopped with a reported reason.

### Phase 4 — Migration assessment (gate)

The agent is eligible, but not every component migrates with full fidelity. Before planning, show the user a **per-component ledger** classifying each discovered component three ways:

- **clean** — behavior preserved. Most components land here: action groups via shim, *any* KB (MANAGED-with-default-config via connector, everything else via KB shim — both reproduce retrieval, see [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)), CodeInterpreter built-in, model + inference params, and managed memory (the standard harness memory, not a downgrade).
- **degraded** — a genuine fidelity change the user should weigh, e.g. a non-DEFAULT orchestration/pre-processing prompt whose business logic can't be cleanly folded into the system prompt, or any behavior the migration can only approximate.
- **cannot** — no harness equivalent, capability lost: Return-of-Control action groups and the **guardrail** (see [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md)). Surface both to the user.

Use the mapping in [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md) to classify. Present the ledger and **pause for explicit acknowledgement** — the user must accept the *degraded* and *cannot* items before planning. Nothing irreversible has happened yet; this is informed consent on fidelity loss.

Completion criterion: user has seen the full ledger and acknowledged the degraded/cannot items.

### Phase 5 — Plan

Map each acknowledged component to its harness target using [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md). Produce a written **migration plan** and **pause for approval** (gate). Surface costs and that the source agent is never modified.

Completion criterion: user approved the written plan.

### Phase 6 — Implement & deploy

Drive the CLI per the approved plan, following [bedrock-agents-to-agentcore-harness/deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md) end to end: scaffold with plain `agentcore create`, deploy the shim Lambdas, `add gateway`/`gateway-target`/`harness`, then the **two-phase deploy**. On scaffolding specifically: use `agentcore create` with no flags. Do **not** use `agentcore create --import` (or `agentcore import`) — that flag *does exist*, but it imports the Bedrock Agent into a **code project**, not a Harness, so it is the wrong route for this migration. There is **no** `agentcore init` command. Set the deploy region before the first deploy (deploy.md's region trap). Generate shim code and tool schemas by **adapting** the `.tmpl` templates in `assets/` per [bedrock-agents-to-agentcore-harness/mapping.md](references/bedrock-agents-to-agentcore-harness/mapping.md). Configure the harness/gateway **inbound auth** to match the source's invocation posture discovered in Phase 2 (deploy.md "Inbound auth") — do not accept the CLI default if it is broader. If deploy fails, surface the error — **fail loudly**, never silently work around it. In particular, if a shim invocation fails with `AccessDenied`, **do not** run `aws lambda add-permission` on the source — that mutates source-side infra; stop and hand the builder the command (deploy.md "Source-side prerequisites").

Completion criterion: `agentcore deploy` reports success. Verification is deploy-success-only; deeper parity is out of scope.

## Security considerations

- **Least-privilege shim roles** — one action on one resource ARN, no wildcards; exact policies in [bedrock-agents-to-agentcore-harness/deploy.md](references/bedrock-agents-to-agentcore-harness/deploy.md).
- **The manifest holds sensitive data** — handling rules in [bedrock-agents-to-agentcore-harness/discovery.md](references/bedrock-agents-to-agentcore-harness/discovery.md).
- **Use ephemeral credentials** (IAM roles, SSO, `assume-role`) for both discovery and deploy — never long-lived IAM user access keys.

## What this migration can not do

- Modify or delete the source Bedrock Agent.
- Modify the source Lambda's resource policy. If a shim invocation fails with `AccessDenied`, stop and ask the builder to grant the shim role `lambda:InvokeFunction` on the source (deploy.md "Source-side prerequisites") — never run `add-permission` on the source itself.
- Migrate KB vector stores / data sources — the new agent calls into the existing KB.
- Migrate conversation history or end-user authentication.
- Bypass the AgentCore CLI for infrastructure the CLI owns.
