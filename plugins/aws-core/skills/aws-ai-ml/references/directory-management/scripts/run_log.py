#!/usr/bin/env python3
"""The run-log writer: the only code that appends to `<project-dir>/run-log.jsonl`.

Each event of a run (a job's launch or result, an analysis result, a decision, an
approval, the run parameters, a score) is one JSON object on one line of
`run-log.jsonl`. The file is append-only: a line is never rewritten, and the file
is never rewritten, truncated or reordered. A status change is a new line.

Every entry carries `kind`, `step`, `iteration`, `created_at` and `status`, `arn`
for a `job`, and the fields specific to its kind. The writer also sets `id`,
derived from those fields and unique within the file; an entry is referred to by
its `id`. Paths inside an entry are stored relative to the project directory.
Each line is appended under an exclusive file lock, so writers running at the
same time never interleave lines or reuse an `id`.

Library use (code templates and bundled scripts)::

    from run_log import write_entry, read_entries, latest_entry

    entry_id = write_entry("my-project", kind="job", step="fine-tune-model",
                           iteration=1, status="launched", arn=job_arn,
                           manifest="manifests/training-job.json")

Command line (the agent)::

    python3 run_log.py write --project-dir my-project --kind decision \\
        --step iteration-decision --iteration 2 --status continue \\
        --field reason='"below target"' --field score=0.71
    python3 run_log.py list --project-dir my-project --step evaluate-base-model
    python3 run_log.py list --project-dir my-project --kind job --latest

`write` prints the new entry's `id`. `--field key=value` parses `value` as JSON
when it can and keeps it as a string otherwise. `--fields-json '{...}'` passes
several fields at once.

Approvals come from the user, so only the command line writes `kind=approval`;
`write_entry()` refuses it.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

RUN_LOG_FILE = "run-log.jsonl"
PLAN_NAMES = ("PLAN.md", os.path.join("specs", "PLAN.md"))

KINDS = ("parameters", "job", "artifact", "analysis", "decision", "approval", "score", "incident")
JOB_STATUSES = ("launched", "completed", "failed", "stopped")
REQUIRED = ("kind", "step", "iteration", "created_at", "status")
RESERVED = REQUIRED + ("arn", "id")

_SLUG = re.compile(r"[^a-z0-9]+")


class RunLogError(ValueError):
    """An entry is missing a required field or has an invalid value."""


def _slug(value: Any) -> str:
    return _SLUG.sub("-", str(value).lower()).strip("-") or "x"


def resolve_project_dir(project_dir: str) -> str:
    """Return the project directory that owns the run log for `project_dir`.

    A project has one run log, beside its PLAN.md. When `project_dir` is a
    subdirectory of a project (such as `iter_2/`), the nearest ancestor that holds
    a `run-log.jsonl` or a PLAN.md is used. When there is none, `project_dir` itself is.
    """
    start = os.path.abspath(project_dir)
    cur = start
    while True:
        if os.path.isfile(os.path.join(cur, RUN_LOG_FILE)) or any(
            os.path.isfile(os.path.join(cur, p)) for p in PLAN_NAMES
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return start
        cur = parent


def run_log_path(project_dir: str) -> str:
    """Path of the project's `run-log.jsonl`."""
    return os.path.join(resolve_project_dir(project_dir), RUN_LOG_FILE)


def _relativize(value: Any, root: str, given: str) -> Any:
    """Store paths that point inside the project relative to the project directory."""
    if isinstance(value, dict):
        return {k: _relativize(v, root, given) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_relativize(v, root, given) for v in value]
    if not isinstance(value, str) or "://" in value or not value:
        return value
    candidate = None
    if os.path.isabs(value):
        candidate = os.path.normpath(value)
    elif given and not os.path.isabs(given):
        # A relative value is relative to the working directory, as `given` is. It
        # points inside the project when it starts with the project directory's own
        # relative path, which `given` names or, for a subdirectory, contains.
        try:
            rel_root = os.path.relpath(root)
        except ValueError:  # pragma: no cover - Windows, another drive
            rel_root = os.curdir
        if rel_root != os.curdir and os.path.normpath(value).startswith(rel_root + os.sep):
            candidate = os.path.abspath(value)
    if candidate and (candidate == root or candidate.startswith(root + os.sep)):
        return os.path.relpath(candidate, root)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate(entry: Dict[str, Any]) -> None:
    for key in REQUIRED:
        if entry.get(key) in (None, ""):
            raise RunLogError(f"run-log entry needs `{key}`")
    if entry["kind"] not in KINDS:
        raise RunLogError(f"`kind` must be one of {', '.join(KINDS)}, not {entry['kind']!r}")
    iteration = entry["iteration"]
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        raise RunLogError("`iteration` must be a non-negative integer (0 for setup and baseline)")
    if entry["kind"] == "job":
        if not entry.get("arn"):
            raise RunLogError("a `job` entry needs `arn`")
        if entry["status"] not in JOB_STATUSES:
            raise RunLogError(f"a `job` status must be one of {', '.join(JOB_STATUSES)}")


def _id_stem(entry: Dict[str, Any]) -> str:
    return "-".join(
        (
            _slug(entry["kind"]),
            _slug(entry["step"]),
            f"iter{entry['iteration']}",
            _slug(entry["status"]),
        )
    )


def _parse_lines(lines: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield each line that is a JSON object; skip blank or unreadable lines."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            yield entry


@contextmanager
def _locked(fh) -> Iterator[None]:
    """Hold an exclusive lock on the open run-log file."""
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    else:  # pragma: no cover - Windows
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _write(project_dir: str, entry: Dict[str, Any]) -> str:
    root = resolve_project_dir(project_dir)
    entry = {k: _relativize(v, root, project_dir) for k, v in entry.items()}
    entry.setdefault("created_at", _now())
    _validate(entry)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, RUN_LOG_FILE)
    stem = _id_stem(entry)
    # "a+" never truncates; every write lands at the end of the file.
    with open(path, "a+", encoding="utf-8") as fh:
        with _locked(fh):
            fh.seek(0)
            text = fh.read()
            taken: Set[str] = {str(e["id"]) for e in _parse_lines(text.splitlines()) if e.get("id")}
            n = 1
            entry_id = stem
            while entry_id in taken:
                n += 1
                entry_id = f"{stem}-{n}"
            line = json.dumps({"id": entry_id, **entry}, sort_keys=False, default=str)
            # A line cut short by an interrupted writer stays as it is; the new line starts fresh.
            prefix = "\n" if text and not text.endswith("\n") else ""
            fh.write(prefix + line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry_id


def _build(kind, step, iteration, status, arn, fields) -> Dict[str, Any]:
    clash = sorted(set(fields) & set(RESERVED))
    if clash:
        raise RunLogError(f"pass {', '.join(clash)} as arguments, not as fields")
    entry: Dict[str, Any] = {"kind": kind, "step": step, "iteration": iteration, "status": status}
    if arn:
        entry["arn"] = arn
    entry.update(fields)
    return entry


def write_entry(
    project_dir: str,
    *,
    kind: str,
    step: str,
    iteration: int,
    status: str,
    arn: Optional[str] = None,
    **fields: Any,
) -> str:
    """Append one new entry and return its `id`.

    Code never records an approval: `kind="approval"` is refused here and is
    written by the agent through the command line after the user gives it.
    """
    if kind == "approval":
        raise RunLogError(
            "approvals come from the user; the agent records them with the run_log.py CLI"
        )
    return _write(project_dir, _build(kind, step, iteration, status, arn, fields))


def record_job(
    project_dir: str, *, step: str, iteration: int, status: str, arn: str, **fields: Any
) -> str:
    """Shorthand for a `job` entry: a launch (`launched`) or a result."""
    return write_entry(
        project_dir, kind="job", step=step, iteration=iteration, status=status, arn=arn, **fields
    )


def read_entries(project_dir: str, **filters: Any) -> List[Dict[str, Any]]:
    """Return every entry matching `filters` (field == value), in file order (oldest first)."""
    path = run_log_path(project_dir)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        entries = list(_parse_lines(fh))
    return [e for e in entries if all(e.get(k) == v for k, v in filters.items() if v is not None)]


def latest_entry(project_dir: str, **filters: Any) -> Optional[Dict[str, Any]]:
    """The newest entry matching `filters`, or None."""
    entries = read_entries(project_dir, **filters)
    return entries[-1] if entries else None


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _parse_fields(pairs: Iterable[str], fields_json: Optional[str]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if fields_json:
        loaded = json.loads(fields_json)
        if not isinstance(loaded, dict):
            raise RunLogError("--fields-json must be a JSON object")
        fields.update(loaded)
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise RunLogError(f"--field needs key=value, got {pair!r}")
        fields[key] = _parse_value(raw)
    return fields


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Append or list run-log entries.")
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("write", help="append one new entry; prints its id")
    w.add_argument("--project-dir", required=True)
    w.add_argument("--kind", required=True, choices=KINDS)
    w.add_argument("--step", required=True)
    w.add_argument("--iteration", required=True, type=int)
    w.add_argument("--status", required=True)
    w.add_argument("--arn")
    w.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    w.add_argument("--fields-json")

    ls = sub.add_parser("list", help="print matching entries as JSON, oldest first")
    ls.add_argument("--project-dir", required=True)
    ls.add_argument("--id")
    ls.add_argument("--kind")
    ls.add_argument("--step")
    ls.add_argument("--iteration", type=int)
    ls.add_argument("--status")
    ls.add_argument("--latest", action="store_true", help="print only the newest match")

    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            fields = _parse_fields(args.field, args.fields_json)
            entry = _build(args.kind, args.step, args.iteration, args.status, args.arn, fields)
            print(_write(args.project_dir, entry))
            return 0
        entries = read_entries(
            args.project_dir,
            id=args.id,
            kind=args.kind,
            step=args.step,
            iteration=args.iteration,
            status=args.status,
        )
        if args.latest:
            entries = entries[-1:]
        print(json.dumps(entries, indent=2))
        return 0
    except (RunLogError, ValueError) as exc:
        print(f"run_log: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
