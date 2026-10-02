#!/usr/bin/env python3
"""Check that every file path a skill's instructions mention actually exists.

Why
---
The aws-startup-advisor skills are prose state machines: a phase file says "Load
`references/phases/design/design-ai.md`" or "run `python3 \"<SKILL_BASE>/scripts/x.py\"`"
and the agent follows the string. Nothing checked that the target exists. A renamed or
never-written file is a dead end the user hits mid-migration (azure-to-aws halts on Bicep
input because `discover-iac.md` points at `extract-bicep.md`, which does not exist), and
any file move during consolidation would break references silently. This is the gate that
makes a move provable, in the same family as `validate-artifacts.py` (artifact contracts)
and `sync-vendored.py` (vendored parity).

What counts as a reference
--------------------------
A token in a skill file that looks like a repository path to an instruction/data file:
`references/…`, `knowledge/…`, `scripts/…`, `skills/…`, `agents/…`, `data/…`, and the
agent-advisor short forms `phases/…`, `shared/…`, `design-refs/…`, with an extension in
md/json/py/sh/tf/yml/yaml/html/txt. Optional prefixes `$PLUGIN_ROOT/`,
`${CLAUDE_PLUGIN_ROOT}/`, `$SKILL_BASE/`, `<SKILL_BASE>/`, `$GCP_BASE/`, `./`, `../`.

Not references (skipped): run-artifact paths (`$MIGRATION_DIR/…`, `$RUN_DIR/…`, `$REPO/…`,
`.migration/…`, `<PLAN_DIR>/…`, `.saws-migrate/…`, `terraform/…`), templated tokens
(`<slug>`, `{name}`, `*`, `NNN`), and URLs.

Resolution order for a bare path `P` found in `skills/<skill>/…/file.md`:
  1. explicit prefix → plugin root / skill root / gcp-to-aws root / referencing file's dir.
     An explicit prefix is authoritative: the agent runs `<SKILL_BASE>/scripts/x.py` as
     written, so none of the fallbacks below apply to it.
  2. `skills/<skill>/P`                     (skill-relative — the documented convention)
  3. `<dir of referencing file>/P`          (file-relative)
  4. `skills/<skill>/references/P`          (agent-advisor short forms: phases/, shared/, design-refs/)
  5. `<plugin>/P` and `<repo>/P`            (plugin- or repo-relative)
A path that resolves nowhere is MISSING_REF.

Usage
-----
    python3 tools/check-skill-refs.py --check            # CI: exit 1 on any non-baselined MISSING_REF
    python3 tools/check-skill-refs.py --check --json
    python3 tools/check-skill-refs.py --list             # print every resolved reference (debug)
    --baseline tools/skill-refs-baseline.json            # known dead refs with reasons; stale entries fail

Stdlib only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLUGIN = REPO_ROOT / "plugins" / "aws-startup-advisor"
DEFAULT_BASELINE = REPO_ROOT / "tools" / "skill-refs-baseline.json"

EXTS = r"(?:md|json|py|sh|tf|ya?ml|html|txt|toml)"
ROOTS = r"(?:references|knowledge|scripts|skills|agents|data|phases|shared|design-refs|fixtures|tools)"
PREFIX = r"(?:\$\{?[A-Z_]+\}?/|<[A-Z_]+>/|\./|(?:\.\./)+)*"
# the path token: optional variable/relative prefix, then seg/seg/…/file.ext. A token with no
# prefix must start with a known root dir, so prose like "foo/bar.md" is not a reference.
_TOKEN_RE = re.compile(
    rf"(?P<prefix>{PREFIX})(?P<path>[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*\.{EXTS})(?![A-Za-z0-9_.])"
)
_ROOTS_RE = re.compile(rf"^{ROOTS}/")
# the vendored/shared library speaks from the CONSUMING skill's point of view; its references
# resolve against skills/shared and against any skill that vendors it
_LIBRARY_ORIGIN_RE = re.compile(r"/skills/(shared/|[^/]+/references/(vendored|shared)/)")
# skills that execute gcp-to-aws's phase files inline (agent-advisor) or by Skill invocation
# (llm-to-bedrock) legitimately name paths inside gcp-to-aws's tree
_GCP_DEPENDENTS = {"agent-advisor", "llm-to-bedrock"}
# the skill whose subagents live in plugins/<plugin>/agents/
_AGENTS_OWNER = "llm-to-bedrock"
# anything carrying a run-artifact prefix or templating is not a repo path
_SKIP_PREFIX_RE = re.compile(
    r"(\$\{?(MIGRATION_DIR|RUN_DIR|REPO|PHASE_DIR|PLAN_DIR|OUT|TARGET|APP|WORKSPACE|TMP)\}?/"
    r"|<(PLAN_DIR|MIGRATION_DIR|RUN_DIR|REPO|run_dir|migration_dir|path|repo)>/"
    r"|\.migration/|\.saws-migrate/|terraform/|ai-migration/|poc/|scaffold/|\.github/)"
)
_URL_RE = re.compile(r"https?://\S*")


@dataclass
class Ref:
    source: Path          # file containing the reference
    line: int
    raw: str              # the token as written
    resolved: Optional[Path]

    @property
    def skill(self) -> str:
        parts = self.source.parts
        if "skills" in parts:
            i = parts.index("skills")
            if i + 1 < len(parts):
                return parts[i + 1]
        if "agents" in parts:
            return "agents"
        return "?"


def _skill_root(source: Path, plugin: Path) -> Optional[Path]:
    try:
        rel = source.relative_to(plugin / "skills")
    except ValueError:
        return None
    return plugin / "skills" / rel.parts[0]


def _candidates(prefix: str, path: str, source: Path, plugin: Path) -> List[Path]:
    """Ordered list of filesystem locations the token could mean."""
    skill = _skill_root(source, plugin)
    here = source.parent
    cands: List[Path] = []
    p = prefix
    if "PLUGIN_ROOT" in p:
        cands.append(plugin / path)
    elif "GCP_BASE" in p:
        cands.append(plugin / "skills" / "gcp-to-aws" / path)
    elif "SKILL_BASE" in p or "SKILL_DIR" in p:
        if skill is not None:
            cands.append(skill / path)
        else:
            cands.append(here / path)
    elif "HELPERS" in p and skill is not None:
        cands.append(skill / "references" / "helpers" / path)
    elif "SCRIPTS" in p and skill is not None:
        cands.append(skill / "scripts" / path)
    elif p.startswith("./") or p.startswith("../"):
        cands.append((here / p / path))
        if skill is not None:
            cands.append(skill / path)
    # `<SKILL_BASE>/../gcp-to-aws/SKILL.md` style: prefix carries `../`
    if "../" in p and skill is not None and "SKILL_BASE" in p:
        up = skill
        for _ in range(p.count("../")):
            up = up.parent
        cands.append(up / path)
    if cands:
        # An explicit base (`<SKILL_BASE>/`, `$PLUGIN_ROOT/`, `$GCP_BASE/`, `./`, `../`) names
        # the location. The agent runs the command as written, so a same-named file under
        # another skill does not make the named one exist — no cross-skill fallbacks here.
        return cands
    if skill is not None:
        cands.append(skill / path)
    cands.append(here / path)
    if skill is not None:
        cands.append(skill / "references" / path)
    cands.append(plugin / path)
    cands.append(REPO_ROOT / path)
    src = str(source)
    if _LIBRARY_ORIGIN_RE.search(src):
        shared = plugin / "skills" / "shared"
        stripped = re.sub(r"^(references/)?(vendored|shared)/", "", path)
        cands.append(shared / stripped)
        # a shared doc may name a file by its vendored-tree path with a flattened dir
        # (`shared/ai-migration-guardrails.md` → skills/shared/ai/ai-migration-guardrails.md)
        for hit in shared.rglob(Path(stripped).name):
            if str(hit).endswith(stripped.split("/")[-1]) and hit.is_file():
                cands.append(hit)
        for other in sorted((plugin / "skills").iterdir()):
            if other.is_dir():
                cands.append(other / path)
                cands.append(other / "references" / path)
    if skill is not None and skill.name in _GCP_DEPENDENTS:
        gcp = plugin / "skills" / "gcp-to-aws"
        cands.append(gcp / path)
        cands.append(gcp / "references" / path)
    if skill is None and "agents" in source.parts:
        # agents/ holds llm-to-bedrock's subagents (llm2bedrock-*) and two generic phase
        # workers; their paths are relative to llm-to-bedrock's scripts/ or helper dirs,
        # named through variables (<BDD_DIR>, $HELPERS) the agent defines at runtime.
        # Resolve ONLY against that skill — a same-named file in another skill must not
        # make a dead llm-to-bedrock path look alive.
        owner = plugin / "skills" / _AGENTS_OWNER
        cands.append(owner / path)
        if owner.is_dir():
            for hit in owner.rglob(Path(path).name):
                if str(hit).endswith(path) and hit.is_file():
                    cands.append(hit)
    return cands


def _resolve(prefix: str, path: str, source: Path, plugin: Path) -> Optional[Path]:
    for c in _candidates(prefix, path, source, plugin):
        try:
            if c.resolve().is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def _is_templated(token: str) -> bool:
    body = re.sub(r"^(?:<[A-Z_]+>/|\$\{?[A-Z_]+\}?/)+", "", token)
    return any(ch in body for ch in "<>{}*[]") or "NNN" in body or "/…" in body


def scan_file(source: Path, plugin: Path) -> List[Ref]:
    refs: List[Ref] = []
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return refs
    for i, line in enumerate(text.splitlines(), start=1):
        line_wo_urls = _URL_RE.sub("", line)
        for m in _TOKEN_RE.finditer(line_wo_urls):
            start = m.start()
            # Only the token's own contiguous prefix decides whether it is a run-artifact
            # path (`<run_dir>/references/x.md`, `.migration/<run>/scripts/y.sh`). An
            # earlier, separate token on the line — "write to `$MIGRATION_DIR/` per
            # `references/shared/schema.md`" — says nothing about this one.
            before = re.search(r"[^\s`]*$", line_wo_urls[:start]).group(0)
            full = m.group(0)
            if _SKIP_PREFIX_RE.search(before + full[: len(m.group("prefix"))]):
                continue
            if _is_templated(full):
                continue
            pfx = m.group("prefix")
            if not pfx and not _ROOTS_RE.match(m.group("path")):
                continue
            # `./x.sh`, `../plan.md`: a relative token with no known root dir anywhere in it is a
            # generated-output or working-tree path, not a reference into the skill tree
            if pfx and re.fullmatch(r"(\./|\.\./)+", pfx) and not re.search(rf"(^|/){ROOTS}/", m.group("path")):
                continue
            # a token glued to a preceding word char or '/' is part of a longer identifier/path
            if start > 0 and (line_wo_urls[start - 1].isalnum() or line_wo_urls[start - 1] in "_-/"):
                continue
            resolved = _resolve(m.group("prefix"), m.group("path"), source, plugin)
            refs.append(Ref(source=source, line=i, raw=full, resolved=resolved))
    return refs


def scan(plugin: Path) -> List[Ref]:
    files: List[Path] = []
    for sub in ("skills", "agents"):
        root = plugin / sub
        if root.is_dir():
            files.extend(p for p in root.rglob("*.md") if p.is_file())
    out: List[Ref] = []
    for f in sorted(files):
        if any(part in ("node_modules", ".git", "fixtures") for part in f.parts):
            continue
        out.extend(scan_file(f, plugin))
    return out


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def apply_baseline(missing: List[Ref], baseline: Dict) -> Tuple[List[Ref], List[Ref], List[Dict]]:
    """Split missing refs into (unbaselined, baselined); return stale entries too.

    Two kinds of rule live in the baseline file:
      ignore[]  — permanent policy: tokens that are not repository references by nature (paths
                  the skill GENERATES, example paths in a user's app). Never stale.
      entries[] — known dead references, each with the fix that retires it. STALE when they
                  stop matching, so the list only shrinks."""
    for rule in baseline.get("ignore", []):
        missing = [r for r in missing
                   if not (fnmatch.fnmatch(_rel(r.source), rule.get("source", "*")) and fnmatch.fnmatch(r.raw, rule.get("ref", "*")))]
    entries = baseline.get("entries", [])
    used = [False] * len(entries)
    un: List[Ref] = []
    bl: List[Ref] = []
    for r in missing:
        hit = False
        for i, e in enumerate(entries):
            if fnmatch.fnmatch(_rel(r.source), e.get("source", "*")) and fnmatch.fnmatch(r.raw, e.get("ref", "*")):
                used[i] = True
                hit = True
                break
        (bl if hit else un).append(r)
    stale = [e for e, u in zip(entries, used) if not u]
    return un, bl, stale


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN, help=argparse.SUPPRESS)
    ap.add_argument("--check", action="store_true", help="exit 1 on any non-baselined missing reference")
    ap.add_argument("--list", action="store_true", help="print every reference and where it resolved")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not (args.check or args.list):
        ap.error("pass --check or --list")

    refs = scan(args.plugin)
    if args.list:
        for r in refs:
            print(f"{_rel(r.source)}:{r.line}  {r.raw}  ->  {_rel(r.resolved) if r.resolved else 'MISSING'}")
        return 0

    missing = [r for r in refs if r.resolved is None]
    stale: List[Dict] = []
    baselined: List[Ref] = []
    if not args.no_baseline and args.baseline.exists():
        missing, baselined, stale = apply_baseline(missing, json.loads(args.baseline.read_text(encoding="utf-8")))

    if args.json:
        print(json.dumps({
            "references": len(refs),
            "missing": [{"source": _rel(r.source), "line": r.line, "ref": r.raw, "skill": r.skill} for r in missing],
            "baselined": [{"source": _rel(r.source), "line": r.line, "ref": r.raw} for r in baselined],
            "stale_baseline_entries": stale,
        }, indent=2))
    else:
        for r in missing:
            print(f"ERROR  MISSING_REF  {_rel(r.source)}:{r.line}  `{r.raw}`")
        for e in stale:
            print(f"ERROR  STALE_BASELINE  entry matched nothing — remove it: {json.dumps(e)}")
        if baselined:
            print(f"baselined (known dead references, explained in {_rel(args.baseline)}): {len(baselined)}")
        ok = not missing and not stale
        print(f"\n{'PASS' if ok else 'FAIL'} — {len(refs)} reference(s) checked, "
              f"{len(missing)} missing, {len(baselined)} baselined, {len(stale)} stale baseline entr{'y' if len(stale) == 1 else 'ies'}")
    return 0 if (not missing and not stale) else 1


if __name__ == "__main__":
    sys.exit(main())
