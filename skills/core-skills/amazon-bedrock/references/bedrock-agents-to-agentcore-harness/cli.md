# AgentCore CLI

The migration tool is the AgentCore CLI, package **`@aws/agentcore`** — use the **latest** version. Its command/flag surface shifts between releases, so **verify it live** rather than trusting a hardcoded flag table.

The AgentCore CLI (`@aws/agentcore`) is **not** the same as the `bedrock-agentcore-starter-toolkit`. The starter toolkit is deprecated and not recommended — do not use it or its commands for this migration. Everything here uses `@aws/agentcore`.

## Authoritative, always-current sources

- Installed surface: `agentcore --help`, then `agentcore <command> --help` for each command about to be used.
- Per-project schema the CLI ships: `https://schema.agentcore.aws.dev/v1/agentcore.json` inside any scaffolded project (authoritative shape for `agentcore.json`, harness, gateway, target, tool-schema). Read before hand-editing config.
- Published / latest version: `npm view @aws/agentcore version`.
- Package page: https://www.npmjs.com/package/@aws/agentcore

## Phase 0 checks

```bash
agentcore --version
npm view @aws/agentcore version      # newer release available?
python3 -c "import boto3; print(boto3.__version__)"   # discovery path probe (see discovery.md)
```

Then probe the commands the migration actually calls and confirm the flags/values each needs are present:

```bash
agentcore create --help
agentcore add gateway --help
agentcore add gateway-target --help
agentcore add harness --help
agentcore add tool --help
agentcore deploy --help
```

If a required flag is **absent**, stop — don't generate commands against a surface that no longer exists. Update the CLI (`npm install -g @aws/agentcore@latest`) and re-probe, or update this skill if the references assume a flag the CLI renamed.

## Never reverse-engineer the CLI bundle
Do **not** read the CLI's minified source (`node_modules/@aws/agentcore/dist/**`) — internal names and wizard-only code paths produce confident-but-wrong conclusions. If `--help`, `.llm-context`, the hosted schema, and these references don't answer it, stop and ask the user.
