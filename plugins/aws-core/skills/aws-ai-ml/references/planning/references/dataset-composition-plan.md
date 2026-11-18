# Typical End-to-End Dataset Processing Plan

A typical dataset processing workflow follows these steps in order:

1. **Define Use Case** — Capture the business problem, target dataset characteristics, and success criteria. *(Skill: use-case-specification)*
2. **Generate Synthetic Dataset** — Author the data generation spec (fields, distributions, quality standards, verification rules), then create a synthetic dataset using the SageMaker DataPreparer API. Includes a sample-first review loop: generate a small batch, let the user review quality, then run full generation. *(Skill: synthetic-dataset-generation)*
3. **Evaluate Dataset Quality** — Evaluate the dataset against its spec (for synthetic data: a focused data-quality spec distilled from the generation spec, or the generation spec as-is; for BYOD: a requirements spec authored with the user) plus built-in metrics on request, via the dataset quality evaluation API (`create_job` with `JobCategory=DataQualityEvaluation`). Requires a `DatasetArn` (HubContent Dataset ARN). Writes a quality report. *(Skill: dataset-quality)*
4. **Label Dataset**: Turn an unlabeled (or partially labeled) dataset into a labeled one: draft/induce a labeling spec, label at scale with per-row confidence scores, and register the result as a versioned DataSet. *(Skill: auto-labeling)* *(Optional: when dataset-quality finds records missing labels)*
5. **Human Review** — Set up annotation to collect human feedback on records that need manual review (e.g., ambiguous quality, low-confidence records flagged by dataset-quality or auto-labeling). Supports local in-chat review or Label Studio. *(Skill: human-in-the-loop)* *(Optional — when quality evaluation or auto-labeling flags records needing human judgment, or user wants to annotate/review records manually)*

Not every plan needs every step. Common variations:

- **Sample → Generate → Evaluate**: Full workflow with quality gate — sample first, review, full generation, then scorecard (steps 1-3).
- **Generate + Evaluate**: User wants synthetic data and wants to verify its quality (steps 1-3, no sampling).
- **Generate only**: User just needs synthetic data, no quality evaluation needed (steps 1-2).
- **Evaluate only (BYOD)**: User has their own dataset and wants a quality scorecard (steps 1, 3). Import via `import_hub_content`, then evaluate.
- **Evaluate + Human Review**: User has data, runs quality evaluation, then reviews flagged records manually (steps 1, 3, 5).
- **Label (BYO unlabeled data)**: when labeling the user's data is the goal, this is not a composition plan. Path 5 of the workflow choice gate and its disambiguation (`planning/overview.md`) send it to `references/auto-labeling-plan.md`, or straight to the `auto-labeling` reference when only the labels are needed.
- **Skip use case**: If the user already has a clear specification or has previously defined one, step 1 can be skipped.

## Common Protocols

### Client Setup

All steps in this plan run through the SageMaker Python SDK (V3), which exposes
the dataset generation and evaluation operations via the `DataPreparer` API — so
you never assemble a raw client, custom endpoint, or job ARNs by hand. The SDK
does rely on a service model that the `sdk-getting-started` skill installs during
setup (Cell 0), but the `DataPreparer` API wraps those underlying client and
endpoint calls for you. Activate the `sdk-getting-started` skill to install the
SDK, then construct a session:

```python
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
session = Session()
```

The individual skills own the exact `DataPreparer` calls for each step:

- **Synthetic generation** — `DataPreparer.generate(...)`. See the
  `synthetic-dataset-generation` skill (`references/api-reference.md`).
- **Quality evaluation** — `DataPreparer.evaluate(...)`. See the `dataset-quality`
  skill (`references/dataset-service-api.md`), which covers job config, spec-driven
  evaluation, polling, output layout, and troubleshooting.
- **Transformation** — see the `dataset-transformation` skill.

### Job Lifecycle

`InProgress` → `Completed` | `Failed` | `Stopping` | `Stopped`

`DataPreparer.generate()` / `DataPreparer.evaluate()` are blocking by default
(`wait=True`) and return a rehydrated `DataSet` (for a quality evaluation, the input dataset; the results are listed in the job's `metadata.json`). Submit with `wait=False` to get
a job handle instead, then call `job.wait()` to poll `DescribeJob`, stream logs,
and render progress; the terminal states are `Completed`, `Failed`, and `Stopped`.

### Job Categories

- `SyntheticDataGeneration` — Generates synthetic training data
- `DataQualityEvaluation` — Evaluates dataset quality (scorecard)

### IAM Requirements

The role passed to `DataPreparer(role=...)` must trust `sagemaker.amazonaws.com`. See
`../../sdk-getting-started/references/execution-role-setup.md` for the required trust principals and managed policies.

### Troubleshooting

For step-specific errors and their fixes, consult the owning skill's reference:
generation (`synthetic-dataset-generation`), quality evaluation
(`dataset-quality/references/dataset-service-api.md`), and transformation
(`dataset-transformation`). For SDK install and credential issues, see
`sdk-getting-started`.
