# Verify and Optimize

Treat completion as a data and capacity result, not merely a successful process exit.

## Contents

- Run a representative canary
- Exercise recovery once
- Define completion
- Verify capacity release
- Measure the economics
- Verify deletion behavior
- Anti-patterns

## Run a representative canary

Submit the canary with the same image, staged model, job definition, networking, and output schemas
planned for the full corpus. Confirm:

- The model downloads from S3 and every checksum passes.
- vLLM, CUDA, the driver, dtype, and quantization are compatible.
- Peak GPU memory leaves measured safety headroom.
- The longest representative prompt and output remain inside configured limits.
- Ordinary records produce schema-valid output.
- Malformed records are quarantined.
- Shard completion and run metadata are durable in S3.
- The job terminates and the GPU instance disappears.

Do not launch the full corpus after a canary that only proves the container starts.

## Exercise recovery once

Cause a controlled interruption during a non-production canary or test run. Verify that:

- AWS Batch marks the attempt failed and retries it under the declared policy.
- The replacement attempt reuses valid completed shard records.
- A partially published shard is not mistaken for a terminal shard.
- Output records are not duplicated for the same `record_id` and immutable run contract.
- The final reconciliation remains correct.

Also submit one intentionally invalid manifest and confirm that it fails without consuming every
retry attempt.

## Define completion

Declare the run complete only when all four conditions hold:

1. The AWS Batch job is `SUCCEEDED`.
2. Every input shard has a valid terminal completion record, and every invalid record is explicitly
   quarantined under the declared policy.
3. Input count equals successful output count plus quarantine count, with no duplicate terminal
   `record_id`.
4. No GPU instance remains after capacity release.

CloudWatch Logs can explain a failure, but log presence, a final log line, or a zero process exit is
not enough to prove record completeness.

## Verify capacity release

Record the timestamps for:

- Job submission.
- First runnable or starting state.
- Model download start and finish.
- Model load finish.
- First output.
- Last output.
- Job terminal state.
- Managed instance disappearance.

With `scaleInAfter` set to `0`, investigate any material gap between the terminal job state and
instance disappearance. Confirm that no other task, job, or lifecycle state is retaining the
instance.

## Measure the economics

Provide measured inputs to `Skill("aws-core:aws-billing-and-cost-management")`; do not embed a stale
rate table in this skill. Include:

- Selected instance type, purchasing model, Region, and runtime.
- Provisioning wait, model download, model load, inference, checkpoint, and post-job release
  intervals.
- Successful and quarantined record counts.
- Input and output token counts.
- S3 request and storage volume.
- Log ingestion volume.
- ECS Managed Instances charges.
- Persistent idle networking resources such as NAT gateways or interface endpoints.
- Retry count and repeated initialization time.

Report at least cost per successful record, cost per million processed tokens, total run cost, and
the persistent monthly cost that remains when no GPU job runs.

Optimize measured bottlenecks in this order:

1. Remove avoidable persistent idle infrastructure.
2. Reduce repeated work through deterministic checkpoints.
3. Tune internal batch size and concurrency within measured memory headroom.
4. Right-size the single GPU against observed throughput and total run cost.
5. Evaluate quantization only with an explicit quality check.

The cheapest hourly GPU is not necessarily the cheapest completed corpus if provisioning, model
load, or throughput dominates.

## Verify deletion behavior

Exercise stack deletion in a non-production environment. Confirm that reusable compute resources can
be removed without deleting the persistent model, input, output, quarantine, and run-metadata
artifacts. List any retained ECR images, logs, S3 objects, or networking resources and their
lifecycle policy.

## Anti-patterns

- Running the workload as an ECS service or an online vLLM endpoint.
- Creating one Batch job per shard and paying model initialization for every shard.
- Baking model weights into the container image.
- Downloading a mutable model revision or using a model-hub token at runtime.
- Selecting a GPU from parameter count alone without measuring the real prompt and output shape.
- Treating local disk as the checkpoint source after Spot interruption.
- Retrying invalid manifests, authorization failures, incompatibility, or persistent out-of-memory
  failures.
- Treating `SUCCEEDED` or a final log line as proof that every record has a terminal result.
- Creating an always-on NAT gateway without stating its idle cost.
- Leaving `scaleInAfter` unset or setting it above `0` for this one-job-per-run architecture.
