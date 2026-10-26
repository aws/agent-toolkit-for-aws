# Example: Customer Support Agent

A complete, realistic example of a customer support agent scaffolded with `agentcore create`. Use this as a reference when the developer asks to "build a customer support agent" or similar task-framed prompts.

## What this agent does

Answers customer questions about product policies, shipping, and returns. Uses the `agent-python-strands` template (Strands as the framework, Bedrock as the model provider). The template already wires in AgentCore Memory; tools can be added later.

If the developer doesn't need custom code, the [Harness variant](#harness-variant-no-code) below is the shorter path.

## Scaffold command

```bash
agentcore create --name SupportAgent --template agent-python-strands
cd SupportAgent
```

The template's Runtime is named `agent`, so the code lives in `app/agent/`.

## Generated `main.py` (annotated)

After scaffolding, `app/agent/main.py` looks something like this (trimmed — the generated file also handles streaming event filtering). The only edit for a support agent is the system prompt:

```python
from functools import lru_cache

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model                     # scaffolded in model/load.py
from parse import parse_payload                       # reads prompt / messages / actorId
from memory.session import get_memory_session_manager # None until a memory ID is set

DEFAULT_SYSTEM_PROMPT = """You are a customer support agent for Acme Corp.
You answer questions about product policies, shipping, and returns.

Guidelines:
- Be concise and friendly
- If you don't know the answer, say so — don't make up policies
- For order-specific questions, ask for the order number
- Escalate to a human agent if the customer expresses frustration"""

tools = []

@lru_cache(maxsize=128)
def _get_agent(session_id: str, actor_id: str) -> Agent:
    return Agent(
        model=load_model(),
        session_manager=get_memory_session_manager(session_id, actor_id),
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        tools=tools,
    )

def create_app():
    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def invoke(payload, context):
        session_id = getattr(context, "session_id", None) or "default-session"
        prompt, actor_id = parse_payload(payload)
        agent = _get_agent(session_id, actor_id)
        async for event in agent.stream_async(prompt):
            yield event

    return app

app = create_app()
if __name__ == "__main__":
    app.run()
```

> The generated `model/load.py` returns a `BedrockModel` configured with a cross-region inference profile (e.g., `global.anthropic.claude-sonnet-5-5`). Using `load_model()` instead of hardcoding the model ID keeps model choice in one place. To use a different model, edit `model/load.py`.
>
> `memory/session.py` reads `MEMORY_AGENTMEMORY_ID`, which deploy injects for the template's `agentMemory` memory. Under `agentcore dev` it's unset, so the agent runs without long-term memory locally.

## Try it locally

```bash
agentcore dev
```

In another terminal:

```bash
agentcore invoke --runtime agent --local --payload '{"prompt": "What is your return policy?"}'
```

Or with `curl` (the HTTP dev server defaults to port 8080 — check the CLI output in case it moved):

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is your return policy?", "actorId": "customer-123"}'
```

## Deploy it

```bash
agentcore deploy
agentcore invoke --runtime agent --payload '{"prompt": "What is your return policy?"}'
```

## Natural next steps

After the basic agent is working, the developer typically asks for one of these next:

| "I want to..." | Next skill |
|---|---|
| "Let it look up orders in our database" | `agents-connect` (add a gateway target for the order API) |
| "Remember the customer's name between sessions" | `agents-build` (loads [`references/memory.md`](../../agents-build/references/memory.md)) — the template's memory already does this once deployed; pass a stable `actorId` |
| "Make sure it can't say anything off-policy" | `agents-connect` (loads [`references/policy.md`](../../agents-connect/references/policy.md)) |
| "Put it on our website" | `agents-build` (loads [`references/integrate.md`](../../agents-build/references/integrate.md)) |
| "Know if it's actually helpful" | `agents-optimize` |

## Variations

### Harness variant (no code)

The same agent as a config-defined Harness — no `main.py` to maintain:

```bash
agentcore create --name SupportAgent
cd SupportAgent
agentcore add harness --name support --system-prompt "You are a customer support agent for Acme Corp. You answer questions about product policies, shipping, and returns. Be concise and friendly. If you don't know the answer, say so. For order-specific questions, ask for the order number."
agentcore deploy
agentcore invoke --harness support --prompt "What is your return policy?"
```

The prompt lands in `app/support/system-prompt.md`; model, tools, skills, and memory (managed memory by default) are in `app/support/harness.yaml`. Edit either file and run `agentcore deploy` again. A Harness can't run locally — `agentcore dev` deploys it.

### LangChain variant

```bash
agentcore create --name SupportAgent --template agent-python-langchain
```

Generated `main.py` uses LangChain's `create_agent` with a LangGraph checkpointer keyed by session ID (trimmed):

```python
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model

app = BedrockAgentCoreApp()
SYSTEM_PROMPT = "..."  # same as Strands version

agent = create_agent(
    model=load_model(),
    tools=[],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver(),
)

@app.entrypoint
async def invoke(payload, context):
    config = {"configurable": {"thread_id": context.session_id or "default-session"}}
    async with await agent.astream_events(
        {"messages": [{"role": "user", "content": payload["prompt"]}]},
        config,
        version="v3",
    ) as stream:
        async for message in stream.messages:
            blocks = (await message.output).content_blocks
            if blocks:
                yield {"node": message.node, "content": blocks}

if __name__ == "__main__":
    app.run()
```

This template doesn't include a memory; add one with `agentcore add memory --name <Name>` if needed.

### TypeScript variant

```bash
agentcore create --name SupportAgent --template agent-typescript-strands
```

Edit `SYSTEM_PROMPT` in `app/agent/main.ts`. Like the Python Strands template, it includes AgentCore Memory wiring (`memory/memory.ts`) and a model loader (`model/load.ts`). For the Vercel AI SDK, use `--template agent-typescript-vercel`.

### Other frameworks (OpenAI Agents SDK, Google ADK, ...)

There's no template for these in v1. Create an empty project, register a Runtime for your own code, and follow the generated `app/<name>/README.md`:

```bash
agentcore create --name SupportAgent
cd SupportAgent
agentcore add runtime --name support --language python
```

Then write `app/support/main.py` (using `BedrockAgentCoreApp` from `bedrock-agentcore`) and `app/support/pyproject.toml` with your framework's dependency.

### Model provider options

`agentcore create --template` always uses the template's default provider (Bedrock). To choose another provider for a Strands template, run `agentcore create` with no flags — the wizard asks for the provider, model ID, and an API-key file. The key is kept in `agentcore/.env.local` for local dev and provisioned as an AgentCore Identity credential on deploy.

| Provider | Best for | Notes |
|---|---|---|
| Bedrock | Default, no API key needed, IAM-based auth | Uses cross-region inference profiles (e.g., `global.anthropic.claude-sonnet-5-5`) |
| Anthropic | Direct Anthropic API access | Requires an Anthropic API key |
| OpenAI | OpenAI models | Requires an OpenAI API key |
| OpenAI-compatible | Any endpoint speaking the OpenAI API | Requires a base URL, model ID, and API key |
| Gemini | Google Gemini models | Requires a Gemini API key |
| LiteLLM | Routing through a LiteLLM model gateway | Python templates only |

For a Harness, set the model with `agentcore add harness --name <HarnessName> --model '<JSON>'` or under `model:` in `harness.yaml` (Bedrock, OpenAI, Gemini, or a LiteLLM gateway).

For cost-sensitive use cases, consider Bedrock Nova models (e.g., `amazon.nova-micro-v1:0`, `amazon.nova-lite-v1:0`) — significantly cheaper than Claude for simpler extractive tasks. See [`agents-optimize/references/cost.md`](../../agents-optimize/references/cost.md) for model selection guidance.

For a chatbot that remembers conversations, the Strands templates and Harnesses already include memory. For other templates, add it later — see [`agents-build/references/memory.md`](../../agents-build/references/memory.md).
