"""Freshness gate for the Bedrock model-lifecycle registry.

`scripts/model-staleness.py` reads the canonical
`skills/shared/ai/ai-model-lifecycle.md`, checks its freshness contract
(`**Last updated**` / `**Staleness window**`), and checks that every vendored
copy under `skills/*/references/vendored/ai/` is byte-identical. These tests
pin the two failure classes the script promises:

- hard (drift, missing/malformed contract, future date, missing canonical or
  required vendored copy) exits 1 with AND without ``--strict``;
- stale (snapshot aged past its window) exits 0 by default and 1 under
  ``--strict``.

Every mutation runs against a throwaway copy of the registry files so the
real plugin tree is never touched. The last test runs the script against the
real plugin and must pass — that is the gate itself.

Run: ``uv run --with pytest python -m pytest plugins/aws-startup-advisor/tests/test_model_staleness.py``
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "model-staleness.py"
CANONICAL = Path("skills/shared/ai/ai-model-lifecycle.md")
VENDORED = (
    Path("skills/gcp-to-aws/references/vendored/ai/ai-model-lifecycle.md"),
    Path("skills/azure-to-aws/references/vendored/ai/ai-model-lifecycle.md"),
)
ALL_COPIES = (CANONICAL, *VENDORED)

LAST_UPDATED_LINE = re.compile(r"^\*\*Last updated:\*\* .*$", re.MULTILINE)
WINDOW_LINE = re.compile(r"^\*\*Staleness window:\*\* .*$", re.MULTILINE)


def _run(plugin_root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--plugin-root", str(plugin_root), *flags],
        capture_output=True,
        text=True,
    )


def _seed(tmp_path: Path) -> Path:
    """Copy just the registry files (canonical + vendored) into a scratch plugin tree."""
    root = tmp_path / "plugin"
    for rel in ALL_COPIES:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PLUGIN_ROOT / rel, dst)
    return root


def _rewrite_all(root: Path, pattern: re.Pattern[str], replacement: str) -> None:
    """Apply the same edit to canonical and every vendored copy so they stay identical."""
    for rel in ALL_COPIES:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        assert pattern.search(text), f"{rel}: pattern {pattern.pattern!r} not found"
        path.write_text(pattern.sub(replacement, text, count=1), encoding="utf-8")


def _set_last_updated(root: Path, when: date) -> None:
    _rewrite_all(root, LAST_UPDATED_LINE, f"**Last updated:** {when.isoformat()}")


# --- clean -------------------------------------------------------------------


def test_clean_tree_passes_in_both_modes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=5))
    for flags in ((), ("--strict",)):
        result = _run(root, *flags)
        assert result.returncode == 0, result.stderr
        assert "fresh and in sync" in result.stdout


# --- hard failures: fail with and without --strict ---------------------------


def test_drifted_vendored_copy_fails_always(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=5))
    drifted = root / VENDORED[0]
    drifted.write_text(drifted.read_text(encoding="utf-8") + "\n<!-- drift -->\n", encoding="utf-8")
    for flags in ((), ("--strict",)):
        result = _run(root, *flags)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "DRIFTED" in result.stderr
        assert str(VENDORED[0]) in result.stderr


def test_missing_last_updated_line_fails(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _rewrite_all(root, LAST_UPDATED_LINE, "")
    result = _run(root)
    assert result.returncode == 1
    assert "freshness contract is missing" in result.stderr


def test_missing_staleness_window_line_fails(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=5))
    _rewrite_all(root, WINDOW_LINE, "")
    result = _run(root)
    assert result.returncode == 1
    assert "freshness contract is incomplete" in result.stderr


def test_non_calendar_date_fails_without_traceback(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _rewrite_all(root, LAST_UPDATED_LINE, "**Last updated:** 2026-13-40")
    result = _run(root)
    assert result.returncode == 1
    assert "not a real calendar date" in result.stderr
    assert "Traceback" not in result.stderr


def test_future_date_fails_in_both_modes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() + timedelta(days=30))
    for flags in ((), ("--strict",)):
        result = _run(root, *flags)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "in the future" in result.stderr


def test_deleted_required_vendored_copy_fails_in_both_modes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=5))
    (root / VENDORED[1]).unlink()
    for flags in ((), ("--strict",)):
        result = _run(root, *flags)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "MISSING" in result.stderr
        assert str(VENDORED[1]) in result.stderr


def test_deleted_canonical_with_surviving_copies_fails(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=5))
    (root / CANONICAL).unlink()
    for flags in ((), ("--strict",)):
        result = _run(root, *flags)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "canonical" in result.stderr and "MISSING" in result.stderr
        assert "NO freshness gate" in result.stderr


def test_plugin_with_no_registry_at_all_is_exempt(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "skills").mkdir(parents=True)
    result = _run(root)
    assert result.returncode == 0, result.stderr


# --- stale: warn-only by default, fails under --strict -----------------------


def test_stale_date_warns_by_default_and_fails_strict(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _set_last_updated(root, date.today() - timedelta(days=400))

    default = _run(root)
    assert default.returncode == 0, default.stderr
    assert "WARN" in default.stderr and "STALE" in default.stderr
    assert "warn-only" in default.stdout

    strict = _run(root, "--strict")
    assert strict.returncode == 1
    assert "ERROR" in strict.stderr and "STALE" in strict.stderr


# --- the real plugin ---------------------------------------------------------


def test_real_plugin_registry_is_in_sync() -> None:
    """Drift / contract check against the committed tree. Staleness is reported
    warn-only here so an aged snapshot does not fail this suite; run the script
    with ``--strict`` to gate on it."""
    result = _run(PLUGIN_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_plugin_copies_are_byte_identical() -> None:
    canonical = (PLUGIN_ROOT / CANONICAL).read_bytes()
    for rel in VENDORED:
        assert (PLUGIN_ROOT / rel).read_bytes() == canonical, f"{rel} drifted from {CANONICAL}"


def test_script_resolves_paths_inside_the_plugin() -> None:
    """The gate must not reach outside plugins/aws-startup-advisor/."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent" in text
    assert "REPO_ROOT" not in text
    assert 'Path("skills/shared/ai/ai-model-lifecycle.md")' in text


@pytest.mark.parametrize("rel", ALL_COPIES)
def test_registry_prose_names_the_plugin_local_gate(rel: Path) -> None:
    text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
    assert "scripts/model-staleness.py" in text
    assert "tools/model-staleness.py" not in text
