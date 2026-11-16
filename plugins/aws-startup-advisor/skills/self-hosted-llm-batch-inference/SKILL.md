---
name: self-hosted-llm-batch-inference
description: "This skill should be used when a startup without a dedicated ML platform team needs recurring, latency-tolerant offline inference for a self-hosted 1B to 8B generative language model on AWS while minimizing GPU spend and recovering automatically from Spot interruption. It prescribes AWS Batch backed by Amazon ECS Managed Instances Spot, with model artifacts staged in Amazon S3, deterministic input shards, vLLM offline inference on one GPU, bounded retries, and output reconciliation before success. Covers sizing from the real prompt and model footprint, choosing networking without an avoidable idle cost floor, and verifying that results are complete and GPU capacity is gone. Not for online endpoints, training, embeddings, other inference engines, multi-GPU or distributed inference, or one-off experiments where manual rerun is acceptable."
license: Apache-2.0
metadata:
  audience: startup
---

# Self-Hosted LLM Batch Inference

Build a repeatable offline inference path for a startup that needs GPU economics without operating
an ML platform. Use one AWS Batch job for one corpus run, backed by Amazon ECS Managed Instances
Spot. Stage model weights in Amazon S3, divide the corpus into deterministic shards, and process
those shards sequentially with vLLM on one GPU.

Keep the infrastructure stack separate from each run. Provision reusable Batch, ECR, IAM, logging,
and optional networking resources with infrastructure as code. Submit each run separately with
immutable image, model, prompt, input manifest, and output identifiers.

Set `scaleInAfter` to `0` for this architecture. No follow-up task is expected on the instance after
the Batch job ends, so retaining idle GPU capacity adds cost without improving the run.

## Scope

Apply this skill only when all of these conditions hold:

- The workload is recurring, latency-tolerant, generative offline inference.
- The model is approximately 1B to 8B parameters and fits on one GPU after measurement.
- The team accepts Spot interruption and requires automatic recovery.
- One model is loaded once and reused across many input shards in a corpus run.
- Persistent artifacts and completion records can live in Amazon S3.

Do not apply this skill to online endpoints, training or fine-tuning, embedding models, other
inference engines, multi-GPU or distributed inference, or one-off experiments where an operator can
rerun the command manually.

## Workflow

1. Read **`references/prepare-model-and-input.md`** and define the immutable model artifact, prompt
   contract, deterministic shard manifest, output schema, quarantine schema, and measured sizing
   inputs.
2. Read **`references/run-with-aws-batch.md`** and author the reusable infrastructure plus the
   separate `SubmitJob` invocation. Preserve one Batch job per corpus run.
3. Read **`references/verify-and-optimize.md`** before the canary and again after the full run.
   Reconcile records, confirm retry behavior, measure cost inputs, and verify that GPU capacity has
   terminated.

## Required deliverables

- A reusable infrastructure stack for the Batch compute environment, queue, job definition, ECR
  repository, IAM roles and instance profile, log group, and only the networking resources that the
  chosen path requires.
- An immutable model artifact and manifest in Amazon S3.
- Deterministic input shards and an input manifest in Amazon S3.
- A separate `SubmitJob` invocation containing immutable image, model, prompt, input manifest, and
  output prefix identifiers.
- Output, quarantine, and run metadata that survive infrastructure deletion.
- A verification record proving completion, record reconciliation, and GPU capacity release.

## Upstream skills

Invoke upstream skills only when authoring the artifacts they own. The `aws-core:` skills ship in the separate `aws-core` plugin. If it is not installed, tell the user, recommend installing it, and continue with the steps that do not depend on it. Do not reproduce its content from memory.

- **`Skill("aws-core:aws-containers")`**: ECS Managed Instances, ECR, and container mechanics.
- **`Skill("aws-core:aws-cloudformation")`** or **`Skill("aws-core:aws-cdk")`**: the selected
  infrastructure-as-code implementation.
- **`Skill("aws-core:aws-iam")`**: role and policy implementation.
- **`Skill("aws-core:aws-storage")`**: S3 storage and transfer implementation.
- **`Skill("aws-core:aws-compute")`**: actual single-GPU instance candidates after measuring the
  workload.
- **`Skill("aws-core:aws-billing-and-cost-management")`**: current rates and cost calculations
  using the measurements defined here.
- **`Skill("aws-core:aws-messaging-and-streaming")`**: Batch state-change notifications when
  unattended completion needs a notification path.
- **`Skill("aws-core:aws-secrets-manager")`**: gated model credentials during staging only.

## Reference files

- **`references/prepare-model-and-input.md`**: Read before choosing GPU capacity or writing
  infrastructure. Defines model staging, prompt and record contracts, deterministic shards,
  manifests, output and quarantine schemas, and measurement inputs.
- **`references/run-with-aws-batch.md`**: Read before authoring the stack or submitting a run.
  Defines the AWS Batch architecture, `scaleInAfter`, networking decision, job lifecycle, retries,
  resumability, IAM boundaries, and stack-to-run contract.
- **`references/verify-and-optimize.md`**: Read before the canary and after every full run. Defines
  acceptance checks, reconciliation, interruption testing, capacity-release verification, and the
  measurements passed to cost analysis.
