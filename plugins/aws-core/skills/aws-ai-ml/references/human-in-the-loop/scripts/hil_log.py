#!/usr/bin/env python3
"""The HIL log: the only code that appends to `<project-dir>/data/hil/hil-log.jsonl`.

The human-in-the-loop skill records four things here, so that a later command (or a
resumed session) can check them:

- `approval`: a decision the user gave (the bucket owner at Step 1, the Step 7 edit
  plan with `discarded_unique_ids`). Written by the agent through the command line.
- `analysis` with `check: s3-export-destination`: an `s3-check` result, which
  `export --s3-uri` requires before it uploads.
- `artifact` with `artifact: relabel-round`: a relabel round's setup output.
- `artifact` with `artifact: hil-export`: the export handed back to auto-labeling
  (`export_path`, `review_mode`), for auto-labeling's next step.

Each entry is one JSON object on one line. The file is append-only: a line is never
rewritten, and the file is never truncated or reordered. Every entry carries `kind`,
`step`, `iteration`, `created_at` (UTC) and `status`. The writer also sets `id`,
derived from those fields and unique within the file; an entry is referred to by its
`id`. Paths inside the project directory are stored relative to it. Each line is
appended under an exclusive file lock, so writers running at the same time never
interleave lines or reuse an `id`.

Command line (the agent)::

    python hil_log.py write --project-dir <dir> --kind approval \\
        --step human-in-the-loop-edit-plan --iteration 0 --status approved \\
        --fields-json '{"discarded_unique_ids": ["r1", "r7"]}'
    python hil_log.py list --project-dir <dir> --kind approval
    python hil_log.py list --project-dir <dir> --id <id> --get discarded_rows

`write` prints the new entry's `id`. `--field key=value` parses `value` as JSON when it
can and keeps it as a string otherwise (so `--field bucket=123` stores a number: pass
string values through `--fields-json`); `--fields-json '{...}'` passes several fields at
once (`-` reads them from stdin). `write` exits 2 and writes nothing on invalid fields.
`list --get DOTTED` prints one field of the single match (`--id`, or the newest with
`--latest`) as JSON; it exits 1 when no entry matches or the entry lacks the field, and 2
when several entries match without `--latest`.

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

HIL_LOG_FILE = os.path.join("data", "hil", "hil-log.jsonl")

KINDS = ("approval", "analysis", "artifact")
REQUIRED = ("kind", "step", "iteration", "created_at", "status")
RESERVED = REQUIRED + ("id",)

_SLUG = re.compile(r"[^a-z0-9]+")


class HilLogError(ValueError):
    """An entry is missing a required field or has an invalid value."""


def _slug(value: Any) -> str:
    return _SLUG.sub("-", str(value).lower()).strip("-") or "x"


def resolve_project_dir(project_dir: str) -> str:
    """The absolute project directory, symlinks resolved; paths in entries are relative to it."""
    return os.path.realpath(project_dir)


def hil_log_path(project_dir: str) -> str:
    """Path of the project's `hil-log.jsonl`."""
    return os.path.join(resolve_project_dir(project_dir), HIL_LOG_FILE)


def _relativize(value: Any, root: str) -> Any:
    """Store absolute paths that point inside the project relative to the project directory."""
    if isinstance(value, dict):
        return {k: _relativize(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_relativize(v, root) for v in value]
    if not isinstance(value, str) or "://" in value or not os.path.isabs(value):
        return value
    candidate = os.path.realpath(value)  # resolve symlinks, as resolve_project_dir does
    if candidate == root or candidate.startswith(root + os.sep):
        return os.path.relpath(candidate, root)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate(entry: Dict[str, Any]) -> None:
    for key in REQUIRED:
        if entry.get(key) in (None, ""):
            raise HilLogError(f"HIL log entry needs `{key}`")
    if entry["kind"] not in KINDS:
        raise HilLogError(f"`kind` must be one of {', '.join(KINDS)}, not {entry['kind']!r}")
    iteration = entry["iteration"]
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        raise HilLogError("`iteration` must be a non-negative integer (0 outside a loop)")


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
    """Hold an exclusive lock on the open log file."""
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
    entry = {k: _relativize(v, root) for k, v in entry.items()}
    entry.setdefault("created_at", _now())
    _validate(entry)
    path = hil_log_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
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
            line = json.dumps({"id": entry_id, **entry}, default=str)
            # A line cut short by an interrupted writer stays as it is; the new line starts fresh.
            prefix = "\n" if text and not text.endswith("\n") else ""
            fh.write(prefix + line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry_id


def _build(kind, step, iteration, status, fields) -> Dict[str, Any]:
    clash = sorted(set(fields) & set(RESERVED))
    if clash:
        raise HilLogError(
            f"{', '.join(clash)} cannot be a field: pass kind, step, iteration and status as "
            "their own flags; the writer sets id and created_at"
        )
    return {"kind": kind, "step": step, "iteration": iteration, "status": status, **fields}


def write_entry(
    project_dir: str, *, kind: str, step: str, iteration: int, status: str, **fields: Any
) -> str:
    """Append one new entry and return its `id`.

    Code never records an approval: `kind="approval"` is refused here and is
    written by the agent through the command line after the user gives it.
    """
    if kind == "approval":
        raise HilLogError(
            "approvals come from the user; the agent records them with the hil_log.py CLI"
        )
    return _write(project_dir, _build(kind, step, iteration, status, fields))


def read_entries(project_dir: str, **filters: Any) -> List[Dict[str, Any]]:
    """Return every entry matching `filters` (field == value), in file order (oldest first)."""
    path = hil_log_path(project_dir)
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
        text = sys.stdin.read() if fields_json == "-" else fields_json
        if not text.strip():
            raise HilLogError("--fields-json -: stdin is empty; pipe the fields object in")
        try:
            loaded = json.loads(text)
        except ValueError as exc:
            raise HilLogError(f"--fields-json is not JSON ({exc})") from None
        if not isinstance(loaded, dict):
            raise HilLogError("--fields-json must be a JSON object")
        fields.update(loaded)
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise HilLogError(f"--field needs key=value, got {pair!r}")
        fields[key] = _parse_value(raw)
    return fields


def _get_dotted(entry: Dict[str, Any], dotted: str) -> Any:
    """The field of `entry` at a dotted path (a numeric segment indexes a list); KeyError if absent."""
    cur: Any = entry
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            raise KeyError(dotted)
    return cur


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Append or list HIL log entries.")
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("write", help="append one new entry; prints its id")
    w.add_argument("--project-dir", required=True)
    w.add_argument("--kind", required=True, choices=KINDS)
    w.add_argument("--step", required=True)
    w.add_argument("--iteration", required=True, type=int)
    w.add_argument("--status", required=True)
    w.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    w.add_argument(
        "--fields-json", metavar="JSON", help="a JSON object of fields; `-` reads it from stdin"
    )

    ls = sub.add_parser("list", help="print matching entries as JSON, oldest first")
    ls.add_argument("--project-dir", required=True)
    ls.add_argument("--id")
    ls.add_argument("--kind")
    ls.add_argument("--step")
    ls.add_argument("--iteration", type=int)
    ls.add_argument("--status")
    ls.add_argument("--latest", action="store_true", help="print only the newest match")
    ls.add_argument(
        "--get",
        metavar="DOTTED",
        help="print only this dotted field of the single match (with --id, or the newest "
        "with --latest) as JSON; exits 1 when no entry matches or the field is absent, "
        "2 when several match without --latest",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            entry = _build(
                args.kind,
                args.step,
                args.iteration,
                args.status,
                _parse_fields(args.field, args.fields_json),
            )
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
        if args.get:
            if len(entries) > 1:
                print(
                    f"hil_log: --get: {len(entries)} entries match; narrow them with --id or pass --latest",
                    file=sys.stderr,
                )
                return 2
            if not entries:
                print("hil_log: --get: no entry matches", file=sys.stderr)
                return 1
            try:
                value = _get_dotted(entries[0], args.get)
            except KeyError:
                print(
                    f"hil_log: --get: entry {entries[0].get('id')} has no `{args.get}`",
                    file=sys.stderr,
                )
                return 1
            print(json.dumps(value, indent=2))
            return 0
        print(json.dumps(entries, indent=2))
        return 0
    except ValueError as exc:  # HilLogError is a ValueError
        print(f"hil_log: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
