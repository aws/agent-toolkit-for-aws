#!/usr/bin/env python3
"""Sync plugin-bundled skills from canonical skills/ sources.

Reads each plugin's skills.json manifest and copies the referenced skill
directories into plugins/<name>/skills/. Skills listed in the manifest are
replaced entirely; plugin-only skills (not in the manifest) are left untouched.

Usage:
    python3 tools/sync-plugin-skills.py              # sync all plugins
    python3 tools/sync-plugin-skills.py --plugin X   # sync one plugin
    python3 tools/sync-plugin-skills.py --check      # exit 1 if out of sync
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def trees_match(a: Path, b: Path) -> bool:
    """Return True if two directory trees are byte-for-byte identical."""
    a_files = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    b_files = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if a_files != b_files:
        return False
    return all(
        filecmp.cmp(a / f, b / f, shallow=False) for f in a_files
    )


def sync_plugin(plugin_dir: Path, check_only: bool) -> list[str]:
    """Sync one plugin. Returns list of error messages (empty = success)."""
    manifest_path = plugin_dir / "skills.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text())
    skills_map = manifest.get("skills", {})
    skills_dir = plugin_dir / "skills"
    errors = []

    for skill_name, source_rel in sorted(skills_map.items()):
        source = REPO_ROOT / source_rel
        dest = skills_dir / skill_name

        if not source.is_dir():
            errors.append(f"{plugin_dir.name}: source not found: {source_rel}")
            continue

        if dest.exists() and trees_match(source, dest):
            continue

        if check_only:
            errors.append(
                f"{plugin_dir.name}: {skill_name} is out of sync with {source_rel}"
            )
        else:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest)
            print(f"  synced {skill_name} <- {source_rel}")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync plugin skills from canonical sources")
    parser.add_argument("--plugin", help="Sync only this plugin")
    parser.add_argument("--check", action="store_true", help="Check mode: exit 1 if out of sync")
    args = parser.parse_args()

    plugins_dir = REPO_ROOT / "plugins"
    all_errors: list[str] = []

    if args.plugin:
        plugin_dir = plugins_dir / args.plugin
        if not plugin_dir.is_dir():
            print(f"Plugin not found: {args.plugin}", file=sys.stderr)
            sys.exit(1)
        print(f"{'Checking' if args.check else 'Syncing'} plugin: {args.plugin}")
        all_errors.extend(sync_plugin(plugin_dir, args.check))
    else:
        for plugin_dir in sorted(plugins_dir.iterdir()):
            if plugin_dir.is_dir() and (plugin_dir / "skills.json").exists():
                print(f"{'Checking' if args.check else 'Syncing'} plugin: {plugin_dir.name}")
                all_errors.extend(sync_plugin(plugin_dir, args.check))

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
