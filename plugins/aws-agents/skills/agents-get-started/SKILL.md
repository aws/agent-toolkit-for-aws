---
name: agents-get-started
description: >
  Use when a developer wants to create a new agent project or get started
  with AgentCore. Handles the Harness vs Runtime choice, template
  selection, project scaffolding, first deploy, and first invocation.
  Triggers on: "build an agent", "create an agent", "get started", "new
  project", "agentcore create", "which template", "which framework",
  "Strands vs LangGraph", "harness or runtime", "hello world agent",
  "first agent", "create MCP server", "host MCP server", "agentcore dev",
  "dev server", "what port", "local development".
  Not for adding capabilities to existing projects — use agents-build
  or agents-connect. Strands vs LangGraph in a migration context routes
  to agents-build, not here. Connecting to an existing MCP server routes
  to agents-connect, not here.
allowed-tools: Read Grep Glob Bash
metadata:
  type: skill
  version: "1.0.0"
  author: aws-agentcore
  requires-cli: ">=1.0.0"
---

# get-started

Walk a developer from zero to a running agent on AWS.

## When to use

- Developer wants to build an agent on AWS and doesn't know where to start
- Developer wants to create a new AgentCore project
- Developer is choosing between a Harness (config-defined agent) and a Runtime (their own code), or between templates (Strands, LangChain, Vercel AI SDK, FastMCP, ...)
- Developer just ran `agentcore create` and wants to know what to do next

Do NOT use for:

- Environment/prerequisite issues (CLI not found, credentials broken) → use `agents-debug`
- Adding capabilities to an existing project (memory, tools, policies) → use `agents-build` or `agents-connect`
- Migrating an existing Bedrock Agent → use `agents-build` (loads [`references/migrate.md`](../agents-build/references/migrate.md))

## Input

`$ARGUMENTS` can be:

- A framework or language preference: "using LangChain", "with Strands", "in TypeScript"
- A protocol: "MCP server", "A2A", "AG-UI"
- A description of what the agent should do: "a customer support agent"
- Empty — the skill will guide the Harness vs Runtime and template choice

## Process

### Step 0: Verify CLI version

```bash
agentcore --version
```

This skill requires v1.0.0 or later.

If the version is older:
> Your AgentCore CLI is out of date (found vX.Y.Z, need v1.0.0+).

Offer to run the update: `npm install -g @aws/agentcore@latest` (or `agentcore update`). After the update completes, re-check the version to confirm it's ≥1.0.0 before continuing. Preserve any context the developer already provided (template preference, project name, what they want to build) so they don't have to repeat themselves.

If `agentcore` is not found:
> The AgentCore CLI isn't installed. Run `npm install -g @aws/agentcore` (requires Node.js 20.12+; Python templates also need [`uv`](https://docs.astral.sh/uv/getting-started/installation/)).
> If you're having trouble with installation, I can run the `agents-debug` skill (which loads [`references/doctor.md`](../agents-debug/references/doctor.md)) to diagnose your environment.

If the Python-based Bedrock AgentCore Starter Toolkit is installed, it also provides an `agentcore` command — have the developer uninstall it so the right CLI runs.

### Step 1: Determine intent — exploring or ready to create?

Before jumping into template selection, figure out where the developer is:

**Ask the developer:** "Are you exploring options (Harness vs Runtime, comparing frameworks, understanding what AgentCore does) or ready to create a project?"

- **Exploring** → Go to Step 2. Present the options, answer questions, and wait. Do not construct a `create` command until they signal they're ready.
- **Ready to create** → Skip to Step 3 (create the project). If they already said Harness, or named a template or framework, skip Step 2 entirely.
- **Already has a project** → Look for `agentcore/agentcore.json` in the current directory (or a parent). If found, read it and skip to Step 5 (local development). Don't re-scaffold. If the file has no `"version": 2`, it's a v0 project: v1 runs it in compatibility mode and blocks most changes. Point the developer at `agentcore migrate` (it checks the project and prints the plan without changing anything; `agentcore migrate --yes` applies it, and `--target <name>` picks the target when it's deployed to several).

If the developer's intent is clear from `$ARGUMENTS` (e.g., "create a Strands agent called MyBot"), skip straight to Step 3.

### Step 2: Harness or Runtime, then a template

**Check conversation context first.** If the developer already discussed this earlier in the conversation (e.g., from a previous skill invocation), don't re-present everything. Summarize what was discussed and ask if they've decided, or if anything changed.

#### Harness vs Runtime

A v1 project can hold either kind of agent, or both:

- A **Harness** is a managed agent you configure in YAML — model, system prompt, tools, skills, memory — and AgentCore runs for you. No agent code to write.
- A **Runtime** is agent code you own, scaffolded from a template (or brought yourself) and hosted on AgentCore Runtime.

| Choose a Harness when... | Choose a Runtime when... |
|---|---|
| A model + prompt + tools (MCP, gateways, built-in shell/file tools) + skills covers what the agent needs | You need custom orchestration logic in code, or a specific framework (Strands, LangChain/LangGraph, Vercel AI SDK, your own) |
| You want the shortest path to a deployed agent | You want a local dev loop — `agentcore dev` runs Runtime code on your machine; a Harness only runs in AWS |
| | You're serving MCP, A2A, or AG-UI, or building an execution environment for Bedrock Managed Agents |
| | You're deploying to a China region (`cn-north-1`, `cn-northwest-1`) — Harnesses aren't available there |

**Default recommendation** (when the developer says "no preference" or "you pick"): start with a **Harness**. It's what the interactive `agentcore create` wizard selects by default and what the CLI's quick start leads with. If they outgrow it, `agentcore export harness --name <HarnessName>` converts it into a Runtime with Strands code they own (see Step 7).

Recommend a **Runtime** instead as soon as any right-hand row applies, or when the developer already has agent code.

#### Runtime templates

If the developer chose a Runtime, pick a template. These are the values for `--template`:

| Template | Language | Best for |
|---|---|---|
| `agent-python-strands` | Python | AWS-native, simplest code path, best AgentCore integration. Includes AgentCore Memory wiring |
| `agent-python-strands-container` | Python | Same as above, built as a container image (custom system dependencies) |
| `agent-python-langchain` | Python | LangChain/LangGraph agents, existing LangChain investment |
| `agent-typescript-strands` | TypeScript | Strands in TypeScript, includes AgentCore Memory wiring |
| `agent-typescript-vercel` | TypeScript | Teams using the Vercel AI SDK |
| `a2a-python-strands` | Python | Agent-to-agent (A2A protocol) |
| `agui-python-strands` | Python | Agents behind an AG-UI frontend |
| `mcp-python-fastmcp` | Python | Hosting an MCP server (tools only, no agent loop) |
| `agent-python-minimal` | Python | Minimal project, no agent framework — bring your own |
| `environment-python-bma` | Python | Execution environment for Bedrock Managed Agents |
| `empty` | — | Empty project (the default when `--template` is omitted); add a Harness or Runtime afterwards |

`agentcore create --help` always lists the current set. Ask the developer to choose; don't assume a template unless they say they have no preference, in which case use `agent-python-strands` (or `agent-typescript-strands` if they want TypeScript).

**Key decision points to surface:**

- "Do you have existing agent code in LangChain/LangGraph?" → `agent-python-langchain`
- "Do you work in TypeScript?" → `agent-typescript-strands` or `agent-typescript-vercel`
- "Are you exposing tools to other agents rather than building an agent?" → `mcp-python-fastmcp`
- "Starting fresh with no preference?" → a Harness, or `agent-python-strands` if they want code

#### Framework not listed?

If the developer asks about a framework that has no template, handle it:

| They ask about | What to say |
|---|---|
| **Google ADK, OpenAI Agents SDK, CrewAI, AutoGen, Semantic Kernel** | No template for these, but AgentCore Runtime is framework-agnostic — use the BYO path below (or start from `agent-python-minimal` and add the framework's dependency). |
| **Anthropic SDK / Claude Agent SDK** | This is a model SDK, not an agent framework. You can use it inside any framework (Strands, LangChain, etc.) or standalone via the BYO path. |
| **Claude Code / Cursor / Copilot** | These are IDE tools, not agent frameworks. They're where you *write* agent code, not what you deploy. Pick a Harness or a template for the agent itself. |
| **LangGraph** | Use `agent-python-langchain` — LangChain's agent API runs on LangGraph. |
| **Custom / homegrown framework** | BYO path — see below. |

**BYO path (any framework, any language):**

`agentcore add runtime` registers a Runtime for code you write yourself. It doesn't generate code: it creates `app/<RuntimeName>/` with a `README.md` and an `AGENTS.md` describing what the code must provide for the chosen protocol, and registers the Runtime in `agentcore.json`.

1. `agentcore create --name <ProjectName>` to scaffold an empty project
2. `cd <ProjectName>` then `agentcore add runtime --name <RuntimeName> --language python` (or `--language typescript`; add `--protocol MCP|A2A|AGUI` if not HTTP)
3. Write your code in `app/<RuntimeName>/` following its `README.md`. For Python: `main.py` + `pyproject.toml`; for TypeScript: `main.ts` + `package.json`
4. Optional: add a file named `Dockerfile` to that folder — the next `agentcore dev`, `build`, or `deploy` switches the Runtime to a container build and says so
5. `agentcore deploy`

**Language-specific notes:**

| Language | Recommended path |
|---|---|
| Python | CodeZip (no Dockerfile) unless you need packages without ARM64 Linux wheels or system packages |
| TypeScript | First-class: `agent-typescript-strands`, `agent-typescript-vercel`, or `agentcore add runtime --name <Name> --language typescript` |
| Java (Spring Boot) | [Spring AI SDK for AgentCore](https://aws.amazon.com/blogs/machine-learning/spring-ai-sdk-for-amazon-bedrock-agentcore-is-now-generally-available) handles the Runtime contract. Register with `agentcore add runtime` and provide a `Dockerfile` (container build) |
| Go, Rust, .NET, other | Implement the Runtime HTTP contract (`POST /invocations`, `GET /ping` on port 8080, ARM64 Linux) and provide a `Dockerfile` |

`--language` only accepts `python` or `typescript`; for other languages the `Dockerfile` decides the build. Container images are built on ARM64 in AWS CodeBuild during deploy, so local Docker is only needed to run a container Runtime with `agentcore dev` (Docker, Podman, or Finch).

#### Framework vs. model provider — a common confusion

The framework is how your agent orchestrates (Strands, LangChain, etc.). The model provider is which LLM it calls (Bedrock, Anthropic, OpenAI, Gemini, ...). These are independent choices.

- `agentcore create --name <ProjectName> --template <name>` always scaffolds the template's default provider (Amazon Bedrock for the model-backed templates).
- To pick another provider for a Strands template (`agent-python-strands` and `-container`, `a2a-python-strands`, `agui-python-strands`, `agent-typescript-strands`), run `agentcore create` with no flags: the wizard asks for the provider (Bedrock, Anthropic, OpenAI, an OpenAI-compatible endpoint, Gemini, or LiteLLM — Python only), the model ID, and an API-key file.
- A Harness picks its model with `agentcore add harness --name <HarnessName> --model '<JSON>'` or in `harness.yaml` (Bedrock, OpenAI, Gemini, or a LiteLLM gateway).

If the developer says "I want to use Claude" they mean the model provider (Bedrock or Anthropic), not the framework. If they say "I want to use LangGraph" they mean the framework.

### Step 3: Create the project

Build the commands based on the developer's choices.

**Before constructing the command — validate the project name.** Check these rules up front (they're the CLI's own validator) and reject the name and ask for a new one if any rule fails:

- **Length ≤ 23 characters** (`MyCustomerSupportAgent` is 22 and fits; `MyCustomerSupportBotApp` is 23 and just fits; `MyCustomerSupportChatBot` is 24 and **fails**)
- **Alphanumeric only** — no hyphens, underscores, dots, or spaces
- **Must start with a letter**
- **Not a reserved package name** — the CLI rejects names that clash with a dependency it installs; if that happens, pick a more specific name

Say the count back out loud when close to the limit: "That name is 24 characters — the CLI caps project names at 23. Want to shorten it to `<suggestion>`?"

Harness and Runtime names follow a different rule: start with a letter, then letters, digits, or underscores (Harness ≤ 40 characters, Runtime ≤ 48). A deployed Harness name also includes the project and target names (`<project>_<target>_<harness>`), and that combination must fit in 40 characters — keep project and Harness names short.

**Construct the command, then present it for confirmation before the developer runs it.** Show the full commands and explain what each choice means. Wait for the developer to confirm or adjust before proceeding.

Example presentation:

> Here's what I'd recommend based on what you've told me:
>
> ```bash
> agentcore create --name MyAgent --template agent-python-strands
> ```
>
> This creates a Python Strands agent using Bedrock models, deployed as a code zip (no Docker needed), with AgentCore Memory already wired in.
>
> Want to run this, or change anything?

Do NOT execute the command automatically — present it and wait.

**Harness project:**

```bash
agentcore create --name <ProjectName>
cd <ProjectName>
agentcore add harness --name <HarnessName> --system-prompt "You are a helpful assistant."
```

`add harness` defaults to a Bedrock model and managed memory. Common options: `--model '<JSON>'` (e.g. `'{"provider":"bedrock","modelId":"<model-id>"}'`), `--tools '<JSON>'`, `--skills '<JSON>'`, `--memory '<JSON>'`, `--max-iterations`, `--timeout-seconds`. See `agentcore add harness --help`; the YAML it writes is documented in the CLI's harness project configuration guide.

**Runtime project from a template:**

```bash
agentcore create --name <ProjectName> --template <Template>
```

**Flag reference (`agentcore create`):**

| Flag | Values | Default |
|---|---|---|
| `--name` | alphanumeric, starts with a letter, max 23 chars | required |
| `--template` | see the template table in Step 2 | `empty` |
| `--skip-install` | — | installs dependencies (`npm install` for the CDK app, `uv sync` / `npm install` for the agent) |
| `--skip-git` | — | initializes a git repository |

There are no `--framework`, `--model-provider`, `--build`, `--memory`, `--protocol`, or `--network-mode` flags on `create` in v1. The template decides the framework, protocol, and build; memory, gateways, and other resources are added with `agentcore add ...`; network mode is set per Runtime (`agentcore add runtime --name <Name> --language python --network-mode VPC --network-config '<JSON>'`) or per Harness (`--network-mode` / `--network-config` on `agentcore add harness`).

**Guidance on choices:**

- **Protocol:** stay on HTTP templates unless the developer specifically needs MCP tool serving (`mcp-python-fastmcp`), agent-to-agent (`a2a-python-strands`), or an AG-UI frontend (`agui-python-strands`)
- **Build:** prefer CodeZip templates; pick `agent-python-strands-container` (or add a `Dockerfile` later) only for custom system dependencies
- **Model provider:** use Bedrock unless the developer has a specific reason for another provider (Bedrock doesn't require managing API keys)
- **Memory:** the Strands templates already include a memory (`agentMemory`). Other templates and Harnesses can add or change memory later via `agents-build` (loads [`references/memory.md`](../agents-build/references/memory.md))

Run `agentcore create` outside any existing project — project commands find the project by walking up from the current directory.

### Step 4: Explain what was created

After the project exists, read `agentcore/agentcore.json` and the generated code to explain the project structure.

The layout below reflects CLI v1.0.0. If the CLI version is different, run `tree <ProjectName>/ -L 3 -a -I node_modules` to see the actual generated structure and explain from there.

**Runtime project (`--template agent-python-strands`):**

```
<ProjectName>/
├── .gitignore
├── agentcore/
│   ├── agentcore.json      ← Project spec ("version": 2): runtimes, harnesses, memories, gateways, ...
│   ├── aws-targets.json    ← Deployment targets (starts as []; filled on first deploy)
│   ├── .env.local          ← Local-only env vars and API keys for `agentcore dev` (gitignored)
│   └── cdk/                ← Vended CDK app (bin/cdk.ts, lib/cdk-stack.ts) — yours to extend
└── app/
    └── agent/               ← The template's Runtime is always named `agent`
        ├── main.py          ← Your agent code — this is where you build
        ├── model/load.py    ← Model provider setup
        ├── memory/session.py← AgentCore Memory session manager
        ├── parse.py         ← Payload parsing (prompt / messages / actorId)
        ├── pyproject.toml   ← Python dependencies
        └── README.md
```

TypeScript templates have `main.ts`, `model/load.ts`, `package.json`, and `tsconfig.json` instead.

**Harness project (`create` + `add harness`):**

```
<ProjectName>/
├── agentcore/
│   ├── agentcore.json      ← Registers the harness: { "name": "<HarnessName>", "path": "app/<HarnessName>" }
│   ├── aws-targets.json
│   └── cdk/
└── app/
    └── <HarnessName>/
        ├── harness.yaml     ← Model, tools, skills, memory, limits, environment
        └── system-prompt.md ← The agent's instructions
```

**Key files to highlight:**

- `app/agent/main.py` (Runtime) or `app/<HarnessName>/harness.yaml` + `system-prompt.md` (Harness) — where the developer builds. Edit, then `agentcore deploy`; a local edit doesn't change an already deployed Harness.
- `agentcore/agentcore.json` — the project spec. Resources are added here via `agentcore add` commands. `agentcore dev`, `build`, and `deploy` also update a Runtime's `build`, `runtimeVersion`, and `entrypoint` from the code and print what changed.
- `agentcore/.env.local` — local environment variables for `agentcore dev`. Keep secrets here, not in `app/` (everything in a CodeZip Runtime's folder is uploaded).
- `agentcore/cdk/lib/cdk-stack.ts` — where to add your own AWS resources (tables, buckets) and grant your agents access.

**Heads-up on resource environment variables.** Resources you add are passed to a deployed Runtime as environment variables: `MEMORY_<NAME>_ID` / `MEMORY_<NAME>_ARN` for memories and `AGENTCORE_GATEWAY_<NAME>_URL` for gateways (names upper-cased). The Strands template's `memory/session.py` reads `MEMORY_AGENTMEMORY_ID` and returns no session manager when it's unset — which it is under `agentcore dev` unless you put it in `agentcore/.env.local`. So locally the agent runs without long-term memory, with no error. Code you add for gateways should handle the same case; see the "Local dev gap" section in `agents-connect` for the guard pattern.

### Step 5: Local development

```bash
agentcore dev
```

What it does depends on the agent type:

- **Runtime:** runs every Runtime in the project locally (CodeZip with `uv run` / Node, container builds with Docker, Podman, or Finch), streams their output, and collects traces locally. Default mode is `headless`; `--mode browser` opens the Agent Inspector web UI.
- **Harness:** a Harness can't run locally. `agentcore dev` **deploys** the project (same as `agentcore deploy`, honoring `--target` and `--yes`) and then prints invoke guidance; with `--mode browser` it opens the Agent Inspector against the deployed Harness. `--skip-deploy` reuses what's already deployed.
- A project with both Runtimes and Harnesses needs `--agent <name>` to choose.

**Ports** (important if you're scripting `curl` calls or testing from another process):

| Protocol | Default port |
|---|---|
| HTTP | `8080` |
| AG-UI | `8080` |
| MCP | `8000` |
| A2A | `9000` |
| Agent Inspector UI (`--mode browser`) | `8081` (`--ui-port` to change) |

**If the default port is already in use**, the CLI moves to the next free port (8080 → 8081 → ...), so a second dev session or a lingering process can shift your port. Read the actual port from the CLI output rather than hardcoding. `agentcore dev --port <N>` pins it (only with a single Runtime — add `--agent <name>` otherwise); a pinned port that's taken fails with a "Port N is already in use" error instead of moving. `--no-traces` turns off local trace collection.

Invoke the local server from another terminal:

```bash
agentcore invoke --runtime agent --local --payload '{"prompt": "Hello"}'
```

**Important limitations to mention:**

- Memory and gateway environment variables are only injected into the deployed Runtime — locally, code that guards on them (like the template's memory module) runs without them
- API keys for non-Bedrock model providers live in `agentcore/.env.local` for local dev and are provisioned as AgentCore Identity credentials on deploy. `agentcore dev` sets `LOCAL_DEV=1` so code can tell the two apart
- `environment-python-bma` Runtimes don't support local dev

### Step 6: First deploy

When the developer is ready to deploy:

```bash
agentcore deploy
```

This will:

1. On first deploy, create the `default` target in `agentcore/aws-targets.json` from the active AWS account (via STS) and the CLI's region (`--region`, then `AWS_REGION` / `AWS_DEFAULT_REGION`, then the active profile, then `us-east-1`)
2. Provision credential providers, synthesize the CDK app, and bootstrap CDK in the account/region if needed
3. Deploy the stack (container images are built in AWS CodeBuild)

There's no preview or confirmation step on a normal deploy. To check the build locally first, run `agentcore build` (see `agents-deploy`). **First deploy usually takes a few minutes.** Subsequent deploys are faster.

After deploy, show them how to invoke:

```bash
# Runtime
agentcore invoke --runtime agent --payload '{"prompt": "Hello, what can you do?"}'

# Harness
agentcore invoke --harness <HarnessName> --prompt "Hello, what can you do?"
```

Pass `--session-id <id>` to continue a conversation. And how to check status:

```bash
agentcore status
```

### Step 7: What's next

Based on what the developer said they want to build, suggest the logical next skill:

| Developer intent | Next skill | Command hint |
|---|---|---|
| "How do I call it from my app?" | `agents-build` | `agentcore status --json` (deployed ARNs for the SDK) |
| "I want it to remember things" | `agents-build` | `agentcore add memory --name <Name>` |
| "I want it to call external APIs" | `agents-connect` | `agentcore add gateway --name <Name>` |
| "I want to restrict what it can do" | `agents-connect` | `agentcore add policy-engine --name <Name>` |
| "I want to measure quality" | `agents-optimize` | `agentcore add evaluator llm-as-a-judge --name <Name> --level SESSION --model <ModelId> --instructions file://judge.md --rating-scale 1-5-quality` |
| "I want to go to production" | `agents-harden` | production readiness checklist |
| "I want multiple agents working together" | `agents-build` | `agentcore add runtime --name <Name> --language python --protocol A2A` |
| "I need it in a VPC" | `agents-build` | `--network-mode VPC --network-config '<JSON>'` on `add runtime` / `add harness` |
| "My Harness needs custom code" | `agents-build` | `agentcore export harness --name <HarnessName>` (converts it to a Runtime with Strands Harness SDK code) |

Don't overwhelm — suggest one or two next steps based on what the developer actually asked for.

### Example walkthroughs

For task-framed prompts (e.g., "build a customer support agent"), load the matching example reference:

| Developer task | Reference |
|---|---|
| Customer support, chatbot, answer policy questions | [`references/example-support-agent.md`](references/example-support-agent.md) |

More examples can be added to this skill's references directory as common patterns emerge.

## Output

- A clear path from "I want to build an agent" to a running deployed agent
- A Harness vs Runtime recommendation and the `agentcore create` (+ `agentcore add harness`) commands tailored to their choices
- An explanation of the generated project structure
- Concrete next steps based on their intent

## Quality criteria

- Every `agentcore` command uses only flags that exist in CLI v1 (`agentcore <command> --help`)
- The Harness vs Runtime and template recommendation is based on the developer's context, not a generic default
- The developer understands what each generated file does
- Next steps are specific to what the developer wants to build, not a generic list of all features
