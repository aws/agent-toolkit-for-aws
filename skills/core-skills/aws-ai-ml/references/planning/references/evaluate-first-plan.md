# Evaluate-First Plan

**Recommended for:** Users who want to check if finetuning is necessary to solving their problem, users who want to check which base model is best for their use case, users who don't want to commit to finetuning yet, and users who are open to suggestions

1. **Define Use Case** — Capture the business problem, users, and success criteria. _(Skill: use-case-specification)_
2. **Select Base Model** — Choose a base model from SageMaker Hub. _(Skill: model-selection)_
3. **Verify Environment** — Check SDK version, region, and execution role are configured. _(Skill: sdk-getting-started)_
4. **Evaluate Dataset** — Run a quality evaluation on the evaluation dataset: check its format, then either evaluate it against requirements the user states, or explore it for issues when the user is unsure what to check; the dataset-quality reference asks which. _(Skill: dataset-quality)_
5. **Transform Dataset** — Convert to SageMaker evaluation format if needed. _(Skill: dataset-transformation)_
6. **Evaluate Model** — Run the base model against the evaluation dataset and present results against success criteria. _(Skill: model-evaluation)_
7. **Decision Gate** — Present evaluation results. User decides whether to fine-tune or stop.

If the user decides to fine-tune after the decision gate, extend the plan:

8. **Select Finetuning Technique** — Choose the appropriate finetuning technique. _(Skill: finetuning-technique)_
9. **Evaluate Training Dataset** — Validate training data format. _(Skill: dataset-quality)_
10. **Transform Training Dataset** — Convert to training format. _(Skill: dataset-transformation)_
11. **Fine-Tune Model** — Train the model. _(Skill: finetuning)_
12. **Evaluate Finetuned Model** — Compare against base model results. _(Skill: model-evaluation)_
13. **Deploy Model** — Create an endpoint. _(Skill: model-deployment)_

At the decision gate, present data objectively against the user's success criteria. Do not recommend — let the user decide.

<!-- markdownlint-disable-file MD029 -->
