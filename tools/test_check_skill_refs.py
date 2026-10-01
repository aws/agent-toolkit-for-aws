"""Tests for tools/check-skill-refs.py — the reference-path lint.

A throwaway plugin tree exercises each resolution rule and each skip rule; the last test
runs the real repository and requires PASS with no stale baseline entries.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "check-skill-refs.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_skill_refs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_skill_refs"] = mod
    spec.loader.exec_module(mod)
    return mod


csr = _load()


def _plugin(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugins" / "p"
    sk = plugin / "skills"
    (sk / "alpha" / "references" / "phases").mkdir(parents=True)
    (sk / "alpha" / "scripts").mkdir()
    (sk / "alpha" / "references" / "vendored" / "dsl").mkdir(parents=True)
    (sk / "shared" / "dsl").mkdir(parents=True)
    (sk / "shared" / "ai").mkdir()
    (sk / "gcp-to-aws" / "references" / "design-refs").mkdir(parents=True)
    (sk / "agent-advisor").mkdir()
    (sk / "beta" / "references").mkdir(parents=True)
    (plugin / "agents").mkdir()
    # targets
    (sk / "alpha" / "references" / "phases" / "design.md").write_text("x")
    (sk / "alpha" / "scripts" / "tool.py").write_text("x")
    (sk / "shared" / "dsl" / "INTERPRETER.md").write_text("x")
    (sk / "alpha" / "references" / "vendored" / "dsl" / "INTERPRETER.md").write_text(
        "see `references/vendored/state/phase-status.schema.json` and `shared/ai-guardrails.md`")
    (sk / "shared" / "ai" / "ai-guardrails.md").write_text("x")
    (sk / "shared" / "state.md").write_text("vendored at `references/vendored/state.md`")
    (sk / "gcp-to-aws" / "references" / "design-refs" / "ai.md").write_text("x")
    (sk / "beta" / "references" / "offers.md").write_text("x")
    (plugin / "agents" / "worker.md").write_text("validate with `scripts/tool.py`")
    return plugin


def _refs(plugin: Path, skill: str, text: str, name: str = "SKILL.md"):
    f = plugin / "skills" / skill / name
    f.write_text(text)
    return {r.raw: (r.resolved is not None) for r in csr.scan_file(f, plugin)}


def test_skill_relative_and_variable_prefixes_resolve(tmp_path: Path):
    plugin = _plugin(tmp_path)
    got = _refs(plugin, "alpha",
                "Load `references/phases/design.md`. Run `python3 \"<SKILL_BASE>/scripts/tool.py\"`. "
                "Also `$SKILL_BASE/scripts/tool.py`, `./scripts/tool.py`, `$PLUGIN_ROOT/skills/shared/dsl/INTERPRETER.md`, "
                "`${CLAUDE_PLUGIN_ROOT}/skills/alpha/scripts/tool.py`, and `../beta/references/offers.md`.")
    assert got == {
        "references/phases/design.md": True, "<SKILL_BASE>/scripts/tool.py": True,
        "$SKILL_BASE/scripts/tool.py": True, "./scripts/tool.py": True,
        "$PLUGIN_ROOT/skills/shared/dsl/INTERPRETER.md": True,
        "${CLAUDE_PLUGIN_ROOT}/skills/alpha/scripts/tool.py": True,
        "../beta/references/offers.md": True,
    }


def test_missing_reference_is_reported(tmp_path: Path):
    plugin = _plugin(tmp_path)
    got = _refs(plugin, "alpha", "Load `references/phases/nope.md` then `scripts/gone.py`.")
    assert got == {"references/phases/nope.md": False, "scripts/gone.py": False}


def test_run_artifacts_templates_urls_and_relative_outputs_are_not_references(tmp_path: Path):
    plugin = _plugin(tmp_path)
    got = _refs(plugin, "alpha",
                "Write `$MIGRATION_DIR/scripts/02-migrate-data.sh`; read `.migration/<run>/references/x.md`; "
                "see https://example.com/references/phases/design.md ; open `references/offers/<slug>.md`; "
                "then `./deploy.sh` and `../plan.md` and `scenarios/scenario-NNN.json`.")
    assert got == {}


def test_library_origin_files_resolve_against_shared(tmp_path: Path):
    """shared/ and vendored copies speak from the consuming skill's point of view."""
    plugin = _plugin(tmp_path)
    vend = plugin / "skills" / "alpha" / "references" / "vendored" / "dsl" / "INTERPRETER.md"
    got = {r.raw: r.resolved for r in csr.scan_file(vend, plugin)}
    # `shared/ai-guardrails.md` → skills/shared/ai/ai-guardrails.md (flattened dir); the
    # state schema is genuinely absent everywhere → MISSING
    assert got["shared/ai-guardrails.md"] is not None
    assert got["references/vendored/state/phase-status.schema.json"] is None
    shared_doc = plugin / "skills" / "shared" / "state.md"
    got2 = {r.raw: r.resolved for r in csr.scan_file(shared_doc, plugin)}
    assert got2["references/vendored/state.md"] is not None


def test_gcp_dependents_may_name_gcp_tree_and_agents_search_skills(tmp_path: Path):
    plugin = _plugin(tmp_path)
    got = _refs(plugin, "agent-advisor", "remap `design-refs/ai.md` → `$GCP_BASE/references/design-refs/ai.md`")
    assert got == {"design-refs/ai.md": True, "$GCP_BASE/references/design-refs/ai.md": True}
    agent = plugin / "agents" / "worker.md"
    got2 = {r.raw: (r.resolved is not None) for r in csr.scan_file(agent, plugin)}
    assert got2 == {"scripts/tool.py": True}


def test_baseline_ignore_vs_entries_and_stale(tmp_path: Path):
    plugin = _plugin(tmp_path)
    f = plugin / "skills" / "alpha" / "SKILL.md"
    f.write_text("`references/phases/nope.md` and `scripts/gone.py`")
    missing = [r for r in csr.scan_file(f, plugin) if r.resolved is None]
    un, bl, stale = csr.apply_baseline(missing, {
        "ignore": [{"source": "*", "ref": "scripts/gone.py", "reason": "generated"}],
        "entries": [{"source": "*alpha/SKILL.md", "ref": "references/phases/nope.md", "reason": "todo"},
                    {"source": "*", "ref": "never.md", "reason": "stale"}],
    })
    assert [r.raw for r in un] == []
    assert [r.raw for r in bl] == ["references/phases/nope.md"]
    assert len(stale) == 1 and stale[0]["ref"] == "never.md"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT)


def test_cli_exit_codes(tmp_path: Path):
    plugin = _plugin(tmp_path)
    (plugin / "skills" / "alpha" / "SKILL.md").write_text("`references/phases/nope.md`")
    r = _run("--check", "--plugin", str(plugin), "--no-baseline", "--json")
    assert r.returncode == 1
    assert json.loads(r.stdout)["missing"][0]["ref"] == "references/phases/nope.md"
    (plugin / "skills" / "alpha" / "SKILL.md").write_text("`references/phases/design.md`")
    # the fixture tree's vendored INTERPRETER.md carries one deliberately dead reference
    (plugin / "skills" / "alpha" / "references" / "vendored" / "dsl" / "INTERPRETER.md").unlink()
    r = _run("--check", "--plugin", str(plugin), "--no-baseline")
    assert r.returncode == 0 and r.stdout.strip().endswith("0 stale baseline entries")


def test_real_repository_passes_with_no_stale_entries():
    r = _run("--check", "--json")
    assert r.returncode == 0, r.stdout
    report = json.loads(r.stdout)
    assert report["missing"] == []
    assert report["stale_baseline_entries"] == []
    assert report["references"] > 500
