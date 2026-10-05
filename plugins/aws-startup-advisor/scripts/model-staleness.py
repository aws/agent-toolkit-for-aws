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

This check reads the canonical registry's OWN declared date and window and
reports drift. It also verifies that every vendored copy
(`references/vendored/ai/ai-model-lifecycle.md`) is byte-identical to the
canonical `skills/shared/ai/ai-model-lifecycle.md` — the discipline the file
documents but that otherwise has no gate.

This is the model-registry sibling of the pricing freshness idea: pricing has a
cache with `_meta.last_updated`; the model registry now has the same contract.

Everything this script reads lives inside this plugin directory
(`plugins/aws-startup-advisor/`). It does not depend on, or write to, anything
at the repository root.

Two failure classes, gated differently:
    - Drift (a vendored copy that differs from canonical) and a missing /
      malformed freshness contract are correctness problems — the plugin is
      inconsistent right now. They fail ALWAYS (with or without --strict).
    - Staleness (the snapshot aged past its window) is time-based. It fails
      ONLY under --strict and stays warn-only otherwise, so a registry that
      quietly aged out does not block unrelated work.

Modes (run from anywhere; paths resolve relative to this file):
    python3 plugins/aws-startup-advisor/scripts/model-staleness.py
        # exit 1 on drift or a malformed contract; staleness is warn-only
    python3 plugins/aws-startup-advisor/scripts/model-staleness.py --strict
        # ALSO exit 1 on staleness (use for a scheduled refresh check)
    python3 plugins/aws-startup-advisor/scripts/model-staleness.py --plugin-root <dir>
        # check a copy of the plugin tree somewhere else (used by the tests)

Stdlib only. Companion test: tests/test_model_staleness.py.
"""
from __future__ import annotations

import argparse
import filecmp
import re
import sys
from datetime import date, datetime
from pathlib import Path

# scripts/model-staleness.py -> plugins/aws-startup-advisor/
DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

CANONICAL = Path("skills/shared/ai/ai-model-lifecycle.md")
VENDORED_GLOB = "skills/*/references/vendored/ai/ai-model-lifecycle.md"

# Vendored copies that MUST exist (relative to the plugin dir). The glob above
# only iterates copies that are still present, so a deleted copy would pass
# silently — yet these paths are real load targets (azure/gcp estimate-ai.md
# and design.md read them). Require them explicitly so dropping one fails
# instead of leaving the next AI estimate reading a missing file.
REQUIRED_VENDORED = (
    Path("skills/gcp-to-aws/references/vendored/ai/ai-model-lifecycle.md"),
    Path("skills/azure-to-aws/references/vendored/ai/ai-model-lifecycle.md"),
)

LAST_UPDATED_RE = re.compile(r"^\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
WINDOW_RE = re.compile(r"^\*\*Staleness window:\*\*\s*(\d+)\s*days?\s*$", re.MULTILINE)


def days_since(iso_date: str) -> int:
    then = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return (date.today() - then).days


class Findings:
    """Two classes of problem, gated differently.

    - hard: the plugin is internally inconsistent RIGHT NOW — a drifted
      vendored copy, or a missing / malformed freshness contract. These fail
      ALWAYS (with or without --strict), so a canonical edit that forgot a
      vendored copy cannot pass.
    - stale: the snapshot has simply aged past its window. This is a
      time-based failure, so it fails ONLY under --strict and stays warn-only
      otherwise — a registry that quietly aged out must not block unrelated
      work.
    """

    def __init__(self) -> None:
        self.hard: list[str] = []
        self.stale: list[str] = []
        self.notes: list[str] = []


def _rel(path: Path, plugin_root: Path) -> str:
    try:
        return str(path.relative_to(plugin_root))
    except ValueError:
        return str(path)


def check_plugin(plugin_root: Path, findings: Findings) -> None:
    """Check the plugin's model registry, appending to `findings`."""
    canonical = plugin_root / CANONICAL
    if not canonical.is_file():
        # No canonical file. Exempt ONLY if nothing else survives it — a
        # required vendored copy still present (or, failing that, ANY
        # ai-model-lifecycle.md anywhere under the plugin, e.g. a renamed or
        # relocated vendored copy the required-paths list doesn't yet know
        # about) means a consumer (estimate-ai.md / design.md) is reading a
        # registry that just lost its freshness gate entirely — a canonical
        # deletion/rename must fail loudly, not read as "this plugin never
        # had a registry."
        surviving = [plugin_root / req for req in REQUIRED_VENDORED if (plugin_root / req).is_file()]
        surviving += [
            p for p in sorted(plugin_root.glob("skills/**/ai-model-lifecycle.md")) if p not in surviving
        ]
        if surviving:
            rel_paths = ", ".join(_rel(p, plugin_root) for p in surviving)
            findings.hard.append(
                f"canonical {CANONICAL} is MISSING, but {rel_paths} still exist and are "
                f"read by estimate-ai.md/design.md — this plugin still has an "
                f"active model registry with NO freshness gate. Restore the "
                f"canonical file (or delete every surviving copy if the registry "
                f"is being retired intentionally)."
            )
        # Otherwise: plugin genuinely ships no model-lifecycle registry at
        # all — nothing to gate, exemption preserved.
        return

    rel = _rel(canonical, plugin_root)
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
            if age < 0:
                # A future date is a malformed contract, not "extra fresh".
                # Treated as staleness (negative headroom) it would report
                # "fresh" forever and silently disable the gate — so it is a
                # HARD error, not warn-only.
                findings.hard.append(
                    f"{rel}: '**Last updated:** {last_updated}' is in the future "
                    f"({-age}d from now) — a bad bump would disable the freshness gate. Fix the date."
                )
            elif stale_by > 0:
                findings.stale.append(
                    f"{rel}: STALE — last updated {last_updated} ({age}d ago), "
                    f"window {window}d, over by {stale_by}d. "
                    f"Refresh the registry against the Bedrock model lifecycle page and bump 'Last updated'."
                )
            else:
                findings.notes.append(
                    f"{rel}: fresh — {age}d old (window {window}d, {-stale_by}d of headroom)."
                )

    # --- Required vendored copies must EXIST (hard). ---
    # The glob below only sees copies that are present, so a deleted copy is
    # invisible to a byte-compare. Check the required paths explicitly first.
    for req in REQUIRED_VENDORED:
        req_path = plugin_root / req
        if not req_path.is_file():
            findings.hard.append(
                f"{req}: MISSING — a required vendored copy of the "
                f"model-lifecycle registry. AI estimate/design load this path; do not delete it. "
                f"Copy the canonical {rel} into place."
            )

    # --- Every vendored copy that exists must be byte-identical to canonical (hard). ---
    for vendored in sorted(plugin_root.glob(VENDORED_GLOB)):
        if not filecmp.cmp(canonical, vendored, shallow=False):
            findings.hard.append(
                f"{_rel(vendored, plugin_root)}: DRIFTED from canonical {rel} — "
                f"copy the canonical file over it (they must stay byte-identical)."
            )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="also fail on staleness. Drift / malformed contract fail regardless.",
    )
    ap.add_argument(
        "--plugin-root",
        type=Path,
        default=DEFAULT_PLUGIN_ROOT,
        help="plugin directory to check (default: the plugin this script lives in)",
    )
    args = ap.parse_args()

    plugin_root = args.plugin_root.resolve()
    if not plugin_root.is_dir():
        print(f"Plugin directory not found: {plugin_root}", file=sys.stderr)
        return 2

    findings = Findings()
    check_plugin(plugin_root, findings)

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
        # Stale but not strict: reported as WARN above, exit 0.
        print(
            f"\nmodel-staleness: {len(findings.stale)} stale registry(ies) — warn-only "
            f"(--strict fails on these)."
        )
        return 0

    print("\nmodel-staleness: model registry fresh and in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
