# Recommendation Workflow

Guide the user through creating and running an AI Recommendation Job. A recommendation job takes a model in S3, deploys it on multiple candidate instance types, benchmarks each configuration (with optional optimizations like kernel tuning and speculative decoding), and returns a ranked list of deployment options with expected performance metrics and deployable ModelPackages.

An AI Recommendation Job is not a SageMaker Inference Recommender job. When the user asks for an AI Recommendation Job or deployment recommendations, use this workflow; don't call `aws sagemaker create-inference-recommendations-job` or `list-inference-recommendations-jobs` unless the user names Inference Recommender.

## Applies to

(Canonical statement of what recommendations support — other references defer here.)

- **Models**: open-source GenAI **base models** (not Nova, not proprietary models, and **not LoRA adapters** — base models only). Two ways to supply the model:
  - **Your own HuggingFace-format weights in S3** (config.json + weights) — `ModelBuilder(model_path="s3://…")`. Provenance doesn't matter (exported, `download_huggingface_model`-staged, etc.), only that it's a readable S3 copy.
  - **A SageMaker JumpStart base model** — `ModelBuilder.from_jumpstart_config(...)` then `build()`, which resolves the model's JumpStart cache S3 artifacts for the job. Works for **ungated** JumpStart models; a **gated** model resolves to a private cache the role can't read and the job fails with an *Access denied* / *Invalid ModelSource.S3.S3Uri* error — stage its weights to your own S3 (`huggingface-to-s3.md`) and use the S3 path instead.
- **Deployment target**: SageMaker endpoints. (Recommendations produce ModelPackages that deploy to SageMaker, not Bedrock.)
- **Regions**: see `model-deployment/overview.md` → Optimization applicability (single source of truth).

## Step 1: Gather Model Information

First determine the model source (see **Applies to**):

- **A model already on a SageMaker endpoint** — the user names an endpoint or inference component, for example to right-size it. Read `workload-from-endpoint.md`: it finds the model behind the endpoint (one of the two sources below) and sizes the workload from the endpoint's traffic.
- **JumpStart base model** — the user names a JumpStart model id (or model-selection resolved one). No S3 URI needed; the builder resolves the JumpStart artifacts. You need a candidate **instance type** for the `Compute(...)` config (model-selection's resolved instance is a good default).
- **Own HF-format weights in S3** — the user has their own copy in S3. You need the **Model S3 URI**.

Either way you also need:

- **IAM Role ARN** — Execution role with SageMaker and S3 permissions. Infer from the SageMaker session's default execution role; only ask the user if none can be resolved.
- **S3 output location** — Where recommendation results should be stored (agent can infer from the model S3 URI bucket, or the session default bucket, if not provided)
- **Tokenizer** — HuggingFace tokenizer id for the model (e.g., `meta-llama/Llama-3.2-1B`). Used by `Workload.synthetic(...)` to generate representative prompts. Infer it from the model name or the model's `config.json` if the user doesn't provide it.

If the model source isn't already clear, ask for the one input that identifies it:

> "What would you like to run recommendations on?
>
> - A **JumpStart base model** — just give me the JumpStart model id, or
> - **Your own model in S3** — the S3 URI where the HuggingFace-format weights are stored (e.g., `s3://my-bucket/models/llama-3-8b/`)
>
> Either way it must be a base model — the recommendation workflow does not support LoRA adapters. I'll infer the tokenizer from the model and use your session's default execution role unless you'd like to specify otherwise."

⏸ Wait for user.

**Region check:** Verify the model's S3 bucket is in a supported region. If the user's default region is not supported, inform them and suggest a supported region.

## Step 2: Choose a Performance Target

| Target         | Metric       | What It Optimizes                                                   |
| -------------- | ------------ | ------------------------------------------------------------------- |
| **Cost**       | `cost`       | Lowest cost per hour while meeting baseline performance             |
| **Latency**    | `ttft-ms`    | Lowest time-to-first-token                                          |
| **Throughput** | `throughput` | Highest output tokens per second                                    |

Ask the user:

> "What's most important for your use case?
>
> 1. **Cost** — Find the cheapest instance that meets performance requirements
> 2. **Latency** — Minimize time-to-first-token (best for interactive/chat)
> 3. **Throughput** — Maximize tokens per second (best for batch processing)"

⏸ Wait for user.

## Step 3: Configure Options

For instance types, optimization, dataset, workload config, and inference framework options, read `recommendation-options.md`.

## Step 4: Confirm the Configuration

Before generating any code, summarize the values collected across Steps 1–3 and confirm once:

> "Here's the recommendation job I'll set up — ok, or would you like to change anything?
>
> - Model (use whichever source applies):
>   - S3 weights: `<model-s3-uri>` (tokenizer `<tokenizer>`), or
>   - JumpStart: `<jumpstart-model-id>` on `<instance-type>` (tokenizer `<tokenizer>`)
> - Execution role: `<role-arn>`
> - Output location: `s3://<bucket>/<prefix>/`
> - Performance target: `<cost | latency | throughput>`
> - Instance types: `<inferred/default, or user-specified>`
> - Optimization: `<on (default) | off>`; framework: `<default | VLLM | LMI>`
> - Workload: `<input/output tokens, concurrency, request_count — or dataset S3 URI>`"

Then proceed to generate the notebook. If the user wants to change a value, they'll say so — don't pause for re-confirmation of information already provided.

## Step 5: Generate Code

Generate a Jupyter notebook or a Python script — read `../code_output_guide.md` for the mode choice and output format rules (the template's `# NOTEBOOK_ONLY` markers make it dual-mode). Each cell's content comes from `../../code_templates/optimize-recommendation.py`, split on the `# Cell N:` comments. The template uses the SageMaker Python SDK (`>=3.20.0`; Cell 1 installs it in notebook mode), not boto3.

- **Cell 0** (markdown): Section header
- **Cell 1**: Setup (`%pip install` — notebook only)
- **Cell 2**: Configuration (imports, `set_attribution`, placeholders)
- **Cell 3**: Define the Workload (`Workload.synthetic(...)`, or `Workload.from_dataset(...)`)
- **Cell 4**: Run the Recommendation Job (`ModelBuilder(...).generate_deployment_recommendations(...)`, blocks until terminal)
- **Cell 5**: Review Recommendations (`model_builder.recommendations`)
- **Cell 6**: Deploy Top Recommendation (only include if user wants to deploy)
- **Cell 7**: Save Manifest

### Placeholders

Cell 2:

- `[REGION]` → AWS region (must be a supported region)
- `[MODEL_S3_URI]` → Model S3 URI from Step 1 (S3-weights source only)
- `[JUMPSTART_MODEL_ID]` / `[INSTANCE_TYPE]` → only for the JumpStart source (Cell 4, Model source B): the JumpStart model id and a candidate instance type for `Compute(...)`
- `[ROLE_ARN]` → Execution role. Infer from the SageMaker session's default execution role; only ask if none can be resolved.
- `[S3_OUTPUT_LOCATION]` → Full S3 URI for output (e.g., `s3://my-bucket/rec-output/`)
- `[RECOMMENDATION_JOB_NAME]` → Agent-generated name (e.g., `rec-<model>-<timestamp>`)
- `[WORKLOAD_CONFIG_NAME]` → Agent-generated name (e.g., `rec-config-<model>`)
- `[PERFORMANCE_METRIC]` → `cost`, `ttft-ms`, or `throughput` from Step 2
- `[TOKENIZER]` → HuggingFace tokenizer id for the model (e.g., `meta-llama/Llama-3.2-1B`)

Cell 3 (workload parameters; for a model already on an endpoint, take them from `workload-from-endpoint.md`):

- `[INPUT_TOKENS_MEAN]` → Average input token count from user
- `[INPUT_TOKENS_STDDEV]` → Std dev of input tokens (default 50)
- `[OUTPUT_TOKENS_MEAN]` → Average output token count from user
- `[OUTPUT_TOKENS_STDDEV]` → Std dev of output tokens (default 30)
- `[CONCURRENCY]` → Concurrent requests from user (default 1)
- `[REQUEST_COUNT]` → Total requests (default 100)
- `[DATASET_S3_URI]` → S3 URI for dataset (only if throughput + optimization)

Cell 6:

- `[ENDPOINT_NAME]` → Agent-generated endpoint name

Cell 7:

- `[PROJECT_DIR]` → absolute path to the user's project directory where the run manifest is written (e.g. `/home/user/my-project`); use the directory established by the `directory-management` reference, or the current working directory if none.

### Conditional cells

- If throughput + optimization: a dataset is required. Build the workload in Cell 3 with `Workload.from_dataset("[DATASET_S3_URI]", custom_dataset_type="<schema>", tokenizer=TOKENIZER, ...)` instead of `Workload.synthetic(...)`. `custom_dataset_type` is an **optional hint** — if you've identified the dataset's schema, pass the matching value so AIPerf parses records correctly; if you're unsure, omit it and AIPerf attempts auto-detection. See `recommendation-options.md` (which defers to `benchmarking-guidance.md`) for the full format→value mapping, including `sagemaker-datacapture` for replaying captured endpoint traffic.
- If the model is a **JumpStart base model** (no S3 copy of the user's own): use Cell 4's "Model source B" block — `ModelBuilder.from_jumpstart_config(...)` + `build()` instead of `ModelBuilder(model_path=...)`. If the job then fails with an *Access denied* / *Invalid ModelSource.S3.S3Uri* error, the model is gated; stage its weights to S3 (`huggingface-to-s3.md`) and switch to the S3 source.
- If user specified instance types: uncomment `instance_types=[...]` in the `generate_deployment_recommendations(...)` call in Cell 4.
- If user disabled optimization: uncomment `advanced_optimization=False` in Cell 4.
- If user chose a framework: uncomment `framework="VLLM"` (or `"LMI"`) in Cell 4.
- Job wait time is handled by the SDK (`wait=True`); no manual polling loop or `MAX_WAIT` is needed. Without optimizations a job typically finishes in 30–60 min; with optimizations enabled (default) it can take 2–10 hours.
- Cell 6 is only included if the user wants to deploy after reviewing results.

## Step 6: Present Recommendations

Read `interpreting-results.md` and present the recommendations to the user following the "Recommendation Job Results" section guidance.

After presenting results, offer next steps:

> "What would you like to do next?
>
> - **Deploy the recommended configuration** — I can help create a SageMaker endpoint using the top recommendation
> - **Run another recommendation** — Try different performance targets (cost vs latency vs throughput)
> - **Compare results** — Run with different instance types or optimization settings
> - **Done** — No further action needed"

If the user wants to deploy, add Cell 6 from the template to the notebook.
