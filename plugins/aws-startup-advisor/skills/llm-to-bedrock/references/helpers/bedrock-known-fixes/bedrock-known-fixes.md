# Bedrock Known Fixes — Index

This skill is an **index**. Each fix below points to a single reference file. **Only read a reference file when its "When" condition exactly matches your current task** — do not read all references up front. The "When" condition is intentionally specific so you can rule out fixes that don't apply.

> **Important:** Apply fixes silently. Do not paste reference-file content back into the conversation; cite a fix by slug if you need to reference one (e.g., "applying `bedrock-response-key-casing`").

## Fixes

- **bedrock-vision** — Bedrock vision service replacing Gemini/other vision API
  - When: rewriting a Python service that calls a non-Bedrock vision API (Gemini `generate_content` with image, OpenAI `gpt-4-vision`, etc.) AND user-uploaded images flow through it. Skip if the existing code already calls `bedrock_runtime.invoke_model` for vision.
  - File: `references/bedrock-vision.md`

- **bedrock-response-key-casing** — boto3 returns `body` (lowercase), code often uses `Body`
  - When: a Python file calls `bedrock_runtime.invoke_model()` or `bedrock_client.invoke_model()` AND accesses the response body with `response["Body"]` (uppercase) or `response['Body']`. Verify with `grep -rn 'response\[.Body.\]'` first.
  - File: `references/bedrock-response-key-casing.md`

- **bedrock-iam-inference-profile** — IAM policy must include both foundation-model AND inference-profile ARN patterns
  - When: (a) writing the Bedrock IAM policy in Terraform and the model ID starts with `us.`/`eu.`/`apac.` (cross-region inference profile prefix), OR (b) seeing `AccessDeniedException` at runtime with message containing `inference-profile`.
  - File: `references/bedrock-iam-inference-profile.md`

- **bedrock-inference-profile-model-id** — Newer Claude models (Haiku 4.5, Sonnet 4.5+, Opus 4+) require the `us.` cross-region inference profile prefix
  - When: getting exact error `ValidationException: Invocation of model ID <id> with on-demand throughput isn't supported. Retry your request with the ID or ARN of an inference profile`.
  - File: `references/bedrock-inference-profile-model-id.md`
