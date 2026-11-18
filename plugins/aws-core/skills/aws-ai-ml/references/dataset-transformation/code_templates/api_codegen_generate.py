# Cell 0 [markdown]: Generate Transformation Code and a Review Sample
# CodeGen Job 1 only. The service generates transformer.py and a transformed
# sample with AutoExecute=False, then this artifact stops. It never submits the
# full-dataset execution job.

# Cell 1: Configuration
INPUT_SOURCE = "[INPUT_S3_URI]"
INPUT_FORMAT = "[INPUT_FORMAT]"
DATASET_NAME = "[DATASET_NAME]"
OUTPUT_S3_PATH = "[OUTPUT_S3_URI]"
SPECIFICATION_S3_URI = "[S3_URI_OF_SPEC]"
EXPECTED_BUCKET_OWNER = "[EXPECTED_BUCKET_OWNER]"
TRANSFORMATION_SPEC = [TRANSFORMATION_SPEC_TEXT]
REQUIRED_INPUT_FIELDS = [REQUIRED_INPUT_FIELDS]
EXPECTED_OUTPUT_FIELDS = [EXPECTED_OUTPUT_FIELDS]
WAIT = True
JOB_ARN = ""

# Cell 2: Validate schema reconciliation before any service job
import csv
import io
import json
import os
import re
import warnings

from botocore.exceptions import ClientError
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session
from sagemaker.core.s3 import parse_s3_url

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
os.environ["SAGEMAKER_PYSDK_CREATED_BY"] = Attribution.SAGEMAKER_AGENT_PLUGIN.value

SCHEMA_SAMPLE_BYTES = 1_048_576
if not JOB_ARN:
    if (
        not re.fullmatch(r"[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}", DATASET_NAME)
        or len(DATASET_NAME) > 63
    ):
        raise ValueError("DATASET_NAME must be a valid 1-63 character name")
    _output_bucket = OUTPUT_S3_PATH.removeprefix("s3://").partition("/")[0]
    if not OUTPUT_S3_PATH.startswith("s3://") or not _output_bucket:
        raise ValueError("OUTPUT_S3_PATH must be an s3:// path")
    if not re.fullmatch(r"\d{12}", EXPECTED_BUCKET_OWNER):
        raise ValueError("EXPECTED_BUCKET_OWNER must be a 12-digit AWS account ID")
    sagemaker_session = Session()
    input_format = INPUT_FORMAT.strip().lower()
    if input_format not in {"jsonl", "csv", "tsv", "parquet"}:
        raise ValueError("INPUT_FORMAT must be one of: jsonl, csv, tsv, parquet")
    if not INPUT_SOURCE.startswith("s3://"):
        raise ValueError(
            "CodeGen schema preflight requires an exact backing s3:// object URI"
        )
    input_bucket, input_key = parse_s3_url(INPUT_SOURCE)
    if not input_bucket or not input_key or input_key.endswith("/"):
        raise ValueError(
            "CodeGen schema preflight requires an exact backing s3:// object URI, "
            "not a bucket or prefix"
        )

    if input_format == "parquet":
        schema_sample_truncated = False
        sagemaker_session.s3_client.head_object(
            Bucket=input_bucket,
            Key=input_key,
            ExpectedBucketOwner=EXPECTED_BUCKET_OWNER,
        )
        try:
            import pyarrow.fs as pyarrow_fs
            import pyarrow.parquet as pyarrow_parquet
        except ImportError as error:
            raise RuntimeError(
                "Parquet schema preflight requires the pyarrow package"
            ) from error
        # Reuse the session identity so the owner check and Parquet read cannot diverge.
        session_credentials = (
            sagemaker_session.boto_session.get_credentials().get_frozen_credentials()
        )
        s3_filesystem = pyarrow_fs.S3FileSystem(
            region=sagemaker_session.boto_region_name,
            access_key=session_credentials.access_key,
            secret_key=session_credentials.secret_key,
            session_token=session_credentials.token,
        )
        with s3_filesystem.open_input_file(
            f"{input_bucket}/{input_key}"
        ) as parquet_input:
            parquet_metadata = pyarrow_parquet.read_metadata(parquet_input)
            if parquet_metadata.num_rows == 0:
                raise ValueError("CodeGen schema preflight found no input records")
            actual_input_fields = sorted(
                parquet_metadata.schema.to_arrow_schema().names
            )
    else:
        try:
            response = sagemaker_session.s3_client.get_object(
                Bucket=input_bucket,
                Key=input_key,
                Range=f"bytes=0-{SCHEMA_SAMPLE_BYTES - 1}",
                ExpectedBucketOwner=EXPECTED_BUCKET_OWNER,
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "InvalidRange":
                raise ValueError(
                    "CodeGen schema preflight found no input records"
                ) from error
            raise
        try:
            input_sample = response["Body"].read()
        finally:
            response["Body"].close()
        if not input_sample:
            raise ValueError("CodeGen schema preflight found no input records")
        input_object_size = int(response["ContentRange"].rsplit("/", 1)[1])
        schema_sample_truncated = input_object_size > len(input_sample)
        schema_sample_has_complete_record = True
        if schema_sample_truncated:
            last_newline = input_sample.rfind(b"\n")
            if last_newline == -1:
                if input_format != "jsonl":
                    raise ValueError(
                        "CodeGen schema preflight could not read a complete record "
                        f"within {SCHEMA_SAMPLE_BYTES} bytes"
                    )
                schema_sample_has_complete_record = False
                input_sample = b""
            else:
                input_sample = input_sample[: last_newline + 1]
        input_text = input_sample.decode("utf-8-sig")
        if input_format in {"csv", "tsv"}:
            delimiter = "\t" if input_format == "tsv" else ","
            reader = csv.reader(io.StringIO(input_text), delimiter=delimiter)
            header = next(reader, None)
            if not any(row for row in reader) and not schema_sample_truncated:
                raise ValueError("CodeGen schema preflight found no input records")
            actual_input_fields = sorted(header or [])
        else:
            sampled_records = []
            for line_number, line in enumerate(input_text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        "CodeGen schema preflight found invalid JSONL at line "
                        f"{line_number}: {error}"
                    ) from error
                if not isinstance(record, dict):
                    raise ValueError(
                        "CodeGen schema preflight requires JSON object records"
                    )
                sampled_records.append(record)
            if not sampled_records:
                if not schema_sample_truncated:
                    raise ValueError("CodeGen schema preflight found no input records")
                schema_sample_has_complete_record = False
            actual_input_fields = sorted(
                {field for record in sampled_records for field in record}
            )

    missing_input_fields = sorted(
        set(REQUIRED_INPUT_FIELDS) - set(actual_input_fields)
    )
    if missing_input_fields:
        if input_format == "jsonl" and schema_sample_truncated:
            warnings.warn(
                "Transformation spec references input field(s) absent from the "
                f"bounded schema sample: {missing_input_fields}. Available sampled "
                f"fields: {actual_input_fields}. The JSONL sample was truncated, "
                "so the field(s) may appear later in the dataset.",
                RuntimeWarning,
            )
        else:
            raise ValueError(
                "Transformation spec references input field(s) absent from the dataset: "
                f"{missing_input_fields}. Available fields: {actual_input_fields}"
            )
    elif input_format == "jsonl" and not schema_sample_has_complete_record:
        warnings.warn(
            "CodeGen schema preflight could not inspect a complete JSONL record "
            f"within {SCHEMA_SAMPLE_BYTES} bytes. Proceeding because the bounded "
            "sample cannot prove a schema mismatch.",
            RuntimeWarning,
        )

# Cell 3: Upload the visible spec and register the input dataset
from sagemaker.ai_registry.data_preparer import DataPreparer, DatasetJobConfig
from sagemaker.ai_registry.data_preparer.constants import JobCategory
from sagemaker.ai_registry.dataset import DataSet
from sagemaker.core.s3 import S3Downloader, S3Uploader

input_dataset_arn = None
if not JOB_ARN:
    if not SPECIFICATION_S3_URI.startswith("s3://"):
        raise ValueError("SPECIFICATION_S3_URI must be an s3:// object URI")
    spec_bucket, spec_key = parse_s3_url(SPECIFICATION_S3_URI)
    if not spec_bucket or not spec_key or spec_key.endswith("/"):
        raise ValueError("SPECIFICATION_S3_URI must be an s3:// object URI")

    # Keeping the exact spec text in this artifact makes the generated-code intent
    # reviewable before execution. The uploader writes to this exact object URI.
    S3Uploader.upload_string_as_file_body(
        TRANSFORMATION_SPEC,
        desired_s3_uri=SPECIFICATION_S3_URI,
    )
    print(f"Uploaded transformation spec: {SPECIFICATION_S3_URI}")

    input_dataset = DataSet.create(
        name=DATASET_NAME,
        source=INPUT_SOURCE,
        wait=True,
    )
    input_dataset_arn = input_dataset.arn
    print(f"Registered input dataset: {input_dataset.arn}")

    codegen_config = DatasetJobConfig(
        job_category=JobCategory.DATA_TRANSFORMATION,
        input_data_config=[{"DatasetArn": input_dataset_arn}],
        output_data_config={"S3OutputPath": OUTPUT_S3_PATH},
        transformation_config={
            "Operations": [
                {
                    "Operator": "CodeGen",
                    "Config": {
                        "SpecificationS3Uri": SPECIFICATION_S3_URI,
                        "AutoExecute": False,
                    },
                }
            ]
        },
    )

# Cell 4: Generate code and sample, then stop
import time

_suffix = f"-codegen-{int(time.time())}"
_prefix = DATASET_NAME[: 63 - len(_suffix)].rstrip("-")
codegen_job_name = f"{_prefix}{_suffix}"

try:
    if JOB_ARN:
        job = DataPreparer.attach(JOB_ARN, wait=False)
        codegen_job_name = job.job_arn.rstrip("/").rsplit("/", 1)[-1]
    else:
        # AutoExecute=False produces review artifacts, not an output DataSet.
        job = DataPreparer().transform(
            codegen_config,
            job_name=codegen_job_name,
            wait=False,
            logs=False,
        )
        JOB_ARN = job.job_arn
    print(f"CodeGen job ARN: {job.job_arn}")
    if WAIT:
        job.wait(logs=True)
        job.refresh()
        if job.job_status != "Completed":
            raise RuntimeError(
                f"CodeGen job ended with status={job.job_status}: {job.failure_reason}"
            )

        job_document = json.loads(job.job_config_document or "{}")
        input_data_config = job_document.get("InputDataConfig")
        if not (
            isinstance(input_data_config, list)
            and input_data_config
            and isinstance(input_data_config[0], dict)
            and input_data_config[0].get("DatasetArn")
        ):
            raise RuntimeError(
                "Completed CodeGen job did not return "
                "InputDataConfig[0].DatasetArn in DescribeJob.JobConfigDocument"
            )
        input_dataset_arn = input_data_config[0]["DatasetArn"]
        approved_candidate_code_s3_uri = job_document.get("TransformationCodeS3Uri")
        report_uri = job_document.get("TransformationReportS3Uri")
        sample_source = (
            report_uri.rsplit("/", 1)[0] + "/sample_output.jsonl"
            if isinstance(report_uri, str) and report_uri.startswith("s3://")
            else None
        )
        if not approved_candidate_code_s3_uri or not sample_source:
            raise RuntimeError(
                "Completed CodeGen job did not return TransformationCodeS3Uri and "
                "TransformationReportS3Uri in DescribeJob.JobConfigDocument"
            )
        if not (
            isinstance(approved_candidate_code_s3_uri, str)
            and approved_candidate_code_s3_uri.startswith("s3://")
            and approved_candidate_code_s3_uri.endswith("/transformer.py")
        ):
            raise RuntimeError(
                "Completed CodeGen job returned an invalid TransformationCodeS3Uri: "
                f"{approved_candidate_code_s3_uri!r}"
            )
        generated_source = S3Downloader.read_file(approved_candidate_code_s3_uri)
        if not generated_source.strip():
            raise RuntimeError(
                f"Generated transformer is empty: {approved_candidate_code_s3_uri}"
            )
        # sample_output.jsonl is the documented sibling of the report for an
        # AutoExecute=False job. Reading it makes a service layout change or empty
        # artifact fail clearly instead of presenting a stale sample URI.
        sample_preview = S3Downloader.read_file(sample_source)
        if not sample_preview.strip():
            raise RuntimeError(f"CodeGen sample is empty: {sample_source}")

        sample_records = []
        for line_number, line in enumerate(sample_preview.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                sample_record = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"CodeGen sample is not valid JSONL at line {line_number}: {error}"
                ) from error
            if not isinstance(sample_record, dict):
                raise RuntimeError(
                    f"CodeGen sample line {line_number} is not a JSON object"
                )
            sample_records.append(sample_record)
        if not sample_records:
            raise RuntimeError(f"CodeGen sample is empty: {sample_source}")

        missing_output_fields = sorted(
            field
            for field in EXPECTED_OUTPUT_FIELDS
            if any(field not in record for record in sample_records)
        )
        if missing_output_fields:
            raise RuntimeError(
                "CodeGen sample is missing expected output field(s): "
                f"{missing_output_fields}"
            )

        print("STOP: review the sample and generated transformer.py before execution.")
        print(f"Sample output: {sample_source}")
        print(f"Generated code candidate: {approved_candidate_code_s3_uri}")
        print(f"CodeGen job: {codegen_job_name} ({job.job_arn})")
except Exception as e:
    print(f"CodeGen generate failed: {type(e).__name__}: {e}")
    raise
