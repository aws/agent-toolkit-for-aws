# End-to-End Model Customization Plan

**Recommended for:** users who are certain they want to finetune a model, and users who clearly communicate that they want to finetune a model

1. **Define Use Case** — Capture the business problem, users, and success criteria. _(Skill: use-case-specification)_
2. **Select Base Model** — Choose a base model from SageMaker Hub based on benchmarks and use case fit. _(Skill: model-selection)_
3. **Verify Environment** — Check SDK version, region, and execution role are configured. _(Skill: sdk-getting-started)_
4. **Select Finetuning Technique** — Choose a fine-tuning technique and validate compatibility with the selected model. _(Skill: finetuning-technique)_
5. **Generate Synthetic Dataset** — Author the data generation spec, then generate synthetic training data via the SageMaker DataPreparer API. Includes a sample-first review loop. _(Skill: synthetic-dataset-generation)_ _(Optional — only when the user needs to generate training data)_
6. **Label Dataset**: Unlabeled (or partially labeled) data gets its labels from the labeling plan, `references/auto-labeling-plan.md`. That plan runs first, and this one continues from its **Register and hand off** step with the labeled DataSet as the training data. _(Skill: auto-labeling)_ _(Optional — only when the user brings unlabeled data that needs labels before training)_
7. **Evaluate Dataset** — Evaluate the dataset against its specification (the generation spec for synthetic data, or a requirements spec authored with the user), plus built-in metrics on request; validates format and volume; writes a quality report. _(Skill: dataset-quality)_
8. **Address Dataset Quality Findings** — Based on quality evaluation results, one or more of: _(Optional — only when dataset-quality flags issues)_
   - **Clean or filter** — remove duplicates, filter toxic/malformed records, fix encoding. _(Skill: dataset-transformation)_
   - **Human review** — annotate records that need manual judgment (records that fail spec criteria, borderline quality). _(Skill: human-in-the-loop)_
   - **Generate more data** — create additional synthetic examples to address diversity/volume gaps. _(Skill: synthetic-dataset-generation)_ — loops back to step 5 → 7.
9. **Transform Dataset** — Convert the dataset to the required format for the selected fine-tuning technique and base model. _(Skill: dataset-transformation)_
10. **Fine-Tune Model** — Train a custom model using SageMaker. _(Skill: finetuning)_
11. **Evaluate Model** — Measure model performance against success criteria. _(Skill: model-evaluation)_
12. **Deploy Model** — Create an endpoint for inference. _(Skill: model-deployment)_

Not every plan needs every step. Users may skip steps if they already have the required artifacts (e.g., skip steps 5–6 if they already have labeled training data, skip steps 7–9 if they have validated data, or skip to deployment if they have a trained model).

**Note:** Evaluation datasets require a different format than training datasets (e.g., SageMaker Eval `query`/`response` vs SFT `prompt`/`completion`). If the user has a separate eval dataset, it may need its own validation and transformation pass before model evaluation.

**Note:** Step 8 actions are driven by dataset-quality findings. If dataset-quality finds no issues, skip step 8 entirely and proceed to step 9 (transform) or step 10 (fine-tune). If "Generate more data" is chosen, the flow loops back to steps 5 → 7 for another round of generation + evaluation.
