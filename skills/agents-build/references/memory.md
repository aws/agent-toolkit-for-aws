# memory

Add, configure, and debug AgentCore Memory — the managed service that lets your agent remember things across sessions.

## When to use

- You want your agent to remember user preferences, facts, or conversation history across separate sessions
- You added memory via `agentcore create` or `agentcore add memory` and need to wire it into your agent code
- Memory recall isn't working as expected
- You want to share memory across multiple agents

Do NOT use this skill for within-session conversation history. That's handled automatically by the runtime — no configuration needed.

## Input

`$ARGUMENTS` is optional. If provided, use it as the memory resource name:

```
/memory                    # uses name from agentcore.json, or prompts
/memory UserContext        # targets a specific memory resource by name
```

## Process

### Step 1: Read the project

Read `agentcore/agentcore.json`. Look for:

- The `memories` array — is memory already configured?
- The `runtimes` array — what agents are in the project and what framework do they use?
- The project `name` — needed for env var construction

**If `agentcore/agentcore.json` does not exist**, check if there's any AgentCore project structure nearby (look for `agentcore/` directory). If none found, proceed with the most helpful answer possible based on what the developer asked — don't block on missing context. If the question is about strategy selection or code patterns, answer it directly. Only ask "which situation are you in?" if the answer genuinely depends on it (e.g., they need CLI commands that differ by setup type).

### Step 2: Determine the situation

**Case A — No memory configured yet**
The `memories` array is empty or missing. Proceed to Step 3 (strategy selection).

**Case B — Memory configured, needs wiring**
Memory exists in `agentcore.json` but the agent code doesn't use it yet. Skip to Step 5 (generate wiring code).

**Case C — Memory configured and wired, debugging recall**
Ask: "What's happening? What did you expect the agent to remember, and what did it actually do?"
Then diagnose using the patterns in the Debugging section below.

**Case D — Developer asking about memory without a project**
Answer the question directly. For strategy questions, explain the options. For code questions, show the pattern with a note that they'll need to substitute their actual memory ID.

### Step 3: Choose a strategy

Present the options and ask the developer which fits their use case. Don't skip this — the wrong strategy wastes money and produces worse results.

```
Which memory strategy fits your use case?

SEMANTIC
  Best for: remembering facts about users across sessions
  How it works: extracts facts and stores them as embeddings; retrieves
  relevant context via similarity search at session start
  Cost: higher (embedding model + vector search per session)
  Example: "Remember that Alex prefers bullet points and works in fintech"

USER_PREFERENCE
  Best for: remembering explicit settings and preferences
  How it works: extracts structured preference data; optimized for
  key-value retrieval
  Cost: lower (structured extraction, no vector search)
  Example: "Remember my preferred response format and language"

SUMMARIZATION
  Best for: remembering what you talked about last time
  How it works: compresses conversation history into summaries; injects
  the summary at the start of each new session
  Cost: medium (summarization model runs at session end)
  Example: "Pick up where we left off last time"

EPISODIC
  Best for: remembering sequences of events or interactions over time
  How it works: stores episodic records of interactions with temporal
  context
  Cost: medium

Common combinations:
  SEMANTIC + USER_PREFERENCE  →  facts + preferences (most common)
  SEMANTIC + SUMMARIZATION    →  full episodic memory (highest capability, highest cost)
  USER_PREFERENCE alone       →  lightweight preference store

Which strategy (or combination) do you want?
```

### Step 4: Add memory to agentcore.json

Run the CLI command to add memory to the project config:

```bash
agentcore add memory --name <MemoryName> --strategies <STRATEGY1,STRATEGY2> --expiry 30
```

This updates `agentcore/agentcore.json`. The memory resource is provisioned when you next run `agentcore deploy` — it takes 2–5 minutes to become active.

The resulting config entry looks like:

```json
{
  "memories": [{
    "type": "AgentCoreMemory",
    "name": "MyMemory",
    "eventExpiryDuration": 30,
    "strategies": [
      {"type": "SEMANTIC"},
      {"type": "USER_PREFERENCE"}
    ]
  }]
}
```

**Memory name rules:** alphanumeric + underscores, max 48 chars, starts with a letter.

**Env var injected at deploy time:** `MEMORY_<UPPERCASENAME>_ID`
Example: memory named `UserContext` → env var `MEMORY_USERCONTEXT_ID`

### Step 5: Generate wiring code

Read `app/<AgentName>/main.py` (or the equivalent entrypoint) to detect the framework. Each framework has its own integration pattern — pick the one that matches:

| Framework | Recommended integration | Source |
|---|---|---|
| Strands | `AgentCoreMemorySessionManager` (CLI template) | `bedrock_agentcore.memory.integrations.strands.*` |
| LangGraph | `AgentCoreMemorySaver` + `AgentCoreMemoryStore` | `langgraph-checkpoint-aws` (official AWS-maintained) |
| OpenAI Agents SDK | `MemoryClient` via `@function_tool` | `bedrock_agentcore.memory.MemoryClient` |
| Google ADK / Claude Agent SDK | BYO — use `MemoryClient` directly | Validate end-to-end before shipping |

> [!WARNING]
> Always check for the MEMORY_ID env var before initializing memory. Memory is NOT
> available during `agentcore dev` — the env var is only set after deploy. Code that
> assumes memory is always available will fail silently in local development.

#### Strands — Session Manager pattern (recommended for new projects)

```python
import os
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from strands import Agent
from model.load import load_model  # scaffolded by `agentcore create`

app = BedrockAgentCoreApp()

# AgentCore injects this env var after deploy.
# Format: MEMORY_<UPPERCASENAME>_ID
MEMORY_ID = os.getenv("MEMORY_<UPPERCASENAME>_ID")
REGION = os.getenv("AWS_REGION", "us-east-1")

@app.entrypoint
def invoke(payload, context):
    actor_id = payload.get("userId", "default-user")
    session_id = getattr(context, "session_id", "default-session")

    session_manager = None
    if MEMORY_ID:
        # RetrievalConfig parameters:
        #   top_k: max number of memory records to retrieve per namespace (SDK default: 10)
        #   relevance_score: similarity threshold, 0 = return anything, 1 = exact match (SDK default: 0.2)
        # The CLI template deviates from SDK defaults to favor precision over recall:
        #   top_k=3 limits context window usage; relevance_score=0.5 filters low-quality matches.
        # Tune these if retrieval misses relevant facts (lower) or surfaces irrelevant ones (raise).
        memory_config = AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config={
                f"/users/{actor_id}/facts": RetrievalConfig(top_k=3, relevance_score=0.5),
                f"/users/{actor_id}/preferences": RetrievalConfig(top_k=3, relevance_score=0.5),
            }
        )
        session_manager = AgentCoreMemorySessionManager(memory_config, REGION)

    agent = Agent(
        model=load_model(),
        session_manager=session_manager,  # None is safe — agent runs without memory
        system_prompt="You are a helpful assistant.",
    )

    result = agent(payload.get("prompt", ""))
    return {"response": str(result)}

if __name__ == "__main__":
    app.run()
```

#### Strands — Hook pattern (for adding memory to an existing agent)

```python
import os
from bedrock_agentcore.memory import MemoryClient
from strands.hooks import AgentInitializedEvent, HookProvider, MessageAddedEvent

MEMORY_ID = os.getenv("MEMORY_<UPPERCASENAME>_ID")
memory_client = MemoryClient(region_name=os.getenv("AWS_REGION", "us-east-1")) if MEMORY_ID else None

class MemoryHook(HookProvider):
    def on_agent_initialized(self, event):
        """Load recent conversation turns into the agent's context."""
        if not MEMORY_ID:
            return
        session_id = event.agent.state.get("session_id", "default")
        turns = memory_client.get_last_k_turns(
            memory_id=MEMORY_ID,
            actor_id="user",
            session_id=session_id,
            k=3
        )
        if turns:
            context = "\n".join([
                f"{m['role']}: {m['content']['text']}"
                for t in turns for m in t
            ])
            event.agent.system_prompt += f"\n\nPrevious conversation:\n{context}"

    def on_message_added(self, event):
        """Save each message to memory after it's processed."""
        if not MEMORY_ID:
            return
        session_id = event.agent.state.get("session_id", "default")
        msg = event.agent.messages[-1]
        memory_client.create_event(
            memory_id=MEMORY_ID,
            actor_id="user",
            session_id=session_id,
            messages=[(str(msg["content"]), msg["role"])]
        )

    def register_hooks(self, registry):
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        registry.add_callback(MessageAddedEvent, self.on_message_added)

# Add to your existing agent:
agent = Agent(
    # ... your existing config ...
    hooks=[MemoryHook()] if MEMORY_ID else [],
    state={"session_id": "default"},
)
```

#### LangGraph — `langgraph-checkpoint-aws` (recommended)

LangGraph has an **official AWS-maintained integration** via the [`langgraph-checkpoint-aws`](https://pypi.org/project/langgraph-checkpoint-aws/) package. It provides two integrations that map cleanly to LangGraph's memory model:

- **`AgentCoreMemorySaver`** — persists LangGraph's checkpoint objects (conversation state, execution graph, metadata) to AgentCore Memory. This is LangGraph's short-term / session memory.
- **`AgentCoreMemoryStore`** — saves conversational messages for AgentCore's long-term extraction (facts, preferences, summaries) and lets the agent search those memories in future sessions.

Use these instead of wiring `MemoryClient` calls into your graph manually — they handle the protocol conversion, actor/session mapping, and retry logic for you.

**Install:**

```bash
pip install langgraph-checkpoint-aws
```

**Required IAM permissions** on the agent's execution role:

- `bedrock-agentcore:CreateEvent`
- `bedrock-agentcore:ListEvents`
- `bedrock-agentcore:RetrieveMemories`

**Basic pattern — short-term checkpointing only:**

```python
import os
from langgraph.prebuilt import create_react_agent
from langgraph_checkpoint_aws import AgentCoreMemorySaver
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model  # scaffolded by `agentcore create`

app = BedrockAgentCoreApp()

MEMORY_ID = os.getenv("MEMORY_<UPPERCASENAME>_ID")
REGION = os.getenv("AWS_REGION", "us-east-1")

# Only wire checkpointing if memory is available (deployed)
checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name=REGION) if MEMORY_ID else None

@app.entrypoint
async def invoke(payload, context):
    actor_id = payload.get("userId", "default-user")
    session_id = getattr(context, "session_id", "default-session")

    graph = create_react_agent(
        model=load_model(),
        tools=tools,
        checkpointer=checkpointer,  # None is safe — graph runs without persistence
    )

    # LangGraph's RunnableConfig maps thread_id → AgentCore session_id,
    # actor_id → AgentCore actor_id under the hood
    config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": actor_id,
        }
    }

    result = await graph.ainvoke(
        {"messages": [("human", payload["prompt"])]},
        config=config,
    )
    return {"response": result["messages"][-1].content}
```

**Full pattern — short-term + long-term retrieval:**

For long-term memory (facts, preferences, summaries extracted by AgentCore), add `AgentCoreMemoryStore` with a pre-model hook that saves messages for extraction and (optionally) retrieves relevant memories:

```python
import os
import uuid
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
from langgraph_checkpoint_aws import AgentCoreMemorySaver, AgentCoreMemoryStore

MEMORY_ID = os.getenv("MEMORY_<UPPERCASENAME>_ID")
REGION = os.getenv("AWS_REGION", "us-east-1")

checkpointer = AgentCoreMemorySaver(MEMORY_ID, region_name=REGION) if MEMORY_ID else None
store = AgentCoreMemoryStore(MEMORY_ID, region_name=REGION) if MEMORY_ID else None

def pre_model_hook(state, config: RunnableConfig, *, store: BaseStore):
    """Save the latest human message for async extraction; optionally retrieve preferences."""
    actor_id = config["configurable"]["actor_id"]
    thread_id = config["configurable"]["thread_id"]
    namespace = (actor_id, thread_id)

    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            store.put(namespace, str(uuid.uuid4()), {"message": msg})
            break

    # Optional: retrieve user preferences to inject into context
    # preferences_ns = ("preferences", actor_id)
    # preferences = store.search(preferences_ns, query=msg.content, limit=5)

    return {"llm_input_messages": messages}

graph = create_react_agent(
    model=load_model(),
    tools=tools,
    checkpointer=checkpointer,
    store=store,
    pre_model_hook=pre_model_hook if store else None,
)
```

**Invoke with config:**

```python
config = {"configurable": {"thread_id": "session-1", "actor_id": "user-alice"}}
response = graph.invoke({"messages": [("human", "I prefer short answers.")]}, config=config)

# New session for the same actor — long-term memories are retrieved
new_config = {"configurable": {"thread_id": "session-2", "actor_id": "user-alice"}}
response = graph.invoke({"messages": [("human", "Summarize my latest report.")]}, config=new_config)
```

The agent remembers "I prefer short answers" across sessions because AgentCore Memory extracts it as a user preference. See the [AgentCore docs on LangGraph integration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html) for the full reference.

**If you need low-level control** (custom retrieval queries, direct event management), fall back to `MemoryClient`:

```python
from bedrock_agentcore.memory import MemoryClient

client = MemoryClient(region_name=REGION)
# client.create_event(...), client.retrieve_memories(...), client.get_last_k_turns(...)
```

Use `MemoryClient` directly only when the checkpoint/store abstractions don't fit your use case.

#### OpenAI Agents SDK — memory as function tools

The OpenAI Agents SDK pattern is to expose memory as `@function_tool` decorated functions. The agent decides when to read and write:

```python
import os
from agents import Agent, Runner, function_tool
from bedrock_agentcore.memory import MemoryClient

MEMORY_ID = os.getenv("MEMORY_<UPPERCASENAME>_ID")
REGION = os.getenv("AWS_REGION", "us-east-1")
_client = MemoryClient(region_name=REGION) if MEMORY_ID else None

def _build_memory_tools(actor_id: str, session_id: str):
    """Factory — binds actor/session into tool closures."""

    @function_tool
    def recall_context(query: str, top_k: int = 3) -> str:
        """Search long-term memory for facts or preferences about the user."""
        if not _client or not MEMORY_ID:
            return "Memory unavailable."
        try:
            memories = _client.retrieve_memories(
                memory_id=MEMORY_ID,
                namespace=f"/users/{actor_id}/facts",
                query=query,
                top_k=top_k,
            )
            return "\n".join(m.get("content", {}).get("text", "") for m in memories) or "No relevant memories."
        except Exception as e:
            return f"Memory error: {e}"

    @function_tool
    def save_fact(content: str) -> str:
        """Save a fact to long-term memory."""
        if not _client or not MEMORY_ID:
            return "Memory unavailable."
        try:
            _client.create_event(
                memory_id=MEMORY_ID,
                actor_id=actor_id,
                session_id=session_id,
                messages=[(content, "ASSISTANT")],
            )
            return "Saved."
        except Exception as e:
            return f"Error: {e}"

    return [recall_context, save_fact]

@app.entrypoint
async def invoke(payload, context):
    actor_id = payload.get("userId", "default-user")
    session_id = getattr(context, "session_id", "default-session")

    agent = Agent(
        name="Assistant",
        instructions="Use recall_context at the start of each session to check what you know about the user. Use save_fact when the user tells you something worth remembering.",
        tools=_build_memory_tools(actor_id, session_id),
    )
    result = await Runner.run(agent, payload["prompt"])
    return {"response": result.final_output}
```

#### Google ADK and Claude Agent SDK — bring your own memory integration

AgentCore Memory doesn't have a framework-specific integration for ADK or the Claude Agent SDK yet, and the samples repo doesn't contain a combined pattern we can point to. Use the general `MemoryClient` API and wire it into the framework's existing extension points:

- **Google ADK:** Expose memory operations as ADK tools (functions passed to `Agent(tools=[...])`). The ADK agent decides when to call them.
- **Claude Agent SDK:** Wrap `query()` with a pre-call memory load and a post-call memory save. The SDK's `ClaudeAgentOptions.system_prompt` is the injection point for retrieved context.

For both frameworks, follow the `MemoryClient` API shown in the OpenAI Agents pattern above — the client calls (`retrieve_memories`, `create_event`, `get_last_k_turns`) are identical. The framework-specific part is just where you call them.

Before shipping a memory integration for ADK or Claude SDK, validate the end-to-end flow against a deployed agent:

1. Deploy with memory enabled
2. Invoke the agent with facts to remember
3. Start a new session
4. Invoke again and verify the agent recalls those facts
5. Check `agentcore logs --runtime <AgentName> --query "memory" --since 1h --level error` for any memory errors

If you build a working pattern, consider contributing it to [`awslabs/agentcore-samples`](https://github.com/awslabs/agentcore-samples) so the next developer doesn't have to figure it out.

### Step 6: Explain the local dev gap and next steps

Always include this note:

```
⚠️  Memory is not available during local development (agentcore dev).

The MEMORY_<NAME>_ID env var is only injected after deploy. The code above
handles this gracefully — it runs without memory when the env var isn't set.

To test memory:
  agentcore deploy -y
  agentcore invoke "My name is Alex and I prefer concise answers"
  agentcore invoke "What do you know about me?"

If using long-term memory (SEMANTIC or USER_PREFERENCE), wait 5–30 seconds
between the first and second invoke — extraction runs asynchronously after
each session ends.

Session ID note: use UUIDs (v4) for session IDs — they satisfy the platform's
minimum length requirement (33 characters) and are what `agentcore invoke`
generates by default. Short or sequential session IDs (e.g., "session-1",
"test") can cause long-term memory extraction to fail silently.
```

**If the developer is using the SDK directly (no CLI project)**, they need to create the memory resource first:

```python
from bedrock_agentcore.memory import MemoryClient

client = MemoryClient(region_name="us-east-1")

# Create memory and wait for it to become ACTIVE (takes 2-5 minutes)
memory = client.create_memory_and_wait(
    name="UserMemory",
    strategies=[
        {"userPreferenceMemoryStrategy": {
            "name": "prefs",
            "namespaces": ["/user/preferences/"]
        }},
        {"semanticMemoryStrategy": {
            "name": "facts",
            "namespaces": ["/user/facts/"]
        }}
    ],
    event_expiry_days=30
)

MEMORY_ID = memory["id"]
print(f"Memory created: {MEMORY_ID}")
# Set this as an env var or hardcode for testing:
# export MEMORY_ID=<value>
```

Then use the same wiring code from Step 5, reading `MEMORY_ID` from the environment.

## Debugging memory recall

If memory was working and stopped, or never worked:

**Agent keeps forgetting things even with memory set up:**
Most common cause: the memory resource is configured but the code isn't reading from it at session start. Check that your entrypoint calls `get_last_k_turns` (or uses the session manager) before creating the agent, not after. Also verify the `MEMORY_<NAME>_ID` env var is set — it's only injected after deploy, not during `agentcore dev`.

**Memory not persisting across sessions:**

1. Check that LTM strategies (SEMANTIC, USER_PREFERENCE) are configured — not just SUMMARIZATION
2. Wait 5–30 seconds after a session ends before starting a new one — extraction is async
3. Verify the memory resource is ACTIVE: `agentcore status --type memory`
4. Use UUIDs (v4) for session IDs — the platform requires a minimum of 33 characters. Short IDs like "session-1" or "test" cause LTM to fail silently. `agentcore invoke` generates compliant IDs by default.

**Memory not loading at session start:**

1. Verify `MEMORY_<NAME>_ID` env var is set: `agentcore status --type memory --json`
2. Check the actor_id is consistent across sessions — memory is scoped per actor
3. Confirm the namespace paths in retrieval_config match the namespaces used when writing — the retrieval namespace must exactly match the namespace the strategy extracts into
4. CLI defaults use paths without trailing slashes (e.g., `/users/{actorId}/facts`). If you customized namespace templates when creating the memory resource, use whatever pattern you chose — consistency between writer and reader is what matters.

**Memory provisioning slow:**
Memory takes 2–5 minutes to become ACTIVE after `agentcore deploy`. Check status:

```bash
agentcore status --type memory
```

## S3 delivery / export buckets must be in the same account

If you're configuring S3 delivery for memory exports, session transcripts, or Browser recording output, the destination bucket must be in the **same AWS account** as the AgentCore resource. Cross-account S3 buckets are not supported as delivery destinations, even with correct bucket policies granting the service principal access.

Symptom of attempting a cross-account bucket: `CreateMemory` (or the relevant resource creation call) fails with `ValidationException: Role does not have access to required S3 buckets` — even when IAM and bucket policies are correctly configured for cross-account access.

**Workaround:** create a same-account bucket for the AgentCore resource to write to. If you need the data in a different account, replicate from the same-account bucket via S3 replication or a scheduled copy job.

## Sharing memory across agents

Memory is a top-level resource — not nested under a single agent. To share:

1. Create one memory resource: `agentcore add memory --name SharedMemory --strategies SEMANTIC`
2. In each agent's code, read the same env var: `MEMORY_SHAREDMEMORY_ID`
3. Use a consistent `actor_id` scheme across agents (e.g., the end user's ID)

## Cross-region inference (data residency)

Memory consolidation (extraction + summarization for long-term strategies) uses cross-region inference by default. Your memory **data stays in your primary region**, but the **inference call** that extracts facts or summarizes a session may execute in another AWS region within the same geography (e.g., `us-east-1` → `us-east-2` or `us-west-2`; EU stays in EU; etc.).

This matters when:

- You have a data-residency requirement that goes beyond storage — some regulations constrain where inference may run, not just where results land
- You're building for a customer whose contract pins processing to a single region
- Your audit trail needs to show which region handled each prompt

**There's no extra cost for cross-region inference, and CloudWatch/CloudTrail logs don't include the inference region.** Across the `Memory`, `Policy`, and `Evaluations` services, this is the default behavior.

**To opt out for Memory:** use a **built-in-with-overrides** strategy (see [`memory-custom-strategy`](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html)) and pin the model to a specific region. The overrides strategy lets you specify the exact model ID used for extraction and consolidation, which gives you region control.

The supported geographies and inference-region mappings change as AgentCore expands — check [the cross-region inference docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html) for the current list rather than baking it in here.

## Beyond the CLI: memory features that require the API

The CLI's `agentcore add memory` and `agentcore.json` cover strategy selection, expiry, and basic configuration. Some memory capabilities are API/SDK-only — the CLI doesn't expose them. When the developer needs one of these, the graduation path is: create the memory via CLI as usual, deploy, then apply the additional config via boto3 or AWS CLI.

**Resource-based policies** (cross-account access, principal-level restrictions):

```python
import boto3, json

client = boto3.client("bedrock-agentcore-control")
memory_id = "<MEMORY_ID>"  # from: agentcore status --type memory --json

client.put_memory_resource_policy(
    memoryId=memory_id,
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
            "Action": [
                "bedrock-agentcore:CreateEvent",
                "bedrock-agentcore:RetrieveMemories",
                "bedrock-agentcore:ListEvents"
            ],
            "Resource": "*"
        }]
    })
)
```

**Custom extraction models** (pin the model used for LTM extraction — e.g., for data residency):

Use the "built-in with overrides" strategy type via `UpdateMemory`. See the [custom memory strategy docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-custom-strategy.html) for the full configuration shape.

**Self-managed strategies** (bring your own extraction logic):

Also API-only. See the AgentCore memory docs for the `selfManagedMemoryStrategy` configuration.

**When you hit a memory capability not covered here**, use the `awsknowledge` MCP server if available — search for the specific API operation (e.g., "AgentCore PutMemoryResourcePolicy") to get the current parameter shapes. The API surface evolves between releases.

**General rule:** if `agentcore.json` has a field for it, use the CLI. If it doesn't, create the resource via CLI, deploy, then apply the additional config via boto3. Don't fight the CLI to do something it wasn't designed for.

## Output

- Updated `agentcore/agentcore.json` with memory resource (via CLI command)
- Wiring code for `app/<AgentName>/main.py` appropriate for the detected framework
- Explanation of the local dev gap and how to test after deploy

## Quality criteria

- Generated code handles `MEMORY_ID` being None (local dev) without crashing
- Env var name matches the memory resource name in `agentcore.json` (uppercase, underscores)
- Framework-specific pattern is used — never generate Strands hooks for a LangGraph project
- LTM extraction delay is communicated
- Session ID guidance recommends UUIDs (v4) when LTM strategies are used (minimum 33 characters)
