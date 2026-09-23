# Generate Phase: AI Artifact Generation

> Loaded by generate.md when generation-ai.json and aws-design-ai.json exist.

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Generate migration artifacts from the AI migration plan and design. Artifacts vary by gateway type detected in discovery.

**Outputs (all users):**

- `ai-migration/setup_bedrock.sh` — Bedrock model access and IAM setup
- `ai-migration/test_comparison.py` — A/B test harness (always Python)
- `ai-migration/bedrock_monitoring.tf` — Bedrock cost budget, anomaly detection, inference profiles (always)

**Outputs (direct SDK users — `ai_framework` = `"direct"`):**

- `ai-migration/provider_adapter.{py,js,go}` — Provider abstraction with feature flag

**Outputs (gateway users — `ai_framework` != `"direct"`):**

- `ai-migration/gateway_config.{yaml,py,json}` — Gateway-specific configuration snippet

**Outputs (if user opted into model evaluation in generate-ai.md Part 0):**

- `ai-migration/eval-prompts.jsonl` — Evaluation prompt dataset
- `ai-migration/run-evaluation.sh` — Bedrock evaluation job script

## Prerequisites

Read from `$MIGRATION_DIR/`:

- `aws-design-ai.json` (REQUIRED) — AI architecture with model mappings and code migration plan
- `generation-ai.json` (REQUIRED) — AI migration plan with timeline and rollback strategy
- `ai-workload-profile.json` (REQUIRED) — AI workload profile with models, languages, and capabilities

If any required file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

**Sparse / IaC-only profile:** If `ai-workload-profile.json` has empty `models[]` or `metadata.profile_source` is `iac_vertex`, use `aws-design-ai.json` for Bedrock targets and example prompts; do **not** fail solely because discovery did not list model IDs.

---

## Step 0: Determine Artifact Path

Check `preferences.json` → `ai_constraints.ai_framework.value` and `aws-design-ai.json` → `ai_architecture.code_migration.migration_path`:

- `migration_path` = `"mantle"` → Generate Mantle setup (Step 1M) + setup (Step 3) + test harness (Step 2). Skip provider adapter (Step 1).
- `migration_path` = `"gpt-oss"` → Generate provider adapter (Step 1) targeting the gpt-oss model on Bedrock via the Converse API + setup (Step 3) + test harness (Step 2). Use the Bedrock model ID from `aws-design-ai.json` → `ai_architecture.bedrock_models[].aws_model_id` (the gpt-oss model ID). Do NOT generate a Mantle script — gpt-oss uses the Converse API directly.
- `"direct"` or absent → Generate provider adapter (Step 1) + setup (Step 3) + test harness (Step 2)
- `"llm_router"`, `"api_gateway"`, `"voice_platform"`, or `"framework"` → Skip Step 1, generate gateway config (Step 3B) instead

**Step 3F runs for ALL paths** (direct, mantle, gpt-oss, gateway, harness, strands) — generate `bedrock_monitoring.tf` regardless of migration path.

**Determine language** (direct SDK users only): Read `ai-workload-profile.json` → `integration.languages` array. Use the first entry: `"python"` → `.py`, `"javascript"`/`"typescript"` → `.js`, `"go"` → `.go`, other/unknown → `.py`.

---

## Step 1M: Generate Mantle Migration Script (OpenAI SDK via Mantle)

Generate `ai-migration/migrate_to_mantle.sh` — a shell script that configures the OpenAI SDK to use Bedrock's Mantle endpoints.

**Requirements:**

- Dry-run by default (`--execute` flag to apply)
- Print the environment variables to set: `OPENAI_BASE_URL=https://bedrock-mantle.{region}.api.aws/v1`, `OPENAI_API_KEY=<bedrock-api-key>`
- Print the model string change: current model ID → Bedrock model ID from `aws-design-ai.json`
- Include a quick verification call using the OpenAI SDK against the Mantle endpoint
- **Add a warning comment** about `max_tokens`: OpenAI SDK users migrating via Mantle carry over their existing `max_tokens` value unchanged. If the existing value is 4096 (OpenAI default), this reduces Bedrock concurrency by 5–8x on TPM quota. Instruct users to audit `max_tokens` before production and include the workload-type lookup table (see Step 1M max_tokens guidance above).
- Note: "No code changes required. Your existing OpenAI SDK calls work unchanged."
- Reference [Mantle documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html) for API key generation
- **Set `max_tokens` default to 1024** in the generated migration script with an explanatory comment. Do NOT inherit the caller's existing `max_tokens` value (often 4096 from OpenAI defaults) — this reduces concurrency by 5–8x on Bedrock's TPM quota. Include a workload-type lookup table as a comment so users tune before production:

  ```bash
  # max_tokens guidance — tune before production:
  # | Workload type                                | Suggested max_tokens |
  # |--------------------------------------------|----------------------|
  # | Classification / extraction / routing       | 256–512              |
  # | Chat / Q&A / summarization                  | 512–1024 (default)   |
  # | Long-form generation / reports              | 2048–4096             |
  # | Tool outputs / multi-step reasoning         | 2048–8192             |
  # | Code generation                             | 2048–4096             |
  # TODO: Review and adjust max_tokens for your workload before deploying to production.
  MAX_TOKENS=1024 # Starting point — see table above
  ```

Skip Step 1 (provider adapter) when this step runs — the OpenAI SDK is the adapter.

---

## Step 1: Generate Provider Adapter (Direct SDK Only)

Generate `ai-migration/provider_adapter.{py,js,go}` — an abstraction layer that lets the user switch between the source AI provider and Bedrock via an environment variable.

**Requirements:**

- Read `AI_PROVIDER` env var to select provider: `vertex_ai` (current), `bedrock` (target), `shadow` (both — return source response, log Bedrock response)
- Expose only the methods matching capabilities in `ai-workload-profile.json` → `integration.capabilities_summary`:
  - `text_generation: true` → `generate(prompt) → str`
  - `streaming: true` → `generate_stream(prompt) → Iterator[str]`
  - `embeddings: true` → `embed(text) → list[float]`
- **Source provider class**: Use SDK imports from `ai-workload-profile.json` → `integration.sdk_imports`. Use model IDs from `ai-workload-profile.json` → `models[].model_id`.
- **Bedrock provider class**: Use `boto3` Converse API (`converse` for generate, `converse_stream` for streaming, `invoke_model` for embeddings with Titan). Use inference profile ARNs from `bedrock_monitoring.tf` output `bedrock_inference_profile_arns` as `modelId` — this enables cost attribution in Cost Explorer. Fall back to raw model IDs from `aws-design-ai.json` → `ai_architecture.bedrock_models[].aws_model_id` if profiles are not yet deployed. Use region from `preferences.json` → `design_constraints.target_region`.

  ```python
  # Use inference profile ARN for cost attribution (preferred)
  # Set BEDROCK_INFERENCE_PROFILE_ARN from terraform output bedrock_inference_profile_arns
  MODEL_ID = os.environ.get(
      "BEDROCK_INFERENCE_PROFILE_ARN",
      "{aws_model_id}"  # fallback — replace with actual ARN from aws-design-ai.json
  )
  ```

- **Shadow mode**: Send requests to both providers, return source response, log Bedrock response for comparison.
- Include error handling and logging for API calls.

For JS: use `@aws-sdk/client-bedrock-runtime` + `@google-cloud/vertexai`. For Go: use `github.com/aws/aws-sdk-go-v2/service/bedrockruntime` + `cloud.google.com/go/aiplatform`.

---

## Step 2: Generate Test Comparison Harness

Generate `ai-migration/test_comparison.py` — always Python regardless of adapter language.

**Requirements:**

- Accept prompts from a JSON file (`--prompts`) or use built-in defaults (`--quick`)
- Run each prompt against both the source provider and Bedrock
- Measure per-prompt: latency (ms), success/failure, response text (truncated to 500 chars)
- Compute summary statistics: p50/p95/mean latency per provider, quality score (trait matching against expected traits), pass/fail criteria
- Pass criteria: Bedrock latency ≤ 2x source latency, mean quality score ≥ 0.9
- Output structured JSON to `--output` (default: `comparison_results.json`)
- Built-in test prompts: include 3-5 prompts based on `ai-workload-profile.json` → `models[].usage_context` covering the primary use case
- Import the provider adapter via `from provider_adapter import get_provider`

---

## Step 3: Generate Bedrock Setup Script

Generate `ai-migration/setup_bedrock.sh`.

**Requirements:**

- Dry-run by default (`--execute` flag to run for real)
- Step 1 — Request model access: List each model from `aws-design-ai.json` → `bedrock_models[].aws_model_id` and the embedding model
- Step 2 — Create IAM role: Trust policy for the compute platform (Lambda, ECS, or EC2 based on `aws-design.json` if present). Bedrock policy: `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` scoped to `arn:aws:bedrock:*::foundation-model/*`
- Compliance carry-through: if `preferences.json` → `design_constraints.compliance` is set and not `none`/`unknown` (full-flow Q2 / AI-only Q1.5), the script and its printed notes MUST reflect the design's Step 0.7 constraints — `AWS_REGION` from the compliance-constrained region (GovCloud for fedramp, EU for gdpr), `eu.` inference-profile model IDs for gdpr, and for hipaa a printed warning that Bedrock invocation logs retain original content (KMS-encrypt + restrict IAM on the log group before enabling)
- Step 3 — Print required environment variables: `AWS_REGION`, `AI_PROVIDER=bedrock`, model IDs
- Step 4 — Check quota: Query current TPM quota for the primary model via `aws service-quotas get-service-quota`. If `aws-design-ai.json` → `ai_architecture.quota_risk` is `"high"` or `"medium"`, print warning: "⚠️ Your token volume may exceed default Bedrock quotas. Request a quota increase via Service Quotas console (allow 1–5 business days)." Include the `aws service-quotas request-service-quota-increase` command template.
- Step 5 — Verification: Test Bedrock access with a simple `converse` call using the primary model
- If `$MIGRATION_DIR/terraform/` exists, print coordination note: "Ensure the IAM role is referenced in compute.tf task definitions"
- Use region from `preferences.json` → `design_constraints.target_region`

---

## Step 3B: Generate Gateway Configuration (Gateway Users Only)

Skip if `ai_framework` = `"direct"` or absent. Read `preferences.json` → `ai_constraints.ai_framework.value` to determine format.

**`"llm_router"`** → Generate `gateway_config.yaml` (LiteLLM format):

- Map each model from `aws-design-ai.json` to a `bedrock/MODEL_ID` entry with `aws_region_name`
- Include embedding model entry if embeddings are used
- Note required env vars: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`

**`"llm_router"` + OpenRouter detected** (evidence: `base_url` containing `openrouter.ai` in `ai-workload-profile.json` → `detection_signals`):

Check `aws-design-ai.json` → `code_migration.openrouter_path` (set in Design Part 5):

- `"same_model_mantle"` → Skip gateway config. Run **Step 1M** (Mantle migration script) using the OpenRouter-sourced model ID as the "current model ID" input. Add a header note that Step 1M's usual "no code changes required" claim does NOT hold here: OpenRouter → Mantle changes the base URL, credential type (Bedrock API key/token provider, not an OpenRouter key), and the model-ID format (e.g. `openai/gpt-4o` → the Mantle model ID). Print this as an explicit line in the generated script rather than reusing Step 1M's unchanged-code language verbatim.
- `"direct"` → Skip gateway config. Generate provider adapter instead (same as Step 1 for direct SDK users). Note: "Migrating from OpenRouter to direct Bedrock API removes the routing middleman and OpenRouter's margin."
- `"litellm"` → Generate `gateway_config.yaml` in LiteLLM format (standard `llm_router` logic above) + add header comment: "# Migration from OpenRouter to self-hosted LiteLLM with Bedrock backend\n# Install: pip install litellm\n# Run: litellm --config gateway_config.yaml"
- `"keep_openrouter"` → Generate `gateway_config.json` with OpenRouter model ID mappings:

  ```json
  {
    "models": {
      "original_model_id": "amazon/{bedrock_model_id}",
      "original_embedding_id": "amazon/{titan_embedding_model_id}"
    },
    "notes": "OpenRouter adds margin on top of provider pricing. Compare OpenRouter pricing vs direct Bedrock pricing in your cost estimate."
  }
  ```

- If `openrouter_path` is absent: default to `"litellm"` (standard LiteLLM config generation)

**`"framework"`** → Generate `gateway_config.py`:

- Show before/after import swap for the detected framework (`ai-workload-profile.json` → `integration.sdk_imports`)
- LangChain: `langchain_google_vertexai` → `langchain_aws.ChatBedrock` (or `langchain_openai` → `langchain_aws.ChatBedrock`)
- LlamaIndex: `llama_index.llms.vertex` → `llama_index.llms.bedrock_converse`
- Include pip install note for the AWS package

**`"voice_platform"`** → Generate `gateway_config.json`:

- Dashboard configuration steps: add Bedrock as provider, set model ID, set region, test before switching production
- Include the Bedrock model ID and region from design artifacts

**`"api_gateway"`** → Generate `gateway_config.yaml`:

- Upstream URL: `https://bedrock-runtime.{region}.amazonaws.com`
- Auth: AWS SigV4 signing for the `bedrock` service
- Note: Converse API endpoint is `POST /model/{modelId}/converse`
- Include gateway-specific notes (Kong plugin, Apigee policy)

---

## Step 3C: Generate AgentCore Harness Artifacts (Harness Users Only)

**Skip if** `aws-design-ai.json` → `agentic_design` is absent OR `agentic_design.migration_approach != "harness"`.

Read `aws-design-ai.json` → `agentic_design.harness_config` for all configuration values.

**Artifact 1: `ai-migration/harness.json`**

Generate the Harness configuration file:

```json
{
  "name": "{harness_config.name}",
  "model": "{harness_config.model_id}",
  "systemPrompt": "{harness_config.system_prompt}",
  "tools": [
    // Each tool from harness_config.tools, mapped to Harness tool format:
    // remote_mcp: {"type": "remote_mcp", "name": "...", "config": {"remoteMcp": {"url": "..."}}}
    // agentcore_browser: {"type": "agentcore_browser", "name": "browser"}
    // agentcore_code_interpreter: {"type": "agentcore_code_interpreter", "name": "code_interpreter"}
    // agentcore_gateway: {"type": "agentcore_gateway", "name": "...", "config": {"agentCoreGateway": {"gatewayArn": "[TODO: Gateway ARN]"}}}
    // inline_function: {"type": "inline_function", "name": "...", "config": {"inlineFunction": {"description": "...", "inputSchema": {...}}}}
  ]
}
```

Use actual values from `harness_config` — no placeholders except where noted with `[TODO: ...]`. Include a comment header explaining the file's purpose.

**Artifact 2: `ai-migration/deploy_harness.sh`**

Generate deployment script. Dry-run by default (`--execute` flag to run for real).

```bash
#!/bin/bash
# AgentCore Harness Deployment Script
# Generated by GCP-to-AWS migration plugin
# Run with --execute to perform actual deployment (default: dry-run)
set -euo pipefail

EXECUTE=${1:-""}
HARNESS_NAME="{harness_config.name}"
MODEL_ID="{harness_config.model_id}"
REGION="{target_region from preferences.json}"

run_cmd() {
    if [ "$EXECUTE" = "--execute" ]; then
        echo ">>> $*"
        eval "$@"
    else
        echo "[DRY-RUN] $*"
    fi
}

echo "=== AgentCore Harness Deployment: $HARNESS_NAME ==="
echo "Model: $MODEL_ID"
echo "Region: $REGION"
echo ""

# Step 1: Verify AgentCore CLI is installed
if ! command -v agentcore &> /dev/null; then
    echo "AgentCore CLI not found. Install with:"
    echo "  pip install bedrock-agentcore-cli"
    if [ "$EXECUTE" != "--execute" ]; then
        echo "[DRY-RUN] Continuing with remaining steps..."
    else
        exit 1
    fi
fi

# Step 2: Create project
run_cmd "agentcore create --name $HARNESS_NAME"

# Step 3: Add harness with model and tools
run_cmd "agentcore add harness --name $HARNESS_NAME \\
  --model-id $MODEL_ID \\
  --system-prompt '{harness_config.system_prompt}' \\
  --tools {comma-separated tool types from harness_config.tools}"

# Step 4: Deploy
run_cmd "agentcore deploy"

# Step 5: Test invocation
echo ""
echo "=== Test Invocation ==="
run_cmd "agentcore invoke --harness $HARNESS_NAME \\
  'Hello, this is a test invocation to verify deployment.'"

echo ""
echo "=== Deployment Complete ==="
echo "Next steps:"
echo "  1. Test with representative prompts: agentcore invoke --harness $HARNESS_NAME 'your prompt'"
echo "  2. Override model for A/B testing: agentcore invoke --harness $HARNESS_NAME --model-id <alt-model> 'prompt'"
echo "  3. View logs: agentcore logs --harness $HARNESS_NAME"
```

**Artifact 3: `ai-migration/incremental_migration.sh`** (only if `harness_config.incremental_migration == true`)

Generate incremental migration script showing multi-model switching:

```bash
#!/bin/bash
# Incremental Migration: Source Provider → Bedrock via AgentCore Harness
# This script demonstrates the multi-model switching capability.
# Run each phase manually and validate before proceeding to the next.
set -euo pipefail

HARNESS_NAME="{harness_config.name}"
SOURCE_PROVIDER="{harness_config.source_model_provider}"
SOURCE_MODEL="{harness_config.source_model_id}"
BEDROCK_MODEL="{harness_config.model_id}"
SESSION_ID=$(uuidgen)

echo "=== Incremental Migration Plan ==="
echo "Source: $SOURCE_PROVIDER / $SOURCE_MODEL"
echo "Target: Bedrock / $BEDROCK_MODEL"
echo "Session: $SESSION_ID"
echo ""

# Phase 0: Store source provider API key in AgentCore Identity
echo "--- Phase 0: Configure source provider credentials ---"
echo "Run once:"
echo "  agentcore add credential --type api-key --name source-provider-key --api-key \$SOURCE_API_KEY"
echo "  agentcore deploy"
echo ""

# Phase 1: Invoke with source provider model on AgentCore infrastructure
echo "--- Phase 1: Source provider on AgentCore ---"
echo "agentcore invoke --harness $HARNESS_NAME \\"
echo "  --model-provider $SOURCE_PROVIDER \\"
echo "  --model-id $SOURCE_MODEL \\"
echo "  --api-key-arn arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default/apikeycredentialprovider/source-provider-key \\"
echo "  --session-id $SESSION_ID \\"
echo "  'Your test prompt here'"
echo ""

# Phase 2: Same session, switch to Bedrock model
echo "--- Phase 2: Bedrock model (same session, context preserved) ---"
echo "agentcore invoke --harness $HARNESS_NAME \\"
echo "  --model-id $BEDROCK_MODEL \\"
echo "  --session-id $SESSION_ID \\"
echo "  'Same test prompt for comparison'"
echo ""

# Phase 3: Update default model
echo "--- Phase 3: Switch default to Bedrock ---"
echo "Edit app/$HARNESS_NAME/harness.json: set \"model\" to \"$BEDROCK_MODEL\""
echo "agentcore deploy"
echo ""

# Phase 4: Remove source provider
echo "--- Phase 4: Clean up source provider credentials ---"
echo "After 48h stable on Bedrock:"
echo "  Remove API key from AgentCore Identity"
echo "  agentcore deploy"
echo ""
echo "=== Migration Complete ==="
```

---

## Step 3D: Generate Evaluation Artifacts (If User Opted In)

Skip if the user did not opt into model evaluation in `generate-ai.md` Part 0.

**`eval-prompts.jsonl`**: Generate 10-20 domain-specific prompts in JSONL format (`{"prompt": "...", "referenceResponse": "", "category": "..."}`). Base prompts on `ai-workload-profile.json` → `models[].usage_context`. Include function-calling prompts if `capabilities_summary.function_calling` is true, retrieval prompts if RAG patterns were detected. Include 2-3 edge case prompts.

**`run-evaluation.sh`**: Dry-run by default. Creates S3 bucket, uploads prompts, calls `aws bedrock create-evaluation-job` with model IDs from `aws-design-ai.json`, downloads results. Use the same model IDs and region as `setup_bedrock.sh`.

---

## Step 3E: Generate Strands Migration Artifacts (Strands Users Only)

**Skip if** `aws-design-ai.json` → `agentic_design` is absent OR `agentic_design.migration_approach != "strands"`.

Read `aws-design-ai.json` → `agentic_design.strands_config` for all configuration values.

**Artifact 1: `ai-migration/strands_agents.py`**

Generate Strands agent definitions from the design config. For each agent in `strands_config.agents`:

```python
"""
Strands Agents Migration — Generated by GCP-to-AWS migration plugin
Source framework: {strands_config.source_framework}
Orchestration: {strands_config.orchestration_primitive}

Install: pip install strands-agents strands-agents-tools boto3
Docs: https://strandsagents.com
"""
from strands import Agent, tool
from strands.models import BedrockModel

# Model configuration
model = BedrockModel(
    model_id="{agents[0].model_id}",
    region_name="{target_region}"
)

# --- Tool definitions ---
# Migrate your existing tool functions by adding the @tool decorator.
# Your tool logic stays the same; Strands handles invocation and result parsing.

@tool
def {tool_name}({params}) -> str:
    """[TODO: Your existing tool description]"""
    # [TODO: Paste your existing tool implementation here]
    pass

# --- Agent definitions ---
{agent_name} = Agent(
    name="{agent_id}",
    model=model,
    system_prompt="""{system_prompt}""",
    tools=[{tool_list}]
)
```

**For multi-agent systems**, generate the orchestration based on `orchestration_primitive`:

- **`agents_as_tools`** (hierarchical):

```python
# Specialist agents wrapped as tools for the orchestrator
@tool
def {specialist_agent_id}(query: str) -> str:
    """[role description]"""
    response = {specialist_var}(query)
    return str(response)

# Orchestrator delegates to specialists
orchestrator = Agent(
    name="orchestrator",
    model=model,
    tools=[{specialist_tool_1}, {specialist_tool_2}, ...]
)

result = orchestrator("Your task here")
```

- **`swarm`** (collaborative):

```python
from strands.multiagent import Swarm

team = Swarm([{agent_1}, {agent_2}, {agent_3}])
result = team("Your task here")
```

- **`graph`** (deterministic workflow):

```python
from strands.multiagent import GraphBuilder

builder = GraphBuilder()
builder.add_node({agent_1}, "{node_1_name}")
builder.add_node({agent_2}, "{node_2_name}")
builder.add_edge("{node_1_name}", "{node_2_name}")  # Add conditions if detected
builder.set_entry_point("{entry_node}")
workflow = builder.build()

result = workflow("Your task here")
```

- **`single_agent`**: Just the single Agent definition (no multi-agent orchestration).

Use actual agent IDs, model IDs, tool names, and system prompts from the design config. Mark TODOs only where implementation details can't be extracted from discovery.

**Artifact 2: `ai-migration/deploy_strands.sh`**

Generate AgentCore Runtime deployment script. Dry-run by default.

```bash
#!/bin/bash
# Strands Agents — AgentCore Runtime Deployment
# Generated by GCP-to-AWS migration plugin
# Run with --execute to perform actual deployment (default: dry-run)
set -euo pipefail

EXECUTE=${1:-""}
PROJECT_NAME="{agent_id}-strands"
REGION="{target_region}"

run_cmd() {
    if [ "$EXECUTE" = "--execute" ]; then
        echo ">>> $*"
        eval "$@"
    else
        echo "[DRY-RUN] $*"
    fi
}

echo "=== Strands Agents — AgentCore Runtime Deployment ==="
echo "Project: $PROJECT_NAME"
echo "Region: $REGION"
echo "Agents: {agent_count}"
echo ""

# Step 1: Verify dependencies
echo "--- Prerequisites ---"
run_cmd "pip install strands-agents strands-agents-tools boto3 bedrock-agentcore-cli"

# Step 2: Create AgentCore project
run_cmd "agentcore create --name $PROJECT_NAME"

# Step 3: Deploy to AgentCore Runtime
echo ""
echo "--- Deploying to AgentCore Runtime ---"
run_cmd "agentcore deploy"

# Step 4: Test invocation
echo ""
echo "--- Test Invocation ---"
run_cmd "agentcore invoke --name $PROJECT_NAME 'Hello, test invocation'"

echo ""
echo "=== Deployment Complete ==="
echo "Next steps:"
echo "  1. Run locally first: python strands_agents.py"
echo "  2. Test with representative prompts"
echo "  3. Deploy: ./deploy_strands.sh --execute"
echo "  4. Monitor: agentcore logs --name $PROJECT_NAME"
echo ""
echo "Strands docs: https://strandsagents.com"
echo "AgentCore docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/"
```

**Artifact 3: `ai-migration/bridge_retarget.py`** (only if `strands_config.bridge_phase == true`)

Generate a partial retarget bridge for OpenAI Agents SDK users — routes model calls through Bedrock while keeping existing orchestration temporarily:

```python
"""
Bridge: OpenAI Agents SDK → Bedrock (via OpenAI-compatible endpoint)
This is a temporary bridge. Use while migrating orchestration to Strands.

This works because Bedrock's Converse API can be accessed through an
OpenAI-compatible proxy, allowing your existing OpenAI Agents SDK code
to call Bedrock models without code changes.

After validating Bedrock model quality, migrate to Strands for full
AWS-native agent capabilities.
"""
import os

# Option A: Use LiteLLM as OpenAI-compatible proxy to Bedrock
# pip install litellm
# Set: OPENAI_API_BASE=http://localhost:4000  (LiteLLM proxy)
# LiteLLM config: model_list: [{model_name: "gpt-4o", litellm_params: {model: "bedrock/{bedrock_model_id}"}}]

# Option B: Use Bedrock's OpenAI-compatible endpoint (if available)
# Set: OPENAI_API_BASE=https://bedrock-runtime.{region}.amazonaws.com/openai/v1
# Set: OPENAI_API_KEY=<not used, auth via SigV4>

# Your existing OpenAI Agents SDK code continues to work unchanged.
# The model calls route through Bedrock instead of OpenAI.

BRIDGE_CONFIG = {
    "source_model": "{source_model_id}",
    "target_model": "bedrock/{bedrock_model_id}",
    "proxy": "litellm",  # or "bedrock_openai_compat"
    "region": "{target_region}",
    "note": "Temporary bridge. Migrate to Strands (strands_agents.py) when ready."
}

print(f"Bridge configured: {BRIDGE_CONFIG['source_model']} → {BRIDGE_CONFIG['target_model']}")
print(f"Next step: Validate model quality, then migrate to Strands.")
```

---

---

## Step 3F: Generate Bedrock Cost Monitoring Terraform

**Runs for ALL migration paths** (direct, mantle, gpt-oss, gateway, harness, strands).
Creates `ai-migration/bedrock_monitoring.tf` — standalone Terraform for AI-only migrations
that have no `baseline.tf` from the infra track.

> **These are detective controls, not spend caps.** Bedrock has no native spend limit.
> Anomaly Detection has ~24h data lag — you'll know within a day, not at month-end invoice.
> AI-only migrations (infra stays on GCP) have zero cost guardrails without this file.

**Seed budget threshold:** Read `estimation-ai.json` → `cost_comparison.projected_bedrock_monthly`.
Round up to nearest integer. If absent, use `50` as the default.

Emit the final computed integer directly in `limit_amount` — do not emit an expression.

```hcl
# ============================================================
# Bedrock Cost Monitoring — Generated by GCP to AWS Migration Advisor
#
# DETECTIVE CONTROLS, NOT SPEND CAPS. Bedrock has no native
# spend limit. Anomaly Detection has ~24h data lag.
# ============================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.66"  # aws_bedrock_inference_profile requires >= 5.66
    }
  }
}

provider "aws" {
  region = "{target_region}"  # from preferences.json design_constraints.target_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

variable "project_name" {
  description = "Project name for resource naming and tagging"
  type        = string
}

variable "alert_email" {
  description = "Email address for Bedrock cost alert notifications"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "app_name" {
  description = "Application name for cost attribution tags"
  type        = string
  default     = "migration"
}

# Bedrock-scoped monthly budget
# Uses 1.5x multiplier (vs 1.2x in baseline.tf account-wide budget) because
# Bedrock token costs are more volatile than infrastructure.
# For hybrid runs: coexists with baseline.tf account-wide budget — different scopes, no conflict.
resource "aws_budgets_budget" "bedrock_spend" {
  name         = "${var.project_name}-bedrock-monthly"
  budget_type  = "COST"
  limit_amount = "{projected_bedrock_monthly_times_1.5_as_integer}"  # AGENT: replace with ceil(projected * 1.5), min 10
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "Service"
    values = ["Amazon Bedrock"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# Bedrock anomaly detection — DIMENSIONAL/SERVICE monitors all services independently.
# A Bedrock spend spike will surface as an anomaly for the SERVICE=AmazonBedrock dimension.
# Note: DIMENSIONAL monitors all services; the budget above is Bedrock-scoped via cost_filter.
resource "aws_ce_anomaly_monitor" "bedrock" {
  name             = "${var.project_name}-bedrock-anomaly"
  monitor_type     = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "bedrock_alert" {
  name      = "${var.project_name}-bedrock-anomaly-alert"
  frequency = "DAILY"

  monitor_arn_list = [aws_ce_anomaly_monitor.bedrock.arn]

  subscriber {
    address = var.alert_email
    type    = "EMAIL"
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_PERCENTAGE"
      values        = ["50"]
      match_options = ["GREATER_THAN_OR_EQUAL"]
    }
  }
}

# Application inference profiles — cost attribution by environment/app
# Tags on these profiles appear in Cost Explorer; tags on API calls do not.
# copy_from must be a full foundation-model ARN or cross-region inference profile ARN.
# For Claude models, use the cross-region inference profile ARN format:
#   arn:aws:bedrock:{region}:{account_id}:inference-profile/us.anthropic.claude-sonnet-5
# For Amazon Nova models, use:
#   arn:aws:bedrock:{region}:{account_id}:inference-profile/us.amazon.nova-pro-v1:0
# [AGENT: generate one block per model in aws-design-ai.json → ai_architecture.bedrock_models[]]
resource "aws_bedrock_inference_profile" "primary" {
  name = "${var.project_name}-${var.environment}-primary"

  model_source {
    # Use cross-region inference profile ARN, not bare model ID
    copy_from = "arn:aws:bedrock:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:inference-profile/{cross_region_inference_profile_id}"
    # AGENT: replace {cross_region_inference_profile_id} with the correct ID from
    # aws-design-ai.json bedrock_models[].aws_model_id, prefixed with "us." for US regions
    # e.g., us.anthropic.claude-sonnet-5 or us.amazon.nova-pro-v1:0
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    Application = var.app_name
    ManagedBy   = "terraform"
  }
}

output "bedrock_inference_profile_arns" {
  value = {
    primary = aws_bedrock_inference_profile.primary.arn
  }
  description = "Use these ARNs as BEDROCK_INFERENCE_PROFILE_ARN env var in your adapter for cost attribution"
}
```

## Step 4: Self-Check

Verify all generated artifacts:

- [ ] Provider adapter (or gateway config) uses actual model IDs from `aws-design-ai.json` — no placeholders
- [ ] Only capabilities present in `capabilities_summary` have methods/tests generated
- [ ] Feature flag (`AI_PROVIDER` env var) controls provider selection in adapter
- [ ] Test harness includes domain-specific prompts from `usage_context`
- [ ] Test harness produces structured JSON output with latency and quality metrics
- [ ] Setup script has correct region from `preferences.json`
- [ ] Setup script IAM role follows least privilege
- [ ] All scripts default to dry-run mode
- [ ] Evaluation artifacts (if generated) have correct model IDs and region
- [ ] No hardcoded credentials in any file
- [ ] bedrock_monitoring.tf generated with budget limit_amount as computed integer (not expression)
- [ ] Budget limit_amount = ceil(projected_bedrock_monthly * 1.5), minimum 10
- [ ] Anomaly monitor uses monitor_type = "DIMENSIONAL" with monitor_dimension = "SERVICE" (no monitor_specification)
- [ ] Inference profile copy_from uses full ARN format, not bare model ID
- [ ] Provider adapter references BEDROCK_INFERENCE_PROFILE_ARN env var with model ID fallback
- [ ] alert_email variable declared in bedrock_monitoring.tf
- [ ] If Harness artifacts generated: `harness.json` uses actual model ID from `agentic_design.harness_config.model_id`
- [ ] If Harness artifacts generated: `harness.json` tool types match `tool_manifest[].transport` mapping
- [ ] If Harness artifacts generated: `deploy_harness.sh` defaults to dry-run
- [ ] If Harness artifacts generated: `incremental_migration.sh` only present when `incremental_migration == true`
- [ ] If OpenRouter path: artifact type matches `code_migration.openrouter_path` value
- [ ] If Strands artifacts generated: `strands_agents.py` uses actual model IDs, agent IDs, and tool names from design config
- [ ] If Strands artifacts generated: orchestration primitive matches `strands_config.orchestration_primitive`
- [ ] If Strands artifacts generated: `bridge_retarget.py` only present when `strands_config.bridge_phase == true`
- [ ] If Strands artifacts generated: `deploy_strands.sh` defaults to dry-run

## Phase Completion

Report generated files to the parent orchestrator. **Do NOT update `.phase-status.json`** — the parent `generate.md` handles phase completion.

Output:

```
Generated AI migration artifacts:
- ai-migration/setup_bedrock.sh
- ai-migration/test_comparison.py
- ai-migration/provider_adapter.{py|js|go}    # Direct SDK users only
- ai-migration/gateway_config.{yaml|py|json}  # Gateway users only
- ai-migration/harness.json                    # Harness users only
- ai-migration/deploy_harness.sh              # Harness users only
- ai-migration/incremental_migration.sh       # Harness + incremental only
- ai-migration/strands_agents.py              # Strands users only
- ai-migration/deploy_strands.sh              # Strands users only
- ai-migration/bridge_retarget.py             # Strands + OpenAI Agents SDK bridge only
- ai-migration/bedrock_monitoring.tf          # Always — Bedrock budget, anomaly detection, inference profiles
- ai-migration/eval-prompts.jsonl              # If evaluation opted in
- ai-migration/run-evaluation.sh               # If evaluation opted in

Gateway type: [ai_framework value]
Language: [detected language]
Models to migrate: [count] models
Capabilities covered: [list from capabilities_summary]
```
