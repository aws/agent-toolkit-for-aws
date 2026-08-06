# Evaluate-First Plan

**Recommended for:** Users who want to check if finetuning is necessary to solving their problem, users who want to check which base model is best for their use case, users who don't want to commit to finetuning yet, and users who are open to suggestions

1. **Define Use Case** — Capture the business problem, users, and success criteria. _(Skill: use-case-specification)_
2. **Select Base Model** — Choose a base model from SageMaker Hub. _(Skill: model-selection)_
3. **Verify Environment** — Check SDK version, region, and execution role are configured. _(Skill: sdk-getting-started)_
4. **Evaluate Dataset** — Validate the evaluation dataset (query/response format). _(Skill: dataset-evaluation)_
5. **Transform Dataset** — Convert to SageMaker evaluation format if needed. _(Skill: dataset-transformation)_
6. **Evaluate Model** — Run the base model against the evaluation dataset and present results against success criteria. _(Skill: model-evaluation)_
7. **Decision Gate** — Present evaluation results. User decides whether to fine-tune or stop.

If the user decides to fine-tune after the decision gate, extend the plan:

1. **Select Finetuning Technique** — Choose the appropriate finetuning technique. _(Skill: finetuning-technique)_
2. **Evaluate Training Dataset** — Validate training data format. _(Skill: dataset-evaluation)_
3. **Transform Training Dataset** — Convert to training format. _(Skill: dataset-transformation)_
4. **Fine-Tune Model** — Train the model. _(Skill: finetuning)_
5. **Evaluate Finetuned Model** — Compare against base model results. _(Skill: model-evaluation)_
6. **Deploy Model** — Create an endpoint. _(Skill: model-deployment)_

At the decision gate, present data objectively against the user's success criteria. Do not recommend — let the user decide.
