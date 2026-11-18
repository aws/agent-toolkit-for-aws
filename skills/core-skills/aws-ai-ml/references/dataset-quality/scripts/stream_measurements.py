#!/usr/bin/env python3
"""Summarise a spec job's measurement criteria without downloading the row-level file.

    python3 <skill-root>/references/dataset-quality/scripts/stream_measurements.py \
        --metadata s3://.../metadata.json

Reads `Reports.RecordLevel[0]` from the job's `metadata.json` (its S3 URI is
`JobConfigDocument.MetadataS3Uri` in `describe_job`) and streams the row-level
file line by line: with boto3 when it is installed, else through
`aws s3 cp s3://BUCKET/KEY -` (the CLI's stdout, piped; a failed copy ends the
script with the CLI's error); one line on stderr says which (`streamed with
boto3` / `streamed with aws s3 cp`). Prints one JSON object per measurement
criterion — a criterion at least one of whose row entries carries the key
`value` (present even when null). A check is skipped and named on stderr: a
row-only check carries a `verdict` on its rows; a `context: documents` check
carries an `outcome` and no `value` (a documents metric carries `value` and
`value_kind` with `outcome: measured`). Numeric values → count, nulls, min,
mean, max; label values → a distribution; an all-null measurement → its null
count. No row is kept in memory, nothing is written to disk. Run only when the
user asks for a measurement summary, never for the report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from typing import Any, Dict, Iterator

READ_TIMEOUT_SECONDS = (
    30  # S3 socket read timeout (botocore default 60), as drill_down_rows.py sets it
)
_SAID: set = set()  # the transports named on stderr so far: one line per run, not per object


class _CliBody:
    """`aws s3 cp s3://BUCKET/KEY -` as a body, when boto3 is not installed: `iter_lines()` yields
    the CLI's stdout line by line as bytes without the newline (as botocore's does) and records when
    the end of stdout is reached; after a full read `close()` waits for the process and, when the
    CLI exited non-zero (object missing, access denied, no credentials), raises `SystemExit` with
    the CLI's stderr, so a failed copy is not mistaken for a file with no measurements. A read that
    stops early (a malformed row, any error in the consumer) ends the copy: `close()` terminates the
    child and waits for it without raising, so the child cannot block on a full pipe and the
    consumer's own error reaches the caller. The CLI's stderr is drained on its own thread while the
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
            self.process.terminate()  # the read stopped early: end the copy so the child cannot block on a full pipe
            self.process.wait()
            self._reader.join()
            return  # no raise: the consumer's own error (a malformed row) propagates
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

        # A read timeout, so a stalled stream raises sooner than botocore's 60 seconds.
        client = boto3.client("s3", config=Config(read_timeout=READ_TIMEOUT_SECONDS))
        transport, body = "boto3", client.get_object(Bucket=bucket, Key=key)["Body"]
    if transport not in _SAID:
        _SAID.add(transport)
        print(f"streamed with {transport}", file=sys.stderr)
    return body


def _iter_lines(uri: str) -> Iterator[str]:
    if uri.startswith("s3://"):
        bucket, key = uri[5:].split("/", 1)
        body = _body(bucket, key)
        try:
            for raw in body.iter_lines():
                if raw:
                    yield raw.decode("utf-8")
        finally:
            body.close()  # both transports: the body is closed after the read
        return
    with open(uri, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield line


def _load_json(uri: str) -> Dict[str, Any]:
    return json.loads("".join(_iter_lines(uri)))


def summarise(
    evaluated_uri: str, criteria_key: str = "dq_spec_eval_criteria"
) -> Dict[str, Dict[str, Any]]:
    """Per-measurement summary. A measurement is a criterion at least one of whose row entries
    carries the key `value` (present even when null); a check is skipped: a row-only check carries a
    `verdict` on its rows, a `context: documents` check carries an `outcome` and no `value`. Numeric
    values get count/nulls/min/mean/max, label values get a distribution, an all-null measurement is
    reported with its null count."""
    stats: Dict[str, Dict[str, Any]] = {}
    for line in _iter_lines(evaluated_uri):
        crit = json.loads(line).get(criteria_key) or {}
        for cid, entry in crit.items():
            entry = entry or {}
            s = stats.setdefault(
                cid,
                {
                    "count": 0,
                    "nulls": 0,
                    "min": None,
                    "max": None,
                    "_sum": 0.0,
                    "labels": {},
                    "has_verdict": False,
                    "has_value": False,
                    "other": 0,
                },
            )
            if entry.get("verdict") is not None:
                s["has_verdict"] = True
            if "value" in entry:
                s["has_value"] = (
                    True  # the key, even when null: a documents check has no `value` key at all
                )
            value = entry.get("value")
            if value is None:
                s["nulls"] += 1
            elif isinstance(value, bool):
                s["other"] += 1
            elif isinstance(value, (int, float)):
                s["count"] += 1
                s["_sum"] += float(value)
                s["min"] = value if s["min"] is None else min(s["min"], value)
                s["max"] = value if s["max"] is None else max(s["max"], value)
            elif isinstance(value, str):
                s["labels"][value] = s["labels"].get(value, 0) + 1
            else:
                s["other"] += 1  # an object or a list is not a measurement value
    out = {}
    for cid, s in stats.items():
        if not s["has_value"]:
            print(f"skipped {cid}: a check (its rows carry no value)", file=sys.stderr)
            continue  # a documents check: `outcome` and no `value` key, not a measurement
        if s["has_verdict"]:
            print(f"skipped {cid}: a check (its rows carry a verdict)", file=sys.stderr)
            continue  # a row-only check, not a measurement
        seen_other = sum(s["labels"].values()) + s["other"]
        if s["count"]:
            out[cid] = {
                "kind": "numeric",
                "count": s["count"],
                "nulls": s["nulls"],
                "min": s["min"],
                "mean": round(s["_sum"] / s["count"], 4),
                "max": s["max"],
            }
            if seen_other:
                out[cid][
                    "non_numeric_values"
                ] = seen_other  # mixed criterion: say so rather than hide it
        elif s["labels"]:
            dist = dict(sorted(s["labels"].items(), key=lambda kv: (-kv[1], kv[0])))
            out[cid] = {
                "kind": "label",
                "count": sum(dist.values()),
                "nulls": s["nulls"],
                "distribution": dist,
            }
            if s["other"]:
                out[cid]["non_scalar_values"] = s["other"]
        elif s["other"]:
            out[cid] = {
                "kind": "non_scalar",
                "count": 0,
                "nulls": s["nulls"],
                "non_scalar_values": s["other"],
                "note": "values are objects or lists; summarise them from the aggregate report",
            }
        else:
            out[cid] = {
                "kind": "unknown",
                "count": 0,
                "nulls": s["nulls"],
                "note": "no row carries a value for this criterion",
            }
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--metadata", help="s3://.../metadata.json of the job (preferred)")
    src.add_argument("--evaluated", help="row-level file URI, when metadata.json is not at hand")
    ap.add_argument("--criteria-key", default="dq_spec_eval_criteria")
    args = ap.parse_args(argv)
    evaluated = args.evaluated
    if args.metadata:
        paths = (_load_json(args.metadata).get("Reports") or {}).get("RecordLevel") or []
        if not paths:
            raise SystemExit("metadata.json has no Reports.RecordLevel entry — pass --evaluated")
        evaluated = paths[0]
    result = summarise(evaluated, args.criteria_key)
    if not result:
        print(
            json.dumps(
                {"measurements": {}, "note": "no criterion carries a numeric value on any row"}
            )
        )
        return
    print(json.dumps({"measurements": result, "source": evaluated}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
