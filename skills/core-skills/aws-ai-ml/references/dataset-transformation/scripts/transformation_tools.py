#!/usr/bin/env python3

import os

import boto3
from sagemaker.core import Attribution, image_uris, set_attribution
from sagemaker.core.helper.session_helper import Session, get_execution_role
from sagemaker.core.processing import FrameworkProcessor
from sagemaker.core.resources import ProcessingJob
from sagemaker.core.shapes import (
    ProcessingInput,
    ProcessingOutput,
    ProcessingS3Input,
    ProcessingS3Output,
)

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


def _get_session(region=None):
    """Create a SageMaker Session, optionally pinned to a region."""
    return Session(boto_session=boto3.Session(region_name=region) if region else None)


def execute_transformation_job(
    transform_script_path,
    dataset_source_s3,
    dataset_output_s3,
    instance_type="ml.m5.xlarge",
    region=None,
    execution_role=None,
    base_job_name="dataset-transformation",
    image_uri=None,
):
    """
    Execute a dataset transformation script as a SageMaker Processing Job
    using the V3 SDK FrameworkProcessor.

    The entire directory containing the script is uploaded as source_dir,
    so transform_fn.py (and any other dependencies) are included automatically.

    Args:
        transform_script_path: Local path to the transformation script (e.g., "<project-dir>/scripts/transform.py")
        dataset_source_s3: S3 URI of the input dataset
        dataset_output_s3: S3 URI for the transformed output dataset
        instance_type: ML instance type (default: ml.m5.xlarge)
        region: AWS region (auto-detected if None)
        execution_role: IAM role ARN (auto-detected if None)
        base_job_name: Prefix for the Processing Job name
        image_uri: Docker image URI for the processing container.
                   If None, uses the SKLearn processing image.
    """
    if not execution_role:
        execution_role = get_execution_role()

    sagemaker_session = _get_session(region)

    if not region:
        region = sagemaker_session.boto_region_name

    # Use SKLearn processing image as default (includes pandas)
    if not image_uri:
        image_uri = image_uris.retrieve(
            framework="sklearn",
            region=region,
            version="1.2-1",
            instance_type=instance_type,
        )

    source_dir = os.path.dirname(os.path.abspath(transform_script_path))
    script_name = os.path.basename(transform_script_path)

    processor = FrameworkProcessor(
        role=execution_role,
        image_uri=image_uri,
        command=["python3"],
        instance_count=1,
        instance_type=instance_type,
        base_job_name=base_job_name,
        sagemaker_session=sagemaker_session,
    )

    input_local_path = "/opt/ml/processing/input"
    output_local_path = "/opt/ml/processing/output"
    input_filename = os.path.basename(dataset_source_s3.rstrip("/"))

    processor.run(
        code=script_name,
        source_dir=source_dir,
        arguments=[
            "--input",
            os.path.join(input_local_path, input_filename),
            "--output",
            os.path.join(output_local_path, input_filename),
        ],
        inputs=[
            ProcessingInput(
                input_name="dataset",
                s3_input=ProcessingS3Input(
                    s3_uri=dataset_source_s3,
                    local_path=input_local_path,
                    s3_data_type="S3Prefix",
                    s3_input_mode="File",
                ),
            )
        ],
        outputs=[
            ProcessingOutput(
                output_name="transformed",
                s3_output=ProcessingS3Output(
                    s3_uri=dataset_output_s3,
                    local_path=output_local_path,
                    s3_upload_mode="EndOfJob",
                ),
            )
        ],
        wait=False,
    )

    print(
        f"Processing job '{processor.latest_job.processing_job_name}' submitted. Output will be at: {dataset_output_s3}"
    )


def describe_transformation_job(job_name, region=None):
    """
    Describe a SageMaker Processing Job by name.

    Args:
        job_name: The name of the processing job to describe.
        region: AWS region (auto-detected if None).

    Returns:
        dict: Job details including status, inputs, outputs, and timing info.
    """
    sagemaker_session = _get_session(region)

    job = ProcessingJob.get(
        processing_job_name=job_name,
        session=sagemaker_session.boto_session,
    )

    details = job.refresh().__dict__
    return {
        "job_name": job_name,
        "status": details.get("processing_job_status"),
        "failure_reason": details.get("failure_reason"),
        "creation_time": str(details.get("creation_time", "")),
        "processing_end_time": str(details.get("processing_end_time", "")),
        "inputs": details.get("processing_inputs", []),
        "outputs": getattr(details.get("processing_output_config"), "outputs", []),
    }
