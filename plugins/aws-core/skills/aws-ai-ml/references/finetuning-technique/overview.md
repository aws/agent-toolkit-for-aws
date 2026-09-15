
# Finetuning Technique

Guides the user through selecting a fine-tuning technique based on their use case and validates compatibility with the selected model.

## When to Use

- User has decided to finetune and needs to choose a technique
- User wants to change their finetuning technique
- Technique needs to be validated against a selected model

## Prerequisites

- A base model has been selected (via model-selection reference). The model name and hub must be known.
- A `use_case_spec.md` file exists. If not, load the use-case-specification reference to generate it first.

## Workflow

### Step 1: Determine Finetuning Technique

Consult `references/finetune_technique_selection_guide.md` to recommend the best-fit technique based on the use case and the user's needs (SFT, DPO, RLVR, RLAIF).

Present the recommendation and reasoning to the user. Ask if they'd like to go with the recommendation or prefer a different technique.

### Step 2: Validate Technique Availability

1. Once the user confirms a technique, retrieve the finetuning techniques available for the selected model by running: `python finetuning-technique/scripts/get_recipes.py <model-name> <hub-name>`
   - This script filters to SFT, DPO, RLVR, and RLAIF, which have validated workflows in this skill. The model may support additional techniques (e.g. CPT, MTRL, PPO) that are not returned by this script.
2. If the chosen technique is available for the model, proceed to Step 3.
3. If the chosen technique is not available for the model, explain that the selected model does not support it on SageMaker and offer to go back to model-selection to pick a different model that supports the chosen technique. If the technique is one the model may support but is not returned by this script (e.g. CPT, MTRL, PPO), explain that this skill does not have a validated workflow for it and offer to help using general knowledge.

### Step 3: Confirm Selections

Present a summary to the user:

```
Here's what we've selected:
- Base model: [model name]
- Fine-tuning technique: [SFT/DPO/RLVR/RLAIF]

```

## References

- `references/finetune_technique_selection_guide.md` — Technique guidance (SFT/DPO/RLVR/RLAIF)
