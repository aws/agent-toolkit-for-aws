#!/usr/bin/env python3
"""Sync plugin-bundled skills from canonical skills/ sources.

Auto-discovers matching skills by name: for each directory under
plugins/<plugin>/skills/<name>/, if a directory with the same name
containing a SKILL.md exists under skills/, the canonical copy is
treated as the source of truth.

Usage:
    python3 tools/sync-plugin-skills.py              # sync all plugins
    python3 tools/sync-plugin-skills.py --plugin X   # sync one plugin
    python3 tools/sync-plugin-skills.py --check      # exit 1 if out of sync
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_canonical_index() -> dict[str, Path]:
    """Build a map of skill name -> canonical directory path."""
    skills_root = REPO_ROOT / "skills"
    index: dict[str, Path] = {}
    if not skills_root.is_dir():
        return index
    for skill_md in skills_root.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        index[skill_dir.name] = skill_dir
    return index


def trees_match(a: Path, b: Path) -> bool:
    """Return True if two directory trees are byte-for-byte identical."""
    a_files = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    b_files = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if a_files != b_files:
        return False
    return all(
        filecmp.cmp(a / f, b / f, shallow=False) for f in a_files
    )


def sync_plugin(plugin_dir: Path, canonical: dict[str, Path], check_only: bool) -> list[str]:
    """Sync one plugin. Returns list of error messages (empty = success)."""
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return []

    errors = []
    for bundled in sorted(skills_dir.iterdir()):
        if not bundled.is_dir():
            continue
        source = canonical.get(bundled.name)
        if source is None:
            continue

        if trees_match(source, bundled):
            continue

        source_rel = source.relative_to(REPO_ROOT)
        if check_only:
            errors.append(
                f"{plugin_dir.name}: {bundled.name} is out of sync with {source_rel}"
            )
        else:
            shutil.rmtree(bundled)
            shutil.copytree(source, bundled)
            print(f"  synced {bundled.name} <- {source_rel}")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync plugin skills from canonical sources")
    parser.add_argument("--plugin", help="Sync only this plugin")
    parser.add_argument("--check", action="store_true", help="Check mode: exit 1 if out of sync")
    args = parser.parse_args()

    plugins_dir = REPO_ROOT / "plugins"
    canonical = build_canonical_index()
    all_errors: list[str] = []

    if args.plugin:
        plugin_dir = plugins_dir / args.plugin
        if not plugin_dir.is_dir():
            print(f"Plugin not found: {args.plugin}", file=sys.stderr)
            sys.exit(1)
        print(f"{'Checking' if args.check else 'Syncing'} plugin: {args.plugin}")
        all_errors.extend(sync_plugin(plugin_dir, canonical, args.check))
    else:
        for plugin_dir in sorted(plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if (plugin_dir / "skills").is_dir():
                print(f"{'Checking' if args.check else 'Syncing'} plugin: {plugin_dir.name}")
                all_errors.extend(sync_plugin(plugin_dir, canonical, args.check))

    if all_errors:
        print(f"\n{len(all_errors)} error(s):", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        if args.check:
            print("\nRun 'python3 tools/sync-plugin-skills.py' to fix.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll plugin skills are in sync.")


if __name__ == "__main__":
    main()
