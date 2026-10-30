# AgentCore Harness Design Reference

> Canonical AgentCore Harness design reference. Source-cloud agnostic: Harness
> is the target, and the incremental-migration shape does not vary by source cloud.
> Vendored into each consuming skill as
> `references/vendored/ai/design-ref-harness.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.
>
> Loaded by `design-ai.md` Step 0.6 when `agentic_profile.is_agentic == true` AND `ai_constraints.agentic.migration_approach == "harness"`.

**Prerequisites:** `references/vendored/ai/ai-migration-guardrails.md` must already be loaded (Step 0.6 loads it before this file). Do NOT duplicate regional caveats, pricing rules, or effort estimation rules here.

---

## When Harness Fits

Recommend Harness when:

- Single agent with tools (not complex multi-agent orchestration)
- OpenAI Assistants API migration (closest 1:1 mapping — Assistants → Harness declarations)
- Team wants managed runtime, memory, identity, and observability without building it
- Incremental migration: compare source-provider and Bedrock models in separate sessions, then start new application sessions on Bedrock
- Agent tasks run < 8 hours (Harness session limit)
- Team prefers config-first iteration over code-first
- Production workload — Harness is GA in all commercial regions with full platform support

## When Harness Does NOT Fit

Do NOT recommend Harness as primary path when:

- Complex multi-agent graphs with custom state management (recommend retarget or Strands)
- Team needs to stay in their current framework for velocity (recommend retarget)
- Agent count > 3 with inter-agent coordination (recommend retarget with AgentCore Runtime, or Strands)
- Custom runtime dependencies that can't be containerized (evaluate custom container image on Harness, or use AgentCore Runtime directly)

For these cases: fall back to retarget path (standard model-swap design in Parts 1–6 of `design-ai.md`).

---

## Harness Configuration Mapping

Map discovered elements to Harness configuration:

| Discovered element                                  | Harness config                                                             | Notes                                                               |
| --------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `bedrock_models[0].aws_model_id`                    | `model.modelId`, with `model.provider: "bedrock"`                            | CLI input JSON; the CLI writes its native Harness YAML             |
| `agents[0].role` or system prompt from code         | `systemPrompt`                                                             | Extract from code if possible; placeholder if not                   |
| Tools with `transport: "mcp"`                       | `tools[]: {"type": "remote_mcp", "config": {"remoteMcp": {"url": "..."}}}` | Direct MCP server connection                                        |
| Tools with `transport: "api"`                       | `tools[]: {"type": "remote_mcp"}` or `{"type": "agentcore_gateway"}`       | Wrap API as MCP server, or use Gateway for centralized auth         |
| Tools with `transport: "function"` (browser/web)    | `tools[]: {"type": "agentcore_browser"}`                                   | Built-in browser tool                                               |
| Tools with `transport: "function"` (code execution) | `tools[]: {"type": "agentcore_code_interpreter"}`                          | Built-in code interpreter                                           |
| Tools with `transport: "function"` (other)          | `tools[]: {"type": "inline_function", "config": {...}}`                    | Client-side execution; Harness pauses and returns call to your code |
| `memory_requirement: "session"`                     | Default behavior                                                           | Harness sessions are stateful by default (microVM per session)      |
| `memory_requirement: "cross_session"`               | AgentCore Memory service                                                   | Configure memory persistence across sessions                        |
| `memory_requirement: "none"`                        | No memory config needed                                                    | Stateless invocations                                               |

**Tool mapping decision:**

```
For each tool in tool_manifest[]:
├── transport == "mcp" → remote_mcp (direct connection)
├── transport == "api"
│   ├── auth_hint == "oauth" or multiple tools share auth → agentcore_gateway (centralized auth)
│   └── auth_hint == "api_key" or "none" → remote_mcp (simpler, wrap as MCP)
├── transport == "function"
│   ├── tool does web browsing/scraping → agentcore_browser
│   ├── tool executes code/scripts → agentcore_code_interpreter
│   └── other local function → inline_function (client-side)
└── transport == "unknown" → inline_function (safest default; client controls execution)
```

---

## Incremental Migration with Separate Comparison Sessions

If `ai_constraints.agentic.incremental_migration == true`:

### Phase 0: Deploy on Harness with existing source provider model

1. Configure the source provider credential through the official npm CLI without embedding the key in generated artifacts.
2. Set the source model and credential reference in the project's native `app/<name>/harness.yaml`, then deploy. Use the CLI's Gemini configuration for a legacy `source_model_provider: "google"` design.
3. Deploy and validate: existing behavior preserved on AWS infrastructure
4. Benefit: AWS observability, security, and scaling — without changing the model yet

### Phase 1: A/B test with Bedrock model

1. Retain two distinct UUIDs, `SOURCE_SESSION_ID` and `TARGET_SESSION_ID`, with the comparison evidence. Invoke the source using `--session-id "$SOURCE_SESSION_ID"` and `--prompt`.
2. Update the native Harness YAML to the selected Bedrock model and deploy it before invoking with `--session-id "$TARGET_SESSION_ID"`.
3. Replay the same ordered prompts independently and compare quality, latency, and tool behavior. **Session history is not transferred.** Do not reuse the source session ID or generate per-invocation model/provider override flags.

For manual commands, call `node "$(npm root -g)/@aws/agentcore/dist/index.js"` so the Python starter toolkit cannot shadow the CLI. Follow the generated manual plan; it does not deploy or invoke automatically.

### Phase 2: Switch default to Bedrock

1. Start new application sessions on the deployed Bedrock configuration.
2. Keep source credentials for a rollback that deploys the source configuration and starts new sessions.
3. Monitor for 48 hours

### Phase 3: Remove source provider

1. Delete API key from AgentCore Identity token vault
2. Remove source provider from Harness config
3. Migration complete

---

## Output: `agentic_design` in `aws-design-ai.json`

When Harness path is selected, write this to `aws-design-ai.json`:

```json
{
  "agentic_design": {
    "migration_approach": "harness",
    "harness_config": {
      "name": "from agentic_profile.agents[0].agent_id",
      "model_id": "from bedrock_models[0].aws_model_id",
      "system_prompt": "extracted from code or placeholder",
      "tools": [
        {
          "type": "remote_mcp|agentcore_browser|agentcore_code_interpreter|agentcore_gateway|inline_function",
          "name": "tool name from tool_manifest",
          "config": {}
        }
      ],
      "memory_enabled": true,
      "memory_type": "session|cross_session",
      "incremental_migration": true,
      "source_model_provider": "open_ai|google",
      "source_model_id": "from models[0].model_id",
      "policy_recommended": true
    },
    "regional_fit": "available|unavailable",
    "deployment_regions": ["from preferences.json target_region"],
    "warnings": []
  }
}
```

**Field rules:**

- `harness_config.name` — Derive from the first agent's `agent_id`, replacing hyphens with underscores. Start with a letter and use only letters, numbers, and underscores; do not emit kebab-case. After the user selects a migration-specific project name, keep `len(project_name) + len("default") + len(harness_config.name) + 2` at or below 40 for the combined deployed Harness name. Do not assume a fixed project name or fixed Harness-name budget. If the derived name is invalid or too long, request a valid name rather than silently truncating it.
- `harness_config.model_id` — The Bedrock model ID selected in Part 1 (e.g., `us.anthropic.claude-sonnet-5`)
- `harness_config.system_prompt` — Extracted from agent code if available; otherwise `"[TODO: Add system prompt from your agent definition]"`
- `harness_config.tools` — Mapped from `tool_manifest[]` using the tool mapping decision tree above
- `harness_config.source_model_provider` — `"open_ai"` or `"google"` based on `summary.ai_source`
- `harness_config.source_model_id` — Original model ID from `models[0].model_id`
- `harness_config.policy_recommended` — Set to `true` when `tool_manifest[]` contains tools with write operations (database mutations, API calls, file writes). Recommend AgentCore Policy for tool-call guardrails.
- `regional_fit` — Result of Step 0.5 regional check for AgentCore Harness in target region. Harness is GA in all commercial regions — this should almost always be `"available"`.

---

## Present Summary (Harness-specific additions)

After the standard model comparison summary from `design-ai.md`, add:

> **Agentic Migration: AgentCore Harness**
>
> - Approach: Config-based agent deployment on AgentCore
> - Tools mapped: [count] tools → [types breakdown]
> - Memory: [session/cross-session/none]
> - Incremental migration: [yes/no]
> - Regional availability: [available/preview in target region]
> - Estimated effort: [range] depending on [drivers from guardrails]
