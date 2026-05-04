# Local vs. Deployed — What Works Where

AgentCore has a local dev server (`agentcore dev`) and a deployed runtime. They don't have feature parity. This reference tells you what works where so generated code and troubleshooting handle both environments correctly.

## Quick reference

| Feature | `agentcore dev` (local) | Deployed runtime |
|---|---|---|
| Agent invocation | ✅ via curl on localhost:8080 | ✅ via `invoke_agent_runtime` or HTTPS |
| Framework model calls | ✅ if Bedrock creds are available | ✅ |
| Python/JS function tools (framework-native) | ✅ | ✅ |
| Credentials (`@requires_api_key`, `@requires_access_token`) | ✅ from `agentcore/.env.local` | ✅ from Secrets Manager |
| Memory | ❌ env var not set locally | ✅ `MEMORY_<NAME>_ID` injected |
| Gateway | ❌ env var not set locally | ✅ `AGENTCORE_GATEWAY_<NAME>_URL` injected |
| Cedar policy evaluation | ❌ policies only enforced at gateway | ✅ |
| Traces (X-Ray) | ✅ `agentcore dev` emits OTEL to CloudWatch by default; disable with `--no-traces` | ✅ auto-enabled |
| CloudWatch logs | ✅ via ADOT / OTEL wiring (same path as traces) | ✅ if using `logging` module + OTEL |
| **Evaluator *definition*** (`agentcore add evaluator`, writing the instructions/code) | ✅ — writes to `agentcore.json`; custom code is unit-testable locally | ✅ |
| **`agentcore run eval`** (on-demand eval over traces) | ✅ — operates on CloudWatch spans; local-dev spans land there if OTEL is on (default) | ✅ |
| **`Evaluate` API with hand-constructed spans** (boto3) | ✅ — no runtime needed at all; submit `SessionSpans` directly | ✅ |
| **Dataset runner** (`OnDemandEvaluationDatasetRunner`) | ❌ invokes an AgentCore Runtime agent in its pipeline | ✅ |
| **Online eval monitoring** (`agentcore add online-eval`) | ❌ ingests traces continuously from deployed runtime | ✅ |
| Observability dashboards | ✅ once Transaction Search is on and local spans are flowing | ✅ in CloudWatch console |
| VPC networking | ❌ local always has internet | ✅ subject to `networkMode: VPC` |
| Inbound auth (AWS_IAM, CUSTOM_JWT) | ❌ no auth required locally | ✅ enforced on every request |

## Implications for generated code

**Always guard features that aren't available locally:**

```python
# Memory pattern
MEMORY_ID = os.getenv("MEMORY_MYMEMORY_ID")
if MEMORY_ID:
    # deployed — wire up memory
    session_manager = AgentCoreMemorySessionManager(...)
else:
    # local — agent runs without memory
    session_manager = None
```

```python
# Gateway pattern
GATEWAY_URL = os.getenv("AGENTCORE_GATEWAY_WEATHER_URL")
if GATEWAY_URL:
    # deployed — use gateway tools
    tools = get_gateway_tools(GATEWAY_URL)
else:
    # local — agent runs without external tools or with local stubs
    tools = []
```

**Credentials work in both, but read from different sources.** The `@requires_api_key` decorator handles this automatically — don't try to read env vars directly.

## Testing workflow

Because memory, gateway, and policies don't work locally, the realistic test loop is:

1. **Local:** `agentcore dev` to verify the agent's code structure, framework wiring, system prompt, and any in-code logic
2. **Deploy to a staging target:** `agentcore deploy --target staging` to test with real memory, gateway, and policies
3. **Production:** only after staging validation

Don't expect `agentcore dev` to reproduce a production failure involving memory recall, gateway tool calls, or policy denials — those require a deployed environment.

## Common "works locally, fails deployed" causes

- Missing `MEMORY_<NAME>_ID` guard — code crashes because the env var is unexpectedly present
- Hardcoded localhost URLs for gateway — replace with `AGENTCORE_GATEWAY_<NAME>_URL`
- IAM permissions that work for your dev credentials but not the execution role
- Region mismatch between `aws configure` (used locally) and `aws-targets.json` (used in deploy)
- Tool call auth that works with your personal credentials but not with gateway SigV4 from the execution role

## Common "works deployed, fails locally" causes

- Code that assumes memory/gateway env vars are always set
- Direct SDK calls that expect the deployed execution role's permissions
- Hardcoded deployed-only URLs or ARNs
