# Finetuning Strategy Data Requirements

**File format: JSONL only.** Non-JSONL files (parquet, csv, etc.) require transformation regardless of schema match.

**Critical** Nova models have a different set of formats than open weights models. Make sure you refer to the right section based on the user's base model.

## Open Weights Models Data Format by Strategy (Llama, Qwen, GPT-OSS, etc.)

### SFT (Supervised Fine-Tuning)

**Required format:**

```jsonl
{
  "prompt": "",
  "completion": ""
}

```

**What it needs:**

- Input-output pairs
- Single "correct" response per input
- Consistent quality across examples

### DPO (Direct Preference Optimization)

**Required format:**

```jsonl
{
  "prompt": "",
  "chosen": "",
  "rejected": ""
}

```

**What it needs:**

- Input with two responses: preferred (chosen) and dispreferred (rejected)
- Clear preference signal between responses
- Both responses should be plausible but one is better
- Avoiding unintentional length bias

### RLVR (Reinforcement Learning from Verifiable Rewards)

**Required format:**

```jsonl
{
  "data_source": "",
  "prompt": [
    {
      "content": "",
      "role": ""
    }
  ],
  "ability": "",
  "reward_model": {
    "ground_truth": "",
    "style": ""
  }
}

```

**What it needs:**

- user prompt
- Ground truth responses in `reward_model.ground_truth` field (leave empty if user data does not have responses)

**How it works:**

1. Model generates response for input
2. Lambda receives full user prompt + reward model fields
3. Lambda computes reward (uses ground_truth if included in verification logic)
4. Model learns to maximize rewards

### RLAIF (Reinforcement Learning from AI Feedback)

RLAIF uses the same base schema as RLVR. The `ability` and `reward_model.style` fields determine which evaluator is used.

**Base schema:**

```jsonl
{
  "data_source": "",
  "prompt": [
    {
      "role": "",
      "content": ""
    }
  ],
  "ability": "",
  "reward_model": {
    "style": "",
    "ground_truth": ""
  }
}

```

#### Built-in Evaluators

| `ability` | `reward_model.style` | Use case |
|---|---|---|
| `pairwise-judging` | `llmj` | Compare two model responses and pick the better one |
| `chain-of-thought` | `llmj-cot` | Evaluate quality of step-by-step reasoning |
| `faithfulness` | `llmj-faithfulness` | Check if response stays grounded in provided context |
| `summarization` | `llmj-summarization` | Evaluate quality of a generated summary |

**`pairwise-judging` — prompt must include both responses to compare; `ground_truth` is the preferred response index + reasoning.**

**`chain-of-thought` / `faithfulness` / `summarization` — prompt contains the task; `ground_truth` is the reference answer or source text.**

#### Custom Evaluator

Set `reward_model.style` to `llmj-custom` and supply a Jinja2 prompt template. The template receives `{{ prompt }}`, `{{ response }}`, and optional `{{ ground_truth }}` as variables. The LLM judge must return a JSON object with a `score` field (0.0–1.0).

```jsonl
{
  "data_source": "",
  "prompt": [
    {
      "role": "user",
      "content": ""
    }
  ],
  "ability": "chain-of-thought",
  "reward_model": {
    "style": "llmj-custom",
    "ground_truth": ""
  }
}

```

The custom Jinja prompt is provided separately at training time (not embedded in the dataset). It must instruct the judge to return exactly: `{"score": <0.0-1.0>, ...}`.

---

## Nova Models Data Format by Strategy

### SFT (Supervised Fine-Tuning)

```jsonl
{
  "schemaVersion": "bedrock-conversation-2024",
  "system": [
    {
      "text": ""
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "text": ""
        }
      ]
    },
    {
      "role": "assistant",
      "content": [
        {
          "text": ""
        }
      ]
    }
  ]
}

```

### DPO (Direct Preference Optimization)

The format is the same as SFT for the first N-1 turns. The final assistant turn uses `candidates` with `preferenceLabel` instead of regular `content`.

```jsonl
{
  "schemaVersion": "bedrock-conversation-2024",
  "system": [
    {
      "text": ""
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "text": ""
        }
      ]
    },
    {
      "role": "assistant",
      "candidates": [
        {
          "content": [
            {
              "text": ""
            }
          ],
          "preferenceLabel": "preferred"
        },
        {
          "content": [
            {
              "text": ""
            }
          ],
          "preferenceLabel": "non-preferred"
        }
      ]
    }
  ]
}

```

### RLVR

```jsonl
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "reference_answer": {
    "answer": "49"
  }
}

```
