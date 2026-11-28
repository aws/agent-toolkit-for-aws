# AI Agents on AWS

Build, deploy, and operate AI agents on AWS with guided workflows for every stage of the developer journey. This plugin covers the full agent lifecycle using Amazon Bedrock AgentCore as the primary runtime.

## Overview

This plugin provides 8 skills covering the full agent lifecycle — from scaffolding a new project to production hardening. Skills use progressive disclosure to load detailed reference material on demand, keeping context lean while providing deep expertise when needed.

## Skills

| Skill | When to use | References |
|---|---|---|
| `agents-get-started` | "build an agent", "create an agent", "get started", "which framework" | example-support-agent |
| `agents-build` | "add memory", "remember across sessions", "call agent from app", "VPC", "multi-agent", "migrate from Bedrock" | memory, integrate, vpc, multi-agent, migrate, local-vs-deployed, browser, code-interpreter, payments, request-headers |
| `agents-connect` | "connect to API", "add gateway", "give my agent tools", "Cedar policy", "restrict tools" | policy |
| `agents-deploy` | "deploy my agent", "deploy failed", "CDK error", "rollback", "canary" | versioning |
| `agents-debug` | "agent not working", "check logs", "command not found", "check my setup" | doctor |
| `agents-optimize` | "evaluate my agent", "measure quality", "quality gate", "regression suite", "observability", "traces", "cost" | evals, observability, cost |
| `agents-harden` | "production checklist", "go to production", "secure agent", "before launch", "cold start" | limits |
| `agents-pay` | "this agent needs to pay", "x402", "402 Payment Required", "spend limit for agent" — the agent paying for itself at run time | operator-guide, security-model, setup, troubleshooting, openclaw-setup |

## Routing guide

When in doubt about which skill to reach for:

- **Starting from nothing?** → `agents-get-started`
- **Environment/CLI broken?** → `agents-debug` (loads `references/doctor.md`)
- **Adding new capabilities to a working project?** → `agents-build`
- **Connecting to external tools/APIs or restricting access?** → `agents-connect`
- **Ready to ship?** → `agents-deploy`
- **Agent is broken?** → `agents-debug`
- **Measuring quality, observability, or cost?** → `agents-optimize`
- **Going to production?** → `agents-harden`
- **The agent you're running needs to pay for something?** → `agents-pay`
- **Building payment capability into an agent you ship?** → `agents-build`

## MCP Servers

| Server | Purpose |
|---|---|
| `awsknowledge` | AWS documentation, architecture guidance, and service reference |

## Installation

### Claude Code

```
/plugin marketplace add aws/agent-toolkit-for-aws
/plugin install aws-agents@agent-toolkit-for-aws
```

### Codex

Discovered automatically from the marketplace manifest.

## Prerequisites

- AgentCore CLI v1.0.0+ (`npm install -g @aws/agentcore@latest`). Projects created with CLI v0 can be upgraded with `agentcore migrate`, which needs the project committed to git with no uncommitted changes.
- AWS CLI v2 with configured credentials. Keep it current: the CloudWatch Omni flows use `aws cloudwatchomni`, and checking eval resources with `aws bedrock-agentcore-control list-evaluators` / `list-online-evaluation-configs` also needs a recent release; older ones (for example 2.32.5) don't have them.
- Node.js 20.12+
- For Python agents and code-based evaluators: Python 3.10+ with [`uv`](https://docs.astral.sh/uv/) (3.12+ for the `agui-python-strands` and `environment-python-bma` templates). TypeScript agents need only Node.js.
- `git`, `jq`, and `uuidgen` — the skills' shell snippets use them (migrate's git check, parsing `--json` output, generating session IDs).
- Optional: [`otelcol-contrib`](https://github.com/open-telemetry/opentelemetry-collector-releases/releases) (or Docker) for the CloudWatch Omni local trace check.
- Bedrock model access for the model your agent uses. Many models, including recent Anthropic models, must be called through an inference profile ID (for example `global.anthropic.claude-...` or `us.anthropic.claude-...`) rather than the bare model ID; the CLI templates already use one.

## Examples

- "How do I build an agent on AWS?"
- "My agent keeps forgetting what I told it"
- "Deploy is failing with a CDK error"
- "I want to call my deployed agent from my React app"
- "Restrict my agent from making purchases over $1000"
- "How do I know if my agent is good?"
- "How much will this cost me?"
- "This agent needs to pay for a paywalled API right now"
- "We're going live next week, what should I check?"
- "I need to roll back to yesterday's version"

## License

Apache-2.0
