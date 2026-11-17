# Recommendation Configuration Options

## Instance Types (optional)

For **latency** and **throughput** targets, the user can specify which instance types to evaluate:

> "Would you like to specify which instance types to evaluate, or let the service choose automatically?
>
> Examples: `ml.g5.xlarge`, `ml.g6.12xlarge`, `ml.p5.48xlarge`"

Note: **Cost** target does not support customer-specified instance types.

## Optimization (optional)

> "Should the service try to optimize the model?
>
> - **Kernel tuning** — Up to 30% improved TTFT and throughput
> - **Speculative decoding** — Lower latency via a draft model that predicts tokens ahead (requires a compatible draft model)
>
> **Heads up:** Without optimizations: 30–60 min. With: 2–10 hours.
>
> Default is yes (`advanced_optimization=True`). Set `advanced_optimization=False` to skip."

### Dataset Requirement for Throughput + Optimization

If **throughput** target AND `advanced_optimization=True`, a dataset is **required**. Without it, the job fails with a validation error.

Ask the user for a dataset (an S3 location), then **inspect it yourself** to figure out the format — don't quiz them on schema names:

> "Since you chose throughput with optimizations, I need a dataset to drive it. Point me at an S3 location — either a JSONL dataset of prompts, or your endpoint's SageMaker Data Capture prefix to replay real traffic. What's the S3 URI?"

⏸ Wait for user.

When the user provides the S3 URI, read a couple of records and identify the schema, then build the workload in Cell 3 of `../../code_templates/optimize-recommendation.py` with `Workload.from_dataset(...)` instead of `Workload.synthetic(...)`.

`custom_dataset_type` is an **optional hint** naming the dataset's schema (not required — omit to let AIPerf auto-detect). See `benchmarking-guidance.md` → "Dataset schema hint (`custom_dataset_type`)" for the schema → value mapping and the dataset-transformation fallback for unsupported formats.

The `Workload.from_dataset(...)` alternative is **Cell 3 of `../../code_templates/optimize-recommendation.py`** (a commented-out block in that cell) — swap it in for `Workload.synthetic(...)` and fill `[DATASET_S3_URI]` and `custom_dataset_type` (from the schema you detected, or omit for auto-detection). Generate it from the template rather than writing it inline.

## Workload Config

Required. Defined as Cell 3 of the notebook (from `../../code_templates/optimize-recommendation.py`). `generate_deployment_recommendations` takes the `Workload` object via `workload=` and **auto-creates** the underlying `AIWorkloadConfig` from it. `workload_config_name=` is the **name to give that newly-created config** (not a reference to a pre-existing one) — the template passes the agent-generated `WORKLOAD_CONFIG_NAME` from Cell 2; if you omit it, the SDK auto-generates a name. Do not pass a config name into `workload=` — that parameter expects a `Workload` object.

For a model already on a SageMaker endpoint, size the workload from the endpoint (concurrency from CloudWatch, prompts from Data Capture when it's on) — see `workload-from-endpoint.md`.

## Inference Framework (optional)

> "Which inference framework?
>
> - **VLLM** — High-performance serving with PagedAttention
> - **LMI** — SageMaker Large Model Inference container
>
> Default: auto-selected based on the model."
