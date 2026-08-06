# RLAIF Fine-Tuning Guide

RLAIF (Reinforcement Learning from AI Feedback) uses a Bedrock LLM as a judge to score model outputs during training. No human-labeled preference pairs are needed — the judge evaluates responses in real time.

## How RLAIF Differs from RLVR

- **RLVR**: reward comes from a Lambda function (verifiable, deterministic)
- **RLAIF**: reward comes from a Bedrock LLM judge (flexible, open-ended)
- **Best for**: summarization, helpfulness, instruction-following, open-ended quality

## Reward Model Options

The `reward_model_id` sets the Bedrock LLM used as judge. To get the current list of available models, run:

```bash
venv/bin/python3 -c "from sagemaker.train.constants import _ALLOWED_REWARD_MODEL_IDS; import json; print(json.dumps(_ALLOWED_REWARD_MODEL_IDS, indent=2))"

```

Present the output to the user as a numbered list showing each model name and its available regions, then ask them to pick one.

---

## Option 1: Builtin Reward Prompt

The simplest path. Choose one of the four builtin prompts — the SDK maps it to the corresponding Jinja template in the Hub recipe.

Pass the builtin name directly as the `reward_prompt` parameter:

- `"Builtin.Summarize"` — evaluates summarization quality
- `"Builtin.Faithfulness"` — evaluates factual consistency with source
- `"Builtin.ChainOfThought"` — evaluates step-by-step reasoning quality
- `"Builtin.Evaluation"` — general response quality evaluation

**When to use**: When one of the four builtin prompts matches the use case well enough. Ask the user which one fits, or suggest based on the task.

**Under the hood**: `reward_prompt="Builtin.Summarize"` sets the hyperparameter `judge_prompt_template` to the matching template. No `Evaluator.create()` call needed.

See `code_templates/rlaif_builtin.py` for the full code template.

---

## Option 2: Custom Reward Prompt

When the builtin prompts don't fit the use case, register a custom Jinja prompt file as a `RewardPrompt` evaluator.
Suitable for: domain-specific quality, structured output validation, or multi-criteria scoring.

**Key difference from RLVR**:

- RLVR uses `Evaluator.create(type=REWARD_FUNCTION)` → deploys a Lambda function
- RLAIF uses `Evaluator.create(type=REWARD_PROMPT)` → uploads a text/Jinja file to S3

The Bedrock judge receives the prompt and evaluates the model output. No Lambda is involved.

### Steps

1. **Write the prompt file** — create a `.jinja` file with a suitable name in the project's scripts directory. The prompt should instruct the judge how to evaluate the model's response. It can reference `{{ prompt }}` and `{{ response }}` template variables.

   **To help user write the prompt** - think:

   - What should the judge look for in a good response?
   - What should it penalize?
   - Should it return a score, a label, or a ranking?

2. **Register the prompt as an evaluator**:

   ```python
   from sagemaker.ai_registry.evaluator import Evaluator
   from sagemaker.ai_registry.air_constants import REWARD_PROMPT

   reward_prompt_evaluator = Evaluator.create(
       name="[GENERATE A NAME HERE]",  # lowercase alphanumeric + hyphens, max 20 chars
       type=REWARD_PROMPT,
       source="path/to/custom_reward_prompt.jinja",  # local file path or S3 URI
       sagemaker_session=sagemaker_session,
       wait=True
   )
   REWARD_PROMPT_ARN = reward_prompt_evaluator.arn
   print(f"Evaluator ARN: {REWARD_PROMPT_ARN}")

   ```

3. **Pass the ARN as `reward_prompt`** to `RLAIFTrainer` (instead of the builtin string).

See `code_templates/rlaif_custom_prompt.py` for the full code template.

---

## Notes

- `mlflow_experiment_name` and `mlflow_run_name` are optional but recommended for tracking.
- For continued fine-tuning from a previously trained model, pass a `ModelPackage` object as `model` instead of a base model string. See `continuous_customization.md`.
