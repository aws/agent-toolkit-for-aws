# OpenClaw Package Publishing

This directory is the canonical source for the `agentcore-payments`
OpenClaw package. PR 1797 in `awslabs/agentcore-samples` carries a traceable
snapshot for its tutorial, not a second publication source.

## Release versions

- Validation release: `1.1.0-rc.1`
- Stable release after validation: `1.1.0`

This is a minor release. Do not publish either version until the package has
passed the checks below and the publisher has given explicit approval.

## Reproducible build and tests

```bash
cd plugins/aws-agents/skills/agents-pay/packages/openclaw
npm ci
npm test
npm audit --audit-level=moderate
```

The committed lockfile pins the complete dependency graph. OpenClaw is an
optional peer because the package is loaded by an existing OpenClaw host.

## Validate and pack

Use the pinned ClawHub CLI release:

```bash
npx --yes clawhub@0.23.1 package validate . \
  --runtime --allow-execute --json

npx --yes clawhub@0.23.1 package pack . \
  --pack-destination ./artifacts --json
```

For inspection against a local OpenClaw checkout, add:

```bash
--openclaw /absolute/path/to/sample-OpenClaw-on-AWS-with-Bedrock
```

Record the generated tarball SHA-256 and verify it before publication:

```bash
shasum -a 256 artifacts/*.tgz
npx --yes clawhub@0.23.1 package verify artifacts/*.tgz \
  --sha256 <recorded-sha256> --json
```

Smoke-test installation against the minimum supported OpenClaw version:

```bash
OPENCLAW_TEST_HOME=$(mktemp -d)
HOME="$OPENCLAW_TEST_HOME" npx --yes openclaw@2026.3.24-beta.2 \
  plugins install artifacts/*.tgz
```

## Publication dry run

Run this before requesting publication approval:

```bash
npx --yes clawhub@0.23.1 package publish . \
  --family code-plugin \
  --name agentcore-payments \
  --version 1.1.0-rc.1 \
  --tags rc \
  --source-repo aws/agent-toolkit-for-aws \
  --source-commit <pr-215-head-sha> \
  --source-ref feat/agents-pay-skill \
  --source-path plugins/aws-agents/skills/agents-pay/packages/openclaw \
  --dry-run --json
```

Stop after the dry run. Publishing, creating a payment session, and spending
testnet funds each require separate explicit approval.

## Post-publication validation

Install the RC on the supplied OpenClaw instance through SSM and validate x402
v2 only:

1. Confirm the package version and the two-tool runtime inventory.
2. Confirm paid replay uses `PAYMENT-SIGNATURE`.
3. Refuse unapproved recipient, value, asset, scheme, network, origin, SSRF,
   and redirect cases before `ProcessPayment`.
4. Confirm signed proofs and paid response bodies never appear in tool output or
   gateway logs.
5. Complete one approved Base Sepolia payment.
6. Roll back to the prior plugin and configuration.

Apply any validation fix to this canonical directory first, rerun the checks,
then refresh the exact tutorial snapshot in PR 1797.
