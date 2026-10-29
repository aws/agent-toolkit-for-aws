# AgentCore CLI v1 for the Harness migration

Use `@aws/agentcore` v1.0.0 or later. This is separate from the Bedrock AgentCore Starter Toolkit and from the AWS CLI. Check the installed commands before acting:

```bash
agentcore --version
agentcore create --help
agentcore add harness --help
agentcore add gateway --help
agentcore add gateway-target --help
agentcore add gateway-connector --help
agentcore build --help
agentcore deploy --help
agentcore status --help
agentcore invoke --help
```

A v1 project has `"version": 2` in `agentcore/agentcore.json`. `agentcore/aws-targets.json` is empty until the first deploy creates the default target from the effective AWS account and region. The Harness's own editable config is `app/<name>/harness.yaml`, with its prompt in `system-prompt.md`. `agentcore add harness --model` takes a JSON object such as `{"provider":"bedrock","modelId":"<source-model>"}`; the written YAML uses `model.bedrockModelConfig.modelId`. For direct YAML edits, follow the scaffolded field names. `agentcore build` validates and packages the project.

`agentcore add runtime --agent-id ... --agent-alias-id ...` translates a classic Bedrock Agent into a code Runtime. It is a separate route from this Harness migration. `agentcore migrate` converts an AgentCore CLI v0 project to v1; it does not import a classic Bedrock Agent.

Do not infer flags from v0 guides. The v1 CLI has no `add tool`, `validate`, `fetch access`, or `project` command group. Check command help and the v1 source for any option this migration needs before issuing the command.
