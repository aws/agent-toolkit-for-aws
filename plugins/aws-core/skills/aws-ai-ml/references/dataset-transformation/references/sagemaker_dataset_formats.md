# SageMaker Supported Dataset Formats (Offline Fallback)

This is an offline summary of the SageMaker model-evaluation dataset format
documentation. Attempt to fetch the live AWS documentation first; use this
file when network access is unavailable.

## Required Fields

| Field         | Required                 |
| ------------- | ------------------------ |
| User prompt   | Yes                      |
| System prompt | No                       |
| Ground truth  | Only for a custom scorer |
| Category      | No                       |

## OpenAI Format

One JSON record contains a `messages` array with optional `system`, required
`user`, and ground-truth `assistant` entries. Compact example:
`{"messages":[{"role":"system","content":"You are helpful."},{"role":"user","content":"Hello!"},{"role":"assistant","content":"Hello to you!"}]}`.

## SageMaker Evaluation Format

Use `query` for the user prompt and `response` for ground truth. `system` and
`category` are optional. Example:
`{"system":"Answer briefly.","query":"What ends a question?","response":"?","category":"Grammar"}`.

## HuggingFace Prompt Completion Format

Standard records use string `prompt` and `completion` fields:
`{"prompt":"What ends a question?","completion":"?"}`.

Conversational records use message arrays for both fields:
`{"prompt":[{"role":"user","content":"What ends a question?"}],"completion":[{"role":"assistant","content":"?"}]}`.

## HuggingFace Preference Format

Standard records use `prompt`, `chosen`, and `rejected` strings:
`{"prompt":"The sky is","chosen":"blue","rejected":"green"}`.

Conversational records use message arrays in all three fields. `chosen` is the
ground truth.

## Verl Format

The preferred shape uses `data_source`, a message-array `prompt`, optional
`ability`, `extra_info.answer` (preferred ground-truth field), and optionally
`reward_model.ground_truth`. Legacy records may use a string `prompt`.

Preserve metadata such as `id`, `data_source`, `ability`, `reward_model`,
`extra_info`, `attributes`, and `difficulty`.
