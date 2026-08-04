# OpenClaw Plugin — Publishing & Maintenance

This directory contains the source code for the `@aws/aws-agent-payments` OpenClaw
plugin, published to [ClawHub](https://clawhub.dev).

## Source of Truth

**This directory is the canonical source.** The published ClawHub package is built
from here. When making changes, update this directory and republish.

## Prerequisites

- Node.js 20+
- OpenClaw CLI installed (`npm install -g openclaw@2026.3.24-beta.2`)
- ClawHub credentials configured (`openclaw auth login`)

## Build

```bash
cd plugins/aws-agents/skills/agents-pay/packages/openclaw
npm ci
npm run build
```

This installs the exact dependency graph from `package-lock.json` and compiles
TypeScript from `src/` into `dist/`.

## Test locally

```bash
# Install from local path (no publish needed)
openclaw plugins install ./plugins/aws-agents/skills/agents-pay/packages/openclaw

# Verify it loads
openclaw plugins list | grep x402
```

## Publish to ClawHub

```bash
cd plugins/aws-agents/skills/agents-pay/packages/openclaw

# Bump version in package.json, then:
npm run build
openclaw plugins publish

# Verify
openclaw plugins search @aws/aws-agent-payments
```

The `openclaw plugins publish` command:
1. Reads `package.json` (name, version, description)
2. Reads `openclaw.plugin.json` (tool contracts, config schema, activation)
3. Bundles `dist/` + metadata
4. Uploads to ClawHub under the `@aws` scope

## Version bumping

Follow semver:
- **Patch** (1.0.x): bug fixes, dependency updates
- **Minor** (1.x.0): new tools, non-breaking config changes
- **Major** (x.0.0): breaking config schema changes, removed tools

Update `version` in `package.json` only — ClawHub reads it from there.

## Users install with

```bash
openclaw plugins install clawhub:@aws/aws-agent-payments
```

## Avoiding dual-source drift

If someone modifies the published ClawHub package without updating this directory,
the versions will diverge. To prevent this:

1. Always develop here first
2. Test locally with `openclaw plugins install ./`
3. Only publish from this directory
4. CI can verify: `openclaw plugins info @aws/aws-agent-payments` version matches
   `package.json` version in this directory
5. Build from `npm ci` and the committed `package-lock.json`, not mutable dependency ranges

## Directory structure

```
packages/openclaw/
├── package.json              # npm manifest + openclaw metadata
├── tsconfig.json             # TypeScript config
├── openclaw.plugin.json      # Plugin manifest (tools, config schema)
├── PUBLISHING.md             # This file
└── src/
    ├── index.ts              # Plugin entry — registers tools + hooks
    ├── config.ts             # Config loading (plugin config or ~/.x402/config.json)
    ├── payments.ts           # AgentCore SDK wrapper (sessions, ProcessPayment, setup)
    └── x402.ts               # x402 protocol (probe, challenge extraction, replay)
```
