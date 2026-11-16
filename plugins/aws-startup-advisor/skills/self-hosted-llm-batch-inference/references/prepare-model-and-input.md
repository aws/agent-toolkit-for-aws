# Prepare the Model and Input

The model, prompt, and input shape decide GPU memory, local storage, throughput, retry cost, and
output completeness. Define them before selecting an instance or writing infrastructure.

## Contents

- Freeze the run contract
- Stage the model in Amazon S3
- Define stable records
- Create deterministic shards
- Define output and quarantine records
- Measure before choosing a GPU

## Freeze the run contract

Assign immutable identifiers to every input that can change inference results:

- Container image digest.
- Model artifact URI and model manifest checksum.
- Prompt template revision.
- Generation parameter set.
- Input manifest URI and checksum.
- Output and quarantine prefixes.

Pass those identifiers to `SubmitJob`. Do not use mutable image tags, an unpinned model revision, or
an input prefix that can change while the job is running.

## Stage the model in Amazon S3

Stage weights before runtime. Keep the vLLM runtime and entry point in the container image, but keep
model weights out of the image so model updates do not require rebuilding and pushing a large image.

Use a revision-specific layout:

```text
s3://<artifact-bucket>/models/<model-id>/<source-revision>/
  manifest.json
  config.json
  tokenizer files
  chat template files
  weight files
```

Record at least these fields in `manifest.json`:

```json
{
  "model_id": "organization/model",
  "source_revision": "<immutable upstream revision>",
  "dtype": "bfloat16",
  "quantization": null,
  "files": [
    {
      "path": "model-00001-of-00002.safetensors",
      "size_bytes": 0,
      "sha256": "<checksum>"
    }
  ]
}
```

Include every file required to load the model offline, including tokenizer configuration and a chat
template when the prompt uses one. Verify file size and checksum after download to local instance
storage.

If the source model is gated, use the model-hub credential only in the staging workflow. Store that
credential with `Skill("aws-core:aws-secrets-manager")`. The Batch runtime role must read the staged
S3 artifact and must not receive a long-lived model-hub token.

## Define stable records

Use a stable `record_id` that does not depend on shard position. Keep the source payload and any
prompt variables explicit:

```json
{
  "record_id": "customer-42/review-817",
  "input": { "text": "..." },
  "metadata": { "language": "ko" }
}
```

Define one deterministic transformation from a record to the exact vLLM request:

- Prompt or messages after template assembly.
- Tokenizer and chat template revision.
- Maximum input length.
- Maximum generated tokens.
- Sampling parameters.
- Stop sequences.

The assembled prompt and expected output shape are infrastructure inputs. Measure them from
representative production records instead of sizing from parameter count alone.

## Create deterministic shards

Create ordered, immutable shards and a manifest. Avoid one S3 object per record because tiny objects
increase request overhead and complicate reconciliation.

Choose a shard size that:

- Keeps rework bounded when Spot interrupts a job.
- Is large enough to amortize S3 requests and checkpoint writes.
- Fits in local working storage with model files and temporary outputs.
- Can be processed sequentially by one model load.

Do not create one AWS Batch job per shard by default. That repeats instance provisioning, model
download, and model load. Submit one job per corpus run and process many shards sequentially.

Use a manifest such as:

```json
{
  "schema_version": 1,
  "run_input_id": "reviews-2026-09-05",
  "record_count": 120000,
  "shards": [
    {
      "shard_id": "000000",
      "uri": "s3://<bucket>/inputs/reviews-2026-09-05/shards/000000.jsonl",
      "record_count": 2000,
      "size_bytes": 0,
      "sha256": "<checksum>"
    }
  ]
}
```

Reject a manifest whose aggregate count, object size, or checksum does not match its shards.

## Define output and quarantine records

Key every terminal record by `record_id` and preserve enough metadata to reproduce the request:

```json
{
  "record_id": "customer-42/review-817",
  "status": "succeeded",
  "model_revision": "<revision>",
  "prompt_revision": "<revision>",
  "generation": { "text": "...", "finish_reason": "stop" },
  "usage": { "input_tokens": 0, "output_tokens": 0 }
}
```

Write invalid records to a quarantine schema instead of retrying the entire shard:

```json
{
  "record_id": "customer-42/review-818",
  "status": "quarantined",
  "error_class": "invalid_input",
  "error_message": "input text is missing"
}
```

Define an explicit quarantine threshold for the run. Below the threshold, finish the remaining
records and report the quarantined count. Above it, fail with a non-retryable data-quality exit
class.

## Measure before choosing a GPU

Use the staged model and representative assembled prompts to measure:

- Weight memory after dtype or quality-tested quantization.
- KV cache at the selected sequence length and concurrency.
- Activations and vLLM or CUDA overhead.
- Peak GPU memory with safety headroom.
- Input and output token distributions.
- Records and tokens per second.
- Model download and load time.
- Container image, model, input, output, checkpoint, and temporary local-storage bytes.

Choose a single GPU only after this measurement. If the workload does not fit safely, reduce
concurrency, bound sequence length, apply quality-tested quantization, choose a smaller model, or
choose a larger single GPU. Do not silently cross into multi-GPU execution.

Prepare a representative canary shard that includes long prompts, expected large outputs, malformed
records, and ordinary records. Use it to validate compatibility, memory, schema, and failure
handling before submitting the full corpus.
