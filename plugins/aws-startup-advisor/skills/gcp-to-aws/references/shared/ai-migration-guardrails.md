# AI Migration Guardrails

Shared warnings and constraints for all agentic migration paths. Loaded once by `design-ai.md` when `agentic_profile.is_agentic == true`. Path-specific design references (Harness, Strands, retarget) should NOT duplicate these — reference this file instead.

---

## AgentCore Regional Availability

AgentCore services have different regional footprints. Always validate via `aws___get_regional_availability` from the AWS MCP Server before recommending.

**As of July 2026:**

| Service                | Availability           | Regions                                                                                                                                                                                         |
| ---------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AgentCore Runtime (GA) | All commercial regions | us-east-1, us-east-2, us-west-2, us-west-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, ap-northeast-2, ap-south-1, eu-central-1, eu-west-1, eu-west-2, eu-north-1, sa-east-1, ca-central-1 |
| AgentCore Harness (GA) | All commercial regions | Same as Runtime (GA June 2026)                                                                                                                                                                  |
| AgentCore Memory (GA)  | All commercial regions | Same as Runtime                                                                                                                                                                                 |
| AgentCore Gateway (GA) | All commercial regions | Same as Runtime                                                                                                                                                                                 |
| AgentCore Policy (GA)  | 13 regions             | us-east-1, us-east-2, us-west-2, us-west-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, ap-south-1, eu-central-1, eu-west-1, eu-west-2, eu-north-1, ca-central-1                            |

**IMPORTANT:** These lists go stale. The `aws___get_regional_availability` call (AWS MCP Server) is the source of truth. Use the table above only as a fallback if the call fails.

**If target region is unavailable for a recommended service:**

1. Flag prominently in `aws-design-ai.json` → `regional_warnings[]`
2. Suggest nearest available region as alternative
3. Note in user summary: "[Service] is not yet available in [target region]. Nearest available: [alternative]."

---

## Bedrock Mantle Throughput Limits

Bedrock Mantle serves OpenAI-compatible and Anthropic-compatible APIs on Bedrock.

### OpenAI proprietary models (GPT-5.6 / 5.5 / 5.4) — TPM only, no RPM

Inference on `bedrock-mantle` for these models is governed by **two per-model, per-region quotas: input tokens per minute and output tokens per minute. There is no requests-per-minute quota.** Exceeding a TPM quota returns HTTP 429. Cached input tokens read through prompt caching **do not count** against the input-TPM quota.

| Workload Volume | Risk Level | Guidance                                                                                           |
| --------------- | ---------- | -------------------------------------------------------------------------------------------------- |
| Low             | Low        | Default TPM quotas are ample                                                                       |
| Medium          | Medium     | Monitor 429s against **token** throughput, not request rate; enable prompt caching                 |
| High            | High       | Enable prompt caching first (cached input is exempt from input TPM), then request a quota increase |

**The `bedrock-runtime` fallback exists only for GPT-5.6.** GPT-5.5 and GPT-5.4 are `bedrock-mantle` only and in-region only — for them, "switch to `bedrock-runtime`" requires moving to a different model (Bedrock-native or `gpt-oss`), a model change with its own eval cost. GPT-5.6 Sol/Terra/Luna DO have a `bedrock-runtime` path via CRIS inference profiles (`us.`/`in.`/`global.` prefixed ids; the model cards recommend runtime for new applications) — a legitimate endpoint option with its own quota family, and on Global CRIS it is also the cost-parity option. Scaling levers on the mantle path, in order:

1. Prompt caching (GPT-5.6 only) — 90% off cached input and exempt from the input-TPM quota
2. Exponential backoff with a bounded retry count (`max_retries` on the OpenAI SDK)
3. Spreading load across minutes and ramping request rate gradually rather than bursting
4. A Service Quotas increase for that model's input/output TPM in that region
5. Only if the above are insufficient: change models, accepting the eval cost

See `references/shared/openai-on-bedrock.md` for the endpoint, region matrix, and caching parameters.

**Source:** [Get started with GPT-5.6 on Amazon Bedrock — Quotas and scaling](https://aws.amazon.com/blogs/machine-learning/get-started-with-openai-gpt-5-6-sol-terra-and-luna-on-amazon-bedrock/)

### Other models on Mantle

For non-OpenAI models served through Mantle, verify current quota dimensions and any shared-account limits in the [Mantle documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html) before advising on throughput. Do not carry the OpenAI TPM-only model over to other providers without checking, and do not assume previously documented shared-RPM behavior still applies.

---

## Bedrock Mantle TPM Limits (Claude Models)

Claude models on Mantle have an additional **output TPM cap** that differs by model generation:

| Model Family            | Output TPM Cap                | Notes                             |
| ----------------------- | ----------------------------- | --------------------------------- |
| Claude 4.7+             | 2,000,000 output TPM          | Per-model cap applies             |
| All other Claude models | No per-model output TPM limit | Standard account TPM limits apply |

**Impact for migration decisions:**

- For Claude migrations at medium/high volume: the 2M output TPM cap on Claude 4.7+ is the binding constraint
- For OpenAI proprietary GPT targets: this Claude cap does not apply. Their mantle constraint is the per-model input/output TPM quota described above; for GPT-5.6 the `bedrock-runtime`/CRIS path is an available alternative (its own quota family), while GPT-5.5/5.4 have no runtime path
- For `gpt-oss` targets: these do run on `bedrock-runtime`, so standard account TPM limits and the Converse-path mitigations apply
- When output-heavy workloads (long JSON, tool outputs, multi-step reasoning) are detected, flag the relevant cap prominently; recommend `bedrock-runtime` for production **only** when the target model actually has a `bedrock-runtime` path

---

## AgentCore Harness (GA)

- Harness is **generally available** (June 2026) in all commercial regions where AgentCore is available.
- No separate Harness charge — pay only for underlying AgentCore capabilities (Runtime, Memory, Gateway).
- Harness is powered by Strands Agents internally. Custom orchestration can switch from config-based to code-defined harness without rearchitecting (export to Strands-based code on the same platform).
- Harness supports Bedrock, OpenAI, and Google Gemini models. Third-party API keys stored in AgentCore Identity token vault.
- Model-agnostic and provider-switchable mid-session without losing context or touching agent logic.

## AgentCore Policy (GA)

- Policy is **generally available** (March 2026) in 13 regions.
- Provides centralized control over agent-tool interactions via natural language policies that compile to Cedar.
- Policies are stored in a policy engine attached to AgentCore Gateway. The gateway intercepts agent-tool traffic and evaluates each request before granting or denying access.
- Operates outside agent code — security, compliance, and operations teams can define access rules without modifying agent code.
- Recommend Policy when `agentic_profile.tools` contains write-capable tools (database writes, API mutations, file operations) or when the startup has compliance requirements.

---

## Model Lifecycle Checks

Before recommending any Bedrock model in an agentic design:

1. Check `references/shared/ai-model-lifecycle.md` for model status
2. Do NOT recommend Legacy models as primary selections
3. If a model is approaching EOL, note the date and suggest the Active successor

---

## Pricing Source Rules

For agentic workload cost estimation:

1. **Primary:** `references/shared/pricing-cache.md` (±5-10% accuracy)
2. **Fallback:** `references/shared/pricing-fallback.md` (cache-miss → `estimated`/`unavailable`)

AgentCore Runtime and Harness pricing: consumption-based, no upfront cost. Include in estimate only if the user selects Harness or Strands path.

---

## Effort Estimation Rules

Do NOT output fixed week estimates for agentic migrations. Output ranges with drivers:

**Format:** "[low]–[high] weeks depending on [driver 1] ([value]), [driver 2] ([value]), [driver 3] ([value])"

**Drivers to include:**

- Agent count (from `agentic_profile.agent_count`)
- Tool count (from `agentic_profile.tool_count`)
- Orchestration complexity (from `agentic_profile.orchestration_pattern`)
- Framework familiarity (team's experience with target framework)
- Test coverage (existing tests reduce migration risk)

**Example:** "2–5 weeks depending on agent count (3), tool count (8), and graph complexity (hierarchical with conditional routing)"
