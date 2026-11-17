#!/usr/bin/env python3
"""Summarize SageMaker Dataset Quality Evaluation deduplication decisions and list the duplicate groups.

Works on the files a dataset quality evaluation job writes to its output folder:
``aggregate/quality_report.json`` (per-operator counts) and
``record_level/evaluated_data.jsonl`` (every input row plus ``dq_<operator>_<field>__<column>``
decision columns for ``exact_dedup`` and ``fuzzy_dedup``). The job never drops rows, and this script
writes no copy of the data.

The row-level file is the user's data and can be large: an ``s3://`` location of it is streamed
line by line and never written to disk. Each scored row is parsed, only the ``dq_`` decision columns
and the bound text column are read from it, and nothing is kept beyond the counts and the capped group
listings. Only the two small files, ``metadata.json`` and the
aggregate report, are saved locally. A group listing (``--groups``) first measures the row-level file
(``head_object``'s ``ContentLength``, or the local file's size) and, at 50 MB or over, prints the size
and the aggregate summary instead of streaming the whole file, the skill's rule for every row-level read
(``overview.md`` Step 8); ``--allow-large`` lists anyway. In a group listing, the text of a column that the job's
``pii_detection`` flagged on that row (``dq_pii_flagged__<column>`` true) prints as ``[REDACTED: PII]``,
the same guard as ``scripts/drill_down_rows.py``.

Imported by ``code_templates/deduplication.py`` and usable from the shell::

    # summarize a finished job (saves metadata.json and the aggregate report; streams the rows)
    python dedup_decisions.py --metadata <the job's MetadataS3Uri> --column prompt --json

    # list the ten largest near-duplicate clusters (an S3 URI or a local path)
    python dedup_decisions.py --record-level <the evaluated_data.jsonl S3 URI> --column prompt \
        --operator fuzzy --groups 10

Dependencies: Python 3.9+ standard library. An ``s3://`` location is read with ``boto3`` when it is
installed, else through the AWS CLI (``aws s3 cp <uri> -``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict
from typing import Any, Iterator, Mapping, Optional

OPERATORS = ("exact_dedup", "fuzzy_dedup")
MODE_TO_OPERATORS = {"exact": ("exact_dedup",), "fuzzy": ("fuzzy_dedup",), "both": OPERATORS}

AGGREGATE_FILE = "aggregate/quality_report.json"
RECORD_LEVEL_FILE = "record_level/evaluated_data.jsonl"
METADATA_FILE = "metadata.json"

DQ_PREFIX = "dq_"
INPUT_PREFIX = "dq_input__"
REDACTED = "[REDACTED: PII]"  # printed in place of a text column pii_detection flagged on the row
PII_PREFIX = "dq_pii_flagged__"  # the flag column pii_detection writes per text column (scripts/drill_down_rows.py)
MEMBERS_SHOWN = (
    20  # members listed per duplicate group; the rest is one "and K more" line (overview.md Step 8)
)
MB = 1024 * 1024
LARGE_FILE_BYTES = (
    50 * MB
)  # 52,428,800: a row-level file this size or over is never streamed whole (overview.md Step 8)


def sanitize_column(column: str) -> str:
    """The row-column suffix the job writes for a bound column: lowercased, each run of characters
    other than letters and digits (`str.isalnum`) replaced by one `_`, leading and trailing `_` dropped.
    """
    # The service's rule (metric_engine.py, `_sanitize_column`); the same body sits in drill_down_rows.py,
    # dedup_decisions.py and taxonomy_summary.py, which run standalone.
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in column)
    return "_".join(p for p in out.split("_") if p)


def column_token(bound: str) -> str:
    """``sanitize_column`` of the bound column; a ``dq_input__`` prefix stays."""
    head = INPUT_PREFIX if bound.startswith(INPUT_PREFIX) else ""
    return head + sanitize_column(bound[len(head) :])


AGGREGATE_COUNTS = (
    "input_count",
    "distinct_count",
    "duplicate_count",
    "duplicate_groups",
    "duplicate_rate",
)
AGGREGATE_PARAMS = ("normalize", "jaccard_threshold", "lowercase")
READ_TIMEOUT_SECONDS = 30  # S3 socket read timeout (botocore default 60): a stalled stream raises


def operators_for_mode(mode: str) -> tuple:
    """Map the template's DEDUP_MODE ('exact' | 'fuzzy' | 'both') to operator names."""
    try:
        return MODE_TO_OPERATORS[mode]
    except KeyError:
        raise ValueError(f"mode must be one of {sorted(MODE_TO_OPERATORS)}, got {mode!r}") from None


# --------------------------------------------------------------------------- locating outputs


def _split_s3(uri: str) -> tuple:
    rest = uri[len("s3://") :]
    bucket, _, key = rest.partition("/")
    if not bucket:
        raise ValueError(f"not an S3 URI: {uri!r}")
    return bucket, key


OUTPUT_FILES = (
    ("aggregate", "Aggregate", AGGREGATE_FILE),
    ("record_level", "RecordLevel", RECORD_LEVEL_FILE),
)


def report_uris(metadata: Mapping[str, Any]) -> dict:
    """The aggregate and record-level S3 URIs a job's ``metadata.json`` lists under ``Reports``."""
    reports = metadata.get("Reports") or {}
    return {
        name: next((uri for uri in reports.get(group) or [] if uri.endswith("/" + suffix)), None)
        for name, group, suffix in OUTPUT_FILES
    }


def _cli_lines(uri: str) -> Iterator[str]:
    """The lines of an S3 object through the AWS CLI (``aws s3 cp <uri> -``), when boto3 is absent.
    A read that stops early ends the copy; a read to the end checks the CLI's exit status. The CLI's
    stderr is drained on its own thread while stdout is read, so a copy that writes much to stderr
    (progress lines, a long error) cannot fill that pipe and block, which would hang the read."""
    import subprocess
    import threading

    try:
        process = subprocess.Popen(
            ["aws", "s3", "cp", uri, "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError:
        raise RuntimeError(f"neither boto3 nor the aws CLI is available to read {uri}") from None
    stderr: list = []
    drain = threading.Thread(target=lambda: stderr.append(process.stderr.read()), daemon=True)  # type: ignore[union-attr]
    drain.start()
    ended = False
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            yield raw.decode("utf-8").rstrip("\r\n")
        ended = True
    finally:
        if not ended:
            process.terminate()
        process.wait()
        drain.join()
        if ended and process.returncode:
            error = b"".join(stderr).decode(errors="replace").strip()
            raise RuntimeError(f"aws s3 cp {uri} failed: {error}")


def iter_lines(location: str) -> Iterator[str]:
    """Yield the lines of a local file or of an S3 object, without their line endings. An S3 object is
    streamed and never written to disk: with boto3 when it is installed, else through the AWS CLI.
    """
    if not location.startswith("s3://"):
        with open(location, encoding="utf-8") as handle:
            for line in handle:
                yield line.rstrip("\r\n")
        return
    try:
        import boto3  # only needed for S3 sources
    except ImportError:
        yield from _cli_lines(location)
        return
    from botocore.config import Config

    bucket, key = _split_s3(location)
    # A read timeout, so a stalled stream raises instead of hanging the read.
    client = boto3.client("s3", config=Config(read_timeout=READ_TIMEOUT_SECONDS))
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        for raw in body.iter_lines():
            yield raw.decode("utf-8")
    finally:
        body.close()


def _cli_head_object(bucket: str, key: str) -> int:
    """``ContentLength`` of an S3 object through the AWS CLI (``aws s3api head-object``), when boto3 is absent."""
    import subprocess

    try:
        done = subprocess.run(
            ["aws", "s3api", "head-object", "--bucket", bucket, "--key", key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"neither boto3 nor the aws CLI is available to measure s3://{bucket}/{key}"
        ) from None
    if done.returncode:
        error = done.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"aws s3api head-object s3://{bucket}/{key} failed: {error}")
    return int(json.loads(done.stdout.decode("utf-8"))["ContentLength"])


def row_level_size(location: str) -> int:
    """The size in bytes of the row-level file, read without streaming it: ``os.path.getsize`` for a
    local path; for an ``s3://`` object ``head_object``'s ``ContentLength``, with boto3 when it is
    installed, else through the AWS CLI (the same fallback ``iter_lines`` uses for the read itself).
    """
    if not location.startswith("s3://"):
        return os.path.getsize(location)
    bucket, key = _split_s3(location)
    try:
        import boto3  # only needed for S3 sources
    except ImportError:
        return _cli_head_object(bucket, key)
    from botocore.config import Config

    client = boto3.client("s3", config=Config(read_timeout=READ_TIMEOUT_SECONDS))
    return int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])


def _save(uri: str, local: str) -> str:
    """Save one small S3 object (``metadata.json``, the aggregate report) under ``local``."""
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as out:
        for line in iter_lines(uri):
            out.write(line + "\n")
    return local


def fetch_outputs(source: str, work_dir: str) -> dict:
    """Find a completed job's output files on S3, or in a local copy of its output folder.

    ``source`` is the S3 URI of the job's ``metadata.json`` (``JobConfigDocument.MetadataS3Uri``
    from DescribeJob), or a local directory holding a copy of the job's output folder. From S3,
    ``metadata.json`` and the aggregate report it lists under ``Reports`` are saved into
    ``work_dir`` (two small files); the record-level file is not downloaded, and its S3 URI is
    returned so every later read streams it (``iter_jsonl`` takes an S3 URI or a local path).
    Returns a dict with keys ``aggregate``, ``record_level``, ``metadata``. ``metadata`` may be
    ``None`` for a local copy; the other two are required and a missing one raises
    ``FileNotFoundError`` naming what was found, so callers never open ``None``.
    """
    found: dict = {}
    if source.startswith("s3://"):
        if not source.endswith("/" + METADATA_FILE):
            raise ValueError(f"{source} is not a metadata.json URI; pass the job's MetadataS3Uri")
        found["metadata"] = _save(source, os.path.join(work_dir, METADATA_FILE))
        with open(found["metadata"], encoding="utf-8") as handle:
            uris = report_uris(json.load(handle))
        found["aggregate"] = (
            _save(uris["aggregate"], os.path.join(work_dir, AGGREGATE_FILE))
            if uris["aggregate"]
            else None
        )
        found["record_level"] = uris["record_level"]  # streamed on every read, never downloaded
    else:
        local = os.path.join(source, METADATA_FILE)
        found["metadata"] = local if os.path.exists(local) else None
        for name, _, suffix in OUTPUT_FILES:
            local = os.path.join(source, suffix)
            found[name] = local if os.path.exists(local) else None
    missing = [name for name, _, _ in OUTPUT_FILES if not found.get(name)]
    if missing:
        present = [name for name, path in found.items() if path]
        raise FileNotFoundError(
            f"{source} is missing {missing}; expected {AGGREGATE_FILE} and {RECORD_LEVEL_FILE} "
            f"(found: {present or 'nothing'})"
        )
    return found


# --------------------------------------------------------------------------- row helpers


def iter_jsonl(path: str) -> Iterator[dict]:
    """Yield one dict per non-empty line of a local file or a streamed S3 object; a malformed line
    raises with its line number."""
    for number, line in enumerate(iter_lines(path), 1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: not valid JSON ({error.msg})") from error


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def decision_columns(
    operator: str, field: str, column: Optional[str], sample_row: Optional[dict] = None
) -> list:
    """Return the record-level column name(s) carrying ``field`` for ``operator``.

    With a bound ``column`` there is exactly one: ``dq_<operator>_<field>__<column>`` (empty when a
    ``sample_row`` is given and lacks it, so callers can fail loudly on a wrong column). Without one
    (recognized nested formats, where the operator ran on the derived prompt and completion) every
    ``dq_<operator>_<field>__*`` column present in ``sample_row`` is returned.
    """
    base = f"{DQ_PREFIX}{operator}_{field}__"
    if column:
        name = base + column_token(column)
        if sample_row is not None and name not in sample_row:
            return []
        return [name]
    if not sample_row:
        return []
    return sorted(key for key in sample_row if key.startswith(base))


def resolve_flag_columns(
    record_path: str, column: Optional[str], operators: tuple, missing_ok: bool = False
) -> dict:
    """Find each operator's ``flagged`` column(s) by scanning for the first row that carries them.

    Rows without decision columns (unannotated) may appear anywhere, including first, so the
    scan continues until every operator is resolved. Raises ``ValueError`` when no row in the
    file carries an operator's columns: when no operator appears at all, that almost always means
    a wrong ``column``; when only some appear, the others did not run (or ran on another column)
    and the message names the ones that did. With ``missing_ok`` an operator that did not run is
    simply left out of the result and the error is raised only when none of the requested
    operators appears at all.
    """
    found: dict = {operator: [] for operator in operators}
    seen: set = set()
    for row in iter_jsonl(record_path):
        for operator in operators:
            if not found[operator]:
                found[operator] = decision_columns(operator, "flagged", column, row)
        seen.update(key for key in row if key.startswith(DQ_PREFIX))
        if all(found.values()):
            break
    missing = [operator for operator, names in found.items() if not names]
    if missing and (not missing_ok or len(missing) == len(found)):
        present = [operator for operator in operators if found[operator]]
        if present:
            raise ValueError(
                f"{missing} left no decision columns for column={column!r} in any row of {record_path}; "
                f"the rows carry decisions from {present} only (the operator did not run in this job, or "
                f"ran on another column; dq_ columns seen: {sorted(seen)}). Choose only the operators "
                f"that ran; the CLI does so by default when --operator is omitted"
            )
        raise ValueError(
            f"no flagged columns for {missing} (column={column!r}) in any row of {record_path}, which "
            f"almost always means a wrong column; dq_ columns seen: {sorted(seen)}"
        )
    return {operator: names for operator, names in found.items() if names}


def _bound_suffix(flag_column: str, operator: str) -> str:
    return flag_column[len(f"{DQ_PREFIX}{operator}_flagged__") :]


def present_operators(record_path: str, column: Optional[str]) -> tuple:
    """The operators whose decision columns appear in at least one scored row, in catalog order.

    One pass over the rows (stopping early once every operator is seen). Raises ``ValueError``
    when no operator's columns appear at all, which almost always means a wrong ``column``.
    """
    found = {operator: False for operator in OPERATORS}
    seen: set = set()
    for row in iter_jsonl(record_path):
        for operator in OPERATORS:
            if not found[operator] and decision_columns(operator, "flagged", column, row):
                found[operator] = True
        seen.update(key for key in row if key.startswith(DQ_PREFIX))
        if all(found.values()):
            break
    present = tuple(operator for operator in OPERATORS if found[operator])
    if not present:
        raise ValueError(
            f"no dedup decision columns (column={column!r}) in any row of {record_path}; "
            f"dq_ columns seen: {sorted(seen)}"
        )
    return present


def bound_columns(record_path: str, operator: str, column: Optional[str]) -> list:
    """The column suffixes ``operator`` was bound to: ``[column]`` when one was bound, otherwise
    every normalized column found in the scored rows (``dq_input__prompt``, ``dq_input__completion``).
    """
    flags = resolve_flag_columns(record_path, column, (operator,))[operator]
    return [column] if column else [_bound_suffix(name, operator) for name in flags]


def _text_of(row: dict, suffix: str, limit: int) -> str:
    """The text the operator judged (the bound column, or the normalized dq_input__* column), cut to
    ``limit`` characters; or ``REDACTED`` when the job's ``pii_detection`` flagged that column on this
    row (the check ``scripts/drill_down_rows.py`` makes before it shows a row)."""
    if row.get(f"{PII_PREFIX}{column_token(suffix)}") is True:
        return REDACTED
    # A dq_input__ column is text the service derived from a source column (dq_input__prompt from
    # messages), so any flag on the row hides it.
    if suffix.startswith(INPUT_PREFIX) and any(
        k.startswith(PII_PREFIX) and v is True for k, v in row.items()
    ):
        return REDACTED
    value = row.get(suffix)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


# --------------------------------------------------------------------------- summarize


def _describe_view(view: Any) -> str:
    if isinstance(view, dict):
        return ", ".join(str(v) for v in view.values()) or "default binding"
    return "default binding"


def aggregate_operators(aggregate_path: str) -> tuple:
    """The dedup operators the aggregate report carries a run for, in catalog order; empty when it
    names none. Read from the small report, so it costs no pass over the rows."""
    aggregate = json.loads("\n".join(iter_lines(aggregate_path)))
    return tuple(operator for operator in OPERATORS if aggregate.get(operator))


def summarize(
    aggregate_path: str,
    record_path: Optional[str] = None,
    column: Optional[str] = None,
    operators: tuple = OPERATORS,
) -> dict:
    """Read the aggregate report (and optionally the scored rows) into a report dict.

    ``result['operators'][op]`` is a list of runs (one per bound column), each with the aggregate
    counts and echoed parameters; ``result['text']`` is a ready-to-print summary. When
    ``record_path`` is given, ``result['record_level_flagged'][op]`` counts flagged rows directly
    from the scored file as a consistency check; a requested operator that did not run is ``None``
    there, matching the "not present" line the aggregate branch prints for it.
    """
    aggregate = json.loads("\n".join(iter_lines(aggregate_path)))  # a local path or an S3 URI
    result: dict = {"operators": OrderedDict(), "text": ""}
    lines = []
    for operator in operators:
        runs = aggregate.get(operator) or []
        if not runs:
            result["operators"][operator] = []
            lines.append(f"{operator}: not present in the aggregate report")
            continue
        entries = []
        for run in runs:
            payload = run.get("result", {})
            entry = {key: payload.get(key) for key in AGGREGATE_COUNTS}
            entry["params"] = {key: payload[key] for key in AGGREGATE_PARAMS if key in payload}
            entry["view"] = run.get("view")
            entries.append(entry)
            rate = entry["duplicate_rate"]
            rate_text = f"{rate:.1%}" if isinstance(rate, (int, float)) else "rate n/a"
            lines.append(
                f"{operator} on {_describe_view(run.get('view'))}: "
                f"{entry['duplicate_count']} of {entry['input_count']} rows flagged ({rate_text}) "
                f"in {entry['duplicate_groups']} groups; {entry['distinct_count']} would remain"
            )
        result["operators"][operator] = entries
    if record_path:
        # Only the operators that ran carry decision columns; do not fail on the ones that did not.
        flag_columns = resolve_flag_columns(record_path, column, operators, missing_ok=True)
        counts: dict = {
            operator: (0 if operator in flag_columns else None) for operator in operators
        }
        for row in iter_jsonl(record_path):
            for operator, columns in flag_columns.items():
                if any(_is_true(row.get(name)) for name in columns):
                    counts[operator] += 1
        result["record_level_flagged"] = counts
    result["text"] = "\n".join(lines)
    return result


# --------------------------------------------------------------------------- groups


def discover_bound_columns(
    record_path: str, operators: tuple, column: Optional[str]
) -> "OrderedDict":
    """The column suffixes every operator was bound to, found in ONE pass over the rows.

    ``{operator: [column]}`` when one was bound, otherwise every normalized column found in the
    scored rows (``dq_input__prompt``, ``dq_input__completion``). Raises ``ValueError`` when no row
    carries an operator's columns (see ``resolve_flag_columns``).
    """
    flags = resolve_flag_columns(record_path, column, tuple(operators))
    return OrderedDict(
        (
            operator,
            [column] if column else [_bound_suffix(name, operator) for name in flags[operator]],
        )
        for operator in operators
    )


def _collect_groups(
    record_path: str, targets: "Mapping", limit: int, text_chars: int, members: int = MEMBERS_SHOWN
) -> "OrderedDict":
    """Two passes over the rows for every (operator, bound column) in ``targets``.

    Pass 1 keeps only flagged rows, grouped by representative; pass 2 fills in the representative
    texts for those groups only. Memory therefore grows with the duplicated rows, not the dataset,
    and a group keeps its first ``members`` members only (its ``members_total`` counts them all), so
    one group of a hundred thousand duplicates prints ``members`` lines, not a hundred thousand.
    The passes stay separate on purpose: the CLI measures the file first and streams it only under
    ``LARGE_FILE_BYTES``, where a second pass costs little, while a single pass would have to hold
    every unflagged row's text until its group is known. Returns ``{operator: {bound: [groups]}}`` with each list largest-first and cut to ``limit``.
    """
    plan: list = []
    for operator, suffixes in targets.items():
        for suffix in suffixes:
            columns = {
                field: f"{DQ_PREFIX}{operator}_{field}__{column_token(suffix)}"
                for field in ("row_id", "flagged", "reason", "representative_row_id")
            }
            plan.append((operator, suffix, columns, OrderedDict()))
    for row in iter_jsonl(record_path):  # pass 1: flagged rows only
        for operator, suffix, columns, groups in plan:
            if not _is_true(row.get(columns["flagged"])):
                continue  # unannotated, unique, or representative row: nothing to group yet
            rep_id = str(row.get(columns["representative_row_id"]))
            group = groups.setdefault(
                rep_id,
                {
                    "representative_row_id": rep_id,
                    "representative_text": None,
                    "members": [],
                    "members_total": 0,
                },
            )
            group["members_total"] += 1
            if len(group["members"]) < members:
                group["members"].append(
                    {
                        "row_id": str(row.get(columns["row_id"])),
                        "reason": row.get(columns["reason"]),
                        "text": _text_of(row, suffix, text_chars),
                    }
                )
    if any(groups for _, _, _, groups in plan):
        for row in iter_jsonl(record_path):  # pass 2: representative texts for those groups only
            for operator, suffix, columns, groups in plan:
                flagged = row.get(columns["flagged"])
                if flagged is None or _is_true(flagged) or not groups:
                    continue
                row_id = str(row.get(columns["row_id"]))
                if row_id in groups and row_id == str(row.get(columns["representative_row_id"])):
                    groups[row_id]["representative_text"] = _text_of(row, suffix, text_chars)
    result: OrderedDict = OrderedDict()
    for operator, suffix, _columns, groups in plan:
        ordered = sorted(groups.values(), key=lambda g: g["members_total"], reverse=True)
        result.setdefault(operator, OrderedDict())[suffix] = ordered[:limit]
    return result


def duplicate_groups_for(
    record_path: str,
    column: Optional[str],
    operators: tuple,
    limit: int = 20,
    text_chars: int = 120,
    members: int = MEMBERS_SHOWN,
) -> "OrderedDict":
    """Duplicate groups for every chosen operator on every bound column: ``{operator: {bound: [groups]}}``.

    Three passes over the rows in total (one to discover the bound columns, two to collect the
    groups), however many operators and bound columns there are. See ``duplicate_groups`` for the
    group shape.
    """
    return _collect_groups(
        record_path,
        discover_bound_columns(record_path, tuple(operators), column),
        limit,
        text_chars,
        members,
    )


def duplicate_groups(
    record_path: str,
    column: Optional[str],
    operator: str,
    limit: int = 20,
    text_chars: int = 120,
    suffix: Optional[str] = None,
    members: int = MEMBERS_SHOWN,
) -> list:
    """Reconstruct duplicate groups for one operator on one bound column, largest first.

    Each group is ``{'representative_row_id', 'representative_text', 'members': [...],
    'members_total'}`` where a member is ``{'row_id', 'reason', 'text'}``; ``members`` holds the
    first ``members`` flagged rows of the group and ``members_total`` counts them all. Only groups
    with at least one flagged member are returned, at most ``limit`` of them. For nested formats (``column`` is None) the operator ran
    once per normalized column; pass ``suffix`` (``dq_input__prompt`` or ``dq_input__completion``)
    to choose one. When several are present and none is chosen, a ``ValueError`` lists them. To
    list several operators or bound columns, use ``duplicate_groups_for`` (fewer passes).
    """
    suffixes = bound_columns(record_path, operator, column)
    if suffix is None:
        if len(suffixes) > 1:
            raise ValueError(
                f"{operator} ran on several columns {suffixes}; pass suffix= to pick one"
            )
        suffix = suffixes[0]
    elif suffix not in suffixes:
        raise ValueError(f"{operator} has no decisions for {suffix!r}; bound columns: {suffixes}")
    return _collect_groups(record_path, {operator: [suffix]}, limit, text_chars, members)[operator][
        suffix
    ]


# --------------------------------------------------------------------------- CLI


def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_argument_group("inputs")
    source.add_argument(
        "--metadata",
        metavar="URI_OR_DIR",
        help="the job's metadata.json S3 URI (DescribeJob JobConfigDocument.MetadataS3Uri), "
        "or a local copy of the job's output folder",
    )
    source.add_argument(
        "--work-dir",
        default="dq_outputs",
        help="where --metadata saves metadata.json and the aggregate report (the row-level "
        "file is streamed from S3, never saved)",
    )
    source.add_argument(
        "--aggregate", help="aggregate/quality_report.json, a local path or an S3 URI"
    )
    source.add_argument(
        "--record-level",
        help="record_level/evaluated_data.jsonl, a local path or an S3 URI " "(streamed)",
    )
    parser.add_argument(
        "--column",
        help="bound text column, as named in the dataset; omit when the "
        "operators ran without a View",
    )
    parser.add_argument(
        "--operator",
        choices=sorted(MODE_TO_OPERATORS),
        default=None,
        help="exact, fuzzy, or both; default: the operators present in the scored rows "
        "(both for a summary without scored rows). An explicit choice must have run: "
        "--groups refuses an operator without decision columns",
    )
    parser.add_argument(
        "--groups",
        type=int,
        default=0,
        metavar="N",
        help="print the N largest duplicate groups of each chosen operator",
    )
    parser.add_argument(
        "--members",
        type=int,
        default=MEMBERS_SHOWN,
        metavar="N",
        help=f"print at most N members per group, then one 'and K more' line "
        f"(default {MEMBERS_SHOWN})",
    )
    parser.add_argument(
        "--bound",
        metavar="SUFFIX",
        help="without a View: which derived column's groups to list "
        "(dq_input__prompt or dq_input__completion)",
    )
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help="list the groups even when the row-level file is 50 MB or over; by default "
        "such a file is not streamed and the aggregate summary is printed instead",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)
    if args.metadata:
        paths = fetch_outputs(args.metadata, args.work_dir)
        args.aggregate = args.aggregate or paths["aggregate"]
        args.record_level = args.record_level or paths["record_level"]
    if not (args.aggregate or args.record_level):
        parser.error("give --metadata, or --aggregate and/or --record-level")
    if args.groups and not args.record_level:
        parser.error("--groups needs --record-level (or --metadata)")
    return args


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    if args.groups and not args.allow_large:
        # The size gate (overview.md Step 8): a row-level file of 50 MB or over is never streamed whole,
        # so it is measured before any pass over its rows, including the operator discovery below.
        size = row_level_size(args.record_level)
        if size >= LARGE_FILE_BYTES:
            print(
                f"The row-level file is {size / MB:.1f} MB, 50 MB or over; the skill does not stream a file "
                f"of that size whole, so the duplicate groups are not listed (--allow-large lists them anyway)"
            )
            if args.aggregate:
                operators = operators_for_mode(args.operator) if args.operator else OPERATORS
                summary = summarize(args.aggregate, None, args.column, operators)
                print(
                    json.dumps({"summary": summary}, indent=2, default=str)
                    if args.json
                    else summary["text"]
                )
            return 0
    if args.operator:
        operators = operators_for_mode(args.operator)
    elif args.record_level:  # default to what actually ran, so a single-operator job needs no flag
        # The small aggregate report names the operators that ran; only without one are the rows scanned.
        operators = aggregate_operators(args.aggregate) if args.aggregate else ()
        operators = operators or present_operators(args.record_level, args.column)
    else:
        operators = (
            OPERATORS  # summary only: summarize() tolerates an operator absent from the report
        )
    report: dict = {}
    if args.aggregate:
        report["summary"] = summarize(args.aggregate, args.record_level, args.column, operators)
    if args.groups:
        if args.bound:
            report["groups"] = {
                operator: duplicate_groups(
                    args.record_level,
                    args.column,
                    operator,
                    limit=args.groups,
                    suffix=args.bound,
                    members=args.members,
                )
                for operator in operators
            }
        else:  # every operator in three passes; a nested format with two bound columns needs --bound
            report["groups"] = {}
            for operator, per_bound in duplicate_groups_for(
                args.record_level, args.column, operators, limit=args.groups, members=args.members
            ).items():
                if len(per_bound) > 1:
                    raise ValueError(
                        f"{operator} ran on several columns {list(per_bound)}; pass --bound to pick one"
                    )
                report["groups"][operator] = next(iter(per_bound.values()))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    if "summary" in report:
        print(report["summary"]["text"])
    for operator, groups in report.get("groups", {}).items():
        print(f"\n{operator}: {len(groups)} group(s) shown, largest first")
        for group in groups:
            print(f"  [{group['members_total']} duplicate(s)] {group['representative_text']}")
            for member in group["members"]:
                print(f"      row {member['row_id']} ({member['reason']}): {member['text']}")
            if group["members_total"] > len(group["members"]):
                print(f"      and {group['members_total'] - len(group['members'])} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
