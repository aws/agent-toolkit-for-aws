"""
Record-id checks for a review whose answers are joined back to rows on an id.

Auto-labeling folds a review export back onto its review rows by the record id, and
Step 8 applies the feedback to the dataset by the record id, so two rows sharing one
would put a reviewer's answer on the wrong row, or on both. ``ls_space_client.py setup
--id-field`` refuses such records before creating any project, and Step 1 checks the
records with the same function:

    python record_ids.py <records.jsonl> [--id-field id]
    python record_ids.py <records.jsonl> --generic

The first form prints {"missing": [...], "duplicates": [...]} and exits 0 when both are
empty, 1 when not. ``--generic`` is for any input other than auto-labeling's: it picks
the id field (``record_id`` when any row has one, else ``id``, else none), adds it to the
output as ``id_field`` and ``duplicate_rows`` ({id: [1-based row numbers]}), and exits 1
on duplicates, or when some rows have an id and others don't (``missing``). When no row has
an id, every answer joins by its row number instead, so a row number can never be taken
for another row's id.

    python record_ids.py join-check <dataset.jsonl> <feedback.jsonl> [--reviewed <reviewed.jsonl>]

is Step 7's check before the edit plan: it prints {"id_field", "dataset_duplicates",
"dataset_missing", "dataset_duplicate_rows", "feedback_duplicates", "unmatched",
"position_joined"} and exits 1 when either duplicates list is not empty, or when some dataset
rows have an id and others don't (``dataset_missing``: a row number could be taken for an id),
or when ``--reviewed`` (the file a local review was of) and the dataset don't have the same
id field (``reviewed_id_mismatch``: only one has one, or they use different ones).
A feedback row's id is its ``record_id``, or, for a Label Studio export row, the id field
in its ``data``; an export row without one is joined on ``data.unique_id``, the hash
``ls_space_client.py`` gave the record, so dataset rows identical in full show up in
``dataset_duplicates`` under that hash. A local row without an id carries its 1-based row
number as ``record_id`` and joins by position (``position_joined``). ``unmatched`` lists
feedback ids no dataset row has.

Every command exits 2 when a file can't be read. Standard library only, so the Label
Studio client imports it without the SageMaker SDK.
"""

import argparse
import hashlib
import json
import sys
from typing import List, Optional


def record_id_problems(records: List[dict], id_field: str = "id") -> dict:
    """``missing``: the 1-based row numbers with no ``id_field`` value (absent, null, or a
    blank string). ``duplicates``: each value two or more records share, compared as
    strings, as the fold joins them."""
    missing, seen, dups = [], set(), []
    for i, r in enumerate(records, 1):
        v = r.get(id_field) if isinstance(r, dict) else None
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(i)
            continue
        key = str(v)
        if key in seen and key not in dups:
            dups.append(key)
        seen.add(key)
    return {"missing": missing, "duplicates": dups}


def generic_id_field(records: List[dict]) -> Optional[str]:
    """The id field of an input other than auto-labeling's: ``record_id`` when any row has
    that key, else ``id`` when any row has that key, else None (every row is joined by its
    position)."""
    for field in ("record_id", "id"):
        if any(isinstance(r, dict) and field in r for r in records):
            return field
    return None


def duplicate_rows(records: List[dict], id_field: str) -> dict:
    """{id: [the 1-based row numbers of every record with it]} for each id two or more
    records share, compared as strings."""
    rows: dict = {}
    for i, r in enumerate(records, 1):
        v = r.get(id_field) if isinstance(r, dict) else None
        if v is not None and not (isinstance(v, str) and not v.strip()):
            rows.setdefault(str(v), []).append(i)
    return {k: v for k, v in rows.items() if len(v) > 1}


def _feedback_id(row: dict, id_field: Optional[str]):
    """A feedback row's record id: ``record_id`` (local review), or the id field inside a
    Label Studio export row's ``data``."""
    if "record_id" in row:
        return row["record_id"]
    data = row.get("data")
    if isinstance(data, dict) and id_field:
        return data.get(id_field)
    return None


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def record_hash(record: dict) -> str:
    """A record's ``unique_id`` as ``ls_space_client.py`` sets it: the record's own
    ``unique_id`` when it has that key (even blank), else the SHA-256 hex digest of
    ``json.dumps(record, sort_keys=True)``."""
    if "unique_id" in record:
        return str(record["unique_id"])
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def _row_number(key: str, n_rows: int) -> Optional[int]:
    """``key`` as a 1-based row number of a dataset with ``n_rows`` rows, else None."""
    try:
        n = int(key)
    except ValueError:
        return None
    return n if 1 <= n <= n_rows and str(n) == key.strip() else None


def join_problems(
    dataset: List[dict], feedback: List[dict], reviewed: Optional[List[dict]] = None
) -> dict:
    """What Step 8's join would get wrong. A feedback row joins on its record id
    (``record_id``, or the dataset's id field in a Label Studio export row's ``data``);
    an export row without one joins on ``data.unique_id``, compared with each dataset
    row's ``record_hash``. ``dataset_duplicates``: ids (or hashes, for rows identical
    in full) two or more dataset rows share. ``dataset_missing``: the 1-based dataset rows
    without an id when other rows have one. ``reviewed_id_mismatch``: the reviewed file
    (``reviewed``) and the dataset don't have the same id field (only one has one, or they
    use different ones: ``id`` and ``record_id``), and local rows came back: a ``record_id``
    (a row number, or the other file's id) then can't name a dataset row. ``feedback_duplicates``: ids two or more
    feedback rows share, such as rows left from an earlier review. ``unmatched``:
    feedback ids no dataset row has. ``position_joined``: the 1-based row numbers that
    local rows without an id join by position (their ``record_id`` is the row number,
    and that dataset row has no id). All compared as strings."""
    id_field = generic_id_field(dataset)
    dataset_report = (
        record_id_problems(dataset, id_field) if id_field else {"missing": [], "duplicates": []}
    )
    dataset_dups = dataset_report["duplicates"]
    dup_rows = duplicate_rows(dataset, id_field) if id_field else {}
    dataset_ids = {
        str(r[id_field])
        for r in dataset
        if id_field and isinstance(r, dict) and r.get(id_field) is not None
    }
    hash_rows: dict = {}
    seen, feedback_dups, unmatched, position_joined = set(), [], [], []
    for row in feedback:
        if not isinstance(row, dict):
            continue
        v = _feedback_id(row, id_field)
        by_hash = False
        if _blank(v):
            data = row.get("data")
            v = data.get("unique_id") if isinstance(data, dict) else None
            if _blank(v):
                continue
            by_hash = True
            if not hash_rows:
                for i, r in enumerate(dataset, 1):
                    if isinstance(r, dict):
                        hash_rows.setdefault(record_hash(r), []).append(i)
        key = str(v)
        if key in seen and key not in feedback_dups:
            feedback_dups.append(key)
        if not by_hash and "record_id" in row and key not in dataset_ids:
            # a local row without an id carries its 1-based row number: it joins by position
            n = _row_number(key, len(dataset))
            if n and not (
                id_field
                and isinstance(dataset[n - 1], dict)
                and not _blank(dataset[n - 1].get(id_field))
            ):
                if n not in position_joined:
                    position_joined.append(n)
                seen.add(key)
                continue
            if key not in unmatched:
                unmatched.append(key)
        elif by_hash:
            rows = hash_rows.get(key, [])
            if not rows and key not in unmatched:
                unmatched.append(key)
            if len(rows) > 1 and key not in dataset_dups:
                dataset_dups.append(key)
                dup_rows[key] = rows
        elif id_field and key not in dataset_ids and key not in unmatched:
            unmatched.append(key)
        seen.add(key)
    reviewed_id_mismatch = bool(
        reviewed is not None
        and generic_id_field(reviewed) != id_field
        and any(isinstance(r, dict) and "record_id" in r for r in feedback)
    )
    return {
        "id_field": id_field,
        "dataset_duplicates": dataset_dups,
        "reviewed_id_mismatch": reviewed_id_mismatch,
        "dataset_missing": dataset_report["missing"],
        "dataset_duplicate_rows": dup_rows,
        "feedback_duplicates": feedback_dups,
        "unmatched": unmatched,
        "position_joined": sorted(position_joined),
    }


def _read(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["join-check"]:
        p = argparse.ArgumentParser(
            prog="record_ids.py join-check",
            description="Check that Step 8 can join the feedback to the dataset by record id.",
        )
        p.add_argument("dataset", help="a local JSONL file of the dataset Step 8 edits")
        p.add_argument(
            "feedback",
            help="the local feedback file (local review feedback or Label Studio export)",
        )
        p.add_argument(
            "--reviewed",
            help="local review: the file that was reviewed (Step 1's copy for S3 or "
            "a DataSet), so row numbers can be told apart from ids",
        )
        args = p.parse_args(argv[1:])
        try:
            dataset, feedback = _read(args.dataset), _read(args.feedback)
            reviewed = _read(args.reviewed) if args.reviewed else None
        except (OSError, ValueError) as e:
            print(json.dumps({"error": f"could not read the files: {e}"}), file=sys.stderr)
            return 2
        problems = join_problems(dataset, feedback, reviewed)
        print(json.dumps(problems))
        return (
            1
            if (
                problems["dataset_duplicates"]
                or problems["dataset_missing"]
                or problems["feedback_duplicates"]
                or problems["reviewed_id_mismatch"]
            )
            else 0
        )

    p = argparse.ArgumentParser(
        description="Check that every record has an id no other record shares.",
        epilog="Also: record_ids.py join-check <dataset.jsonl> <feedback.jsonl> "
        "(Step 7: can the feedback be joined to the dataset by record id?)",
    )
    p.add_argument("records", help="a local JSONL file of the records")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--id-field", help="the record id field (default: id)")
    mode.add_argument(
        "--generic",
        action="store_true",
        help="input other than auto-labeling's: pick the id field; fail on duplicates, "
        "or when only some rows have an id",
    )
    args = p.parse_args(argv)
    try:
        records = _read(args.records)
    except (OSError, ValueError) as e:
        print(json.dumps({"error": f"could not read {args.records}: {e}"}), file=sys.stderr)
        return 2
    if args.generic:
        field = generic_id_field(records)
        problems = (
            record_id_problems(records, field) if field else {"missing": [], "duplicates": []}
        )
        print(
            json.dumps(
                {
                    "id_field": field,
                    **problems,
                    "duplicate_rows": duplicate_rows(records, field) if field else {},
                }
            )
        )
        return 1 if problems["duplicates"] or problems["missing"] else 0
    problems = record_id_problems(records, args.id_field or "id")
    print(json.dumps(problems))
    return 1 if problems["missing"] or problems["duplicates"] else 0


if __name__ == "__main__":
    sys.exit(main())
