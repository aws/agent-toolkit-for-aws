#!/usr/bin/env python3
"""Shared runtime helpers for dataset-transformation pipelines.

Used by both delivery modes (script and notebook) and by the pre-built
operation scripts (``dedup_filter.py``, ``dataset_split.py``). Provides:

* I/O primitives that abstract over local paths and ``s3://`` URIs:
  :func:`is_s3`, :func:`split_s3_uri`, :func:`iter_text_lines`,
  :func:`copy_file`, :func:`input_exists`.
* Manifest discipline helpers: :func:`init_manifest`, :func:`record_step`,
  :func:`finalize`.
* Generic record-by-record JSONL runner: :func:`run_record_transform`.
* Opt-in input staging: :func:`stage_input` (copies a local input to
  ``data/raw/`` only when explicitly requested; S3 URIs pass through).

Behaviour summary:

* :func:`init_manifest`        — create a ``ManifestWriter`` and persist a
  ``status='partial'`` manifest immediately so a crash mid-pipeline still
  leaves a partial manifest on disk.
* :func:`record_step`          — record a single pipeline step on the
  manifest from a stats dict (returned by ``run_record_transform``,
  ``dedup_dataset``, or ``split_dataset``) and re-write the manifest with
  ``status='partial'``.
* :func:`finalize`             — copy the last step's output to the final
  destination(s), mark the run completed, and write the final manifest.
  When a destination is an ``s3://`` URI the file is uploaded via boto3
  rather than written to a local folder.
* :func:`run_record_transform` — read a JSONL input (local path or
  ``s3://`` URI) line-by-line, apply a transform function to each parsed
  record, and write results to a local output JSONL. S3 inputs are
  streamed in memory and never copied to ``data/raw/``.
* :func:`stage_input`          — **opt-in** helper. Inputs are read
  directly from their source by default; call this only when you
  explicitly want a local copy of the input under
  ``<project_dir>/data/raw/<basename>``. S3 URIs are returned unchanged.

Only stdlib imports are used at module load time. ``boto3`` is imported
lazily inside the S3 helpers, so pure local-to-local runs do not require
``boto3`` to be installed.

Bucket ownership: S3 calls are pinned to a bucket owner
(``ExpectedBucketOwner``): the caller's own account unless the caller names
another one with the ``expected_bucket_owner`` argument. A bucket name can be
deleted and re-created by someone else, so an unpinned call could read
another account's data or write customer data into it. An S3-to-S3 copy also
checks the source bucket's owner first. IAM for the S3 helpers:
``s3:GetObject`` on inputs, ``s3:PutObject`` on outputs, and
``sts:GetCallerIdentity`` when no owner is given (no IAM permission needed).

Environment variables: ``AWS_REGION`` and ``AWS_DEFAULT_REGION`` are read (by
name only) to choose the Region every STS and S3 client is created in; none
are set.
"""

import json
import os
import shutil
from typing import Callable, Optional, Union

from manifest_writer import ManifestWriter

# ---------------------------------------------------------------------------
# I/O helpers — shared between local and S3 paths
# ---------------------------------------------------------------------------


_S3_PREFIX = "s3://"

# The caller's own account ID, cached after the first sts:GetCallerIdentity so
# repeated S3 calls in one process do not call STS again. Used only when no
# expected_bucket_owner is passed. Module-level: shared by every caller in the
# process that imports this module.
_caller_account_id: Optional[str] = None


def _aws_region() -> str:
    """The AWS Region every client in this module is created in.

    Resolved from ``AWS_REGION``, then ``AWS_DEFAULT_REGION``, then the
    configured profile's Region. The STS client uses this Region's endpoint,
    so the identity lookup never falls back to the global endpoint. S3
    clients are created in this Region too, but boto3 follows S3 redirects to
    a bucket's own Region, so S3 calls are not held to it; the bucket owner
    check (``ExpectedBucketOwner``) is what guards which bucket is used.

    Raises
    ------
    RuntimeError
        If no Region is configured. S3 calls that used to run with no Region
        configured now stop here.
    """
    import boto3  # lazy import

    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or boto3.session.Session().region_name
    )
    if not region:
        raise RuntimeError(
            "No AWS Region configured. Set AWS_REGION or AWS_DEFAULT_REGION, "
            "or a Region in the AWS profile."
        )
    return region


def _s3_client():
    """An S3 client created in :func:`_aws_region` (see its note on redirects)."""
    import boto3  # lazy import

    return boto3.client("s3", region_name=_aws_region())


def _bucket_owner(expected_bucket_owner: Optional[str]) -> str:
    """The account that must own the bucket: the one given, else the caller's.

    Raises
    ------
    RuntimeError
        If no owner is given and the caller's account cannot be resolved
        (boto3 missing, no credentials or Region, or STS refused the call).
    """
    global _caller_account_id
    if expected_bucket_owner:
        return str(expected_bucket_owner)
    if _caller_account_id:
        return _caller_account_id
    try:
        import boto3  # lazy import

        sts = boto3.client("sts", region_name=_aws_region())
        _caller_account_id = sts.get_caller_identity()["Account"]
    except Exception as e:  # noqa: BLE001 - any failure means the owner is unknown
        raise RuntimeError(
            "Could not resolve the caller's AWS account to use as the S3 "
            f"ExpectedBucketOwner ({type(e).__name__}). Configure AWS "
            "credentials and a Region (AWS_REGION or AWS_DEFAULT_REGION), or "
            "pass expected_bucket_owner."
        ) from e
    return str(_caller_account_id)


def is_s3(path: str) -> bool:
    """Return True when *path* is an ``s3://`` URI."""
    return isinstance(path, str) and path.startswith(_S3_PREFIX)


def split_s3_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key`` into ``(bucket, key)``.

    Raises
    ------
    ValueError
        If *uri* is not a well-formed S3 URI with a non-empty key.
    """
    if not is_s3(uri):
        raise ValueError(f"Not an S3 URI: {uri!r}")
    bucket, _, key = uri[len(_S3_PREFIX) :].partition("/")
    if not bucket or not key:
        raise ValueError(
            f"S3 URI {uri!r} is missing a bucket or key (expected " "s3://bucket/key)."
        )
    return bucket, key


def iter_text_lines(
    path: str,
    on_decode_error: Optional[Callable[[], None]] = None,
    expected_bucket_owner: Optional[str] = None,
):
    """Yield lines (with no trailing newline) from a local path or S3 URI.

    For ``s3://`` URIs, the body is streamed via boto3's ``iter_lines`` —
    the input is never written to local disk. Local files are also read as
    bytes so both sources use the same strict UTF-8 decoding. By default an
    invalid line raises ``UnicodeDecodeError``. When *on_decode_error* is
    provided, the callback is invoked and that line is skipped so callers can
    include it in their malformed-record accounting without rewriting bytes.
    """

    def decode_line(raw: bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            if on_decode_error is None:
                raise
            on_decode_error()
            return None

    if is_s3(path):
        bucket, key = split_s3_uri(path)
        body = _s3_client().get_object(
            Bucket=bucket,
            Key=key,
            ExpectedBucketOwner=_bucket_owner(expected_bucket_owner),
        )["Body"]
        try:
            for raw in body.iter_lines():
                line = decode_line(raw)
                if line is not None:
                    yield line
        finally:
            body.close()
        return
    with open(path, "rb") as fin:
        for raw in fin:
            # Strip one line ending only — preserve interior whitespace so the
            # caller sees the same text for local files and S3 objects.
            if raw.endswith(b"\n"):
                raw = raw[:-1]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            line = decode_line(raw)
            if line is not None:
                yield line


def input_exists(path: str, expected_bucket_owner: Optional[str] = None) -> bool:
    """Return True when *path* exists and is readable.

    Accepts local paths and ``s3://`` URIs. For S3, performs a
    ``head_object`` to check existence without downloading the body.
    Use this instead of ``os.path.isfile`` whenever the path may be an
    S3 URI — ``os.path.isfile`` returns False for any ``s3://`` URI,
    even when the object exists.
    """
    if is_s3(path):
        from botocore.exceptions import ClientError

        bucket, key = split_s3_uri(path)
        try:
            _s3_client().head_object(
                Bucket=bucket,
                Key=key,
                ExpectedBucketOwner=_bucket_owner(expected_bucket_owner),
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise
    return os.path.isfile(path)


def stage_input(
    input_path: str,
    project_dir: str = ".",
    *,
    overwrite: bool = False,
) -> str:
    """**Opt-in** helper to copy a local input into ``data/raw/``.

    By default, transformation pipelines read inputs directly from their
    source — local paths are opened in place and S3 URIs are streamed by
    :func:`run_record_transform`. Call this helper only when you
    explicitly want a local copy of the input staged under
    ``<project_dir>/data/raw/<basename>`` (for example, to make the
    project self-contained for sharing or rerunning). It is **not**
    invoked by the default notebook cell templates.

    Local file inputs are copied into the project's ``data/raw/``
    directory. S3 URIs are returned unchanged — S3 inputs are streamed
    at execution time and are never written to disk under ``data/raw/``.

    The local copy is **idempotent**: if the destination file already
    exists, has the same size as the source, and is at least as new, the
    copy is skipped. Pass ``overwrite=True`` to force a re-copy even
    when an up-to-date copy is already present.

    Parameters
    ----------
    input_path : str
        Local file path or ``s3://`` URI. Must point to an existing,
        readable file when local.
    project_dir : str
        Project root directory. The staged file lands at
        ``<project_dir>/data/raw/<basename of input_path>``.
    overwrite : bool
        When True, force a fresh copy even if a same-sized, same-or-newer
        copy already exists at the destination.

    Returns
    -------
    str
        For S3 URIs, the URI unchanged. For local paths, the destination
        path under ``data/raw/`` (a local path).

    Raises
    ------
    FileNotFoundError
        When *input_path* is a local path that does not exist.
    """
    if is_s3(input_path):
        return input_path

    src = os.path.abspath(input_path)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Input file does not exist: {src}")

    raw_dir = os.path.join(project_dir, "data", "raw")
    os.makedirs(raw_dir, exist_ok=True)

    basename = os.path.basename(src)
    dst = os.path.join(raw_dir, basename)

    # If the user already pointed input_path at the staged copy, do
    # nothing — return the path as-is.
    if os.path.isfile(dst) and os.path.samefile(src, dst):
        return dst

    if not overwrite and os.path.isfile(dst):
        src_stat = os.stat(src)
        dst_stat = os.stat(dst)
        if src_stat.st_size == dst_stat.st_size and dst_stat.st_mtime >= src_stat.st_mtime:
            return dst

    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def init_manifest(
    project_dir: str,
    run_number: int,
    spec_input: list[str],
    final_output: str | list[str],
    hub_content_arn: str | None = None,
) -> ManifestWriter:
    """Initialize a :class:`ManifestWriter` for a notebook run.

    A ``status='partial'`` manifest is written to disk immediately so the
    file exists even if the notebook crashes before any step completes.

    Parameters
    ----------
    project_dir : str
        Root project directory. The manifest is written under
        ``<project_dir>/manifests/transformation_manifest_run_NNN.json``.
    run_number : int
        The run number (used for the manifest filename).
    spec_input : list[str]
        Original input path(s) from the Transformation Spec.
    final_output : str | list[str]
        Final output destination(s) from the Transformation Spec. May be a
        single path or a list of paths (multi-file output, e.g. when the
        final operation is a ``split``).
    hub_content_arn : str | None
        SageMaker Hub content ARN, set after Hub registration. ``None`` by
        default; can be set later via ``writer.set_hub_content_arn(arn)``.

    Returns
    -------
    ManifestWriter
        A writer pre-configured with the supplied metadata. The on-disk
        manifest file already exists with ``status='partial'``.
    """
    writer = ManifestWriter(
        project_dir=project_dir,
        run_number=run_number,
        spec_input=spec_input,
        final_output=final_output,
        hub_content_arn=hub_content_arn,
    )
    writer.set_status("partial")
    writer.write()
    return writer


# Stat keys consulted (in order) when extracting input / output record
# counts from a stats dict returned by a step function.
_INPUT_RECORD_KEYS: tuple[str, ...] = ("input_records", "total", "records")
_OUTPUT_RECORD_KEYS: tuple[str, ...] = ("output_records", "kept", "records")


def _extract_count(stats: dict, candidates: tuple[str, ...], role: str) -> int:
    """Return the first present key from *candidates* in *stats*.

    Raises
    ------
    ValueError
        If none of the candidate keys are present.
    """
    for key in candidates:
        if key in stats:
            return int(stats[key])
    raise ValueError(
        f"stats is missing a {role} record count key; expected one of "
        f"{list(candidates)}, got keys={sorted(stats.keys())}"
    )


def record_step(
    writer: ManifestWriter,
    step: int,
    op_type: str,
    input_path: str | list[str],
    output_path: str | list[str],
    stats: dict,
    parameters: dict | None = None,
    instruction: str | None = None,
) -> None:
    """Record a single pipeline step on the manifest, then persist.

    Extracts ``input_records`` and ``output_records`` from *stats* using
    the following fallbacks:

    * ``input_records``: ``stats['input_records']`` → ``stats['total']``
      → ``stats['records']``.
    * ``output_records``: ``stats['output_records']`` → ``stats['kept']``
      → ``stats['records']``.

    Parameters
    ----------
    writer : ManifestWriter
        The writer (typically obtained from :func:`init_manifest`).
    step : int
        1-based step number.
    op_type : str
        Inferred operation type (``"ingest"``, ``"clean"``, ``"dedup"``,
        ``"split"``, ``"schema_transform"``, ...).
    input_path : str | list[str]
        Input path(s) consumed by this step. Recorded on the operation as
        ``parameters['input_path']`` for reference. ``ManifestWriter`` does
        not have a dedicated input_path field — the previous step's
        ``output_path`` already records the upstream input.
    output_path : str | list[str]
        Output path(s) produced by this step. Stored on the operation.
    stats : dict
        Stats dict returned by ``run_record_transform``, ``dedup_dataset``
        or ``split_dataset``.
    parameters : dict | None
        Operation-specific parameters to record on the manifest. The
        ``input_path`` is added automatically when not already present.
    instruction : str | None
        Original natural-language instruction for this step.

    Raises
    ------
    ValueError
        When *stats* is missing both the input-count and output-count keys.
    """
    input_records = _extract_count(stats, _INPUT_RECORD_KEYS, role="input")
    output_records = _extract_count(stats, _OUTPUT_RECORD_KEYS, role="output")

    merged_parameters: dict = dict(parameters) if parameters else {}
    merged_parameters.setdefault("input_path", input_path)

    writer.add_operation(
        step=step,
        op_type=op_type,
        instruction=instruction if instruction is not None else "",
        input_records=input_records,
        output_records=output_records,
        output_path=output_path,
        parameters=merged_parameters,
    )
    writer.set_status("partial")
    writer.write()


def finalize(
    writer: ManifestWriter,
    final_path: str | list[str],
    last_step_output: str | list[str],
    expected_bucket_owner: Optional[str] = None,
) -> None:
    """Copy the last step's output to the final destination and complete.

    For string ``final_path`` / ``last_step_output``, ``shutil.copy`` is
    used. For lists, each element is copied positionally; the two lists
    must have the same length.

    After copying, the writer's final output and status are updated and
    the manifest is rewritten to disk. A one-line confirmation is printed.

    Parameters
    ----------
    writer : ManifestWriter
        The writer initialized at the start of the run.
    final_path : str | list[str]
        Final destination path(s) declared in the spec.
    last_step_output : str | list[str]
        Output path(s) produced by the last pipeline step.
    expected_bucket_owner : str, optional
        For an ``s3://`` destination, the account that must own the
        bucket. Default: the caller's own account.

    Raises
    ------
    TypeError
        If *final_path* and *last_step_output* are of mismatched kinds
        (one a string and the other a list).
    ValueError
        If both are lists but have different lengths.
    """
    if isinstance(final_path, str) and isinstance(last_step_output, str):
        copy_file(last_step_output, final_path, expected_bucket_owner)
    elif isinstance(final_path, list) and isinstance(last_step_output, list):
        if len(final_path) != len(last_step_output):
            raise ValueError(
                f"final_path (len={len(final_path)}) and last_step_output "
                f"(len={len(last_step_output)}) must have the same length"
            )
        for src, dst in zip(last_step_output, final_path):
            copy_file(src, dst, expected_bucket_owner)
    else:
        raise TypeError(
            "final_path and last_step_output must both be str or both be list[str]; "
            f"got final_path={type(final_path).__name__}, "
            f"last_step_output={type(last_step_output).__name__}"
        )

    writer.set_final_output(final_path)
    writer.set_status("completed")
    manifest_path = writer.write()
    print(f"\u2705 Pipeline complete. Manifest: {manifest_path}")


def copy_file(src: str, dst: str, expected_bucket_owner: Optional[str] = None) -> None:
    """Copy *src* to *dst*, supporting both local paths and S3 URIs.

    Behaviour:

    * Local-to-local: standard ``shutil.copy``; the destination directory
      is created if needed.
    * Local-to-S3: uploaded via boto3's ``upload_file``.
    * S3-to-local: downloaded via boto3's ``download_file``; the
      destination directory is created if needed.
    * S3-to-S3: server-side managed copy via boto3's ``copy`` (multipart
      for large objects), after a ``head_object`` that checks the source
      bucket's owner.

    *src* must exist (locally) or be reachable (S3). *dst* parent
    directories are created automatically for local destinations.
    """
    src_is_s3 = is_s3(src)
    dst_is_s3 = is_s3(dst)

    if not src_is_s3 and not dst_is_s3:
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy(src, dst)
        return

    s3 = _s3_client()
    owner = _bucket_owner(expected_bucket_owner)

    if not src_is_s3 and dst_is_s3:
        bucket, key = split_s3_uri(dst)
        s3.upload_file(src, bucket, key, ExtraArgs={"ExpectedBucketOwner": owner})
        return

    if src_is_s3 and not dst_is_s3:
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        bucket, key = split_s3_uri(src)
        s3.download_file(bucket, key, dst, ExtraArgs={"ExpectedBucketOwner": owner})
        return

    # S3-to-S3 (managed copy handles multipart for objects > 5 GB). The managed
    # copy does not accept a source-owner argument, so check the source bucket's
    # owner with head_object first.
    src_bucket, src_key = split_s3_uri(src)
    dst_bucket, dst_key = split_s3_uri(dst)
    s3.head_object(Bucket=src_bucket, Key=src_key, ExpectedBucketOwner=owner)
    s3.copy(
        {"Bucket": src_bucket, "Key": src_key},
        dst_bucket,
        dst_key,
        ExtraArgs={"ExpectedBucketOwner": owner},
    )


# ---------------------------------------------------------------------------
# Generic record-by-record JSONL runner
# ---------------------------------------------------------------------------


def run_record_transform(
    input_path: str,
    output_path: str,
    transform_fn: Callable[[dict], Optional[dict]],
    expected_bucket_owner: Optional[str] = None,
) -> dict:
    """Generic record-by-record JSONL runner.

    Reads *input_path* line-by-line, applies *transform_fn* to each parsed
    record, and writes results to *output_path*. *input_path* may be a
    local file path or an ``s3://`` URI; S3 inputs are streamed via boto3
    and are never downloaded to local disk. *output_path* must be a local
    path (intermediate step outputs always live under
    ``data/transformed/run_NNN/``).

    Behavior:

    * If a line is blank, it is skipped silently and not counted.
    * If a line fails JSON parsing, it is counted as ``malformed`` and
      not written.
    * If ``transform_fn(record)`` returns ``None``, the record is counted
      as ``filtered`` and not written.
    * If ``transform_fn(record)`` returns a ``dict``, it is serialized as
      JSON and appended to *output_path*.
    * Any other return type is treated as a transform error and counted
      as ``filtered``.

    The directory containing *output_path* is created when it does not
    yet exist.

    Parameters
    ----------
    input_path : str
        Path to a JSONL input file. Local path or ``s3://`` URI.
    output_path : str
        Local path to a JSONL output file. Created/overwritten on each
        call.
    transform_fn : callable
        Function ``record -> dict | None``. Called once per parsed
        record.
    expected_bucket_owner : str, optional
        For an ``s3://`` input, the account that must own the bucket.
        Default: the caller's own account.

    Returns
    -------
    dict
        ``{'total': N, 'kept': K, 'removed': N-K, 'malformed': M,
        'filtered': F}``, where ``total = kept + filtered + malformed``
        and ``removed = filtered + malformed``.
    """
    if is_s3(output_path):
        raise ValueError(
            "run_record_transform writes intermediate step outputs to local "
            f"disk; output_path={output_path!r} must be a local path. The "
            "final S3 upload is performed by finalize()."
        )

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    total = 0
    kept = 0
    malformed = 0
    filtered = 0

    def count_decode_error():
        nonlocal total, malformed
        total += 1
        malformed += 1

    with open(output_path, "w", encoding="utf-8") as fout:
        for line in iter_text_lines(
            input_path,
            on_decode_error=count_decode_error,
            expected_bucket_owner=expected_bucket_owner,
        ):
            stripped = line.strip()
            if not stripped:
                # Blank lines are not records.
                continue
            total += 1
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue

            result = transform_fn(record)

            if result is None:
                # Whether or not skip_none is True, we cannot write None
                # to the JSONL output. Count as filtered for accounting.
                filtered += 1
                continue
            if not isinstance(result, dict):
                # transform_fn returned something other than dict|None
                # (e.g. a list, a primitive). Treat as filtered to keep
                # the output JSONL strictly object-per-line.
                filtered += 1
                continue

            fout.write(json.dumps(result, ensure_ascii=False) + "\n")
            kept += 1

    return {
        "total": total,
        "kept": kept,
        "removed": total - kept,
        "malformed": malformed,
        "filtered": filtered,
    }


__all__ = [
    "is_s3",
    "split_s3_uri",
    "iter_text_lines",
    "input_exists",
    "copy_file",
    "stage_input",
    "init_manifest",
    "record_step",
    "finalize",
    "run_record_transform",
]
