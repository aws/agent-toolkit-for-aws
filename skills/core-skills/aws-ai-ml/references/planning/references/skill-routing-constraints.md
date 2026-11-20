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
  dataset-quality.
- sdk-getting-started MUST run after model-selection and before
  dataset-quality.
- model-selection runs before model-evaluation.
- finetuning-technique is NOT required. It only enters the plan if
  the user decides to fine-tune after the decision gate.

## Direct Fine-Tuning Path

When the user chooses to go straight to fine-tuning:

- sdk-getting-started MUST run after model-selection and before
  dataset-quality.
- model-selection MUST run before finetuning-technique.
- finetuning-technique MUST run before dataset-quality (for
  training data) and finetuning. The technique must be known before
  training data can be validated or training can begin.

## Ordering Constraints

- model-selection MUST run before sdk-getting-started when model-selection is in the plan.
- sdk-getting-started MUST run after model-selection and before the
  first task that runs scripts or makes AWS API calls requiring an
  execution role (e.g., synthetic-dataset-generation, dataset-quality,
  finetuning, model-evaluation, model-deployment). It is not needed
  before conversational-only tasks like use-case-specification or
  model-selection.
- synthetic-dataset-generation MUST run after finetuning-technique
  **when finetuning is part of the plan** (technique and model must
  be known before generating training data). For standalone tabular
  data generation (database seeding, test data, augmentation without
  downstream training), synthetic-dataset-generation can run
  independently without finetuning-technique. It MUST still run
  before dataset-quality when both are present.
- dataset-quality should run after finetuning-technique and before
  finetuning. It handles both format validation and quality
  evaluation (spec-driven against a requirements document, plus
  deterministic metrics).

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

## Conditional Inclusion

- synthetic-dataset-generation: Include when the user does not have
  training data, wants to generate or augment data, or mentions
  synthetic data. Also include for non-training use cases: database
  seeding, test data generation, data augmentation, anonymization,
  Feature Store population, demo environments, or schema validation.
  The downstream consumer does NOT need to be a training job.
  Exclude when the user already has a dataset ready for evaluation
  or training.

## Skill Boundaries (synthetic-dataset-generation + dataset-quality)

- synthetic-dataset-generation handles both spec authoring and data
  generation end-to-end. Do not use a separate skill for spec
  creation.
- All dataset format validation and quality evaluation MUST go
  through dataset-quality. Do not run format_detector.py or dataset quality evaluation API
  calls ad-hoc in other skills.

## Routing: dataset-quality

- Trigger phrases: "check data quality", "run dataset-quality metrics", "is my
  dataset okay", "evaluate my data", "check my training data", "how
  good is my training data", "assess my dataset quality", "check
  diversity", "check toxicity", "run a scorecard", "what languages
  are in my dataset", "is my data all English", "does my data
  contain PII"; for the spec path: "evaluate my data against my
  requirements", "does my data meet my spec", "check my policy on
  every row", "classify my rows as A or B", "is every category at
  least 10 percent"; for the deduplication sub-reference: "find
  duplicates", "how many duplicates", "near-duplicates", "is my data
  repetitive", "audit duplicates before removing"; for the taxonomy
  sub-reference: "what's in my dataset", "what topics does my data
  cover", "taxonomy of my data", "cluster my prompts", "coverage gaps"
- Supports format validation, quality evaluation (built-in metrics, a
  requirements spec, or both; spec-driven is the recommended path),
  and both in one step. When the customer is unsure what to check,
  the skill offers an exploratory analysis inside the quality
  evaluation.
- The job runs on a registered dataset: the skill registers a file or
  S3 URI itself, and the job runs in the dataset's region. The skill
  does not mutate the dataset; every finding is reported, and acting
  on it (dropping duplicates, filtering, redacting, regenerating,
  relabeling) is a later step of another skill (the list below).
- The spec path (`references/spec-authoring.md`,
  `bring-your-own-spec.md`, `structured-spec.md`, the examples under
  `references/spec-examples/`): a requirements spec authored with the
  customer or brought by them, with optional reference documents that
  its grounding criteria are judged against (`ContextDocumentsS3Uri`),
  a judge model and a sample size. Criteria are deterministic checks,
  model-judged qualities, and measurements or labels in the customer's
  own values with aggregates over them (shares, thresholds).
  Classification into the customer's categories or rules, balance
  against a required share, and any check in the customer's words
  route here, not to taxonomy. A calling skill can hand in a finished
  spec and receive the outputs without an interview.
- For BYOD (bring your own data) workflows, include dataset-quality
  in the plan to validate format and evaluate quality before
  finetuning — against a requirements spec authored with the user
  (recommended), built-in metrics, or both.
- For synthetic-dataset-generation workflows, include
  dataset-quality after synthetic-dataset-generation to evaluate the
  generated data against the generation spec — dataset-quality offers
  a focused dataset quality spec distilled from it first, the generation
  spec as-is second. Format *classification* can be treated as
  known since synthetic-dataset-generation output format is known — but dataset-quality's
  training volume check MUST still run. Known-good format provenance
  says nothing about record count, and a split between generation and
  training can leave the training partition below the minimum even
  when the generated pool cleared it.
- Deduplication sub-reference (`references/deduplication/`): duplicate
  questions route here. It identifies exact and near duplicates, alone
  or with the other metrics in the same dataset quality evaluation
  job, and removes nothing. Include it after
  synthetic-dataset-generation or a BYOD import and before the full
  evaluation or finetuning when the plan needs duplicates found;
  independent of model-selection and finetuning-technique. Removing
  duplicates from a small local file inside a transformation spec
  stays with dataset-transformation.
- Taxonomy sub-reference (`references/taxonomy/`): questions about
  what the data covers route here when the customer has no categories
  of their own. It discovers the data's composition in fixed framings
  (task, domain, quality tier), alone or with the other metrics in the
  same job, and runs only in us-east-1 (do not plan it in another
  region). It is not classification into customer-defined categories
  (the spec path) and NOT a substitute for auto-labeling (user-defined
  label set). Include it after synthetic-dataset-generation or a BYOD
  import when the plan needs the data's composition before deciding
  what to filter (dataset-transformation) or generate more of
  (synthetic-dataset-generation). Independent of model-selection and
  finetuning-technique.
- After dataset-quality completes, route based on findings:
  - Low uniqueness, or rows flagged as duplicates → the deduplication
    sub-reference when the question is which rows are duplicates and
    of what; dataset-transformation (dedup) to remove them, or when
    the user only wants a cleaned local file
  - Unclear what the data covers, or whether coverage matches the
    use case → the taxonomy sub-reference (map tasks, domains, and
    quality tiers before deciding what to filter or generate;
    us-east-1), or the spec path when the customer has categories of
    their own
  - Toxic records, encoding issues, length violations →
    dataset-transformation (filter, clean)
  - Rows flagged by language_detection → dataset-transformation
    LanguageFilter with the same languages / min_score on the same
    column (it drops exactly the flagged rows)
  - PII found by pii_detection → dataset-transformation PiiRedaction
    on the same column, with the action the user picks (dataset-quality only
    estimates on a sample; it chooses no action)
  - Rows that fail the spec's checks (`dq_spec_eval_pass` false) or score
    low on a graded spec criterion, ambiguous quality, borderline cases
    → human-in-the-loop (human annotation/review)
  - Low diversity, dataset too small, insufficient coverage
    → synthetic-dataset-generation (generate more data, loop back
    to dataset-quality for re-evaluation)
  - Unlabeled or partially labeled records that need labels
    → auto-labeling (label at scale with per-row confidence)
  - No issues → proceed to dataset-transformation (format
    conversion) or finetuning

## Routing: auto-labeling

- Trigger phrases: "label my data", "auto-label", "I have unlabeled
  data", "classify these records", "generate labels", "tag this
  dataset", "annotate at scale", "label then fine-tune", "confidence
  scores for my labels", "bootstrap labels".
- auto-labeling turns an unlabeled corpus + a labeling spec into a
  labeled dataset with per-row confidence scores and a held-out
  accuracy report, and registers the result as a versioned
  `<name>-labeled` DataSet ARN. It authors/induces the spec itself
  when the user has none, and needs no labeled seed (its cold-start
  path bootstraps one via human-in-the-loop).
- sdk-getting-started MUST run before auto-labeling — the same ordering rule as
  dataset-quality and finetuning.
- auto-labeling MUST run before any step that consumes its labeled
  output: dataset-quality (score the labeled dataset; its
  held_out_report is a quality signal), dataset-transformation
  (convert the labeled DataSet to a training format), finetuning, or
  model-evaluation. Downstream steps consume the labeled data by the
  registered DataSet ARN; the corpus run's labels stay behind the API.
- synthetic-dataset-generation and use-case-specification are
  upstream producers when present: synthetic-dataset-generation when the corpus to label is
  synthetic, use-case-specification for the labeling goal/taxonomy.
  Neither is required — a user can bring their own corpus and spec.
- auto-labeling routes its low-confidence tail and spot-check to
  human-in-the-loop for review by the review DataSet ARN (and has
  people label its cold-start sample there). human-in-the-loop shows
  the rows blind and returns only its export: one row per reviewed
  record with the row's `id`, the label and completed / skipped. For an
  auto-labeling review set it skips its own edit hand-off to
  dataset-transformation. auto-labeling folds the export (seed
  bootstrap / spec refinement, the spot-check verdict) and applies the
  corrections itself, as one dataset-transformation overlay by id,
  whose output becomes the labeled DataSet's next version.
  This is a loop, not a one-way hand-off — after human-in-the-loop
  completes, the plan returns to auto-labeling, then proceeds with the
  corrected dataset.
- auto-labeling does NOT require model-selection or
  finetuning-technique — labeling is upstream of the training-format
  decision.

## Routing: human-in-the-loop

- Trigger phrases: "set up annotation", "review samples", "set up
  Label Studio", "annotations are done", "summarize annotation
  results", "apply the annotations", "incorporate human feedback",
  "annotate my data", "review records", "human review", "need human
  feedback", "manual review"
- human-in-the-loop handles the full annotation cycle: preview data,
  choose review mode (local chat review or Label Studio), draft
  annotation questions, collect feedback, and hand off edits to
  dataset-transformation.
- human-in-the-loop SHOULD run after dataset-quality when quality
  signals indicate records that need human judgment, and after
  auto-labeling to review its low-confidence tail and spot-check
  (auto-labeling hands over the review DataSet ARN and a hand-off
  spec; human-in-the-loop shows the rows blind and returns only the
  export, one row per record with its `id` and label; auto-labeling
  folds it into its seed/spec and applies the corrections itself, so
  the edit hand-off below does not run for that review set). It can
  also be triggered directly by the
  user at any point if they want to annotate or review dataset
  records.
- human-in-the-loop MUST have a data file available before it can
  proceed. If the plan includes HITL, ensure a prior step produces
  or identifies the dataset to review.
- human-in-the-loop hands off dataset edits to
  dataset-transformation, except for an auto-labeling review set, whose
  corrections auto-labeling applies. It does NOT modify the dataset
  itself.
