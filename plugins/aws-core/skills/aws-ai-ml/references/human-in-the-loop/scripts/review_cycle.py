#!/usr/bin/env python3
"""Keep a local review from mixing with an earlier review in the same project directory.

Local review writes its answers to the fixed path
``<project-dir>/data/hil/local_review_feedback.jsonl`` and appends to it, and the cycle's
metadata goes to the fixed ``manifests/human-in-the-loop.json``. A second review in the
same project directory would append to the first one's answers and overwrite its metadata, so a new
review goes into a new project directory. The skill runs ``begin`` when the user picks local
review at the Step 2 checkpoint (before the mode is saved) and on every resume:

    python review_cycle.py begin --project-dir <dir> --data-file <path, S3 URI or ARN> [--adopt]

``begin`` prints {"state", "cycle_number", "data_file", "earlier_data_file", "changed",
"feedback_rows", "finished", "existing"}. ``existing`` lists a cycle's outputs
(``CYCLE_OUTPUTS``, ``ls_setup_relabel_*.json`` and ``labels.before_hil.*.jsonl``) in
``data/hil/``. ``finished`` is true when the review was completed: Step 8's
``updated_dataset.jsonl`` is there, or a ``labels.before_hil.<n>.jsonl`` backup (auto-labeling
input, whose Step 8 output is moved onto ``labels.jsonl``), or the HIL log has a completed
``hil-export`` hand-back entry (every auto-labeling input). Step 1's copy of the input
(``review_records.jsonl``) doesn't count: the current review writes it before ``begin``
runs, so it holds the current review's rows.

- ``new`` (exit 0): no cycle outputs. It records the data file in the manifest as
  ``human_in_the_loop.local_review_data_file`` (with ``local_review_data_sha256``, the
  SHA-256 of a local file's bytes, null for S3 or an ARN) and ``cycle_number`` (1 when
  unset).
- ``resume`` (exit 3): an unfinished local review of the same data file. A local file
  must also have the recorded SHA-256.
- ``unrecorded`` (exit 3): cycle outputs whose data file was never recorded: a Label Studio
  review, or a local review started before this check. With ``--adopt`` (after the user
  confirmed it is a review of this data file), it records the data file as ``new`` does and
  reports ``resume`` with ``adopted`` true, unless Label Studio outputs are among them or
  the review was finished. Then it stays ``unrecorded`` and writes nothing.
- ``earlier_cycle`` (exit 3): a review of another data file, a finished one, one with
  Label Studio outputs (a Label Studio cycle followed the recorded local review), or one
  of a local file whose bytes have changed since, or that can't be checked because no
  SHA-256 was recorded or the file is now missing (``changed`` true).

Only ``new`` and ``--adopt`` write anything. Exit 2: the manifest or a file can't be read.

Stdlib only.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from typing import List, Optional

FEEDBACK = "local_review_feedback.jsonl"
STEP8_OUTPUT = "updated_dataset.jsonl"
HIL_LOG = "hil-log.jsonl"
# A cycle's outputs under data/hil/ (plus ls_setup_relabel_*.json); the HIL log is not one.
CYCLE_OUTPUTS = (
    FEEDBACK,
    STEP8_OUTPUT,
    "annotation_summary.json",
    "discarded_rows.jsonl",
    "label_studio_export.jsonl",
    "ls_setup.json",
)
# Outputs only a Label Studio cycle writes (plus ls_setup_relabel_*.json).
LS_OUTPUTS = ("label_studio_export.jsonl", "ls_setup.json")
MANIFEST = os.path.join("manifests", "human-in-the-loop.json")


def _hil_dir(project_dir: str) -> str:
    return os.path.join(project_dir, "data", "hil")


def _manifest_path(project_dir: str) -> str:
    return os.path.join(project_dir, MANIFEST)


def _read_manifest(project_dir: str) -> dict:
    path = _manifest_path(project_dir)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_manifest(project_dir: str, manifest: dict) -> None:
    path = _manifest_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _is_remote(path: str) -> bool:
    return "://" in path or path.startswith("arn:")


def _same_file(a: Optional[str], b: str) -> bool:
    """Same data file: S3 URIs and ARNs compared as given, local paths after resolving."""
    if not a:
        return False
    if _is_remote(a) or _is_remote(b):
        return a == b
    return os.path.realpath(a) == os.path.realpath(b)


def _sha256(path: str) -> Optional[str]:
    """The SHA-256 of a local file's bytes; None for S3, an ARN or a missing file."""
    if _is_remote(path) or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _count_rows(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _cycle_files(hil_dir: str) -> List[str]:
    names = [name for name in CYCLE_OUTPUTS if os.path.exists(os.path.join(hil_dir, name))]
    for pattern in ("ls_setup_relabel_*.json", "labels.before_hil.*.jsonl"):
        names += sorted(os.path.basename(p) for p in glob.glob(os.path.join(hil_dir, pattern)))
    return names


def _handed_back(hil_dir: str) -> bool:
    """True when the HIL log has a completed ``hil-export`` artifact entry (the hand-back)."""
    path = os.path.join(hil_dir, HIL_LOG)
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:  # blank or unreadable line: skipped, as hil_log.py does
                continue
            if (
                isinstance(entry, dict)
                and entry.get("kind") == "artifact"
                and entry.get("status") == "completed"
                and entry.get("artifact") == "hil-export"
            ):
                return True
    return False


def _record(
    project_dir: str, manifest: dict, hil: dict, data_file: str, digest: Optional[str]
) -> None:
    hil["local_review_data_file"] = data_file
    hil["local_review_data_sha256"] = digest
    hil.setdefault("cycle_number", 1)
    manifest["human_in_the_loop"] = hil
    _write_manifest(project_dir, manifest)


def begin(project_dir: str, data_file: str, adopt: bool = False) -> dict:
    hil_dir = _hil_dir(project_dir)
    existing = _cycle_files(hil_dir)
    manifest = _read_manifest(project_dir)
    hil = manifest.get("human_in_the_loop") or {}
    earlier = hil.get("local_review_data_file")
    digest = _sha256(data_file)
    finished = (
        STEP8_OUTPUT in existing
        or any(f.startswith("labels.before_hil.") for f in existing)
        or _handed_back(hil_dir)
    )
    label_studio = any(f in LS_OUTPUTS or f.startswith("ls_setup_relabel_") for f in existing)
    # a local file must match the SHA-256 recorded for it: one recorded without a SHA-256, or now
    # missing, can't be shown unchanged, so it counts as changed (S3 and ARNs have none on both sides)
    changed = bool(
        earlier and _same_file(earlier, data_file) and digest != hil.get("local_review_data_sha256")
    )
    out = {
        "data_file": data_file,
        "earlier_data_file": earlier,
        "changed": changed,
        "feedback_rows": (
            _count_rows(os.path.join(hil_dir, FEEDBACK)) if FEEDBACK in existing else 0
        ),
        "finished": finished,
        "existing": existing,
    }
    if not existing:
        _record(project_dir, manifest, hil, data_file, digest)
        return {"state": "new", "cycle_number": hil["cycle_number"], **out}
    if not earlier and adopt and not label_studio and not finished:
        _record(project_dir, manifest, hil, data_file, digest)
        return {"state": "resume", "adopted": True, "cycle_number": hil["cycle_number"], **out}
    if not earlier:
        state = "unrecorded"
    elif not finished and not changed and not label_studio and _same_file(earlier, data_file):
        state = "resume"
    else:
        state = "earlier_cycle"
    return {"state": state, "cycle_number": hil.get("cycle_number", 1), **out}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Check a project directory for an earlier review before a local review."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("begin", help="check the project directory before a local review starts")
    b.add_argument("--project-dir", required=True)
    b.add_argument(
        "--data-file",
        required=True,
        help="the file being reviewed, as the user gave it (local path, S3 URI or DataSet ARN)",
    )
    b.add_argument(
        "--adopt",
        action="store_true",
        help="for an unrecorded review the user confirmed is of this file: record the file",
    )
    args = p.parse_args(argv)
    try:
        out = begin(args.project_dir, args.data_file, adopt=args.adopt)
        print(json.dumps(out))
        return 0 if out["state"] == "new" else 3
    except (OSError, ValueError) as e:
        print(json.dumps({"error": f"could not read the project directory: {e}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
