"""Writer regression coverage for emit-plan-json.py.

The web-import schema types runId as a lowercase-canonical UUID, but the state
schema (and native `uuidgen` on macOS) can carry an uppercase UUID. The writer
must lowercase a UUID-shaped run_id at the handoff boundary so the emitted plan
still imports. This anchors that canonicalization against a real golden run.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
WRITER = PLUGIN_ROOT / "scripts" / "emit-plan-json.py"
GOLDEN = PLUGIN_ROOT / "fixtures" / "gcp-decision-gate" / "after-decide-complete"


def _emit(run: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(WRITER), "--migration-dir", str(run)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"writer exited {result.returncode}: {result.stderr}"
    plan = run / "plan.json"
    assert plan.exists(), f"writer did not emit plan.json: {result.stdout}"
    return json.loads(plan.read_text())


def _seed(tmp_path: Path, run_id: str) -> Path:
    run = tmp_path / "run"
    shutil.copytree(GOLDEN, run)
    status_path = run / ".phase-status.json"
    status = json.loads(status_path.read_text())
    status["run_id"] = run_id
    status_path.write_text(json.dumps(status, indent=2))
    return run


def test_uppercase_uuid_run_id_is_lowercased(tmp_path: Path) -> None:
    upper = "8C1E4F2A-3B6D-4A7E-9F10-5D2C8B7A6E41"
    data = _emit(_seed(tmp_path, upper))
    assert data["runId"] == upper.lower(), f"runId not lowercased: {data.get('runId')!r}"


def test_lowercase_uuid_run_id_is_unchanged(tmp_path: Path) -> None:
    lower = "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"
    data = _emit(_seed(tmp_path, lower))
    assert data["runId"] == lower, f"runId altered: {data.get('runId')!r}"


def test_heroku_skill_writer_matches_plugin_copy() -> None:
    """heroku-to-aws invokes the writer from its own scripts/ dir so a standalone
    ``npx skills add --skill heroku-to-aws`` install (which carries only the skill
    tree, not plugin-root scripts/) can still emit the handoff plan. That skill copy
    must stay byte-identical to the shared plugin-level writer — this guards the two
    from drifting, since nothing else keeps them in sync."""
    skill_copy = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "emit-plan-json.py"
    assert skill_copy.exists(), f"heroku skill writer missing: {skill_copy}"
    assert skill_copy.read_bytes() == WRITER.read_bytes(), (
        "heroku skill emit-plan-json.py has drifted from the plugin-level copy; "
        "re-copy plugins/aws-startup-advisor/scripts/emit-plan-json.py"
    )
