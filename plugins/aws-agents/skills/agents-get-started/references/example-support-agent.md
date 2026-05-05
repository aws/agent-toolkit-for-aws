# Example: Customer Support Agent

A complete, realistic example of a customer support agent scaffolded with `agentcore create`. Use this as a reference when the developer asks to "build a customer support agent" or similar task-framed prompts.

## What this agent does

Answers customer questions about product policies, shipping, and returns. Uses Strands as the framework, Bedrock (Claude Sonnet) as the model, and starts without memory or tools (both can be added later).

## Scaffold command

```bash
agentcore create \
  --name SupportAgent \
  --framework Strands \
  --protocol HTTP \
  --build CodeZip \
  --model-provider Bedrock \
  --memory none
```

## Generated `main.py` (annotated)

After scaffolding, `app/SupportAgent/main.py` looks something like:

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from model.load import load_model  # scaffolded by `agentcore create` in model/load.py

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """You are a customer support agent for Acme Corp.
You answer questions about product policies, shipping, and returns.

Guidelines:
- Be concise and friendly
- If you don't know the answer, say so — don't make up policies
- For order-specific questions, ask for the order number
- Escalate to a human agent if the customer expresses frustration"""

@app.entrypoint
def invoke(payload, context):
    agent = Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
    )
    result = agent(payload.get("prompt", ""))
    return {"response": str(result)}

if __name__ == "__main__":
    app.run()
```

> The generated `model/load.py` returns a `BedrockModel` configured with a cross-region inference profile (e.g., `global.anthropic.claude-sonnet-4-5-*`). Using `load_model()` instead of hardcoding the model ID means your code tracks whatever default the CLI ships. To use a different model, edit `model/load.py`.

## Try it locally

```bash
agentcore dev
```

In another terminal:

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is your return policy?"}'
```

## Deploy it

```bash
agentcore deploy
```

## Natural next steps

After the basic agent is working, the developer typically asks for one of these next:

| "I want to..." | Next skill |
|---|---|
| "Let it look up orders in our database" | `agents-connect` (add a gateway target for the order API) |
| "Remember the customer's name between sessions" | `agents-build` (loads [`references/memory.md`](../../agents-build/references/memory.md)) |
| "Make sure it can't say anything off-policy" | `agents-connect` (loads [`references/policy.md`](../../agents-connect/references/policy.md)) |
| "Put it on our website" | `agents-build` (loads [`references/integrate.md`](../../agents-build/references/integrate.md)) |
| "Know if it's actually helpful" | `agents-optimize` |

## Variations

### LangGraph variant

```bash
agentcore create --name SupportAgent --framework LangChain_LangGraph --model-provider Bedrock --memory none
```

Generated `main.py` uses `create_react_agent` and `langchain_aws`:

```python
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model

app = BedrockAgentCoreApp()
SYSTEM_PROMPT = "..."  # same as Strands version

@app.entrypoint
async def invoke(payload, context):
    graph = create_react_agent(load_model(), tools=[])
    result = await graph.ainvoke({
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=payload["prompt"]),
        ]
    })
    return {"response": result["messages"][-1].content}

if __name__ == "__main__":
    app.run()
```

### OpenAI Agents SDK variant

```bash
agentcore create --name SupportAgent --framework OpenAIAgents --model-provider OpenAI --memory none
```

```python
from agents import Agent, Runner
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload, context):
    agent = Agent(
        name="SupportAgent",
        instructions="...",  # same as Strands version
    )
    result = await Runner.run(agent, payload["prompt"])
    return {"response": result.final_output}

if __name__ == "__main__":
    app.run()
```

### Google ADK variant

```bash
agentcore create --name SupportAgent --framework GoogleADK --model-provider Gemini --memory none
```

```python
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

agent = Agent(
    model="gemini-2.5-flash",
    name="SupportAgent",
    description="Customer support agent",
    instruction="...",  # same as Strands version
)

@app.entrypoint
async def invoke(payload, context):
    user_id = payload.get("user_id", "default_user")
    session_id = getattr(context, "session_id", "default_session")
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="support", user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=agent, app_name="support", session_service=session_service)
    content = types.Content(role="user", parts=[types.Part(text=payload["prompt"])])
    async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=content):
        if event.is_final_response():
            return {"response": event.content.parts[0].text}

if __name__ == "__main__":
    app.run()
```

### Model provider options

The CLI supports four model providers:

| Provider | Best for | Notes |
|---|---|---|
| `Bedrock` | Default, no API key needed, IAM-based auth | Uses cross-region inference profiles (e.g., `global.anthropic.claude-sonnet-4-5-*`) |
| `Anthropic` | Direct Anthropic API access | Requires `ANTHROPIC_API_KEY`; model IDs like `claude-sonnet-4-5-20250929` |
| `OpenAI` | GPT-4 / GPT-5 models | Requires `OPENAI_API_KEY`; typically paired with OpenAI Agents SDK |
| `Gemini` | Google Gemini models | Requires `GEMINI_API_KEY`; typically paired with Google ADK |

For cost-sensitive use cases, consider Bedrock Nova models (e.g., `amazon.nova-micro-v1:0`, `amazon.nova-lite-v1:0`) — significantly cheaper than Claude for simpler extractive tasks. See [`agents-optimize/references/cost.md`](../../agents-optimize/references/cost.md) for model selection guidance.

For a chatbot that remembers conversations, add `--memory longAndShortTerm` during scaffolding. Memory can also be added later — see [`agents-build/references/memory.md`](../../agents-build/references/memory.md).
