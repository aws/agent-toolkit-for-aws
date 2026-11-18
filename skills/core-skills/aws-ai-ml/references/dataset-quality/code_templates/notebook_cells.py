# =============================================================================
# Dataset Quality Evaluation — Notebook Cell Templates
#
# The cells use the V3 SDK's DataPreparer entrypoint for the dataset quality evaluation job itself.
# CreateJob is handled by DataPreparer.evaluate(wait=False), which returns the
# Job handle at once; DescribeJob polling and the live status panel live in that
# handle's wait(). Cell 5's WAIT flag decides whether Cell 8 waits. No bespoke helpers.
#
# BYOD (bring-your-own-data) registers the dataset with DataSet.create
# (Cell 7; references/dataset-import.md).
#
# The agent selects which cells to include based on the user's entry point:
#
#   Entry point: Dataset ARN known     → Cells 0, 2 to 5, 8, 9
#   Entry point: Dataset in S3 (BYOD)  → Cells 0, 2 to 5, 7, 8, 9
#   Entry point: Local file            → Cells 0, 2 to 9
#
#   Cell 0 and Cell 9 are markdown cells (the title with the Bedrock notice; the
#   next step). The values the user or the agent sets sit at the top of the
#   cell that uses them, each before any logic (skill rule 14): Cell 3 holds
#   REGION and ROLE_ARN and stops when the region is not one the service runs in; Cell 5 (Job setup, in every path) the job name, the
#   dataset, the Operations list and the WAIT
#   flag; Cell 6 the upload bucket and path; Cell 7 the Hub content name, the
#   data file's URI and its format. Cell 5 also defines `preparer`, which
#   Cell 8 calls. Cell 6 (Upload) is the only local-file-only conditional
#   cell; Cell 7 (Import) runs for every BYOD entry. Markers: `# Cell N: Label`
#   for a code cell, `# Cell N [markdown]: Label` for a markdown cell.
#   The SDK is installed before the notebook runs, as the shared
#   sagemaker-python-sdk-setup.md says; no cell installs anything.
#
# The agent renumbers cells sequentially in the generated notebook.
# Placeholders are bracketed uppercase tokens; every one is listed, with its
# expected format and an example, in quality-job-submit.md's placeholder table.
#
# Note: a format validation only (overview.md Step 1, references/format-check.md)
# does not use a notebook; it runs scripts/format_detector.py directly. This
# template is for the quality evaluation job (references/quality-job-submit.md).
#
# -----------------------------------------------------------------------------
# SCHEMA VERSION:
#   JobConfigSchemaVersion "3.0.0", pinned in Cell 8 (why: dataset-service-api.md,
#   "Dataset Quality Evaluation", Important).
# =============================================================================


# -----------------------------------------------------------------------------
# Cell 0 [markdown]: Dataset quality evaluation
# -----------------------------------------------------------------------------
# Render as a MARKDOWN cell: the notebook's title, then the Bedrock notice from
# quality-job-submit.md "Confirm the plan" (the same lines, under the same
# conditions: the first line always, then only the family lines in the plan).
# Run this notebook with the kernel of the environment the setup page installed
# into; on a venv setup, register ./.venv as the kernel.

# # Dataset quality evaluation
#
# ⚠️ This evaluation uses Amazon Bedrock. [Bedrock Service Terms](https://aws.amazon.com/service-terms/) and pricing apply.
# [the spec-driven evaluation line and the taxonomy line, only when the plan has them]


# -----------------------------------------------------------------------------
# Cell 2: Verify the SDK
# -----------------------------------------------------------------------------
# Confirms the imports resolve in the notebook's kernel, and
# sets the usage attribution before any call to the service (Cell 4's schema
# read, with Cell 3's session, is the first).

from sagemaker.ai_registry import DataPreparer, DatasetJobConfig, JobCategory
from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
print("DataPreparer ready:", DataPreparer)


# -----------------------------------------------------------------------------
# Cell 3: Verify or configure intelligent defaults
# -----------------------------------------------------------------------------
# The user values come first: the region slot, then the two values the user
# picks at quality-job.md Step 11 (items 2 and 3), each None (unquoted) for the
# default; then the session, the default output location when none was picked,
# and the printout. The usage attribution is already set in Cell 2.

import boto3
from sagemaker.core.helper.session_helper import Session

REGION = ""                      # "" : the session's region. Set it (e.g. "us-east-1") only when the dataset is in another region (Step 8)
OUTPUT_S3_URI = [OUTPUT_S3_URI]  # "s3://<bucket>/<prefix>/" (quoted), or None (unquoted): s3://<default bucket>/output/
ROLE_ARN = [ROLE_ARN]            # "arn:aws:iam::<account>:role/<name>" (quoted), or None (unquoted) only when the session identity is itself a SageMaker execution role (Step 11 item 3)

boto_session = boto3.Session(region_name=REGION or None)
session = Session(boto_session=boto_session)

# The regions the service runs in (dataset-service-api.md "Available regions").
# The check stops the notebook before any upload, registration or submit.
SUPPORTED_REGIONS = ("us-east-1", "us-west-2")
if session.boto_region_name not in SUPPORTED_REGIONS:
    raise RuntimeError(
        f"the dataset quality evaluation runs in {SUPPORTED_REGIONS}; the job's region is "
        f"{session.boto_region_name}. Set REGION to one of them, or use a dataset there."
    )

if OUTPUT_S3_URI is None:
    OUTPUT_S3_URI = f"s3://{session.default_bucket()}/output/"

print(f"✅ Role:   {ROLE_ARN or 'resolved by the SDK at submit (Cell 5 prints the role used)'}")
print(f"✅ Region: {session.boto_region_name}")
print(f"✅ Output: {OUTPUT_S3_URI}")


# -----------------------------------------------------------------------------
# Cell 4: Discover available fields
# -----------------------------------------------------------------------------
# Print the full schema tree: every field, type, required flag and description
# for dataset quality evaluation jobs. The read goes to the job's region through
# Cell 3's session, the first call to the service.

DatasetJobConfig.print_schema(JobCategory.DATA_QUALITY_EVALUATION, schema_version="3.0.0", sagemaker_session=session)


# -----------------------------------------------------------------------------
# Cell 5: Job setup
# -----------------------------------------------------------------------------

EVALUATION_BASE_NAME = "[EVALUATION_BASE_NAME]"  # e.g. "dq-my-project"
DATASET_ARN          = "[DATASET_ARN]"            # populated by Cell 7 for BYOD flows

# The operations the job runs (Cell 8 sends it as the EvaluationConfig). Zero-config
# default: the deterministic default metrics. Replace with the Operations list
# assembled in quality-job-submit.md Step 12 when the plan has a spec, curated
# metrics, or the exploratory analysis.
EVALUATION_CONFIG = {"Operations": [{"Operator": "default_metrics"}]}

# Each Operations entry is {"Operator": ..., "Config": {...}}; only the listed
# operations run. Do NOT include EvaluationConfigSchemaVersion.
#
# RECOMMENDED — the requirements spec, plus the default metrics if the user
# asked for them (drop that entry if they declined the built-ins). spec_eval
# always names SpecS3Uri, or CodeArtifactS3Uri (the earlier run's spec_eval/
# FOLDER, not the .py file) to re-run the same criteria. A spec with
# context: documents criteria needs the folder of reference documents in the
# spec_eval Config as ContextDocumentsS3Uri (an S3 folder URI ending in "/").
# Check every object, hidden files included, against the contract
# in references/dataset-service-api.md, Spec-driven evaluation, "The documents
# folder"; that section states the folder limits and failure remedies;
# a folder that misses one fails the job before compute with the service's
# message naming the file or folder.
#
# EVALUATION_CONFIG = {"Operations": [
#     {"Operator": "default_metrics"},
#     {"Operator": "spec_eval", "Config": {"SpecS3Uri": "s3://<bucket>/specs/<dataset>-dq-spec.md"}},
#     # add "DownSampleRecordCount": 100 to the spec_eval Config to sample first
#     # add "ContextDocumentsS3Uri": "s3://<bucket>/reference-docs/" to the spec_eval Config for context: documents criteria
#     {"Operator": "exploratory_analysis"},   # only when the plan includes it
# ]}
#
# EXTRA METRICS sit next to default_metrics. Every View entry is
# {"Role": ..., "Column": ...} with the metric's Role (supported-metrics.md, or
# on-request-metrics.md for an on-request family);
# the column MUST exist in the records, and never a nested (list/dict) column.
# Settings sit beside View inside Config. Without a View a metric runs on the
# derived prompt/completion text; language_detection and pii_detection always
# need a View, e.g.:
#   {"Operator": "fuzzy_dedup", "Config": {"View": [{"Role": "Text", "Column": "completion"}], "JaccardThreshold": 0.8}}
#   {"Operator": "language_detection", "Config": {"View": [{"Role": "Text", "Column": "completion"}], "languages": ["en"]}}
#   {"Operator": "pii_detection", "Config": {"View": [{"Role": "Messages", "Column": "messages"}]}}
#   {"Operator": "data_balance", "Config": {"View": [{"Role": "Label", "Column": "difficulty"}, {"Role": "Label", "Column": "topic"}]}}
#   {"Operator": "effectiveness"}   # takes no View

# Whether Cell 8 waits for the job (the run option, quality-job-submit.md Delivery Mode).
WAIT = True  # True: notebook, and the script's run-it-and-wait option. False: the script's start-but-don't-wait option.

# The role goes on DataPreparer(role=...), never on the DatasetJobConfig
# (the service's rejection: troubleshooting.md, Common Errors).

preparer = DataPreparer(base_job_name=EVALUATION_BASE_NAME, sagemaker_session=session,
                        **({"role": ROLE_ARN} if ROLE_ARN else {}))
print("Role used:", preparer.role or "the SDK's default, resolved at submit")


# -----------------------------------------------------------------------------
# Cell 6: Upload dataset to S3  [CONDITIONAL — local-file entry point only]
# -----------------------------------------------------------------------------
# Include only when the user provides a local file path.
# Skip if the dataset is already in S3 or the user has a DatasetArn.

INPUT_BUCKET = "[INPUT_BUCKET]"  # target bucket for BYOD uploads
LOCAL_DATASET_PATH = "[LOCAL_DATASET_PATH]"  # the path as the user gave it; a \ or " in it written as \\ or \"
DATASET_S3_KEY = "byod/[HUB_CONTENT_NAME]/[DATASET_FILENAME]"  # the file name the same way

# The upload is a Python call in the notebook and in the script alike: no shell reads the
# path or the file name, so a quote, a space, $, { or a backtick in them stays literal.
session.boto_session.client("s3").upload_file(LOCAL_DATASET_PATH, INPUT_BUCKET, DATASET_S3_KEY)
print(f"Uploaded to: s3://{INPUT_BUCKET}/{DATASET_S3_KEY}")


# -----------------------------------------------------------------------------
# Cell 7: Register the dataset in the SageMaker AI Registry  [CONDITIONAL: BYOD only]
# -----------------------------------------------------------------------------
# Skip if the user already has a DatasetArn (e.g. from SDG output).
#
# DataSet.create registers one data file into the account's SageMaker AI Registry
# (references/dataset-import.md). A new name gets version 1.0.0; a name already registered gets
# the next major version. The cell does not read Cell 6's variables.
#   * Dataset in S3: the user's own file URI (one data file, never a folder).
#   * Local file: the URI Cell 6 printed, s3://<input bucket>/byod/<hub content name>/<filename>.

HUB_CONTENT_NAME = "[HUB_CONTENT_NAME]"  # e.g. "my-data": letters, digits and hyphens
DATASET_S3_URI   = "[DATASET_S3_URI]"    # e.g. "s3://my-input-bucket/datasets/my-data/train.jsonl": the data file's full URI
DATASET_FORMAT   = "[DATASET_FORMAT]"    # e.g. "HF_Prompt_Completion": the detector's result (Step 9); the SDK does not check it against the file

import inspect

from sagemaker.ai_registry import DataSet
from sagemaker.train.defaults import TrainDefaults

if not HUB_CONTENT_NAME:
    raise ValueError("Set HUB_CONTENT_NAME (the dataset's Hub content name) before registering.")

# The registration role: Cell 3's ROLE_ARN, or the SDK's default role when it is None.
REGISTRATION_ROLE_ARN = ROLE_ARN or TrainDefaults.get_role(sagemaker_session=session)

# A Custom registration passes no validation role.
VALIDATION_ROLE_ARN = REGISTRATION_ROLE_ARN if DATASET_FORMAT != "Custom" else None

# Passes validation_role_arn when the installed SDK takes it.
VALIDATION_ARGS = ({"validation_role_arn": VALIDATION_ROLE_ARN}
                   if "validation_role_arn" in inspect.signature(DataSet.create).parameters else {})

# Registers in the job's region (Cell 3's session).
dataset = DataSet.create(
    name=HUB_CONTENT_NAME,
    source=DATASET_S3_URI,
    dataset_file_format=DATASET_FORMAT,
    role=REGISTRATION_ROLE_ARN,
    **VALIDATION_ARGS,
    wait=False,
    sagemaker_session=session,
)
dataset.wait()  # returns when the entry is Available

DATASET_ARN = dataset.arn
print(f"Dataset registered: {dataset.name} version {dataset.version}")
print(f"Dataset ARN: {DATASET_ARN}")


# -----------------------------------------------------------------------------
# Cell 8: Evaluate the dataset
# -----------------------------------------------------------------------------
# Submits a DataQualityEvaluation job via DataPreparer, then waits or returns.
#   * evaluate(dq_config, wait=False) assembles the CreateJob envelope
#     (JobName, RoleArn, JobConfigSchemaVersion, JobConfigDocument, Tags, ...) and
#     returns the Job handle at once.
#   * The cell prints the job name and ARN as one JSON line right after submit,
#     so both survive a kernel restart or an ended turn. Re-attach later with
#     DataPreparer.attach(job_arn, wait=False) (references/progress-check.md);
#     describe_job takes the name, attach takes the ARN.
#   * The Operations list it sends is Cell 5's EVALUATION_CONFIG; the WAIT flag
#     is Cell 5's too. Nothing in this cell is set by the user or the agent.
#   * WAIT = True (notebook; the script's run-it-and-wait option): job.wait() polls
#     DescribeJob (status every 30s) and renders the same live status panel the
#     blocking evaluate() shows. job.wait() does NOT raise on Failed or Stopped,
#     so the cell checks job.job_status itself and raises RuntimeError with the
#     FailureReason (a HUB_FINALIZATION_FAILED job may still have output on S3).
#   * WAIT = False (the script's start-but-don't-wait option): the cell ends
#     right after the JSON line; nothing in this script polls.
#   * A dataset quality evaluation job registers no new hub content, so there is no output DataSet
#     handle; the job's metadata.json (JobConfigDocument.MetadataS3Uri, printed
#     on completion) lists the S3 URIs of its output files.
#   * The job is named from Cell 5's base_job_name.
#
# schema_version="3.0.0" is required (dataset-service-api.md, "Dataset Quality Evaluation", Important).

dq_config = DatasetJobConfig(
    input_data_config=[{"DatasetArn": DATASET_ARN}],
    output_data_config={"S3OutputPath": OUTPUT_S3_URI},
    schema_version="3.0.0",
)

# The operations the job runs: Cell 5's EVALUATION_CONFIG (the zero-config default,
# or the Operations list the agent assembled there from quality-job-submit.md Step 12).
dq_config.evaluation_config = EVALUATION_CONFIG

import json

job = preparer.evaluate(dq_config, wait=False)  # submits; returns the Job handle
print(json.dumps({"job_name": job.job_name, "job_arn": job.job_arn}))  # keep both: attach() takes the ARN, describe_job the name

if WAIT:  # Cell 5's flag: True unless the user chose start-but-don't-wait
    job.wait()  # live status panel; returns on Completed, Failed or Stopped without raising
    if job.job_status != "Completed":
        raise RuntimeError(f"{job.job_name} ended {job.job_status}: {job.failure_reason or 'no failure reason given'}")
    print("Evaluation complete:", job.job_name)
    metadata_s3_uri = json.loads(job.job_config_document).get("MetadataS3Uri")
    if not metadata_s3_uri:  # no MetadataS3Uri (troubleshooting.md)
        raise RuntimeError(f"{job.job_name} completed without MetadataS3Uri; find its outputs with "
                           f"dataset-quality/scripts/dq_job_output.py --job-arn {job.job_arn}")
    print(json.dumps({"metadata_s3_uri": metadata_s3_uri}))
    print()
    print("metadata.json echoes the request config and lists each output's S3 URI under Reports.")
    print("Copy the aggregate files one by one, each by its own URI; never copy the output folder whole:")
    print("  aggregate/quality_report.json       — dataset-level metric results (list of runs per operator)")
    print("  record_level/evaluated_data.jsonl   — original records + dq_<metric>__<column> score columns; streamed on request only, never downloaded")
    print("  spec_eval/judge_code.py             — derived criteria + checker (spec runs only); its folder re-runs via CodeArtifactS3Uri")
    print("  aggregate/exploratory/findings.json — ranked exploratory findings, also in quality_report.json (exploratory analysis only)")
else:
    print(f"Submitted; not waiting. Re-attach later with job_arn: {job.job_arn}")


# -----------------------------------------------------------------------------
# Cell 9 [markdown]: Next step — come back for the report
# -----------------------------------------------------------------------------
# Render as a MARKDOWN cell. Verbatim text (drop the last sentence unless the
# user opted into the dashboard in Step 11):

# ## ✅ Evaluation complete? Come back to the chat for the report
#
# Once the cell above shows **Evaluation complete**, return to the chat and
# say so (e.g. *"done — the job finished"*). The agent will write the quality
# report `dq_report_<job-name>.md` next to this notebook and walk you through
# the results. It can also add an interactive dashboard below.
