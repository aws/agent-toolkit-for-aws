#!/usr/bin/env python3
"""Show the rows a drill-down question names without downloading the row-level file.

    python3 <skill-root>/references/dataset-quality/scripts/drill_down_rows.py \\
        --metadata s3://.../metadata.json --where dq_word_count__completion '<' 20
    python3 .../drill_down_rows.py --metadata s3://.../metadata.json --lowest dq_word_count__completion
    python3 .../drill_down_rows.py --metadata s3://.../metadata.json --failed completion_min_length
    python3 .../drill_down_rows.py --metadata s3://.../metadata.json --sample dq_word_count__completion

Reads `Reports.RecordLevel[0]` from the job's `metadata.json` (its S3 URI is
`JobConfigDocument.MetadataS3Uri` in `describe_job`), or the object named by
`--bucket` and `--key`, and streams the row-level file line by line: with boto3
when it is installed, else through `aws s3 cp s3://BUCKET/KEY -` (the CLI's
stdout, piped; the process is ended when the read stops; a failed copy ends the
script with the CLI's error); one line on stderr
says which (`streamed with boto3` / `streamed with aws s3 cp`). One mode is
required. `--where COLUMN OP VALUE` answers a predicate question: the first CAP
matching rows in file order, and the read stops at the cap. A row whose value is
of another kind than VALUE (a string where VALUE is a number, or the reverse) is
not comparable: it is skipped, never a match, and one line on stderr after `Kept`
says how many rows were skipped for that reason. `--lowest COLUMN` or
`--highest COLUMN` answers a ranking question: one pass over the whole stream,
`heapq` keeps a bounded set of the CAP extreme rows, unscored rows are skipped.
A ranking ranks numbers only: a row whose value is not a number (a string on some
rows of a spec metric) is skipped, and one line on stderr after `Kept` says how
many rows were skipped for that reason.
COLUMN is a flat column name or a dotted path into a nested object, such as
`dq_spec_eval_criteria.<id>.value` for a spec metric's per-row value; a row
without the path, or with `None` there, is unscored, and the kept row carries the
value under the dotted path as its key.
`--sample [COLUMN]` is the sampled read: the first CAP rows of the file in file
order, whatever their values (a label, a negative number, a missing score; no row
is filtered out), and the read stops at the cap; with COLUMN each kept row carries
that column's value when the row has one. It is the form for a file too large to
stream whole, and the `Kept` line says the rows are a sample. `--columns` with no
names keeps no text column, so a kept row is its score alone.
`--failed [CRITERION]` keeps rows whose `dq_spec_eval_pass` is `False` (never
`None`) and, with CRITERION, only rows whose `dq_spec_eval_failed_criteria` list
names it. Each kept row carries, by default, which rules failed and why: its
`dq_spec_eval_failed_criteria` list and a `failed` object `{id: reason, ...}` with
each failed criterion's `reason` from `dq_spec_eval_criteria[<id>]`; with
CRITERION, also that criterion's `reason`. A failed `context: documents`
criterion also brings its `evidence`, `quote` and `support` from the same entry
(the keys the entry has) in a `context` object `{id: {evidence, quote, support},
...}` beside `failed`; with CRITERION, that criterion's fields appear at the top
level beside `reason` too. No second read of the file is needed for the failed
rule, the reason or the passage cited. Those are the row keys a spec filter tests:
`dq_spec_eval_pass`, `dq_spec_eval_failed_criteria` (the list of failed ids), and
per criterion `dq_spec_eval_criteria[<id>].outcome`
(`pass` / `fail` / `not_applicable` / `not_evaluable` on a `context: documents`
criterion, which has no `verdict`) or `.verdict` (`True` / `False` on a row check),
with `.reason` on every entry. Prints one JSON object per kept row (the text
columns and the score, or the failed ids and reasons) on stdout and `Kept N rows`
on stderr. At most CAP rows are in memory, the file is never held whole, nothing
is written to disk. The rows are the user's data and may hold PII: a kept text
column that the job's `pii_detection` flagged on that row (`dq_pii_flagged__<column>`
true) is printed as `[REDACTED: PII]`. On a row flagged on any text column, kept or
not, `--failed` prints each criterion's `reason` and a documents criterion's `quote`,
`evidence` and `support` as the same marker, since the LLM check's reason often echoes the
row's own text. Used by `drill-down.md`.
"""

from __future__ import annotations

import argparse
import heapq
import json
import operator
import subprocess
import sys
import threading
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

CAP = 20  # rows kept: the presentation limit in drill-down.md
READ_TIMEOUT_SECONDS = 30  # S3 socket read timeout (botocore default 60): a stalled stream raises
# Text columns by format: chat formats use `messages`, others have flat
# prompt/completion (or chosen/rejected, text) fields.
TEXT_COLS = ("messages", "prompt", "completion", "chosen", "rejected", "text")
OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}
# A `context: documents` criterion's row fields carried beside its reason on a failed row
CONTEXT_KEYS = ("evidence", "quote", "support")
REDACTED = "[REDACTED: PII]"  # printed in place of a text column pii_detection flagged on the row
PII_PREFIX = "dq_pii_flagged__"  # the flag column pii_detection writes per text column
INPUT_PREFIX = "dq_input__"  # a text column the service derives from a source column
_SAID: set = set()  # the transports named on stderr so far: one line per run, not per object


class _CliBody:
    """`aws s3 cp s3://BUCKET/KEY -` as a body, when boto3 is not installed: `iter_lines()` yields
    the CLI's stdout line by line as bytes without the newline (as botocore's does) and records when
    the end of stdout is reached; a read that stopped at the cap ends the copy: `close()` terminates
    the process and waits for it, so it leaves no child behind; after a full read `close()` waits and,
    when the CLI exited non-zero (object missing, access denied, no credentials), raises `SystemExit`
    with the CLI's stderr, so a failed copy is not mistaken for no matching rows. Whether the read was
    full is the recorded end of stdout, never `poll()`, which can still be None right after the last
    line of a copy that is about to exit non-zero. The CLI's stderr is drained on its own thread while the
    body is read, so a copy that writes much to stderr cannot block the read. The object goes through
    the pipe only; nothing is written to disk."""

    def __init__(self, bucket: str, key: str):
        command = ["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"]
        self.ended = False  # set by `iter_lines()` when the end of stdout is reached
        self._stderr = b""  # the CLI's stderr, drained by `_reader` while stdout is read
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise SystemExit("neither boto3 nor the aws CLI is available to read " + command[3])
        self._reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._reader.start()

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        self._stderr = self.process.stderr.read()  # whole: ends when the child closes its stderr

    def iter_lines(self) -> Iterator[bytes]:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            yield line.rstrip(b"\r\n")
        self.ended = True

    def close(self) -> None:
        if not self.ended:
            self.process.terminate()  # the read stopped early: end the copy
            self.process.wait()
            self._reader.join()
            return
        self.process.wait()  # the read went to the end: the copy has finished; check the CLI's exit
        self._reader.join()
        if self.process.returncode:
            error = self._stderr.decode(errors="replace").strip()
            raise SystemExit("aws s3 cp failed: " + error)


def _body(bucket: str, key: str):
    """The object's body: boto3 when it is installed, else the AWS CLI piped through `_CliBody`."""
    try:
        import boto3
    except ImportError:
        transport, body = "aws s3 cp", _CliBody(bucket, key)
    else:
        from botocore.config import Config

        # A read timeout, so a stalled stream raises instead of hanging the read.
        client = boto3.client("s3", config=Config(read_timeout=READ_TIMEOUT_SECONDS))
        transport, body = "boto3", client.get_object(Bucket=bucket, Key=key)["Body"]
    if transport not in _SAID:
        _SAID.add(transport)
        print(f"streamed with {transport}", file=sys.stderr)
    return body


def _split_s3(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://") or "/" not in uri[5:]:
        raise SystemExit(f"not an S3 object URI: {uri}")
    bucket, key = uri[5:].split("/", 1)
    return bucket, key


def _record_level(metadata_uri: str) -> Tuple[str, str]:
    body = _body(*_split_s3(metadata_uri))
    try:
        meta = json.loads(b"".join(body.iter_lines()))
    finally:
        body.close()
    paths = (meta.get("Reports") or {}).get("RecordLevel") or []
    if not paths:
        raise SystemExit("metadata.json has no Reports.RecordLevel entry — pass --bucket and --key")
    return _split_s3(paths[0])


def _rows(body) -> Iterator[Dict[str, Any]]:
    for raw in body.iter_lines():
        if not raw:
            continue
        yield json.loads(raw)


def _get(row: Dict[str, Any], path: str) -> Any:
    """The value at a dotted `path`: `a.b.c` is `row["a"]["b"]["c"]`; `None` when a segment is missing
    or a value on the way is not an object. A flat column name is a one-segment path."""
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def sanitize_column(column: str) -> str:
    """The row-column suffix the job writes for a bound column: lowercased, each run of characters
    other than letters and digits (`str.isalnum`) replaced by one `_`, leading and trailing `_` dropped.
    """
    # The service's rule (metric_engine.py, `_sanitize_column`); the same body sits in drill_down_rows.py,
    # dedup_decisions.py and taxonomy_summary.py, which run standalone.
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in column)
    return "_".join(p for p in out.split("_") if p)


def _shown(row: Dict[str, Any], column: str) -> Any:
    """The column's value, or `REDACTED` when the job's `pii_detection` flagged it on this row. A
    `dq_input__` column is text the service derived from a source column (`dq_input__prompt` from
    `messages`), so it is `REDACTED` when any column of the row is flagged."""
    if row.get(f"{PII_PREFIX}{sanitize_column(column)}") is True:
        return REDACTED
    if column.startswith(INPUT_PREFIX) and _pii_flagged(row):
        return REDACTED
    return row[column]


def _pick(row: Dict[str, Any], columns: Sequence[str], score_col: Optional[str]) -> Dict[str, Any]:
    picked = {c: _shown(row, c) for c in columns if c in row}
    if not score_col:
        return picked
    # A flat score column goes through the same redaction as the shown columns: a `--where` on a text
    # column names that column as the score, and its value on a flagged row must stay `REDACTED`. A
    # dotted path (a judge's `reason` quotes the row's text) is `REDACTED` when any column of the row is flagged.
    if score_col in row:
        score = _shown(row, score_col)
    else:
        score = REDACTED if _pii_flagged(row) else _get(row, score_col)
    return (
        {**picked, score_col: score} if score is not None else picked
    )  # the score under its (dotted) path


def _matches(value: Any, op: str, target: Any) -> Optional[bool]:
    """`value OP target`, or `None` when the two are not comparable: a row's value of another kind than
    the target (a string against a number, as a spec metric's per-row value can be on some rows), or a
    pair the operator rejects. `None` is never a match, so one such row cannot end the streamed read.
    """
    numbers = (int, float)
    same_kind = (isinstance(value, numbers) and isinstance(target, numbers)) or type(value) is type(
        target
    )
    if not same_kind:
        return None
    try:
        return bool(OPS[op](value, target))
    except TypeError:
        return None


def where_rows(
    body, score_col: str, op: str, target: Any, cap: int, columns: Sequence[str]
) -> Tuple[List[Dict[str, Any]], int]:
    """A predicate question: the first `cap` rows whose `score_col` satisfies `op target`, in file order,
    and the number of rows skipped because their value was not comparable to `target`."""
    kept, skipped = [], 0
    for row in _rows(body):
        # The question's condition. Example: "completions under 20 words".
        value = _get(row, score_col)
        if value is None:
            continue  # unscored row: not a match
        match = _matches(value, op, target)
        if match is None:
            skipped += 1  # another kind of value than the target: counted, never a match
        elif match:
            kept.append(_pick(row, columns, score_col))
            if len(kept) >= cap:
                break  # stop reading: the rest of the file stays on S3
    kept.sort(key=lambda r: r[score_col], reverse=op in (">", ">="))
    return kept, skipped


def scored_rows(
    body, score_col: str, columns: Sequence[str], skipped: List[int]
) -> Iterator[Tuple[Any, Dict[str, Any]]]:
    # One pass over the stream: yields (score, row with the named columns only) for each scored row
    for row in _rows(body):
        score = _get(
            row, score_col
        )  # a flat column or a dotted path such as dq_spec_eval_criteria.<id>.value
        if score is None:
            continue  # unscored row: it has no rank
        if not isinstance(score, (int, float)):
            skipped[0] += 1  # not a number ("n/a" on some rows): no rank, counted, never an abort
            continue
        yield score, _pick(row, columns, score_col)


def ranked_rows(
    body, score_col: str, lowest: bool, cap: int, columns: Sequence[str]
) -> Tuple[List[Dict[str, Any]], int]:
    """A ranking question: the `cap` lowest (or highest) rows on `score_col` over the whole stream, and
    the number of rows skipped because their value is not a number (`heapq` cannot order a string
    against a number, so such a row would end the read)."""
    pick = heapq.nsmallest if lowest else heapq.nlargest
    skipped = [0]
    ranked = pick(
        cap, scored_rows(body, score_col, columns, skipped), key=lambda item: item[0]
    )  # a bounded set of CAP rows, never the file
    return [row for _, row in ranked], skipped[0]  # already sorted by the metric, worst first


def sample_rows(
    body, score_col: Optional[str], cap: int, columns: Sequence[str]
) -> List[Dict[str, Any]]:
    """The sampled read: the first `cap` rows in file order, whatever their values, then stop. No
    condition is tested, so a label column, a negative score or a missing score never keeps the read
    going past the cap; a row without `score_col` is kept without it."""
    kept = []
    for row in _rows(body):
        kept.append(_pick(row, columns, score_col))
        if len(kept) >= cap:
            break  # stop reading: the rest of the file stays on S3
    return kept


def _pii_flagged(row: Dict[str, Any]) -> bool:
    """Whether the job's `pii_detection` flagged any text column of this row (`dq_pii_flagged__<column>`
    true for any column, kept or not): then the LLM check's text about the row is treated as the row's own.
    """
    return any(k.startswith(PII_PREFIX) and v is True for k, v in row.items())


def _context(entry: Any, flagged: bool = False) -> Dict[str, Any]:
    """A documents criterion's `evidence`, `quote` and `support`: the keys its row entry has, each
    `REDACTED` when the row is PII-flagged (the quote is the row's text, the evidence can carry it).
    """
    entry = entry if isinstance(entry, dict) else {}
    return {k: REDACTED if flagged else entry[k] for k in CONTEXT_KEYS if k in entry}


def failed_rows(
    body, criterion: Optional[str], cap: int, columns: Sequence[str]
) -> List[Dict[str, Any]]:
    """Rows that failed `criterion` (any criterion when None), each with its failed ids, their reasons and
    a documents criterion's evidence, quote and support, up to `cap`. On a row `pii_detection` flagged,
    each reason and each of those fields is `REDACTED`, as the text column is: the LLM check's reason often
    echoes the row's text."""
    kept = []
    for row in _rows(body):
        # `dq_spec_eval_pass` null rows were not evaluated: neither a pass nor a failure
        if row.get("dq_spec_eval_pass") is not False:
            continue
        failed = row.get("dq_spec_eval_failed_criteria") or []  # which rules the row failed
        if criterion is not None and criterion not in failed:
            continue
        detail = row.get("dq_spec_eval_criteria")  # the reason from the per-criterion detail
        detail = detail if isinstance(detail, dict) else {}
        flagged = _pii_flagged(row)  # PII on any text column: the LLM check's text may echo it
        reasons = {c: (detail.get(c) or {}).get("reason") for c in failed}  # why, per failed rule
        if flagged:
            reasons = {c: REDACTED if r is not None else None for c, r in reasons.items()}
        context = {
            c: _context(detail.get(c), flagged) for c in failed
        }  # the passage cited, per documents rule
        context = {c: fields for c, fields in context.items() if fields}
        picked = {
            **_pick(row, columns, None),
            "dq_spec_eval_failed_criteria": failed,
            "failed": reasons,
        }
        if context:
            picked["context"] = context
        reason = reasons.get(criterion) if criterion else None
        kept.append(
            {**picked, **context.get(criterion, {}), "reason": reason} if criterion else picked
        )
        if len(kept) >= cap:
            break
    return kept


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--metadata", help="s3://.../metadata.json of the job (preferred)")
    src.add_argument("--bucket", help="bucket of record_level/evaluated_data.jsonl, with --key")
    ap.add_argument("--key", help="key of record_level/evaluated_data.jsonl, with --bucket")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--where",
        nargs=3,
        metavar=("COLUMN", "OP", "VALUE"),
        help="predicate: the first CAP rows where COLUMN OP VALUE (OP: " + " ".join(OPS) + ")",
    )
    mode.add_argument("--lowest", metavar="COLUMN", help="ranking: the CAP lowest rows on COLUMN")
    mode.add_argument("--highest", metavar="COLUMN", help="ranking: the CAP highest rows on COLUMN")
    mode.add_argument(
        "--failed",
        nargs="?",
        const="",
        metavar="CRITERION",
        help="rows with dq_spec_eval_pass False; with CRITERION, only rows that failed it",
    )
    mode.add_argument(
        "--sample",
        nargs="?",
        const="",
        metavar="COLUMN",
        help="sampled read: the first CAP rows of the file, any value; with COLUMN, each carries its value",
    )
    ap.add_argument("--cap", type=int, default=CAP, help=f"rows kept (default {CAP})")
    ap.add_argument(
        "--columns",
        nargs="*",
        default=list(TEXT_COLS),
        help="text columns kept (none named: the score column only)",
    )
    args = ap.parse_args(argv)
    if bool(args.bucket) != bool(args.key):
        ap.error("--bucket and --key go together")
    if args.where and args.where[1] not in OPS:
        ap.error("--where OP must be one of " + " ".join(OPS))
    bucket, key = _record_level(args.metadata) if args.metadata else (args.bucket, args.key)
    body = _body(bucket, key)
    ranking = args.lowest or args.highest
    skipped = (
        ""  # the summary of rows skipped as not comparable (--where) or not a number (ranking)
    )
    try:
        if args.where:
            column, op, target = args.where
            kept, count = where_rows(body, column, op, _value(target), args.cap, args.columns)
            if count:
                skipped = f"Skipped {count} rows whose {column} is not comparable with {target}"
        elif ranking:
            kept, count = ranked_rows(body, ranking, bool(args.lowest), args.cap, args.columns)
            if count:
                skipped = f"Skipped {count} rows whose {ranking} is not a number"
        elif args.sample is not None:
            kept = sample_rows(body, args.sample or None, args.cap, args.columns)
        else:
            kept = failed_rows(body, args.failed or None, args.cap, args.columns)
    finally:
        body.close()
    for row in kept:
        print(json.dumps(row))
    if ranking:
        note = f" ({'lowest' if args.lowest else 'highest'} on {ranking}, of the whole file)"
    elif args.sample is not None:
        note = " (a sample: the first rows of the file, in file order, whatever their values)"
    else:
        note = " (cap reached; more may match)" if len(kept) >= args.cap else ""
    print(f"Kept {len(kept)} rows{note}", file=sys.stderr)
    if skipped:
        print(skipped, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
