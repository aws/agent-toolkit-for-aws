# Format Check (Steps 2 to 5)

The router (`../overview.md` Step 1) sends two requests here: a quality evaluation of a local file or an S3 URI, which continues at `quality-job.md` Step 6 when this page ends, and a format check that is the whole request, which ends here. A quality evaluation of a dataset whose Dataset ARN is already known skips this page and starts at `quality-job.md` Step 6; the bring-your-own-spec entry (`bring-your-own-spec.md`) takes the format from the Dataset entity and never reads the data.

**Always run the local format detector first** to determine the routing path. For recognized formats, built-in metrics run on default columns unless the user picks columns. For unrecognized columnar formats, the user selects metrics and then provides column bindings. Unrecognized nested formats have no validated workflow in this capability (the service's Views bind flat columns only) — offer dataset-transformation to flatten them first.

**Also check training volume before evaluating.** If the dataset is meant for training, read `training-volume-requirements.md` and follow it. Do this even when the format came from a known-good upstream source such as synthetic-dataset-generation (SDG) output — format provenance says nothing about record count. A dataset that is correctly formatted but too small to train is a finding the user needs before they spend time on a quality evaluation, and before they launch a training job that is more likely to fail.

---

## Format Validation

### Step 2: Locate the dataset

For this step, you need: **the dataset file path.** If the path is already known from the conversation or project files (the request, a Step 0 manifest, an SDG output location), move on to Step 3 without asking.

If not, discover first: list the files the conversation points at (`ls` on a directory the user named, or `aws s3 ls` on a bucket the conversation named or the session's default bucket) and offer the candidates you find. Ask the open question only when nothing is found:

> "Which dataset should I check? You can give a local file path or an S3 URI (s3://bucket/path/to/data.jsonl)."

⏸ Wait for user.

Once the path is known:

- The full path may be a local file path or an S3 URI
- Resolve the full path, make sure read permissions are available
- Help the user if the file is not found

### Step 3: Determine strategy and model

File formatting depends on the fine-tuning strategy and base model.

- If the strategy and model are already known from conversation context, use them.
- If not available in context, ask the user directly in one question (e.g., "Which fine-tuning strategy and base model are you targeting?"). If the user doesn't know yet, proceed with format detection alone — Step 5's strategy-alignment commentary becomes informational only.

### Step 4: Check file formatting

**MANDATORY: Always run the format detector script.** Never infer the format by reading the file yourself or guessing from field names. The script is the single source of truth for format classification.

```bash
python scripts/format_detector.py local_path/to/dataset --json
```

Dependencies: a local `.jsonl` or `.csv` file needs nothing beyond Python (the standard library only); an S3 URI needs `boto3` installed in the Python the command runs with, since the detector reads the object through it; a `.parquet` path needs nothing, because the detector does not read it. When `boto3` is missing, do not install anything on your own. Ask, and wait for the answer:

> "Can I install the required SDK components into this project's Python environment and then run the format check?"

On yes, follow the install in `../../sdk-getting-started/references/sagemaker-python-sdk-setup.md` (it installs `boto3` with the SDK) and run the detector with the Python the SDK was installed into (on a venv setup, `./.venv/bin/python`). A scratch environment outside the project (a venv under `/tmp`, a `pip install` into any other Python) is also an install and needs the same yes; a temporary one that is deleted afterwards still changes the user's machine without consent.

**Rules:**

- Send the full path directly as an argument
- Do not send the model and strategy as arguments: the detector reads the schema only
- Do not download the data from S3 or copy it locally: the detector reads what it needs itself (a ranged read of the first 1 MB of a `.jsonl` or `.csv` object; nothing of a Parquet object), and the file may be large and is the user's data
- Do NOT read the dataset yourself to determine the format — only the script output is authoritative
- Do NOT skip this step even if you think you know the format from context

**What the output covers.** What the detector reads depends on the file type.

- **`.jsonl`** (or a path with no known extension): the file's first 1 MB, classified from the lines in it. It passes a sample in which some lines are not JSON as long as the parsed lines match a format, and lists those lines as parse errors (`Parse errors: N` in the text form, the `parse_errors` list in the JSON form). When the output lists parse errors, tell the user the count and the first error before continuing, since the job reads every line of the file and a line the sample could not parse is one the job will meet too. A first record longer than the sample ends in an `Error:` line that says so, never in `Custom`: run the check again with `--sample-size` larger than that record.
- **`.csv`**: the header and the first 5 rows (an S3 object through a ranged read of its first 1 MB, read from memory and never written to disk, so nothing of the user's data is left in the project folder). The output's `columns` lists the header. Before the format rules run, a blank cell and the tokens pandas reads as missing (`NA`, `N/A`, `NaN`, `null`, `None` and the rest of its default list) count as no value, as the quality job's CSV reader sees them; a known format needs text in every sampled row of its text columns, so a `prompt,completion` file with one blank completion in the sample is `Custom`.
- **`.parquet`**: nothing, local or S3. The format is `Custom`, `sampled` is `false`, `columns` is empty, and the `note` says the format check does not read Parquet files and the quality job does. Tell the user that, and that the evaluation binds the columns explicitly from the names they give (`quality-job.md` Step 10.3), which the job accepts for any format; no known format's default columns apply.
- **`.tsv`, `.pq`, plain `.json` and the other extensions the detector stops on**: it reads nothing and ends with an `Error:` line that says why. Tell the user what it says; `../overview.md`, Out of Scope, has the boundary.

**When the output has a `service_note`.** The detector found a known format, but a column that format needs as text holds only numbers or blanks, or only booleans (`True`/`False`) or blanks, in the sampled rows. The quality job's CSV reader reads such a column as numbers or booleans, and the job then names the file `Custom` and refuses default columns. The text metrics still run on that column: each value counts as one word of one character, and the job log warns of degraded results. Duplicate detection (`exact_dedup`) on that column fails the whole job. So bind every metric to its column by name at `quality-job.md` Step 10.3, on the columns in `columns`, so the job runs whatever name it gives the file; this adds no question. Tell the user in one sentence that the column holds only numbers (or only booleans) and that the text metrics score each number as a one-character word. Leave `exact_dedup` off that column: bind it to the text columns only, or leave it out when there is none.

### Step 5: Summarize results and format compatibility

The format detector identifies which of the supported formats the dataset matches. Read `supported-formats.md` for the full catalog (what each format is, which strategies it covers) and the example responses for non-matching datasets.

**When the format is recognized:** determine whether it's columnar or nested (fixed mapping):

- Columnar: HF_Prompt_Completion, HF_Preference, SageMaker_Eval, Verl
- Nested: Bedrock_Converse, OpenAI_Messages, Nova_PPO, Nova_CPT

**For recognized columnar formats**, report the format and any additional columns, then continue to `quality-job.md` Step 6 without asking a separate question here — evaluation intent (Step 7) and collecting the dataset location to register (Step 8) come before the evaluation decision:

> "Your dataset format is **[format]** — ready for quality evaluation.[If additional columns exist: Your dataset also has additional columns ([list]) beyond prompt and completion.]"

**For recognized nested formats**, check if the raw record has additional flat keys alongside `messages`:

- Read the first record. If the only top-level key is `messages` (no additional flat keys): report the format and continue to Step 6. Note that column binding is not available for this format — Step 10.3 will be skipped later.
- If the record has additional flat keys alongside `messages` (e.g., `{"messages": [...], "category": "medical", "difficulty": "easy"}`): report the format and the additional bindable columns, then continue to Step 6.

Report the format and continue to Step 6:

> "Your dataset format is **[format]** (nested messages).[If additional flat keys: Your dataset also has additional columns ([list]) that can be included in the evaluation.]"

🚨 **Recognized nested formats do NOT support explicit View bindings on `prompt`/`completion`.** The service derives those columns; you cannot bind to them explicitly. However, additional flat keys that exist alongside `messages` in the raw record ARE bindable via explicit View.

**When the format is `Custom`:** for a `.csv` file, present the output's `columns` and continue to Step 6 as columnar (bindings come at Step 10.3), without reading the file yourself. For a `.parquet` file, ask which column holds the text to evaluate and, when there is one, which holds the completion; continue to Step 6 as columnar and bind those names at Step 10.3. Never read the file yourself. For a `.jsonl` file, read the first 3-5 lines and decide columnar (all top-level values scalars; present the columns, continue to Step 6, bindings come at Step 10.3) or nested (any value a list of dicts; no validated workflow here, offer dataset-transformation to flatten first); the branch text and the sentence to the user are `supported-formats.md`, "When the format is Custom". Never write transformation code inline: if the user wants to transform their dataset, activate the **dataset-transformation** capability, which owns all format conversion work.

**Important: training datasets and evaluation datasets have different format requirements.**

- **Training datasets** must match the fine-tuning strategy format (SFT, DPO, RLVR) per `strategy_data_requirements.md`
- **Evaluation datasets** (for model evaluation) must match one of the [SageMaker evaluation dataset formats](https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html). If the dataset is meant for Custom Scorer evaluation (Prime Math, Prime Code, or a Custom Lambda), read `custom-scorer-evaluation-dataset-formats.md` and check the records against the scorer's fields; the detector's catalog does not cover those shapes.

Report back to the user:

- If their dataset is valid for its intended purpose
- Warn if their dataset is valid but for a different strategy or model
- Warn if their dataset is not valid for any strategy/model pair

**Check minimum data volume for training datasets.** Read `training-volume-requirements.md` and follow it — it carries the minimum, what and how to count, and the scope carve-outs. Do not restate the number from memory. Surface any volume warning here, alongside the format result and before offering quality evaluation or any other downstream step.

After reporting, continue by path:

- **Quality-evaluation path** (every entry except a caller's format-only request): continue to `quality-job.md` Step 6 without asking whether to run a quality evaluation. The user decides what runs at Step 7 (intent) and Step 12 (plan confirmation); a format check is never the end of this path. This is the same rule the recognized-columnar paragraph above states; it applies to every supported format, including unrecognized columnar formats (column bindings come at Step 10.3) and `Nova_RLVR`.
- **Format-only request from a calling capability** (or a user who said "only"): report the verdict and stop here; the caller decides what happens next. Do not offer or start a job. State any volume warning as a sentence (the count and the recommended minimum from `training-volume-requirements.md`, and that training below it is more likely to fail) without that page's closing question about more data or synthetic examples; the reply ends without a question.

If the dataset is `Nova_RLVR`, add the caveat to the report on either path: its core columns (`messages`, `reference_answer`) are nested, so built-in metrics can run only on any additional flat columns the records carry, while spec-driven evaluation and the exploratory analysis work on the whole record; the sentence to the user is `supported-formats.md`, "When the format is Nova_RLVR".

If the user wants a quality evaluation, the next step is the intent decision (`quality-job.md` Step 7), before Step 8 collects the dataset location to register (the generated notebook registers it after the plan confirmation); never name registration first. A quality evaluation continues at `quality-job.md` Step 6.
