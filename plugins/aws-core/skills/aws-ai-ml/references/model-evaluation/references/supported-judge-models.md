# Supported Judge Models

Reference: [Amazon Bedrock LLM-as-Judge Evaluation](https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-judge.html)

## Allowed Judge Models

The SageMaker Python SDK is the source of truth for which judge models are allowed: when you submit the evaluation job, the SDK validates the judge model and, if it is not supported, raises an error that lists the currently accepted models (and their allowed regions). The table below is a convenience reference that may lag the SDK — do not treat it as exhaustive; rely on the SDK's submit-time validation to confirm a given model is accepted:

| Model                          | Model ID                                    | Regions                                         |
| ------------------------------ | ------------------------------------------- | ----------------------------------------------- |
| Amazon Nova Pro                | `amazon.nova-pro-v1:0`                      | us-east-1                                       |
| Anthropic Claude 3.5 Sonnet v1 | `anthropic.claude-3-5-sonnet-20240620-v1:0` | us-west-2, us-east-1, ap-northeast-1            |
| Anthropic Claude 3.5 Sonnet v2 | `anthropic.claude-3-5-sonnet-20241022-v2:0` | us-west-2                                       |
| Anthropic Claude 3 Haiku       | `anthropic.claude-3-haiku-20240307-v1:0`    | us-west-2, us-east-1, ap-northeast-1, eu-west-1 |
| Anthropic Claude 3.5 Haiku     | `anthropic.claude-3-5-haiku-20241022-v1:0`  | us-west-2                                       |
| Meta Llama 3.1 70B Instruct    | `meta.llama3-1-70b-instruct-v1:0`           | us-west-2                                       |
| Mistral Large                  | `mistral.mistral-large-2402-v1:0`           | us-west-2, us-east-1, eu-west-1                 |

This list applies to both built-in and custom metrics — the SDK does not distinguish between them.

Source: derived from the SageMaker SDK's internal evaluator allowlist (sagemaker SDK v3). This is an SDK internal — do not import or reference it in generated code; the SDK enforces the allowlist itself at job-submission time.

## Selection Guidance

Verify each candidate is active in the user's region. Run `aws bedrock get-foundation-model --model-identifier <model-id> --region <region>` and extract `modelDetails.modelLifecycle.status` from the response.

Only include models that return `ACTIVE`. Models marked `LEGACY` will fail at evaluation time.

Present all active models to the user and let them choose. **NEVER recommend or suggest any particular model.** Only display the list. If the user asks for guidance, you may share these general trade-offs so they can decide:

- Cost vs quality: Smaller models are faster and cheaper; larger models produce higher-quality judgments
- Task complexity: Simple tasks (QA, classification) may not need the most capable model; complex reasoning (math, multi-step) benefits from stronger models
