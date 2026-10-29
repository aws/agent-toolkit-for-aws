# multi-agent

Build AgentCore systems where agents delegate work to other agents.

## When to use

- You want an orchestrator agent to delegate complex tasks to a specialist
- You're building a system where agents have different roles and capabilities
- You want agents to discover and communicate with each other via the A2A standard
- You want multiple agents to share the same memory

## Input

`$ARGUMENTS` is optional:

```
/multi-agent              # interactive — asks which pattern you need
/multi-agent a2a          # A2A protocol setup
/multi-agent direct       # direct invocation pattern
/multi-agent memory       # shared memory across agents
```

## Choosing a pattern

### Step 1: Deploy the specialist agent

The specialist is a standard AgentCore agent. Deploy it normally:

```bash
agentcore create --name SpecialistProject --template agent-python-strands
cd SpecialistProject
# ... add your specialist logic to app/agent/main.py ...
agentcore deploy
```

Get the specialist's runtime ARN after deploy:

```bash
agentcore status --json | jq -r '.resources[] | select(.resourceType == "runtime" and .name == "agent") | .arn'
```

### Step 2: Add the specialist as a tool in the orchestrator

The orchestrator calls the specialist via `bedrock-agentcore:InvokeAgentRuntime`. Add this tool to your orchestrator's agent code:

```python
import os
import json
import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

# Set this env var in your orchestrator's deployment config
SPECIALIST_ARN = os.getenv("SPECIALIST_AGENT_ARN")
REGION = os.getenv("SPECIALIST_AGENT_REGION")

def call_specialist(prompt: str, session_id: str = None) -> str:
    """
    Call the specialist agent and return its response.
    The specialist runs in its own isolated session.
    """
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    kwargs = {
        "agentRuntimeArn": SPECIALIST_ARN,
        "qualifier": "DEFAULT",  # or a specific version number to pin
        "payload": json.dumps({"prompt": prompt}).encode(),
    }
    if session_id:
        kwargs["runtimeSessionId"] = session_id

    response = client.invoke_agent_runtime(**kwargs)
    # response["response"] is a StreamingBody — read, then parse JSON
    body = response["response"].read()
    result = json.loads(body.decode() if isinstance(body, bytes) else body)
    return result.get("response", result.get("result", str(result)))
```

Passing `"DEFAULT"` as the qualifier calls the live version. To pin to a specific version (staging pin, canary, or rollback), pass a numeric version string instead — see [`agents-deploy/references/versioning.md`](../../agents-deploy/references/versioning.md) for the full workflow.

**For Strands**, register it as a `@tool`:

```python
from strands import Agent, tool

@tool
def delegate_to_specialist(task: str) -> str:
    """
    Delegate a complex analysis task to the specialist agent.
    Use this when the task requires deep domain expertise.

    Args:
        task: The specific task or question for the specialist.

    Returns:
        The specialist's detailed response.
    """
    return call_specialist(task)

@app.entrypoint
def invoke(payload, context):
    agent = Agent(
        model=load_model(),  # scaffolded by `agentcore create`
        system_prompt="""You are an orchestrator. For complex analysis tasks,
        delegate to the specialist using the delegate_to_specialist tool.
        Synthesize the specialist's response for the user.""",
        tools=[delegate_to_specialist],
    )
    result = agent(payload.get("prompt", ""))
    return {"response": str(result)}

if __name__ == "__main__":
    app.run()
```

**For LangGraph**, add it as a tool node:

```python
from langchain_core.tools import tool as lc_tool

@lc_tool
def delegate_to_specialist(task: str) -> str:
    """Delegate complex tasks to the specialist agent."""
    return call_specialist(task)

# Add to your LangGraph tool node
tools = [delegate_to_specialist]
tool_node = ToolNode(tools)
llm_with_tools = llm.bind_tools(tools)
```

**For OpenAI Agents SDK**, register as a `@function_tool`:

```python
from agents import Agent, Runner, function_tool

@function_tool
def delegate_to_specialist(task: str) -> str:
    """Delegate a complex analysis task to the specialist agent.
    Use when the task requires deep domain expertise."""
    return call_specialist(task)

@app.entrypoint
async def invoke(payload, context):
    agent = Agent(
        name="Orchestrator",
        instructions="For complex analysis, delegate to the specialist using delegate_to_specialist. Synthesize the response for the user.",
        tools=[delegate_to_specialist],
    )
    result = await Runner.run(agent, payload["prompt"])
    return {"response": result.final_output}
```

**For Google ADK**, pass as a plain function in the agent's `tools=[]` list. Note: the official samples use A2A for ADK multi-agent patterns (see `awslabs/agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/host_adk_agent/`). The direct-invocation pattern below is extrapolated from the ADK base template — validate against your ADK version before relying on it in production:

```python
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

def delegate_to_specialist(task: str) -> str:
    """Delegate complex analysis to the specialist agent."""
    return call_specialist(task)

agent = Agent(
    model="gemini-2.5-flash",
    name="orchestrator",
    description="Orchestrator that delegates complex tasks to specialists.",
    instruction="For complex analysis, call delegate_to_specialist and synthesize the response.",
    tools=[delegate_to_specialist],
)

@app.entrypoint
async def invoke(payload, context):
    user_id = payload.get("user_id", "default_user")
    session_id = getattr(context, "session_id", "default_session")
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="orchestrator", user_id=user_id, session_id=session_id
    )
    runner = Runner(agent=agent, app_name="orchestrator", session_service=session_service)
    content = types.Content(role="user", parts=[types.Part(text=payload["prompt"])])
    async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=content):
        if event.is_final_response():
            return {"response": event.content.parts[0].text}
```

For a validated ADK multi-agent pattern, use A2A instead of direct invocation — see the A2A section below and the sample linked above.

**For Claude Agent SDK:** See [`awslabs/agentcore-samples/03-integrations/agentic-frameworks/claude-agent/claude-sub-agents/`](https://github.com/awslabs/agentcore-samples/tree/main/03-integrations/agentic-frameworks/claude-agent/claude-sub-agents) for the official sub-agent pattern. This plugin doesn't ship a Claude SDK delegation pattern because the sample is more current than anything we could extrapolate.

### Step 3: Grant IAM permission

The orchestrator's execution role needs permission to invoke the specialist:

```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore:InvokeAgentRuntime",
  "Resource": "arn:aws:bedrock-agentcore:<REGION>:<YOUR_ACCOUNT_ID>:runtime/SpecialistAgent-*"
}
```

Add this to `agentcore/agentcore.json` under the orchestrator agent's IAM config, or add it manually to the auto-created execution role after deploy.

### Step 4: Pass the specialist ARN to the orchestrator

Run `agentcore status --target <specialist-target> --json` in the specialist project and select the deployed Runtime ARN and the top-level `region`. In the orchestrator project, add `{"name":"SPECIALIST_AGENT_ARN","value":"<specialist-runtime-arn>"}` and `{"name":"SPECIALIST_AGENT_REGION","value":"<specialist-region>"}` to that Runtime entry's `envVars` array in `agentcore/agentcore.json`. For local development, set the same variables in `agentcore/.env.local`. These are separate files: `.env.local` does not configure the deployed Runtime. Run `agentcore build`, then `agentcore deploy --target <orchestrator-target>` in the orchestrator project. Do not grant its execution role `bedrock-agentcore:InvokeAgentRuntime` on `*`; scope the permission to the specialist Runtime ARN.

## Pattern 2: A2A protocol

The specialist exposes the A2A standard — discoverable via an agent card, callable via JSON-RPC. AgentCore's A2A runtime handles the HTTP server, port binding (9000), and agent card serving for you.

### Step 1: Build the A2A specialist

Use the `serve_a2a` helper from `bedrock-agentcore` — this matches what the CLI scaffolds via `agentcore create --template a2a-python-strands`.

```python
# app/agent/main.py
from strands import Agent, tool
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from bedrock_agentcore.runtime import serve_a2a
from model.load import load_model


@tool
def analyze_data(dataset_name: str) -> str:
    """Run detailed analysis on the named dataset."""
    # Your specialist logic here
    return f"Analysis results for {dataset_name}..."


def create_agent(context_id: str) -> Agent:
    return Agent(
        model=load_model(),
        system_prompt="You are an analysis specialist. Use tools when appropriate.",
        tools=[analyze_data],
    )

if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(agent_factory=create_agent))
```

```
# requirements.txt
strands-agents[a2a]
bedrock-agentcore
```

`serve_a2a` handles port 9000 binding, agent card generation at `/.well-known/agent-card.json`, and JSON-RPC routing automatically. No FastAPI or uvicorn needed.

### Step 2: Deploy the A2A specialist

```bash
agentcore create --name SpecialistA2A --template a2a-python-strands
cd SpecialistA2A
# The CLI scaffolds app/agent/main.py with the serve_a2a pattern shown above — customize it with your specialist logic
# Configure the specialist Runtime in agentcore/agentcore.json for CUSTOM_JWT
# with the same OIDC discovery URL and allowed client ID used by the
# orchestrator's OAuth M2M credential below. For example, set:
# "authorizerType": "CUSTOM_JWT",
# "authorizerConfiguration": {"customJwtAuthorizer": {
#   "discoveryUrl": "https://<YOUR_IDP>/.well-known/openid-configuration",
#   "allowedClients": ["<CLIENT_ID>"]}}
# Also set "requestHeaderAllowlist": ["Authorization"] on this Runtime
# so the A2A server receives the bearer header.
agentcore deploy
```

After deploy, get the Runtime ARN and region:

```bash
agentcore status --json | jq '{region, runtime: [.resources[] | select(.resourceType == "runtime") | .arn]}'
```

`status` does not return a URL. URL-encode the Runtime ARN (including its colons and slashes) and use `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<encoded-runtime-arn>/invocations/` as `SPECIALIST_A2A_URL`. The same URL must be used for agent-card discovery and JSON-RPC calls.

### Step 3: Test locally

```bash
# Start the A2A server locally (from your specialist project directory).
# Run the curl commands below in another terminal while this server is running.
agentcore dev

# Test the agent card (discovery)
curl http://localhost:9000/.well-known/agent-card.json | jq .

# Send a message
curl -X POST http://localhost:9000 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "req-001",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "What is 42 * 17?"}],
        "messageId": "msg-001"
      }
    }
  }' | jq .
```

### Step 4: Call the A2A specialist from the orchestrator

The specialist URL is a non-secret identifier, so pass it via the orchestrator Runtime's `envVars` array in its project. The bearer token **is** a secret — do **not** stash it in `os.getenv(...)` on the deployed runtime (runtime env vars are not vault-backed). Return to the **orchestrator project root** before registering the OAuth M2M provider; the specialist project cannot provision credentials for a different project's Runtime. Use `@requires_access_token` to fetch a fresh token at call time:

```bash
# From the orchestrator project root: register the OAuth provider that issues
# tokens for calls to the specialist.
# The v1 CLI accepts client secrets from file or stdin, never inline values.
agentcore add credentials oauth \
  --name SpecialistA2A \
  --discovery-url https://<YOUR_IDP>/.well-known/openid-configuration \
  --client-id <CLIENT_ID> \
  --client-secret file://<LOCAL_SECRET_FILE> \
  --scopes a2a.invoke
```

```python
import asyncio
import os
from uuid import uuid4
import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from bedrock_agentcore.identity.auth import requires_access_token

# Non-secret identifier — fine to pull from the environment.
SPECIALIST_URL = os.getenv("SPECIALIST_A2A_URL")

@requires_access_token(
    provider_name="SpecialistA2A",
    scopes=["a2a.invoke"],
    auth_flow="M2M",
)
async def call_a2a_specialist(message: str, *, access_token: str) -> str:
    session_id = str(uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }

    async with httpx.AsyncClient(timeout=300, headers=headers) as http_client:
        resolver = A2ACardResolver(httpx_client=http_client, base_url=SPECIALIST_URL)
        agent_card = await resolver.get_agent_card()

        config = ClientConfig(httpx_client=http_client, streaming=False)
        client = ClientFactory(config).create(agent_card)

        msg = Message(
            kind="message",
            role=Role.user,
            parts=[Part(TextPart(kind="text", text=message))],
            message_id=uuid4().hex,
        )

        async for event in client.send_message(msg):
            if hasattr(event, "parts"):
                return " ".join(p.text for p in event.parts if hasattr(p, "text"))
    return ""

# Use in your orchestrator's entrypoint:
@app.entrypoint
def invoke(payload, context):
    result = asyncio.run(call_a2a_specialist(payload.get("prompt", "")))
    return {"response": result}
```

Add `{"name":"SPECIALIST_A2A_URL","value":"<specialist-runtime-url>"}` to the orchestrator Runtime's `envVars`, then run `agentcore deploy --target <orchestrator-target>` from that project. This first deploy provisions the new credential before building the Runtime; `agentcore build` may fail before that happens. The decorator handles caching and refresh. For local dev, put the OAuth values in the orchestrator project's `agentcore/.env.local` so `agentcore dev` can resolve the decorator — the deployed Runtime reads them from the credential provider instead.

---

## Shared memory across agents

Memory is a top-level resource — not nested under a single agent. Multiple agents can share the same Memory ID when their IAM roles can access it.

### Setup

1. Create one shared Memory resource in an owner project and deploy it to the chosen target:

```bash
agentcore add memory --name SharedMemory --strategies SEMANTIC,USER_PREFERENCE
agentcore deploy --target <owner-target>
```

2. Get the Memory ID and ARN from `agentcore status --target <owner-target> --json`. The owner project's Runtime receives `MEMORY_SHAREDMEMORY_ID` automatically. For a Runtime in another project, add `{"name":"MEMORY_SHAREDMEMORY_ID","value":"<deployed-memory-id>"}` to that Runtime's `envVars` in `agentcore/agentcore.json`, grant its execution role the required Memory actions on the deployed Memory ARN, and deploy that project to its intended target. Both Runtimes must use the Memory's region.

3. In each agent's code, read the same env var:

```python
MEMORY_ID = os.getenv("MEMORY_SHAREDMEMORY_ID")
```

4. Use a consistent `actor_id` scheme — typically the end user's ID — so both agents read and write the same user's memory.

### Key consideration

When multiple agents share memory, they share the same namespace. Use namespaced paths to avoid collisions:

```python
# Orchestrator writes to /orchestrator/ namespace
memory_client.create_event(
    memory_id=MEMORY_ID,
    actor_id=user_id,
    session_id=session_id,
    messages=[("User asked about X", "user")],
)

# Specialist reads from all namespaces
turns = memory_client.get_last_k_turns(
    memory_id=MEMORY_ID,
    actor_id=user_id,
    session_id=session_id,
    k=5,
)
```

---

## Troubleshooting

**A2A server not responding:**

- Verify it's running on port 9000 (not 8080)
- Check the agent card endpoint returns: `curl http://localhost:9000/.well-known/agent-card.json`
- Verify your `main.py` uses `serve_a2a(StrandsA2AExecutor(agent_factory=create_agent))`

**Direct invocation permission denied:**

- Check the orchestrator's execution role has `bedrock-agentcore:InvokeAgentRuntime`
- Verify the resource ARN pattern matches the specialist's ARN
- IAM changes take ~30 seconds to propagate

**Specialist not found:**

- Verify `SPECIALIST_AGENT_ARN` env var is set correctly
- Check `agentcore status --json` shows `deployed` state

**A2A auth errors:**

- A2A supports SigV4 and OAuth 2.0 — make sure you're using the right auth method
- Obtain a bearer token from the configured identity provider; `agentcore status --json` does not issue JWTs

## Output

- Decision tree to choose the right pattern
- Complete code for the chosen pattern (orchestrator + specialist)
- IAM policy for agent-to-agent invocation
- Local testing commands

## Quality criteria

- Pattern recommendation matches the developer's latency and interoperability needs
- Generated code includes correct IAM permissions for agent-to-agent invocation
- A2A server runs on port 9000 (not 8080) using `serve_a2a(StrandsA2AExecutor(agent_factory=create_agent))`
- Agent card is at `/.well-known/agent-card.json` with correct capabilities
- Shared memory uses consistent `actor_id` scheme across agents
