# Workload From an Existing Endpoint

Use this when the user wants recommendations for a model that's already on a SageMaker endpoint — for example, to right-size the endpoint or find a cheaper or faster configuration for it. The endpoint tells you which model to run the job on and how much load it serves, so size the job from it rather than from defaults. The results feed `recommendation-workflow.md`: the model source in Step 1, and the workload in Cell 3 of `../../code_templates/optimize-recommendation.py`.

Every call here is a read. They need `sagemaker` describe, list and `ListTags` access, `cloudwatch:GetMetricStatistics`, `cloudwatch:GetMetricData` and `cloudwatch:ListMetrics` (the token metrics in Step 3), `application-autoscaling:DescribeScalableTargets`, and `s3:ListBucket` on the Data Capture bucket; on an access-denied error, say which permission is missing. (The AWS MCP server is recommended but not required — the runtime routes these CLI calls through it automatically when available.)

If the user refers to findings or a notification about the endpoint and their details aren't in the conversation, say that you can't see them, and ask the user to paste them if they want them explained. You can still report what the endpoint's configuration and metrics show, as your own observations. Don't present the model's `DeploymentRecommendation` (instance types SageMaker suggested when the model was created, not an analysis of the endpoint's traffic) as those findings.

## Step 1: Find the Model Behind the Endpoint

Run `aws sagemaker describe-endpoint --endpoint-name <name>`. Keep the region, each production variant's `VariantName` and `CurrentInstanceCount`, and `DataCaptureConfig` (Step 3). If the endpoint has more than one variant, list them and ask the user to choose the one to size.

- **Inference components:** run `aws sagemaker list-inference-components --endpoint-name-equals <name>`. If there's more than one, list them with their models and ask the user to choose. Run `aws sagemaker describe-inference-component --inference-component-name <ic>` and keep `Specification.ModelName` and `RuntimeConfig.CurrentCopyCount`. A component with `Specification.BaseInferenceComponentName` hosts an adapter, and the job takes base models (`recommendation-workflow.md` → "Applies to"): size its base component's model, and tell the user the results cover the base model without the adapter. Read Steps 2 and 3 on the base component too: its container serves the adapter's requests, so its metrics carry them.
- **No inference components:** run `aws sagemaker describe-endpoint-config --endpoint-config-name <config>` and keep the variant's `ModelName` and `InstanceType`.

Run `aws sagemaker describe-model --model-name <model>` and determine the source from its container:

- **HuggingFace-format weights in the user's own S3** (`PrimaryContainer.ModelDataSource.S3DataSource.S3Uri` or `PrimaryContainer.ModelDataUrl`, or the same fields under `Containers`, is a prefix with `config.json` and the weights) → the S3 source.
- **A JumpStart model** (`aws sagemaker list-tags --resource-arn <model-arn>` shows a tag ending in `jumpstart-model-id`, such as `sagemaker-sdk:jumpstart-model-id`) → the JumpStart source with that id.
- **Only a HuggingFace Hub id** (`HF_MODEL_ID` in the container's `Environment`) → the model has to be staged to S3 first. Offer it (`huggingface-to-s3.md`) and say what it involves: it downloads the model, can need a license acceptance and a HuggingFace token, and stores a copy in the user's S3 bucket, which costs storage until they delete it. Then use the S3 source.

The model id or `HF_MODEL_ID` gives the tokenizer too.

## Step 2: Concurrency From CloudWatch

The job's `concurrency` is the number of concurrent requests the **whole deployment** serves; the job measures each candidate configuration at its per-copy share. SageMaker publishes concurrency per copy or per instance, so convert it:

| Endpoint            | Metric (namespace `AWS/SageMaker`) | Dimensions                    | Deployment concurrency                       |
| ------------------- | ---------------------------------- | ----------------------------- | -------------------------------------------- |
| Inference component | `ConcurrentRequestsPerCopy`        | `InferenceComponentName`      | value × `CurrentCopyCount`                   |
| Model on a variant  | `ConcurrentRequestsPerModel`       | `EndpointName`, `VariantName` | value × the variant's `CurrentInstanceCount` |

Read the last 7 days, so the window covers a weekly cycle, as hourly maximums: `aws cloudwatch get-metric-statistics --namespace AWS/SageMaker --metric-name ConcurrentRequestsPerCopy --dimensions Name=InferenceComponentName,Value=<ic> --statistics Maximum --period 3600 --start-time <7 days ago> --end-time <now>` (for a variant, the other metric and its two dimensions).

- Recommend the peak — the highest hourly maximum, converted and rounded up, so the recommended configuration holds at the busiest hour, not just on average — and confirm it in the workflow's Step 4 summary. `CurrentCopyCount` already counts the copies on every instance; don't multiply it by the instance count as well.
- If the copy or instance count autoscales (`aws application-autoscaling describe-scalable-targets --service-namespace sagemaker`), the current count may not be the count at the peak hour. Say so when you state the value.
- If there are no datapoints (no traffic in the window), say so and ask the user what concurrency they expect (default 1). If the endpoint is newer than 7 days, say how many days the value covers.

## Step 3: Token Sizes

The `AWS/SageMaker` endpoint metrics have no token counts, with or without enhanced metrics (`MetricsConfig.EnableEnhancedMetrics`, which adds instance and container dimensions to them). Use the first of these that applies:

1. **The endpoint's traffic** — if `DataCaptureConfig.EnableCapture` is true and the capture prefix of the variant from Step 1 (`<DestinationS3Uri>/<endpoint-name>/<variant-name>/`, since Data Capture writes each variant's requests under its own folder) holds files (`aws s3api list-objects-v2 --bucket <bucket> --prefix <key-prefix> --max-items 1`; capture files are keyed by date, so the first one also shows when capture started), recommend replaying the captured requests and confirm, even when another source below applies: replay uses the real prompts, and the statistics are the alternative to offer. Build Cell 3 with the template's `Workload.from_dataset(...)` block on the capture prefix, `custom_dataset_type="sagemaker-datacapture"` and the concurrency from Step 2, so the prompts come from real requests (leave out the block's `prompt_input_tokens_mean`). On an endpoint with more than one inference component, the variant's captures can include the other components' requests; say so when you recommend the replay. Captured requests can hold the endpoint's users' data: say so when you recommend this, and don't read records into the conversation unless the user agrees. Keep `request_count` at or below the number of captured requests, about the endpoint's `Invocations` sum since capture started (Step 2's dimensions, `--statistics Sum`) times `InitialSamplingPercentage` / 100, so the replay doesn't repeat prompts (`benchmarking-guidance.md` → "Prefix caching"). Prerequisites are in `benchmark-workflow.md` → "Dataset mode".
2. **The endpoint's token metrics** — run this even when `describe-endpoint-config` shows no `MetricsConfig` or no `EnableDetailedObservability`: older AWS CLI versions leave the field out, so a missing field doesn't mean it's off. With detailed observability on, a vLLM container publishes each completed request's prompt and response length to CloudWatch, and the SageMaker Python SDK reads them (`sagemaker>=3.29.0`; the AWS CLI can't). Run this directly, not in a notebook, with `AWS_DEFAULT_REGION` set to the endpoint's region and the variant or inference component from Step 1:

   ```python
   from sagemaker.core import Attribution, set_attribution
   from sagemaker.serve.ai_inference_recommender import describe_endpoint_traffic
   set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
   traffic = describe_endpoint_traffic("<endpoint>", inference_component_name="<ic>")  # or variant_name="<variant>"
   print(traffic)
   ```

   It describes the last 7 days: the request count, and the input and output tokens per request (`traffic.input_tokens`, `traffic.output_tokens`), each with percentiles from `min` to `max`, a `mean` and a `stddev`. Use the `mean` and `stddev` values for `[INPUT_TOKENS_MEAN]`, `[INPUT_TOKENS_STDDEV]`, `[OUTPUT_TOKENS_MEAN]` and `[OUTPUT_TOKENS_STDDEV]`. Its `concurrency.max`, rounded up, is Step 2's value, read the same way. If `token_metrics_error` is set, the read failed: tell the user its reason (for example, a missing permission) and use the next source. If the token entries are `None` and `detailed_observability` is `False`, the endpoint configuration turns detailed observability off: tell the user. If they're `None` otherwise, the endpoint published no token metrics for the model: the container isn't vLLM (LMI, for example), or the window had no traffic. The result doesn't say which, so don't name one to the user. Either way, use the next source. If it fails, tell the user why (for example, a missing permission, or a `sagemaker` older than 3.29.0) and use the next source.
3. **Values in the request** — for example, statistics the user brought from the console. Use them as given.
4. **Ask the user** for the typical prompt and response lengths, offering an estimate from the use case (chat: short to moderate; summarization: long input). If the user doesn't know, use input 512 and output 256 tokens.

## Step 4: State What You Derived

In the workflow's Step 4 summary, give each workload value with its source (for example, "concurrency 8: a peak of 2 per copy over the last 7 days × 4 copies", or "input 540 ± 145 tokens: the endpoint's 13,829 requests over the last 7 days"), and the endpoint's current instance type, instance count and copies, so the user can compare the recommendations with what's deployed. Then continue with the workflow.
