# GPU-Accelerated Functions on LMI

Lambda Event Functions can run on NVIDIA GPU instances through a capacity provider. Lambda installs and patches the GPU driver, assigns one GPU (or one GPU fraction) to each execution environment, and scales on GPU utilization in addition to CPU utilization and concurrency.

For supported instance types, accelerator memory values, limits, base image tags and pricing, use the GPU section of the [Lambda Managed Instances documentation](https://docs.aws.amazon.com/lambda/latest/dg/lambda-managed-instances.html) and [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/). Do not quote these values from memory.

## When a GPU Fits

Recommend a GPU when the workload's libraries have GPU implementations: model inference (PyTorch, vLLM, SGLang), video transcoding with NVENC/NVDEC, headless rendering (OpenGL through EGL, Vulkan), or GPU array math (CuPy, RAPIDS). Sequential logic, I/O-bound work and calls to other services pay for an idle accelerator; keep those on CPU instances.

## Setup Rules

- **Container image only.** Managed runtimes are not supported. Start from a Lambda GPU base image, or bring any image that has a multi-concurrent runtime interface client and no GPU driver.
- **Request the EC2 quota first.** The account's *Running On-Demand G and VT instances* quota defaults to 0, so ALWAYS tell the user to request an increase before the first deployment.
- **Dedicated capacity provider.** GPU and non-GPU instance types cannot share a capacity provider. List GPU types from several generations so scaling can fall back when one is short.
- **Accelerator memory is set on the function** with `AcceleratorConfig.AcceleratorMemorySize`. It is a minimum: Lambda picks the newest allowed instance type with the smallest GPU that fits. Request the smallest value that fits one copy of the model plus per-worker overhead.
- **The instance must fit the vCPUs too.** vCPUs = (`MemorySize` in MB / 1024) / `ExecutionEnvironmentMemoryGiBPerVCpu` (default 2). Lambda also reserves 1 vCPU + 1 GB per instance, so an allowed instance type needs more vCPUs than that result; look up each candidate's vCPU count in the EC2 instance type docs or with `aws ec2 describe-instance-types`. If no allowed size fits, activation fails with `IncompatibleAcceleratorInstanceTypes`. Raise the ratio or list larger sizes.
- **Minimum execution environments default to 1** for GPU functions (not 3), so a default deployment has no AZ redundancy and stops serving during an in-place rollout. Recommend raising `MinExecutionEnvironments` for production traffic, weighed against the GPU cost.
- **Fractional GPU types** share the physical GPU's compute and encoder/decoder engines with other EC2 instances. Leave them out for transcoding and rendering.

```bash
aws lambda create-function ... --package-type Image \
  --accelerator-config '{"AcceleratorMemorySize":16}' \
  --capacity-provider-config '{"LambdaManagedInstancesCapacityProviderConfig":{"CapacityProviderArn":"<gpu-capacity-provider-arn>"}}'
```

## Concurrency and GPU State

Each concurrent invocation runs in its own worker process, and every worker runs init code. GPU functions have their own default `PerExecutionEnvironmentMaxConcurrency`, independent of vCPUs.

- **Small models**: load the model onto the GPU in init code. Each worker holds its own CUDA context and copy, so GPU memory grows with concurrency.
- **Large models**: set concurrency to 1, or run one model server process that owns the GPU and have workers forward requests over local HTTP (elect the starter with a file lock in `/tmp`). The vLLM and SGLang base images already do this.
- **Tune** with `ExecutionEnvironmentGPUMemoryUsed`: lower concurrency when it nears the accelerator memory or invocations hit CUDA out-of-memory; raise it when GPU memory and utilization stay low under load. Raise `MemorySize` with concurrency, because init memory grows with the number of workers.

## Startup, Scaling and Deployments

- **Startup** = instance launch + image pull + init (model load). Init is capped at 15 minutes regardless of the function timeout.
- **Load weights from Amazon S3 in the same Region**, streamed into memory (`VLLM_LOAD_FORMAT=runai_streamer` on the vLLM/SGLang images, `s3torchconnector` on PyTorch). Downloading from Hugging Face is for testing only. Keep weights out of the image, and use SOCI for large images (see configuration-guide.md).
- **Scale-out is slower than CPU functions.** Lower the GPU utilization target (`AVERAGE_GPU_UTILIZATION` scaling policy) for bursty traffic, and pre-warm before known spikes.
- **GPU capacity is scarce.** Recommend an EC2 On-Demand Capacity Reservation with `open` eligibility for production; Lambda uses it automatically, but not a targeted reservation.
- **`$LATEST.PUBLISHED` rollouts fall back to in-place** when new GPU instances cannot launch: execution environments are replaced in batches, the function runs at reduced capacity, and scaling pauses. Numbered versions always need spare capacity to activate. Every `Active` version keeps GPU instances billed.

## Troubleshooting

Check `aws lambda get-function-configuration --function-name <fn>:<version> --query '[State,StateReasonCode,StateReason]'` first.

| Symptom | Cause | Fix |
|---------|-------|-----|
| No GPU instances launch | G and VT On-Demand quota is 0 or too low | Request a quota increase |
| `InvalidParameterValueException` on create/update | No allowed type has enough GPU memory | Lower `AcceleratorMemorySize` or add a larger GPU type |
| `IncompatibleAcceleratorInstanceTypes` | Enough GPU memory but too few vCPUs | Raise `ExecutionEnvironmentMemoryGiBPerVCpu` or list larger sizes |
| `InsufficientCapacityException`, scaling stops | No allowed GPU type available | Add generations and AZs, or reserve capacity |
| `FunctionError.InitResourceExhausted` | Init memory grows with concurrency | Raise `MemorySize` or lower concurrency |
| Init stalls or exceeds 15 min | Model download through NAT, very large image | Stream from same-Region S3, shrink the image, use SOCI |
| CUDA out of memory | Each worker holds its own model copy | Lower concurrency, raise accelerator memory, or use a single model server |
| GPU utilization near 0 while transcoding | Encoder/decoder engines are not counted | Expected; use `Duration` |
