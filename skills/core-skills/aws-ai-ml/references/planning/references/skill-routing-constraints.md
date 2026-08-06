# Skill Routing Constraints

## Plan Completeness

- Generate the complete plan upfront. The plan presented to the user

  must include all steps needed to reach their goal. Do not generate
  a partial plan with the intent to add steps later.

- Each step must be executed by its designated skill. Do not perform

  a skill's work ad-hoc or inline within another skill.

## Mandatory Inclusion

- use-case-specification: Recommend by default in every plan

  unless the user explicitly declines or has an existing spec.

## Evaluate-First Path

When the user chooses to evaluate the base model before fine-tuning:

- model-selection MUST run before sdk-getting-started and

  dataset-evaluation.

- sdk-getting-started MUST run after model-selection and before

  dataset-evaluation.

- model-selection runs before model-evaluation.
- finetuning-technique is NOT required. It only enters the plan if

  the user decides to fine-tune after the decision gate.

## Direct Fine-Tuning Path

When the user chooses to go straight to fine-tuning:

- model-selection MUST run before sdk-getting-started.
- sdk-getting-started MUST run after model-selection and before

  dataset-evaluation.

- model-selection MUST run before finetuning-technique.
- finetuning-technique MUST run before dataset-evaluation (for

  training data) and finetuning. The technique must be known before
  training data can be validated or training can begin.

- dataset-evaluation should run after finetuning-technique and before

  finetuning, to catch format issues before training.

## Ordering Constraints

- model-selection MUST run before sdk-getting-started.
- sdk-getting-started MUST run after model-selection and before the

  first task that runs scripts or makes AWS API calls requiring an
  execution role (e.g., dataset-evaluation, finetuning,
  model-evaluation, model-deployment). It is not needed before
  conversational-only tasks like use-case-specification or
  model-selection.

## Skill Boundaries

- All dataset format changes MUST go through dataset-transformation.

  Do not write inline transformation code in other skills' notebooks.

- All model selection MUST go through model-selection.

  Do not resolve model IDs ad-hoc.

- All technique selection MUST go through finetuning-technique.

  Do not select techniques ad-hoc.

## Model-Selection Anti-Pattern

- **Do not resolve ambiguous constraints yourself when selecting or

  filtering models.** Terms like "lightweight", "fast", "small", or
  "cheap" are resolved through the use-case-specification →
  select-for-deployment pipeline, not by agent inference. If the user
  has not gone through use-case-specification, activate it — do not
  substitute your own interpretation of their words.
