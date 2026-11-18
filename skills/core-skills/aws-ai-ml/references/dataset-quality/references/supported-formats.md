# Dataset Quality Evaluation Supported Formats

**Supported formats and their dataset quality evaluation API names:**

| Detected format | Description | Covers |
|---|---|---|
| `Bedrock_Converse` | Nova SFT and DPO (messages with nested content arrays, optional candidates) | NOVA_SFT, NOVA_DPO |
| `HF_Prompt_Completion` | Open-source SFT (prompt/completion, string or message array) | OPEN_WEIGHTS_SFT, OPEN_WEIGHTS_SFT_CONV |
| `HF_Preference` | DPO (chosen/rejected, string or message array) | GPT_OSS_DPO, OPEN_WEIGHTS_DPO |
| `Verl` | RLVR/RLAIF (prompt + no completion/chosen/rejected) | VERL, VERL_LEGACY |
| `Nova_PPO` | Nova PPO (turns array with User:/Bot: prefixes) | Nova PPO |
| `Nova_CPT` | Nova CPT (single `text` field; other keys allowed unless they are another format's field names) | Nova CPT |
| `OpenAI_Messages` | OpenAI/GPT-OSS chat-completions (messages with string content, system role allowed) | OpenAI chat format |
| `SageMaker_Eval` | SageMaker single-turn eval (query/response, optional system/category) | SageMaker eval format |
| `Nova_RLVR` | Nova RLVR (messages + reference_answer dict) | Nova RLVR |
| `Custom` | Does not match any supported format | — |

**When the format is `Custom` (not recognized):**

Check whether the format is **columnar** (all top-level values are scalars/strings) or **nested** (any value is a list of dicts like `messages`):

**Custom + columnar (a `.jsonl` or `.csv` file with flat columns, every top-level value a scalar or a string, and every `.parquet` file):** Quality evaluation IS supported. The user must provide explicit column bindings (Views) for each metric. Present the discovered columns (for a `.csv` file, the `columns` the format check reported; for a `.parquet` file, which the format check does not read, the column names the user gives) and proceed to metric selection → column binding. No transformation required. A `.tsv` file stops at the format check (overview.md, Out of Scope).

**Custom + nested:** quality evaluation has no validated workflow in this capability; the service's Views bind flat columns only and cannot reach a nested structure, so offer dataset-transformation to flatten first and never write transformation code inline. The sentence to the user:
> "Your dataset has a nested structure that isn't a recognized format. Dataset quality evaluation requires flat columns for binding. Would you like to flatten your data first?"

**When the format is `Nova_RLVR`:** the format is recognized and has no default metric set. Its core columns (`messages` list, `reference_answer` dict) are **nested and cannot be bound** to any built-in metric (the job is accepted at submit and fails minutes later). Read the first record: any **additional flat scalar columns** (e.g. `difficulty`, `source`) can be bound to built-ins via `quality-job.md` Step 10.2 + 10.3. Spec-driven evaluation and the exploratory analysis read the whole record, nested fields included. Proceed to Step 10 on the spec path; offer built-ins only for the flat columns that exist.

> "Your dataset is formatted as Nova_RLVR. Its core columns are nested, and built-in metrics only bind flat text - so built-ins can run on [your additional columns: [list] / nothing here, since the record has only the two core columns]. Evaluating against a requirements spec and exploring the data both work on the whole record. Let's start with the spec."

**For format validation purposes** (not quality evaluation), you can still provide informative guidance about what recognized format the dataset is closest to:

Example responses:

- "Your dataset has `query` and `response` fields but doesn't match `SageMaker_Eval` (perhaps due to extra fields). Remove any extra fields beyond `query`, `response`, `system`, and `category` to match SageMaker_Eval format. Alternatively, rename `query` → `prompt` and `response` → `completion` to match HF_Prompt_Completion."
- "Your dataset has `messages` with a `reference_answer` field, but `reference_answer` is a plain string instead of a dict. This is close to `Nova_RLVR`, which expects `reference_answer` to be a dictionary. Wrap the string value in a dict (e.g., `{\"answer\": \"...\"}`) to match the Nova_RLVR format."
- "Your dataset has `input` and `output` fields. This is close to HF_Prompt_Completion but uses different field names. Rename `input` → `prompt` and `output` → `completion`."
- "Your dataset has `instruction`, `input`, and `output` fields (Alpaca format). To make it compatible, concatenate `instruction` + `input` into `prompt` and rename `output` → `completion`."
- "Your dataset has `messages` with flat string content (OpenAI chat format), but some records have no `assistant` turn, so it doesn't match `OpenAI_Messages`. That format needs every message to carry a `role` and a string `content`, with at least one `assistant` message per record. Add the assistant turn or drop the records that lack one to match OpenAI_Messages."
