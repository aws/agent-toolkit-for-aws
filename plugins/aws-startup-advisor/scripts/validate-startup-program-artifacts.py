#!/usr/bin/env python3
"""Validate startup-program artifacts match preferences.json startup_program_status.

Prevents inferring AWS Activate Founders vs Portfolio when Q27 was skipped or
startup_program_status is unknown.

Usage:
  python3 validate-startup-program-artifacts.py --migration-dir /path/to/.migration/RUN_ID
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Phrases that imply a confirmed tier — forbidden when status is unknown.
FORBIDDEN_WHEN_UNKNOWN = [
    re.compile(r"your\s+status:\s*eligible", re.IGNORECASE),
    re.compile(r"\beligible\s+founders\s+tier\b", re.IGNORECASE),
    re.compile(r"\beligible\s+for\s+up\s+to\s+\$5k\s+aws\s+activate\b", re.IGNORECASE),
    re.compile(r"\bactivate\s+portfolio\s+credits\s+eligibility\b", re.IGNORECASE),
    re.compile(r"\*\*your\s+status:\s*eligible_founders\*\*", re.IGNORECASE),
    re.compile(r"\*\*your\s+status:\s*eligible_portfolio\*\*", re.IGNORECASE),
]

ACTIVATE_APPLY_URL = "https://aws.amazon.com/startups/credits/"
ACTIVATE_LINK_RE = re.compile(r'href=["\']https?://aws\.amazon\.com/startups/credits/?["\']', re.IGNORECASE)
ACTIVATE_MENTION_RE = re.compile(r"\baws\s+activate\b", re.IGNORECASE)


# preferences.json blocks that may carry startup_program_status. Canonical home is
# startup_constraints (see schema-preferences.md "startup_constraints optional (Q27)"),
# but tolerate ai_constraints / design_constraints so a producer-side placement change
# can never silently disable this gate. Search ALL blocks — never short-circuit on the
# first truthy block (a truthy design_constraints without the key must not stop the search).
_STATUS_BLOCKS = ("startup_constraints", "ai_constraints", "design_constraints")


def _load_status(migration_dir: Path) -> tuple[str | None, dict | None]:
    prefs_path = migration_dir / "preferences.json"
    if not prefs_path.is_file():
        return None, None
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    for block_name in _STATUS_BLOCKS:
        block = (prefs.get(block_name) or {}).get("startup_program_status")
        if isinstance(block, dict):
            value = block.get("value")
            if isinstance(value, list):
                value = value[0] if value else None
            return value, prefs
    return None, prefs


def validate_startup_artifacts(migration_dir: Path) -> list[str]:
    errors: list[str] = []
    status, _prefs = _load_status(migration_dir)
    if status is None:
        return errors  # no preferences — nothing to enforce

    if status != "unknown":
        return errors

    texts: list[tuple[str, str]] = []
    for name in ("STARTUP_PROGRAMS.md", "migration-report.html"):
        path = migration_dir / name
        if path.is_file():
            texts.append((name, path.read_text(encoding="utf-8")))

    ai_startup = migration_dir / "ai-migration" / "STARTUP_PROGRAMS.md"
    if ai_startup.is_file():
        texts.append((str(ai_startup.relative_to(migration_dir)), ai_startup.read_text(encoding="utf-8")))

    for label, content in texts:
        for pattern in FORBIDDEN_WHEN_UNKNOWN:
            if pattern.search(content):
                errors.append(
                    f'{label}: startup_program_status is "unknown" but content implies a '
                    f"confirmed Activate tier ({pattern.pattern})"
                )
                break

        if ACTIVATE_MENTION_RE.search(content) and not ACTIVATE_LINK_RE.search(content):
            # Plain URLs count for markdown files
            if ACTIVATE_APPLY_URL not in content:
                errors.append(
                    f"{label}: mentions AWS Activate but has no clickable link to "
                    f"{ACTIVATE_APPLY_URL} — add <a href=\"...\"> in HTML or [text](url) in Markdown"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate startup program artifact honesty")
    parser.add_argument(
        "--migration-dir",
        type=Path,
        required=True,
        help="Migration output directory containing preferences.json",
    )
    args = parser.parse_args()

    if not args.migration_dir.is_dir():
        print(f"STARTUP_FAIL | reason=not_a_directory | path={args.migration_dir}", file=sys.stderr)
        return 1

    errors = validate_startup_artifacts(args.migration_dir)
    if errors:
        print("STARTUP_FAIL | startup-program-artifacts", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("STARTUP_OK | startup_program_status aligned with artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
