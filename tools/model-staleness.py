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

Two failure classes, gated differently:
    - Drift (a vendored copy that differs from canonical) and a missing /
      malformed freshness contract are correctness problems — the repo is
      inconsistent right now. They fail ALWAYS (with or without --strict), so
      the PR/build path catches them.
    - Staleness (the snapshot aged past its window) is time-based. It fails
      ONLY under --strict (the weekly job) and stays warn-only otherwise, so a
      registry that quietly aged out does not sink unrelated PRs.

Modes:
    python3 tools/model-staleness.py            # PR/build: exit 1 on drift or a
                                                # malformed contract; staleness is
                                                # warn-only (exit 0)
    python3 tools/model-staleness.py --strict   # weekly: ALSO exit 1 on staleness
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


class Findings:
    """Two classes of problem, gated differently.

    - hard: the repo is internally inconsistent RIGHT NOW — a drifted vendored
      copy, or a missing / malformed freshness contract. These fail ALWAYS
      (with or without --strict), so a PR cannot merge a canonical edit that
      forgot a vendored copy.
    - stale: the snapshot has simply aged past its window. This is a
      time-based failure, so it fails ONLY under --strict (the weekly job) and
      stays warn-only in the PR/build path — a registry that quietly aged out
      must not sink unrelated PRs.
    """

    def __init__(self) -> None:
        self.hard: list[str] = []
        self.stale: list[str] = []
        self.notes: list[str] = []


def check_plugin(plugin_dir: Path, findings: Findings) -> None:
    """Check one plugin's model registry, appending to `findings`."""
    canonicals = sorted(plugin_dir.glob(CANONICAL_GLOB))
    if not canonicals:
        # Plugin ships no model-lifecycle registry — nothing to gate.
        return

    for canonical in canonicals:
        rel = canonical.relative_to(REPO_ROOT)
        text = canonical.read_text(encoding="utf-8")
        m_date = LAST_UPDATED_RE.search(text)
        m_win = WINDOW_RE.search(text)

        # --- Freshness contract must be present AND well-formed (hard). ---
        if m_date is None:
            findings.hard.append(
                f"{rel}: no '**Last updated:** YYYY-MM-DD' line — the freshness contract is missing."
            )
        elif m_win is None:
            findings.hard.append(
                f"{rel}: no '**Staleness window:** N days' line — the freshness contract is incomplete."
            )
        else:
            last_updated = m_date.group(1)
            window = int(m_win.group(1))
            try:
                age = days_since(last_updated)
            except ValueError:
                findings.hard.append(
                    f"{rel}: '**Last updated:** {last_updated}' is not a real calendar date."
                )
            else:
                stale_by = age - window
                if stale_by > 0:
                    findings.stale.append(
                        f"{rel}: STALE — last updated {last_updated} ({age}d ago), "
                        f"window {window}d, over by {stale_by}d. "
                        f"Refresh the registry against the Bedrock model lifecycle page and bump 'Last updated'."
                    )
                else:
                    findings.notes.append(
                        f"{rel}: fresh — {age}d old (window {window}d, {-stale_by}d of headroom)."
                    )

        # --- Every vendored copy must be byte-identical to this canonical (hard). ---
        for vendored in sorted(plugin_dir.glob(VENDORED_GLOB)):
            if not filecmp.cmp(canonical, vendored, shallow=False):
                findings.hard.append(
                    f"{vendored.relative_to(REPO_ROOT)}: DRIFTED from canonical {rel} — "
                    f"copy the canonical file over it (they must stay byte-identical)."
                )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="also fail on staleness (the weekly job). Drift / malformed contract fail regardless.",
    )
    ap.add_argument("--plugin", help="check a single plugin by directory name")
    args = ap.parse_args()

    if not PLUGINS_ROOT.is_dir():
        print("No plugins/ directory found.", file=sys.stderr)
        return 0

    if args.plugin:
        plugin_dirs = [PLUGINS_ROOT / args.plugin]
    else:
        plugin_dirs = [p for p in sorted(PLUGINS_ROOT.iterdir()) if p.is_dir()]

    findings = Findings()
    for plugin_dir in plugin_dirs:
        if not plugin_dir.is_dir():
            print(f"Plugin not found: {plugin_dir}", file=sys.stderr)
            return 2
        check_plugin(plugin_dir, findings)

    for note in findings.notes:
        print(f"  ok: {note}")

    # Drift / malformed contract always fail. Staleness fails only under --strict.
    for failure in findings.hard:
        print(f"  ERROR: {failure}", file=sys.stderr)
    for failure in findings.stale:
        label = "ERROR" if args.strict else "WARN"
        print(f"  {label}: {failure}", file=sys.stderr)

    should_fail = bool(findings.hard) or (args.strict and bool(findings.stale))

    if should_fail:
        n = len(findings.hard) + (len(findings.stale) if args.strict else 0)
        print(f"\nmodel-staleness: {n} problem(s) — failing.", file=sys.stderr)
        return 1

    if findings.stale:
        # Stale but not strict: reported as WARN above, exit 0 so unrelated PRs stay green.
        print(
            f"\nmodel-staleness: {len(findings.stale)} stale registry(ies) — warn-only "
            f"(the weekly --strict job fails on these)."
        )
        return 0

    print("\nmodel-staleness: all model registries fresh and in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
