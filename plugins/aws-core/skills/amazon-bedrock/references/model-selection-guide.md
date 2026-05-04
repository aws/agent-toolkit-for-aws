# Model Selection Guide

## Table of Contents

- Model ID Formats
- Model Access Provisioning
- Selection Criteria
- Embedding Models for Knowledge Bases
- Pricing Models

## Model ID Formats

Agents consistently get these wrong. Four patterns:

| Access Type | Format | Example Pattern |
|------------|--------|---------|
| On-demand (single region) | `provider.model-name-version` | `anthropic.claude-<model>-<date>-v<N>:0` |
| Cross-region (system-defined) | `geographic-prefix.provider.model-name-version` | `us.anthropic.claude-<model>-<date>-v<N>:0` |
| Application inference profile | ARN | `arn:aws:bedrock:<region>:<account-id>:inference-profile/<id>` |
| Provisioned throughput | ARN | `arn:aws:bedrock:<region>:<account-id>:provisioned-model/<id>` |

Always look up current model IDs: `aws bedrock list-foundation-models --region <region>` and `aws bedrock list-inference-profiles --region <region>`, or refer to the latest [Bedrock supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html).

**Critical**: Some models do not support on-demand invocation with base model IDs and require an inference profile ID instead. Before using a model, check `aws bedrock list-inference-profiles --region <region>` — if an inference profile exists for the model, use the inference profile ID. If you get `ValidationException: on-demand throughput isn't supported`, switch to the inference profile ID.

## Model Access Provisioning

Most serverless models are automatically available without manual enablement. Use IAM policies and SCPs to control which models can be used.

**What still requires action:**

- **Anthropic models**: Enabled by default but require a one-time usage form submission before first use (via Bedrock console playground or `PutUseCaseForModelAccess` API). For AWS Organizations, submitting via API at the management account level extends approval to child accounts.
- **Third-party Marketplace models**: A subset of models require AWS Marketplace subscription, which is created automatically on first invocation if the caller has `aws-marketplace:Subscribe` permission.
- **EULAs**: Some models still require EULA acceptance. Review EULAs at the [model card in Model Catalog](https://console.aws.amazon.com/bedrock/) or the [Bedrock third-party model terms](https://aws.amazon.com/legal/bedrock/third-party-models/).

**Access control**: Use IAM policies (`bedrock:InvokeModel` scoped to specific resource ARNs) and SCPs to control which models can be used. Use `bedrock:ListFoundationModels` for listing models and `bedrock:GetFoundationModel` for getting details about a specific model. The IAM Resource ARN format depends on the model ID type:

- Inference profile ID → `arn:aws:bedrock:<region>:<account-id>:inference-profile/<profile-id>`
- Base model ID → `arn:aws:bedrock:<region>::foundation-model/``<model-id>```
- These are different ARN formats and are not interchangeable. See [Bedrock IAM resource types](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrock.html#amazonbedrock-resources-for-iam-policies)
- For least-privilege policies scoped to specific inference profiles, you MUST include BOTH the inference profile ARN (`arn:aws:bedrock:<region>:<account-id>:inference-profile/<profile-id>`) AND the foundation model ARN with a wildcard region (`arn:aws:bedrock:*::foundation-model/<model-id>`), because the request may be routed to any region in the profile -- otherwise `bedrock:InvokeModel` calls fail with `AccessDeniedException`. See [Prerequisites for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html)

**INVALID_PAYMENT_INSTRUMENT error:**
Some AWS accounts (especially Organizations with European billing/SEPA) get this error when subscribing to Marketplace models. This is an account billing issue, not a Bedrock issue.

- Workaround: temporarily set a VISA/credit card as default payment method
- Alternative: per AWS re:Post user reports, adding USD payment profiles in the organization management account (Billing → Payment Preferences → Payment profiles) for service providers ending with "- Marketplace" may resolve the issue
- Contact AWS Support if the issue persists

## Selection Criteria

List models with capabilities: `aws bedrock list-foundation-models --region <region>`

Quick defaults (verify current availability — new models are added frequently, check `aws bedrock list-foundation-models --region <region>` or the [Bedrock supported models page](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html)):

- **General purpose / reasoning**: Claude Sonnet
- **Fast + cheap**: Claude Haiku or Nova Micro
- **Open-source / fine-tuning**: Llama
- **Multilingual**: Cohere Command or Claude
- **Code generation**: Claude Sonnet or Llama

Decision framework — choose based on:

| Criterion | What to Check |
|-----------|--------------|
| Reasoning depth | Claude Opus/Sonnet for complex tasks, Haiku/Nova for simple |
| Cost sensitivity | Nova Micro or Haiku for lowest cost; batch inference for discounted bulk processing |
| Multimodal needs | Nova Pro/Lite for text + image + video; Claude Sonnet for text + image |
| Open-source requirement | Llama (fine-tuning available) |
| Latency sensitivity | Haiku or Nova Micro for fastest inference |
| Context window | Check: `aws bedrock get-foundation-model --model-identifier``<model-id>``` |

## Embedding Models for Knowledge Bases

This is a non-obvious choice that affects KB quality. The table below shows common options — additional embedding models (including multimodal embeddings) are available. Check `aws bedrock list-foundation-models --by-output-modality EMBEDDING --region <region>` for the current list.

| Model | Dimensions | Best For |
|-------|-----------|----------|
| Titan Embeddings V2 | 1024 (configurable) | Default choice, good multilingual support |
| Cohere Embed | 1024 | Strong multilingual, 100+ languages |

**Critical**: The embedding model dimensions MUST match the vector store index dimensions. Mismatched dimensions cause ingestion failure.

Refer to the latest AWS documentation on Bedrock embedding models for current options.

## Pricing Models

| Model | Description | When to Use |
|-------|-------------|-------------|
| On-demand | Pay per input/output token | Default, unpredictable traffic |
| Batch inference | Discounted async processing | Bulk processing, not real-time |
| Provisioned throughput | Reserved capacity, predictable pricing | High-volume, predictable workloads |
| Cross-region inference | Broader availability via geographic routing (uses on-demand pricing). Geographic profiles (`us.`, `eu.`, `apac.`) stay within their geography; `global.` profiles route across all commercial regions | Traffic distribution; use geographic profiles when data residency matters |
| Service tiers (on-demand) | Priority (fastest, premium price) / Standard (default) / Flex (discounted, may queue) | Match latency and cost to workload needs |
| Reserved tier | Dedicated capacity reservation (1 or 3 month commitment, 99.5% uptime target) | Mission-critical apps that cannot tolerate downtime |

Refer to the latest AWS documentation on Bedrock pricing for current rates and discount percentages. Pricing changes without notice — do not hardcode pricing assumptions.
