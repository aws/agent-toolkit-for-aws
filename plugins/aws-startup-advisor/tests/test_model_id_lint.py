"""Reference lint for Bedrock model IDs against the lifecycle registry.

`scripts/model-id-lint.py` reads `skills/shared/ai/ai-model-lifecycle.md` and
fails when a retired model ID (excluded table row or Removed list) or a
fabricated dated Sonnet 4.6 / Opus 4.8 ID appears outside the catalog files.

Mutations run against a throwaway copy of the registry so the committed plugin
tree is never edited. Retired IDs are taken from the registry at runtime and
written only into that scratch tree — this file must not contain them, because
the lint scans every file under the plugin, including tests.

Run: ``uv run --with pytest python -m pytest plugins/aws-startup-advisor/tests/test_model_id_lint.py``
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "model-id-lint.py"
REGISTRY_REL = Path("skills/shared/ai/ai-model-lifecycle.md")

# Built by concatenation so this source does not contain a fabricated dated ID.
_FAB_SONNET = "claude-" + "sonnet-4-6" + "-" + "20250929"
_FAB_OPUS = "claude-" + "opus-4-8" + "-" + "20250929"
_FAB_ALLOW = (
    "skills/llm-to-bedrock/references/helpers/resolve-bedrock-model-id/"
    "resolve-bedrock-model-id.md"
)


def _load():
    spec = importlib.util.spec_from_file_location("model_id_lint", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run(plugin_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--plugin-root", str(plugin_root)],
        capture_output=True,
        text=True,
    )


def _seed(tmp_path: Path, registry_text: str | None = None) -> Path:
    root = tmp_path / "plugin"
    dest = root / REGISTRY_REL
    dest.parent.mkdir(parents=True)
    if registry_text is None:
        shutil.copyfile(PLUGIN_ROOT / REGISTRY_REL, dest)
    else:
        dest.write_text(registry_text, encoding="utf-8")
    return root


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _banned(plugin: Path) -> list[str]:
    mod = _load()
    banned, errors = mod.load_banned_ids(plugin)
    assert errors == [], errors
    assert banned, "registry parsed no retired IDs"
    return [model_id for model_id, _pattern in banned]


def _legacy_id() -> str:
    """A Legacy-table model ID that is still a valid target (not excluded)."""
    mod = _load()
    text = (PLUGIN_ROOT / REGISTRY_REL).read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        lower = line.lower()
        if "legacy" not in lower or "excluded" in lower:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        ids = mod._ID_IN_BACKTICKS.findall(cells[1])
        if ids:
            return ids[0]
    pytest.fail("registry has no legacy (non-excluded) model ID to use as a valid target")


def test_clean_registry_copy_passes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    result = _run(root)
    assert result.returncode == 0, result.stderr
    assert "model-id lint: OK" in result.stdout


def test_every_retired_id_fails_outside_the_catalog(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    for i, model_id in enumerate(_banned(PLUGIN_ROOT)):
        _write(root, f"skills/example/bad-{i}.md", f"recommend `{model_id}`\n")
    result = _run(root)
    assert result.returncode == 1, result.stdout
    for model_id in _banned(PLUGIN_ROOT):
        assert model_id in result.stderr, model_id


def test_glob_retired_id_matches_a_concrete_expansion(tmp_path: Path) -> None:
    globs = [model_id for model_id in _banned(PLUGIN_ROOT) if "*" in model_id]
    if not globs:
        pytest.skip("registry has no wildcard retired ID")
    model_id = globs[0]
    concrete = model_id.replace("*", "90b")
    root = _seed(tmp_path)
    _write(root, "skills/example/glob.md", f"recommend `{concrete}`\n")
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert model_id in result.stderr


def test_legacy_model_outside_exclusion_zone_is_allowed(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    _write(root, "skills/example/legacy.md", f"recommend `{_legacy_id()}`\n")
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_retired_id_allowed_in_both_pricing_caches(tmp_path: Path) -> None:
    model_id = _banned(PLUGIN_ROOT)[0]
    root = _seed(tmp_path)
    for rel in (
        "skills/gcp-to-aws/references/shared/pricing-cache.md",
        "skills/azure-to-aws/references/shared/pricing-cache.md",
    ):
        _write(root, rel, f"existing users may still see `{model_id}`\n")
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_retired_id_in_html_fixture_fails(tmp_path: Path) -> None:
    model_id = _banned(PLUGIN_ROOT)[0]
    root = _seed(tmp_path)
    _write(root, "fixtures/report.html", f"<p>{model_id}</p>\n")
    result = _run(root)
    assert result.returncode == 1
    assert "fixtures/report.html" in result.stderr


def test_fabricated_dated_id_fails_except_in_the_repair_helper(tmp_path: Path) -> None:
    blocked = _seed(tmp_path)
    _write(blocked, "skills/example/fab.md", f"use {_FAB_SONNET} or {_FAB_OPUS}\n")
    blocked_result = _run(blocked)
    assert blocked_result.returncode == 1
    assert "fabricated" in blocked_result.stderr

    allowed = _seed(tmp_path / "allowed")
    _write(allowed, _FAB_ALLOW, f"example of a broken id: {_FAB_SONNET}\n")
    allowed_result = _run(allowed)
    assert allowed_result.returncode == 0, allowed_result.stderr


def test_zero_parse_guardrail_fails(tmp_path: Path) -> None:
    stub = (
        "# registry\n"
        "| Model | Model ID | Status |\n"
        "| --- | --- | --- |\n"
        "**Removed:**\n"
        "- nothing listed\n"
    )
    root = _seed(tmp_path, stub)
    _write(root, "skills/example/ok.md", "no model here\n")
    result = _run(root)
    assert result.returncode == 1
    assert "ZERO" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_plugin_root_exits_2(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = _run(missing)
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_real_plugin_passes() -> None:
    result = _run(PLUGIN_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "retired IDs enforced" in result.stdout


def test_script_resolves_paths_inside_the_plugin() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent" in text
    assert '"plugins" / "aws-startup-advisor"' not in text
    assert "REPO_ROOT" not in text
