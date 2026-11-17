#!/usr/bin/env python3
"""Summarize a SageMaker Dataset Quality Evaluation ``taxonomy`` run.

Works on the files a dataset quality evaluation job writes to its output folder:
``aggregate/quality_report.json`` (per-framing counts, run id, HTML report path) and
``record_level/evaluated_data.jsonl`` (every input row plus
``dq_taxonomy_<framing>_{l1,l2,l3,margin}__<column>`` columns). Builds the category tree with row
counts, and lists rows by category or by low confidence.

An ``s3://`` location is streamed from S3 line by line and never written to disk: the row-level
file is the user's data and can be gigabytes. Each scored row is parsed, only the named taxonomy
columns and the bound text column are read from it, and nothing is kept beyond the counts and the
capped row listings.

Imported by ``code_templates/taxonomy.py`` and usable from the shell::

    # tree with counts for every framing that ran (streams metadata.json and the two reports it lists)
    python taxonomy_summary.py --metadata <the job's MetadataS3Uri> --column prompt

    # rows assigned to one leaf, and the 20 least confident rows
    python taxonomy_summary.py --record-level <the evaluated_data.jsonl S3 URI> --column prompt \
        --framing task --category l3="Unit conversion" --low-confidence 20

Dependencies: Python 3.9+ standard library. An ``s3://`` location is read with ``boto3`` when it is
installed, else through the AWS CLI (``aws s3 cp <uri> -``).
"""

from __future__ import annotations

import argparse
import heapq
import json
import os
import sys
from collections import OrderedDict
from typing import Any, Iterable, Iterator, Mapping, Optional

FRAMINGS = ("task", "domain", "quality")
LEVELS = ("l1", "l2", "l3")
LOW_CONFIDENCE_MARGIN = 0.1  # the margin below which a row counts as low-confidence (references/result-interpretation.md)
READ_TIMEOUT_SECONDS = 30  # S3 socket read timeout (botocore default 60): a stalled stream raises

AGGREGATE_FILE = "aggregate/quality_report.json"
RECORD_LEVEL_FILE = "record_level/evaluated_data.jsonl"
METADATA_FILE = "metadata.json"

DQ_PREFIX = "dq_"
INPUT_PREFIX = "dq_input__"
REDACTED = "[REDACTED: PII]"  # printed in place of a text column pii_detection flagged on the row
PII_PREFIX = "dq_pii_flagged__"  # the flag column pii_detection writes per text column (scripts/drill_down_rows.py)


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


RUN_FIELDS = (
    "input_count",
    "output_count",
    "excluded_count",
    "count_anomaly",
    "taxonomy_run_id",
    "taxonomy_report_path",
)
FRAMING_FIELDS = ("l1_count", "l2_count", "l3_count", "classified_count", "low_confidence_count")


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
    """Yield the lines of a local file or of an S3 object. An S3 object is streamed and never written
    to disk: with boto3 when it is installed, else through the AWS CLI (as dedup_decisions.py reads).
    """
    if not location.startswith("s3://"):
        with open(location, encoding="utf-8") as handle:
            yield from handle
        return
    try:
        import boto3  # only needed for S3 sources
    except ImportError:
        yield from _cli_lines(location)
        return
    from botocore.config import Config

    bucket, key = _split_s3(location)
    # A read timeout, so a stalled stream raises sooner than botocore's 60 seconds.
    client = boto3.client("s3", config=Config(read_timeout=READ_TIMEOUT_SECONDS))
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        for raw in body.iter_lines():
            yield raw.decode("utf-8")
    finally:
        body.close()


def load_json(location: str) -> Any:
    """Parse one small JSON file (``metadata.json`` or the aggregate report), local or on S3."""
    return json.loads("\n".join(iter_lines(location)))


def fetch_outputs(source: str) -> dict:
    """Find a completed job's output files on S3, or in a local copy of its output folder.

    ``source`` is the S3 URI of the job's ``metadata.json`` (``JobConfigDocument.MetadataS3Uri``
    from DescribeJob), or a local directory holding a copy of the job's output folder. From S3,
    ``metadata.json`` is read and the S3 URIs of the aggregate and record-level files it lists under
    ``Reports`` are returned; nothing is downloaded, and every later read streams the object. Returns
    a dict with keys ``aggregate``, ``record_level``, ``metadata``, each an S3 URI or a local path,
    which every reader of this module accepts. ``metadata`` may be ``None`` for a local copy; the
    other two are required and a missing one raises ``FileNotFoundError`` naming what was found, so
    callers never open ``None``.
    """
    found: dict = {}
    if source.startswith("s3://"):
        if not source.endswith("/" + METADATA_FILE):
            raise ValueError(f"{source} is not a metadata.json URI; pass the job's MetadataS3Uri")
        found["metadata"] = source
        uris = report_uris(load_json(source))
        for name, _, _ in OUTPUT_FILES:
            found[name] = uris[name]
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


def bound_suffixes(framing: str, column: Optional[str], sample_row: Optional[dict]) -> list:
    """Column suffixes the framing was bound to: the bound column, or every ``dq_input__*`` seen."""
    if column:
        return [column]
    base = f"{DQ_PREFIX}taxonomy_{framing}_l1__"
    if not sample_row:
        return []
    return sorted(key[len(base) :] for key in sample_row if key.startswith(base))


def taxonomy_columns(framing: str, suffix: str) -> dict:
    """Map ``l1``/``l2``/``l3``/``margin`` to their record-level column names."""
    token = column_token(suffix)
    return {
        field: f"{DQ_PREFIX}taxonomy_{framing}_{field}__{token}" for field in LEVELS + ("margin",)
    }


def discover_columns(
    record_path: str, framings: Iterable[str], column: Optional[str], require_all: bool = True
) -> "OrderedDict":
    """The column suffixes every requested framing was bound to, found in ONE pass over the rows.

    Per framing: ``[column]`` when one was bound (verified to appear in at least one row); otherwise
    every normalized column found across the scored rows (``dq_input__prompt``,
    ``dq_input__completion``). Rows without taxonomy columns (unclassified) may appear anywhere,
    including first. Raises ``ValueError`` naming every framing no row carries, which almost always
    means a wrong ``column`` or a framing that did not run; with ``require_all=False`` such framings
    are simply left out of the result instead (the default scan over all framings).
    """
    wanted = list(framings)
    found: dict = {framing: set() for framing in wanted}
    seen: set = set()
    for row in iter_jsonl(record_path):
        for framing in wanted:
            for suffix in bound_suffixes(framing, column, row):
                if taxonomy_columns(framing, suffix)["l1"] in row:
                    found[framing].add(suffix)
        seen.update(key for key in row if key.startswith(DQ_PREFIX))
        if column and all(found.values()):
            break  # a bound column has exactly one suffix per framing; nothing left to discover
    missing = [framing for framing in wanted if not found[framing]]
    if missing and not require_all:
        return OrderedDict(
            (framing, sorted(found[framing])) for framing in wanted if found[framing]
        )
    if missing:
        label = f"framing {missing[0]!r}" if len(missing) == 1 else f"framings {missing}"
        raise ValueError(
            f"no taxonomy columns for {label} (column={column!r}) in any row of "
            f"{record_path}; dq_ columns seen: {sorted(seen)}"
        )
    return OrderedDict((framing, sorted(found[framing])) for framing in wanted)


def bound_columns(record_path: str, framing: str, column: Optional[str]) -> list:
    """The column suffixes one ``framing`` was bound to; see ``discover_columns``."""
    return discover_columns(record_path, [framing], column)[framing]


def resolve_columns(
    record_path: str, framing: str, column: Optional[str], suffix: Optional[str] = None
) -> dict:
    """Map ``l1``/``l2``/``l3``/``margin``/``text`` to record-level column names for one bound column.

    For nested formats (``column`` is None) the framing ran once per normalized column; pass
    ``suffix`` to choose one. When several are present and none is chosen, a ``ValueError`` lists
    them rather than silently picking one.
    """
    suffixes = bound_columns(record_path, framing, column)
    if suffix is None:
        if len(suffixes) > 1:
            raise ValueError(
                f"framing {framing!r} ran on several columns {suffixes}; pass suffix= to pick one"
            )
        suffix = suffixes[0]
    elif suffix not in suffixes:
        raise ValueError(
            f"framing {framing!r} has no columns for {suffix!r}; bound columns: {suffixes}"
        )
    columns = taxonomy_columns(framing, suffix)
    columns["text"] = suffix
    return columns


def _text_of(row: dict, suffix: str, limit: int) -> str:
    """The bound text of a row for a listing, or ``REDACTED`` when the job's ``pii_detection`` flagged
    that column on this row (the check ``scripts/drill_down_rows.py`` makes before it shows a row).
    """
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


def _margin(value: Any) -> Optional[float]:
    try:
        margin = float(value)
    except (TypeError, ValueError):
        return None
    return margin if margin == margin else None  # NaN guard


# --------------------------------------------------------------------------- tree


def _count_row(summary: dict, row: dict, columns: dict) -> None:
    """Add one scored row to a tree summary (no-op for a row without an L1 label)."""
    l1, l2, l3 = (row.get(columns[level]) for level in LEVELS)
    if not l1:
        return
    summary["classified"] += 1
    margin = _margin(row.get(columns["margin"]))
    if margin is not None and margin < LOW_CONFIDENCE_MARGIN:
        summary["low_confidence"] += 1
    node1 = summary["tree"].setdefault(l1, {"count": 0, "children": OrderedDict()})
    node1["count"] += 1
    node2 = node1["children"].setdefault(l2 or "(none)", {"count": 0, "children": OrderedDict()})
    node2["count"] += 1
    node2["children"][l3 or "(none)"] = node2["children"].get(l3 or "(none)", 0) + 1


def build_trees(record_path: str, targets: Mapping[str, Iterable[str]]) -> "OrderedDict":
    """Count rows per L1 > L2 > L3 label for every (framing, bound column) in ONE pass over the rows.

    ``targets`` maps framing -> bound column suffixes, the shape ``discover_columns`` returns.
    Returns ``{framing: {bound: tree_summary}}`` where each tree_summary is
    ``{'framing', 'bound', 'total', 'classified', 'low_confidence', 'tree'}`` and ``tree`` maps
    L1 label -> ``{'count', 'children': {L2 label -> {'count', 'children': {L3 label -> count}}}}``.
    """
    plan = [
        (framing, bound, taxonomy_columns(framing, bound))
        for framing, bounds in targets.items()
        for bound in bounds
    ]
    trees: OrderedDict = OrderedDict()
    for framing, bound, _columns in plan:
        trees.setdefault(framing, OrderedDict())[bound] = {
            "framing": framing,
            "bound": bound,
            "total": 0,
            "classified": 0,
            "low_confidence": 0,
            "tree": OrderedDict(),
        }
    total = 0
    for row in iter_jsonl(record_path):
        total += 1
        for framing, bound, columns in plan:
            _count_row(trees[framing][bound], row, columns)
    for framing_trees in trees.values():
        for summary in framing_trees.values():
            summary["total"] = total
    return trees


def build_tree(
    record_path: str,
    column: Optional[str],
    framing: str,
    suffix: Optional[str] = None,
    columns: Optional[dict] = None,
) -> dict:
    """Count rows per L1 > L2 > L3 label for one framing on one bound column.

    See ``build_trees`` for the result shape and ``resolve_columns`` for ``suffix``. Pass a
    precomputed ``resolve_columns`` result as ``columns`` to skip the column-discovery pass; the
    rows are then read exactly once.
    """
    if columns is None:
        columns = resolve_columns(record_path, framing, column, suffix)
    bound = columns["text"]
    return build_trees(record_path, {framing: [bound]})[framing][bound]


def run_label(run: dict) -> str:
    """The bound column an aggregate run covers, from its ``view`` (``{"Text": "prompt"}``)."""
    view = run.get("view")
    if isinstance(view, dict):
        return ", ".join(str(value) for value in view.values()) or "all rows"
    if isinstance(view, list):
        return (
            ", ".join(
                str(item.get("Column", item)) if isinstance(item, dict) else str(item)
                for item in view
            )
            or "all rows"
        )
    return str(view) if view else "all rows"


def render_tree(
    tree_summary: dict, title: Optional[str] = None, max_l1: int = 8, max_children: int = 5
) -> str:
    """Render the tree largest-first as indented text with counts and percentages."""
    total = tree_summary["total"] or 1
    lines = [title or f"{tree_summary['framing']} taxonomy on {tree_summary.get('bound', '?')}"]
    lines.append(
        f"{tree_summary['classified']} of {tree_summary['total']} rows classified, "
        f"{tree_summary['low_confidence']} low-confidence (margin < {LOW_CONFIDENCE_MARGIN})"
    )
    l1_items = sorted(tree_summary["tree"].items(), key=lambda kv: kv[1]["count"], reverse=True)
    for label, node in l1_items[:max_l1]:
        lines.append(f"{label} — {node['count']} rows ({node['count'] / total:.0%})")
        l2_items = sorted(node["children"].items(), key=lambda kv: kv[1]["count"], reverse=True)
        for l2_label, l2_node in l2_items[:max_children]:
            lines.append(f"  ├─ {l2_label} — {l2_node['count']}")
            l3_items = sorted(l2_node["children"].items(), key=lambda kv: kv[1], reverse=True)
            for l3_label, count in l3_items[:max_children]:
                lines.append(f"  │  ├─ {l3_label} — {count}")
            if len(l3_items) > max_children:
                lines.append(f"  │  └─ … {len(l3_items) - max_children} more")
        if len(l2_items) > max_children:
            lines.append(f"  └─ … {len(l2_items) - max_children} more")
    if len(l1_items) > max_l1:
        lines.append(f"… {len(l1_items) - max_l1} more top-level categories")
    return "\n".join(lines)


# --------------------------------------------------------------------------- summarize


def summarize(
    aggregate_path: str,
    record_path: Optional[str] = None,
    column: Optional[str] = None,
    framings: Optional[list] = None,
) -> dict:
    """Read the aggregate report (and optionally the scored rows) into a report dict.

    ``result['runs']`` holds one entry per bound column (its ``view`` names the column, see
    ``run_label``; each has its own ``taxonomy_report_path``) with the run fields and per-framing
    counts; ``result['trees'][framing][bound_column]`` (when ``record_path`` is given) holds one
    tree summary per bound column, so nested formats get a prompt tree and a completion tree;
    ``result['text']`` is a ready-to-print summary.
    """
    aggregate = load_json(aggregate_path)
    runs_in = aggregate.get("taxonomy") or []
    result: dict = {"runs": [], "trees": OrderedDict(), "text": ""}
    lines = []
    if not runs_in:
        lines.append("taxonomy: not present in the aggregate report")
    for run in runs_in:
        payload = run.get("result", {})
        # nested formats produce one run per normalized column: name it so the lines stay distinct
        prefix = f"{run_label(run)} — " if len(runs_in) > 1 else ""
        entry = {field: payload.get(field) for field in RUN_FIELDS}
        entry["view"] = run.get("view")
        entry["framings"] = OrderedDict()
        for framing, counts in (payload.get("framings") or {}).items():
            entry["framings"][framing] = {field: counts.get(field) for field in FRAMING_FIELDS}
            lines.append(
                f"{prefix}{framing}: {counts.get('l1_count')} / {counts.get('l2_count')} / "
                f"{counts.get('l3_count')} categories (L1 / L2 / L3), "
                f"{counts.get('classified_count')} of {entry['input_count']} rows classified, "
                f"{counts.get('low_confidence_count')} low-confidence"
            )
        if (
            entry["output_count"] != entry["input_count"]
            or entry["count_anomaly"]
            or (entry["excluded_count"] or 0) > 0
        ):
            lines.append(
                "WARNING: row accounting disagrees (output_count, excluded_count, or "
                "count_anomaly) — treat this run as suspect"
            )
        result["runs"].append(entry)
    if record_path and result["runs"]:
        wanted = list(framings) if framings else list(result["runs"][0]["framings"])
        # Two passes over the scored rows in total: one to discover every framing's bound columns,
        # one to count every tree, however many framings and bound columns there are.
        result["trees"] = build_trees(record_path, discover_columns(record_path, wanted, column))
    result["text"] = "\n".join(lines)
    return result


# --------------------------------------------------------------------------- row listings


def rows_for_category(
    record_path: str,
    column: Optional[str],
    framing: str,
    level: str,
    label: str,
    limit: int = 20,
    text_chars: int = 120,
    suffix: Optional[str] = None,
) -> dict:
    """Rows whose ``level`` (l1/l2/l3) label equals ``label``; returns ``{'total', 'rows'}``.

    See ``resolve_columns`` for ``suffix`` (nested formats).
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    matches: list = []
    total = 0
    columns = resolve_columns(record_path, framing, column, suffix)
    for row in iter_jsonl(record_path):
        if row.get(columns[level]) != label:
            continue
        total += 1
        if len(matches) < limit:
            matches.append(
                {
                    "text": _text_of(row, columns["text"], text_chars),
                    "l1": row.get(columns["l1"]),
                    "l2": row.get(columns["l2"]),
                    "l3": row.get(columns["l3"]),
                    "margin": _margin(row.get(columns["margin"])),
                }
            )
    return {"total": total, "rows": matches}


def low_confidence_rows(
    record_path: str,
    column: Optional[str],
    framing: str,
    limit: int = 20,
    threshold: float = LOW_CONFIDENCE_MARGIN,
    text_chars: int = 120,
    suffix: Optional[str] = None,
) -> dict:
    """Rows with margin below ``threshold``, least confident first; returns ``{'total', 'rows'}``.

    ``total`` counts every low-confidence row; only the ``limit`` least confident are kept in memory
    (a bounded heap), so the listing is safe on large outputs. See ``resolve_columns`` for ``suffix``
    (nested formats).
    """
    columns = resolve_columns(record_path, framing, column, suffix)
    total = 0
    kept: list = []  # bounded heap of the ``limit`` smallest margins: (-margin, -order, item)
    for order, row in enumerate(iter_jsonl(record_path)):
        margin = _margin(row.get(columns["margin"]))
        if margin is None or margin >= threshold:
            continue
        total += 1
        if limit <= 0:
            continue
        entry = (
            -margin,
            -order,
            {
                "text": _text_of(row, columns["text"], text_chars),
                "l3": row.get(columns["l3"]),
                "margin": margin,
            },
        )
        if len(kept) < limit:
            heapq.heappush(kept, entry)
        else:
            heapq.heappushpop(kept, entry)  # evicts the largest margin (latest row on ties)
    ordered = sorted(
        kept, key=lambda entry: (-entry[0], -entry[1])
    )  # ascending margin, then file order
    return {"total": total, "rows": [item for _, _, item in ordered]}


# --------------------------------------------------------------------------- CLI


def _parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_argument_group("inputs")
    source.add_argument(
        "--metadata",
        metavar="URI_OR_DIR",
        help="the job's metadata.json S3 URI (DescribeJob JobConfigDocument.MetadataS3Uri), "
        "or a local copy of the job's output folder; S3 objects are streamed",
    )
    source.add_argument(
        "--aggregate", help="aggregate/quality_report.json, an S3 URI or a local path"
    )
    source.add_argument(
        "--record-level",
        help="record_level/evaluated_data.jsonl, an S3 URI (streamed) " "or a local path",
    )
    parser.add_argument(
        "--column",
        help="bound text column, as named in the dataset; omit when the "
        "operator ran without a View",
    )
    parser.add_argument(
        "--framing",
        choices=FRAMINGS,
        help="framing for --category / --low-confidence " "(default: every framing that ran)",
    )
    parser.add_argument(
        "--category",
        metavar="LEVEL=LABEL",
        help='list rows assigned to a label, e.g. l1="Reasoning & Logic"',
    )
    parser.add_argument(
        "--low-confidence", type=int, default=0, metavar="N", help="list the N least confident rows"
    )
    parser.add_argument("--limit", type=int, default=20, help="rows shown per listing")
    parser.add_argument(
        "--bound",
        metavar="SUFFIX",
        help="without a View: which derived column to list rows for "
        "(dq_input__prompt or dq_input__completion)",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)
    if args.metadata:
        paths = fetch_outputs(args.metadata)
        args.aggregate = args.aggregate or paths["aggregate"]
        args.record_level = args.record_level or paths["record_level"]
    if not (args.aggregate or args.record_level):
        parser.error("give --metadata, or --aggregate and/or --record-level")
    if (args.category or args.low_confidence) and not (args.record_level and args.framing):
        parser.error("--category and --low-confidence need --record-level and --framing")
    return args


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    report: dict = {}
    framings = [args.framing] if args.framing else None
    if args.aggregate:
        report["summary"] = summarize(args.aggregate, args.record_level, args.column, framings)
    elif args.record_level:
        report["summary"] = {"runs": [], "trees": OrderedDict(), "text": ""}
        # Two passes over the rows in total, like the aggregate path: an explicitly requested framing
        # must be present (fail loudly); the default scan simply omits framings that did not run.
        targets = discover_columns(
            args.record_level, framings or list(FRAMINGS), args.column, require_all=bool(framings)
        )
        report["summary"]["trees"] = build_trees(args.record_level, targets)
    if args.category:
        level, _, label = args.category.partition("=")
        report["category"] = rows_for_category(
            args.record_level,
            args.column,
            args.framing,
            level.strip(),
            label.strip().strip('"'),
            args.limit,
            suffix=args.bound,
        )
    if args.low_confidence:
        report["low_confidence"] = low_confidence_rows(
            args.record_level, args.column, args.framing, args.low_confidence, suffix=args.bound
        )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    summary = report["summary"]
    if summary["text"]:
        print(summary["text"])
    for per_column in summary["trees"].values():
        for tree in per_column.values():
            print()
            print(render_tree(tree))
    if "category" in report:
        print(
            f"\n{report['category']['total']} rows in {args.category}; showing "
            f"{len(report['category']['rows'])}:"
        )
        for item in report["category"]["rows"]:
            print(f"  [{item['l3']}] margin={item['margin']}: {item['text']}")
    if "low_confidence" in report:
        print(f"\n{report['low_confidence']['total']} low-confidence rows; least confident first:")
        for item in report["low_confidence"]["rows"]:
            print(f"  margin={item['margin']:.3f} [{item['l3']}]: {item['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
