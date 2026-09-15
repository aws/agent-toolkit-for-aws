
# Workflow Instruction

Follow the workflow shown below. Locate the dataset, check the file type, and resolve any issues with missing files or wrong file types. Determine the fine-tuning model and fine-tuning strategy. Run the appropriate validation based on the model family. Summarize the results: is the dataset ready for fine-tuning?

## Prerequisites

- The SDK environment has been verified (SDK version, region, execution role). If not done, load the `sdk-getting-started` reference first.

---

## Workflow

1. **Locate Dataset**:
   - The full path may be a local file path, or an S3 URI
   - Resolve the full path to the dataset file, make sure read permissions are available, and help the user if the file is not found

2. **Determine strategy and model**:
   - File formatting depends on the currently selected fine-tuning strategy and fine-tuning base model.
   - If the strategy and model are already known from the conversation context (e.g., selected via the model-selection and finetuning-technique references), use them.
   - If not available in context, load the model-selection and/or finetuning-technique references to determine them before proceeding.
   - **Exception:** If the user is validating an evaluation dataset (not a training dataset), neither model nor technique is required — the format detector can validate eval format (query/response structure) independently. Do not block on model-selection or finetuning-technique for eval dataset validation.

3. **Check File Formatting**: Run the tool format_detector.py to make sure the file conforms to formatting requirements.
   - Send the full path directly to the format_detector script as an argument
   - Do not send the model and strategy as arguments
   - Do not download data from S3
   - Do not make local copies of data
   - **Required serialization is JSONL.** All supported training and evaluation formats are JSON Lines (`.jsonl`) — one JSON object per line. The `format_detector` only validates JSONL input.
   - **If the file is not JSONL** (e.g., `.parquet`, `.csv`, `.tsv`, Arrow), the format detector cannot validate it and the dataset is **not** ready as-is — even if its columns or schema happen to match the target. Do not hand-inspect the file and declare it valid. Treat a non-JSONL file as requiring transformation, and proceed to the transformation recommendation in Step 4. Matching column names (e.g., `prompt`/`completion` in a parquet) is **not** sufficient — the data must be serialized as JSONL.

4. **Summarize Results**: Tell the user if their data is ready
   - Examine the output of format_detector and compare to the known strategy and model
   - **Important: training datasets and evaluation datasets have different format requirements.**
     - **Training datasets** must match the fine-tuning strategy format per `references/strategy_data_requirements.md`
     - **Evaluation datasets** (for model evaluation) must match one of the [SageMaker evaluation dataset formats](https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html).
     - **Custom Scorer evaluation datasets** have scorer-specific requirements. If the dataset is intended for Custom Scorer evaluation (Prime Math, Prime Code, or Custom Lambda), read `references/custom-scorer-evaluation-dataset-formats.md` and validate against the scorer-specific schema. The scorer type should be known from conversation context (determined in the model-evaluation reference).
   - Report back to the user if their current dataset is valid for its intended purpose
   - Warn the user if their dataset is valid, but for a different strategy or model
   - Warn the user if their dataset is not valid for any strategy/model pair
   - A dataset is only "ready" if it is **both** serialized as JSONL **and** matches the required schema for the strategy/model. A non-JSONL file (parquet, csv, etc.) is never ready as-is, regardless of its columns — recommend transformation.
   - If the user plans to finetune a model with the evaluated dataset, it needs to be uploaded to an S3 bucket in the same region as the planned training job (usually the default region). Warn the user if this is NOT the case.
   - If the dataset is NOT in the necessary format (wrong serialization or wrong schema), recommend transforming it using the dataset-transformation reference, wait for user confirmation, and update the plan based on their response

## Messages to the User

- Introduction: "This skill checks the structure of your dataset for model fine-tuning."
- File types: This skill applies to files that are formatted according to the [Amazon SageMaker AI Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/autopilot-llms-finetuning-data-format.html#autopilot-llms-finetuning-dataset-format)

## Resources

- scripts/format_detector.py is self-contained format validation script that can be run independently
- model-selection and finetuning-technique references should have already determined the base model and fine-tuning strategy
- references/strategy_data_requirements.md contains data format requirements per strategy

### Script Details

- scripts/format_detector.py is self-contained format validation script that can be run independently:

```bash
# With the file path argument identified in workflow step 1
python scripts/format_detector.py local_path/to/dataset

```

## References

- `scripts/format_detector.py` — Self-contained format validation script
- `references/strategy_data_requirements.md` — Data format requirements per strategy
