# Schema — aws-design-ai.json (GCP)

> **Why this file exists.** `design-ai.md` produces `aws-design-ai.json`, and
> `estimate-ai.md` consumes it, so a prose-only contract drifts between the two by
> construction. This file is the single written contract for GCP's CURRENT
> `aws-design-ai.json` emission — the single-scalar `metadata.ai_source` shape
> `design-ai.md` writes today, not the shared `ai_sources[]`/`gateways[]` target shape in
> `skills/shared/ai/schema-design-aws-ai.md`. It is kept parallel to Azure's own shape doc
> at `skills/azure-to-aws/references/shared/schema-design-aws-ai.md` for the same reason:
> `scripts/artifact-contracts.json`'s `skills.gcp-to-aws.aws-design-ai.json` entry shadows
> the shared target-only schema with this file until `design-ai.md` is repointed.

`aws-design-ai.json` is written by `phases/design/design-ai.md` **only when
`ai-workload-profile.json` exists**.

## Shape

```jsonc
{
  "phase": "design",
  "focus": "ai",
  "timestamp": "<ISO 8601>",
  "source_profile": "ai-workload-profile.json",
  "metadata": {
    "ai_source": "gemini", // "gemini" | "openai" | "anthropic" | "both" | "other" — summary.ai_source from the profile
    "bedrock_models_selected": [], // aws_model_id strings chosen (Bedrock targets only)
    "regional_validation": "checked" // checked | fallback_static
  },
  "design_blocks": [], // one per workloads[] entry — see § design_blocks
  "ai_architecture": {}, // see design-ai.md Part 6 field table
  "regional_warnings": [], // ALWAYS present, [] when clean
  "multi_model_warnings": [], // ALWAYS present, [] when single model
  "agentic_design": null // present ONLY when agentic_profile.is_agentic
}
```

## design_blocks[]

One row per confirmed workload — see `design-ai.md` Part 6 field table.

```jsonc
{
  "workload_id": "wl_3a1f2c", // from the profile's workloads[]; preserve verbatim
  "model_id": "gemini-2.5-flash", // the source model the workload used
  "target_bedrock_model": "amazon.nova-lite-v1:0", // XOR target_aws_service
  "target_aws_service": null, // XOR target_bedrock_model
  "capability": "text_generation", // see § capability vocabulary
  "capability_confidence": "medium", // high | medium | low
  "rationale": "<one or two sentences a customer can read>",
  "confidence_warning": null // non-null string when capability_confidence == "low"
}
```

- **`target_bedrock_model` XOR `target_aws_service` — exactly one is non-null per row.**
  Bedrock-model capabilities (`text_generation`, `structured_output`, `image_generation`,
  `embedding`, `speech_to_text`, `text_to_speech`, `unknown`) set `target_bedrock_model` and
  leave `target_aws_service` null. The three traditional-AI capabilities
  (`document_extraction`, `image_analysis`, `speech_transcription`) set `target_aws_service`
  (one of `"textract"`, `"rekognition"`, `"transcribe"`) and leave `target_bedrock_model` null.
- **`confidence_warning`** is a non-null string when `capability_confidence == "low"`; null
  for `high`/`medium`.
- **Input order preserved:** `design_blocks[]` order matches the profile's `workloads[]` order.

## capability vocabulary

Bedrock-model capabilities: `text_generation`, `structured_output`, `image_generation`,
`embedding`, `speech_to_text`, `text_to_speech`, `unknown`.
Traditional-AI capabilities (AWS AI service, not Bedrock): `document_extraction`,
`image_analysis`, `speech_transcription`.

## Validation Checklist

- [ ] `metadata.ai_source` matches `summary.ai_source` from `ai-workload-profile.json`.
- [ ] Every `design_blocks[]` row has exactly one of `target_bedrock_model` /
      `target_aws_service` non-null (XOR).
- [ ] Every traditional-AI row (`document_extraction`/`image_analysis`/`speech_transcription`)
      has `target_bedrock_model: null` and a non-null `target_aws_service`.
- [ ] `confidence_warning` is non-null only when `capability_confidence == "low"`.

## Status — GCP's current emission contract

This file documents GCP's CURRENT scalar `aws-design-ai.json` emission as-is, the same role
`skills/azure-to-aws/references/shared/schema-design-aws-ai.md` plays for Azure.
`scripts/artifact-contracts.json`'s `skills.gcp-to-aws.aws-design-ai.json` entry shadows the
shared `json_schema` entry with this file's `Shape` block for exactly this reason: GCP's
actual runtime output has not changed. The shared, many-valued `ai_sources[]`/`gateways[]`
contract at `skills/shared/ai/schema-design-aws-ai.md` is the TARGET shape — repointing
`design-ai.md` to emit it is deferred runtime-adoption work, not done by this file.
