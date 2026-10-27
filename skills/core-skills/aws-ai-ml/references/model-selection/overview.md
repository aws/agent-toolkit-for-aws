# Model Selection

Guides the user through selecting a base model based on their use case.

## When to Use

- User asks which model to use
- User wants to select or change their base model
- User mentions a model name or family (e.g., "Llama", "Mistral", "Nova") — the exact Hub model ID still needs to be resolved
- User wants to evaluate a base model before deciding whether to finetune

## Prerequisites

None — this skill can be entered directly.

---

### Routing Rules

1. **Ambiguity gate:** If it is unclear whether the user wants to **fine-tune** a model or **deploy a base model as-is**, you MUST ask before proceeding. Do not assume either path. **Do NOT recommend, list, or name any models until this is resolved.**

2. **Recommend use-case-spec first:** If no `*_use_case_spec.md` file exists for this use case, recommend creating one via `references/use-case-specification/overview.md` before filtering. This produces better results because the spec captures constraints that map to concrete filter values. If the user declines or provides a specific model name/ID, proceed without it. **After making this recommendation, stop and wait for the user's response. Do not continue with model selection in the same turn.**

3. **Base model filtering MUST use select-for-deployment:** When making a final model selection or recommendation for deployment, you MUST follow `references/select-for-deployment.md` and use its scripts. `SageMakerPublicHub` uses `get_deployable_models.py` for a selection-session catalog snapshot and `search_deployable_models.py` for confirmed candidates; private Hubs keep `get_deployable_models.py` plus `filter_deployable_models.py`. Do not make a final model selection or recommendation for deployment ad hoc from your own knowledge.

4. **Offer to create a use-case spec after filtering:** If filtering was done without a spec, and no `*_use_case_spec.md` file exists for this use case, offer to create one to refine the criteria for future iterations.

5. **No premature recommendations:** You may provide an initial quick-filtered list of models based on what you know, but do NOT make a recommendation or suggest a specific model as "the best choice" until the full selection workflow (select-for-deployment scripts or Step 3A) has been followed. If you have NOT run `get_deployable_models.py` or `get_model_names.py` in this session, you MUST prefix any model list with:

> ⚠️ This is a preliminary list based on general knowledge. I have not yet queried all available models in your Hub. There may be better matches once we run the full selection workflow.

NEVER present a model list without stating whether it came from the Hub scripts or from static reference data.

---

## Workflow

### Step 1: Check Region

Run the same boto3 region check used by planning and SDK setup:

```bash
python -c "import boto3; print(boto3.session.Session().region_name)"
```

- Result is `None` → STOP. Tell user: "Set your region via `export AWS_DEFAULT_REGION=us-west-2` or `aws configure`."
- Region set → store REGION in context, continue.

### Step 2: Discover Hub

1. List all available SageMaker Hubs in the user's region:

   ```bash
   aws sagemaker list-hubs --region <region>
   ```

2. From the results, filter out any hub whose `HubDescription` contains "AI Registry" — these do not contain JumpStart models.
3. The remaining hubs are eligible (e.g., `SageMakerPublicHub` and any private hubs).
4. If exactly one eligible hub exists, use it automatically — do not ask the user.
5. If multiple eligible hubs exist, present them to the user and ask which one to use. Example:

   ```
   I found the following model hubs:
   - SageMakerPublicHub — SageMaker Public Hub
   - Private-Hub-XYZ — Private Hub models
   Which hub would you like to use?

   ```

6. Store the selected hub name for use in subsequent steps.

### Step 3: Select Base Model

Determine the user's goal from the plan, conversation context, or `use_case_spec.md` (check the **## Intent** section):

- If the goal is **fine-tuning / model customization** (Intent says "Fine-tune") → follow [Step 3A: Select for Fine-tuning](#step-3a-select-for-fine-tuning) below.
- If the goal is **base model deployment** (Intent says "Deploy base model") → read `references/select-for-deployment.md` and follow it through all steps (including hosting configuration selection). Then proceed to Step 4 below.

If the intent is ambiguous, ask:

> "Would you like to fine-tune a model, or deploy a base model as-is?"

#### Step 3A: Select for Fine-tuning

First, retrieve all available SageMaker Hub model names by running: `python model-selection/scripts/get_model_names.py <hub-name>`. Note how many models the script returns.

Present all available models to the user with their licenses before making any recommendations. Cross-reference the model list with `references/model-licenses.md` and display each as `<model name> - [<license>](<url>)`. For example: "Qwen3-4B - [Apache 2.0](https://huggingface.co/Qwen/Qwen3-4B/blob/main/LICENSE)"

**Display every model — completeness is required:**

- `get_model_names.py` returns the models in a fixed, deterministic order:
  **alphabetical by name (A→Z, case-insensitive)**. Present them in exactly that
  order — do **not** re-sort or reorder the list. (This applies only to this raw
  availability list; the benchmark ranking tables in `references/model-selection.md`
  keep their performance order and must not be alphabetized.)
- List **each** model returned by `get_model_names.py` as its own separate line with its own license URL. The number of models you display MUST equal the number the script returned.
- Do **not** omit, drop, or skip any model — even when the list is long.
- Do **not** separate models into Text vs VLM categories. Do **not** exclude VLMs from text-only use cases. Present **all** models in a single unified list regardless of modality.
- Do **not** merge or group models under a shared license, and do **not** collapse similar-looking models into one entry. Models that look like variants of each other are still distinct and each needs its own line. For example:
  - Text vs. vision variants of the same family (e.g., `Qwen3-32B` text models vs. `Qwen3-VL-27B` vision models) are different models.
  - Version variants (e.g., `Amazon Nova Lite` vs. `Amazon Nova Lite v2`) are different models.
  - Models that share an identical license URL still each get their own line.
- After presenting the list, verify your output: confirm the count of displayed models matches the count returned by the script. If any are missing, add them before continuing.

If you already know the model the user wants to use (from conversation context or planning files), confirm that it's in the list, display its license, and move on. Otherwise, help the user pick a model following the instructions in `references/model-selection.md`.
**Important:** Make sure to remember this list of available models when helping with model selection. Don't recommend a model that's not available to the user.

**EULA disclaimer (REQUIRED — you MUST include this whenever you present this model list):**

After presenting the model list, always append this disclaimer:

> "ℹ️ **Note:** Some models in this list require accepting an End-User License Agreement (EULA) before deployment. This is a SageMaker JumpStart requirement that is independent of the model's open-source license. Once you choose a model, I'll tell you whether it requires EULA acceptance."

### Step 4: Confirm Selection

#### 4a. Check EULA gating status

After the user selects a model — on **both** the base model deployment path and the fine-tuning
path — check whether that model requires a JumpStart hub EULA acknowledgment. If the
`HubContentDocument` was already retrieved earlier in this session, reuse that response instead of
calling the API again. Otherwise, call `describe-hub-content` and check the `GatedBucket` field in
the `HubContentDocument` JSON:

```
aws sagemaker describe-hub-content \
    --region <region> \
    --hub-name <hub-name> \
    --hub-content-type Model \
    --hub-content-name <selected-model-id>
```

Where:

- `<region>` — the REGION resolved in Step 1
- `<hub-name>` — the hub name selected in Step 2
- `<selected-model-id>` — the HubContentName of the model the user just chose

From the response, parse the `HubContentDocument` JSON string and read `GatedBucket`:

- If `GatedBucket` is `true`: the model is **gated** — tell the user this model requires accepting
  an EULA at deployment time.
- If `GatedBucket` is `false` or absent: the model is **not gated** — tell the user this model does
  not require accepting an EULA.

If the `describe-hub-content` call fails (permissions, model not found, region mismatch), do not
block selection — tell the user the gating status could not be determined and recommend they verify
the model's license terms independently.

> **Important:** The JumpStart hub EULA gate is independent of the upstream model license. A model
> can be Apache 2.0 licensed and still be gated (requiring EULA acceptance), or vice versa. The
> upstream license governs legal usage rights; the hub gate is a separate acknowledgment for models
> whose artifacts are stored in a gated S3 bucket.

#### 4b. Present confirmation summary

Present a summary to the user:

```
Here's what we've selected:
- Base model: <model name>
- EULA required at deploy: Yes / No

```

If the model is gated, add:

> "⚠️ This model requires accepting an End-User License Agreement (EULA) at deployment time."

For the **base model deployment path**, also carry forward the three fields resolved in
`select-for-deployment.md` Step 6:

```
- Model ID (Hub ID): [model_id]
- Instance type: [instance_type]
- Hosting configuration: [inference_config_name, or "none (base config)"]

```

`model_id` is the JumpStart Hub ID of the base model selected above (the `(Hub ID)` label is a
reminder to use that exact identifier, not a friendly name). `model_id` and `instance_type` are both
required; `inference_config_name` may be `null` when the model has no labeled configs. Carry all
three forward — do not drop any of them.

Ask if they'd like to proceed with this model.

## References

- `references/model-selection.md` — Fine-tuning model selection instructions and benchmark descriptions
- `references/select-for-deployment.md` — Base model deployment selection sub-workflow
- `references/model-licenses.md` — Model license information for display during model selection
