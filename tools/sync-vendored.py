#!/usr/bin/env python3
"""Keep each skill's `references/vendored/` copies byte-identical to `skills/shared/`.

Why
---
The aws-startup-advisor migration skills are installable one at a time
(`npx skills add … --skill gcp-to-aws`), so each skill folder must be self-contained.
Shared material (the DSL interpreter, pricing caches, estimate schemas, …) is therefore
*vendored* — copied — into `skills/<skill>/references/vendored/<path>` from the
canonical `skills/shared/<path>`. Until now the copies were kept in sync by hand
("copy the changed file over every vendored copy in the same change"), with no gate.
This tool is the gate, in the same shape as `sync-plugin-skills.py`.

Rule
----
For every file under `plugins/<plugin>/skills/<skill>/references/vendored/<path>`
(README.md excluded), `plugins/<plugin>/skills/shared/<path>` must exist and be
byte-identical. The vendored tree is a subset of shared/ — a skill vendors only
what it loads — so files present in shared/ but not vendored are fine.

Usage
-----
    python3 tools/sync-vendored.py              # copy shared/ over every vendored copy
    python3 tools/sync-vendored.py --check      # exit 1 if any copy differs / has no source
    python3 tools/sync-vendored.py --plugin aws-startup-advisor

Exit 0 when in sync (or after syncing), 1 on --check failure. Stdlib only.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
VENDORED_SUBDIR = Path("references") / "vendored"
SHARED_DIRNAME = "shared"
SKIP_NAMES = {"README.md"}


def _rel(p: Path) -> str:
    """Repo-relative for display; absolute when the tree lives elsewhere (tests)."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def vendored_files(plugin_dir: Path) -> List[Tuple[Path, Path, Path]]:
    """Yield (vendored_file, canonical_file, rel_path) triples for one plugin."""
    skills_dir = plugin_dir / "skills"
    shared = skills_dir / SHARED_DIRNAME
    out: List[Tuple[Path, Path, Path]] = []
    if not skills_dir.is_dir():
        return out
    for skill in sorted(skills_dir.iterdir()):
        vend = skill / VENDORED_SUBDIR
        if skill.name == SHARED_DIRNAME or not vend.is_dir():
            continue
        for f in sorted(p for p in vend.rglob("*") if p.is_file()):
            if f.name in SKIP_NAMES:
                continue
            rel = f.relative_to(vend)
            out.append((f, shared / rel, rel))
    return out


def check_plugin(plugin_dir: Path) -> List[str]:
    errors: List[str] = []
    for vend, canon, rel in vendored_files(plugin_dir):
        if not canon.is_file():
            errors.append(
                f"{_rel(vend)}: no canonical source at "
                f"{_rel(canon)} — either add the file to skills/shared/ "
                f"or stop vendoring it"
            )
        elif not filecmp.cmp(vend, canon, shallow=False):
            errors.append(
                f"{_rel(vend)}: differs from "
                f"{_rel(canon)} — run `python3 tools/sync-vendored.py`"
            )
    return errors


def sync_plugin(plugin_dir: Path) -> Tuple[int, List[str]]:
    """Copy canonical over vendored where they differ. Returns (copied, errors)."""
    copied = 0
    errors: List[str] = []
    for vend, canon, rel in vendored_files(plugin_dir):
        if not canon.is_file():
            errors.append(
                f"{_rel(vend)}: no canonical source at "
                f"{_rel(canon)} — cannot sync; add it to skills/shared/ or delete the copy"
            )
            continue
        if not filecmp.cmp(vend, canon, shallow=False):
            shutil.copyfile(canon, vend)
            copied += 1
            print(f"  synced {_rel(vend)} <- {_rel(canon)}")
    return copied, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Keep skills' references/vendored/ copies identical to skills/shared/")
    ap.add_argument("--plugin", help="Only this plugin (directory name under plugins/)")
    ap.add_argument("--check", action="store_true", help="Report drift and exit 1; change nothing")
    ap.add_argument("--plugins-root", type=Path, default=PLUGINS_ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    plugins = [args.plugins_root / args.plugin] if args.plugin else sorted(
        p for p in args.plugins_root.iterdir() if p.is_dir())
    total_files = 0
    all_errors: List[str] = []
    copied = 0
    for plugin_dir in plugins:
        files = vendored_files(plugin_dir)
        total_files += len(files)
        if not files:
            continue
        if args.check:
            all_errors.extend(check_plugin(plugin_dir))
        else:
            n, errs = sync_plugin(plugin_dir)
            copied += n
            all_errors.extend(errs)

    if all_errors:
        print(f"FAIL — {len(all_errors)} vendored file(s) out of contract:")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    if args.check:
        print(f"PASS — {total_files} vendored file(s) byte-identical to skills/shared/")
    else:
        print(f"OK — {total_files} vendored file(s) checked, {copied} synced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
