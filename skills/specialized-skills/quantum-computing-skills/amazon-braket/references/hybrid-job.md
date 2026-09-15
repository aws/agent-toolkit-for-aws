# Hybrid job

## Key operations

| Operation | Amazon Braket Python SDK | AWS CLI | boto3 `braket` client |
|---|---|---|---|
| Create | `AwsQuantumJob.create(...)` or `@hybrid_job` decorator | `aws braket create-job --region <region> --job-name <name> --role-arn <AmazonBraketJobsExecutionRole arn> --device-config '{"device":"<device>"}' --instance-config '{"instanceType":"<instance-type>","volumeSizeInGb":30}' --output-data-config '{"s3Path":"s3://<bucket>/<prefix>"}' --algorithm-specification '{"scriptModeConfig":{"entryPoint":"<module>:<function>","s3Uri":"s3://<bucket>/source.tar.gz","compressionType":"GZIP"}}'` — all six flags are required, and you must package and upload `source.tar.gz` yourself | [`create_job`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/create_job.html) |
| Status & metadata | `AwsQuantumJob.state()`, `.metadata()` | `aws braket get-job --job-arn <arn> --region <region> --query '{status:status,failureReason:failureReason,spec:algorithmSpecification}'` | [`get_job`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/get_job.html) |
| Cancel | `AwsQuantumJob.cancel()` | `aws braket cancel-job --job-arn <arn> --region <region>` | [`cancel_job`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/cancel_job.html) |
| Search / list | — no SDK method | `aws braket search-jobs --filters '[]' --region <region> --query 'jobs[].{name:jobName,status:status,device:device}'` | [`search_jobs`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/search_jobs.html) |
| Results / metrics / logs | `AwsQuantumJob.result()`, `.metrics()`, `.logs()` | — | — (results in S3, metrics in CloudWatch) |

Learn more about hybrid jobs at https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs.html.
Choose a current `instanceType` from https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-configure-job-instance-for-script.html.

## Submitting a job

Learn more about creating a hybrid job at https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-first.html.

### `entry_point` MUST be derived from `source_module`

`entry_point` is `<module path inside the archive>:<function>` — a **colon** between module and function, never a dot.
The SDK archives `source_module` under its **basename only**, stripping every leading path component, so the module path is relative to that basename.

| `source_module` | archive contains | `entry_point` |
|---|---|---|
| `a/b/algorithm.py` (a file) | `algorithm.py` at root | `algorithm:main` |
| `a/b/hj_source` (a directory) | `hj_source/algorithm_script.py` | `hj_source.algorithm_script:main` |

Two failure modes, both `ModuleNotFoundError` at container boot — do NOT do either:

- ❌ bare module for a directory `source_module`: `entry_point="algorithm_script:main"` (missing the required `hj_source.` prefix)
- ❌ full path in the module: `entry_point="a.b.hj_source.algorithm_script:main"` (leading `a/b/` is stripped by the SDK)

## Choosing a container

### Embedded simulators

Embedded simulators run inside the job container instead of dispatching to a managed simulator or a QPU.
Pass `device="local:<provider>/<simulator>"` and a matching `image_uri=retrieve_image(Framework.<VARIANT>, region)`; the provider and simulator names come from the framework variant you select, not from a plugin's device name.

Learn more about embedded simulators at https://docs.aws.amazon.com/braket/latest/developerguide/pennylane-embedded-simulators.html.

### Multi-GPU simulation with CUDA-Q

Whenever a simulation is GPU- or memory-bound — even if the user doesn't say "CUDA-Q" — for example a 30+ qubit state-vector simulation that runs out of memory on one GPU, consider using CUDA-Q with Hybrid Jobs.
CUDA-Q's `mgpu` target pools the memory of several GPUs to hold one state vector.
Refer to the notebook [6_Distributed_state_vector_simulations.ipynb](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/nvidia_cuda_q/6_Distributed_state_vector_simulations.ipynb) for examples on how to use CUDA-Q with Hybrid Jobs for large simulations.

Learn more about using CUDA-Q on Amazon Braket at https://docs.aws.amazon.com/braket/latest/developerguide/braket-using-cuda-q.html.

### Bring your own container (BYOC)

**Bring your own container (BYOC)** is the fully-custom path when the base images and framework variants don't fit your dependency stack.

Learn more about bringing your own container at https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-byoc.html and https://docs.aws.amazon.com/braket/latest/developerguide/running-hybrid-jobs-in-own-container.html.

## Writing the algorithm script

Algorithm code MUST NOT hardcode device ARNs, buckets, or credentials — read them from the job environment (`get_job_device_arn()`, `get_hyperparameters()`, `get_results_dir()` from `braket.jobs.environment_variables`) so the same script runs unchanged across devices and regions.

To persist any data from the algorithm script, call `save_job_result` — never write result files by hand:

```python
from braket.jobs import save_job_result
save_job_result({"counts": counts})
```

It writes `results.json` to the managed output directory and uploads it to the job's S3 output; read it back with `load_job_result()`.
Do NOT `open(...)` a results path yourself or treat a bucket name as a local directory — the container has no such path and it raises `FileNotFoundError`.

Learn more about the algorithm script environment at https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-script-environment.html.

## Debugging a failed job

`@hybrid_job(local=True)` or `LocalQuantumJob.create(...)` runs the container on your machine — use it to reproduce a failure before resubmitting.

Learn more about debugging a hybrid job with local mode at https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-local-mode.html.

### Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` at container boot | `entry_point` uses a dot, or its module path doesn't match the archive layout | Derive it from `source_module` per the procedure above |
| `ModuleNotFoundError: __path__ attribute not found` | Algorithm script sits flat at the archive root (raw-API path only) | Put it inside a named subdirectory; the SDK packages correctly |
| Missing dependency, e.g. scipy | Base image lacks the package | Add `requirements.txt` to the source module, or pick an image that includes it |
| Job fails before your code runs | Source or results bucket is in a different region than the job | Keep both in the job's region |
| `create` rejects `instance_count`/`instance_type` | Not top-level kwargs | Use `InstanceConfig(instanceType=..., instanceCount=N)`; with `instanceCount > 1` the algorithm must handle multiple hosts |
| Invented per-hyperparameter env vars | All hyperparameters are one JSON blob at `AMZN_BRAKET_HP_FILE` | Read them with `get_hyperparameters()` |
| `create_job` denied at `PassRole` | Execution role name doesn't match the required prefix | Name it `AmazonBraketJobsExecutionRole[-suffix]` under `/service-role/` |
| Tasks lose priority queueing | `create_quantum_task` called through boto3 inside the algorithm script | Pass `AMZN_BRAKET_JOB_TOKEN` as `jobToken` (the SDK does this automatically) |

## References

- API: [CreateJob](https://docs.aws.amazon.com/braket/latest/APIReference/API_CreateJob.html) · [InstanceConfig](https://docs.aws.amazon.com/braket/latest/APIReference/API_InstanceConfig.html)
- SDK API:
  - [`braket.aws.aws_quantum_job`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.aws.aws_quantum_job.html)
  - [`braket.jobs`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.html) · [`braket.jobs.hybrid_job`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.hybrid_job.html)
  - [`braket.jobs.environment_variables`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.environment_variables.html) · [`braket.jobs.data_persistence`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.data_persistence.html)
  - [`braket.jobs.metrics`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.metrics.html) · [`braket.jobs.image_uris`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.jobs.image_uris.html)
- Developer guide:
  - [Working with hybrid jobs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs.html) · [Create a hybrid job](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-first.html)
  - [Define the algorithm environment](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-script-environment.html) · [PennyLane embedded simulators](https://docs.aws.amazon.com/braket/latest/developerguide/pennylane-embedded-simulators.html)
  - [BYOC](https://docs.aws.amazon.com/braket/latest/developerguide/braket-jobs-byoc.html) · [Running hybrid jobs in your own container](https://docs.aws.amazon.com/braket/latest/developerguide/running-hybrid-jobs-in-own-container.html) · [Using CUDA-Q](https://docs.aws.amazon.com/braket/latest/developerguide/braket-using-cuda-q.html)
- Notebooks:
  - [hybrid_jobs](https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/hybrid_jobs) — start with [0 — Creating your first hybrid job](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/hybrid_jobs/0_Creating_your_first_Hybrid_Job/0_Creating_your_first_Hybrid_Job.ipynb); [4 — Embedded simulators](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/hybrid_jobs/4_Embedded_simulators_in_Braket_Hybrid_Jobs/Embedded_simulators_in_Braket_Hybrid_Jobs.ipynb); [3 — Bring your own container](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/hybrid_jobs/3_Bring_your_own_container/bring_your_own_container.ipynb)
  - [nvidia_cuda_q](https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/nvidia_cuda_q) — [3 — Hybrid jobs with CUDA-Q](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/nvidia_cuda_q/3_Hybrid_jobs_with_CUDA-Q.ipynb) · [5 — Multiple GPU simulations](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/nvidia_cuda_q/5_Multiple_GPU_simulations.ipynb) · [6 — Distributed state vector simulations](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/nvidia_cuda_q/6_Distributed_state_vector_simulations.ipynb)
- Container source: [`amazon-braket-containers`](https://github.com/amazon-braket/amazon-braket-containers)
