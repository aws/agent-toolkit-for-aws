#!/usr/bin/env python3
"""Report a dataset quality evaluation job's state and where its outputs are in S3.

    python3 <skill-root>/references/dataset-quality/scripts/dq_job_output.py \
        --job-arn arn:aws:sagemaker:<region>:<account>:job/DataQualityEvaluation/<job-name>

Prints one JSON object: ``job_name``, ``job_status``, ``secondary_status``, ``failure_reason``,
``operators`` (the ``Operator`` values the job ran), ``metadata_s3_uri`` (set when the job has
completed), ``output_folder`` (the job's S3 folder, or null while nothing is written yet), and
``record_level`` (the S3 URI of ``record_level/evaluated_data.jsonl`` once that file exists).

A completed job's folder is the one holding ``JobConfigDocument.MetadataS3Uri``, and its
``metadata.json`` lists every report. Before then the folder is found by ``running_job_folder``,
the one place that derives it.

Dependencies: Python 3.9+, the SageMaker Python SDK with DataPreparer, boto3.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

RECORD_LEVEL_SUFFIX = "/record_level/evaluated_data.jsonl"


def split_s3(uri: str) -> tuple:
    bucket, _, key = uri[len("s3://") :].partition("/")
    if not uri.startswith("s3://") or not bucket:
        raise ValueError(f"not an S3 URI: {uri!r}")
    return bucket, key


def _keys(s3: Any, folder: str, delimiter: Optional[str] = None) -> List[str]:
    bucket, prefix = split_s3(folder)
    extra = {"Delimiter": delimiter} if delimiter else {}
    found: list = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, **extra):
        found.extend(f"s3://{bucket}/{p['Prefix']}" for p in page.get("CommonPrefixes", []))
        found.extend(f"s3://{bucket}/{o['Key']}" for o in page.get("Contents", []))
    return found


def creation_seconds(created_at: Any) -> List[str]:
    """The job's creation second as the folder name spells it (``2026-10-27T192836``), then the
    second before it, in case the creation time reached the client rounded up."""
    if not isinstance(created_at, datetime):
        created_at = datetime.strptime(str(created_at)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    second = created_at.astimezone(timezone.utc).replace(microsecond=0)
    return [t.strftime("%Y-%m-%dT%H%M%S") for t in (second, second - timedelta(seconds=1))]


def _read_json(s3: Any, uri: str) -> Dict[str, Any]:
    bucket, key = split_s3(uri)
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def running_job_folder(
    s3: Any, job_name: str, document: Dict[str, Any], created_at: Any
) -> Optional[str]:
    """The output folder of a job DescribeJob gives no MetadataS3Uri for, or None if none exists yet.

    The folder name ends in the job's creation time without colons, with any fractional seconds,
    and is matched to the second. ``<S3OutputPath>/data-quality-evaluation/<JobName>/<createdAt>/``
    is tried first, then ``<S3OutputPath>/<JobName>-<createdAt>/``.
    """
    output_path = ((document.get("OutputDataConfig") or {}).get("S3OutputPath") or "").rstrip("/")
    if not output_path:
        return None
    for layout in (
        f"{output_path}/data-quality-evaluation/{job_name}/{{}}",
        f"{output_path}/{job_name}-{{}}",
    ):
        for stamp in creation_seconds(created_at):
            prefix = layout.format(stamp)
            folders = [uri for uri in _keys(s3, prefix, delimiter="/") if uri.endswith("/")]
            if len(folders) > 1:
                raise RuntimeError(f"more than one output folder matches {prefix}: {folders}")
            if folders:
                return folders[0]
    return None


def locate(job: Any, s3: Any) -> Dict[str, Any]:
    """``job`` is a DataPreparer Job handle after ``attach`` or ``refresh``."""
    document = json.loads(job.job_config_document or "{}")
    metadata_s3_uri = document.get("MetadataS3Uri")
    if metadata_s3_uri:
        folder = metadata_s3_uri.rsplit("/", 1)[0] + "/"
        reports = _read_json(s3, metadata_s3_uri).get("Reports") or {}
        record_level = next(iter(reports.get("RecordLevel") or []), None)
    else:
        folder = running_job_folder(s3, job.job_name, document, job.created_at)
        record_level = (
            next((uri for uri in _keys(s3, folder) if uri.endswith(RECORD_LEVEL_SUFFIX)), None)
            if folder
            else None
        )
    operations = (document.get("EvaluationConfig") or {}).get("Operations") or []
    return {
        "job_name": job.job_name,
        "job_status": job.job_status,
        "secondary_status": job.secondary_status,
        "failure_reason": job.failure_reason,
        "operators": [op.get("Operator") for op in operations if isinstance(op, dict)],
        "metadata_s3_uri": metadata_s3_uri,
        "output_folder": folder,
        "record_level": record_level,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--job-arn", required=True, help="the DataQualityEvaluation job ARN")
    args = parser.parse_args(argv)

    import boto3
    from sagemaker.ai_registry import DataPreparer
    from sagemaker.core import Attribution, set_attribution
    from sagemaker.core.helper.session_helper import Session

    set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
    boto_session = boto3.Session(region_name=args.job_arn.split(":")[3])
    job = DataPreparer.attach(
        args.job_arn, wait=False, sagemaker_session=Session(boto_session=boto_session)
    )
    print(json.dumps(locate(job, boto_session.client("s3")), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
