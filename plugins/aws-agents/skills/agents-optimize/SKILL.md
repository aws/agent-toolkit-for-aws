---
name: agents-optimize
description: >
  Use when measuring or improving agent quality and performance — set up
  evaluators, online monitoring, CI/CD quality gates, observability, or
  cost optimization. Triggers on: "evaluate my agent", "add evaluator",
  "measure quality", "quality gate", "run evals", "agent too slow",
  "why is it slow", "reduce latency", "set up observability", "CloudWatch
  dashboard", "how much does my agent cost", "cost optimization", "logs
  not showing up", "logs missing", "spans not found", "eval failing",
  "eval error", "dev traces", "local traces", "agentcore dev traces",
  "traces to CloudWatch", "batch evaluation", "eval dataset",
  "regression suite", "A/B test", "improve system prompt".
  Not for debugging errors or crashes — use agents-debug. Slow but
  correct routes here; broken routes to debug.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  requires-cli: ">=1.0.0"
---

# optimize

Measure and improve your AgentCore agent's quality through evaluation, monitoring, and observability.

## When to use

- You want to know if your agent is giving good answers
- You want to set up continuous quality monitoring in production
- You want to add a quality gate to your CI/CD pipeline
- You want to understand agent behavior through logs, metrics, and traces
- You want to set up CloudWatch dashboards or X-Ray tracing

Do NOT use for:

- Debugging a specific broken agent (wrong answers, errors) → use `agents-debug`
- Production security hardening (IAM, auth) → use `agents-harden`

## Input

`$ARGUMENTS` can be:

- An eval goal: "add a quality gate", "set up monitoring"
- An observability goal: "set up CloudWatch dashboard", "understand my traces"
- A specific evaluator: "llm-as-a-judge", "code-based"
- Empty — the skill will guide based on project context

## Process

### Step 0: Verify CLI version

Run `agentcore --version`. This skill requires v1.0.0 or later. If the version is older, tell the developer to run `npm install -g @aws/agentcore@latest` (or `agentcore update`) before proceeding — the eval, logs, and traces commands in this skill's references are v1 forms.

### Step 1: Read project context

Read `agentcore/agentcore.json` to understand existing `evaluators`, `onlineEvalConfigs`, `configBundles`, and the agents being measured (`runtimes` for your own code, `harnesses` for config-defined agents).

If `agentcore/agentcore.json` is not found:
> "This skill requires an AgentCore project. Use `agents-get-started` to create one."

The `agentcore eval ...` commands work without a project (they take deployed resource IDs), so a developer with only a deployed runtime ID can still use the on-demand and batch evaluation paths in `references/evals.md`.

If `agentcore.json` has no `"version": 2`, it is a v0 project. CLI v1 runs it in compatibility mode and blocks `add`/`remove`, so `agentcore add evaluator` and `agentcore add online-eval` will fail. Tell the developer to run `agentcore migrate` from the project root first (it shows the planned changes and asks before applying; `--yes` skips the prompt, `--target <name>` picks a target when the project is deployed to several).

### Step 2: Determine the workflow

| Developer intent | Action |
|---|---|
| Measure quality, add evaluator, run eval, CI/CD gate, online monitoring, datasets / regression runs, A/B tests, prompt recommendations | Load [`references/evals.md`](references/evals.md) and follow its workflow |
| Set up observability, CloudWatch, X-Ray, logs, metrics, dashboards | Load [`references/observability.md`](references/observability.md) and follow its workflow |
| Understand or reduce AgentCore costs | Load [`references/cost.md`](references/cost.md) |
| Both — "I want to understand and improve my agent" | Start with observability setup, then add evals |

### Step 3: Follow the loaded reference

The reference file contains the full procedure. Follow it step by step.

### Cross-references

- After setting up evals, suggest `agents-harden` for production readiness
- If eval results reveal agent issues, suggest `agents-debug` for root cause analysis
- If the developer needs to add capabilities first, suggest `agents-build`

## Output

Depends on the workflow — see the loaded reference for specific outputs.

## Quality criteria

- Evaluator configuration uses only valid CLI flags (check `agentcore <command> --help` when unsure)
- LLM-as-a-Judge instructions contain placeholders valid for the evaluator's level
- Online eval sampling rate is appropriate (not 100% in production without discussion)
- CI/CD quality gate has a clear pass/fail threshold
- Observability setup includes both tracing and logging
- The developer understands the eval data delay: **~10 seconds put-to-get, end-to-end** for deployed agents — one ingestion step covers both trace reads and eval queries; there is no separate indexing wait
- The developer understands that `agentcore dev` traces stay local (Agent Inspector / `agentcore/.cli/traces/`) and are not visible to `agentcore eval` commands, which read CloudWatch
