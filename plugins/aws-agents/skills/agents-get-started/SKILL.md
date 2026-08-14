---
name: agents-get-started
description: >
  Use when a developer wants to create a new agent project or get started
  with AgentCore. Handles Harness-vs-Runtime selection, project scaffolding,
  local development, deployment, and first invocation. Triggers on: "build an agent",
  "create an agent", "get started", "new project", "agentcore project
  create", "which
  framework", "Strands vs LangGraph", "hello world agent", "first agent",
  "create MCP server", "host MCP server", "local agent server", "dev server",
  "what port", "local development".
  Not for adding capabilities to existing projects — use agents-build
  or agents-connect. Strands vs LangGraph in a migration context routes
  to agents-build, not here. Connecting to an existing MCP server routes
  to agents-connect, not here.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  cli-surface: refactor
---

# get-started

Walk a developer from zero to a managed Harness or a Runtime project.

## When to use

- Developer wants to build an agent on AWS and doesn't know where to start
- Developer wants to create a new AgentCore project
- Developer is choosing between a managed Harness and custom Runtime code
- Developer just ran `agentcore project create` and wants to know what to do next

Do NOT use for:

- Environment/prerequisite issues (CLI not found, credentials broken) → use `agents-debug`
- Adding capabilities to an existing project (memory, tools, policies) → use `agents-build` or `agents-connect`
- Migrating an existing Bedrock Agent → use `agents-build` (loads [`references/migrate.md`](../agents-build/references/migrate.md))

## Input

`$ARGUMENTS` can be:

- A framework preference: "using LangGraph", "with Strands"
- A protocol: "MCP server", "A2A"
- A description of what the agent should do: "a customer support agent"
- Empty — the skill will guide framework selection

## Process

### Step 0: Verify the refactor command tree

```bash
agentcore project create --help
agentcore harness create --help
agentcore runtime list --help
```

There is no root `--version` flag on this branch. If any command above is
absent, stop and explain that this skill requires the refactor CLI command
tree. Do not fall back to legacy root commands or aliases.

If `agentcore` is not found:
> The AgentCore CLI refactor build is not installed. Follow the installation
> instructions for that build. If installation is failing, use
> `agents-debug`.

### Step 1: Determine intent — exploring or ready to create?

Before jumping into framework selection, figure out where the developer is:

**Ask the developer:** "Are you exploring options (comparing frameworks, understanding what AgentCore does) or ready to create a project?"

- **Exploring** → Go to Step 2 (framework comparison). Present the options, answer questions, and wait. Do not construct a `create` command until they signal they're ready.
- **Ready to create** → Skip to Step 3 (create the project). If they already specified a framework, skip Step 2 entirely.
- **Already has a project** → Inspect the current directory for generated
  project files. If found, read them and skip to Step 5. Do not re-scaffold.

If the developer's intent is clear from `$ARGUMENTS` (e.g., "create a Strands agent called MyBot"), skip straight to Step 3.

### Step 2: Choose Harness or Runtime

| Need | Choose |
|---|---|
| Managed agent loop configured with model, prompt, tools, skills, and memory | Harness |
| Custom framework, graph/workflow, protocol handling, or full loop control | Runtime project |

Create a Harness directly with `agentcore harness create`. A project is not
required. For Runtime code, `agentcore project create` scaffolds a supported
template; framework selection happens in application code.

#### Runtime framework selection

**Check conversation context first.** If the developer already discussed frameworks earlier in this conversation (e.g., from a previous skill invocation), don't re-present the full table. Summarize what was discussed and ask if they've decided, or if anything changed.

If this is the first time discussing frameworks, present the options:

**Common Python frameworks:**

| Framework | Best for |
|---|---|
| Strands | AWS-native, simplest path, best AgentCore integration |
| LangGraph | Complex graph-based workflows, existing LangChain investment |
| Google ADK | Teams already using Google's agent toolkit |
| OpenAI Agents | Teams already using OpenAI's agent SDK |

**Ask the developer to choose.** Present the options and wait for their selection. Don't assume a default unless they explicitly say they have no preference.

> **Note:** The refactor CLI does not expose a `--framework` flag. Install and
> configure the chosen framework in the scaffolded Runtime project.

**Default recommendation** (only when the developer says "no preference" or "you pick"): Strands — AWS-native framework with the tightest AgentCore integration and the most samples/docs.

**Key decision points to surface:**

- "Do you have existing agent code in LangGraph or OpenAI Agents?" → use that framework
- "Do you need complex graph-based workflows with conditional branching?" → LangGraph
- "Starting fresh with no preference?" → Strands

#### Framework not listed?

If the developer asks about a framework not in the table above, handle it:

| They ask about | What to say |
|---|---|
| **CrewAI, AutoGen, Semantic Kernel** | Use the container project path below. AgentCore Runtime is framework-agnostic — any code that implements the HTTP contract works. |
| **Anthropic SDK / Claude Agent SDK** | This is a model SDK, not an agent framework. You can use it inside any framework (Strands, LangGraph, etc.) or standalone. For standalone use, wrap it in a container with the Runtime contract. |
| **Claude Code / Cursor / Copilot** | These are IDE tools, not agent frameworks. They're where you *write* agent code, not what you deploy. Pick a framework from the table above for the agent itself. |
| **LangChain (without LangGraph)** | LangChain is a library, LangGraph is the agent framework built on it. Configure either in the scaffolded application code. |
| **Custom / homegrown framework** | BYO Container path — see below. |

**Container project path (any framework, any language):**

For custom frameworks or languages, scaffold the container template and
implement the Runtime HTTP contract (`POST /invocations`, `GET /ping`):

```bash
agentcore project create \
  --name <ProjectName> \
  --template hello-world-python-container
```

Replace the starter application with the chosen framework and container
entrypoint. Use the project lifecycle commands to build and deploy it.

**Language-specific notes:**

| Language | Recommended path |
|---|---|
| Java (Spring Boot) | [Spring AI SDK for AgentCore](https://aws.amazon.com/blogs/machine-learning/spring-ai-sdk-for-amazon-bedrock-agentcore-is-now-generally-available) — handles the Runtime contract, SSE streaming, and health checks. |
| JavaScript / TypeScript | Implement the Runtime contract in Express/Fastify/etc. |
| Go, Rust, .NET, other | Implement the Runtime HTTP contract. |

#### Framework vs. model provider — a common confusion

The framework is how your agent orchestrates (Strands, LangGraph, etc.). The model provider is which LLM it calls (Bedrock, Anthropic, OpenAI, Gemini). These are independent choices:

- Strands + Bedrock (default) — AWS-native everything
- Strands + Anthropic — Strands orchestration, direct Anthropic API for the model
- LangGraph + Bedrock — LangGraph orchestration, Bedrock for the model
- OpenAI Agents + OpenAI — OpenAI everything

If the developer says "I want to use Claude" they mean the model provider (Bedrock or Anthropic), not the framework. If they say "I want to use LangGraph" they mean the framework.

### Step 3: Create the Harness or project

For a Harness, validate the name against
`[a-zA-Z][a-zA-Z0-9_]{0,39}` and create it directly:

```bash
agentcore harness create \
  --name <HarnessName> \
  --system-prompt "You are a helpful assistant" \
  --model '{"bedrockModelConfig":{"modelId":"<MODEL_ID>"}}' \
  --max-iterations 50 \
  --timeout-seconds 300
```

Invoke it after creation:

```bash
agentcore harness invoke \
  --id <HARNESS_ID> \
  --prompt "Hello, what can you do?"
```

For a Runtime project, validate the project name before constructing the
command:

- **Length ≤ 23 characters** (this is shorter than most developers assume — `MyCustomerSupportAgent` is 22 chars and fits; `CustomerSupportChatbot` is 22 and fits; `MyCustomerSupportBotApp` is 23 and just fits; `MyCustomerSupportChatBot` is 24 and **fails**)
- **Alphanumeric only** — no hyphens, underscores, dots, or spaces
- **Must start with a letter**

Say the count back out loud when close to the limit: "That name is 24 characters — the CLI caps project names at 23. Want to shorten it to `<suggestion>`?" Do not run the command with an invalid name on the assumption that the CLI error message will be clear — it isn't always, and the developer's mental model will be wrong for subsequent commands.

Present the command for confirmation before the developer runs it:

**Default Python template:**

```bash
agentcore project create --name <ProjectName>
```

**Container template:**

```bash
agentcore project create \
  --name <ProjectName> \
  --template hello-world-python-container
```

The only project templates on this branch are `hello-world-python` (default)
and `hello-world-python-container`. Do not generate legacy framework,
protocol, build, model-provider, memory, network, or dry-run flags.

### Step 4: Explain what was created

After the project exists, inspect the generated code and explain the actual
template structure:

```bash
tree <ProjectName>/ -L 3
```

Do not assume the legacy `agentcore/agentcore.json` layout. The refactor
templates own their generated structure.

**Key files to highlight:**

- `app/<AgentName>/main.py` — the agent's entry point. This is where the developer adds tools, system prompts, and logic.
- The generated dependency file — framework and model dependencies.
- The generated environment/config files — non-secret local configuration.

**If the scaffold includes an MCP client,** inspect its endpoint and tool
wiring rather than assuming it is available locally. Two things to flag:

1. **A Gateway endpoint is an AWS resource.** If the endpoint is absent, use
   the guard pattern from `agents-connect`: `if not GATEWAY_URL: tools = []`.
2. **If the developer doesn't need MCP tools at all**, remove the `mcp_clients` list and the loop that appends it to `tools`. The scaffold includes it as a convenience, not a requirement.

The reference client code in `agents-connect` (Path A) shows the correct
pattern for gateway-backed MCP clients after the Gateway exists.

### Step 5: Local development

Start local development:

```bash
agentcore project dev
```

Use the URL printed by the command to test the generated application.

### Step 6: First deploy

Deploy the project and inspect its resource status:

```bash
agentcore project deploy
agentcore project status
```

The reference does not define flags for these commands, so keep them bare.
Once the Runtime exists, inspect and invoke it directly:

```bash
agentcore runtime get --id <RUNTIME_ID> --json
agentcore runtime invoke \
  --id <RUNTIME_ID> \
  --payload '{"prompt":"Hello, what can you do?"}' \
  --json
```

### Step 7: What's next

Based on what the developer said they want to build, suggest the logical next skill:

| Developer intent | Next skill |
|---|---|
| "How do I call it from my app?" | `agents-build` |
| "I want it to remember things" | `agents-build` |
| "I want it to call external APIs" | `agents-connect` |
| "I want to restrict what it can do" | `agents-connect` |
| "I want to measure quality" | `agents-optimize` |
| "I want to go to production" | `agents-harden` |
| "I want multiple agents working together" | `agents-build` |
| "I need it in a VPC" | `agents-build` |

Don't overwhelm — suggest one or two next steps based on what the developer actually asked for.

### Example walkthroughs

For task-framed prompts (e.g., "build a customer support agent"), load the matching example reference:

| Developer task | Reference |
|---|---|
| Customer support, chatbot, answer policy questions | [`references/example-support-agent.md`](references/example-support-agent.md) |

More examples can be added to this skill's references directory as common patterns emerge.

## Output

- A clear Harness-versus-Runtime recommendation
- A valid `agentcore harness create` or `agentcore project create` command
- An explanation of the generated project structure
- Project development, deployment, status, and Runtime invocation steps
- Concrete next steps based on their intent

## Quality criteria

- Commands use only the refactor CLI command tree
- Project lifecycle commands have no invented flags
- Framework recommendation is based on the developer's context, not a generic default
- The developer understands what each generated file does
- Next steps are specific to what the developer wants to build, not a generic list of all features
