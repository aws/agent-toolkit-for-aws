"""Exercise research regression cases using only stubbed cloud/database tools."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-scripts.md"
DOCS = ROOT / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-docs.md"
BLOCKS = re.findall(r"```bash\n(.*?)```", SCRIPTS.read_text(), re.DOTALL)


def block(marker: str) -> str:
    matches = [value for value in BLOCKS if marker in value]
    assert len(matches) == 1, marker
    return matches[0]


def database_script(tool: str = "pgcopydb") -> str:
    return "\n".join(
        block(marker)
        for marker in (
            "# Data migration\n",
            "# Cloud SQL → RDS data migration",
            "missing=()",
            "# Offline-copy guard",
            "# Allocated disk is an upper bound",
            "# Tool: pgcopydb (database" if tool == "pgcopydb" else "# Tool: pg_dump/pg_restore",
            "# Data-integrity gate:",
        )
    )


@pytest.fixture
def run_script(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    script = tmp_path / "migration/scripts/test.sh"
    script.parent.mkdir(parents=True)
    log = tmp_path / "calls.jsonl"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    stub = f"""#!{sys.executable}
import json, os, pathlib, stat, sys
name = pathlib.Path(sys.argv[0]).name
record = {{"name": name, "args": sys.argv[1:],
           "has_password_override": "PGPASSWORD" in os.environ}}
passfile = os.environ.get("PGPASSFILE")
if passfile:
    path = pathlib.Path(passfile)
    record.update(passfile=passfile, passwords=path.read_text(),
                  mode=stat.S_IMODE(path.stat().st_mode),
                  auth_mode=stat.S_IMODE(path.parent.stat().st_mode))
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps(record) + "\\n")
if os.environ.get("FAIL_TOOL") == name:
    sys.exit(7)
print("12" if name == "psql" else "stubbed")
"""
    for name in ("aws", "gcloud", "terraform", "jq", "psql", "pgcopydb", "pg_dump", "pg_restore", "verify-data"):
        path = tools / name
        path.write_text(stub)
        path.chmod(0o755)

    def run(text: str, *args: str, **overrides: str):
        script.write_text(text)
        log.write_text("")
        env = {
            "PATH": f"{tools}:/usr/bin:/bin",
            "CALLS": str(log),
            "TMPDIR": str(tmp_path),
            "SOURCE_HOST": "source.example",
            "TARGET_HOST": "target.example",
            "SOURCE_DB_PASSWORD": "source-secret",
            "TARGET_DB_PASSWORD": "target-secret",
            "DATABASE_NAME": "orders",
            "SOURCE_WRITES_FROZEN": "yes",
            "TARGET_WRITES_FROZEN": "yes",
            "DATA_VERIFIER": str(tools / "verify-data"),
            **overrides,
        }
        result = subprocess.run(
            ["/bin/bash", str(script), *args],
            cwd=unrelated,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        records = [json.loads(line) for line in log.read_text().splitlines()]
        return result, records

    return run


def test_prerequisite_counter_survives_first_success_and_reports_all_checks(run_script):
    result, calls = run_script(block("# Prerequisite checks:"), "--execute")
    assert result.returncode == 0, result.stderr
    assert "5 passed, 0 failed" in result.stdout
    assert [call["name"] for call in calls] == ["aws"]


def test_prerequisite_first_api_failure_is_retained_and_blocks(run_script):
    result, _ = run_script(block("# Prerequisite checks:"), "--execute", FAIL_TOOL="aws")
    assert result.returncode == 1
    assert "4 passed, 1 failed" in result.stdout


@pytest.mark.parametrize("args", [(), ("--execute", "--final-sync"), ("--final-sync",)])
def test_offline_preview_and_unsupported_final_sync_never_connect(run_script, args):
    result, calls = run_script(database_script(), *args)
    assert result.returncode == (0 if not args else 2)
    assert calls == []


@pytest.mark.parametrize("missing", ["SOURCE_WRITES_FROZEN", "TARGET_WRITES_FROZEN", "DATA_VERIFIER"])
def test_missing_freeze_or_verifier_stops_before_database_access(run_script, missing):
    result, calls = run_script(database_script(), "--execute", **{missing: ""})
    assert result.returncode == 1
    assert "HOLD" in result.stderr
    assert calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("TARGET_HOST", "target.example:5432"),
        ("SOURCE_HOST", "postgresql://source.example/orders"),
        ("TARGET_HOST", "target.example host=other.example"),
        ("TARGET_PORT", "0"),
        ("TARGET_PORT", "65536"),
        ("SOURCE_PORT", "1;false"),
        ("TARGET_PORT", "123456789123456789"),
        ("SOURCE_DB_PASSWORD", "one\ntwo"),
        ("TARGET_DB_PASSWORD", "one\rtwo"),
        ("PGSSLMODE", "disable"),
        ("DATABASE_NAME", "host=unintended.example"),
        ("DATABASE_NAME", "postgresql://unintended.example/orders"),
    ],
)
def test_invalid_connections_fail_before_any_database_call(run_script, field, value):
    result, calls = run_script(database_script(), "--execute", **{field: value})
    assert result.returncode == 1, result.stderr
    assert "HOLD" in result.stderr
    assert calls == []


def test_special_credentials_use_restricted_passfile_without_entering_argv(run_script):
    source_secret = "source:@/%'\\password"
    target_secret = "target:@/%'\\password"
    result, calls = run_script(
        database_script(),
        "--execute",
        SOURCE_DB_PASSWORD=source_secret,
        TARGET_DB_PASSWORD=target_secret,
        DATABASE_NAME="ord'ers\\db",
        SOURCE_DB_USER="source'user",
        TARGET_DB_USER="target\\user",
        SOURCE_PORT="05432",
        TARGET_PORT="6543",
        PGPASSWORD="wrong-inherited-password",
        PGSSLMODE="verify-full",
    )
    assert result.returncode == 0, result.stderr
    assert [call["name"] for call in calls] == ["psql", "pgcopydb", "verify-data"]
    copy = calls[1]
    assert copy["args"][:2] == ["copy", "db"]
    source = copy["args"][copy["args"].index("--source") + 1]
    target = copy["args"][copy["args"].index("--target") + 1]
    assert "port=5432" in source
    assert "port=6543" in target
    assert "dbname='ord\\'ers\\\\db'" in source
    assert "user='source\\'user'" in source
    assert "user='target\\\\user'" in target
    assert "sslmode='verify-full'" in source
    assert copy["passwords"] == (
        "source.example:5432:ord'ers\\\\db:source'user:source\\:@/%'\\\\password\n"
        "target.example:6543:ord'ers\\\\db:target\\\\user:target\\:@/%'\\\\password\n"
    )
    assert copy["mode"] == 0o600
    assert copy["auth_mode"] == 0o700
    assert "-X" in calls[0]["args"]
    assert "ON_ERROR_STOP=1" in calls[0]["args"]
    rendered = result.stdout + result.stderr + json.dumps([call["args"] for call in calls])
    assert source_secret not in rendered and target_secret not in rendered
    assert not Path(copy["passfile"]).exists()
    assert not Path(copy["passfile"]).parent.exists()


@pytest.mark.parametrize("failing_tool", ["pgcopydb", "verify-data"])
def test_copy_or_verification_failure_blocks_success_and_removes_credentials(run_script, failing_tool):
    result, calls = run_script(database_script(), "--execute", FAIL_TOOL=failing_tool)
    assert result.returncode != 0
    assert "Offline copy and data verification passed" not in result.stdout
    if failing_tool == "pgcopydb":
        assert "verify-data" not in [call["name"] for call in calls]
    else:
        assert "Keep writers frozen and do not cut over" in result.stderr
    assert all(not Path(call["passfile"]).exists() for call in calls)


def test_dump_path_keeps_auth_until_verification_then_cleans_up(run_script):
    result, calls = run_script(database_script("pg_dump"), "--execute")
    assert result.returncode == 0, result.stderr
    assert [call["name"] for call in calls] == ["psql", "pg_dump", "pg_restore", "verify-data"]
    assert all(not Path(call["passfile"]).exists() for call in calls)
    assert all(not call["has_password_override"] for call in calls if call["name"] != "psql")


@pytest.mark.parametrize(
    "tool,failing_tool",
    [
        ("pgcopydb", ""),
        ("pgcopydb", "pgcopydb"),
        ("pgcopydb", "verify-data"),
        ("pg_dump", ""),
        ("pg_dump", "pg_dump"),
        ("pg_dump", "pg_restore"),
        ("pg_dump", "verify-data"),
    ],
)
def test_inherited_dump_path_is_preserved_on_success_and_failure(
    run_script, tmp_path, tool, failing_tool,
):
    sentinel = tmp_path / "unrelated-user-file"
    sentinel.write_text("preserve this data")
    result, calls = run_script(
        database_script(tool),
        "--execute",
        DUMP_FILE=str(sentinel),
        FAIL_TOOL=failing_tool,
    )
    assert result.returncode == (0 if not failing_tool else 1 if failing_tool == "verify-data" else 7)
    assert sentinel.read_text() == "preserve this data"
    assert all(not Path(call["passfile"]).parent.exists() for call in calls)
    dumps = [call for call in calls if call["name"] == "pg_dump"]
    for dump in dumps:
        owned_dump = Path(dump["args"][dump["args"].index("-f") + 1])
        assert owned_dump != sentinel
        assert not owned_dump.exists()


def test_same_database_is_rejected_even_when_port_has_leading_zero(run_script):
    result, calls = run_script(
        database_script(), "--execute", TARGET_HOST="source.example", TARGET_PORT="05432",
    )
    assert result.returncode == 1
    assert "different databases" in result.stderr
    assert calls == []


@pytest.mark.parametrize("execute", [False, True])
def test_large_or_unknown_database_hold_does_not_touch_source(run_script, execute):
    script = block("# Data migration\n") + block("# Large/unknown database:")
    result, calls = run_script(script, *(["--execute"] if execute else []))
    assert result.returncode == (1 if execute else 0)
    assert "HOLD" in result.stderr
    assert calls == []


def test_documented_protocol_requires_explicit_rollback_policy_and_real_data_gate():
    docs = DOCS.read_text()
    assert "user's informed acceptance recorded in preferences" in docs
    assert "RDS address output" in SCRIPTS.read_text()
    assert "the parser rejects `--final-sync`" in docs.lower()
    assert "inventory** checks" in docs
    assert "psql -X --no-password -v ON_ERROR_STOP=1" in docs
    assert "do not relabel a CLI failure as a registry failure" in docs
