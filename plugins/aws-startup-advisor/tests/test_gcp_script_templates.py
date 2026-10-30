"""Exercise the documented scripts with stub tools, without cloud access."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-scripts.md"
)
BLOCKS = re.findall(r"```bash\n(.*?)```", SOURCE.read_text(), re.DOTALL)


def block(marker: str) -> str:
    matches = [value for value in BLOCKS if marker in value]
    assert len(matches) == 1, marker
    return textwrap.dedent(matches[0])


def database_script() -> str:
    return "\n".join(
        block(marker)
        for marker in (
            "# Data migration",
            "# Cloud SQL → RDS data migration",
            "missing=()",
            "# Allocated disk is an upper bound",
            "# Tool: pg_dump/pg_restore",
        )
    )


@pytest.fixture
def runner(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = f"""#!{sys.executable}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if os.environ.get("STUB_FAIL") == name:
    sys.exit(7)
print("1" if name == "psql" else "stub-result")
"""
    for name in ("aws", "gcloud", "docker", "psql", "pg_dump", "pg_restore", "terraform"):
        path = tools / name
        path.write_text(stub)
        path.chmod(0o755)
    script = tmp_path / "migration/scripts/test.sh"
    script.parent.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    def run(text: str, *args: str, **extra: str):
        script.write_text(text)
        log.write_text("")
        env = {
            "PATH": f"{tools}:/usr/bin:/bin",
            "CALLS": str(log),
            "TMPDIR": str(tmp_path),
            **extra,
        }
        result = subprocess.run(
            ["bash", str(script), *args],
            cwd=unrelated,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls, script

    return run


def test_database_default_dry_run_needs_no_credentials_or_tools(runner):
    result, calls, _ = runner(database_script())
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert calls == []


@pytest.mark.parametrize("args", [("--dry-run",), ("--execute", "--dry-run")])
def test_unrecognized_or_ambiguous_arguments_do_not_execute(runner, args):
    result, calls, _ = runner(database_script(), *args)
    assert result.returncode == 2
    assert calls == []


def test_execute_reports_all_missing_inputs_before_running_tools(runner):
    result, calls, _ = runner(database_script(), "--execute")
    assert result.returncode == 1
    for name in ("SOURCE_HOST", "TARGET_HOST", "SOURCE_DB_PASSWORD", "TARGET_DB_PASSWORD", "DATABASE_NAME"):
        assert name in result.stdout
    assert calls == []


def test_database_preserves_exported_inputs_and_disables_psql_startup_files(runner):
    result, calls, _ = runner(
        database_script(),
        "--execute",
        SOURCE_HOST="source.example",
        TARGET_HOST="target.example",
        DATABASE_NAME="orders",
        SOURCE_DB_PASSWORD="source-test-password",
        TARGET_DB_PASSWORD="target-test-password",
    )
    assert result.returncode == 0, result.stderr
    assert [call[0] for call in calls] == ["psql", "pg_dump", "pg_restore"]
    assert "-X" in calls[0] and "ON_ERROR_STOP=1" in calls[0]
    assert "source.example" in calls[0] and "orders" in calls[0]
    assert "source.example" in calls[1] and "target.example" in calls[2]
    assert "--exit-on-error" in calls[2]
    assert "source-test-password" not in result.stdout + result.stderr
    assert "target-test-password" not in result.stdout + result.stderr
    dump = calls[1][calls[1].index("-f") + 1]
    assert not Path(dump).exists()


def test_failed_dump_stops_before_restore_and_cleans_up(runner):
    result, calls, _ = runner(
        database_script(),
        "--execute",
        SOURCE_HOST="source.example",
        TARGET_HOST="target.example",
        DATABASE_NAME="orders",
        SOURCE_DB_PASSWORD="source-test-password",
        TARGET_DB_PASSWORD="target-test-password",
        STUB_FAIL="pg_dump",
    )
    assert result.returncode == 7
    assert [call[0] for call in calls] == ["psql", "pg_dump"]
    assert not Path(calls[1][calls[1].index("-f") + 1]).exists()


def test_container_dry_run_does_not_fetch_account_or_inspect_cloud(runner):
    text = "\n".join(
        block(marker)
        for marker in (
            "# App migration:",
            'ECR_REGISTRY="${AWS_ACCOUNT_ID}',
            'echo "Listing ECR repositories',
        )
    )
    result, calls, _ = runner(text)
    assert result.returncode == 0, result.stderr
    assert calls == []


def test_secrets_dry_run_does_not_read_secret_values(runner):
    result, calls, _ = runner(block("# Secrets migration:"))
    assert result.returncode == 0, result.stderr
    assert calls == []


@pytest.mark.parametrize("failing_tool", ["aws", "terraform"])
def test_inventory_checks_preserve_failures_and_resolve_script_relative_paths(runner, failing_tool):
    result, calls, script = runner(
        block("# Post-migration validation"),
        S3_BUCKET="example-assets",
        STUB_FAIL=failing_tool,
    )
    assert result.returncode == 1
    assert "Do not proceed to cutover" in result.stderr
    assert calls[0] == [
        "terraform", f"-chdir={script.parent.parent}/terraform", "state", "list",
    ]


def test_successful_inventory_probes_do_not_claim_application_validation(runner):
    result, calls, _ = runner(block("# Post-migration validation"), S3_BUCKET="example-assets")
    assert result.returncode == 0, result.stderr
    assert calls
    assert "does not establish application health or data integrity" in result.stdout
