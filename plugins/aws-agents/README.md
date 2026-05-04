# AI Agents on AWS

Build, deploy, and operate AI agents on AWS with guided workflows for every stage of the developer journey. This plugin covers the full agent lifecycle using Amazon Bedrock AgentCore as the primary runtime.

## Overview

This plugin provides 7 skills covering the full agent lifecycle — from scaffolding a new project to production hardening. Skills use progressive disclosure to load detailed reference material on demand, keeping context lean while providing deep expertise when needed.

## Skills

| Skill | When to use | References |
|---|---|---|
| `agents-get-started` | "build an agent", "create an agent", "get started", "which framework" | example-support-agent |
| `agents-build` | "add memory", "remember across sessions", "call agent from app", "VPC", "multi-agent", "migrate from Bedrock" | memory, integrate, vpc, multi-agent, migrate, local-vs-deployed |
| `agents-connect` | "connect to API", "add gateway", "give my agent tools", "Cedar policy", "restrict tools" | policy |
| `agents-deploy` | "deploy my agent", "deploy failed", "CDK error", "rollback", "canary" | versioning |
| `agents-debug` | "agent not working", "check logs", "command not found", "check my setup" | doctor |
| `agents-optimize` | "evaluate my agent", "measure quality", "quality gate", "observability", "traces", "cost" | evals, observability, cost |
| `agents-harden` | "production checklist", "go to production", "secure agent", "before launch", "cold start" | limits |

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

- AgentCore CLI v0.9.0+ (`npm install -g @aws/agentcore`)
- AWS CLI with configured credentials
- Node.js 20+
- Python 3.11+ with `uv`

## Examples

- "How do I build an agent on AWS?"
- "My agent keeps forgetting what I told it"
- "Deploy is failing with a CDK error"
- "I want to call my deployed agent from my React app"
- "Restrict my agent from making purchases over $1000"
- "How do I know if my agent is good?"
- "How much will this cost me?"
- "We're going live next week, what should I check?"
- "I need to roll back to yesterday's version"

## License

Apache-2.0
