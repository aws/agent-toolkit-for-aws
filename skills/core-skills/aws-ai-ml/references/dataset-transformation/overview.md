
# Dataset Transformation Agent

Transforms a data set provided by the user into their desired format.

## When to Use

- User needs to generate code for transforming datasets for SageMaker model training or model evaluation.
- A dataset requires processing, cleaning, or formatting before training or evaluation.
- Workflow requires a formal review and approval cycle before execution.

## Prerequisites

- The SDK environment has been verified (SDK version, region, execution role). If not done, load the `sdk-getting-started` reference first.

## Principles

1. **One thing at a time.** Each response advances exactly one decision. Never combine multiple questions or recommendations in a single turn.
2. **Confirm before proceeding.** Wait for the user to agree before moving to the next step. You are a guide, not a runaway train.
3. **Don't read files until you need them.** Only read reference files when you've reached the workflow step that requires them and the user has confirmed the direction. Never read ahead.
4. **No narration.** Don't explain what you're about to do or what you just did. Share outcomes and ask questions. Keep responses short and focused.
5. **No repetition.** If you said something before a tool call, don't repeat it after. Only share new information.
6. **Do not deviate from the Workflow.** The steps listed in the workflow should be followed exactly as described. Progress from Step 1 to Step 11 to complete the task. Do not deviate from the workflow!
7. **Always end with a question.** Whenever you pause for user input, acknowledgment, or feedback, your response must end with a question. Never leave the user with a statement and expect them to know they need to respond.
8. **Default output format is JSONL.** Unless the user explicitly requests a different file format, the transformed dataset should be written as `.jsonl` (JSON Lines — one JSON object per line).

## Known Dataset Formats Reference

This skill supports two transformation purposes — **training data** and **evaluation data** — each with its own format resolution path. The purpose is determined in Step 1 of the workflow.

### Training Data Formats

Resolve the target format using the reference file ../dataset-evaluation/references/strategy_data_requirements.md. When the transformation is for **model training**, the required format depends on both the **model type** (Open Weights like Llama/Qwen vs Nova) and the **finetuning technique** (SFT, DPO, RLVR, RLAIF) — make sure to match on both dimensions. If either the model type or technique is not yet known, ask the user before resolving the format.

### Evaluation Data Formats

When the transformation is for **model evaluation**, resolve the target format using this order:

1. Try fetching the live documentation at https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html to get the latest evaluation dataset schema definitions.
2. **If the fetch fails** (e.g., no internet access, VPC environment), fall back to the offline copy at `references/sagemaker_dataset_formats.md`. Inform the user that the format schemas are from an offline copy and may be outdated.

Use whichever source you successfully access as the source of truth for the target format. Do not rely on memorized schemas.

## Workflow

### Step 1: Determine transformation purpose

Your first response should determine whether this transformation is for **model training** or **model evaluation**. If the context already makes this clear (e.g., the user said "I need to prep my training data" or "I need to format my eval dataset"), confirm your understanding and move on. Otherwise, ask:

> "Is this dataset transformation for model training or model evaluation? This helps me look up the right target format for you."

- **Training** → format resolution will use the local training data requirements reference (model type + finetuning technique dependent).
- **Evaluation** → format resolution will use the live AWS documentation (with offline fallback).

Remember this choice — it determines how the target format is resolved in Step 3.

⏸ Wait for user.

### Step 2: Set expectations

Acknowledge the user's request and state what this skill can do:

> "I can help you transform your dataset's format! Here's my plan: I will first need to understand the format of your dataset and the transformation requirements. Once I have that, I will generate a dataset transformation function that we can refine together. After the dataset transformation function is refined to your liking, I will perform the transformation task and upload it to your desired location! Does this sound good?"

⏸ Wait for user.

### Step 3: Understand the dataset transformation task

For this step, you need to know: **what dataset format the user would like to transform their dataset from and what dataset format they would like to transform it in to.**
If you know this already, skip this step. If not, ask the user:

> "What's the dataset format you would like to transform it into?"

Resolve the target format based on the purpose determined in Step 1:

- **If training data**: Ask the user for the finetuning technique (SFT, DPO, RLVR, RLAIF) and model type (Open Weights like Llama/Qwen vs Nova) if not already known. Then look up the required format from the "Training Data Formats" section in the Known Dataset Formats Reference above.
- **If evaluation data**: If the user mentions a well-known format name (e.g., "OpenAI format", "SageMaker format"), fetch the schema from the live documentation as described in the "Evaluation Data Formats" section above. If a well-known format is fetched, confirm with the user:

> "I've found a SageMaker dataset format: {sagemaker-dataset-format-name} with schema: {sagemaker-dataset-format-schema}. Is this what you were referring to?"

If the user describes a custom format not listed in the reference doc, ask them to provide a sample record of the desired output format.

⏸ Wait for user.

### Step 4: Get the dataset from the user

For this step, you need: **the location of the user's dataset**.
If you know this already, skip this step. If not, ask the user:

> "Where can I find your dataset? Either a local directory or S3 location works!"

⏸ Wait for user.

### Step 5: Examine sample data

Read 1–2 sample records from the user's dataset and show them so the user can confirm the source schema. Do not run format detection — that is handled by the planning reference before this reference is invoked.

Do not show a side-by-side mapping to the target format here — the detailed mapping will be handled in Step 7 when generating the transformation function.

⏸ Wait for user.

### Step 6: Get the dataset output location

For this step, you need: **to understand where to output the transformed dataset to. It could be an S3 URI or local directory**
If you already know where the dataset is supposed to be output to, skip this step. If not, ask the user:

> "Where should I output your transformed dataset to? Either a local directory or S3 location works!"

If the user provides a directory (not a full file path), construct the output filename using the pattern `{original_name}_{target_format}.jsonl` (e.g., `gen_qa_100k_openai.jsonl`).

⏸ Wait for user.

### Step 7: Generate and validate the transformation function

For this step, you need: **to generate a python function that transforms the dataset from the format in Step 5 to the format in Step 3**

Read the reference guide at `references/dataset_transformation_code.md` and follow its skeleton exactly when generating the transformation function.

The python function should be in the form of:

```python
def transform_dataset(df: pd.DataFrame) -> pd.DataFrame:

```

The `<project-dir>` is the project directory established by the directory-management reference (e.g., `dpo-to-rlvr-conversion`).

In notebook mode, add a `%%writefile <project-dir>/scripts/transform_fn.py` code cell AND write the file to disk for testing. In script mode, write the file to disk directly.

Continue iterating with the user's feedback — update the code in place on each revision rather than showing code inline.

**If sample data was collected in Step 5**, test the function against the sample records:

1. Generate the transformation function.
2. Write the sample data to a temporary JSONL file (e.g., `/tmp/test_input.jsonl`), then run:

   `python3 -c "import sys; sys.path.insert(0, '<project-dir>/scripts'); from transform_fn import transform_dataset; import pandas as pd; df = pd.read_json('/tmp/test_input.jsonl', lines=True); result = transform_dataset(df); print(result.to_json(orient='records', lines=True))"`

3. If the test fails, fix and re-test until it passes.
4. Show the user the function and transformed sample output for review.

**If no sample data**, present the function for review and refinement.

⏸ Wait for user.

### Step 8: Determine output target

If no project directory exists, load the **directory-management** reference to set one up.

⏸ Wait for user.

### Step 9: Generate the execution code

**Before writing the code, read:**

- `references/code_output_guide.md` (output format rules)
- `code_templates/transformation.py` (cell structure and skeleton code)

The template uses `# Cell N: Label` markers — each marker starts a new section. Cell 2 (Transformation Function) is dynamically generated from Step 7; all other cells follow the template skeleton.

Generate the execution logic following the code output guide.

- In notebook mode, add a `%%writefile <project-dir>/scripts/<script_name>.py` code cell AND write the file to disk. In script mode, write the file to disk directly.
- The script must import `transform_dataset` from `transform_fn`.
- Replace placeholders with the actual input/output paths.

Read the reference guide at `references/dataset_transformation_code.md` and follow its execution script skeleton exactly.

**If sample data was collected in Step 5**, test the full pipeline:

1. Write the sample records to a temporary JSONL file (e.g., `/tmp/test_input.jsonl`).
2. Run: `python3 <project-dir>/scripts/<script_name> --input /tmp/test_input.jsonl --output /tmp/test_output.jsonl`
3. If it fails, debug and fix, then re-run until successful.
4. Show the user the output for review.

**If no sample data**, present the notebook for review and refinement.

⏸ Wait for user.

### Step 10: Determine and confirm execution mode

Check the size of the input dataset:

- If the dataset is in S3, run `aws s3api head-object --bucket <bucket> --key <key>` and check the `ContentLength` field.
- If the dataset is local, check the file size.

**Decision criteria:**

- Dataset < 50 MB → recommend local execution
- Dataset ≥ 50 MB → recommend SageMaker Processing Job

Inform the user of the recommendation and get their approval:

If local:

> "Your dataset is {size} MB — since it's under 50 MB, I'd recommend running the transformation locally. Would you like to proceed with local execution, or would you prefer a SageMaker Processing Job instead?"

If SageMaker Processing Job:

> "Your dataset is {size} MB — since it's over 50 MB, I'd recommend running this as a SageMaker Processing Job for better performance. Would you like to proceed with a SageMaker Processing Job, or would you prefer to run it locally instead?"

Do not execute until the user approves. If the user rejects the recommendation, switch to the alternative and get their explicit approval before proceeding.

⏸ Wait for user.

**After user confirms, add an execution cell to the notebook. Do NOT run the transformation directly (no bash, no inline python). If notebook execution tools (`run_cell`) are available, offer to run the cells. Otherwise, generate the cell for the user to execute themselves:**

If local execution:

- Add a cell that runs the transformation by importing from the `.py` files already on disk (written by the agent during Steps 7 and 9): import `transform_dataset` from `transform_fn`, load the dataset, transform, and save output. Scripts are located in `<project-dir>/scripts/`.

If SageMaker Processing Job:

- Add a cell that submits and monitors the Processing Job inline using the V3 SageMaker SDK directly (FrameworkProcessor, ProcessingInput, ProcessingOutput, etc.). Create a FrameworkProcessor with the SKLearn 1.2-1 image, configure inputs/outputs, and call `processor.run(wait=True, logs=True)` to block the cell and stream logs until the job completes. See `scripts/transformation_tools.py` for reference implementation details.
- Inform the user they can run this cell to kick off and monitor the job.

**Important:** The agent must NOT execute the transformation directly via bash or inline python. If `run_cell` is available, use it to run the notebook cells. Otherwise, the cells are for the user to review and run. Only sample data (from Steps 7 and 9) should be transformed by the agent for validation purposes.

> If `run_cell` is available: "I've added the execution cell to the notebook. Would you like me to run it?"
> Otherwise: "I've added the execution cell to the notebook. You can run it to transform the full dataset. Would you like to review the notebook before running it?"

⏸ Wait for user.

### Step 11: Verify and confirm with the user

For this step, you need: **to verify the output looks correct and confirm with the user.**

- Read 1–2 sample records from the output to show the user.
- Report the total number of records transformed.
- Ask the user if the output looks good.

⏸ Wait for user to confirm.
