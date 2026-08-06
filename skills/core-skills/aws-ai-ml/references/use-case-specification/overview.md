
# Use Case Specification

Multi-turn conversation to gather use case details and produce a use case specification document.

## Principles

1. **One thing at a time.** Each response advances exactly one decision or collects one piece of information.
2. **Confirm before proceeding.** Wait for the user to approve the spec before considering this skill complete.
3. **Infer, don't interrogate.** Use what's already known from the conversation. Only ask when you truly can't infer.
4. **Do NOT ask about base model selection.** Model selection is handled exclusively by the model-selection reference.

## Workflow

### Step 0: Check for Existing Spec

Before starting discovery, check if a `*_use_case_spec.md` file already exists in the project. If it does, present it to the user and ask whether they want to reuse it, modify it, or start fresh.

### Step 1: Determine Intent

Check the plan (`PLAN.md`) or conversation context to determine whether the user wants to:

- **Fine-tune a model** → read `references/spec-for-finetuning.md` and follow it.
- **Deploy a base model** → read `references/spec-for-deployment.md` and follow it.

If the intent is already clear from the plan (e.g., the plan includes finetuning steps vs. only model-selection + model-deployment), use that. If ambiguous and not already resolved by the planning skill, ask:

> "Are you looking to fine-tune a model for your use case, or deploy a base model as-is?"

⏸ Wait for user response.

## Edit Protocol

- If the user requests changes pertaining to any information covered by use_case_spec.md, you must edit it accordingly and ask for confirmation again.
- The user can edit use_case_spec.md directly if they want to. If the user says they've updated the file directly, read it to get the latest in your context.

## References

- `references/spec-for-finetuning.md` — Discovery and spec generation workflow for fine-tuning
- `references/spec-for-deployment.md` — Discovery and spec generation workflow for base model deployment
