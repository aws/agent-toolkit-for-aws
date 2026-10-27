#!/usr/bin/env python3
"""Resolve the GCP ai_track state from the first-pass classifier output and the sibling skill.

Read-only unless ``--write-run-dir`` is given. Never spawns a process and never
invokes another skill. Consumes the first-pass ``bma-route-classifier.py classify``
JSON (no ``--bma-base``) and prints one canonical JSON line on stdout:

  ai_track=not_applicable  no AI evidence; the sibling is never stat'ed        exit 0
  ai_track=active          sibling present; caller runs the second classifier
                           pass with --bma-base exactly as before               exit 0
  ai_track=deferred        sibling missing but infrastructure input exists;
                           the infrastructure migration proceeds and the AI
                           track is deferred with warning_code
                           deferred_shared_ai_engine                            exit 0
  AI_TRACK_FAIL | code=bedrock_migration_assessment_missing_ai_only | ...
                           sibling missing and no infrastructure input (AI-only
                           repository): nothing can proceed; stderr, stdout empty  exit 1
  usage / path errors                                                           exit 2

A present-but-tampered sibling is NOT a deferral case: the resolver reports
``active`` and the classifier's second pass still fails closed with
``BMA_STANDALONE_CLOSURE_INVALID``. The sibling check mirrors
``bma-route-classifier.py::validate_closure``: ``<skill-base>/../bedrock-migration-assessment/SKILL.md``
must be a regular, non-symlink file whose frontmatter has
``name: bedrock-migration-assessment``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
MISSING_SKILL = "bedrock-migration-assessment"
WARNING_CODE = "deferred_shared_ai_engine"
INSTALL_HINT = (
    "npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills "
    f"--skill {MISSING_SKILL}"
)
RECORD_NAME = "ai-track.json"
RESUME_ARTIFACTS = ("gcp-resource-inventory.json", "billing-profile.json", "live-capture/manifest.json")
AI_ONLY_DETAIL = (
    "This repository has AI evidence and no infrastructure input; the AI assessment is performed "
    f"by the {MISSING_SKILL} skill, which is not installed beside gcp-to-aws. "
    f"Install it with: {INSTALL_HINT} and rerun."
)


class UsageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def sibling_present(skill_base: Path) -> tuple[bool, Path]:
    root = skill_base.parent / MISSING_SKILL
    skill = root / "SKILL.md"
    if not _regular(skill):
        return False, root
    try:
        frontmatter = skill.read_text(encoding="utf-8").split("---", 2)
    except (OSError, UnicodeDecodeError):
        return False, root
    if len(frontmatter) < 3 or f"\nname: {MISSING_SKILL}\n" not in "\n" + frontmatter[1] + "\n":
        return False, root
    return True, root


def infrastructure_evidence(classification: dict, resume_dir: Path | None) -> list[str]:
    inventory = classification.get("inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    evidence = [key for key in ("terraform", "billing") if inventory.get(key)]
    if resume_dir is not None and any(_regular(resume_dir / name) for name in RESUME_ARTIFACTS):
        evidence.append("resume_artifacts")
    return evidence


def resolve(skill_base: Path, classification: dict, resume_dir: Path | None) -> dict:
    """Return the ai_track record, or raise UsageError for the AI-only + missing case."""
    if not classification.get("AI_CANDIDATE"):
        return {"schema_version": SCHEMA_VERSION, "ai_track": "not_applicable", "reason": "no_ai_evidence"}
    present, root = sibling_present(skill_base)
    if present:
        return {
            "schema_version": SCHEMA_VERSION,
            "ai_track": "active",
            "reason": "bedrock_migration_assessment_present",
            "bma_base": str(root.resolve()),
        }
    evidence = infrastructure_evidence(classification, resume_dir)
    if not evidence:
        raise UsageError("bedrock_migration_assessment_missing_ai_only")
    signal_files = classification.get("ai_signal_files")
    return {
        "schema_version": SCHEMA_VERSION,
        "ai_track": "deferred",
        "reason": "bedrock_migration_assessment_missing",
        "missing_skill": MISSING_SKILL,
        "infrastructure_evidence": evidence,
        "warning_code": WARNING_CODE,
        "install_hint": INSTALL_HINT,
        "ai_signal_files": signal_files if isinstance(signal_files, list) else [],
    }


def _load_classification(source: str) -> dict:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise UsageError("classification_unreadable") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise UsageError("classification_invalid")
    return value


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill-base", type=Path, required=True, help="absolute path of the gcp-to-aws skill root")
    parser.add_argument("--classification", required=True, help="first-pass classifier JSON file, or - for stdin")
    parser.add_argument("--resume-dir", type=Path, default=None, help="the selected resume run directory, if any")
    parser.add_argument("--write-run-dir", type=Path, default=None, help=f"write <dir>/{RECORD_NAME}")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.skill_base.is_absolute() or not args.skill_base.is_dir() or args.skill_base.is_symlink():
            raise UsageError("path_invalid")
        if args.resume_dir is not None and (not args.resume_dir.is_dir() or args.resume_dir.is_symlink()):
            raise UsageError("path_invalid")
        if args.write_run_dir is not None and (not args.write_run_dir.is_dir() or args.write_run_dir.is_symlink()):
            raise UsageError("path_invalid")
        result = resolve(args.skill_base, _load_classification(args.classification), args.resume_dir)
        if args.write_run_dir is not None:
            target = args.write_run_dir / RECORD_NAME
            if target.is_symlink():
                raise UsageError("path_invalid")
            target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except UsageError as exc:
        if exc.code == "bedrock_migration_assessment_missing_ai_only":
            print(
                f"AI_TRACK_FAIL | code={exc.code} | missing_skill={MISSING_SKILL} | detail={AI_ONLY_DETAIL}",
                file=sys.stderr,
            )
            return 1
        print(f"AI_TRACK_FAIL | code={exc.code}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"AI_TRACK_FAIL | code=io_error | detail={exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
