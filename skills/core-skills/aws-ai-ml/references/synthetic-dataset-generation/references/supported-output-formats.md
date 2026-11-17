# Supported Output Formats

The synthetic dataset generation platform validates generated data against **9 distinct LLM training formats** using a format detector. Output that doesn't match any supported format is classified as `Custom`.

**Important:** `Custom` format is valid for hub finalization — datasets with `Custom` format are stored and accessible normally. However, `Custom` datasets are not directly compatible with format-specific fine-tuning pipelines (SFT, DPO, RLVR, etc.) without a transformation step.

**The 9 LLM training formats:**

1. Bedrock_Converse (has SFT and DPO variants — both are the same format)
2. Nova_CPT
3. Nova_PPO
4. HF_Prompt_Completion
5. HF_Preference
6. Verl
7. OpenAI_Messages
8. SageMaker_Eval
9. Nova_RLVR

## Format Selection Guide

| Fine-Tuning Technique | Model Family | Recommended Format |
|---|---|---|
| SFT | Nova / Bedrock models | Bedrock_Converse |
| SFT | Open-source / HuggingFace | HF_Prompt_Completion |
| SFT | OpenAI-compatible / GPT-OSS | OpenAI_Messages |
| DPO | Nova / Bedrock models | Bedrock_Converse (DPO variant with candidates) |
| DPO | Open-source / HuggingFace | HF_Preference |
| CPT (continued pre-training) | Nova | Nova_CPT |
| RLHF / PPO | Nova | Nova_PPO |
| RLVR | Nova | Nova_RLVR |
| RLVR | Open-source / Verl | Verl |
| Evaluation | SageMaker eval pipelines | SageMaker_Eval |

## Format Schemas

### 1. Bedrock_Converse

Allowed top-level keys: `messages`, `schemaVersion`, `system`, `toolConfig` — **no other keys allowed**. This is one format with two variants (SFT and DPO).

**SFT variant:**

```json
{
  "messages": [
    {
      "role": "user",
      "content": [{"text": "User message here"}]
    },
    {
      "role": "assistant",
      "content": [{"text": "Assistant response here"}]
    }
  ]
}
```

**Critical:** `content` must be an **array of objects**, not a plain string. Each content item must contain one of: `text`, `image`, `video`, `document`, `toolUse`, `toolResult`, `reasoningContent`. Roles must be `user` or `assistant`. Minimum 2 messages.

**DPO variant:**

Same structure, but the last assistant message uses `candidates` with `preferenceLabel`:

```json
{
  "messages": [
    {
      "role": "user",
      "content": [{"text": "User message here"}]
    },
    {
      "role": "assistant",
      "candidates": [
        {
          "content": [{"text": "Preferred response"}],
          "preferenceLabel": "preferred"
        },
        {
          "content": [{"text": "Non-preferred response"}],
          "preferenceLabel": "non-preferred"
        }
      ]
    }
  ]
}
```

### 2. Nova_CPT

For continued pre-training. Only `text` key allowed — **no other keys**. Must be a string.

```json
{"text": "Document text for continued pre-training. Can be any length."}
```

**Critical:** The record must contain exactly one key (`text`) with a string value. No metadata, no additional fields.

### 3. Nova_PPO

Required keys: `turns`, `turns_to_mask`, `reward_category`. Optional: `meta_data`. **No other keys allowed.**

```json
{
  "turns": ["User: What is 2+2?", "Bot: 4"],
  "turns_to_mask": [0],
  "reward_category": "math"
}
```

`reward_category` must be one of: `default`, `math`, `coding`, `if`, `rag`, `rai`. Each turn must start with `User:` or `Bot:`.

### 4. HF_Prompt_Completion

Requires `prompt` and `completion`. Must NOT have `chosen` or `rejected` (otherwise it becomes ambiguous). Extra keys are allowed.

String variant:

```json
{
  "prompt": "Classify the sentiment: Great product!",
  "completion": "positive"
}
```

Conversational variant (not for SFT training sets; see below):

```json
{
  "prompt": [{"role": "user", "content": "Classify the sentiment: Great product!"}],
  "completion": [{"role": "assistant", "content": "positive"}]
}
```

Each value can be a plain string or a message array (`[{role, content}]`). An SFT training set uses the string variant (SFT in `dataset-quality/references/strategy_data_requirements.md`).

### 5. HF_Preference

Requires `chosen` and `rejected`. Extra keys are allowed.

```json
{
  "chosen": "The sky is blue because of Rayleigh scattering.",
  "rejected": "The sky is blue because it reflects the ocean."
}
```

Each value can be a plain string or a message array (`[{role, content}]`).

### 6. Verl

Requires `prompt`. Must NOT have `completion`, `chosen`, or `rejected`. Extra keys are allowed.

```json
{
  "prompt": [
    {"role": "system", "content": "You are a helpful math tutor."},
    {"role": "user", "content": "What is 2+2?"}
  ],
  "extra_info": {"answer": "4"}
}
```

### 7. OpenAI_Messages

Only `messages` key allowed — **no other keys**. Messages use `role` + string `content` (not an array like Bedrock_Converse). Roles: `user`, `assistant`, `system`. Must have at least one `assistant` message.

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": "The capital of France is Paris."}
  ]
}
```

**Critical:** `content` must be a **plain string**, not an array of objects. This is what distinguishes it from Bedrock_Converse. The `system` role is allowed here but not in Bedrock_Converse.

### 8. SageMaker_Eval

Required keys: `query`, `response` (both strings). Optional: `system`, `category`. **No other keys allowed.**

```json
{
  "query": "What are the benefits of cloud computing?",
  "response": "Cloud computing offers scalability, cost efficiency, and flexibility..."
}
```

With optional fields:

```json
{
  "query": "Explain quantum entanglement.",
  "response": "Quantum entanglement is a phenomenon where...",
  "system": "You are a physics professor.",
  "category": "science"
}
```

### 9. Nova_RLVR

Required keys: `messages`, `reference_answer`. **No other keys allowed.** Messages use the same shape as OpenAI_Messages (role + string content). `reference_answer` must be a dict.

```json
{
  "messages": [
    {"role": "user", "content": "What is 15 * 23?"}
  ],
  "reference_answer": {"answer": "345", "reasoning": "15 * 23 = 15 * 20 + 15 * 3 = 300 + 45 = 345"}
}
```

**Critical:** `reference_answer` must be a **dict** (object), not a string. The `messages` array uses string content (same as OpenAI_Messages format).

## Validation Rules Summary

- Format detection runs against **all records** — every record must pass the same validator
- If records match **zero** or **multiple** formats, the dataset is classified as `Custom` (not usable for format-specific fine-tuning without transformation)
- **Strict key formats** (Bedrock_Converse, Nova_CPT, Nova_PPO, OpenAI_Messages, SageMaker_Eval, Nova_RLVR): Extra top-level keys beyond the allowed set will fail validation. The final output record must contain only the keys the format allows.
- **Flexible key formats** (HF_Prompt_Completion, HF_Preference, Verl): Extra keys are allowed — only the required keys are checked. Additional metadata fields (e.g., `product_category`, `review_length`) can be included in the output.
- **Ambiguity trap**: A record with both `prompt`+`completion` AND `chosen`+`rejected` could match multiple formats → classified as `Custom`. Avoid mixing keys from different formats.

## Tabular / Custom Format

Tabular data generation (CSV row augmentation, schema-based synthetic records, multi-relational datasets) produces `Custom` format output. This is **by design** — tabular rows are not LLM training data and don't conform to any of the 9 formats above.

**What this means:**

- Hub finalization succeeds with `Custom` format
- The dataset is stored and accessible via `DescribeHubContent`
- To use this data for ML training, a transformation step (via the dataset-transformation skill) converts it to the target format

**Supported delivery formats for tabular:**

| Format | How to request | Output |
|--------|---------------|--------|
| CSV (default) | "in CSV format" or no format specified | `output_samples.csv` (single-table) or `{table}.csv` per table (multi) + `dataset_schema.json` |
| Parquet | "Output as parquet" in the spec/task description | `{table}.parquet` per table + CSVs retained + `dataset_schema.json` |
| SQLite | "Output as sqlite" in the spec/task description | `output_samples.sqlite` (all tables with FK constraints) + CSVs retained + `dataset_schema.json` |

The platform detects the target format from the **task description** (your original prompt to the synthetic dataset generation service). The modality classifier runs an LLM call at temperature=0 that infers modality, format, and schema type. Parquet and SQLite are converted from streaming CSVs at job completion.

**Supported seed data formats (CDG input):**

- `.csv` — parsed directly
- `.parquet` — schema inferred from column metadata
- `.sqlite` / `.db` — each table extracted as CSV
- `.json` / `.jsonl` — each record becomes a row

**Multi-relational support:**

- Single job can generate multiple related tables (e.g., customers + orders)
- Foreign-key integrity is maintained across tables
- Foreign-key, primary-key, and NOT NULL constraints are validated automatically
- Output contains one CSV per table (e.g., `customers.csv`, `orders.csv`)

**Spec guidance for tabular generation:**

- State "Output as parquet" or "Output as sqlite" in the Overall Goal for non-CSV formats
- For multi-relational: describe all tables and their FK relationships in one spec
- `generator` produces one record (or one parent+children group) per call
- `verify_sample` checks structure — field count, types, ranges (per row, not cross-table)
- See `references/sample-spec-tabular-augmentation.md` for working templates
