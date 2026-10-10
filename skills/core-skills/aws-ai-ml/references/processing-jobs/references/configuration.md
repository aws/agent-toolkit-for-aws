# Processing Template Configuration

All templates support notebook and script mode. Notebook-only dependency lines are marked `# NOTEBOOK_ONLY`. Fill every bracketed placeholder before running.

## Common values

| Placeholder | Expected value | Example |
|---|---|---|
| `[PROJECT_DIR]` | Confirmed project root | `./feature-processing` |
| `[ROLE_ARN]` | SageMaker execution role ARN | `arn:aws:iam::123456789012:role/SageMakerExecutionRole` |
| `[INPUT_S3_URI]` | Same-region processing input | `s3://my-sagemaker-bucket/input/` |
| `[OUTPUT_S3_URI]` | Processing output prefix | `s3://my-sagemaker-bucket/output/` |
| `[INSTANCE_TYPE]` | Processing instance type verified against quota | `ml.m5.xlarge` |
| `[BASE_JOB_NAME]` | Lowercase/hyphenated job prefix | `feature-processing` |
| `[IMAGE_FRAMEWORK]` | Confirmed framework accepted by `image_uris.retrieve` | `sklearn` |
| `[IMAGE_VERSION]` | Exact supported DLC version; never infer `latest` | `1.2-1` |
| `[IMAGE_PYTHON_VERSION]` | Exact supported DLC Python identifier | `py3` |

Resolve framework/version/Python combinations from the [SageMaker prebuilt-container documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/docker-containers-prebuilt.html) and [SDK image URI utility](https://sagemaker.readthedocs.io/en/stable/api/utility/image_uris.html). Leaving `IMAGE_VERSION`/`IMAGE_PYTHON_VERSION` empty passes `None`, which makes SageMaker Python SDK v3 resolve its latest supported regional mapping; print and review the resulting URI. For reproducibility, set explicit supported versions or pin that resolved URI in `CUSTOM_IMAGE_URI`.

For custom ECR images, list the newest tagged candidates read-only:

```bash
aws ecr describe-images --repository-name <repository> --region <region> \
  --query 'reverse(sort_by(imageDetails[?imageTags!=null],&imagePushedAt))[:10].{Pushed:imagePushedAt,Tags:imageTags,Digest:imageDigest}'
```

Show `imagePushedAt`, tags, and digests; get user approval; then use `<repository-uri>@sha256:<digest>`. Never silently select a mutable `latest` tag.

## Script and framework templates

| Placeholder | Expected value |
|---|---|
| `[SCRIPT_PATH]` | Local or S3 Python script path |
| `[SOURCE_DIR]` | Source directory uploaded with the framework job |
| `[ENTRY_SCRIPT]` | Script relative to `SOURCE_DIR` |
| `[REQUIREMENTS]` | Optional requirements file relative to `SOURCE_DIR` |
| `[FRAMEWORK]` | Framework supported by the chosen SageMaker DLC |
| `[FRAMEWORK_VERSION]` | Exact version with a matching SageMaker DLC |
| `[PYTHON_VERSION]` | DLC Python identifier such as `py310` |

Do not treat the examples as an exhaustive framework list; check the linked SDK/container documentation. GPU requests require a compatible GPU image and Processing quota and are not a separately validated branch in this reference.

## Spark template

| Setting | Expected value |
|---|---|
| `[SPARK_APPLICATION]` | Local/S3 `.py` script or `.jar` path |
| `[SPARK_MAIN_CLASS]` | Fully qualified Java/Scala main class; required only for JAR applications |
| `SPARK_VERSION` | Optional SageMaker Spark framework-version override; leave empty for SDK resolution |
| `SPARK_PYTHON_VERSION` | Optional Spark Python-version override; leave empty for SDK resolution |
| `SPARK_CONTAINER_VERSION` | Optional Spark container-version override; leave empty for SDK resolution |
| `[SPARK_EVENT_LOGS_S3_URI]` | S3 prefix for Spark event logs |

Set `APPLICATION_KIND` to `pyspark` or `jar`. Leave `SPARK_VERSION`, `SPARK_PYTHON_VERSION`, and `SPARK_CONTAINER_VERSION` empty to let SDK v3 resolve the latest supported regional Spark image, then review `processor.image_uri`; set explicit versions for reproducibility. For JARs, derive the main class from the manifest, build file, or app documentation and ask the user if unresolved. Clear `SPARK_MAIN_CLASS` for PySpark. Multi-instance jobs use one Spark driver and the remaining instances as workers.

## Dataset definition template

| Placeholder | Expected value |
|---|---|
| `[QUERY_PROCESSING_SCRIPT]` | Script that reads the staged query result from `/opt/ml/processing/input/query` |
| `[QUERY_RESULT_S3_URI]` | S3 prefix where Athena/Redshift writes query results |
| `[ATHENA_CATALOG]`, `[ATHENA_DATABASE]`, `[ATHENA_QUERY]` | Athena catalog, database, and SQL |
| `[REDSHIFT_CLUSTER]`, `[REDSHIFT_DATABASE]`, `[REDSHIFT_DB_USER]`, `[REDSHIFT_QUERY]` | Redshift connection metadata and SQL |
| `[REDSHIFT_CLUSTER_ROLE_ARN]` | IAM role attached to the Redshift cluster for dataset generation |

Set `SOURCE_KIND` to `athena` or `redshift`. Exactly one dataset-definition branch is emitted. Configure its explicit image framework/version/Python fields the same way as the script template.
