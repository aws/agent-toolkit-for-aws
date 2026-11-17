"""
Dataset format check for the dataset-quality capability.

The detection code is the ``sagemaker_dataset_format_detector`` package
beside this script; this script does not classify records itself. Formats,
the hub's DatasetFileFormat values:
    Nova_CPT, Bedrock_Converse, Nova_PPO,
    HF_Prompt_Completion, HF_Preference, Verl,
    OpenAI_Messages, SageMaker_Eval, Nova_RLVR
Datasets that match none of them are classified as "Custom".

This script adds the loaders and the command line:

- ``.jsonl`` (and a path with no known extension): a 1 MiB local or S3
  ranged read, every line parsed, ``detect_format`` on the records.
- ``.csv``: ``detect_file_format(path, n=5)``, which reads the header and
  5 rows; an S3 object is fetched with the same 1 MiB ranged read and read
  from memory through ``detect_stream_format``, never written to disk. Blank
  cells and the tokens pandas reads as missing values become
  None before the format rules run, as the quality job's CSV reader sees
  them. When the content reads as another container (TSV, JSON Lines), the
  result is Custom with a note naming that container.
- ``.parquet``: nothing is read. The result is Custom, and the columns are
  bound explicitly from the names the user gives; the quality job reads
  the file.

The quality job reads ``.jsonl``, ``.csv`` and ``.parquet``. Other
extensions (``.tsv``, ``.pq``, plain ``.json`` and the rest of the stop
list) are stopped before any read with a message naming what the check
reads.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys

# The detector package sits beside this script; put this folder on the path so
# the import works when the script is imported as well as when it is run.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from sagemaker_dataset_format_detector.detector import (  # noqa: E402
    BEDROCK_CONVERSE,
    CUSTOM,
    HF_PREFERENCE,
    HF_PROMPT_COMPLETION,
    NOVA_CPT,
    NOVA_PPO,
    NOVA_RLVR,
    OPENAI_MESSAGES,
    SAGEMAKER_EVAL,
    SUPPORTED_FORMATS,
    VERL,
    detect_format,
)
from sagemaker_dataset_format_detector.file_format import CSV as CSV_CONTAINER  # noqa: E402
from sagemaker_dataset_format_detector.file_format import (
    detect_file_format,
    detect_stream_format,
)

logger = logging.getLogger(__name__)

# S3 read errors (a missing object, denied access, no credentials) end in the same one-line
# "Error: ..." as a local read error. botocore comes with boto3; without it no S3 read happens.
try:
    from botocore.exceptions import BotoCoreError, ClientError

    _S3_ERRORS: tuple = (BotoCoreError, ClientError)
except ImportError:  # pragma: no cover - boto3 is not installed
    _S3_ERRORS = ()

# File extensions the detector does not read; stopped at load time with a
# message naming what it reads.
_UNSUPPORTED_EXTENSIONS = {
    ".tsv",
    ".psv",
    ".json",  # single JSON object/array — not JSONL
    ".pq",  # the job reads .parquet only
    ".xlsx",
    ".xls",
    ".txt",
    ".yaml",
    ".yml",
    ".arrow",
    ".feather",
    ".avro",
    ".orc",
    ".ndjson",  # very close to jsonl but reject by convention
}

_CSV_EXTENSIONS = {".csv"}
_PARQUET_EXTENSIONS = {".parquet"}

# Rows the service's detector call sees.
_SERVICE_SAMPLE_ROWS = 5

# The cell values pandas reads as missing (its default na_values), which the
# service's CSV loader turns into NaN. csv.DictReader keeps them as strings, so
# a prompt,completion file with one blank completion reads as a known format
# here and as Custom in the job. They become None before the format rules run.
_PANDAS_NA_TOKENS = frozenset(
    {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
)

# For each known format a flat file can take, the columns the detector's
# check requires to hold text (detector.py: _check_nova_cpt,
# _check_hf_preference, _check_sagemaker_eval, _check_hf_prompt_completion,
# _check_verl). The service's CSV loader (pandas) reads a column of numbers as
# numbers, which fails that check, so the service says Custom where the
# sampled text says a known format.
_TEXT_COLUMNS = {
    NOVA_CPT: ("text",),
    HF_PREFERENCE: ("chosen", "rejected"),
    SAGEMAKER_EVAL: ("query", "response"),
    HF_PROMPT_COMPLETION: ("prompt", "completion"),
    VERL: ("prompt",),
}

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_BOOLEANS = frozenset({"true", "false"})  # pandas reads a column of these as booleans, not text

# A CSV cell longer than the csv module's default limit (128 KB) is data, not an error.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _extension(file_path: str) -> str:
    _, ext = os.path.splitext(file_path.split("?", 1)[0].lower())
    return ext


def _s3_parts(file_path: str) -> tuple[str, str]:
    parts = file_path[5:].split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid S3 URI: {file_path}")
    return parts[0], parts[1]


def _numeric_only_columns(format_name: str, records: list[dict]) -> list[str]:
    """The format's text columns whose sampled values are all numbers or blanks, or all booleans
    (True/False, any case) or blanks: pandas reads either column as non-text."""
    columns = []
    for column in _TEXT_COLUMNS.get(format_name, ()):
        values = [record.get(column) for record in records]
        if not values or not all(isinstance(v, str) for v in values):
            continue
        cells = [v.strip() for v in values if v.strip()]  # type: ignore[union-attr]
        if all(_NUMBER.match(c) for c in cells) or all(c.lower() in _BOOLEANS for c in cells):
            columns.append(column)
    return columns


def _service_note(columns: list[str]) -> str:
    if len(columns) == 1:
        subject = f"column {columns[0]} holds"
    else:
        subject = f"columns {' and '.join(columns)} hold"
    return (
        f"the service may name this file Custom because {subject} only "
        f"numbers or booleans; bind the columns explicitly"
    )


def _normalize_csv_cells(records: list[dict]) -> list[dict]:
    """Return the records with blank cells and pandas missing-value tokens as None.

    ``detect_file_format`` reads a CSV with ``csv.DictReader``, which keeps every
    cell a string. The quality job's CSV loader (pandas) reads a blank cell or one
    of its default missing-value tokens as NaN, and the format rules then see no
    text in that cell. Normalizing first makes the two reads agree: a known
    format needs text in every sampled row of its text columns. A token is
    matched on the cell as written, as pandas matches ``na_values``: a cell with
    spaces around a token, or of spaces alone, stays a string in both reads.
    """
    normalized = []
    for record in records:
        normalized.append(
            {
                key: (None if isinstance(value, str) and value in _PANDAS_NA_TOKENS else value)
                for key, value in record.items()
            }
        )
    return normalized


def _classify_csv(file_path: str, sample_size_bytes: int = 1_048_576) -> dict:
    """Classify a ``.csv`` with ``detect_file_format(path, n=5)``; an S3 sample is read from memory."""
    if file_path.startswith("s3://"):
        import boto3

        bucket, key = _s3_parts(file_path)
        client = boto3.client("s3")
        response = client.get_object(
            Bucket=bucket, Key=key, Range=f"bytes=0-{sample_size_bytes - 1}"
        )
        try:
            data = response["Body"].read()
        finally:
            response["Body"].close()
        # A read cut at the cap may end inside a row; drop that partial row.
        if len(data) >= sample_size_bytes:
            last_newline = data.rfind(b"\n")
            if last_newline == -1:
                # No row ends inside the sample, so not even the header was read whole:
                # say so, as the JSON Lines path does, never classify an unread row.
                raise ValueError(
                    f"the first row of '{file_path}' is longer than the {sample_size_bytes}-byte "
                    f"sample, so its format could not be read; run the check again with "
                    f"--sample-size larger than that row"
                )
            data = data[: last_newline + 1]
        # The bytes are the user's data: they stay in memory and are never written to disk, so
        # a process killed mid-read leaves nothing behind. utf-8-sig strips a BOM, as the file read does.
        with io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig") as sample:
            result = detect_stream_format(sample, n=_SERVICE_SAMPLE_ROWS, label=file_path)
    else:
        result = detect_file_format(file_path, n=_SERVICE_SAMPLE_ROWS)

    if result.file_format != CSV_CONTAINER:
        # The detector reads the container from the bytes, never the extension: a .csv holding
        # tab-separated or JSON Lines content is not what the job's CSV loader reads as columns.
        return {
            "format": CUSTOM,
            "file_type": "csv",
            "content_format": result.file_format,
            "columns": [],
            "rows_sampled": 0,
            "note": (
                f"the file is named .csv but its content reads as {result.file_format}, not "
                f"comma-separated values; the quality job reads a .csv as comma-separated, so "
                f"rename the file to match its content or bind the columns explicitly. A valid "
                f"CSV reads this way too when it has one column, or a quoted cell longer than the "
                f"8 KB sample the delimiter sniff reads: bind the column explicitly"
            ),
        }

    records = result.records
    columns = list(records[0].keys()) if records else []
    # The format rules run on the cells as the job's reader sees them (blanks and
    # missing-value tokens as None), never on the raw strings DictReader returns.
    record_format = detect_format(_normalize_csv_cells(records), strict=False)
    output = {
        "format": record_format,
        "file_type": "csv",
        "columns": columns,
        "rows_sampled": len(records),
    }
    numeric = _numeric_only_columns(record_format, records)
    if numeric:
        output["service_note"] = _service_note(numeric)
    return output


PARQUET_NOTE = (
    "The format check does not read Parquet files; the quality job reads them. "
    "Bind the columns explicitly from the names the user gives, so no known "
    "format's defaults apply."
)


def _classify_parquet(file_path: str) -> dict:
    """Return Custom for a ``.parquet`` path without opening it."""
    return {
        "format": CUSTOM,
        "file_type": "parquet",
        "columns": [],
        "rows_sampled": 0,
        "sampled": False,
        "note": PARQUET_NOTE,
    }


# ---------------------------------------------------------------------------
# CLI wrapper — file loading for local and S3 paths
# ---------------------------------------------------------------------------


def _load_records_from_file(
    file_path: str, sample_size_bytes: int = 1_048_576
) -> tuple[list[dict], int, list[str]]:
    """Load and parse JSONL records from a local file or S3 URI.

    Args:
        file_path: Local path or S3 URI (s3://bucket/key).
        sample_size_bytes: Max bytes to read (default 1MB).

    Returns:
        Tuple of (records, lines_sampled, parse_errors).

    Raises:
        ValueError: If ``file_path`` has a known non-JSONL extension.
    """
    # Stop on an extension the detector does not read (.tsv, .json, ...)
    # upfront. Without this check TSV data would parse as JSONDecodeErrors
    # on every line, return zero records, and surface as the confusing "Empty
    # dataset" message in detect_format. The message names what the check
    # reads and where the capability states the boundary.
    ext = _extension(file_path)
    if ext in _UNSUPPORTED_EXTENSIONS:
        reason = ""
        if ext in (".tsv", ".pq"):
            reason = " A .pq file renamed to .parquet is read; a .tsv file is not."
        raise ValueError(
            f"The format check reads JSON Lines (.jsonl), CSV (.csv) and "
            f"Parquet (.parquet), the formats the quality job reads; it "
            f"does not read '{ext}' files.{reason} A quality evaluation of "
            f"this file has no validated workflow in this capability "
            f"(overview.md, Out of Scope)."
        )

    if file_path.startswith("s3://"):
        import boto3

        bucket, key = _s3_parts(file_path)
        client = boto3.client("s3")
        response = client.get_object(
            Bucket=bucket, Key=key, Range=f"bytes=0-{sample_size_bytes - 1}"
        )
        try:
            data = response["Body"].read()
        finally:
            response["Body"].close()
    else:
        with open(file_path, "rb") as f:
            data = f.read(sample_size_bytes)

    if not data:
        return [], 0, []

    # When the buffer was cut at the sample size, trim to the last newline BYTE
    # before decoding: a fixed byte-range read from S3 (or f.read) can cut
    # through the middle of a multibyte UTF-8 character or a record, which would
    # make data.decode("utf-8") raise UnicodeDecodeError or drop a partial line
    # into parse_errors. 0x0A never appears as a UTF-8 continuation byte, so
    # truncating there guarantees a decodable buffer. A buffer shorter than the
    # sample size was read whole, so its last line is complete and is kept
    # whether or not the file ends with a newline.
    if len(data) >= sample_size_bytes:
        last_newline = data.rfind(b"\n")
        if last_newline == -1:
            # No line ends inside the sample, so not even the first record was read: say so,
            # never classify an unread record as Custom.
            raise ValueError(
                f"the first record of '{file_path}' is longer than the {sample_size_bytes}-byte "
                f"sample, so its format could not be read; run the check again with "
                f"--sample-size larger than that record"
            )
        data = data[: last_newline + 1]

    text = data.decode("utf-8")
    lines = [line for line in text.split("\n") if line]

    records = []
    parse_errors = []
    for i, line in enumerate(lines, start=1):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            parse_errors.append(f"Line {i}: {e}")

    # Guard against files with unknown/no extension (e.g. an S3 key without
    # a suffix) that turn out not to be JSONL at all. If every line sampled
    # failed to parse as JSON, raise with the same guidance as the extension
    # check so callers see "not JSONL" rather than "Empty dataset".
    if lines and not records:
        raise ValueError(
            f"'{file_path}' does not appear to be JSONL — all {len(lines)} "
            f"sampled line(s) failed JSON parsing. Dataset quality evaluation expects JSONL "
            f"(newline-delimited JSON, one record per line). "
            f"First parse error: {parse_errors[0]}"
        )

    return records, len(lines), parse_errors


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Detect a JSONL, CSV or Parquet dataset's format (9 supported formats + Custom)"
    )
    parser.add_argument("file_path", help="S3 URI (s3://bucket/key) or local file path")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=1_048_576,
        help="Bytes to sample from a JSONL or CSV file (default: 1MB)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict mode (reject extra keys); applies to JSON Lines only, a CSV is always read relaxed",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        ext = _extension(args.file_path)
        if ext in _CSV_EXTENSIONS or ext in _PARQUET_EXTENSIONS:
            if ext in _CSV_EXTENSIONS:
                output = _classify_csv(args.file_path, args.sample_size)
            else:
                output = _classify_parquet(args.file_path)
            supported = output["format"] != CUSTOM
            output["supported"] = supported
            output["mode"] = "relaxed"
            output["supported_formats"] = SUPPORTED_FORMATS
            if args.json:
                print(json.dumps(output, indent=2))
            else:
                print(f"Format: {output['format']}")
                print(f"Supported: {'yes' if supported else 'no'}")
                print(f"File type: {output['file_type']}")
                print(f"Rows sampled: {output['rows_sampled']}")
                print(f"Columns: {', '.join(output['columns'])}")
                if output.get("note"):
                    print(f"Note: {output['note']}")
                if output.get("service_note"):
                    print(f"Service note: {output['service_note']}")
            sys.exit(0 if supported else 1)

        records, lines_sampled, parse_errors = _load_records_from_file(
            args.file_path, args.sample_size
        )
        format_name = detect_format(records, strict=args.strict)

        supported = format_name != CUSTOM
        # Nova_RLVR is supported for spec-driven and exploratory evaluation;
        # its nested core columns bind to no built-in metric. The caveat's
        # home is references/supported-formats.md.
        note = None
        if format_name == NOVA_RLVR:
            note = (
                "Nova_RLVR: spec-driven and exploratory evaluation apply; "
                "built-in metrics bind only additional flat columns, never "
                "messages or reference_answer. See references/supported-formats.md."
            )

        if args.json:
            output = {
                "format": format_name,
                "supported": supported,
                "lines_sampled": lines_sampled,
                "records_parsed": len(records),
                "mode": "strict" if args.strict else "relaxed",
                "supported_formats": SUPPORTED_FORMATS,
            }
            if note:
                output["note"] = note
            if parse_errors:
                output["parse_errors"] = parse_errors
            print(json.dumps(output, indent=2))
        else:
            print(f"Format: {format_name}")
            print(f"Supported: {'✓' if supported else '✗'}")
            print(f"Mode: {'strict' if args.strict else 'relaxed'}")
            print(f"Lines sampled: {lines_sampled}")
            print(f"Records parsed: {len(records)}")
            if note:
                print(f"Note: {note}")
            if parse_errors:
                print(f"Parse errors: {len(parse_errors)}")
                for err in parse_errors:
                    print(f"  {err}")
            if format_name == CUSTOM:
                print(f"\nSupported formats: {', '.join(SUPPORTED_FORMATS)}")
                if records and isinstance(records[0], dict):
                    first_keys = sorted(records[0].keys())
                    print(f"Your dataset keys: {first_keys}")

        sys.exit(0 if supported else 1)
    except (FileNotFoundError, IOError, ValueError, csv.Error, *_S3_ERRORS) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
