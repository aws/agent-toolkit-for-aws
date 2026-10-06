"""Tests for sync-vendored.py — the vendored-copy parity gate.

Builds a throwaway plugin tree so the tests do not depend on (or mutate) the real
skills, then checks the real plugin is clean as the last assertion.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "tools" / "sync-vendored.py"


def _load():
    spec = importlib.util.spec_from_file_location("sync_vendored", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_vendored"] = mod
    spec.loader.exec_module(mod)
    return mod


sv = _load()


def _tree(tmp_path: Path) -> Path:
    plugin = tmp_path / "p"
    shared = plugin / "skills" / "shared"
    (shared / "dsl").mkdir(parents=True)
    (shared / "dsl" / "INTERPRETER.md").write_text("canonical v2\n")
    (shared / "pricing.json").write_text('{"a": 1}\n')
    vend = plugin / "skills" / "alpha" / "references" / "vendored"
    (vend / "dsl").mkdir(parents=True)
    (vend / "dsl" / "INTERPRETER.md").write_text("canonical v2\n")   # in sync
    (vend / "pricing.json").write_text('{"a": 0}\n')                  # drifted
    (vend / "orphan.md").write_text("no source\n")                   # no canonical
    (vend / "README.md").write_text(
        "# Vendored\n\n"
        "| Vendored path | Canonical source |\n"
        "| --- | --- |\n"
        "| `dsl/INTERPRETER.md` | `skills/shared/dsl/INTERPRETER.md` |\n"
        "| `pricing.json` | `skills/shared/pricing.json` |\n"
        "| `orphan.md` | `skills/shared/orphan.md` |\n")
    # a skill that vendors nothing, and the shared dir itself, are both ignored
    (plugin / "skills" / "beta").mkdir()
    return plugin


def test_check_reports_drift_and_orphans_but_not_readme(tmp_path: Path):
    plugin = _tree(tmp_path)
    errors = sv.check_plugin(plugin)
    joined = "\n".join(errors)
    assert "pricing.json: differs from" in joined
    assert "orphan.md: no canonical source" in joined
    assert "INTERPRETER.md" not in joined
    assert "README.md" not in joined
    assert len(errors) == 2


def test_sync_copies_canonical_over_drifted_and_leaves_orphans_as_errors(tmp_path: Path):
    plugin = _tree(tmp_path)
    copied, errors = sv.sync_plugin(plugin)
    assert copied == 1
    vend = plugin / "skills" / "alpha" / "references" / "vendored"
    assert (vend / "pricing.json").read_text() == '{"a": 1}\n'
    assert len(errors) == 1 and "orphan.md" in errors[0]
    # after sync, only the orphan remains
    assert [e for e in sv.check_plugin(plugin) if "orphan" not in e] == []


def test_deleted_copy_is_caught_via_readme_table(tmp_path: Path):
    """Review probe on #386: deleting a vendored copy left check_plugin at 0 errors because
    it only walked files that still existed. The README table is the record of intent."""
    plugin = _tree(tmp_path)
    vend = plugin / "skills" / "alpha" / "references" / "vendored"
    (vend / "dsl" / "INTERPRETER.md").unlink()
    errors = sv.check_manifest(plugin)
    assert any("dsl/INTERPRETER.md" in e and "missing on disk" in e for e in errors), errors
    # sync restores it from canonical
    copied, _ = sv.sync_plugin(plugin)
    assert (vend / "dsl" / "INTERPRETER.md").read_text() == "canonical v2\n"
    assert copied >= 1
    assert not any("missing on disk" in e for e in sv.check_manifest(plugin))


def test_unlisted_copy_and_wrong_canonical_path_are_caught(tmp_path: Path):
    plugin = _tree(tmp_path)
    vend = plugin / "skills" / "alpha" / "references" / "vendored"
    (vend / "extra.md").write_text("x\n")
    readme = vend / "README.md"
    readme.write_text(readme.read_text().replace("`skills/shared/pricing.json`", "`skills/other/pricing.json`"))
    errors = sv.check_manifest(plugin)
    assert any("extra.md" in e and "not listed" in e for e in errors), errors
    assert any("pricing.json" in e and "expected `skills/shared/pricing.json`" in e for e in errors), errors


def test_new_shared_file_nobody_vendors_is_not_an_error(tmp_path: Path):
    """Documented limit, pinned so the README wording stays honest: a brand-new
    skills/shared/ file that no skill vendors is NOT drift."""
    plugin = _tree(tmp_path)
    (plugin / "skills" / "shared" / "brand-new.md").write_text("new\n")
    (plugin / "skills" / "alpha" / "references" / "vendored" / "orphan.md").unlink()
    readme = plugin / "skills" / "alpha" / "references" / "vendored" / "README.md"
    readme.write_text("\n".join(l for l in readme.read_text().splitlines() if "orphan" not in l) + "\n")
    (plugin / "skills" / "alpha" / "references" / "vendored" / "pricing.json").write_text('{"a": 1}\n')
    assert sv.check_plugin(plugin) == []
    assert sv.check_manifest(plugin) == []


def test_cli_check_exit_codes(tmp_path: Path):
    plugin = _tree(tmp_path)
    r = subprocess.run([sys.executable, str(SCRIPT), "--check", "--plugin-root", str(plugin)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout
    vend = plugin / "skills" / "alpha" / "references" / "vendored"
    (vend / "orphan.md").unlink()
    readme = vend / "README.md"
    readme.write_text("\n".join(l for l in readme.read_text().splitlines() if "orphan" not in l) + "\n")
    subprocess.run([sys.executable, str(SCRIPT), "--plugin-root", str(plugin)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(SCRIPT), "--check", "--plugin-root", str(plugin)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("PASS")


def test_plugin_without_a_skills_directory_is_skipped(tmp_path: Path):
    """Review finding on #386: `--check` called skills.iterdir() before the is_dir() filter,
    so a plugin root with no skills/ raised FileNotFoundError. Pinned behaviorally: an
    empty plugin root (no skills/ at all) must pass cleanly, not crash."""
    plugin = tmp_path / "mcp-only"
    plugin.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), "--check", "--plugin-root", str(plugin)],
                       capture_output=True, text=True)
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0 and "PASS" in r.stdout


def test_real_plugin_is_in_sync():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=PLUGIN_ROOT)
    assert r.returncode == 0, r.stdout
    assert "vendored file(s) byte-identical" in r.stdout and "README tables" in r.stdout
