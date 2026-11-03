# Schema: preferences.json (AI-only)

Clarify phase output (`references/phases/clarify/clarify-ai-only.md`). Design, Estimate, and Generate read it once those phases exist in this skill.

---

## Wrapper object (required fields)

Every key in `design_constraints`, `ai_constraints`, and `startup_constraints` (when present) MUST be an object with:

| Field                | Type   | Required | Description                                                                                                                                                              |
| -------------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `value`              | any    | yes      | Interpreted constraint value                                                                                                                                             |
| `chosen_by`          | string | yes      | `"user"` \| `"default"` \| `"extracted"` \| `"derived"`                                                                                                                  |
| `prompt`             | string | yes      | Question shown to the user, or a short detection label when skipped                                                                                                      |
| `design_consequence` | string | yes      | One sentence: how this choice shaped the AWS design, estimate, or plan                                                                                                   |
| `question_id`        | string | no       | AI-only catalog ID (`Q1`–`Q11`, `Q1.5`) when mapped; omit for derived values                                                                                             |
| `source`             | string | no       | Raw provenance signal. Required when `chosen_by` is `"extracted"` (prefix `ai-profile:`) or `"default"` (`"default:<Qid>"`). Omit for `"user"` and `"derived"`. |

**Do not write null values.** Omit keys that produce no constraint.

### `prompt` by `chosen_by`

| `chosen_by` | `prompt` content                                                                         |
| ----------- | ---------------------------------------------------------------------------------------- |
| `user`      | Verbatim question text from `clarify-ai-only.md` (blockquote body, without answer options) |
| `extracted` | Detection label, e.g. `"Detected: gpt-4o (openai via openai_api, high confidence)"`      |
| `default`   | Question text + `" (default applied)"`                                                   |
| `derived`   | The specific derivation rule, e.g. `"Derived from compliance: gdpr → eu-west-1"`         |

### `design_consequence`

Use the **Impact** row for the selected answer from `clarify-ai-only.md` when the user answered. For extracted/default/derived, use the catalog below or synthesize one sentence tied to the actual `value`.

---

## Top-level shape

```json
{
  "metadata": {
    "migration_type": "ai-only",
    "clarify_mode": "full",
    "timestamp": "<ISO 8601>",
    "discovery_artifacts": ["ai-workload-profile.json"],
    "questions_asked": ["Q2"],
    "questions_defaulted": ["Q3"],
    "questions_extracted": ["Q5"],
    "report_caveats": ["Compliance requirements were not confirmed by the user"]
  },
  "design_constraints": {
    "<key>": {
      "value": "<answer or default>",
      "chosen_by": "user|default|extracted|derived",
      "prompt": "<question text shown>",
      "design_consequence": "<one line: what this decides>",
      "question_id": "<Qn — optional>",
      "source": "<provenance — optional>"
    }
  },
  "ai_constraints": {
    "<key>": {
      "value": "<answer or default>",
      "chosen_by": "user|default|extracted|derived",
      "prompt": "<question text shown>",
      "design_consequence": "<one line: what this decides>",
      "question_id": "<Qn — optional>",
      "source": "<provenance — optional>"
    }
  },
  "startup_constraints": {
    "<key>": {
      "value": "<answer or default>",
      "chosen_by": "user|default|extracted|derived",
      "prompt": "<question text shown>",
      "design_consequence": "<one line: what this decides>",
      "question_id": "<Qn — optional>",
      "source": "<provenance — optional>"
    }
  }
}
```

`metadata.report_caveats` is present only when a caveat was added (Q1.5 default).

---

## Constraint catalog (prompt + consequence templates)

| Key                      | Section               | `question_id` | Default `prompt` (user-asked)                                 | `design_consequence` template                                                                     |
| ------------------------ | --------------------- | ------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `target_region`          | `design_constraints`  | —             | Derived from compliance and cross-cloud answers               | Bedrock resources deploy in `[value]`; model availability is checked for this region              |
| `compliance`             | `design_constraints`  | Q1.5          | Do you have any compliance or regulatory requirements?        | `[value]` gates Bedrock models, regions, and logging. `["unknown"]` requires a report caveat      |
| `ai_framework`           | `ai_constraints`      | Q1            | Which AI framework or orchestration layer are you using?      | `[value]` determines migration effort (gateway config vs SDK swap vs agent framework migration)   |
| `ai_priority`            | `ai_constraints`      | Q2            | What matters most for your AI application?                    | `[value]` drives Bedrock model selection (quality vs cost vs latency)                             |
| `ai_monthly_spend`       | `ai_constraints`      | Q3            | Monthly AI spend on OpenAI or Gemini?                         | `[value]` band sets token volume and model tier assumptions                                       |
| `cross_cloud`            | `ai_constraints`      | Q4            | Cross-cloud API call concerns                                 | `[value]` selects endpoint type (public, VPC endpoint, PrivateLink) and rollout approach          |
| `ai_model_baseline`      | `ai_constraints`      | Q5            | Current model in use?                                         | `[value]` is the quality/latency baseline for Bedrock comparison                                  |
| `ai_vision`              | `ai_constraints`      | Q6            | What input types must the model accept?                       | `[value]` requires vision- or audio-capable Bedrock models when not text-only                     |
| `ai_token_volume`        | `ai_constraints`      | Q7            | Monthly AI usage volume                                       | `[value]` sets on-demand vs provisioned throughput and caching analysis                           |
| `ai_latency`             | `ai_constraints`      | Q8            | Response speed importance                                     | `[value]` adds latency success criteria and model filtering                                       |
| `ai_complexity`          | `ai_constraints`      | Q9            | AI task complexity                                            | `[value]` affects recommended model size and agentic path                                         |
| `ai_critical_feature`    | `ai_constraints`      | Q10           | Specialized features needed                                   | `[value]` gates the model shortlist and capability validation                                     |
| `startup_program_status` | `startup_constraints` | Q11           | Have you applied for AWS Activate credits?                    | `[value]` triggers the Activate credits callout in the plan                                       |

---

## Validation (Clarify Step 3 self-check)

Before marking Clarify complete:

1. Every written constraint has `value`, `chosen_by`, `prompt`, and `design_consequence`.
2. No empty strings for `prompt` or `design_consequence`.
3. `question_id` present when the constraint maps to a catalog question.
4. `source` present on every constraint where `chosen_by` is `"extracted"` or `"default"`. Omit for `"user"` and `"derived"`.
