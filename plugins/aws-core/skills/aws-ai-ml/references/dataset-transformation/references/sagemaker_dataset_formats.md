# SageMaker Supported Dataset Formats (Offline Fallback)

This is an offline copy of the supported dataset formats from:
https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html

**Note:** Always attempt to fetch the live documentation first. Only use this file as a fallback when internet access is unavailable (e.g., VPC environments).

## Required Fields

| Field         | Required               |
| ------------- | ---------------------- |
| User Prompt   | Yes                    |
| System Prompt | No                     |
| Ground truth  | Only for Custom Scorer |
| Category      | No                     |

## 1. OpenAI Format

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello!"
    },
    {
      "role": "assistant",
      "content": "Hello to you!"
    }
  ]
}

```

- `system` role is optional (system prompt)
- `user` role is the query
- `assistant` role is the ground truth

## 2. SageMaker Evaluation Format

```json
{
  "system": "You are an English major with top marks in class who likes to give minimal word responses: ",
  "query": "What is the symbol that ends the sentence as a question",
  "response": "?",
  "category": "Grammar"
}

```

- `system` and `category` are optional
- `response` is the ground truth

## 3. HuggingFace Prompt Completion Format

### Standard

```json
{
  "prompt": "What is the symbol that ends the sentence as a question",
  "completion": "?"
}

```

### Conversational

```json
{
  "prompt": [
    { "role": "user", "content": "What is the symbol that ends the sentence as a question" }
  ],
  "completion": [
    { "role": "assistant", "content": "?" }
  ]
}

```

- `completion` is the ground truth

## 4. HuggingFace Preference Format

### Standard

```json
{
  "prompt": "The sky is",
  "chosen": "blue",
  "rejected": "green"
}

```

### Conversational

```json
{
  "prompt": [
    { "role": "user", "content": "What color is the sky?" }
  ],
  "chosen": [
    { "role": "assistant", "content": "It is blue." }
  ],
  "rejected": [
    { "role": "assistant", "content": "It is green." }
  ]
}

```

- `chosen` is the ground truth

## 5. Verl Format

### Current (prompt as messages array)

```json
{
  "data_source": "openai/gsm8k",
  "prompt": [
    { "content": "You are a helpful math tutor.", "role": "system" },
    { "content": "What is 2+2?", "role": "user" }
  ],
  "ability": "math",
  "extra_info": {
    "answer": "4"
  },
  "reward_model": {
    "ground_truth": "4"
  }
}

```

### Legacy (prompt as string)

```json
{
  "data_source": "openai/gsm8k",
  "prompt": "What is 2+2?",
  "extra_info": {
    "answer": "4"
  }
}

```

- Ground truth via `extra_info.answer` (preferred) or `reward_model.ground_truth`
- Preserves metadata fields: `id`, `data_source`, `ability`, `reward_model`, `extra_info`, `attributes`, `difficulty`
