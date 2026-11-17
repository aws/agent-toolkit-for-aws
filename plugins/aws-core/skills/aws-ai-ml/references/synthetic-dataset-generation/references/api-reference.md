# Synthetic Dataset Generation — API Reference

The synthetic dataset generation workflow is driven end-to-end by the V3 SDK's `DataPreparer` entrypoint.
This document is a thin pointer; the authoritative schema for every field that
can go inside `DatasetJobConfig(generation_config={...})` lives with the service
and is fetched live by the SDK.

## Live schema discovery

```python
from sagemaker.ai_registry import DataPreparer, DatasetJobConfig, JobCategory

DatasetJobConfig.print_schema(JobCategory.SYNTHETIC_DATA_GENERATION)
# Returns None; prints a pretty tree to stdout.

DatasetJobConfig.schema(JobCategory.SYNTHETIC_DATA_GENERATION)
# Returns the resolved JSON Schema dict (Hub-published).
```

`JobCategory.SYNTHETIC_DATA_GENERATION` is the SDK's Python enum member. Its value, the one the API takes (a boto3 or CLI `JobCategory` parameter, and the category in a job ARN), is `SyntheticDataGeneration`; the API rejects `SYNTHETIC_DATA_GENERATION`.

`print_schema` renders every field the service's `JobConfigSchema` declares
(snake_case field names, Python types, required flags, descriptions). New
fields added by the service show up here on the next SDK call with no SDK
update required — that's the single source of truth.

## Minimal synthetic dataset generation submission

```python
from sagemaker.ai_registry import DataPreparer, DatasetJobConfig

sample = DataPreparer.generate(DatasetJobConfig(
    dataset_name="my-dataset",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": "s3://my-bucket/input/task_description.txt"},
        "NumSamples": 5,
    },
    output_data_config={"OutputS3Uri": "s3://my-bucket/output/sdg/"},
))
print(sample.arn)     # Hub content ARN — feed to dataset quality or ModelTrainer
print(sample.source)  # S3 URI of the generated JSONL
```

When the SageMakerConfig or caller-level defaults supply `RoleArn` and
`OutputDataConfig.OutputS3Uri`, the submission further collapses to:

```python
DataPreparer.generate(DatasetJobConfig(
    dataset_name="my-dataset",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": "s3://my-bucket/input/task_description.txt"},
        "NumSamples": 5,
    },
))
```

## Spec-file naming

`SpecS3Uri` must point at a `.txt` or `.md` file containing the data spec.
Any filename is accepted — the system detects specs by content, not filename.

## Code-artifacts mode (iteration)

`SpecS3Uri` and `CodeArtifacts` are mutually exclusive — a request must contain exactly one.
Sending both fails schema validation, which is a configuration error to fix, not a transient
failure — do not retry.

Replace `DatasetSpecification.SpecS3Uri` with `DatasetSpecification.CodeArtifacts`:

```json
"DatasetSpecification": {
    "CodeArtifacts": {
        "GenerationCodeS3Uri": "s3://my-bucket/code/generation.py",
        "VerifiersCodeS3Uri":  "s3://my-bucket/code/verifiers.py",
    },
},
```

Filenames must be exactly `generation.py` and `verifiers.py`. Once code
artifacts are in play they — not the spec — are the source of truth for
generation/verification logic.

## Contextual data (CDG)

Set `generation_config["InputDataS3Uri"]` to a file or folder prefix. Max
1000 files, 10 MB each. Supported formats: csv, db, doc, docx, html, json,
jsonl, md, parquet, pdf, sql, sqlite, txt. Omit for NCDG (non-contextual).

## Parameter constraints (enforced client-side by the dynamic Pydantic model)

| Parameter | Constraint |
|---|---|
| `DatasetName` | Alphanumeric + hyphens, 1–63 chars, must start/end with alphanumeric |
| `NumSamples` | Integer, 1–50000 |
| `OutputDataConfig.OutputS3Uri` | Valid S3 URI, must end with `/`. Bucket must match SageMaker region. |
| `DatasetSpecification.SpecS3Uri` | Valid S3 URI pointing to a `.txt` or `.md` spec file. No trailing `/`. |
| `GenerationConfig.InputDataS3Uri` | Optional. File or folder URI. |
| `DatasetSpecification.CodeArtifacts.{GenerationCodeS3Uri,VerifiersCodeS3Uri}` | Filenames must be exactly `generation.py` / `verifiers.py`. |

> **⚠️ Same-region requirement:** All S3 buckets (input, output) must be in
> the same AWS region as the SageMaker endpoint.

## Lifecycle + observability

`DataPreparer.generate()` is blocking by default (`wait=True`). While waiting
it:

1. Polls `DescribeJob` every 30 s (`describe_interval`).
2. Drains new CloudWatch log events every 10 s (`poll`) and prints them inline.
3. Polls the service's streaming `verified_samples.jsonl` under
   `{OutputS3Uri}/{JobName}-{service-timestamp}/job_metadata/` every 30 s to
   surface a `Samples: X / Y (Z%)` progress line in the status panel. The
   lock-on match uses strict `{JobName}-{service-ISO-timestamp}/` path
   matching so it cannot drift to a concurrent or past job's output.
4. On terminal state emits a final panel and rehydrates a `DataSet` via
   `DataSet.get(name=...)`.

To run non-blocking (submit only, then poll or re-attach later):

```python
job = preparer.generate(cfg, wait=False)
print(job.job_arn)  # save this — printed automatically at submission time
print(job.job_name)
```

The returned `Job` handle has `.job_arn`, `.job_name`, `.job_status`. Call
`job.wait()` to block later, or `job.refresh()` to poll status.

To re-attach after a kernel restart (using only the ARN):

```python
dataset = DataPreparer.attach(job_arn)
# Renders the same Rich progress panel, waits, and returns the DataSet.
```

`attach()` works for all job categories (synthetic dataset generation, dataset quality, dataset transformation, dataset inference). If the job
already completed, it returns the result immediately without waiting.

To stop a running job (via ARN or Job handle):

```python
DataPreparer.stop(job_or_arn)
```

Blocks by default until the job transitions to `Stopped` (1–5 min); pass `wait=False` for fire-and-forget. If the job is already in a terminal state, it is a safe no-op.

The returned `DataSet` carries a public `.job_arn` attribute:

```python
dataset = preparer.generate(cfg)
print(dataset.job_arn)  # persist this for re-attach / support tickets
```

## Error paths

| Raised | Meaning |
|---|---|
| `DataPreparerConfigurationError` | Pre-submit config invalid (e.g. bad JobName, category mismatch, unresolvable RoleArn). |
| `DataPreparerSchemaNotFoundError` | Requested `schema_version` not published for this category. Check `available_versions` on the exception. |
| `DataPreparerSchemaValidationError` | Payload failed validation against the live Hub schema. Message carries valid siblings + "Did you mean?" fuzzy suggestions + `print_schema` hint. |
| `DataPreparerJobFailedError` | Service reported `JobStatus=Failed`. `.failure_reason` carries the cause; `HUB_FINALIZATION_FAILED` is surfaced here unchanged (compute succeeded but Hub registration did not — the data may still be usable on S3). |
| `DataPreparerJobStoppedError` | `JobStatus=Stopped`. |
| `DataPreparerJobTimeoutError` | Waiter timed out. |

All errors inherit from `DataPreparerError` so a single `except
DataPreparerError` catches the whole taxonomy.
