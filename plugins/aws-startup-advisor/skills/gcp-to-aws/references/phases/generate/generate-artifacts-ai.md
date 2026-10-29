# Generate Phase: AI Artifact Generation

> Loaded by generate.md when generation-ai.json and aws-design-ai.json exist.

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Generate migration artifacts from the AI migration plan and design. Artifacts vary by gateway type detected in discovery.

**Outputs (all users):**

- `ai-migration/setup_bedrock.sh` — Bedrock model access and IAM setup
- `ai-migration/test_comparison.py` — A/B test harness (always Python)
- `ai-migration/bedrock_monitoring.tf` — Bedrock cost budget, anomaly detection, inference profiles (always)

**Outputs (direct SDK users, selected Mantle path):**

- `ai-migration/migrate_to_mantle.sh` — Selected Chat/Responses client setup; no provider adapter

**Outputs (direct SDK users, selected runtime path):**

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

**AgentCore deployment scripts (Steps 3C and 3E):** Use the official [`@aws/agentcore` CLI](https://github.com/aws/agentcore-cli), which requires Node.js 20.12 or later and npm. The deprecated Python starter toolkit also provides an `agentcore` executable; ensure it does not shadow the npm CLI. Verify each generated command against the installed CLI's `--help` before deployment.

---

## Step 0: Determine Artifact Path

Check `preferences.json` → `ai_constraints.ai_framework.value` and `aws-design-ai.json` → `ai_architecture.code_migration.migration_path`:

- `migration_path` starts with `"mantle"` (`"mantle"`, `"mantle_openai_chat"`, `"mantle_openai_responses"`) → Generate Mantle setup (Step 1M) + setup (Step 3) + test harness (Step 2). Skip provider adapter (Step 1). Design records `"mantle_openai_responses"`; treat that spelling as this same Mantle path.
- `migration_path` = `"runtime_openai_cris"` → Generate the CRIS-aware Mantle-equivalent script
  (Step 1M, using the `us.`/`global.`-prefixed inference-profile ID and the `bedrock-runtime`
  base URL instead of `bedrock-mantle`) + setup (Step 3) + test harness (Step 2). Skip provider
  adapter (Step 1) — same as `"mantle"`, just a different endpoint and model-id form.
- `migration_path` = `"gpt-oss"` → Generate provider adapter (Step 1) targeting the gpt-oss model on Bedrock via the Converse API + setup (Step 3) + test harness (Step 2). Use the Bedrock model ID from `aws-design-ai.json` → `ai_architecture.bedrock_models[].aws_model_id` (the gpt-oss model ID). Do NOT generate a Mantle script — gpt-oss uses the Converse API directly.
- `"converse"`, `"direct"`, or absent → Generate provider adapter (Step 1) + setup (Step 3) + test harness (Step 2). `"converse"` is a Converse client swap (Design records it when a proprietary model cannot stay on Mantle); do NOT generate a Mantle script for it.
- `"llm_router"`, `"api_gateway"`, `"voice_platform"`, or `"framework"` → Skip Step 1, generate gateway config (Step 3B) instead. Step 3B's OpenRouter subroute can still replace that gateway config with Step 1M (`same_model_mantle`) or the provider adapter (`direct`); do not decide those two from `migration_path` alone.

For `runtime_openai_cris`, read the matched `bedrock_models[].required_client_api`.
Use `responses` for current Design plans without that field; only legacy plans fall back
to the row or `code_migration.runtime_api` and their Converse default. Use the resolved
API consistently for the generated client, comparison and setup calls.
Preserve the exact `aws_model_id` string, whether a short profile ID or a system-profile ARN.
When building the IAM policy, use a supplied profile ARN directly and resolve its backing
foundation-model resources; do not interpolate the ARN into another ARN.

**Step 3F runs for ALL paths** (direct, mantle, gpt-oss, gateway, harness, strands) — generate `bedrock_monitoring.tf` regardless of migration path.

**Determine language** (direct SDK users only): Read `ai-workload-profile.json` → `integration.languages` array. Use the first entry: `"python"` → `.py`, `"javascript"`/`"typescript"` → `.js`, `"go"` → `.go`, other/unknown → `.py`.

---

## Step 1M: Generate Mantle Migration Script (OpenAI SDK via Mantle)

Generate `ai-migration/migrate_to_mantle.sh` — a shell script that configures the OpenAI SDK to use Bedrock's Mantle endpoints.

**Requirements:**

- Dry-run by default (`--execute` flag to apply)
- For proprietary GPT targets, print `OPENAI_BASE_URL=https://bedrock-mantle.{region}.api.aws/openai/v1`. Use the model-specific base path from `shared/openai-on-bedrock.md`; generic `/v1` returns 404 for proprietary GPT models. Credentials must be Bedrock credentials, not the source provider's API key; prefer the auto-refreshing `BedrockOpenAI` token provider shown in that reference.
- Print the model string change: current model ID → Bedrock model ID from `aws-design-ai.json`
- Include a quick verification call using the selected Mantle API: `chat.completions.create` for `mantle_openai_chat`, `responses.create` for `mantle_openai_responses`. Reuse the target-call shape in Step 2; never call Converse with a bare Astra ID.
- Preserve request/response shapes only when the selected API matches the source. Otherwise include the planned API reshape. Do not claim all existing SDK calls work unchanged; parameters and tool/state behavior still need the selected model/API's verification.
- Reference [Mantle documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html) for API key generation
- Include the output-budget lookup table below as a starting heuristic. Send a budget parameter only after verifying its name and behavior for the selected API; `MAX_TOKENS` is a local tuning value, not permission to send a `max_tokens` kwarg to every model. Do not apply Claude/runtime quota multipliers or GPT-5.x cache exemptions to Astra Mantle.

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

**CRIS variant client surface:** When `migration_path` is `"runtime_openai_cris"`, check `aws-design-ai.json` → `ai_architecture.bedrock_models[].required_client_api`. If it is non-Responses (`converse`, `chat_completions`, or `invoke`), the generated CRIS client/adapter MUST emit that surface — e.g. a `client.converse(...)` call against the `bedrock-runtime` CRIS id — rather than defaulting to `responses.create`. If absent or `"responses"`, keep the Responses surface (the region-only-move default).

Skip Step 1 when this step runs. Step 2 uses the selected client directly for both
Mantle and runtime CRIS; do not emit or import a provider-adapter stub on these paths.

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
- **Bedrock provider class**: For a Converse plan, use `boto3` (`converse` for generate, `converse_stream` for streaming, `invoke_model` for separately selected Titan embeddings). For `runtime_openai_cris`, preserve the runtime API selected in the design: Converse uses this adapter shape; an OpenAI-compatible Chat/Responses selection uses the OpenAI SDK at `https://bedrock-runtime.{region}.amazonaws.com/openai/v1` with Bedrock credentials and the exact CRIS ID. Never send a bare Astra ID to runtime or replace a validated `global.` profile with `us.`. Use an application inference profile only when the selected model/API supports it; otherwise retain `aws-design-ai.json` → `ai_architecture.bedrock_models[].aws_model_id`. Use region from `preferences.json` → `design_constraints.target_region`.

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

For JS/Go, choose the source SDK from the recorded imports rather than assuming Vertex. Use the AWS runtime SDK for a Converse target, or the matching OpenAI client for a selected OpenAI-compatible runtime API.

---

## Step 2: Generate Test Comparison Harness

Generate `ai-migration/test_comparison.py` — always Python regardless of adapter language.

**Requirements:**

- Accept prompts from a JSON file (`--prompts`) or use built-in defaults (`--quick`)
- Support `--target-only` for the setup smoke test; this mode needs no source credentials.
- Run each prompt against both the source provider and Bedrock
- Measure per-prompt: latency (ms), success/failure, response text (truncated to 500 chars)
- Compute summary statistics: p50/p95/mean latency per provider, quality score (trait matching against expected traits), pass/fail criteria
- Pass criteria: Bedrock latency ≤ 2x source latency, mean quality score ≥ 0.9
- Output structured JSON to `--output` (default: `comparison_results.json`)
- Built-in test prompts: include 3-5 prompts based on `ai-workload-profile.json` → `models[].usage_context` covering the primary use case
- **Adapter paths** (`direct`, `converse`, `gpt-oss`, or a gateway subroute that emits an adapter): use `from provider_adapter import get_provider` from the emitted provider adapter.
- **Mantle / runtime CRIS / `same_model_mantle` paths:** do not import `provider_adapter` because Step 0 intentionally skips it. Call the source using its recorded SDK and call the target directly with the selected Mantle API. Use this target function for proprietary GPT plans, substituting the saved design values:

  ```python
  def call_bedrock(prompt):
      from aws_bedrock_token_generator import provide_token
      from openai import BedrockOpenAI

      region = "{target_region}"
      model_id = "{aws_model_id}"
      api_path = "{migration_path}"
      required_client_api = "{required_client_api}"
      if api_path == "runtime_openai_cris":
          if required_client_api == "converse":
              import boto3
              response = boto3.client("bedrock-runtime", region_name=region).converse(
                  modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}]
              )
              return "".join(block["text"] for block in response["output"]["message"]["content"] if "text" in block)
          if required_client_api not in {"responses", "chat_completions"}:
              raise ValueError("Generate the model-specific selected runtime API before comparison")
          from openai import OpenAI
          client = OpenAI(
              base_url=f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1",
              api_key=lambda: provide_token(region=region), max_retries=2,
          )
      else:
          client = BedrockOpenAI(
              aws_region=region,
              bedrock_token_provider=lambda: provide_token(region=region),
              max_retries=2,
          )
      if api_path == "mantle_openai_chat" or (api_path == "runtime_openai_cris" and required_client_api == "chat_completions"):
          response = client.chat.completions.create(
              model=model_id, messages=[{"role": "user", "content": prompt}]
          )
          return response.choices[0].message.content
      response = client.responses.create(model=model_id, input=prompt)
      return response.output_text
  ```

  Substitute the resolved `required_client_api` for runtime plans. A selected `invoke`
  surface needs its model-specific Invoke harness before setup; never substitute Converse.
  Mantle uses the recorded migration path.

  Install `openai>=2.45.0,<3` and `aws-bedrock-token-generator>=1,<2` in the generated project's environment. The setup smoke test invokes this same harness with `--target-only --quick`, so setup and comparison cannot choose different APIs.

---

## Step 3: Generate Bedrock Setup Script

Generate `ai-migration/setup_bedrock.sh`.

**Requirements:**

- Dry-run by default (`--execute` flag to run for real)
- Step 1 — Request model access: List each model from `aws-design-ai.json` → `bedrock_models[].aws_model_id` and the embedding model
- Step 2 — Create IAM role: Trust policy for the compute platform (Lambda, ECS, or EC2 based on `aws-design.json` if present). Match inference permissions to the selected endpoint. Mantle needs `bedrock-mantle:CreateInference` scoped to `arn:aws:bedrock-mantle:{region}:{account_id}:project/*`, plus `bedrock-mantle:CallWithBearerToken` on `*` when using bearer credentials. Runtime needs `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` against the selected foundation-model ARN and, for CRIS, the exact inference-profile ARN. For GPT-6 CRIS, also grant `bedrock:InvokeModel` on `arn:aws:bedrock:{region}:{account}:project/default`. Runtime actions do not authorize Mantle.
- If the runtime client uses `BEDROCK_INFERENCE_PROFILE_ARN` from the generated monitoring output, also authorize that exact `application-inference-profile/…` ARN, retaining the backing model/CRIS resources needed for the selected model and fallback. Resolve it from the same output used by the client; do not grant every application profile. Re-run setup after enabling or changing this override so the effective invocation target and IAM remain aligned. See [inference-profile IAM prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).
- Compliance carry-through: if `preferences.json` → `design_constraints.compliance` is set and not `none`/`unknown` (full-flow Q2 / AI-only Q1.5), the script and its printed notes MUST reflect the design's Step 0.7 constraints — `AWS_REGION` from the compliance-constrained region (GovCloud for fedramp, EU for gdpr), `eu.` inference-profile model IDs for gdpr, and for hipaa a printed warning that Bedrock invocation logs retain original content (KMS-encrypt + restrict IAM on the log group before enabling)
- Step 3 — Print required environment variables: `AWS_REGION`, `AI_PROVIDER=bedrock`, model IDs
- Step 4 — Check quota: Query current TPM quota for the primary model via `aws service-quotas get-service-quota`. If `aws-design-ai.json` → `ai_architecture.quota_risk` is `"high"` or `"medium"`, print warning: "⚠️ Your token volume may exceed default Bedrock quotas. Request a quota increase via Service Quotas console (allow 1–5 business days)." Include the `aws service-quotas request-service-quota-increase` command template.
- Step 5 — Verification: Run `test_comparison.py --target-only --quick` using the same selected API, model ID and region as the generated client. A Mantle selection must never run a Converse probe; a runtime selection must preserve its validated profile ID.
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

Generate strict JSON (no comments) as input to `agentcore add harness`. The CLI writes the deployed configuration to `app/<name>/harness.yaml`; this input file is not that native YAML schema.

```json
{
  "name": "{harness_config.name}",
  "model": {"provider": "bedrock", "modelId": "{harness_config.model_id}"},
  "systemPrompt": "{harness_config.system_prompt}",
  "tools": []
}
```

Populate `tools` from the design as full JSON objects, not comma-separated tool names. Preserve each tool's name, type, and configuration using the [Harness tool schema](https://github.com/aws/agentcore-cli/blob/e2f59dad4bbb124021c0cf59111c4add63a9dbcb/docs/harness-project-configuration.md#tools-and-tool-access): `remote_mcp`/`remoteMcp`, `agentcore_gateway`/`agentCoreGateway`, `agentcore_browser`/`agentCoreBrowser`, `agentcore_code_interpreter`/`agentCoreCodeInterpreter`, and `inline_function`/`inlineFunction`. Do not silently drop tools or deploy unresolved TODOs. Use CLI-valid logical names (letters, numbers, underscores, starting with a letter).

**Artifact 2: `ai-migration/deploy_harness.sh`**

Generate a first-deployment script alongside `harness.json`. Dry-run by default. These commands follow the [AgentCore CLI 1.0.1 command reference](https://github.com/aws/agentcore-cli/blob/e2f59dad4bbb124021c0cf59111c4add63a9dbcb/command.md). Keep arguments separate: prompts and JSON must never be evaluated as shell code. A pre-existing project must be updated from its project directory, not overwritten by this script.

```bash
#!/bin/bash
set -euo pipefail

EXECUTE=${1:-""}
RUN_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REGION="{target_region from preferences.json}"

run_cmd() {
    if [ "$EXECUTE" = "--execute" ]; then
        "$@"
    else
        printf '[DRY-RUN] '
        printf '%q ' "$@"
        printf '\n'
    fi
}

# Step 1: Verify prerequisites
if ! command -v agentcore >/dev/null 2>&1; then
    echo "AgentCore CLI not found. Install with: npm install -g @aws/agentcore"
    if [ "$EXECUTE" = "--execute" ]; then exit 1; fi
fi
CONFIG="$RUN_DIR/harness.json"
PROJECT_NAME="migration"
HARNESS_NAME=$(python3 -c '
import json, re, sys
name = json.load(open(sys.argv[1]))["name"]
if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
    raise SystemExit("Harness name must start with a letter and contain only letters, numbers or underscores")
if len("_".join((sys.argv[2], "default", name))) > 40:
    raise SystemExit("Combined project/default-target/harness name exceeds 40 characters; choose a shorter name")
print(name)
' "$CONFIG" "$PROJECT_NAME")
MODEL_JSON=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["model"]))' "$CONFIG")
TOOLS_JSON=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["tools"]))' "$CONFIG")
# NUL termination preserves trailing newlines in the system prompt.
IFS= read -r -d '' SYSTEM_PROMPT < <(python3 -c 'import json,sys; sys.stdout.write(json.load(open(sys.argv[1]))["systemPrompt"] + "\0")' "$CONFIG")
# Step 2: Create and enter the child project
cd -- "$RUN_DIR"
run_cmd agentcore create --name "$PROJECT_NAME" --skip-git
run_cmd cd -- "$PROJECT_NAME"

# Step 3: Register the complete harness configuration
run_cmd agentcore add harness --name "$HARNESS_NAME" \
  --model "$MODEL_JSON" --system-prompt "$SYSTEM_PROMPT" --tools "$TOOLS_JSON" \
  --authorizer-type AWS_IAM

# Step 4: Deploy from the registered project
run_cmd agentcore deploy --region "$REGION"

# Step 5: Invoke the deployed harness
run_cmd agentcore invoke --harness "$HARNESS_NAME" --region "$REGION" \
  --prompt 'Hello, this is a test invocation to verify deployment.'

if [ "$EXECUTE" = "--execute" ]; then
    echo "Deployment and test invocation completed."
else
    echo "Dry run only; no project was created or deployed."
fi
echo "For later updates, enter $RUN_DIR/$PROJECT_NAME."
echo "Edit app/$HARNESS_NAME/harness.yaml, then run agentcore deploy --region $REGION."
echo "View logs: agentcore logs harness --name $HARNESS_NAME --region $REGION"
```

**Artifact 3: `ai-migration/incremental_migration.sh`** (only if `harness_config.incremental_migration == true`)

Generate a **manual plan**, not commands claiming per-invocation model overrides. CLI 1.0.1 `invoke` has no `--model-id`, `--model-provider`, or `--api-key-arn` flags.

1. Enter the project created by `deploy_harness.sh`.
2. Configure the source provider's credential through AgentCore Identity using the current official CLI documentation. Do not embed API keys in the script or command output.
3. Update `app/<harness_name>/harness.yaml` to the source provider's model configuration and credential reference; run `agentcore deploy --region <region>`.
4. Test with `agentcore invoke --harness <harness_name> --prompt "Your test prompt" --region <region>`.
5. Replace the model configuration with `bedrockModelConfig: {modelId: <target_model_id>}`, deploy again, and repeat the same test prompts. Do not promise session/context preservation across model changes without verifying it.
6. Remove the source credential only after the user validates the Bedrock cutover and its rollback plan.

If retaining the filename `incremental_migration.sh`, it must only print these instructions; it must not perform credential operations, deployments, or invocations automatically.

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
def create_{agent_name}():
    return Agent(
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
    response = create_{specialist_var}()(query)
    return str(response)

def invoke(prompt: str) -> str:
    orchestrator = Agent(
        name="orchestrator",
        model=model,
        tools=[{specialist_tool_1}, {specialist_tool_2}, ...]
    )
    return str(orchestrator(prompt))
```

- **`swarm`** (collaborative):

```python
from strands.multiagent import Swarm

def invoke(prompt: str) -> str:
    team = Swarm([create_{agent_1}(), create_{agent_2}(), create_{agent_3}()])
    return str(team(prompt))
```

- **`graph`** (deterministic workflow):

```python
from strands.multiagent import GraphBuilder

def invoke(prompt: str) -> str:
    builder = GraphBuilder()
    builder.add_node(create_{agent_1}(), "{node_1_name}")
    builder.add_node(create_{agent_2}(), "{node_2_name}")
    builder.add_edge("{node_1_name}", "{node_2_name}")  # Add conditions if detected
    builder.set_entry_point("{entry_node}")
    workflow = builder.build()
    return str(workflow(prompt))
```

- **`single_agent`**: Export `def invoke(prompt: str) -> str: return str(create_<generated_agent_name>()(prompt))` alongside the Agent definition (no multi-agent orchestration).

Use actual agent IDs, model IDs, tool names, and system prompts from the design config. Mark TODOs only where implementation details can't be extracted from discovery.

Export the selected orchestration through `invoke(prompt)` without invoking a model at import time. Construct fresh agents and orchestration state per invocation so unrelated runtime requests do not share conversation history; session persistence requires a separately designed session store. Preserve migrated local tool modules and their dependencies; unresolved tool implementations must be completed before deployment.

**Runtime files: `ai-migration/main.py` and `ai-migration/pyproject.toml`**

The runtime serves the generated code, not the CLI's sample agent. Generate this entrypoint alongside `strands_agents.py`:

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands_agents import invoke

app = BedrockAgentCoreApp()

@app.entrypoint
def handle(payload):
    return {"result": invoke(payload["prompt"])}

if __name__ == "__main__":
    app.run()
```

Generate a project manifest, adding any dependencies required by the migrated tool code:

```toml
[project]
name = "migrated-strands-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["bedrock-agentcore", "aws-opentelemetry-distro", "strands-agents", "strands-agents-tools", "boto3"]

[tool.agentcore]
entrypoint = "main.py"
```

**Artifact 2: `ai-migration/deploy_strands.sh`**

Generate a first-deployment script. `add runtime` registers a Python HTTP runtime but does not generate its implementation. Copy the generated entrypoint, agent code and manifest into that runtime's directory before deployment. Add explicit copy commands for any additional migrated local modules. Dry-run must not create directories, install packages or call AWS. The SDK serves inside AgentCore's managed runtime; retain AWS IAM invocation authentication and do not publish its container port directly.

```bash
#!/bin/bash
set -euo pipefail

EXECUTE=${1:-""}
RUN_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_NAME="{agent_id}_strands"
RUNTIME_NAME="{agent_id}"
REGION="{target_region}"

run_cmd() {
    if [ "$EXECUTE" = "--execute" ]; then
        "$@"
    else
        printf '[DRY-RUN] '
        printf '%q ' "$@"
        printf '\n'
    fi
}

# Step 1: Install the CLI; runtime dependencies come from pyproject.toml
run_cmd npm install -g @aws/agentcore

# Step 2: Create and enter the child project
cd -- "$RUN_DIR"
run_cmd agentcore create --name "$PROJECT_NAME" --skip-git
run_cmd cd -- "$PROJECT_NAME"

# Step 3: Register and populate the runtime
run_cmd agentcore add runtime --name "$RUNTIME_NAME" --language python --protocol HTTP --authorizer-type AWS_IAM
run_cmd cp -- "$RUN_DIR/main.py" "$RUN_DIR/strands_agents.py" \
  "$RUN_DIR/pyproject.toml" "app/$RUNTIME_NAME/"

# Step 4: Build and deploy the registered runtime
run_cmd agentcore deploy --region "$REGION"

# Step 5: Send the JSON payload handled by main.py
run_cmd agentcore invoke --runtime "$RUNTIME_NAME" --region "$REGION" \
  --payload '{"prompt":"Hello, test invocation"}'

if [ "$EXECUTE" = "--execute" ]; then
    echo "Deployment and test invocation completed."
else
    echo "Dry run only; no project was created or deployed."
fi
echo "For later updates, enter $RUN_DIR/$PROJECT_NAME and update app/$RUNTIME_NAME/."
echo "Deploy: agentcore deploy --region $REGION"
echo "Monitor: agentcore logs runtime --name $RUNTIME_NAME --region $REGION"
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

Budget and anomaly monitoring apply to every path. **Application inference profiles are conditional:** omit the profile resource and its output for Mantle targets, including Astra, and for any model/API without documented support. Astra supports application inference profiles only on runtime Converse, not on runtime Chat/Responses. An unsupported profile must not prevent the applicable budget/anomaly resources from being emitted.

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
# AGENT: omit this resource and its output for Mantle or any unsupported model/API.
# Tags on these profiles appear in Cost Explorer; tags on API calls do not.
# copy_from must be a full foundation-model ARN or cross-region inference profile ARN.
# For Claude models, use the cross-region inference profile ARN format:
#   arn:aws:bedrock:{region}:{account_id}:inference-profile/us.anthropic.claude-sonnet-5
# For Amazon Nova models, use:
#   arn:aws:bedrock:{region}:{account_id}:inference-profile/us.amazon.nova-pro-v1:0
# [AGENT: generate one block per eligible runtime model/API in the saved design]
resource "aws_bedrock_inference_profile" "primary" {
  name = "${var.project_name}-${var.environment}-primary"

  model_source {
    copy_from = "{verified_model_source_arn}"
    # AGENT: use the exact foundation-model or CRIS ARN resolved for this model/API.
    # Preserve the chosen profile's geography; never manufacture a "us." prefix
    # or replace a validated global profile with a regional one.
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
