# AgentCore CLI

The migration tool is the AgentCore CLI, package **`@aws/agentcore`** version **1.x**, use the **latest** version. Its command/flag surface shifts between releases, so **verify it live** rather than trusting a hardcoded flag table.

The AgentCore CLI (`@aws/agentcore`) is **not** the same as the `bedrock-agentcore-starter-toolkit`. The starter toolkit is deprecated and not recommended — do not use it or its commands for this migration. Everything here uses `@aws/agentcore`.

## Command surface in 1.x

Every project operation lives under `agentcore project …`. The pre-1.0 top-level commands (`agentcore create`, `agentcore add …`, `agentcore add tool`, `agentcore deploy`, `agentcore status`, `agentcore validate`, `agentcore import`) **no longer exist**. If a user or an older note mentions them, translate:

| Pre-1.0 | 1.x |
|---|---|
| `agentcore create` | `agentcore project create --name <project>` (a managed harness project by default) |
| `agentcore add harness` | `agentcore project add harness` (or the harness `project create` scaffolds) |
| `agentcore add gateway` | `agentcore project add gateway` |
| `agentcore add gateway-target` | `agentcore project add gateway-target --target-configuration <json>` |
| `agentcore add gateway-target --type connector` | `agentcore project add gateway-connector` |
| `agentcore add tool` | no command. Tools are declared in `app/<harness>/harness.yaml` (or `project add harness --tools <json>`) |
| `agentcore deploy` | `agentcore project deploy` |
| `agentcore status` | `agentcore project status` |
| `agentcore validate` | `agentcore project build` (validates the spec and synthesizes CloudFormation) |
| `agentcore create --import` / `agentcore import` | `agentcore project add runtime --type import` (produces a code Runtime, not a Harness) |

Harness configuration is a YAML file, `app/<harness>/harness.yaml`, with the system prompt in `app/<harness>/system-prompt.md` next to it. There is no `harness.json`.

## Authoritative, always-current sources

- Installed surface: `agentcore --help`, then `agentcore project <command> --help` for each command about to be used.
- Harness configuration shape: the commented `harness.yaml` that `project create` scaffolds documents every optional field (model, tools, memory, truncation, limits, auth). Read it before editing.
- Published / latest version: `npm view @aws/agentcore version`. `agentcore update` checks and installs updates.
- Package page: https://www.npmjs.com/package/@aws/agentcore

## Phase 0 checks

```bash
agentcore --version                  # must be 1.x
npm view @aws/agentcore version      # newer release available?
python3 -c "import boto3; print(boto3.__version__)"   # discovery path check (see discovery.md)
```

Then confirm the commands the migration actually calls exist with the flags each needs:

```bash
agentcore project create --help
agentcore project add harness --help          # --system-prompt, --model, --tools, --authorizer-type, --lifecycle-config
agentcore project add gateway --help          # --authorizer-type
agentcore project add gateway-target --help   # --target-configuration
agentcore project add gateway-connector --help
agentcore project build --help                # validates the spec, synthesizes CloudFormation
agentcore project deploy --help               # --target; region comes from --region / AWS_REGION
agentcore project status --help
```

If `agentcore --version` is not 1.x, or a required flag is **absent**, stop, don't generate commands against a surface that doesn't exist. Update the CLI (`npm install -g @aws/agentcore@latest`) and re-check, or update this skill if the references assume a flag the CLI renamed.

## Never reverse-engineer the CLI bundle
Do **not** read the CLI's bundled source (`node_modules/@aws/agentcore/dist/**`), internal names and wizard-only code paths produce confident-but-wrong conclusions. If `--help`, the scaffolded `harness.yaml`, and these references don't answer it, stop and ask the user.
