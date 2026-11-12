# Run with AWS Batch

Use AWS Batch as the job control plane and Amazon ECS Managed Instances Spot as the GPU capacity
provider. Batch adds queueing, job state, timeout, and retry policy without an additional AWS Batch
service charge. The GPU instance, storage, data transfer, logs, and ECS Managed Instances charges
still apply.

## Contents

- Architecture
- Separate infrastructure from a run
- Set `scaleInAfter` to zero
- Choose networking from the existing environment
- Size the compute environment from measurements
- Define the job contract
- Process one corpus per job
- Classify failures for Batch retries
- Keep IAM boundaries explicit

## Architecture

```text
immutable model artifact in S3
             |
input manifest and deterministic shards in S3
             |
SubmitJob -> AWS Batch queue -> ECS Managed Instances Spot
                                  |
                                  v
                        one vLLM offline process
                        loads the model once
                        processes shards sequentially
                                  |
                                  v
                    output, quarantine, and run metadata in S3
                                  |
                                  v
                  instance released with scaleInAfter = 0
```

Use the vLLM offline Python API, not an HTTP serving endpoint. This workload has one local producer
and no online request path, so an endpoint adds lifecycle and networking surface without helping
batch completion.

## Separate infrastructure from a run

Provision reusable resources with AWS CloudFormation or AWS CDK:

- AWS Batch compute environment using `ECS_MANAGED_INSTANCES`.
- `InstanceLaunchTemplate.CapacityOptionType` set to `SPOT`.
- `ManagedInstancesProvider.InfrastructureOptimization.ScaleInAfter` set explicitly to `0`.
- Batch job queue and job definition.
- ECR repository with immutable image identification.
- Job, execution, infrastructure, and managed-instance roles plus the required instance profile.
- CloudWatch Logs log group.
- Optional networking resources only after choosing a network path.

Keep these outside the stack and persistent across stack deletion:

- Model artifacts and manifests.
- Input shards and manifests.
- Output and quarantine records.
- Run metadata and completion manifests.

Submit the run after the stack exists. A deployment must not start inference as a side effect.

## Set `scaleInAfter` to zero

This architecture assigns one corpus run to one Batch job. The process loads the model once,
processes all shards, writes terminal metadata, and exits. No follow-up task is expected on that
instance, so configure:

```yaml
ComputeResources:
  Type: ECS_MANAGED_INSTANCES
  ManagedInstancesProvider:
    InfrastructureOptimization:
      ScaleInAfter: 0
    InstanceLaunchTemplate:
      CapacityOptionType: SPOT
```

Do not retain an idle GPU for a hypothetical retry. AWS Batch records failure and resubmits work
through its retry policy. Resumable outputs reduce the repeated work after a new instance starts.

The property accepts an integer from 0 through 3600 seconds or `-1`, which disables scale-in. This
skill prescribes `0` for its one-job-per-run lifecycle.

Sources:

- <https://docs.aws.amazon.com/batch/latest/userguide/ecs-managed-instances-compute-environments.html>
- <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-batch-computeenvironment-managedinstancesprovider.html>
- <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-batch-computeenvironment-instancelaunchtemplate.html>
- <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecs-capacityprovider-infrastructureoptimization.html>
- <https://aws.amazon.com/batch/pricing/>

## Choose networking from the existing environment

Inspect the VPC, subnets, routes, NAT gateways, and VPC endpoints before creating network resources.
Then choose one path:

| Condition                                                                       | Path                                                                                                                            |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| An existing approved outbound path reaches S3, ECR, logs, and required AWS APIs | Reuse it.                                                                                                                       |
| Public IPv4 is allowed and this is greenfield                                   | Use public subnets that assign public IPv4 addresses, with no inbound security group rules, and avoid an always-on NAT gateway. |
| Private-only networking is required                                             | Reuse an existing NAT gateway, or present its persistent cost before creating one.                                              |

Amazon ECS Managed Instances require external network access to the Amazon ECS service endpoint. A
private subnet without public IPv4 therefore requires a NAT gateway for this architecture. Existing
VPC endpoints can reduce traffic through that gateway for supported services, but do not present
them as a replacement for the documented NAT requirement.

Do not assume private subnets are cheaper. A NAT gateway and optional interface endpoints can remain
billable when no GPU job is running. State every networking cost that remains at idle in the final
deliverable.

## Size the compute environment from measurements

Pass actual single-GPU candidates to `Skill("aws-core:aws-compute")` only after measuring the model
and real prompt shape. Configure enough local instance storage for:

- Pulled container layers.
- Staged model files.
- Input shard working space.
- Temporary output and checkpoint files.
- Transfer and filesystem headroom.

Keep the initial architecture to one GPU per job. If no single-GPU candidate fits safely, stop and
revise the model, quantization, sequence length, or scope rather than adding distributed execution.

## Define the job contract

The job definition and `SubmitJob` parameters must make a run reproducible. Include:

- Container image digest.
- Model artifact URI and manifest checksum.
- Prompt and generation configuration revision.
- Input manifest URI and checksum.
- Output, quarantine, and run-metadata prefixes.
- GPU, CPU, and memory requirements, plus compute-environment local-storage sizing.
- Job timeout and maximum retry attempts.
- Quarantine threshold.

Use environment variables or command arguments for identifiers, not secrets. Let the job role obtain
only the AWS access required for those identifiers.

## Process one corpus per job

The entry point must:

1. Validate the run contract and input manifest.
2. Download the staged model to local storage and verify every checksum.
3. Initialize vLLM once.
4. Visit shards in deterministic order.
5. Skip a shard that already has a valid terminal completion record for the same immutable run
   contract.
6. Process records in internal batches selected by measured GPU memory and throughput.
7. Write complete output and quarantine objects, verify their counts and checksums, then publish the
   shard completion record last.
8. Reconcile the shard input, output, and quarantine counts.
9. Write a run completion manifest only after all shards are terminal.

Install a termination handler that stops accepting new internal batches, flushes completed records,
and writes progress before exit when the runtime receives a termination signal. Resumption must
depend on S3 records, not local disk.

## Classify failures for Batch retries

Map stable process exit classes to the AWS Batch retry strategy:

| Failure                                                            | Batch action                                                              |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| Spot interruption or host loss                                     | Retry.                                                                    |
| Transient S3, ECR, network, or AWS service failure                 | Retry with bounded attempts.                                              |
| Container startup failure that can succeed on replacement capacity | Retry with bounded attempts.                                              |
| Invalid manifest or checksum                                       | Exit without retry.                                                       |
| Model and vLLM incompatibility                                     | Exit without retry.                                                       |
| Missing authorization or staged artifact                           | Exit without retry.                                                       |
| Persistent GPU out-of-memory at the declared contract              | Exit without retry.                                                       |
| Invalid individual record                                          | Quarantine it; fail the run only when the declared threshold is exceeded. |

Keep retry attempts bounded. A retry is useful only when replacement capacity or a transient
dependency can change the outcome.

Use AWS Batch job state-change events for unattended notifications. Treat CloudWatch Logs as
diagnostic evidence, not as the source of data completeness. The S3 shard and run manifests are the
completion source of truth.

Sources:

- <https://docs.aws.amazon.com/batch/latest/userguide/job_retries.html>
- <https://docs.aws.amazon.com/batch/latest/userguide/batch_cwe_events.html>
- <https://docs.vllm.ai/en/latest/serving/offline_inference.html>

## Keep IAM boundaries explicit

Delegate policy syntax and role creation to `Skill("aws-core:aws-iam")`, while preserving these
boundaries:

- The staging identity writes only the model artifact prefix it owns.
- The Batch job role reads the selected model and input prefixes and writes only the selected output,
  quarantine, and run-metadata prefixes.
- The execution role pulls the image and writes logs.
- The infrastructure role allows Batch and ECS Managed Instances to manage capacity.
- The managed-instance role and instance profile allow the instance to join and operate under ECS
  Managed Instances.
- The runtime receives no long-lived model-hub credential.
- A public-subnet security group has no inbound rules.

Do not collapse these responsibilities into one broad role because the team is small. The
separation keeps a compromised inference container from changing infrastructure or replacing model
artifacts.
