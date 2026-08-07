#!/usr/bin/env python3
"""Simulate how OpenClaw / Claude Code / Codex load a skill, and assert portability.

This check does not launch OpenClaw. Instead it reproduces the *documented
loading mechanics* that determine whether a skill works there, and checks the
agents-pay folder against them:

  1. Schema-less YAML frontmatter: unknown keys must parse without error, and
     `description` must be present (OpenClaw silently drops a skill without one).
  2. Folder flattening: `npx skills add` installs only the skill dir (and some
     backends fall back to a recursive copy). Any `../` reference outside the
     skill dir breaks. Simulated by copying the folder in isolation.
  3. No render-time shell execution: Claude Code executes !`cmd` / ```! blocks
     before the model sees content. A portable skill must contain none.
  4. Scripts must import and run from the copied-in-isolation folder, using only
     the stdlib plus declared third-party deps.

Exit code 0 means portable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Resolve the skill dir from this file's own location, so the check works from
# any checkout, any copy, and any working directory.
SKILL = Path(__file__).resolve().parent.parent

failures: list[str] = []
checks = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  [pass] {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        failures.append(label)


def parse_frontmatter(text: str) -> dict:
    """Mimic a permissive, schema-less frontmatter reader (OpenClaw's approach).

    Flattens nested maps the way OpenClaw does (objects get stringified), and
    accepts multi-line `>` block scalars, which the shipped parser handles even
    though the docs claim single-line only.
    """
    if not text.startswith("---\n"):
        raise ValueError("no frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    body = text[4:end]

    out: dict[str, str] = {}
    key: str | None = None
    for line in body.splitlines():
        if not line.strip():
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:", line):
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            out[key] = "" if v in (">", "|", ">-", "|-") else v
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


print(f"Simulating harness load of: {SKILL.name}\n")

# ---------------------------------------------------------------- 1. frontmatter
print("1. Schema-less frontmatter parsing (OpenClaw-style)")
text = (SKILL / "SKILL.md").read_text()
try:
    fm = parse_frontmatter(text)
    check(True, "frontmatter parses without error")
    check(bool(fm.get("description")), "description present (else silently dropped)")
    check(fm.get("name") == SKILL.name, f"name matches directory ({fm.get('name')})")
    check(len(fm.get("description", "")) >= 20, "description >= 20 chars (repo validator)")
    forbidden = [k for k in fm if k == "stages" or k.startswith("owner_")]
    check(not forbidden, "no CI-forbidden keys (stages/owner_*)", str(forbidden))
    # Unknown-to-OpenClaw keys must be harmless, not fatal.
    for k in ("allowed-tools", "metadata"):
        if k in fm:
            print(f"         (note: '{k}' parsed then ignored by OpenClaw — inert, not fatal)")
except Exception as e:  # noqa: BLE001
    check(False, "frontmatter parses without error", str(e))

# --------------------------------------------------------- 2. no render-time exec
print("\n2. No render-time shell execution (Claude Code executes these)")
md_files = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
bang_backtick = re.compile(r"(?<![`\w])!`[^`]+`")
bang_fence = re.compile(r"^\s*```!", re.MULTILINE)
for f in md_files:
    t = f.read_text()
    hits = bang_backtick.findall(t) + bang_fence.findall(t)
    check(not hits, f"{f.name}: no !`cmd` or ```! blocks", str(hits[:2]))

# ------------------------------------------------------------- 3. no ../ escapes
print("\n3. No references outside the skill directory (flattening-safe)")
for f in md_files:
    t = f.read_text()
    # Markdown links/targets that climb out of the skill dir.
    escapes = re.findall(r"\]\(\.\./[^)]*\)", t) + re.findall(r"(?m)^\s*(?:python3?\s+)?\.\./\S+", t)
    check(not escapes, f"{f.name}: no ../ path references", str(escapes[:2]))

# ------------------------------------------- 4. survives isolated (flattened) copy
print("\n4. Works after being copied in isolation (npx skills add / fs.cp fallback)")
with tempfile.TemporaryDirectory() as tmp:
    dest = Path(tmp) / "skills" / SKILL.name
    shutil.copytree(SKILL, dest)
    check(True, f"copied to isolated root {dest.parent}")

    # Every relative link must resolve inside the copy.
    missing = []
    for f in [dest / "SKILL.md", *sorted((dest / "references").glob("*.md"))]:
        for target in re.findall(r"\]\((?!https?:)([^)#][^)]*)\)", f.read_text()):
            if not (f.parent / target).exists():
                missing.append(f"{f.name} -> {target}")
    check(not missing, "all relative links resolve in the isolated copy", "; ".join(missing[:3]))

    # Scripts must import and the suite must pass from the copy.
    r = subprocess.run(
        [sys.executable, "test_x402_policy.py"],
        cwd=dest / "scripts", capture_output=True, text=True, timeout=180,
    )
    check(r.returncode == 0, "test suite passes from the isolated copy",
          r.stderr.strip().splitlines()[-1] if r.stderr else "")
    ran = re.search(r"Ran (\d+) tests", r.stderr or "")
    if ran:
        print(f"         ({ran.group(1)} tests executed)")

    r = subprocess.run(
        [sys.executable, "-c", "import x402_policy, x402_fetch; print('ok')"],
        cwd=dest / "scripts", capture_output=True, text=True, timeout=120,
    )
    check(r.returncode == 0, "x402_policy + x402_fetch import from the isolated copy",
          r.stderr.strip().splitlines()[-1] if r.stderr else "")

    r = subprocess.run(
        [sys.executable, "agents_pay_admin.py", "--help"],
        cwd=dest / "scripts", capture_output=True, text=True, timeout=120,
    )
    check(r.returncode == 0, "admin CLI runs from the isolated copy")

# ------------------------------------------------------------------ 5. dependencies
print("\n5. Runtime dependency surface")
imports: set[str] = set()
for py in sorted((SKILL / "scripts").glob("*.py")):
    # Only real import statements. A docstring line like "Dependencies: pip install
    # valkey" or "no runtime beyond Python" would otherwise register as a module, so
    # track triple-quoted blocks and skip their contents.
    in_docstring = False
    for line in py.read_text().splitlines():
        if line.count('"""') % 2 or line.count("'''") % 2:
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        m = re.match(r"\s*(?:import|from)\s+([A-Za-z_][\w.]*)", line)
        if m:
            imports.add(m.group(1).split(".")[0])
stdlib = set(sys.stdlib_module_names)
third_party = sorted(
    i for i in imports
    if i not in stdlib and not i.startswith("x402") and i != "agents_pay_admin"
)
print(f"         third-party: {third_party or 'none'}")
check(set(third_party) <= {"httpx", "bedrock_agentcore", "certifi"},
      "third-party deps limited to httpx / bedrock_agentcore / certifi", str(third_party))

print(f"\n{'=' * 62}")
if failures:
    print(f"PORTABILITY: FAILED — {len(failures)}/{checks} checks failed")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"PORTABILITY: PASSED — {checks}/{checks} checks")
sys.exit(0)
