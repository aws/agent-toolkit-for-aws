"""File-level (container) format detection: CSV / TSV / JSONL.

This module is the file-container counterpart to :mod:`detector`. The two
concerns are orthogonal:

    file_format   = "CSV"                    (how data is serialized on disk)
    record_format = "HF_Prompt_Completion"   (what the record schema means)

``detector`` classifies the *record schema* from a list of already-parsed
dicts. This module determines the *container format* of a file on disk, parses
its sample records, and pairs the two by delegating record classification back
to :func:`detector.detect_format`.

This module depends only on the standard library plus :mod:`detector`; it must
never be imported by :mod:`detector` (one-way dependency, no cycles).
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from typing import IO

from sagemaker_dataset_format_detector.detector import detect_format

logger = logging.getLogger(__name__)

# Unknown / unsupported container format. Mirrors detector.CUSTOM so the file
# and record "unknown" values stay in lockstep. NOT a member of FILE_FORMATS or
# TABULAR_FILE_FORMATS.
CUSTOM = "Custom"

# Sniffer configuration
_SNIFFER_SAMPLE_BYTES = 8192
_SNIFFER_DELIMITERS = ",\t|;"

# Delimiters auto-accepted from CONTENT sniffing. Comma and tab are the
# canonical CSV/TSV delimiters that map to our two named tabular formats. Other
# delimiters the Sniffer may report (e.g. ';', '|') are NOT accepted —
# structurally-tabular-but-non-CSV inputs (semicolon logs, markdown tables)
# sniff cleanly and would be misclassified; such files are classified Custom.
_TRUSTED_CONTENT_DELIMITERS = {",", "\t"}

# Bounds for the first-line JSON probe. The per-line byte cap prevents a
# newline-less pathological input (e.g. a huge single-line blob) from being
# read entirely into memory; the line-scan cap bounds work when a file begins
# with many blank lines.
_PROBE_MAX_LINE_BYTES = 1_048_576  # 1 MiB
_PROBE_MAX_LINES = 100

# Matches a "separator-only" cell (dashes/colons/pipes/whitespace), e.g. the
# ``|---|---|`` row of a markdown table.
_SEPARATOR_CELL = re.compile(r"^[\s:\-|]*$")

# Matches the *start* of a JSON object: an opening brace followed by optional
# whitespace and then either the closing brace (empty object) or the opening
# quote of a string key. Used only to recognize a legitimately large first
# record whose probe was truncated mid-object, where json.loads on the fragment
# cannot succeed. This is stricter than a bare leading ``{`` so a tabular row
# that merely starts with a brace (e.g. ``{foo,bar`` or ``{1;2;3``) is not
# mistaken for JSON: only a quoted key or an empty object can validly follow.
_JSON_OBJECT_PREFIX = re.compile(r'^\{\s*(?:"|\})')

# Sentinel distinguishing "first line was not valid JSON" from a valid JSON
# value that happens to be falsy (null, 0, false, "").
_NO_JSON = object()

# File-level format constants (aliases for clarity at call sites)
JSONL = "JSONL"
CSV = "CSV"
TSV = "TSV"

# All recognized file formats
FILE_FORMATS = {JSONL, CSV, TSV}

# Tabular file formats (CSV/TSV family)
TABULAR_FILE_FORMATS = {CSV, TSV}


@dataclass(frozen=True)
class FormatDetectionResult:
    """Result of combined file-level + record-level format detection.

    Attributes:
        file_format: Container format (JSONL, CSV, TSV).
        record_format: Record schema classification from the detector module
            (e.g. HF_Prompt_Completion, Custom). For CSV/TSV files, this is the
            classification of the parsed dicts (column names as keys).
        records: Parsed records (list of dicts) from the file.
    """

    file_format: str
    record_format: str
    records: list[dict]

    @property
    def is_tabular(self) -> bool:
        """True if the file is a tabular format (CSV or TSV)."""
        return self.file_format in TABULAR_FILE_FORMATS

    @property
    def effective_format(self) -> str:
        """The format to use for validation comparisons.

        For tabular files, returns the file_format (CSV/TSV) since the record
        schema is irrelevant (a CSV with prompt/completion columns is still
        CSV, not HF_Prompt_Completion). For an unknown container (Custom),
        returns Custom — the record classification is meaningless. For JSONL
        files, returns the record_format.
        """
        if self.file_format == CUSTOM:
            return CUSTOM
        if self.is_tabular:
            return self.file_format
        return self.record_format


def detect_file_format(path: str, n: int = 10) -> FormatDetectionResult:
    """Detect both file-level and record-level format from a dataset file.

    Args:
        path: Local file path to dataset.
        n: Maximum number of records to read for classification.

    Returns:
        FormatDetectionResult with file_format, record_format, and parsed
        records.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the file is empty or cannot be read as text (binary /
            non-UTF-8), or if a file confidently detected as JSONL contains a
            malformed / non-object line.
    """
    # utf-8-sig strips BOM from Windows/Excel-generated CSV files
    with open(path, "r", encoding="utf-8-sig") as f:
        return detect_stream_format(f, n=n, label=path)


def detect_stream_format(f: IO[str], n: int = 10, label: str = "<stream>") -> FormatDetectionResult:
    """Detect both file-level and record-level format from an open, seekable text stream.

    The stream form of ``detect_file_format``: a caller that already holds the
    bytes (a ranged read of an S3 object) wraps them in a text stream and never
    writes them to disk. ``label`` names the source in error messages.
    """
    try:
        # Read the first non-empty line (bounded) for the JSON probe. A
        # JSONL file may begin with blank/whitespace lines; probing only the
        # first physical line would miss the actual JSON content and fall
        # through to csv.Sniffer. The per-line byte cap and line-scan cap
        # keep a pathological input (e.g. a huge single-line blob, or a file
        # of endless blank lines) from being slurped into memory.
        first_line = ""
        first_line_truncated = False
        for _ in range(_PROBE_MAX_LINES):
            _line = f.readline(_PROBE_MAX_LINE_BYTES)
            if not _line:
                break
            if _line.strip():
                first_line = _line
                # readline(cap) returns at most `cap` characters. If it
                # returned exactly the cap and did NOT terminate at a
                # newline, the physical line was longer than the cap and
                # this probe holds only a truncated prefix of it.
                hit_cap = len(_line) >= _PROBE_MAX_LINE_BYTES
                first_line_truncated = hit_cap and not _line.endswith("\n")
                break
        f.seek(0)
        # Read a sample (up to 8KB) for Sniffer-based delimiter detection.
        # Sniffer needs multiple lines to reliably detect delimiters.
        sample_text = f.read(_SNIFFER_SAMPLE_BYTES)
        if not sample_text.strip():
            raise ValueError(f"File '{label}' contains no valid records.")

        file_format, delimiter, jsonl_confident = _detect_container_format(
            first_line, sample_text, first_line_truncated
        )

        # Unknown container: don't attempt to parse records or classify.
        if file_format == CUSTOM:
            return FormatDetectionResult(
                file_format=CUSTOM,
                record_format=CUSTOM,
                records=[],
            )

        f.seek(0)
        if file_format in TABULAR_FILE_FORMATS:
            if delimiter is None:
                raise ValueError(
                    f"Internal error: tabular format '{file_format}' " "detected without delimiter"
                )
            records = _read_csv_records(f, n, delimiter)
        else:
            # JSONL. When JSONL was chosen only as the fallback (the first
            # line was not a JSON object), a parse failure means the file
            # is not actually JSONL — classify it as Custom rather than
            # raising. When JSONL was *confidently* detected (first line was
            # a JSON object), a malformed line is a genuine error and
            # propagates.
            try:
                records = _read_jsonl_records(f, n)
            except ValueError:
                if jsonl_confident:
                    raise
                return FormatDetectionResult(
                    file_format=CUSTOM,
                    record_format=CUSTOM,
                    records=[],
                )
    except UnicodeDecodeError as e:
        raise ValueError(
            f"File '{label}' could not be read as UTF-8 text " "(unsupported or non-text file)."
        ) from e

    if not records:
        raise ValueError(f"File '{label}' contains no valid records.")

    record_format = detect_format(records, strict=False)

    return FormatDetectionResult(
        file_format=file_format,
        record_format=record_format,
        records=records,
    )


def _detect_container_format(
    first_line: str, sample_text: str, first_line_truncated: bool
) -> tuple[str, str | None, bool]:
    """Determine file container format from content analysis only.

    Detection order:
    1. JSON parse on the full first line: a JSON object -> JSONL (confident);
       a valid JSON value that is NOT an object (e.g. an array) -> Custom.
    1b. Only when the probe line was truncated at _PROBE_MAX_LINE_BYTES (so
       json.loads on the fragment cannot succeed): if the fragment matches a
       JSON-object *opening* (``{`` then a quoted key or ``}``), treat it as
       confident JSONL. This preserves the "confident JSONL raises on a
       malformed line" contract for a legitimately large first record instead
       of silently downgrading to Custom. A truncated non-object fragment skips
       content sniffing (the sample is a fragment of one giant line) and
       defaults to non-confident JSONL. When the line was NOT truncated, the
       full-line parse in step 1 is authoritative and no prefix heuristic runs.
    2. csv.Sniffer for delimiter detection, gated by _is_confident_tabular.
       Only comma/tab are accepted; any other delimiter is treated as unknown.
    3. Fallback -> JSONL (not confident); the caller treats a parse failure of
       a non-confident JSONL as Custom rather than an error.

    Detection is content-only: the file extension is intentionally NOT used, so
    a mislabeled file (e.g. a JSON blob named ``.csv``) is classified by what it
    actually contains rather than by its name.

    Args:
        first_line: The full (bounded) first non-empty line, for the JSON probe.
            A single JSONL record may exceed the Sniffer sample, so this must
            not be the byte-truncated sample.
        sample_text: Up to _SNIFFER_SAMPLE_BYTES of content, used by csv.Sniffer.
        first_line_truncated: True if ``first_line`` is only a prefix of the
            physical first line because it hit _PROBE_MAX_LINE_BYTES. When set,
            a failed full-line JSON parse is expected (the fragment is
            incomplete) and the JSON-object-opening prefix check decides JSONL.

    Returns:
        Tuple of (file_format, delimiter, jsonl_confident). delimiter is None
        for JSONL / Custom. jsonl_confident is True only when JSONL was chosen
        because the first line was (or began as) a JSON object.
    """
    stripped_first = first_line.strip()

    # 1. Content-first: try JSON parse on the full first line.
    try:
        parsed = json.loads(stripped_first)
    except (json.JSONDecodeError, ValueError):
        parsed = _NO_JSON
    if parsed is not _NO_JSON:
        if isinstance(parsed, dict):
            return JSONL, None, True
        # Valid JSON but not an object (e.g. array, scalar): JSON-ish but not a
        # supported record container -> unknown.
        return CUSTOM, None, False

    # 1b. Full-line parse failed. Only reinterpret this as JSONL when the probe
    # was truncated at the byte cap: an untruncated line that fails json.loads
    # is genuinely not JSON (step 1 is authoritative), so we must not guess from
    # a leading brace — a tabular row can legitimately start with ``{``.
    if first_line_truncated:
        # The fragment cannot be fully parsed. If it *opens* a JSON object (an
        # opening brace followed by a quoted key or an empty object), it is a
        # large first record: classify as confident JSONL so a malformed later
        # line raises per the documented contract. _read_jsonl_records re-reads
        # and validates the real first line from the start of the file.
        if _JSON_OBJECT_PREFIX.match(stripped_first):
            return JSONL, None, True
        # A truncated fragment that does not open an object is a pathological
        # non-JSON blob (e.g. one enormous newline-less line). The sample handed
        # to csv.Sniffer is itself a fragment of that single line, so a Sniffer
        # "delimiter" would be a false positive. Skip content sniffing and fall
        # through to the non-confident JSONL default, which the caller resolves
        # to Custom on parse failure.
        return JSONL, None, False

    # 2. Content-first: csv.Sniffer + confidence gate. Only comma/tab are
    # auto-accepted from content (see _TRUSTED_CONTENT_DELIMITERS).
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=_SNIFFER_DELIMITERS)
        delim = dialect.delimiter
        if delim in _TRUSTED_CONTENT_DELIMITERS and _is_confident_tabular(sample_text, delim):
            if delim == "\t":
                return TSV, "\t", False
            return CSV, ",", False
    except csv.Error:
        pass

    # 3. Cannot determine from content. Default to JSONL as a non-confident
    # fallback: if the content is genuinely JSONL it parses; if not, the caller
    # converts the parse failure into Custom.
    return JSONL, None, False


def _is_confident_tabular(sample_text: str, delimiter: str) -> bool:
    """True if ``sample_text`` looks like coherent tabular data for ``delimiter``.

    Guards against csv.Sniffer false positives: requires a consistent column
    count of at least 2 across non-blank rows, and rejects markdown-style
    separator rows (e.g. ``|---|---|``). Reuses the already-read sample — no
    extra file I/O.
    """
    lines = sample_text.splitlines()
    # The sample is capped at _SNIFFER_SAMPLE_BYTES, which can cut the final
    # line mid-row for files larger than the cap. A truncated last row has a
    # different column count and would fail the consistency check below, so
    # drop it when the sample hit the byte cap (keeping >=2 rows to check).
    if len(sample_text) >= _SNIFFER_SAMPLE_BYTES and len(lines) > 2:
        lines = lines[:-1]
    rows = [
        row for row in csv.reader(lines, delimiter=delimiter) if any(cell.strip() for cell in row)
    ]
    if len(rows) < 2:
        return False
    widths = {len(row) for row in rows}
    if len(widths) != 1 or next(iter(widths)) < 2:
        return False
    for row in rows:
        if all(_SEPARATOR_CELL.match(cell or "") for cell in row):
            return False
    return True


def _read_csv_records(stream: IO[str], n: int, delimiter: str) -> list[dict]:
    """Read up to n records from a CSV/TSV stream using DictReader."""
    reader = csv.DictReader(stream, delimiter=delimiter)
    records: list[dict] = []
    for row in reader:
        if len(records) >= n:
            break
        # Drop surplus fields from ragged rows (collected under restkey=None)
        row.pop(None, None)
        # Skip rows where all values are empty; guard non-str values
        if any(isinstance(v, str) and v.strip() for v in row.values()):
            records.append(dict(row))
    return records


def _read_jsonl_records(stream: IO[str], n: int) -> list[dict]:
    """Read up to n valid JSONL records from a text stream."""
    records: list[dict] = []
    for line_num, line in enumerate(stream, start=1):
        if len(records) >= n:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON at line {line_num}: {e}") from e
        if not isinstance(record, dict):
            raise ValueError(
                f"Line {line_num} is not a JSON object " f"(got {type(record).__name__})."
            )
        records.append(record)
    return records
