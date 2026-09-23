# Strands Agents + AgentCore Runtime Design Reference

> Loaded by `design-ai.md` Step 0.6 when `agentic_profile.is_agentic == true` AND `ai_constraints.agentic.migration_approach == "strands"`.

**Prerequisites:** `references/shared/ai-migration-guardrails.md` must already be loaded (Step 0.6 loads it before this file). Do NOT duplicate regional caveats, pricing rules, or effort estimation rules here.

---

## What is Strands Agents

Strands Agents is an open-source SDK from AWS (open-sourced May 2025, 1.0 released July 2025) that takes a model-driven approach to building AI agents. It powers production features inside AWS services (Amazon Q Developer, AWS Glue, VPC Reachability Analyzer) and is the framework underlying the AgentCore Harness.

**Key differentiators vs other frameworks:**

- **Model-driven:** The LLM drives tool selection and planning autonomously — no hardcoded task flows
- **Multi-agent primitives:** Agents-as-Tools (hierarchical), Swarms (collaborative), Graphs (deterministic), A2A protocol (cross-organization)
- **AWS-native deployment:** First-class deployment on AgentCore Runtime with microVM isolation, 8-hour sessions, auto-scaling
- **Multi-model:** Supports Bedrock, OpenAI, Anthropic, and any OpenAI-compatible endpoint. Different models per agent in the same system.
- **Session management:** Built-in durable session persistence (S3, file-based, or custom DAO)
- **Async-native:** Full async support with streaming, concurrent agent evaluation, cancellation

**When to recommend Strands (this path):**

- Startup is on OpenAI Agents SDK or custom agent loops where retarget doesn't work well (tightly coupled to OpenAI API)
- Multi-agent system that would benefit from structured primitives (Graphs, Swarms, Agents-as-Tools)
- Team wants AWS-native agent infrastructure (AgentCore Runtime, Memory, Gateway, Identity, Observability)
- Team is willing to refactor orchestration code (accepts 2-6 week effort)
- Startup doesn't know Strands exists — this is the plugin surfacing an option they wouldn't discover from a base LLM

**When NOT to recommend Strands:**

- Working LangGraph/CrewAI/AutoGen system where retarget (model swap) is sufficient
- Team needs to ship in < 2 weeks (retarget or Harness is faster)
- Simple single-agent pattern (Harness is simpler and GA — config vs code)
- Team has no Python/TypeScript expertise (Strands SDK is Python and TypeScript)

---

## Framework-to-Strands Mapping

Map the detected `agentic_profile.framework` and `orchestration_pattern` to Strands primitives:

### OpenAI Agents SDK → Strands Agent

| OpenAI Agents SDK                        | Strands Equivalent                                           | Notes                                                    |
| ---------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------- |
| `Assistant` / `Agent` definition         | `Agent(name=..., model=..., system_prompt=..., tools=[...])` | Direct mapping. System prompt, tools, model all map 1:1. |
| `Runner.run()` / `Runner.run_streamed()` | `agent("prompt")` or `agent.stream_async("prompt")`          | Strands agent is callable directly.                      |
| `function` tool type                     | `@tool` decorated function                                   | Same concept, different decorator syntax.                |
| `handoff` to another agent               | `@tool` wrapping another agent (Agents-as-Tools pattern)     | Strands uses agents-as-tools for delegation.             |
| Thread / conversation state              | `SessionManager` with file or S3 backend                     | Strands persists full conversation automatically.        |
| `response.output`                        | `result = agent("prompt"); str(result)`                      | Agent returns result object.                             |

**Bridge option (Phase 0):** Before full Strands rewrite, startups on OpenAI Agents SDK can do a partial retarget — route model calls through Bedrock using OpenAI-compatible endpoint format while keeping the Agents SDK orchestration intact. This buys time on AWS infrastructure without rewriting. Then migrate to Strands when ready.

### LangGraph → Strands Graphs

| LangGraph                                     | Strands Equivalent                         | Notes                                                                                       |
| --------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `StateGraph(state_schema)`                    | `GraphBuilder()`                           | Strands graphs don't require explicit state schema — state flows via agent context.         |
| `graph.add_node("name", function)`            | `builder.add_node(agent, "name")`          | Strands nodes are agents, not arbitrary functions. Wrap functions as single-purpose agents. |
| `graph.add_edge("a", "b")`                    | `builder.add_edge("a", "b")`               | Direct mapping.                                                                             |
| `graph.add_conditional_edges("a", router_fn)` | `builder.add_edge("a", "b", condition=fn)` | Condition function receives state, returns bool.                                            |
| `graph.set_entry_point("start")`              | `builder.set_entry_point("start")`         | Direct mapping.                                                                             |
| `graph.compile()`                             | `builder.build()`                          | Returns executable graph.                                                                   |
| `MemorySaver` / sidebaring                    | `SessionManager` with S3 or file backend   | Different API but same concept — durable state across invocations.                          |

**Key difference:** LangGraph nodes are arbitrary functions; Strands graph nodes are Agents. For non-agent nodes (pure data transformation), wrap in a minimal Agent with a focused system prompt and no tools.

### CrewAI → Strands Swarms or Agents-as-Tools

| CrewAI                                                  | Strands Equivalent                                                           | Notes                                                             |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `Agent(role=..., goal=..., backstory=..., tools=[...])` | `Agent(name=..., system_prompt=..., tools=[...])`                            | Map `role`+`goal`+`backstory` into `system_prompt`.               |
| `Task(description=..., agent=...)`                      | Task is implicit — the orchestrator agent decides what to delegate.          | Strands is model-driven; tasks aren't pre-defined.                |
| `Crew(agents=[...], process=Process.sequential)`        | Sequential: chain agents with output piping, or use Graph with linear edges. |                                                                   |
| `Crew(agents=[...], process=Process.hierarchical)`      | `Swarm([agent1, agent2, agent3])` or Agents-as-Tools with manager agent.     | Swarm for collaborative; Agents-as-Tools for explicit delegation. |
| `crew.kickoff()`                                        | `swarm("task description")` or `manager_agent("task description")`           |                                                                   |

**Key difference:** CrewAI pre-defines tasks and assigns them to agents. Strands is model-driven — the orchestrator agent (or swarm) decides dynamically which specialist to consult. This is more flexible but requires good system prompts.

### AutoGen → Strands Agents-as-Tools or Swarms

| AutoGen                                        | Strands Equivalent                                                              | Notes                                                              |
| ---------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `AssistantAgent(name=..., system_message=...)` | `Agent(name=..., system_prompt=...)`                                            | Direct mapping.                                                    |
| `UserProxyAgent`                               | `handoff_to_user` tool from `strands_tools`                                     | Built-in human-in-the-loop.                                        |
| `GroupChat(agents=[...])`                      | `Swarm([agent1, agent2, ...])`                                                  | Swarm provides collaborative multi-agent without fixed turn order. |
| `GroupChatManager`                             | Implicit in Swarm coordination, or explicit manager Agent with Agents-as-Tools. |                                                                    |
| `initiate_chat()`                              | `swarm("initial message")` or `agent("initial message")`                        |                                                                    |

### Custom Agent Loops → Strands Agent

Custom `while` loops with LLM call + tool dispatch map most directly to a single Strands Agent:

```python
# Before (custom loop):
while not done:
    response = openai.chat.completions.create(model="gpt-4o", messages=messages, tools=tool_schemas)
    if response.tool_calls:
        result = execute_tool(response.tool_calls[0])
        messages.append(tool_result)
    else:
        done = True

# After (Strands):
from strands import Agent
from strands.models import BedrockModel

agent = Agent(
    model=BedrockModel(model_id="us.anthropic.claude-sonnet-5"),
    tools=[web_search, calculator, file_read],  # your existing tool functions with @tool decorator
    system_prompt="Your existing system prompt here"
)
result = agent("Your task here")
```

The Strands Agent handles the loop internally — model calls, tool dispatch, result parsing, context management. Your tool functions stay the same; just add the `@tool` decorator.

---

## AgentCore Runtime Deployment

Strands agents deploy on AgentCore Runtime for production:

**What AgentCore Runtime provides:**

- Serverless microVM isolation per session (no shared state between users)
- Auto-scaling from zero to thousands of sessions
- Up to 8-hour session duration for long-running agent tasks
- Built-in observability via OpenTelemetry (traces to CloudWatch, Datadog, etc.)
- VPC support and PrivateLink for network isolation

**Deployment model:**

| `task_duration` (from Clarify Q25) | Deployment recommendation                                                              |
| ---------------------------------- | -------------------------------------------------------------------------------------- |
| `quick` (< 30s)                    | AgentCore Runtime standard. Consider Lambda for simple single-turn if no state needed. |
| `medium` (30s – 5min)              | AgentCore Runtime standard. Sessions handle this natively.                             |
| `long` (5min – 1hr)                | AgentCore Runtime required. Lambda will timeout.                                       |
| `very_long` (1hr+)                 | AgentCore Runtime with session chaining. Break into sub-tasks if > 8 hours.            |

**Memory integration:**

| `memory_requirement` (from Clarify Q24) | Strands + AgentCore config                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------------- |
| `none`                                  | No SessionManager needed. Stateless invocations.                                            |
| `session`                               | `SessionManager` with in-session state. AgentCore Runtime sessions are stateful by default. |
| `cross_session`                         | `SessionManager` with S3 backend + AgentCore Memory service for long-term knowledge.        |

---

## Output: `agentic_design` in `aws-design-ai.json`

When Strands path is selected, write this to `aws-design-ai.json`:

```json
{
  "agentic_design": {
    "migration_approach": "strands",
    "strands_config": {
      "agents": [
        {
          "agent_id": "from agentic_profile.agents[].agent_id",
          "strands_primitive": "Agent|Graph|Swarm",
          "model_id": "from bedrock_models[].aws_model_id",
          "system_prompt": "extracted or placeholder",
          "tools": ["from tool_manifest, mapped to @tool functions"],
          "role_in_system": "orchestrator|specialist|worker"
        }
      ],
      "orchestration_primitive": "single_agent|agents_as_tools|swarm|graph",
      "session_manager": "none|file|s3",
      "memory_service": false,
      "deployment_target": "agentcore_runtime",
      "bridge_phase": true,
      "source_framework": "from agentic_profile.framework"
    },
    "regional_fit": "available|preview|unavailable",
    "warnings": []
  }
}
```

**Mapping `orchestration_pattern` → `orchestration_primitive`:**

| Detected pattern | Strands primitive | Rationale                                                                          |
| ---------------- | ----------------- | ---------------------------------------------------------------------------------- |
| `single`         | `single_agent`    | One Agent with tools. Simplest.                                                    |
| `hierarchical`   | `agents_as_tools` | Manager agent delegates to specialist agents wrapped as tools.                     |
| `swarm`          | `swarm`           | Multiple agents collaborate via shared memory.                                     |
| `graph`          | `graph`           | Explicit node/edge workflow with conditional routing.                              |
| `sequential`     | `graph` (linear)  | Graph with linear edges, no branching. Simpler than full graph but same primitive. |
| `unknown`        | `agents_as_tools` | Safe default — hierarchical delegation is the most common multi-agent pattern.     |

**`bridge_phase`:** Set to `true` if `source_framework == "openai_agents"` — indicates the partial retarget bridge (Phase 0) should be included in generated artifacts.

---

## AgentCore Agent Performance Loop (Public Preview, May 2026)

AgentCore launched an observe-evaluate-optimize-deploy loop in **public preview** (May 2026). APIs may change before GA; CloudTrail audit logging is not yet supported for these features. Surface this as an optional post-migration capability for teams that care about production evals, regression testing, prompt/tool optimization, and A/B rollout — not as an unconditional migration advantage.

**When to surface:** `agentic_profile.is_agentic == true` AND the design targets AgentCore Runtime, Evaluations, or Gateway. Not gated on `migration_approach == "strands"` alone — the capability is tied to AgentCore, not the Strands SDK specifically.

**Capabilities (all preview):**

| Capability           | What it does                                                                                                          | Prerequisite                                  | Cost note                                                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------ |
| **Recommendations**  | Analyzes production traces + evaluator outputs → recommends targeted updates to system prompts and tool descriptions  | AgentCore traces + evaluations must be active | No separate charge; underlying AgentCore service costs apply |
| **A/B Testing**      | Validates prompt/tool changes via controlled rollout before full deployment                                           | AgentCore Gateway                             | No separate charge                                           |
| **Batch Evaluation** | Replays curated or historical sessions to compare pre/post scores; catches regressions before changes reach end users | AgentCore Evaluations                         | No separate charge                                           |
| **User Simulation**  | Generates realistic multi-turn conversations using LLM-backed actors to reveal behaviors beyond scripted test cases   | AgentCore Evaluations                         | Incurs Bedrock model invocation costs per simulated turn     |

**Caveats to surface explicitly:**

- All capabilities are **public preview** — APIs may change before GA
- **CloudTrail not yet supported** — do not recommend for workloads requiring complete audit coverage
- User simulation incurs model invocation costs; estimate before enabling at scale
- Requires AgentCore traces/evaluations to be active before recommendations are useful

**Output addition to `aws-design-ai.json`:**

Add to `agentic_design` (optional — only when AgentCore Runtime/Evaluations/Gateway is in the design):

```json
"performance_loop": {
  "status": "preview",
  "capabilities": ["recommendations", "batch_evaluations", "user_simulation", "ab_testing"],
  "recommended_when": ["production eval requirements", "regression testing needed", "prompt/tool optimization desired", "A/B rollout required"],
  "prerequisites": ["AgentCore traces and evaluations active", "AgentCore Gateway for A/B testing"],
  "caveats": ["preview APIs — may change before GA", "CloudTrail not supported yet", "user simulation incurs model invocation costs"]
}
```

---

## Present Summary (Strands-specific additions)

After the standard model comparison summary from `design-ai.md`, add:

> **Agentic Migration: Strands Agents + AgentCore Runtime**
>
> - Source framework: [detected framework]
> - Strands primitive: [orchestration_primitive] (mapped from [detected orchestration_pattern])
> - Agents to convert: [count] ([list agent_ids])
> - Tools to migrate: [count] (existing functions get `@tool` decorator)
> - Deployment: AgentCore Runtime ([task_duration] sessions)
> - Memory: [session_manager] + [AgentCore Memory if cross_session]
> - Bridge phase: [yes/no — for OpenAI Agents SDK users]
> - Estimated effort: [range] depending on [drivers from guardrails]
> - **Performance loop (preview):** Because this design targets AgentCore Runtime, you can optionally add AgentCore's preview performance loop for evaluation, simulation, prompt/tool recommendations, and A/B validation. Note: CloudTrail not yet supported; user simulation incurs model costs.
> - **Note:** Strands Agents is an open-source AWS framework (strandsagents.com) that powers AgentCore internally. It provides multi-agent primitives (Graphs, Swarms, Agents-as-Tools, A2A) with native AgentCore deployment.
