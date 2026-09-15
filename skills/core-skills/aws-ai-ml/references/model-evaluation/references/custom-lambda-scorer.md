# Custom Lambda Scorer

This file guides you through resolving a custom Lambda scorer (evaluator) for use with Custom Scorer evaluation.

## Resolve evaluator

For this step, you need: **the evaluator ARN of a registered reward function.**

Check if you already know this from conversation context (e.g., the user mentioned a reward function ARN, or one was used in a previous evaluation). If so, confirm and return to the main workflow.

If not, ask:

> "Do you have an existing reward function registered in SageMaker? If so, what's the evaluator ARN?"

If the user has an ARN, validate it:

- It should look like: `arn:aws:sagemaker:REGION:ACCOUNT:hub-content/.../JsonDoc/NAME/VERSION`
- Validate by splitting the part after `hub-content/` into `HUB_NAME/JsonDoc/CONTENT_NAME/VERSION` and calling:

  ```
  aws sagemaker describe-hub-content --hub-name HUB_NAME --hub-content-type JsonDoc --hub-content-name CONTENT_NAME --hub-content-version VERSION --region REGION

  ```

  If the call succeeds, `HubContentStatus` is `Available`, and `HubContentSearchKeywords` includes `@evaluatortype:rewardfunction`, the evaluator is valid.

If validation fails, tell the user what went wrong:

- **API call errors** → "That ARN doesn't seem to exist. Could you double-check it?"
- **Status is not `Available`** → "That evaluator exists but isn't ready (status: [status]). It may still be provisioning."
- **Missing `@evaluatortype:rewardfunction`** → "That resource exists but doesn't appear to be a reward function evaluator. Could you verify you have the right ARN?"

In any failure case, offer to re-enter the ARN or fall back to a built-in scorer.

If the user doesn't have one:

> "You don't have a registered reward function yet. I can help you create one — I'll provide a template with your scoring logic and register it as a SageMaker Hub Evaluator. Or you can use a built-in scorer instead.
>
> 1. **Create a new reward function** — I'll walk you through it
> 2. **Use a built-in scorer** — Prime Math or Prime Code
>
> Which would you prefer?"

- If **create new** → read `references/create-reward-function.md` and follow its instructions. It will produce an evaluator ARN. Once complete, return here and proceed to "After resolution".
- If **built-in** → return to the main Custom Scorer workflow and switch to the built-in scorer path.

## After resolution

Once you have the evaluator ARN, return to the main Custom Scorer workflow.

---

## Lambda input/output contracts

### Lambda return format

The return format depends on the model type:

**For OSS models:**

```python
# <RETURN_FORMAT> — OSS models
return {
    "statusCode": 200,
    "headers": {"Content-Type": "application/json"},
    "body": json.dumps([result])  # body is a JSON STRING
}

```

**For Nova models:**

```python
# <RETURN_FORMAT> — Nova models
return {
    "statusCode": 200,
    "headers": {"Content-Type": "application/json"},
    "body": [result]  # body is a PARSED LIST (not json.dumps)
}

```

Each result object has the shape:

```json
{"id": "sample_id", "aggregate_reward_score": 0.85, "metrics_list": [{"name": "metric_name", "value": 0.75, "type": "Metric"}]}

```

### Lambda input format

The input format depends on the model type:

**For OSS models (gen_qa path):**

```json
[{
  "id": "hash",
  "model_response": "model's generated text",
  "query": "the prompt",
  "response": "the gold answer from dataset",
  "reference_answer": {"text": "the gold answer from dataset"},
  "metadata": {},
  "processor_config": {}
}]

```

**For Nova models (rft_eval path):**

```json
[{
  "id": "sample_id",
  "messages": [
    {"role": "user", "content": "the prompt"},
    {"role": "assistant", "content": "model's generated output"}
  ],
  "reference_answer": "the gold answer from dataset"
}]

```

To extract the model response from Nova input: read the last message with `role: "assistant"`.

### Evaluator registration

`CustomScorerEvaluator` requires a **Hub Content ARN** (registered via `Evaluator.create()`), NOT a raw Lambda ARN.

```python
from sagemaker.ai_registry.evaluator import Evaluator
from sagemaker.ai_registry.air_constants import REWARD_FUNCTION

evaluator = Evaluator.create(
    name="my-reward-function",
    source="path/to/reward_function.py",
    type=REWARD_FUNCTION
)
# Use evaluator.arn as the evaluator parameter

```

Using a raw Lambda ARN (e.g., `arn:aws:lambda:...`) will fail with `Invalid HubContentArn format`.
