#!/usr/bin/env python3
"""Model-ID drift lint.

Fails when a skill (or example, agent prompt, script, or fixture) names a
Bedrock model the lifecycle registry has retired, outside the catalog files
whose JOB is to record it.

Everything this script reads lives inside this plugin directory
(`plugins/aws-startup-advisor/`). It does not depend on, or write to, anything
at the repository root.

The banned-as-target set is READ FROM THE REGISTRY, not hardcoded. The single
source of truth is `skills/shared/ai/ai-model-lifecycle.md`:

- the Legacy/EOL table rows whose Status is **excluded** (inside the 90-day
  exclusion zone — must not appear in any recommendation), and
- every model in the **Removed** (past-EOL) list.

Deriving the set from the registry is the whole point: a new EOL row becomes
enforced the moment someone edits the table, which is exactly the recurring
model-currency churn this gate exists to collapse. A `legacy` row (e.g. Claude
Opus 4.1, >90 days to EOL) is a valid target and is deliberately NOT banned.

Plus one heuristic the table cannot express — fabricated dated hybrids
(`claude-sonnet-4-6-<date>` / `claude-opus-4-8-<date>`): those model IDs are
undated; the dated forms graft a newer name onto an older date stamp and never
existed.

Catalog files whose job is to list retired models (the lifecycle registry
itself and the pricing rate cards) are allowlisted. A vendored copy under
`skills/<skill>/references/vendored/<rel>` collapses onto its canonical
`skills/shared/<rel>` path so it inherits the canonical allowlist entry.

Stdlib only. Exit 0 = clean.

Modes (run from anywhere; paths resolve relative to this file):
    python3 plugins/aws-startup-advisor/scripts/model-id-lint.py
    python3 plugins/aws-startup-advisor/scripts/model-id-lint.py --plugin-root <dir>
        # check a copy of the plugin tree somewhere else (used by the tests)
"""

import argparse
import re
import sys
from pathlib import Path

# scripts/model-id-lint.py -> plugins/aws-startup-advisor/
DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_REL = Path("skills/shared/ai/ai-model-lifecycle.md")
EXTS = {".md", ".py", ".json", ".ts", ".tf", ".sh", ".template", ".html"}

# Catalog files whose job is to record retired models. A model ID may appear
# here; anywhere else it is a rewrite target. Vendored copies collapse onto the
# canonical shared path (below), so only canonical paths are listed.
CATALOG_ALLOWLIST = {
    "skills/shared/ai/ai-model-lifecycle.md",
    "skills/gcp-to-aws/references/shared/pricing-cache.md",
    "skills/azure-to-aws/references/shared/pricing-cache.md",
}

# The broken-ID-repair helper's example is intentionally invalid.
FABRICATED_ALLOWLIST = {
    "skills/llm-to-bedrock/references/helpers/resolve-bedrock-model-id/resolve-bedrock-model-id.md",
}

FABRICATED_RE = re.compile(r"claude-(?:sonnet-4-6|opus-4-8)-\d{8}")

SELF = Path(__file__).resolve()
_VENDORED = re.compile(r"^skills/[^/]+/references/vendored/")

# A Bedrock model ID inside a backtick span: provider.model-name[:rev] — the
# `:rev` suffix is OPTIONAL (e.g. `anthropic.claude-sonnet-4-6` is a real,
# actively-used ID in this repo with no revision number at all — CRIS/mantle
# IDs and some newer model names omit it). Also matches the bare `v1:1`-style
# continuation the Nova Reel row uses. `*` is a wildcard. Requires at least one
# `.` or `-` after the leading segment so a plain word isn't misread as an ID.
_ID_IN_BACKTICKS = re.compile(
    r"`([a-z0-9][a-z0-9.\-]*(?:\*[a-z0-9.\-]*)*(?:[.\-][a-z0-9]+)(?::[0-9]+)?|v[0-9]+:[0-9]+)`"
)


def canonicalize(rel: str) -> str:
    return _VENDORED.sub("skills/shared/", rel)


def _rebuild_dual_ids(tokens: list[str]) -> list[str]:
    """A row/bullet may list a full ID followed by a bare `vN:M` continuation
    sharing its stem (the Nova Reel notation: `amazon.nova-reel-v1:0` /
    `v1:1`). Rebuild the continuation against the preceding full ID's stem so
    it becomes its own complete ID (`amazon.nova-reel-v1:1`), never a bare
    `v1:1` fragment — banning that bare fragment as a substring would match
    any unrelated "v1:1" text (a version string, a doc reference) anywhere in
    the repo. Shared by both the excluded-table and Removed-list parsers so a
    dual-ID entry keeps reconstructing correctly regardless of which section
    it lives in (e.g. after a past-EOL row moves from the table to Removed)."""
    rebuilt: list[str] = []
    last_full = None
    for tok in tokens:
        if tok.startswith("v") and last_full and ":" in last_full:
            stem = last_full.rsplit("-v", 1)[0]
            rebuilt.append(f"{stem}-{tok}")
        else:
            rebuilt.append(tok)
            last_full = tok
    return rebuilt


def _id_to_regex(model_id: str) -> re.Pattern:
    """A retired model ID -> a matcher. `*` in the ID (e.g. the Llama 3.2 glob
    `meta.llama3-2-*-instruct-v1:0`) becomes a TOKEN-BOUNDED wildcard `[^\\s`]*`,
    not `.*` — a greedy `.*` runs across whitespace/backticks into a later model
    ID on the same line (e.g. `...llama3-2-*...` matching through the
    `meta.llama3-3-70b-instruct-v1:0` replacement named right after it), which
    false-fails a line that mentions the retired glob and its Active replacement
    together. Everything outside a `*` is literal."""
    parts = [re.escape(p) for p in model_id.split("*")]
    return re.compile(r"[^\s`]*".join(parts))


def load_banned_ids(plugin: Path) -> tuple[list[tuple[str, re.Pattern]], list[str]]:
    """Parse ai-model-lifecycle.md. Returns (list of (model_id, regex), errors)."""
    registry = plugin / REGISTRY_REL
    errors: list[str] = []
    if not registry.is_file():
        return [], [f"registry not found: {REGISTRY_REL}"]

    text = registry.read_text(encoding="utf-8")
    ids: list[str] = []
    excluded_count = 0
    removed_count = 0

    # 1) Legacy/EOL table rows whose Status cell is **excluded**.
    #    Read IDs from the Model ID column (2nd cell) ONLY — not the whole row.
    #    The Active Replacement column also holds a model ID; scanning the whole
    #    row would ban the replacement (e.g. `stability.stable-image-core-v1:0`
    #    in the Nova Canvas row), which is an Active model that legitimately
    #    appears as a target elsewhere.
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        if "excluded" not in line.lower():
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        excluded_ids = _ID_IN_BACKTICKS.findall(cells[1])
        excluded_count += len(excluded_ids)
        ids.extend(_rebuild_dual_ids(excluded_ids))

    # 2) The Removed (past-EOL) bullet list.
    in_removed = False
    for line in text.splitlines():
        if line.startswith("**Removed"):
            in_removed = True
            continue
        if in_removed:
            # The section ends at the next blockquote / bold header / heading.
            if line.startswith((">", "#")) or (line.startswith("**") and not line.startswith("**Removed")):
                in_removed = False
                continue
            if line.lstrip().startswith("-"):
                # Read IDs from the text BEFORE any "replacement:" clause — the
                # replacement names an Active model (often in backticks), and
                # scanning the whole bullet would ban it. Mirrors the excluded
                # table reading the Model ID column only. A bullet with no
                # "replacement:" (e.g. Command R / R+, two retired IDs) keeps
                # them all.
                head = re.split(r"replacement:", line, maxsplit=1)[0]
                removed_ids = _ID_IN_BACKTICKS.findall(head)
                removed_count += len(removed_ids)
                ids.extend(_rebuild_dual_ids(removed_ids))

    # Dedupe, preserve order.
    seen: set[str] = set()
    uniq = [i for i in ids if not (i in seen or seen.add(i))]

    # Guardrail: a parser that silently finds nothing is worse than a denylist.
    # Fire per-SECTION, not just on the grand total — a rename that stops only
    # the Removed list matching (e.g. "**Removed" -> "**Archive") would still
    # leave the excluded rows parsing, hiding the drop behind a non-zero total.
    if excluded_count == 0:
        errors.append(
            f"{REGISTRY_REL}: parsed ZERO **excluded** table rows — "
            f"the Legacy/EOL table format may have changed. Refusing to run a no-op gate."
        )
    if removed_count == 0:
        errors.append(
            f"{REGISTRY_REL}: parsed ZERO IDs from the **Removed** (past-EOL) "
            f"list — its header/format may have changed. Refusing to run a no-op gate."
        )

    return [(i, _id_to_regex(i)) for i in uniq], errors


def lint(plugin: Path) -> tuple[list[str], list[str], int]:
    """Return (setup errors, failures, banned-id count) for one plugin tree."""
    banned, errors = load_banned_ids(plugin)
    if errors:
        return errors, [], 0

    failures = []
    for path in sorted(plugin.rglob("*")):
        if not path.is_file() or path.suffix not in EXTS or path.resolve() == SELF:
            continue
        rel = str(path.relative_to(plugin))
        if "node_modules" in rel:
            continue
        canonical = canonicalize(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        in_catalog = canonical in CATALOG_ALLOWLIST or rel in CATALOG_ALLOWLIST
        in_fab_allow = canonical in FABRICATED_ALLOWLIST or rel in FABRICATED_ALLOWLIST

        for i, line in enumerate(text.splitlines(), 1):
            if not in_catalog:
                for model_id, pattern in banned:
                    if pattern.search(line):
                        failures.append(
                            f"{rel}:{i}: retired Bedrock model `{model_id}` "
                            f"(excluded/removed per ai-model-lifecycle.md) used outside the model catalog"
                        )
            if not in_fab_allow and FABRICATED_RE.search(line):
                failures.append(
                    f"{rel}:{i}: fabricated dated ID — Sonnet 4.6 / Opus 4.8 Bedrock IDs are undated; "
                    f"this form never existed"
                )

    return [], failures, len(banned)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--plugin-root",
        type=Path,
        default=DEFAULT_PLUGIN_ROOT,
        help="plugin directory to check (default: the plugin this script lives in)",
    )
    args = ap.parse_args()

    plugin = args.plugin_root.resolve()
    if not plugin.is_dir():
        print(f"Plugin directory not found: {plugin}", file=sys.stderr)
        return 2

    errors, failures, banned_count = lint(plugin)
    if errors:
        print(f"model-id lint: {len(errors)} setup problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if failures:
        print(f"model-id lint: {len(failures)} problem(s)", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"model-id lint: OK ({banned_count} retired IDs enforced from the registry)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
