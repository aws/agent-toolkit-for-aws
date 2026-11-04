#!/usr/bin/env python3
"""model-catalog-drift.py: keep the model-selection catalogs in step with the lifecycle registry.

Why
---
Two shared sources describe Bedrock models:

- `skills/shared/ai/ai-model-lifecycle.md` is the canonical Active/Legacy/EOL registry. It is
  kept current (the knowledge auto-update pipeline edits it, and `model-staleness.py` fails it
  after its staleness window).
- `skills/shared/ai/models/*-bedrock.json` are the machine-readable selection catalogs that the
  agent-advisor engine reads (vendored into the skill by `sync-vendored.py`).

Nothing tied the two together, so a model could launch, land in the registry, and never reach
the catalog the engine actually selects from. `model-id-lint.py` already keeps retired IDs out of
the catalogs; this gate covers the other direction.

Rules
-----
1. Coverage: every Anthropic or OpenAI model the registry's Capability Constraints table marks
   **Active** must appear in a catalog, either as a model entry (any path's `model_id`) or in
   that catalog's optional top-level `registry_exclusions` object (`{"<model id>": "<reason>"}`),
   which records an intentional omission. The catalogs have no non-selectable status: the
   selection engine treats every entry under `models` as a candidate, so a model that should not
   be selected belongs in `registry_exclusions`, not in `models`. Each exclusion needs a
   non-empty reason (else an error) and must name a model that is Active in the registry (else
   a warning).
2. Freshness: each catalog's `verified_at` must fall inside the registry's staleness window
   and must not be in the future.

Findings are warnings by default (exit 0) so the gate can land before the catalogs are
refreshed; `--strict` turns them into failures (exit 1). Structural problems (a registry table
that no longer parses, a catalog that is not valid JSON) always fail.

Usage
-----
    python3 plugins/aws-startup-advisor/tools/model-catalog-drift.py
    python3 plugins/aws-startup-advisor/tools/model-catalog-drift.py --strict
    python3 plugins/aws-startup-advisor/tools/model-catalog-drift.py --plugin-root <dir> --today 2026-11-04

Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_REL = Path("skills/shared/ai/ai-model-lifecycle.md")
CATALOG_DIR_REL = Path("skills/shared/ai/models")
PROVIDER_PREFIXES = {"anthropic": "anthropic.", "openai": "openai."}
CAPABILITY_HEADING = re.compile(r"^## Capability Constraints\b")
WINDOW_RE = re.compile(r"^\*\*Staleness window:\*\*\s*(\d+)\s*days", re.M)
_ID_IN_BACKTICKS = re.compile(r"`([a-z0-9][a-z0-9.\-]*(?::[0-9]+)?)`")


def registry_active_ids(text: str) -> list[str]:
    """Model IDs the Capability Constraints table marks Active, in table order."""
    ids: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = bool(CAPABILITY_HEADING.match(line))
            continue
        if not in_section or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[2].lower().startswith("active"):
            continue
        ids.extend(_ID_IN_BACKTICKS.findall(cells[1]))
    return ids


def staleness_window_days(text: str) -> int | None:
    match = WINDOW_RE.search(text)
    return int(match.group(1)) if match else None


def catalog_model_ids(catalog: dict) -> set[str]:
    ids: set[str] = set()
    for model in catalog.get("models", {}).values():
        for path in model.get("paths", {}).values():
            if isinstance(path, dict) and path.get("model_id"):
                ids.add(path["model_id"])
    return ids


def check(plugin: Path, today: dt.date) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors are structural; warnings are drift findings."""
    errors: list[str] = []
    warnings: list[str] = []
    registry = plugin / REGISTRY_REL
    if not registry.is_file():
        return [f"registry not found: {REGISTRY_REL}"], []
    text = registry.read_text(encoding="utf-8")
    active = registry_active_ids(text)
    if not active:
        return [f"{REGISTRY_REL}: parsed ZERO Active rows from the Capability Constraints table; "
                "its heading or format may have changed. Refusing to run a no-op gate."], []
    window = staleness_window_days(text)
    if window is None:
        errors.append(f"{REGISTRY_REL}: no '**Staleness window:** N days' line")

    catalog_dir = plugin / CATALOG_DIR_REL
    covered: dict[str, set[str]] = {}
    for provider in PROVIDER_PREFIXES:
        path = catalog_dir / f"{provider}-bedrock.json"
        rel = CATALOG_DIR_REL / path.name
        if not path.is_file():
            errors.append(f"catalog not found: {rel}")
            continue
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON ({exc})")
            continue
        exclusions = catalog.get("registry_exclusions", {})
        if not isinstance(exclusions, dict):
            errors.append(f"{rel}: registry_exclusions must be an object of {{model id: reason}}")
            exclusions = {}
        for model_id, reason in exclusions.items():
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{rel}: registry_exclusions[`{model_id}`] needs a non-empty reason")
            if model_id not in active:
                # A typo'd or no-longer-Active exclusion would otherwise suppress nothing (or the
                # wrong thing) forever; surface it so it gets corrected or removed.
                warnings.append(f"{rel}: registry_exclusions lists `{model_id}`, which is not an Active "
                                f"model in {REGISTRY_REL.name}; fix the id or remove the exclusion")
        covered[provider] = catalog_model_ids(catalog) | set(exclusions)
        verified = catalog.get("verified_at")
        try:
            age = (today - dt.date.fromisoformat(verified)).days
        except (TypeError, ValueError):
            errors.append(f"{rel}: verified_at {verified!r} is not an ISO date")
            continue
        if age < 0:
            warnings.append(f"{rel}: verified_at {verified} is in the future; use the real verification date")
        elif window is not None and age > window:
            warnings.append(f"{rel}: verified_at {verified} is {age} days old "
                            f"(registry staleness window is {window} days); re-verify the catalog")

    # Matching is exact on the bare model id. The registry's Model ID column lists bare ids (CRIS
    # prefixes such as `us.` / `global.` live in the table notes), and every catalog path carries
    # the bare id in `model_id`, so a prefixed form never needs to be matched here.
    for model_id in active:
        provider = next((p for p, prefix in PROVIDER_PREFIXES.items() if model_id.startswith(prefix)), None)
        if provider is None or provider not in covered:
            continue
        if model_id not in covered[provider]:
            warnings.append(
                f"{CATALOG_DIR_REL / f'{provider}-bedrock.json'}: `{model_id}` is Active in "
                f"{REGISTRY_REL.name} but missing from the catalog; add a complete model entry "
                f"(every entry under `models` is a selection candidate) or record it under "
                f"registry_exclusions with a reason")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--plugin-root", type=Path, default=DEFAULT_PLUGIN_ROOT)
    parser.add_argument("--strict", action="store_true", help="fail on drift findings")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args(argv)
    errors, warnings = check(args.plugin_root, args.today)
    for msg in errors:
        print(f"ERROR: {msg}")
    level = "ERROR" if args.strict else "WARN"
    for msg in warnings:
        print(f"{level}: {msg}")
    if errors or (args.strict and warnings):
        print("model-catalog-drift: FAIL")
        return 1
    print(f"model-catalog-drift: OK ({len(warnings)} warning(s); pass --strict to enforce)"
          if warnings else "model-catalog-drift: catalogs cover every Active registry model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
