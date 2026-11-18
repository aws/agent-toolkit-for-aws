# Synthetic Dataset Generation Template

# Cell 0 [markdown]: Synthetic Dataset Generation

# Cell 1: Verify the SDK

# %pip install --upgrade 'sagemaker>=3.30.0,<4.0' boto3 -q  # NOTEBOOK_ONLY
# This cell confirms imports resolve before we submit jobs.
from sagemaker.ai_registry import DataPreparer, DatasetJobConfig, JobCategory
from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

print("DataPreparer ready:", DataPreparer)

# Cell 2: Discover Available Fields

# Print the full schema tree — shows every field, type, required flag,
# and description for synthetic dataset generation jobs. New fields added by the service appear
# here automatically with no SDK update needed.
DatasetJobConfig.print_schema(JobCategory.SYNTHETIC_DATA_GENERATION)

# Cell 3: Configure Intelligent Defaults

from sagemaker.core.helper.session_helper import Session, get_execution_role

session = Session()
ROLE_ARN = get_execution_role()
bucket = session.default_bucket()
OUTPUT_S3_URI = f"s3://{bucket}/output/"

print(f"✅ Role:   {ROLE_ARN}")
print(f"✅ Bucket: {bucket}")
print(f"✅ Output: {OUTPUT_S3_URI}")

# Cell 4: Job Configuration

JOB_BASE_NAME = ""      # e.g., "sdg-my-project" — SDK appends "-{UTC-timestamp}"
DATASET_NAME = ""       # name for the resulting DataSet
SPEC_S3_URI = ""        # e.g., "s3://my-bucket/input/my-spec/task_description.txt"
INPUT_DATA_S3_URI = ""  # optional — CDG contextual data
NUM_SAMPLES = 100       # 1..50000, full-run size
IS_TABULAR = False      # set True if Step 1b confirmed tabular generation
SAMPLE_SIZE = 5 if IS_TABULAR else 10  # sample run size (smaller for tabular — CSV structure verification needs fewer rows)
GENERATION_MODEL = "us.anthropic.claude-haiku-5-5"     # model for data generation
VERIFICATION_MODEL = "us.anthropic.claude-sonnet-5"    # model for sample verification
CODE_GENERATION_MODEL = "us.anthropic.claude-sonnet-5" # model for code generation (spec-based sample run)

# Optional MLflow tracking — leave None unless the user asked to log this job
# to SageMaker managed MLflow (Step 1, input 7). To enable, set e.g.
# MLFLOW_CONFIG = {"MlflowResourceArn": "arn:aws:sagemaker:<region>:<acct>:mlflow-app/<id>"}
MLFLOW_CONFIG = None

# OUTPUT_S3_URI comes from Cell 3; it is passed to each DatasetJobConfig below.
# ROLE_ARN is set in Cell 3 for user visibility; the service reads it from the Session.
preparer = DataPreparer(base_job_name=JOB_BASE_NAME, sagemaker_session=session)

# Cell 5: Sample Generation

WAIT = True

# Build the per-category payload. `DatasetJobConfig` is dynamically validated
# at submit time against the Hub-published JobConfigSchema for
# SyntheticDataGeneration — you can inspect the schema with
#   DatasetJobConfig.print_schema(JobCategory.SYNTHETIC_DATA_GENERATION)

sample_config = DatasetJobConfig(
    dataset_name=f"{DATASET_NAME}-sample",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": SPEC_S3_URI},
        "NumSamples": SAMPLE_SIZE,
        "ModelConfig": {
            "SampleGenerationModelConfig": {"ModelId": GENERATION_MODEL},
            "SampleVerificationModelConfigs": [{"ModelId": VERIFICATION_MODEL}],
            "CodeGenerationModelConfig": {"ModelId": CODE_GENERATION_MODEL},
        },
    },
    output_data_config={"OutputS3Uri": OUTPUT_S3_URI},
)
# Only include InputDataS3Uri when actually provided.
if INPUT_DATA_S3_URI:
    sample_config.generation_config["InputDataS3Uri"] = INPUT_DATA_S3_URI

# Log to SageMaker managed MLflow only when configured in Cell 4.
if MLFLOW_CONFIG:
    sample_config.mlflow_config = MLFLOW_CONFIG

print(f"Submitting sample ({SAMPLE_SIZE} records)…")
if WAIT:
    sample_dataset = preparer.generate(sample_config)

    # sample_dataset.arn is the Hub content ARN — pass this downstream to dataset
    # quality evaluation (via DataPreparer.evaluate) or InputData(data_source=
    # sample_dataset.source) for ModelTrainer.
    print()
    print("Sample DataSet.arn    :", sample_dataset.arn)
    print("Sample DataSet.source :", sample_dataset.source)
    print("Sample DataSet.job_arn:", sample_dataset.job_arn)
else:
    sample_job = preparer.generate(sample_config, wait=False)
    print()
    print(f"Submitted (wait=False). Job ARN: {sample_job.job_arn}")
    print("Re-attach later with DataPreparer.attach(job_arn) to retrieve the DataSet.")

# sample_dataset is used by Cell 6 (refinement) and Cell 7 (full generation)
# to derive the code artifacts path.
# sample_dataset.job_arn is printed last so script-delivery mode can re-attach
# from the next script via DataPreparer.attach("<sample job ARN>").

# Cell 6: Refinement

WAIT = True

# Iteration cell — re-run after generation.py / verifiers.py are updated.
# Skip this cell if you're happy with the initial samples.

RUN_REFINEMENT = False  # ← Set to True after updating code artifacts

if not RUN_REFINEMENT:
    print("⚠️ Refinement is disabled. Set RUN_REFINEMENT = True above after updating your code artifacts.")
else:
    # Derive code artifacts path from the INITIAL SAMPLE (only it has generation_code/)
    code_artifacts_uri = sample_dataset.source[:-len("output/")] + "generation_code/"

    refined_config = DatasetJobConfig(
        dataset_name=f"{DATASET_NAME}-refined",
        generation_config={
            "DatasetSpecification": {
                "CodeArtifacts": {
                    "GenerationCodeS3Uri": code_artifacts_uri + "generation.py",
                    "VerifiersCodeS3Uri":  code_artifacts_uri + "verifiers.py",
                },
            },
            "NumSamples": SAMPLE_SIZE,
            "ModelConfig": {
                "SampleGenerationModelConfig": {"ModelId": GENERATION_MODEL},
                "SampleVerificationModelConfigs": [{"ModelId": VERIFICATION_MODEL}],
            },
        },
        output_data_config={"OutputS3Uri": OUTPUT_S3_URI},
    )
    if INPUT_DATA_S3_URI:
        refined_config.generation_config["InputDataS3Uri"] = INPUT_DATA_S3_URI
    if MLFLOW_CONFIG:
        refined_config.mlflow_config = MLFLOW_CONFIG

    print(f"Re-generating {SAMPLE_SIZE} samples with updated code…")
    print(f"  Code artifacts: {code_artifacts_uri}")
    if WAIT:
        refined_dataset = preparer.generate(refined_config)
        print()
        print("Refined DataSet.arn   :", refined_dataset.arn)
        print("Refined DataSet.source:", refined_dataset.source)
    else:
        refined_job = preparer.generate(refined_config, wait=False)
        print()
        print(f"Submitted (wait=False). Job ARN: {refined_job.job_arn}")
        print("Re-attach later with DataPreparer.attach(job_arn) to retrieve the DataSet.")

# Cell 7: Full Generation

WAIT = True

# Reuse the code artifacts from the INITIAL SAMPLE for full-scale generation.
code_artifacts_uri = sample_dataset.source[:-len("output/")] + "generation_code/"

full_config = DatasetJobConfig(
    dataset_name=DATASET_NAME,
    generation_config={
        "DatasetSpecification": {
            "CodeArtifacts": {
                "GenerationCodeS3Uri": code_artifacts_uri + "generation.py",
                "VerifiersCodeS3Uri":  code_artifacts_uri + "verifiers.py",
            },
        },
        "NumSamples": NUM_SAMPLES,
        "ModelConfig": {
            "SampleGenerationModelConfig": {"ModelId": GENERATION_MODEL},
            "SampleVerificationModelConfigs": [{"ModelId": VERIFICATION_MODEL}],
        },
    },
    output_data_config={"OutputS3Uri": OUTPUT_S3_URI},
)
if INPUT_DATA_S3_URI:
    full_config.generation_config["InputDataS3Uri"] = INPUT_DATA_S3_URI
if MLFLOW_CONFIG:
    full_config.mlflow_config = MLFLOW_CONFIG

print(f"Submitting full generation ({NUM_SAMPLES} records)…")
if WAIT:
    full_dataset = preparer.generate(full_config)
    print()
    print("Full DataSet.arn   :", full_dataset.arn)
    print("Full DataSet.source:", full_dataset.source)
else:
    full_job = preparer.generate(full_config, wait=False)
    print()
    print(f"Submitted (wait=False). Job ARN: {full_job.job_arn}")
    print("Re-attach later with DataPreparer.attach(job_arn) to retrieve the DataSet.")
