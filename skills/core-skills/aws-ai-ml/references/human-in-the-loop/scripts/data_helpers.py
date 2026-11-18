"""
Shared data helpers for SageMaker AI Agent Skills.

Resolves dataset ARNs to S3 paths and reads data files from local disk or S3.

S3 reads are pinned to a bucket owner (ExpectedBucketOwner): the caller's own
account unless the caller names another one. A bucket name can be deleted and
re-created by someone else, so a read without the pin could return another
account's data. IAM for an S3 read: s3:GetObject on the object,
s3:ListBucket on the bucket (to tell another account's bucket from a permission
problem when a read is refused, and to find the .jsonl in a folder such as a hub
dataset's), and sts:GetCallerIdentity when no
owner is given (no IAM permission needed, but it needs an AWS region, from
AWS_REGION, AWS_DEFAULT_REGION or the AWS config).
"""

import json
import os
import re
from typing import List, Optional

from sagemaker.core import Attribution, set_attribution

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


# The shapes the hub ARN is built from; the hub name pattern is DescribeHubContent's own.
_PARTITION = r"aws(-[a-z]+)*"
_REGION = r"[a-z]{2}(-[a-z]+)+-\d+"
_HUB_NAME = r"[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}"


def resolve_dataset_arn_to_s3(dataset_arn: str, region: Optional[str] = None) -> str:
    """Resolve a dataset hub content ARN to its S3 URI.

    Args:
        dataset_arn: ARN like arn:aws:sagemaker:us-west-2:123456789012:hub-content/HubName/DataSet/Name/Version
        region: AWS region. If None, the ARN's own region; a different region is refused,
            because the hub in that region is not the one the ARN names.

    Returns:
        The document's DatasetS3Uri when it has one, else
        s3://<DatasetS3Bucket>/<DatasetS3Prefix>. Either can name a file or a folder
        (such as a labeling job's review/ folder); read_records() reads a folder's
        single .jsonl.

    Raises:
        ValueError: If the ARN or ``region`` is invalid, or the hub document is unreadable or
            names no valid S3 location.
        RuntimeError: If the DescribeHubContent call fails.
    """
    # Validate and parse ARN
    parts = dataset_arn.split(":")
    if len(parts) < 6 or not parts[5].startswith("hub-content/"):
        raise ValueError(
            f"Invalid dataset ARN format: {dataset_arn}. "
            "Expected: arn:aws:sagemaker:<region>:<account>:hub-content/<HubName>/DataSet/<Name>[/<Version>]"
        )
    if not (
        re.fullmatch(_PARTITION, parts[1])
        and re.fullmatch(_REGION, parts[3])
        and re.fullmatch(r"\d{12}|aws", parts[4])
    ):
        raise ValueError(
            f"Invalid dataset ARN format: {dataset_arn}. "
            "Expected a partition, a region and a 12-digit account (or aws): arn:aws:sagemaker:<region>:<account>:hub-content/..."
        )
    if region and region != parts[3]:
        raise ValueError(
            f"Region {region!r} differs from the dataset ARN's region {parts[3]!r}; "
            "the dataset is read only from the ARN's own region."
        )
    region = parts[3]

    resource_parts = parts[5].split("/")
    if len(resource_parts) < 4:
        raise ValueError(
            f"Invalid dataset ARN resource: {parts[5]}. "
            "Expected: hub-content/<HubName>/DataSet/<Name>[/<Version>]"
        )

    hub_name = resource_parts[1]
    if not re.fullmatch(_HUB_NAME, hub_name):
        raise ValueError(f"Invalid hub name in dataset ARN: {hub_name!r}.")
    content_name = resource_parts[3]
    content_version = resource_parts[4] if len(resource_parts) > 4 else None

    kwargs = {
        # The hub's ARN, not its bare name: a bare name reads the caller's own hub of that name,
        # so another account's dataset ARN would read a different dataset.
        "hub_name": f"arn:{parts[1]}:sagemaker:{region}:{parts[4]}:hub/{hub_name}",
        "hub_content_type": "DataSet",
        "hub_content_name": content_name,
    }
    if content_version:
        kwargs["hub_content_version"] = content_version

    try:
        import contextlib
        import sys

        import boto3

        # Some sagemaker-core versions log to stdout on each client; keep that off a caller's
        # stdout during this call.
        with contextlib.redirect_stdout(sys.stderr):
            from sagemaker.core.resources import HubContent

            content = HubContent.get(
                **kwargs, session=boto3.session.Session(region_name=region), region=region
            )
        response = {"HubContentDocument": content.hub_content_document}
    except Exception as e:
        # The type, the error code and the text with the caller's role session removed.
        raise RuntimeError(
            f"Failed to describe hub content for {dataset_arn}: {type(e).__name__}: "
            f"{_error_code(e)}: {scrub_identity(str(e))}"
        ) from None

    try:
        doc = json.loads(response.get("HubContentDocument") or "")
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise ValueError(f"Hub content {dataset_arn} has no readable dataset document.")
    uri = doc.get("DatasetS3Uri")
    if uri:  # the dataset's file or folder, when the document names it
        if not (isinstance(uri, str) and uri.startswith("s3://") and len(uri) > 5):
            raise ValueError(f"Hub content {dataset_arn} has an invalid DatasetS3Uri.")
        return uri
    bucket, prefix = doc.get("DatasetS3Bucket"), doc.get("DatasetS3Prefix")
    if not (isinstance(bucket, str) and bucket and isinstance(prefix, str)):
        raise ValueError(
            f"Hub content {dataset_arn} names no dataset location "
            "(DatasetS3Uri, or DatasetS3Bucket and DatasetS3Prefix)."
        )
    return f"s3://{bucket}/{prefix}"  # a file or a folder: read_records() reads either


class CrossAccountBucketError(PermissionError):
    """The read was refused by the owner check; nothing was read.

    ``confirmed`` is True when the bucket is reachable and another account owns it. It is
    False when these credentials can't tell: the bucket may be another account's (one that
    grants s3:GetObject but not s3:ListBucket) or the caller may lack access to it.
    """

    def __init__(self, bucket: str, expected_owner: str, confirmed: bool):
        self.bucket = bucket
        self.confirmed = confirmed
        what = (
            "is not owned by account" if confirmed else "could not be read as a bucket of account"
        )
        super().__init__(
            f"s3://{bucket} {what} {expected_owner}, so nothing was read from it. "
            "If it belongs to another account the user trusts, read it with that account's id "
            "as expected_bucket_owner."
        )


def _error_code(e: Exception) -> str:
    return ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code", "") or type(
        e
    ).__name__


# A person's name in an AWS identity: an assumed role's session, a federated user, an IAM user
# (with its path), or the name after a role/user unique id. IAM names may hold any of [\w+=,.@-].
_NAME = r"[\w+=,.@-]+"
_IDENTITY_NAME = (
    (re.compile(rf"(assumed-role/{_NAME})/{_NAME}"), r"\1"),
    (re.compile(rf"(:federated-user)/{_NAME}"), r"\1"),
    (re.compile(r"(:user)/[\w+=,.@/-]+"), r"\1"),
    (re.compile(rf"\b((?:AROA|AIDA|ASIA)[A-Z0-9]+):{_NAME}"), r"\1"),
)


def scrub_identity(text: str) -> str:
    """``text`` with the person's name dropped from every AWS identity in it.

    ``assumed-role/<role>/<session>`` keeps the role, ``federated-user/<name>`` and
    ``user/<path>/<name>`` keep only the type, and ``<unique id>:<name>`` keeps the id; the rest
    of the text is unchanged.
    """
    for pattern, repl in _IDENTITY_NAME:
        text = pattern.sub(repl, text)
    return text


def _scrubbed(e: Exception) -> Exception:
    """``e`` itself (same class, ``.response`` and code), its message with the caller's name dropped."""
    e.args = tuple(scrub_identity(a) if isinstance(a, str) else a for a in e.args) or e.args
    err = (getattr(e, "response", None) or {}).get("Error")
    if isinstance(err, dict) and isinstance(err.get("Message"), str):
        err["Message"] = scrub_identity(err["Message"])
    return e


def _caller_account() -> str:
    import boto3

    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or boto3.session.Session().region_name
    )
    if not region:
        raise ValueError("No AWS region configured. Set AWS_REGION or AWS_DEFAULT_REGION.")
    os.environ.setdefault(
        "AWS_STS_REGIONAL_ENDPOINTS", "regional"
    )  # never the global us-east-1 endpoint
    try:
        return boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    except Exception as e:
        raise _scrubbed(e)


def _owner_check_outcome(s3, bucket: str, owner: str) -> Optional[bool]:
    """After a denied owner-pinned read, ask HeadBucket (metadata only) why.

    None: ``owner`` owns the bucket, or it doesn't exist (the read failed for another reason).
    True: reachable, and another account owns it. False: denied with and without the owner
    check, so these credentials can't tell whose bucket it is. Any other error on either
    HeadBucket (throttling, network, credentials) is raised: it is not an ownership answer.
    """
    try:
        s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=owner)
        return None
    except Exception as e:
        code = _error_code(e)
        if code in ("404", "NoSuchBucket", "NotFound"):
            return None
        if code not in ("403", "AccessDenied"):
            raise _scrubbed(e)
    try:
        s3.head_bucket(Bucket=bucket)
        return True
    except Exception as e:
        if _error_code(e) in ("403", "AccessDenied"):
            return False
        raise _scrubbed(e)  # throttling, network, credentials: not an ownership answer


MAX_READ_BYTES = 50 * 1024 * 1024  # the most this skill reads and parses client-side


class RecordsTooLargeError(ValueError):
    """A records file is too large to read client-side."""

    def __init__(self, path: str, size: int):
        super().__init__(
            f"{path} is {size / 1024 / 1024:.0f} MB, over the {MAX_READ_BYTES // 1024 // 1024} MB "
            "this skill reads client-side. Review a sample of it instead (for example, have "
            "dataset-transformation write one), or split it."
        )
        self.path, self.size = path, size


def _raise_refused(s3, bucket: str, owner: str, e: Exception):
    """Raise the error for a refused owner-pinned S3 call: CrossAccountBucketError when
    the owner check explains it, else the error itself, scrubbed."""
    if _error_code(e) not in ("403", "AccessDenied"):
        raise _scrubbed(e)
    confirmed = _owner_check_outcome(s3, bucket, owner)
    if confirmed is None:
        raise _scrubbed(e)
    raise CrossAccountBucketError(bucket, owner, confirmed) from None


def _get_owned(s3, bucket: str, key: str, owner: str):
    try:
        return s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=owner)
    except Exception as e:
        _raise_refused(s3, bucket, owner, e)


def _folder_jsonl_key(
    s3,
    bucket: str,
    prefix: str,
    owner: str,
    path: str,
    allow_empty: bool = False,
    object_error=None,
) -> Optional[str]:
    """The key of the one .jsonl directly in the folder ``prefix`` (owner-pinned
    listing). More than one is a ValueError, and so is none unless ``allow_empty``
    (then None): the agent never picks a file. A refused listing goes through the
    owner check, unless ``object_error`` is given: then a denied listing raises that
    error instead, and any other failed listing raises its own error (scrubbed)."""
    keys = []
    try:
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix, Delimiter="/", ExpectedBucketOwner=owner
        ):
            keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".jsonl")]
    except Exception as e:
        if object_error is not None and _error_code(e) in ("403", "AccessDenied"):
            raise _scrubbed(object_error) from None
        _raise_refused(s3, bucket, owner, e)
    if not keys and allow_empty:
        return None
    if len(keys) != 1:
        found = ", ".join(k.rsplit("/", 1)[-1] for k in keys[:5]) or "none"
        raise ValueError(
            f"{path} is a folder with {len(keys)} .jsonl files directly in it "
            f"({found}); nothing was read. Name the file to read."
        )
    return keys[0]


def read_records(path: str, expected_bucket_owner: Optional[str] = None) -> List[dict]:
    """Read JSONL records from a local file or S3 URI.

    Args:
        path: Local file path or S3 URI (s3://bucket/key).
        expected_bucket_owner: For an S3 URI, the account that must own the bucket.
            Default: the caller's own account.

    Returns:
        List of parsed JSON records.

    Raises:
        CrossAccountBucketError: The owner check refused the read: an account other than
            ``expected_bucket_owner`` (default: the caller's) owns the bucket, or these
            credentials can't tell; nothing was read.
        RecordsTooLargeError: The file is over MAX_READ_BYTES (50 MB), the most this skill
            reads client-side; nothing was parsed.
        ValueError: The S3 URI names a folder that holds no .jsonl, or more than one,
            directly in it; nothing was read.
        botocore ``ClientError``: the S3 error itself, the caller's name dropped from its
            message, for any other failed read; a missing object that names no folder
            keeps its NoSuchKey, even when the folder listing is denied.

    A folder (no key, a key ending in ``/``, or a key without ``.jsonl`` that S3 reports
    missing as an object) is read through the one ``.jsonl`` directly in it, such as a
    labeling job's ``review/review_rows.jsonl`` behind a review DataSet's
    ``DatasetS3Uri``. The listing is owner-pinned like the read.
    """
    if path.startswith("s3://"):
        import boto3

        parts = path[len("s3://") :].split(
            "/", 1
        )  # only the leading scheme: a key may contain "s3://"
        bucket, key = parts[0], (parts[1] if len(parts) > 1 else "")
        owner = (
            str(expected_bucket_owner) if expected_bucket_owner else _caller_account()
        )  # a HIL log value may be a number
        s3 = boto3.client("s3")
        if not key or key.endswith("/"):
            key = _folder_jsonl_key(s3, bucket, key, owner, path)  # type: ignore[assignment]
        try:
            obj = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=owner)
        except Exception as e:
            if _error_code(e) not in ("NoSuchKey", "404") or key.endswith(".jsonl"):
                _raise_refused(s3, bucket, owner, e)
            # No such object: it may be a folder named without its trailing "/". The
            # NoSuchKey already passed the owner pin, so a refused listing is not another
            # account's bucket: it keeps the object's own error.
            key = _folder_jsonl_key(  # type: ignore[assignment]
                s3, bucket, key + "/", owner, path, allow_empty=True, object_error=e
            )
            if key is None:  # not a folder either: the object is missing
                raise _scrubbed(e)
            obj = _get_owned(s3, bucket, key, owner)
        size = obj.get("ContentLength")
        if size is not None and size > MAX_READ_BYTES:
            obj["Body"].close()
            raise RecordsTooLargeError(path, size)
        content = obj["Body"].read().decode("utf-8")
        lines = content.strip().split("\n")
    else:
        size = os.path.getsize(path)
        if size > MAX_READ_BYTES:
            raise RecordsTooLargeError(path, size)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

    return [json.loads(line) for line in lines if line.strip()]
