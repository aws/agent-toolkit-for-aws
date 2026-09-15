# Custom Scorer Evaluation Dataset Formats

Dataset format requirements for evaluation datasets used with the Custom Scorer pathway. Note that these are distinct from any requirements for training dataset formats — they are specifically for datasets scored by Prime Math, Prime Code, or a Custom Lambda during model evaluation.

## Format by scorer type

### Prime Math

Evaluates mathematical reasoning by comparing model output to a ground truth answer using symbolic equality.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | The math problem |
| `response` | string | yes | The ground truth answer |

**Example:**

```jsonl
{"query": "What is 15 + 27?", "response": "42"}
{"query": "What is the square root of 81?", "response": "9"}
{"query": "Solve for x: 2x + 6 = 20", "response": "7"}

```

**Notes:**

- The scorer uses sympy for symbolic comparison and extracts answers from `\boxed{}`, text after "is", "=", "answer:", etc.
- `response` should be just the answer value (e.g., "42"), not a full explanation. The scorer compares this against what it extracts from the model's output.

---

### Prime Code

Evaluates code generation by executing the model's output against test cases (stdin → stdout).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | The coding problem description |
| `response` | string | yes | Reference solution code (used for text metrics like ROUGE/BLEU) |
| `metadata` | object | yes | Test cases: `{"inputs": [...], "outputs": [...]}` |

**Example:**

```jsonl
{"query": "Write a program that reads an integer and prints its double.", "response": "n = int(input())\nprint(n * 2)", "metadata": {"inputs": ["5", "3", "10"], "outputs": ["10", "6", "20"]}}

```

**Notes:**

- `metadata.inputs` and `metadata.outputs` must be string arrays of equal length.
- The scorer extracts code from ` ```python ``` ` blocks in the model's output, then executes it with each input piped to stdin and compares stdout to the expected output.
- The model must produce code that reads from stdin and prints to stdout.

---

### Custom Lambda

Uses your own Lambda function to score model outputs. The dataset format depends on the model type.

#### Dataset for Custom Lambda — OSS models

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | The prompt/input |
| `response` | string | yes | The ground truth / expected output |
| `system` | string | no | System prompt |

**Example:**

```jsonl
{"query": "Redact PII from: John Smith lives at 123 Main St.", "response": "[PERSON: John Smith] lives at [ADDRESS: 123 Main St].", "system": "You are a PII redaction assistant."}

```

#### Dataset for Custom Lambda — Nova models

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | array | yes | Conversation array with `role` and `content` (plain strings, not objects) |
| `reference_answer` | string | no | Ground truth — required only if your Lambda compares against it |

Messages may include a `system` role (optional):

```jsonl
{"messages": [{"role": "system", "content": "You are a PII redaction assistant."}, {"role": "user", "content": "Redact PII from: John Smith lives at 123 Main St."}], "reference_answer": "[PERSON: John Smith] lives at [ADDRESS: 123 Main St]."}

```

Or just a `user` message:

```jsonl
{"messages": [{"role": "user", "content": "Redact PII from: John Smith lives at 123 Main St."}], "reference_answer": "[PERSON: John Smith] lives at [ADDRESS: 123 Main St]."}

```
