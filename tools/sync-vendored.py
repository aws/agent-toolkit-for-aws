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

Rules
-----
1. Every file under `plugins/<plugin>/skills/<skill>/references/vendored/<path>`
   (README.md excluded) has a canonical `plugins/<plugin>/skills/shared/<path>` and is
   byte-identical to it.
2. Each vendored directory's README.md carries a `| Vendored path | Canonical source |`
   table. Every row must exist on disk (a deleted copy is caught), every file on disk must
   have a row (the README stays honest), and the row's canonical source must be
   `skills/shared/<same path>`.

What this gate cannot see: a NEW file added to skills/shared/ that no skill vendors yet.
The vendored tree is a subset of shared/ by design — a skill vendors only what it loads —
so adding a shared file a skill needs means adding the copy AND the README row.

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
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

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


_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*$", re.M)


def readme_manifest(vend_dir: Path) -> Tuple[Dict[str, str], List[str]]:
    """Parse the `| Vendored path | Canonical source |` table in a vendored README.

    Returns ({vendored_rel_path: canonical_path_as_written}, errors). A README without the
    table is an error: the table is the only record of what the skill is MEANT to vendor,
    which is what lets a deleted copy be detected at all."""
    readme = vend_dir / "README.md"
    if not readme.is_file():
        return {}, [f"{_rel(vend_dir)}: no README.md — the vendored-path table lives there"]
    rows = {}
    text = readme.read_text(encoding="utf-8")
    for vend_rel, canon in _ROW_RE.findall(text):
        rows[vend_rel.strip()] = canon.strip()
    if not rows:
        return {}, [f"{_rel(readme)}: no `| Vendored path | Canonical source |` table rows found"]
    return rows, []


def check_manifest(plugin_dir: Path) -> List[str]:
    """Rule 2: README table ↔ files on disk, both directions, with correct canonical paths."""
    errors: List[str] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return errors
    for skill in sorted(skills_dir.iterdir()):
        vend = skill / VENDORED_SUBDIR
        if skill.name == SHARED_DIRNAME or not vend.is_dir():
            continue
        rows, errs = readme_manifest(vend)
        errors.extend(errs)
        if not rows:
            continue
        on_disk = {str(p.relative_to(vend)) for p in vend.rglob("*") if p.is_file() and p.name not in SKIP_NAMES}
        for rel in sorted(set(rows) - on_disk):
            errors.append(
                f"{_rel(vend / rel)}: listed in {_rel(vend / 'README.md')} but missing on disk — "
                f"the copy was deleted; restore it with `python3 tools/sync-vendored.py` or remove the row")
        for rel in sorted(on_disk - set(rows)):
            errors.append(
                f"{_rel(vend / rel)}: on disk but not listed in {_rel(vend / 'README.md')} — add a row")
        for rel, canon in sorted(rows.items()):
            expected = f"skills/{SHARED_DIRNAME}/{rel}"
            if canon != expected:
                errors.append(
                    f"{_rel(vend / 'README.md')}: row for `{rel}` names canonical `{canon}`, expected `{expected}`")
    return errors


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
    """Copy canonical over vendored where they differ, and restore copies the README
    lists that are missing on disk. Returns (copied, errors)."""
    copied = 0
    errors: List[str] = []
    skills_dir = plugin_dir / "skills"
    shared = skills_dir / SHARED_DIRNAME
    if skills_dir.is_dir():
        for skill in sorted(skills_dir.iterdir()):
            vend = skill / VENDORED_SUBDIR
            if skill.name == SHARED_DIRNAME or not vend.is_dir():
                continue
            rows, _ = readme_manifest(vend)
            for rel in sorted(rows):
                target = vend / rel
                canon = shared / rel
                if not target.exists() and canon.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(canon, target)
                    copied += 1
                    print(f"  restored {_rel(target)} <- {_rel(canon)}")
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
        if not files and not any((skill / VENDORED_SUBDIR).is_dir()
                                 for skill in (plugin_dir / "skills").iterdir()
                                 if (plugin_dir / "skills").is_dir() and skill.is_dir()):
            continue
        if args.check:
            all_errors.extend(check_plugin(plugin_dir))
            all_errors.extend(check_manifest(plugin_dir))
        else:
            n, errs = sync_plugin(plugin_dir)
            copied += n
            all_errors.extend(errs)
            all_errors.extend(check_manifest(plugin_dir))

    if all_errors:
        print(f"FAIL — {len(all_errors)} vendored file(s) out of contract:")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    if args.check:
        print(f"PASS — {total_files} vendored file(s) byte-identical to skills/shared/ and matching their README tables")
    else:
        print(f"OK — {total_files} vendored file(s) checked, {copied} synced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
