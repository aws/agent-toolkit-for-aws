# Migrate a Bedrock Agent or a v0 CLI project

These are different migrations. Identify the source before running a command.

## AgentCore CLI v0 project

If `agentcore/agentcore.json` has `"version": 1`, commit the project and run `agentcore migrate` from the project root. Read the plan it prints and resolve any concerns. Apply it with `agentcore migrate --yes` only after approving that plan. Use `--target <name>` when the project has several deployment targets. Recheck the v2 `agentcore/agentcore.json`, run `agentcore build`, and test the migrated project before deploying. This migration preserves deployed resources; it does not import a Bedrock Agent.

## Classic Bedrock Agent to AgentCore Runtime

Use this when the source is a classic Bedrock Agent with an agent ID and an alias pointing to a prepared version. The v1 CLI translates it into a code based Runtime; it does not create a Harness. For a Harness migration, use the canonical `amazon-bedrock` guide at `skills/core-skills/amazon-bedrock/references/migrate-bedrock-agents-to-agentcore-harness.md`.

### Prerequisites

- Obtain the source agent ID, alias ID, region, and a desired Strands or LangGraph implementation.
- Confirm the alias resolves to a prepared version rather than `DRAFT`.
- Use credentials that can read the source agent, its alias, action groups, and knowledge bases.
- Start from an existing v1 project, or create one with `agentcore create --name <ProjectName> --template empty`.

### Translate and review

From the v1 project root:

```bash
agentcore add runtime \
  --name ImportedAgent \
  --agent-id <AGENT_ID> \
  --agent-alias-id <ALIAS_ID> \
  --framework strands \
  --region <SOURCE_REGION>
```

`--framework` accepts `strands` or `langgraph`. `--language` is not needed on this import path. The importer writes Runtime code and configuration into the project. Inspect the generated files and `agentcore/agentcore.json`, including the prompt, model, action groups, knowledge base references, auth, and IAM. Record anything the importer did not carry over. Source and target agents can have different prompt or tool behavior; compare actual responses before cutover.

### Test and deploy

```bash
agentcore build
agentcore dev
agentcore deploy --region <TARGET_REGION>
agentcore status --json
agentcore invoke --runtime ImportedAgent --payload '{"prompt":"Hello, what can you do?"}'
```

Set the first deployment region deliberately. `agentcore/aws-targets.json` starts empty and the first deploy creates the default target using the CLI's effective region. Use `--target` to select another target on later commands.

Keep the source Bedrock Agent running until application calls have been tested against the new Runtime. Its history and sessions are separate. For application invocation, load [integrate.md](integrate.md).
