# Benchmark Workflow

Guide the user through creating and running an AI Benchmark Job to measure inference performance (latency, throughput) on an existing SageMaker endpoint.

**Read `benchmarking-guidance.md` first** for the know-how that shapes the choices below — when a benchmark stops (`request_count`, not a timer), how many requests a given percentile needs (e.g. p99 needs ≥ ~1000 requests), synthetic vs. dataset vs. real-traffic selection (and why speculative-decoding setups need real data), and comparability rules.

## Applies to

- Benchmarking scope (supported endpoint types, and the not-Bedrock/HyperPod rule incl. the don't-search directive): see `model-deployment/overview.md` → Optimization applicability (single source of truth). Custom (non-OpenAI) endpoint formats are handled via template mode (see Step 3).
- **Regions**: see `model-deployment/overview.md` → Optimization applicability (single source of truth).

## Step 1: Identify the Endpoint

You need the **endpoint name** and its **region**. Everything else (job name, workload-config name, S3 output location, tokenizer) the agent infers and confirms — do not make the user supply them.

If the user doesn't know their endpoint name:

> "I can look up your SageMaker endpoints. Would you like me to list them?"

Run `aws sagemaker list-endpoints --status-equals InService` to list candidates. Run `aws sagemaker describe-endpoint --endpoint-name <name>` to confirm it exists, capture its region, and read the model behind it. If the endpoint uses inference components, run `aws sagemaker list-inference-components --endpoint-name-equals <name>` to enumerate them. (The AWS MCP server is recommended but not required — the runtime routes these CLI calls through it automatically when available.)

**Determine the request/response format yourself — don't ask the user.** Read the container image/env vars via `aws sagemaker describe-model --model-name <name>` (LMI/TGI/vLLM → OpenAI ChatCompletions → synthetic mode). If still ambiguous, one probe (`aws sagemaker-runtime invoke-endpoint` with `{"messages":[...], "max_tokens":8}`) settles it — but a probe sends real inference, so gate it behind the Step 2 confirmation (don't send it before the user agrees). A non-OpenAI shape → template mode.

**Region / Bedrock check:** confirm the endpoint is in a supported region (see Applies-to). If the "endpoint" is actually Bedrock, this workflow can't benchmark it — tell the user, and offer to benchmark it if they deploy it to a SageMaker endpoint.

## Step 2: In-Service Safety Check

Benchmarking (and the Step 1 format probe) sends real inference load that can add latency for live users. If the endpoint was just created in this conversation, proceed. Otherwise warn that it's `InService`, suggest a dedicated copy if it serves production traffic, and ⏸ wait for explicit confirmation before sending any load (including the probe).

## Step 3: Choose the Workload Source

The workload defines the traffic the benchmark sends. Pick the source that matches the user's intent:

| Intent | Source | SDK call |
| ------ | ------ | -------- |
| Standard perf check / "how much can it serve" (OpenAI ChatCompletions endpoint) | **Synthetic** | `Workload.synthetic(...)` |
| **Load test** — push high concurrency to find the ceiling | **Synthetic**, high `concurrency` + higher `request_count` | `Workload.synthetic(...)` |
| Endpoint speaks a **custom (non-OpenAI) format** | **Template** — a Jinja2 request template + JMESPath response field | `Workload.template(...)` |
| "How does it do on **my dataset**" — a curated file of prompts in S3 | **Dataset (S3 file)** | `Workload.from_dataset(<s3-jsonl-prefix>, ...)` |
| "How does it do on **my real traffic**" — actual requests the endpoint served | **Traffic capture (SageMaker Data Capture)** | `Workload.from_dataset(<data-capture-prefix>, custom_dataset_type="sagemaker-datacapture", ...)` |

**Dataset vs. traffic capture are different sources** — keep them distinct:

- **Dataset** comes from **S3**: a JSONL file the user curated/exported (ShareGPT / OpenAI Chat / OpenAI Completions). It's whatever prompts they chose to put there.
- **Traffic capture** comes from **an endpoint**: SageMaker Data Capture writes the requests/responses the endpoint actually served to an S3 prefix. It's real production traffic, not a curated file. Point `from_dataset` at that capture prefix with `custom_dataset_type="sagemaker-datacapture"`. (The endpoint must have Data Capture enabled and use a supported request format.)

### Tokenizer

All workload modes — synthetic, dataset, and template (custom-format) — take a **tokenizer** (HuggingFace tokenizer id, e.g. `meta-llama/Llama-3.2-1B`) to size prompts; pass `tokenizer=TOKENIZER` in every mode (it's required for `Workload.synthetic`). Infer it from the model behind the endpoint (`aws sagemaker describe-endpoint --endpoint-name <name>` → model → HuggingFace model id / model name). If you can't infer it confidently, suggest your best guess and ask the user to confirm rather than asking them to supply it cold.

### Workload parameters

Infer input/output token sizes and concurrency from the endpoint's use case (e.g. chat = short-to-moderate; summarization = long input; a load test drives concurrency high); only ask if genuinely ambiguous. To benchmark at the load the endpoint serves today, take concurrency from its CloudWatch metrics as in `workload-from-endpoint.md` Step 2, and token sizes from its token metrics as in Step 3, item 2. Defaults if nothing else is known: input 512, output 256, concurrency 1, request_count 100.

### Custom-format endpoints (template mode)

For endpoints that don't speak OpenAI ChatCompletions, use `Workload.template(...)`:

- `request_template` — a Jinja2 template (local path or inline string) describing the endpoint's request payload; it's uploaded for you. (Or pass `template_s3_uri` if already in S3.)
- `response_field` — a JMESPath query that extracts generated text from the response (e.g. `generated_text` or `choices[0].message.content`). Omit to let AIPerf auto-detect.

### Dataset mode

For "benchmark on my dataset / real traffic", use `Workload.from_dataset(s3_uri, tokenizer=..., custom_dataset_type=...)`. The user gives you an S3 location — **you inspect it and figure out the format**; don't ask them to name it.

**Inspect first, then decide:** read a couple of records from the S3 prefix (or the endpoint's SageMaker Data Capture prefix) and identify the schema.

- **`custom_dataset_type` is optional** — a *hint* to AIPerf naming the schema so it parses records correctly; pass the matching value if you identify the schema, or omit it to let AIPerf auto-detect (omitting does not fail the job). See `benchmarking-guidance.md` → "Dataset schema hint (`custom_dataset_type`)" for the schema → value mapping.
- **If the data is in a format none of those cover, do NOT ask the user to reformat it by hand.** Hand off to the **`dataset-transformation`** skill to convert it into a supported schema (e.g. OpenAI Chat JSONL), then come back and benchmark the converted data. That skill owns all format conversion.

**Two dataset sources (keep them straight):**

- **My dataset — a curated file in S3:** the user points you at a JSONL prefix they exported/curated. Inspect it, detect the schema, benchmark it. This measures the endpoint against *the prompts they chose*.
- **My real traffic — SageMaker Data Capture:** the user points you at (or asks you to find) the endpoint's Data Capture prefix. This is what the endpoint *actually served*. Use `custom_dataset_type="sagemaker-datacapture"`. Prerequisites: the endpoint must have Data Capture enabled (check `aws sagemaker describe-endpoint --endpoint-name <name>` → `DataCaptureConfig`) and serve a supported request format. If Data Capture isn't enabled, tell the user it must be turned on first (it can't be applied retroactively to past traffic). This is the most production-faithful source, and the right choice for speculative-decoding comparisons (see `benchmarking-guidance.md`).

## Step 4: Confirm the Auto-Generated Names

Do **not** ask the user to type job names, config names, or the S3 output path. Infer a short prefix from the endpoint/model and today's date, derive the names, and confirm once:

> "I'll use these names — ok, or would you like a different prefix?
>
> - Benchmark job: `bench-<prefix>`
> - Workload config: `bench-<prefix>-wl`
> - Results output: `s3://<default-bucket>/benchmarks/<prefix>/`
>
> (Default bucket is your account's SageMaker default bucket; tell me if you'd rather use a specific bucket.)"

If the user accepts, proceed. If they give a different prefix or bucket, use it. This is the only naming interaction.

## Step 5: Generate Code

Generate a Jupyter notebook or a Python script — read `../code_output_guide.md` for the mode choice and output format rules (the template's `# NOTEBOOK_ONLY` markers make it dual-mode). Each cell's content comes from `../../code_templates/optimize-benchmark.py`, split on the `# Cell N:` comments. The template uses the SageMaker Python SDK (`>=3.20.0`; Cell 1 installs it in notebook mode), not boto3.

- **Cell 0** (markdown): Section header
- **Cell 1**: Setup (`%pip install` — notebook only)
- **Cell 2**: Configuration (imports, `set_attribution`, values)
- **Cell 3**: Define the Workload — `Workload.synthetic(...)` by default; swap to `Workload.template(...)` (custom format) or `Workload.from_dataset(...)` (dataset/Data Capture) per Step 3
- **Cell 4**: Run the Benchmark (`start_benchmark(...)`, blocks until the job is terminal)
- **Cell 5**: Display Results (`job.show_result()`)
- **Cell 6**: Save Manifest
- **Cell 7** (optional): Compare runs — `compare_benchmarks(...)`. Include only when the user has (or wants) a second run to compare against; reload a prior run with `BenchmarkJob.get("<name>").show_result()`.

### Values

Cell 2:

- `[REGION]` → endpoint's region (from Step 1)
- `[ENDPOINT_NAME]` → endpoint name (from Step 1)
- `[ROLE_ARN]` → execution role. Infer from the endpoint's model (`aws sagemaker describe-model --model-name <name>` → `ExecutionRoleArn`) or the SageMaker default execution role; only ask if none can be resolved.
- `[S3_OUTPUT_LOCATION]`, `[BENCHMARK_JOB_NAME]`, `[WORKLOAD_CONFIG_NAME]` → the confirmed auto-generated names from Step 4
- `[TOKENIZER]` → inferred tokenizer (Step 3)

Cell 3 (workload parameters): `[INPUT_TOKENS_MEAN]` (default 512), `[INPUT_TOKENS_STDDEV]` (50), `[OUTPUT_TOKENS_MEAN]` (256), `[OUTPUT_TOKENS_STDDEV]` (30), `[CONCURRENCY]` (1), `[REQUEST_COUNT]` (100).

Cell 3 (optional extra params): `[EXTRA_PARAMS]` → a dict of extra AIPerf workload parameters passed through `**params`, only when needed. Leave the line commented if not. Use it for `ignore_eos: True` (when the user specified an exact output length — see `benchmarking-guidance.md`), a low sampling `temperature` (for speculative-decoding runs), or a warmup control if the runtime's AIPerf workload exposes one. Example: `{"ignore_eos": True, "temperature": 0.2}`.

Cell 3 (dataset mode only): `[DATASET_S3_URI]` → S3 URI of the dataset/traffic-capture prefix to replay (e.g. `s3://my-bucket/benchmark-data/` or the endpoint's SageMaker Data Capture prefix). Only used in the commented `Workload.from_dataset(...)` block; leave the synthetic workload in place if the user isn't benchmarking on their own data.

Cell 4 conditional: `[INFERENCE_COMPONENT_NAME]` → the inference-component name(s) to target, only if the endpoint uses inference components. Obtain via `aws sagemaker list-inference-components --endpoint-name-equals <name>` (Step 1). If the endpoint has none, leave `inference_components=[...]` commented out.

Cell 6: `[PROJECT_DIR]` → absolute path to the user's project directory where the run manifest is written (e.g. `/home/user/my-project`); use the directory established by the `directory-management` reference, or the current working directory if none.

Cell 7 (only when comparing runs): `[BASELINE_JOB_NAME]` → the earlier benchmark job to compare against (reloaded via `BenchmarkJob.get(...)`); `[BASELINE_LABEL]` / `[THIS_RUN_LABEL]` → short human labels for the two runs (e.g. `before-opt` / `after-opt`, or `concurrency-4` / `concurrency-150`). Omit this cell entirely for a single run.

## Step 6: Present Results

When the job completes, read `interpreting-results.md` and present the metrics using the **"Benchmark Job Results" headline format** exactly (one consistent human-readable line first, second-order metrics after).

After presenting results, offer next steps:

> "What would you like to do next?
>
> - **Run another benchmark** — different concurrency or token lengths (e.g. a higher-concurrency load test)
> - **Compare against a previous run** — line this run up against an earlier one (before/after optimization, synthetic vs. dataset, or a concurrency step) with a single Δ% table
> - **Get deployment recommendations** — find a cheaper/faster instance + serving config for this model
> - **Done**"
