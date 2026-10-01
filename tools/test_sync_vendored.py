"""Tests for tools/sync-vendored.py — the vendored-copy parity gate.

Builds a throwaway plugins tree so the tests do not depend on (or mutate) the real
skills, then checks the real repository is clean as the last assertion.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "sync-vendored.py"


def _load():
    spec = importlib.util.spec_from_file_location("sync_vendored", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_vendored"] = mod
    spec.loader.exec_module(mod)
    return mod


sv = _load()


def _tree(tmp_path: Path) -> Path:
    plugins = tmp_path / "plugins"
    shared = plugins / "p" / "skills" / "shared"
    (shared / "dsl").mkdir(parents=True)
    (shared / "dsl" / "INTERPRETER.md").write_text("canonical v2\n")
    (shared / "pricing.json").write_text('{"a": 1}\n')
    vend = plugins / "p" / "skills" / "alpha" / "references" / "vendored"
    (vend / "dsl").mkdir(parents=True)
    (vend / "dsl" / "INTERPRETER.md").write_text("canonical v2\n")   # in sync
    (vend / "pricing.json").write_text('{"a": 0}\n')                  # drifted
    (vend / "orphan.md").write_text("no source\n")                   # no canonical
    (vend / "README.md").write_text("explanatory, never compared\n")
    # a skill that vendors nothing, and the shared dir itself, are both ignored
    (plugins / "p" / "skills" / "beta").mkdir()
    return plugins


def test_check_reports_drift_and_orphans_but_not_readme(tmp_path: Path):
    plugins = _tree(tmp_path)
    errors = sv.check_plugin(plugins / "p")
    joined = "\n".join(errors)
    assert "pricing.json: differs from" in joined
    assert "orphan.md: no canonical source" in joined
    assert "INTERPRETER.md" not in joined
    assert "README.md" not in joined
    assert len(errors) == 2


def test_sync_copies_canonical_over_drifted_and_leaves_orphans_as_errors(tmp_path: Path):
    plugins = _tree(tmp_path)
    copied, errors = sv.sync_plugin(plugins / "p")
    assert copied == 1
    vend = plugins / "p" / "skills" / "alpha" / "references" / "vendored"
    assert (vend / "pricing.json").read_text() == '{"a": 1}\n'
    assert len(errors) == 1 and "orphan.md" in errors[0]
    # after sync, only the orphan remains
    assert [e for e in sv.check_plugin(plugins / "p") if "orphan" not in e] == []


def test_cli_check_exit_codes(tmp_path: Path):
    plugins = _tree(tmp_path)
    r = subprocess.run([sys.executable, str(SCRIPT), "--check", "--plugins-root", str(plugins)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout
    (plugins / "p" / "skills" / "alpha" / "references" / "vendored" / "orphan.md").unlink()
    subprocess.run([sys.executable, str(SCRIPT), "--plugins-root", str(plugins)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(SCRIPT), "--check", "--plugins-root", str(plugins)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("PASS")


def test_real_repository_is_in_sync():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, r.stdout
    assert "vendored file(s) byte-identical" in r.stdout
