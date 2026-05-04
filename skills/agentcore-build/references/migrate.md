# migrate

Move an existing Amazon Bedrock Agent to AgentCore Runtime.

## When to use

- You have an existing Bedrock Agent (created via the Bedrock console or API) and want to run it on AgentCore Runtime
- You want to add AgentCore capabilities (Memory, Gateway, Observability) to an existing agent
- You want to move from the declarative Bedrock Agents model to a code-first framework

## Input

`$ARGUMENTS` is optional:

```
/migrate                    # interactive — walks through the migration
/migrate strands            # migrate targeting Strands framework
/migrate langgraph          # migrate targeting LangGraph framework
```

## What migration does

The `agentcore create --type import` command reads your existing Bedrock Agent's configuration and generates an AgentCore project that reproduces its behavior in a code-first framework. Specifically:

- **System prompt** → copied into the generated `main.py`
- **Action groups (Lambda-backed)** → converted to Gateway targets with `--type lambda-function-arn`
- **Knowledge bases** → referenced in the system prompt with a note to wire retrieval manually (AgentCore doesn't auto-import KB bindings)
- **Guardrails** → noted in comments but not auto-converted (AgentCore uses Cedar policies, not Bedrock Guardrails)
- **Agent alias / version** → the import targets a specific alias, not the draft

What migration does **not** do:

- It does not delete or modify the original Bedrock Agent — the source agent keeps running
- It does not migrate conversation history or session state
- It does not convert Bedrock Guardrails to Cedar policies (different authorization model)
- It does not auto-wire Knowledge Base retrieval — you'll need to add that as a tool or direct SDK call

## Prerequisites

1. The Bedrock Agent must exist and have at least one alias
2. Your AWS credentials must have `bedrock:GetAgent`, `bedrock:GetAgentAlias`, and `bedrock:ListAgentActionGroups` permissions
3. You need the agent ID, alias ID, and region

## Process

### Step 1: Run the import

```bash
agentcore create \
  --type import \
  --agent-id <AGENT_ID> \
  --agent-alias-id <ALIAS_ID> \
  --region <REGION> \
  --name <ProjectName> \
  --framework Strands
```

The `--framework` flag determines which code-first framework the generated project uses. Strands is recommended for the closest mapping to Bedrock Agent behavior.

**Project name rules apply:** max 23 characters, alphanumeric only, starts with a letter.

### Step 2: Review the generated project

```bash
cd <ProjectName>
cat app/<AgentName>/main.py
cat agentcore/agentcore.json
```

Check:

- The system prompt matches your original agent's instructions
- Action groups appear as Gateway targets in `agentcore.json` (under `agentCoreGateways`)
- The model ID is correct for your target region

### Step 3: Fill in what migration doesn't cover

**Knowledge Bases:** If your Bedrock Agent used Knowledge Bases, you have two options:

1. **Keep using the KB via boto3** — call `bedrock-agent-runtime:RetrieveAndGenerate` or `Retrieve` directly from your agent code as a tool
2. **Replace with AgentCore Memory** — if the KB was used for user-specific context, AgentCore Memory with SEMANTIC strategy may be a better fit. See [memory.md](memory.md).

**Guardrails → Cedar policies:** Bedrock Guardrails (content filters, denied topics, word filters) don't have a 1:1 mapping to Cedar policies. Cedar policies control *which tools the agent can call and with what parameters* — they're authorization rules, not content filters. If you need content filtering, keep the guardrail logic in your agent code (pre/post-processing) or use Bedrock Guardrails as a standalone API call.

**Custom orchestration:** If your Bedrock Agent used custom orchestration (return-of-control, custom Lambda orchestrators), you'll need to rebuild that logic in the framework's native patterns — Strands tool chains, LangGraph graph nodes, etc.

### Step 4: Test locally and deploy

```bash
# Test locally (memory and gateway won't be available yet)
agentcore dev

# Deploy when ready
agentcore deploy -y

# Verify
agentcore invoke "Hello, what can you do?"
agentcore status
```

### Step 5: Cut over traffic

Once the AgentCore agent is working correctly:

1. Update your application to invoke the AgentCore Runtime instead of the Bedrock Agent
2. See [integrate.md](integrate.md) for the invocation patterns (SigV4, JWT, SDK)
3. Keep the original Bedrock Agent running as a fallback until you're confident
4. Delete the Bedrock Agent only after the AgentCore agent has been stable in production

## Common migration issues

**"Model not available in target region"**
The imported agent may reference a model ID that isn't available in your AgentCore deployment region. Edit `model/load.py` to use a cross-region inference profile or a model available in your region.

**"Action group Lambda in a different region"**
Gateway targets can invoke Lambda functions cross-region, but latency increases. Consider deploying the Lambda in the same region as your AgentCore agent, or accept the latency trade-off.

**"Agent behavior differs after migration"**
The most common cause is prompt format differences between Bedrock Agent's orchestration and the code-first framework. Bedrock Agent injects structured XML around tool results; Strands/LangGraph use different formats. Tune the system prompt to compensate.

## Output

- A working AgentCore project that reproduces the Bedrock Agent's behavior
- A list of what was auto-converted and what needs manual work
- Guidance on cutting over traffic from the old agent to the new one
