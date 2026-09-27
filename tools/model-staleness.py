#!/usr/bin/env python3
"""model-staleness.py — surface a stale Bedrock model-lifecycle registry.

WHY: the design/estimate phases pick Bedrock models against a vendored
`ai-model-lifecycle.md` registry (the Active/Legacy/EOL table + the 90-day
exclusion rule). That registry declares a freshness contract at the top of the
file — a `**Last updated:** YYYY-MM-DD` line and a `**Staleness window:** N days`
line — but nothing enforced it. A registry that quietly crosses its own window
silently degrades every model recommendation: a model can move Active -> Legacy
-> gone in as little as a 45-day Legacy period (see the file), so a snapshot
older than that window can recommend a model that is already Legacy or EOL.

This check reads each canonical registry's OWN declared date and window and
reports drift. It also verifies that every vendored copy
(`references/vendored/ai/ai-model-lifecycle.md`) is byte-identical to its
canonical `skills/shared/ai/ai-model-lifecycle.md` — the discipline the file
documents but that otherwise has no gate in this repo.

This is the model-registry sibling of the pricing freshness idea: pricing has a
cache with `_meta.last_updated`; the model registry now has the same contract.

Modes:
    python3 tools/model-staleness.py            # report; ALWAYS exit 0 (safe in
                                                # `build` — a stale registry must
                                                # not fail unrelated PRs)
    python3 tools/model-staleness.py --strict   # exit 1 on staleness OR a
                                                # drifted vendored copy (for the
                                                # scheduled freshness workflow)
    python3 tools/model-staleness.py --plugin aws-startup-advisor

Stdlib only. Matches tools/validate.py and tools/sync-plugin-skills.py.
"""
from __future__ import annotations

import argparse
import filecmp
import re
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"

DEFAULT_WINDOW_DAYS = 45
CANONICAL_GLOB = "skills/shared/ai/ai-model-lifecycle.md"
VENDORED_GLOB = "skills/*/references/vendored/ai/ai-model-lifecycle.md"

LAST_UPDATED_RE = re.compile(r"^\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
WINDOW_RE = re.compile(r"^\*\*Staleness window:\*\*\s*(\d+)\s*days?\s*$", re.MULTILINE)


def days_since(iso_date: str) -> int:
    then = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return (date.today() - then).days


def parse_contract(path: Path) -> tuple[str | None, int]:
    """Return (last_updated_iso_or_None, window_days) declared in a registry file."""
    text = path.read_text(encoding="utf-8")
    m_date = LAST_UPDATED_RE.search(text)
    m_win = WINDOW_RE.search(text)
    last_updated = m_date.group(1) if m_date else None
    window = int(m_win.group(1)) if m_win else DEFAULT_WINDOW_DAYS
    return last_updated, window


def check_plugin(plugin_dir: Path, strict: bool) -> tuple[list[str], list[str]]:
    """Check one plugin's model registry. Returns (failures, notes)."""
    failures: list[str] = []
    notes: list[str] = []

    canonicals = sorted(plugin_dir.glob(CANONICAL_GLOB))
    if not canonicals:
        # Plugin ships no model-lifecycle registry — nothing to gate.
        return failures, notes

    for canonical in canonicals:
        rel = canonical.relative_to(REPO_ROOT)
        last_updated, window = parse_contract(canonical)

        if last_updated is None:
            failures.append(
                f"{rel}: no '**Last updated:** YYYY-MM-DD' line — cannot enforce freshness."
            )
        else:
            age = days_since(last_updated)
            stale_by = age - window
            if stale_by > 0:
                failures.append(
                    f"{rel}: STALE — last updated {last_updated} ({age}d ago), "
                    f"window {window}d, over by {stale_by}d. "
                    f"Refresh the registry against the Bedrock model lifecycle page and bump 'Last updated'."
                )
            else:
                notes.append(
                    f"{rel}: fresh — {age}d old (window {window}d, {-stale_by}d of headroom)."
                )

        # Every vendored copy must be byte-identical to this canonical file.
        for vendored in sorted(plugin_dir.glob(VENDORED_GLOB)):
            if not filecmp.cmp(canonical, vendored, shallow=False):
                failures.append(
                    f"{vendored.relative_to(REPO_ROOT)}: DRIFTED from canonical {rel} — "
                    f"copy the canonical file over it (they must stay byte-identical)."
                )

    return failures, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="exit 1 when stale or drifted")
    ap.add_argument("--plugin", help="check a single plugin by directory name")
    args = ap.parse_args()

    if not PLUGINS_ROOT.is_dir():
        print("No plugins/ directory found.", file=sys.stderr)
        return 0

    if args.plugin:
        plugin_dirs = [PLUGINS_ROOT / args.plugin]
    else:
        plugin_dirs = [p for p in sorted(PLUGINS_ROOT.iterdir()) if p.is_dir()]

    all_failures: list[str] = []
    all_notes: list[str] = []
    for plugin_dir in plugin_dirs:
        if not plugin_dir.is_dir():
            print(f"Plugin not found: {plugin_dir}", file=sys.stderr)
            return 2
        failures, notes = check_plugin(plugin_dir, args.strict)
        all_failures.extend(failures)
        all_notes.extend(notes)

    for note in all_notes:
        print(f"  ok: {note}")
    for failure in all_failures:
        print(f"  {'ERROR' if args.strict else 'WARN'}: {failure}", file=sys.stderr)

    if all_failures:
        if args.strict:
            print(f"\nmodel-staleness: {len(all_failures)} problem(s) — failing (--strict).", file=sys.stderr)
            return 1
        print(f"\nmodel-staleness: {len(all_failures)} problem(s) — warn-only (pass --strict to fail).")
        return 0

    print("\nmodel-staleness: all model registries fresh and in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
