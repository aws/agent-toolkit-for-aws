# Dataset Quality & Validation

Validates dataset formatting and evaluates dataset quality for SageMaker model fine-tuning. Two modes, plus two sub-references for operators that run in the same dataset quality evaluation job as any other metric but need their own interpretation:

- **Format validation only**: checks schema compliance using `format_detector.py`. Detects which of the supported formats the dataset matches and reports compatibility. The procedure is `references/format-check.md`.
- **Quality evaluation**: evaluates the dataset against a requirements spec (the recommended path; the generation spec for synthetic-dataset-generation (SDG) output, or one authored with the user), plus built-in deterministic metrics, via a SageMaker AI dataset quality evaluation job. Generates a Jupyter notebook. The procedure is `references/quality-job.md` (Steps 6 to 11), then `references/quality-job-submit.md` (Steps 12 and 12b), then `references/results-and-report.md` (Step 13). A free-form exploratory analysis complements it for issues no spec anticipates: client-side before a spec exists (`references/exploratory-analysis.md`, from Step 7), or by the service as part of the job (Step 12).
- **Deduplication sub-reference** (`references/deduplication/overview.md`): `exact_dedup` and `fuzzy_dedup`, service-side exact and near-duplicate identification with a per-row decision. Run them alone through the sub-reference or alongside other metrics in one quality evaluation (`references/quality-job.md` Step 10.2); either way the sub-reference owns the interpretation (duplicate groups).
- **Taxonomy sub-reference** (`references/taxonomy/overview.md`): `taxonomy` discovers what tasks, domains, and quality tiers the data covers (us-east-1 only, calls Bedrock). Run it through the sub-reference, or add it to a quality evaluation in us-east-1 after confirming its cost (`references/quality-job.md` Step 10.2); either way the sub-reference owns the interpretation.

## Principles

1. **One thing at a time.** Each response advances exactly one decision. Never combine multiple questions in a single turn; a gate that names two questions as one gate (the bring-your-own-spec run-or-review gate) is one question.
2. **Confirm before proceeding.** Wait for the user to agree before moving to the next step.
3. **Don't read files until you need them.** Only read reference files when you've reached the workflow step that requires them.
4. **No narration.** Do not announce a tool call before making it or describe one after ('I will now read X', 'Let me run the detector', 'I have read the page'). Say the outcome and, when you pause, the question.
5. **No repetition.** If you said something before a tool call, don't repeat it after.
6. **Always end with a question when you pause for a decision.** Whenever you pause for user input, your response must end with a question. Nothing follows it: a summary, the plan, the results, the Output files block and every detail come before the question, never after. A thanks, a close, or "nothing else" is not a pause for a decision: it gets a one-sentence acknowledgment, no question, and no repeated closing block.
7. **No internal labels.** Never reveal internal workflow labels like "Path A", "Path B", "Step 2A", "v1", "v2", or script names to the user, and never the words "skill", "reference" or "page" for your own instructions ("the skill stops here", "the page requires me to"): say "I" or name the action. Just describe what you're doing in plain language. A job output path the user can open (an S3 URI, a file under the job's output prefix) is not an internal label.
8. **Working files.** Every file this capability downloads or writes (a generation spec, a data sample, a run log, a job's aggregate files) goes under the project directory, the working folder of the conversation, never `/tmp`, `mktemp` or the home directory. `references/results-and-report.md` (Step 13, Local copies) is the instance for the aggregate files.
9. **Format detection is a routing decision.** The format detector result determines whether the user can use quick mode (defaults) or must provide explicit column bindings. Unrecognized columnar formats are supported with explicit Views. Unrecognized nested formats have no validated workflow here; offer dataset-transformation to flatten first.
10. **Never offer downstream capabilities while evaluation is in progress.** Wait for the job to reach a terminal state before suggesting `finetuning` or any other next-step capability.

## Prerequisites

**For format validation:**

- A dataset file (local path or S3 URI)
- The fine-tuning strategy and base model (from conversation context, or asked in Step 3 of `references/format-check.md` if unknown)

**For quality evaluation (additional):**

- A dataset registered in the SageMaker AI Registry, with its Dataset ARN
- An S3 bucket for scorecard output
- An IAM role ARN with SageMaker trust relationship, or a configured `SageMakerConfig` providing one (settled at `references/quality-job.md` Step 11 before the plan)
- AWS Region: us-east-1 or us-west-2; `references/dataset-service-api.md` keeps the list
- The SDK installed as `../sdk-getting-started/references/sagemaker-python-sdk-setup.md` says; run the notebook with the kernel of the environment the setup page installed into (on a venv setup, register `./.venv` as the kernel).
- The AWS calls on these pages are written as AWS CLI commands, which run with or without the AWS MCP server; the AWS MCP server is recommended but not required.
- The SDK install is agreed in one place, the plan's Setup line of each path (`references/quality-job.md` Step 11 item 9, and Step 4 of the deduplication and taxonomy overviews), and runs only after the plan is confirmed; when the router's SDK prerequisite sends you to `sdk-getting-started` before this capability, check there only whether the SDK is installed as its setup page says, ask no install question, and carry the answer into the plan.

## Workflow

### Step 0: Check for prior context

Before starting, silently scan `<project-dir>/manifests/` for upstream capability outputs:

- `transformation_manifest_run_NNN.json`: if the dataset-transformation capability (DT) ran (e.g., the dataset was reshaped into a supported format), read the final output path and target format.

Pick the most recent relevant manifest and remember the fields for downstream steps. If no manifests exist, that's expected for a first run; do not prompt the user about this. The dataset quality evaluation itself does not write a manifest.

Also check conversation context: the dataset may have been generated via the synthetic-dataset-generation capability, validated previously, or brought by the user.

### Step 1: Determine evaluation scope

Based on the user's request, determine which mode to use, then read the page the row names and follow it:

| User intent | Mode and page |
|---|---|
| A calling capability asks only whether the format is valid (for example model-evaluation's "validate dataset format" step), or the user says "format only" / "just check the format" | Format validation only: read `references/format-check.md` (Steps 2 to 5), then return the verdict; do not offer or start a job |
| "Is my dataset formatted correctly?" / "Check my training data" / "Validate my evaluation dataset" / any dataset brought for evaluation or training without the word "only" | Quality evaluation, entered through the format check: read `references/format-check.md` (Steps 2 to 5), then `references/quality-job.md` from Step 6 |
| "Check data quality" / "Run DQ metrics" / "Run a scorecard" / "How good is my data?" / "Evaluate my data before fine-tuning" | Quality evaluation (includes format detection by the dataset quality evaluation job's container): start where the rule below the table says, at `references/format-check.md` or `references/quality-job.md` Step 6 |
| "Evaluate against my spec / requirements" / "Does my data meet X?" / "Check these rules on my data" / "Evaluate the generated data against its spec" | Quality evaluation, spec path: start where the rule below the table says and walk every step; the requirements the user stated are the spec's requirements (`references/quality-job.md` Step 7, `intent = knows-requirements`, then Step 10.1); when a spec file or S3 URI is already in the request, `references/bring-your-own-spec.md` |
| "Find duplicates" / "How many duplicates?" / "Near-duplicates" / "Audit duplicates before removing any" | Deduplication sub-reference: read `references/deduplication/overview.md` and follow it (per-row decisions, duplicate groups). If the user also wants a scorecard, run one quality evaluation instead and add `exact_dedup` / `fuzzy_dedup` to the selection in `references/quality-job.md` Step 10.2; read their results with `references/deduplication/references/result-interpretation.md` |
| "What's in my dataset?" / "What topics does my data cover?" / "Categorize my dataset" / "Coverage gaps" / "Is my data balanced across tasks?" | Taxonomy sub-reference: read `references/taxonomy/overview.md` and follow it (us-east-1 only, calls Bedrock; discovers task, domain, and quality category trees with per-row categories). If the user also wants a scorecard and the session is in us-east-1, run one quality evaluation instead and add `taxonomy` in `references/quality-job.md` Step 10.2 after confirming its cost; read its results with `references/taxonomy/references/result-interpretation.md` |
| "What languages are in my dataset?" / "Is my data all English?" / "Detect languages" / "How many rows would a language filter drop?" | Quality evaluation: `references/quality-job.md` with `language_detection` in the Step 10.2 selection (alone or with other metrics; no Bedrock cost). It needs an explicit View on one flat text column; its View rule is `references/on-request-metrics.md` (Language Detection). Read its results with `references/result-interpretation.md` (language detection check); to actually drop rows, hand off to dataset-transformation's `LanguageFilter` (`references/results-and-report.md`) |
| "Does my data contain PII?" / "Find emails, phone numbers, or SSNs in my data" / "How much personal data is in my dataset?" | Quality evaluation: `references/quality-job.md` with `pii_detection` in the Step 10.2 selection (calls Bedrock on a sample of rows). It needs an explicit View on one chat column (Role `Messages`) or one flat text column (Role `Text`); its View rule is `references/on-request-metrics.md` (PII Detection). Read its results with `references/result-interpretation.md` (PII detection check); to redact or drop the PII, hand off to dataset-transformation's `PiiRedaction` (`references/results-and-report.md`) |
| Ambiguous | Ask the user |

Where a quality evaluation starts:

- A quality evaluation of a local file or an S3 URI starts at `references/format-check.md` (Steps 2 to 5, the detector first) and continues at `quality-job.md` Step 6.
- A quality evaluation of a dataset whose Dataset ARN is already known (from a manifest, the conversation, or an SDG result handed in) starts at `quality-job.md` Step 6; the detector does not run, the format comes from the Dataset entity at Step 9.
- A spec handed in by a capability, or a spec file or S3 URI already in the request, starts at `references/bring-your-own-spec.md`.

From its start, every quality evaluation walks every step in order to Step 12 (`references/quality-job-submit.md`, the plan and its confirmation); no step is skipped because the request looks complete. The path pages and the sub-reference pages (`references/taxonomy/overview.md` and `references/deduplication/overview.md`, each with its own plan confirmation at Step 5) mark their stops "Wait for user"; each stop holds for every user request, in a chat and in an unattended run alike. A request that asks for everything up front ("run it yourself and wait", "just run it", "start it and don't wait") chooses the delivery mode and the run option only (`references/quality-job-submit.md`, Delivery Mode); it does not answer the intent question of `references/quality-job.md` Step 7, and it never waives the plan confirmation.

If the user's intent is ambiguous, ask the user to choose between a format check and a full quality evaluation, naming what each does: the format check is a quick check that the dataset schema matches a supported format; the quality evaluation runs diversity, toxicity, uniqueness, and spec-driven checks, generates a notebook, and takes a few minutes. Wait for the user's answer.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this capability. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- **Quality evaluation of an unrecognized nested dataset** (format `Custom` with any value a list of dicts). The service's Views bind flat columns only and cannot reach a nested structure. Offer dataset-transformation to flatten the data first, then evaluate the flat output. Never write transformation code inline.
- **The embedding-based metrics `remote_clique` and `chamfer_distance`.** The service lists them, but this capability has no validated workflow for them: leave them out of a metric selection, and when the user asks for one, say so and point at the service's metric list (`references/supported-metrics.md`, "Notes").
- **Quality evaluation of a `.tsv` or `.pq` file.** The format check (`scripts/format_detector.py`) stops on either extension; the job reads `.csv`, `.jsonl` and `.parquet`. Say so when the detector stops; a conversion or rename is the user's choice, never a requirement stated as the only way.

## Resources

- `scripts/format_detector.py`: format validation script (detects supported formats, reports compatibility)
- `code_templates/notebook_cells.py`: notebook cell templates with placeholders for the dataset quality evaluation
- `references/format-check.md`: path page, Steps 2 to 5 (locate, strategy and model, run the detector, summarize)
- `references/quality-job.md`: path page, Steps 6 to 11 (locate for the job, intent, register, validate format, decide, metrics, binding, parameters)
- `references/quality-job-submit.md`: path page, Steps 12 and 12b (confirm the plan, delivery mode, generate the code, the EvaluationConfig)
- `references/results-and-report.md`: path page, Step 13 (retrieve, data source rules, chat digest, next steps, visualizing)
- `references/exploratory-analysis.md`: the client-side free-form exploratory analysis of Step 7, read only on the "unsure" branch
- `references/drill-down.md`: the row-level drill-down procedure, read only when the user accepts the drill-down offer
- `references/structured-spec.md`: the structured `## Criteria` format and the Criterion grammar, read only when a spec takes the structured form
- `references/spec-examples/`: the 20 spec examples in three family pages; `references/spec-examples.md` is their index
- `references/spec-authoring.md`: the spec-authoring interview
- `references/strategy_data_requirements.md`: data format requirements per strategy
- `references/training-volume-requirements.md`: minimum record counts per strategy
- `references/supported-metrics.md`: full metric catalog with descriptions and defaults; the on-request families are `references/on-request-metrics.md`
- `references/on-request-metrics.md`: the five on-request metric families (data filters, duplicate detection, language detection, PII detection, dataset composition)
- `references/dataset-service-api.md`: API payloads for the dataset quality evaluation and client setup
- `references/dataset-import.md`: the hub import of a BYOD dataset (hub resolution, import)
- `references/output-schema.md`: output format for evaluation results
- `references/troubleshooting.md`: common errors and failure paths
- `references/format-metric-mapping.md`: which metrics apply to which input formats
- `references/result-interpretation.md`: threshold checks and the spec-driven evaluation checks
- `references/report-template.md`: template for the per-job `dq_report_<job-name>.md` written at Step 13
- `references/report-optional-sections.md`: the fill instructions for the duplicate detection and dataset taxonomy sections of the report, read only when one of those families ran
- `references/bring-your-own-spec.md`: entry for a caller (user or another capability) that already has a finished spec: lint if structured, one question, submit, report. No interview.
- `references/report-visualization.md`: how the agent generates the visualization of a run (chart guardrails, shape classification, Plotly patterns)
- `references/progress-check.md`: live-progress protocol for mid-job status queries
- `references/supported-formats.md`: format catalog + example responses for Custom datasets
- `references/custom-scorer-evaluation-dataset-formats.md`: dataset formats for Custom Scorer evaluation (Prime Math, Prime Code, Custom Lambda), read at Step 5 of `references/format-check.md` when the dataset is meant for one
- `references/deduplication/`: sub-reference: `exact_dedup` / `fuzzy_dedup` identification job, duplicate report with per-row decisions
- `references/taxonomy/`: sub-reference: `taxonomy` operator job (us-east-1 only, Bedrock), per-framing category trees, per-row categories and confidence, HTML report
