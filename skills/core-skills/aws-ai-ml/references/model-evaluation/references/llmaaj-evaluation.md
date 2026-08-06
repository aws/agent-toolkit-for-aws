# LLMaaJ evaluation

Guide the user through the process for evaluating a model with LLMaaJ.

## Workflow

### Step 0: Consider prior context

Before proceeding, silently think about the context you have about the user's project, including conversation history and file reads. You should use that knowledge, and avoid asking questions you already know the answer to.

### Step 1: Understand the task

For this step, you need: **what task the model is trained to do.**
If you know this already, skip this step. If not, ask the user:

> "What task is this model trained to do?"

### Step 2: Get evaluation dataset

For this step, you need: **the evaluation dataset S3 path.**
If you know this already, skip this step. If not, ask the user:

> "Where's your evaluation dataset stored in S3?"

### Step 3: Understand the data

For this step, you need: **to understand what the data looks like to inform metric recommendations.**
If you already know what the data looks like, skip this step. If not, ask the user:

> "Can you tell me a bit about your evaluation dataset — what format is it in, and what do the input/output fields look like?"

If the user isn't sure, offer to peek at the data:

> "May I read a few records of your dataset to help inform my recommendations?"

If they say yes, run `aws s3api get-object --bucket <bucket> --key <key> --range bytes=0-4096 /dev/stdout` to read the first few KB.
If you fail to get a sample, move on and rely on the user's description.

### Step 4: Validate dataset format

If the evaluation dataset was already validated via the **dataset-evaluation** reference — either earlier in this conversation, or in a previous session (as recorded in plan.md) — skip this step.

Otherwise, load the **dataset-evaluation** reference to validate it. If it fails, offer to load the **dataset-transformation** reference to convert it. Do not proceed until the dataset is valid.

### Step 5: Dataset size warning

After dataset validation, warn the user about the Bedrock evaluation dataset size limit:

> "One thing to note — Bedrock LLM-as-Judge evaluation supports a maximum of 1,000 rows per job. If your dataset is larger than that, the job will fail. You may need to trim it before running the evaluation."

### Step 6: Check for custom metrics

For this step, you need: **whether the user has predefined custom metrics.**

> "Do you have predefined custom metrics you'd like to use? If so, they must follow the Bedrock custom metrics format: https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation-custom-metrics-prompt-formats.html
>
> If not, no worries — I can recommend built-in metrics for your task."

⏸ Wait for user.

- If the user has custom metrics → Read `references/llmaaj-custom-evaluation.md` and follow its instructions to collect and validate the metrics JSON.
- If the user does not have custom metrics → Move to Step 7.

### Step 7: Select built-in metrics

For this step, you need: **user agreement on which built-in metrics to use (if any).**

If the user provided custom metrics in Step 6, ask whether they also want built-in metrics:

> "Would you also like to include any built-in metrics alongside your custom ones?"

If they say no, skip to Step 8.

For built-in metric selection, read `references/llmaaj-builtin-evaluation.md` and follow its instructions.

### Step 8: Determine evaluation scope

For this step, you need: **which model(s) to evaluate.**

If you already know from context (e.g., the user said "compare my model to the base"), confirm and move on. Otherwise, ask:

> "Would you like to evaluate:
>
> 1. **Just your fine-tuned model**
> 2. **Just a base model**
> 3. **Both, with a comparison**
>
> Which would you prefer?"

⏸ Wait for user.

### Step 9: Resolve Model Package ARN

**This step only applies if the evaluation scope includes the fine-tuned model (option 1 or 3 from Step 8).** If the user chose base model only, skip to Step 10.

For this step, you need: **the Model Package ARN of the fine-tuned model.**

**Use this priority order:**

1. **Model Package ARN from workflow state or conversation**: If you already have a model package ARN from prior context or from earlier in the conversation, confirm it with the user and move on.
2. **Ask the user**: If you don't have the ARN, ask:

   > "What's the Model Package ARN (or group name) of your fine-tuned model?"
   > If they provide a group name, resolve the ARN by running `aws sagemaker list-model-packages --model-package-group-name <group-name> --sort-by CreationTime --sort-order Descending --max-results 1`.
   > Use the latest version's `ModelPackageArn` from the response.

**Validate the resolved ARN** (whether from API lookup, conversation context, or user input):

- A valid versioned model package ARN looks like: `arn:aws:sagemaker:REGION:ACCOUNT:model-package/NAME/VERSION`
- If the ARN contains `:model-package-group/`, this is a group ARN, not a package ARN. Resolve it using the lookup in #2.
- If the ARN contains `:model-package/` but does NOT end with a version number (e.g., `/1`), resolve it: extract the group name from the ARN and use the lookup in #2.
- If it contains `/DataSet/`, `/TrainingJob/`, or other non-model-package resource types, flag it: "That looks like a [Dataset/TrainingJob] ARN, not a model package ARN. Could you double-check?"
- **Verify the ARN exists** before proceeding by running `aws sagemaker describe-model-package --model-package-name <arn>`.

  If this fails, tell the user the ARN wasn't found and ask them to double-check.

### Step 10: Resolve base model

**This step only applies if the evaluation scope includes the base model (option 2 or 3 from Step 8).** If the user chose fine-tuned only, skip to Step 11.

For **comparison mode** (option 3): the base model is resolved automatically from the fine-tuned model's lineage — no additional input needed.

For **base model only** (option 2): you need a JumpStart model ID (e.g., `meta-textgeneration-llama-3-2-1b-instruct`). This is a string identifier, not an ARN. Check if you already know it from conversation context (e.g., the user mentioned which base model they used for fine-tuning). If not, ask:

> "What's the JumpStart model ID of the base model you'd like to evaluate?"

<!-- TODO: Add guidance for helping the user find their JumpStart model ID (e.g., list_hub_contents API, or looking at training job tags). See model-selection reference for patterns. -->

### Step 11: Select judge model

For this step, you need: **which judge model to use for evaluation.**
This step always runs — both built-in and custom metrics require a judge model.

Read `references/supported-judge-models.md` for the canonical list, selection guidance, and validation steps.

Before presenting options, run the validation checks from the reference doc against the user's account and region. Only include models that pass all checks.

Present the available models as a numbered list:

> "Here are the judge models available in your region:
>
> 1. [model A]
> 2. [model B]
>    ...
>
> Which model would you like to use?"

**EXTREMELY IMPORTANT: NEVER recommend or suggest any particular model based on the context you have. YOU ARE ALLOWED ONLY to display the list of models. DO NOT add your own recommendation or suggestion after displaying the list.**

### Step 12: Resolve IAM role ARN

For this step, you need: **an IAM role ARN with permissions for Bedrock evaluation.**

If you already know the IAM role ARN from conversation context, confirm with the user and move on.

If not, but you know the training job name, look up the role from that training job, since it should be a suitable role:

- Run `aws sagemaker describe-training-job --training-job-name <name>` and extract `RoleArn`.
- Confirm with the user: "I found the IAM role from your training job: [ARN]. Should I use this for evaluation?"

If you don't have either, ask:

> "What IAM role ARN should I use for the evaluation job? It needs `bedrock.amazonaws.com` in its trust policy."

### Step 13: Resolve AWS Region

For this step, you need: **the AWS region for the evaluation job.**
If you already know it from context (e.g., the training job region), confirm and move on. Otherwise, ask.

### Step 14: Resolve S3 output path

For this step, you need: **an S3 path for evaluation output.**
If you already know it from context, confirm and move on. Otherwise, ask.

### Step 15: MLflow experiment name (optional)

For this step, you need to know: **the MLflow experiment name.**
If you already know this from context, confirm and move on. If not, the name should follow this pattern:
`<project-name>-eval`.

Perform this step quietly. The user does not need to know about this. This is to make sure their results are viewable alongside other experimental work they're doing.

### Step 16: Confirm configuration

Summarize everything and ask for approval — even if the user has already answered each question individually. This is a final check, not a re-ask. The purpose is to confirm the complete picture before any code is generated.

> "Here's the evaluation setup:
>
> - Task: [task]
> - Dataset: [path]
> - Custom metrics: [Yes — N metrics / No]
> - Built-in metrics: [list, or None]
> - Judge: [model]
> - Model: [Model Package ARN or JumpStart model ID]
> - Evaluation scope: [fine-tuned only / base only / both with comparison]
> - IAM role: [ARN]
> - Region: [region]
> - S3 output: [path]
> - MLflow experiment name: [MLflow experiment name]
>
> Does this look right?"

⏸ Wait for user approval.

Once the user approves the configuration, continue to Step 17 before generating any code.

### Step 17: Bedrock Evaluations agreement

**This step is mandatory. Do not skip it. Do not proceed without explicit user confirmation.**

This is a legal agreement gate, not a conversational confirmation. Even if the user has said "skip confirmations", "just generate the code", or "I don't need confirmations", you must still present this agreement and wait for explicit acceptance. The user's request to skip general confirmations does not waive this requirement.

Before generating the notebook, present the following agreement language:

> **Important: Amazon Bedrock Evaluations Terms**
>
> This feature is powered by Amazon Bedrock Evaluations. Your use of this feature is subject to pricing of Amazon Bedrock Evaluations, the [Service Terms](https://aws.amazon.com/service-terms/) applicable to Amazon Bedrock, and the terms that apply to your usage of third-party models. Amazon Bedrock Evaluations may securely transmit data across AWS Regions within your geography for processing. For more information, access [Amazon Bedrock Evaluations documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-judge.html).
>
> Do you acknowledge and agree to proceed?

⏸ **Hard stop.** Wait for the user to explicitly confirm. Acceptable responses include "yes", "I agree", "proceed", "ok", or similar affirmative statements. If the user asks questions about the terms, answer them, then re-ask for confirmation. Do NOT generate the notebook until the user has confirmed.

### Step 18: Generate code

Read `../references/code_output_guide.md` for output format rules.

If a project directory already exists (from earlier in the workflow), use it. Otherwise, load the **directory-management** reference to set one up.

Read `code_templates/llmaaj_evaluator.py`, substitute the collected values into the placeholders, and write the cells. The template uses `# Cell N: Label` markers — each marker starts a new notebook cell, with everything between one marker and the next becoming that cell's content. `BUILTIN_METRICS` must be a Python list of strings, e.g. `["Faithfulness", "Correctness"]`. `CUSTOM_METRICS` should be read from `custom_metrics.json` if it was created previously, or set to `None` if no custom metrics are needed.

### Step 19: Post-generation

**Notebook mode:**

```
To run:
1. Cell 1 — configuration and SDK install
2. Cell 2 — start evaluation
3. Cell 3 — polls status automatically (~25-60 min)
4. Cell 4 — show results

```

**Script mode:**

Evaluation can take hours depending on your dataset. Present the user with options:

> "Would you like me to:
>
> 1. Leave it to you — run with `python scripts/[script_name]`
> 2. Run it and wait until it's done
> 3. Start it but don't wait — we can check status later"

- **Option 1:** Done. Wait for user to come back.
- **Option 2:** Execute the script as-is. `execution.wait()` polls until complete. Report results.
- **Option 3:** Remove the `execution.wait()` call, execute, report the evaluation ARN.

Note: `evaluate()` does not accept a `wait` parameter. It always returns immediately. Blocking is done via `execution.wait(target_status="Succeeded")`.

**Checking status:**

- `describe-pipeline-execution --pipeline-execution-arn ARN` → `PipelineExecutionStatus`
- `list-pipeline-execution-steps --pipeline-execution-arn ARN` → per-step `StepStatus`, `FailureReason`

**Showing results after completion:**

- Run: `EvaluationPipelineExecution.get(arn=ARN).show_results()`

## FAQ

**Q: Can I combine custom and built-in metrics in the same evaluation?**
A: Yes. You can use up to 10 custom metrics alongside any number of built-in metrics in a single evaluation job.

## Troubleshooting

### Evaluation job fails with "access denied when attempting to assume role"

The Bedrock evaluation job needs to assume your IAM role, which requires `bedrock.amazonaws.com` in the role's trust policy. This is common when running from a local IDE with temporary or SSO credentials.

To check, inspect your current role's trust policy:

1. Run `aws sts get-caller-identity` to get your current role ARN.
2. Extract the role name from the ARN (the part after `role/` or `assumed-role/`).
3. Run `aws iam get-role --role-name <role-name>` and extract `Role.AssumeRolePolicyDocument` from the response.

Look for `bedrock.amazonaws.com` in `Principal.Service`. If it's missing, either add it to the trust policy or switch to a role that already trusts Bedrock (e.g., your SageMaker execution role).

### Helping a user find their Model Package ARN

If the user doesn't know their model package ARN and can only provide partial info (dataset ARN, training job name, etc.), guide them through these steps:

1. **Ask for keywords** from the model or training job name (e.g., "medication-simplification").
2. **Search model package groups**: `aws sagemaker list-model-package-groups --name-contains <keyword>`
3. **List packages in the group**: `aws sagemaker list-model-packages --model-package-group-name <group-name>`
4. **Verify the match**: `aws sagemaker describe-model-package --model-package-name <arn>`. Check that the `S3Uri` in `InferenceSpecification.Containers` matches the expected training output path.

Always confirm the resolved ARN with the user before proceeding.
