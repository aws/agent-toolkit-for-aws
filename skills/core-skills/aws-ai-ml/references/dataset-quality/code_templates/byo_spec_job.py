# Bring-your-own-spec job — skill-caller lane (bring-your-own-spec.md Step 4S)
# Submits ONE dataset quality evaluation job against a spec the caller already has and prints the
# job name and ARN. With WAIT = True it then waits and prints the S3 URI of the job's
# metadata.json; with WAIT = False it ends after the submission, and the caller re-attaches
# later. Nothing else: no built-in metrics, no exploratory analysis, no report generation
# (the caller's page does that from metadata.json).
#
# Prerequisites: the SDK is installed as sagemaker-python-sdk-setup.md says, and the dataset is
# registered in the SageMaker AI Registry (DatasetArn).
# Every bracketed placeholder is filled by the agent from bring-your-own-spec.md Step 3; its
# placeholder table has a row for each of the ten (expected format and an example).
# Dependencies: sagemaker-core, sagemaker-train, boto3.

# Cell 0 [markdown]: Bring-your-own-spec evaluation
# ⚠️ This evaluation uses Amazon Bedrock. [Bedrock Service Terms](https://aws.amazon.com/service-terms/) and pricing apply.
# A judge model chosen by the service scores the rows whenever the spec has criteria a model must judge, in the
# account running the job. The spec is the whole evaluation: no built-in metrics run.

# Cell 1: Configuration and imports

import json

import boto3
from sagemaker.ai_registry import DataPreparer, DatasetJobConfig
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

DATASET_ARN = "[DATASET_ARN]"            # Hub content ARN of the registered dataset
OUTPUT_S3_URI = "[OUTPUT_S3_URI]"        # S3 prefix the job writes its output folder under
JOB_NAME = "[JOB_NAME]"                  # job base name, ASCII letters/digits/hyphens; the SDK appends a timestamp
ROLE_ARN = [ROLE_ARN]                    # the role bring-your-own-spec.md Step 3 settled, "<role arn>" (quoted; the caller's role when it passed one); None (unquoted) only when the session identity is itself a SageMaker execution role
SPEC_S3_URI = [SPEC_S3_URI]              # "s3://.../specs/<file>.md" (quoted), or None when CODE_ARTIFACT_S3_URI is set
CODE_ARTIFACT_S3_URI = [CODE_ARTIFACT_S3_URI]  # an earlier job's spec_eval/ folder (its Reports.SpecEval judge_code.py URI without the file name), else None
DOWN_SAMPLE_RECORD_COUNT = [DOWN_SAMPLE_RECORD_COUNT]  # None, or an integer only when the caller asked for a sample
JUDGE_MODEL_ID = [JUDGE_MODEL_ID]        # None (unquoted) unless the caller named a model, then "<model id>" (quoted); the service applies its default
CONTEXT_DOCUMENTS_S3_URI = [CONTEXT_DOCUMENTS_S3_URI]  # None (unquoted) unless the caller brought reference documents for context: documents criteria, then "s3://.../reference-docs/" (quoted; a folder URI ending in "/")
WAIT = [WAIT]                            # True: the caller reads metadata.json next, so wait for the job. False: start it, print its name and ARN, and end

# Cell 2: Assemble the job configuration

if bool(SPEC_S3_URI) == bool(CODE_ARTIFACT_S3_URI):
    raise ValueError("set exactly one of SPEC_S3_URI and CODE_ARTIFACT_S3_URI")

spec_eval_config = {"SpecS3Uri": SPEC_S3_URI} if SPEC_S3_URI else {"CodeArtifactS3Uri": CODE_ARTIFACT_S3_URI}
if DOWN_SAMPLE_RECORD_COUNT:
    spec_eval_config["DownSampleRecordCount"] = int(DOWN_SAMPLE_RECORD_COUNT)
if JUDGE_MODEL_ID:
    spec_eval_config["ModelConfig"] = {"JudgeModelConfig": {"ModelId": JUDGE_MODEL_ID}}
if CONTEXT_DOCUMENTS_S3_URI:
    if not CONTEXT_DOCUMENTS_S3_URI.endswith("/"):
        raise ValueError("CONTEXT_DOCUMENTS_S3_URI must be an S3 folder URI ending in /")
    spec_eval_config["ContextDocumentsS3Uri"] = CONTEXT_DOCUMENTS_S3_URI

dq_config = DatasetJobConfig(
    input_data_config=[{"DatasetArn": DATASET_ARN}],
    output_data_config={"S3OutputPath": OUTPUT_S3_URI},
    schema_version="3.0.0",              # required pin; unpinned resolves an older request version
)
dq_config.evaluation_config = {"Operations": [{"Operator": "spec_eval", "Config": spec_eval_config}]}  # spec only on this lane

# Cell 3: Submit; then wait and read the metadata URI, or hand back the job

REGION = DATASET_ARN.split(":")[3]            # the dataset's region is the job's region; nothing else decides it
session = Session(boto_session=boto3.Session(region_name=REGION))
preparer = DataPreparer(sagemaker_session=session, base_job_name=JOB_NAME, **({"role": ROLE_ARN} if ROLE_ARN else {}))
job = preparer.evaluate(dq_config, wait=False)  # submits; returns the Job handle
print(json.dumps({"job_name": job.job_name, "job_arn": job.job_arn}))

if WAIT:
    # The caller needs MetadataS3Uri, which DescribeJob returns only at completion.
    job.wait()                                  # polls until terminal; does NOT raise on failure

    # The handle carries the DescribeJob fields after the wait.
    if job.job_status != "Completed":
        raise SystemExit(f"{job.job_name} ended {job.job_status}: {job.failure_reason or 'no failure reason given'}")
    metadata_s3_uri = json.loads(job.job_config_document).get("MetadataS3Uri")  # job_config_document is a JSON string
    if not metadata_s3_uri:  # no MetadataS3Uri (troubleshooting.md)
        raise SystemExit(f"{job.job_name} completed without MetadataS3Uri; find its outputs with "
                         f"dataset-quality/scripts/dq_job_output.py --job-arn {job.job_arn}")
    print(json.dumps({"job_name": job.job_name, "job_arn": job.job_arn, "job_status": job.job_status,
                      "metadata_s3_uri": metadata_s3_uri}))
else:
    # The caller collects the outputs later: DataPreparer.attach(job_arn, wait=False), then Step 4S item 4.
    print(f"Submitted; not waiting. Re-attach later with job_arn: {job.job_arn}")
