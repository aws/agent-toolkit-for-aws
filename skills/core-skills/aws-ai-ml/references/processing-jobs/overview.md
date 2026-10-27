# Processing Jobs

Run arbitrary scripts and distributed data workloads on SageMaker managed processing compute with SageMaker Python SDK v3. Covers plain scripts, framework environments, Spark, custom containers, Athena/Redshift dataset definitions, and failure diagnosis.

## When to use

Use this capability when the user asks to:

- "run my script on SageMaker" or execute Python on managed compute with S3 I/O
- run a transform with PyTorch, TensorFlow, Hugging Face, XGBoost, or sklearn dependencies
- run PySpark/Spark JAR distributed ETL or process large datasets
- run a custom processing container
- query Athena or Redshift directly into a processing job
- diagnose a failed, stopped, or stuck processing job

Dataset format conversion that is already covered by `dataset-transformation` stays there; that capability may call SageMaker Processing internally.

## Operating assumptions

| Area | Assumption |
|---|---|
| Runtime | Python supported by `sagemaker>=3.22.0,<4.0`; templates install dependencies at use time |
| Credentials | Ambient AWS credentials plus a SageMaker execution role; caller needs processing create/describe, S3, logs, ECR/DLC, `iam:PassRole`, and Athena/Redshift permissions when selected |
| Storage | Small scripts/configs may be local; processor uploads code and stages data through S3; container paths live under `/opt/ml/processing/` |
| Region | Resolve from the AWS session; processing images and S3 query/output locations must be usable in that region |
| Network | PyPI access is needed for installation; runtime egress depends on the selected container and VPC/network isolation settings |

## Decision flow

1. Check conversation and project files before asking for values.
2. Choose one branch:
   - **Single Python script or BYOC** → `code_templates/script_processing.py`
   - **Framework source directory + requirements** → `code_templates/framework_processing.py`
   - **PySpark or Spark JAR** → `code_templates/spark_processing.py`
   - **Athena or Redshift query input** → `code_templates/dataset_definition_processing.py`
   - **Existing job failure/status** → `references/troubleshooting.md`
3. Use a prebuilt image resolved through `image_uris.retrieve` when it fits. Follow the managed-image resolution and reproducibility rules in `references/configuration.md`; review the resolved URI before launch.
4. For a custom ECR image, use the read-only `aws ecr describe-images` procedure in `references/configuration.md`, present candidate tags/digests and timestamps, obtain user selection, and pin the selected digest. Never silently select a mutable `latest` tag.
5. For Athena/Redshift, SageMaker executes the query and stages results to the configured S3 URI; do not add a separate manual export step.

## Gather inputs

Use cascading fallback: conversation → project files → ask one unresolved question at a time.

Required for launch: script/app or image, role, instance type/count, max runtime, input/output mapping, and wait behavior. Additionally:

- Framework: framework, exact supported version, Python version, source directory, optional `requirements.txt`
- Spark: PySpark script or JAR, optional Spark/Python/container version overrides, dependencies, multi-instance count. Apply the version policy from `references/configuration.md`.
- BYOC: ECR image URI and command/entrypoint expectations
- Athena: catalog, database, workgroup (optional), SQL, query-result S3 URI, output format
- Redshift: cluster, database, DB user, cluster role, SQL, query-result S3 URI, output format

For a Spark JAR, infer the fully qualified main class from the JAR manifest, build file (`pom.xml`, `build.sbt`, Gradle), or application documentation. Ask the user if it remains unresolved. `SPARK_MAIN_CLASS` is required only for `APPLICATION_KIND="jar"`; clear it for PySpark.

GPU-backed Processing Jobs are supported only with a GPU processing instance, compatible CUDA/framework or BYOC image, and sufficient regional quota. This reference has not validated a dedicated GPU-processing branch, so state that limitation and verify image compatibility/quota rather than assuming a CPU image will work.

## Preflight and confirmation

Before generating code or submitting a job:

1. Verify region, execution-role trust, S3 paths, exact image availability, query permissions, and requested compute quota.
2. Validate that input/output local paths start with `/opt/ml/processing/`, because SageMaker Processing mounts input channels and collects declared outputs under that container path; paths outside it are not automatically populated or uploaded.
3. For GPU requests, additionally verify GPU-compatible image metadata and the relevant Processing instance quota.
4. Summarize branch, image/framework/version, script/query, S3 I/O, instance type/count, volume, max runtime, and wait behavior.
5. Link to [SageMaker pricing](https://aws.amazon.com/sagemaker/ai/pricing/) rather than calculating a dollar estimate.
6. Ask for explicit approval. Stop until approved.

## Generate and launch

1. Read `references/configuration.md` and the selected template.
2. Write the customized output under the project directory in notebook or script mode.
3. Keep `WAIT_FOR_COMPLETION=False` unless the user asks to block.
4. Templates submit with `wait=False`, print job name/ARN immediately, and use `logs_for_processing_job` only when waiting.
5. Report output S3 locations after completion.

## Diagnose an existing job

Read `references/troubleshooting.md`. Start with `DescribeProcessingJob`, then inspect the job's CloudWatch stream. Return failure signature, root cause category, evidence, and fix; state what was not checked.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- scheduled orchestration through SageMaker Pipelines, Step Functions, or EventBridge
- Ground Truth labeling jobs
- EMR/Glue cluster administration outside the processing job
- a dedicated, end-to-end validated GPU Processing branch

## References

- `code_templates/script_processing.py` — plain script and BYOC
- `code_templates/framework_processing.py` — framework image, source directory, requirements
- `code_templates/spark_processing.py` — PySpark or Spark JAR
- `code_templates/dataset_definition_processing.py` — Athena or Redshift query input
- `references/configuration.md` — placeholders and branch settings
- `references/troubleshooting.md` — status and failure classification
- [SageMaker Processing SDK reference](https://sagemaker.readthedocs.io/en/stable/processing.html)
- [SageMaker prebuilt containers](https://docs.aws.amazon.com/sagemaker/latest/dg/docker-containers-prebuilt.html)
