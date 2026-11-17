# Cell 0 [markdown]: API Dataset Transformation
# Describe the transformation: which operator, input dataset(s), and expected output.
# State that this runs as a SageMaker DataTransformation CreateJob via the pySDK.

# Cell 1: Configuration
#
# [PLACEHOLDER] block — all inputs resolved up front, before any SDK call.

import os

if os.path.basename(os.getcwd()) == "notebooks":
    os.chdir("..")
PROJECT_ROOT = os.getcwd()

RUN_NUM = [RUN_NUMBER]
API_INPUTS = [API_INPUTS]
OUTPUT_S3_PATH = "[OUTPUT_S3_URI]"       # s3:// prefix where the transform output lands
OPERATOR = "[OPERATOR]"                  # e.g. "FuzzyDedup" — from operator-name-mapping.md

# OPERATOR_CONFIG: the operator's Config fields ONLY, as a resolved dict
# literal. Copy the exact keys from api-operator-configs.md for the chosen
# operator — never invent a field. For example:
#   OPERATOR_CONFIG = {"TextField": "note"}
# The schema is validated client-side except LanguageFilter and PiiRedaction, which have no
# client-side Config validation; their unknown keys and bad values fail the job at run time.
# Other operators raise DataPreparerSchemaValidationError. This dict is placed under
# transformation_config["Operations"][].Config in Cell 4. Example for FuzzyDedup:
#   {"JaccardThreshold": 0.7, "NumPerm": 128, "NgramSize": 5}
OPERATOR_CONFIG = [OPERATOR_CONFIG]

# Wait handling (see api-execution-flow.md): default True. Set False ONLY for an
# explicit background run or when a size/duration estimate crosses the routing
# threshold (a PiiRedaction job always does: it makes a model call per row); a
# False run returns a Job handle — persist job.job_arn and re-attach.
# For OPERATOR = "PiiRedaction", set this to False before running.
WAIT = True
JOB_ARN = ""  # Set to the saved ARN only when re-attaching after a restart.
job = None  # Populated by Cell 5 or Cell 6 for a WAIT=False job.

# Telemetry attribution: emit BOTH signals BEFORE the FIRST SDK call.
# DataSet.create below is a pySDK call that creates hub content, so attribution
# must be set here — not later — or registration runs un-attributed. (1)
# set_attribution stamps the pySDK calls; (2) SAGEMAKER_PYSDK_CREATED_BY stamps
# provenance on the created job. Both are required, not alternatives.
from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
os.environ["SAGEMAKER_PYSDK_CREATED_BY"] = Attribution.SAGEMAKER_AGENT_PLUGIN.value

# Cell 2: Discover the operator schema (optional, discoverability)
# print_schema shows the live Config contract for the operator's category, so a
# typo or wrong field is caught here rather than at submit time. OPTIONAL: the
# mandatory imports live in Cell 3 (below), so skipping this cell is safe.

from sagemaker.ai_registry.data_preparer import DatasetJobConfig
from sagemaker.ai_registry.data_preparer.constants import JobCategory

DatasetJobConfig.print_schema(JobCategory.DATA_TRANSFORMATION)

# Cell 3: Register the input dataset (runtime registration)
# Raw S3 input is registered into the hub as a DataSet (DataSet.create wraps
# import_hub_content) and its ARN becomes the transform input. This is a RUNTIME
# step of the API lane, not a user prerequisite.

# Keep mandatory imports outside the optional schema-discovery cell.
from sagemaker.ai_registry.data_preparer import (
    DataPreparer,
    DataPreparerJobTimeoutError,
    DatasetJobConfig,
)
from sagemaker.ai_registry.data_preparer.constants import JobCategory
from sagemaker.ai_registry.dataset import DataSet

input_dataset_arns = []
if not JOB_ARN:
    _output_bucket = OUTPUT_S3_PATH.removeprefix("s3://").partition("/")[0]
    if not OUTPUT_S3_PATH.startswith("s3://") or not _output_bucket:
        raise ValueError("OUTPUT_S3_PATH must be an s3:// path")
    expected_input_count = 2 if OPERATOR == "Merge" else 1
    if len(API_INPUTS) != expected_input_count:
        raise ValueError(
            f"{OPERATOR} requires exactly {expected_input_count} API input(s)"
        )
    for input_spec in API_INPUTS:
        existing_arn = input_spec.get("DatasetArn", "")
        source_uri = input_spec.get("S3Uri", "")
        dataset_name = input_spec.get("DataSetName", "")
        if bool(existing_arn) == bool(source_uri):
            raise ValueError(
                "Each API input must set exactly one of DatasetArn or S3Uri"
            )
        if source_uri and not dataset_name:
            raise ValueError("A raw S3 API input also requires DataSetName")
        if source_uri and not (
            isinstance(dataset_name, str)
            and 1 <= len(dataset_name) <= 63
            and dataset_name.isascii()
            and dataset_name[0].isalnum()
            and dataset_name[-1].isalnum()
            and all(char.isalnum() or char == "-" for char in dataset_name)
        ):
            raise ValueError("DataSetName must be a valid 1-63 character name")
        if source_uri:
            source_bucket, _, source_key = source_uri.removeprefix("s3://").partition("/")
            if (
                not source_uri.startswith("s3://")
                or not source_bucket
                or not source_key
                or source_key.endswith("/")
            ):
                raise ValueError("S3Uri must be an exact s3:// object URI")

    for input_spec in API_INPUTS:
        existing_arn = input_spec.get("DatasetArn", "")
        if existing_arn:
            input_dataset_arns.append(existing_arn)
            continue
        input_dataset = DataSet.create(
            name=input_spec["DataSetName"],
            source=input_spec["S3Uri"],
            wait=True,
        )
        print(f"Registered input dataset: {input_dataset.arn}")
        input_dataset_arns.append(input_dataset.arn)

# Cell 4: Assemble the DataTransformation job config
# Source-verified shape (live `DatasetJobConfig.print_schema(DATA_TRANSFORMATION)`):
#   - input_data_config : list of {"DatasetArn": ...} entries (1; Merge uses 2)
#   - output_data_config: {"S3OutputPath": <s3 uri>}   (REQUIRED — where output lands)
#   - transformation_config: an OBJECT with an "Operations" list — NOT a bare list.
#     Each operation is {"Operator": <name>, "Config": {...}}.
# job_category is inferred from transform() but we set it explicitly. Each job runs ONE
# operator per job (single-entry Operations list); a multi-step pipeline is run as
# chained jobs — feed this output ARN into the next job's input_data_config.

job_config = None
if not JOB_ARN:
    job_config = DatasetJobConfig(
        job_category=JobCategory.DATA_TRANSFORMATION,
        input_data_config=[
            {"DatasetArn": input_dataset_arn}
            for input_dataset_arn in input_dataset_arns
        ],
        output_data_config={"S3OutputPath": OUTPUT_S3_PATH},
        transformation_config={
            "Operations": [
                {
                    "Operator": OPERATOR,          # [OPERATOR]
                    "Config": OPERATOR_CONFIG,     # exact Config keys from api-operator-configs.md
                }
            ]
        },
    )

# Cell 5: Run the transform
# transform(wait=True) blocks, streams status transitions, and returns List[DataSet]
# (always a list — Split/Merge may emit >1 output). No preview for built-in
# operations. On timeout, DataPreparerJobTimeoutError carries job_arn — catch, detach,
# and surface the ARN so the user can re-attach later (Cell 6).

# Telemetry attribution was already emitted in Cell 3, BEFORE the first
# SDK call (DataSet.create), so both the registration and this transform are
# stamped. Do not re-emit it here.

import time

# jobName must match [a-zA-Z0-9](-*[a-zA-Z0-9]){0,62} and be <= 63 chars
# (DescribeJob/transform reject longer names). Keep the operator + timestamp
# suffix whole (needed for uniqueness) and truncate the dataset-name prefix to fit.
job_name = None
if not JOB_ARN:
    preparer = DataPreparer()
    _suffix = f"-{OPERATOR.lower()}-{int(time.time())}"
    first_input = API_INPUTS[0]
    prefix_source = first_input.get("DataSetName", "")
    if not prefix_source:
        arn_parts = [part for part in first_input["DatasetArn"].split("/") if part]
        prefix_source = arn_parts[-2] if len(arn_parts) > 1 else arn_parts[-1]
    normalized_prefix = "".join(
        char
        if char.isascii() and (char.isalnum() or char == "-")
        else "-"
        for char in prefix_source
    ).strip("-")
    while "--" in normalized_prefix:
        normalized_prefix = normalized_prefix.replace("--", "-")
    normalized_prefix = normalized_prefix or "dataset"
    _prefix = normalized_prefix[: 63 - len(_suffix)].rstrip("-")
    job_name = f"{_prefix}{_suffix}"   # unique per run, <= 63 chars

    background_job_ready = False
    try:
        outputs = preparer.transform(
            job_config,
            job_name=job_name,
            wait=WAIT,
            logs=WAIT,                                    # logs require wait=True
        )
        if WAIT:
            # Surface a traceable job record: job identity and output DataSet ARN(s).
            print(f"Job: {job_name}")
            for ds in outputs:
                # Immutability: output is a NEW hub content version; input is preserved.
                print(f"Output dataset: {ds.arn}  source={ds.source}")
        else:
            # wait=False → Job handle. Retain it for same-session status/finalize,
            # and print the ARN so Cell 6 can re-attach after a kernel restart.
            job = outputs
            JOB_ARN = job.job_arn
            background_job_ready = True
    except DataPreparerJobTimeoutError as timeout_error:
        JOB_ARN = timeout_error.job_arn
        job = DataPreparer.attach(JOB_ARN, wait=False)
        WAIT = False
        background_job_ready = True
    except Exception as e:
        # Actionable failure surfacing, then re-raise (fail loud — do not swallow).
        # The DataPreparer exception taxonomy:
        #   DataPreparerSchemaValidationError  → wrong/misspelled Config field (see .errors)
        #   DataPreparerSchemaNotFoundError    → no schema for category/version (.available_versions)
        #   DataPreparerConfigurationError     → pre-submit config incomplete
        #   DataPreparerJobFailedError         → JobStatus=Failed (.failure_reason, .secondary_status)
        #     LanguageFilter / PiiRedaction: .failure_reason is a generic ClientError — read failure_info.error_message in the job's report.json (Cell 7 finds it)
        #   DataPreparerJobStoppedError        → JobStatus=Stopped
        #   DataPreparerJobTimeoutError        → waiter timeout (.job_arn, .elapsed_seconds) — detach + re-attach
        # NOTE: transform(wait=True) can raise an
        # OutputDatasetArns-missing / result-rehydration error on a job that actually
        # reached Completed. That case is handled deliberately by the AGENT, not here:
        # see api-execution-flow.md "Progress + actionable failure" (confirm via
        # DescribeJob, then read report.json in the job's output folder). The template
        # does not auto-recover — it surfaces the error rather than guessing success.
        print(f"Transform failed: {type(e).__name__}: {e}")
        raise
    if background_job_ready:
        print(f"Submitted (background). Re-attach with job_arn: {job.job_arn}")

# Cell 6: Re-attach to a background job (only when WAIT=False)
# Cross-session: set JOB_ARN in Cell 1 to the ARN printed by Cell 5.
if JOB_ARN or not WAIT:
    from sagemaker.ai_registry.data_preparer import DataPreparer

    reattach_arn = JOB_ARN or getattr(job, "job_arn", "")
    if not reattach_arn:
        raise RuntimeError(
            "Set JOB_ARN in Cell 1 to the ARN printed by Cell 5 before re-attaching."
        )
    job = DataPreparer.attach(reattach_arn, wait=False)
    print(f"Background job status: {job.job_status}")
    if job.job_status in {"Failed", "Stopped"}:
        raise RuntimeError(
            f"Built-in transformation ended with {job.job_status}: "
            f"{job.failure_reason}"
        )
    if job.job_status == "Completed":
        outputs = DataPreparer.attach(reattach_arn, wait=True)
        for ds in outputs:
            print(ds.arn, ds.source)

# Cell 7: Finalize — report the built-in transformation output.
# Prefer the re-attached handle after a kernel restart. In the original
# wait=True session there is no handle, so retain the submit-time name.
this_job_arn = getattr(job, "job_arn", None)
this_job_name = (
    this_job_arn.rstrip("/").rsplit("/", 1)[-1]
    if this_job_arn
    else globals().get("job_name")
)
if not this_job_name:
    raise RuntimeError(
        "No built-in transformation job identity is available. Re-run Cell 5 "
        "in the original session, or re-attach the saved job ARN in Cell 6."
    )

# Only a FINISHED job has a report. A background built-in submit
# (WAIT=False) has not completed yet, so there is no report.json to stat — re-attach
# via Cell 6 first, then finalize.
job_status = (
    getattr(job, "job_status", None)
    if JOB_ARN or not WAIT
    else "Completed"
)
job_completed = job_status == "Completed"
if not job_completed:
    print(f"Background submit (WAIT=False): job {this_job_name} status={job_status or 'not re-attached'}; "
          "re-attach via Cell 6, then re-run this finalize.")
else:
    # Find report.json under the current service layout, then fall back to the
    # earlier flat layout for jobs created before that contract changed.
    from sagemaker.core.s3 import S3Downloader

    out_bucket, _, out_prefix = OUTPUT_S3_PATH.removeprefix("s3://").rstrip("/").partition("/")
    out_prefix = f"{out_prefix}/" if out_prefix else ""
    current_prefix = (
        f"s3://{out_bucket}/{out_prefix}data-transformation/{this_job_name}/"
    )
    legacy_report_uri = (
        f"s3://{out_bucket}/{out_prefix}{this_job_name}/report.json"
    )
    try:
        report_candidates = [
            uri for uri in S3Downloader.list(current_prefix)
            if uri.endswith("/report.json")
        ]
        if not report_candidates:
            report_candidates = [
                uri for uri in S3Downloader.list(legacy_report_uri)
                if uri == legacy_report_uri
            ]
        if len(report_candidates) != 1:
            raise RuntimeError(
                "Expected exactly one transformation report, found "
                f"{len(report_candidates)} under {current_prefix}"
            )
        print(f"Transformation report: {report_candidates[0]}")
    except Exception as report_error:
        print(f"Transformation report not resolved: {report_error}")
