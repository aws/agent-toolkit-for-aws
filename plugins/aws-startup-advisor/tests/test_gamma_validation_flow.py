"""Run the documented Generate gate from a standalone, extracted gamma package."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import pytest


PLUGIN = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gamma_validation_builder", PLUGIN / "scripts/build-gamma-skillset.py"
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture(scope="module", params=builder.SUPPORTED_SKILLS)
def extracted(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("extracted gamma")
    archive = directory / "candidate.zip"
    builder.build_archive(PLUGIN, request.param, archive)
    package = directory / "package"
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(package)
    return request.param, package


def test_documented_gate_runs_and_rejects_conflict(extracted, tmp_path):
    skill, package = extracted
    root = package / "skills" / skill
    instructions = (root / "references/phases/generate/generate.md").read_text()
    match = re.search(r'python3 "([^"]+/validate-migration-artifacts\.py)"', instructions)
    assert match, "Generate must call the actual artifact checker"
    checker = Path(match[1].replace("<SKILL_BASE>", str(root))).resolve()
    assert checker.is_relative_to(package)
    assert checker.is_file()
    assert "ARTIFACTS_OK" in instructions
    assert "GATE_FAIL" in instructions

    run = tmp_path / "migration"
    terraform = run / "terraform"
    terraform.mkdir(parents=True)
    config = """resource "aws_db_instance" "orders" {
  engine = "postgres"
  storage_encrypted = true
  publicly_accessible = false
  backup_window = "03:00-03:30"
  maintenance_window = "sun:04:00-sun:04:30"
}
"""
    path = terraform / "database.tf"
    path.write_text(config)
    flags = []
    if skill == "heroku-to-aws":
        # Use the same trusted template that the source instructs Generate to
        # copy. The gate syntax-checks it; no database client is executed.
        source = (root / "references/phases/generate/generate-docs.md").read_text()
        script = source.split("### 3A: PostgreSQL Migration Script", 1)[1]
        script = script.split("```bash\n", 1)[1].split("\n```", 1)[0] + "\n"
        (run / "scripts").mkdir()
        (run / "scripts/migrate-postgres.sh").write_text(script)
        flags.append("--require-postgres-script")
    report = run / "artifact-validation-status.json"
    unrelated = tmp_path / "unrelated working directory"
    unrelated.mkdir()
    command = [sys.executable, str(checker), str(run), *flags, "--json", str(report)]
    good = subprocess.run(command, cwd=unrelated, capture_output=True, text=True)
    assert good.returncode == 0, good.stdout + good.stderr
    assert json.loads(report.read_text())["artifact_status"] == "ARTIFACTS_OK"

    path.write_text(config.replace("sun:04:00-sun:04:30", "sun:03:00-sun:03:30"))
    before = path.read_bytes()
    bad = subprocess.run(command, cwd=unrelated, capture_output=True, text=True)
    assert bad.returncode == 1
    result = json.loads(report.read_text())
    assert result["artifact_status"] == "ARTIFACTS_FAIL"
    assert any(item["rule"] == "rds_windows_overlap" for item in result["findings"])
    assert path.read_bytes() == before
    assert not (run / ".phase-status.json").exists()
