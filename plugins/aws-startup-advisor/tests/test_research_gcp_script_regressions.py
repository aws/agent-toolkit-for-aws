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


ZERO_DOWNTIME_MARKERS = (
    "# Data migration\n",
    "# Cloud SQL → RDS data migration",
    "# Zero-downtime requested:",
    "missing=()",
    "# Offline-downtime acknowledgement:",
    "# Offline-copy guard",
    "# Allocated disk is an upper bound",
    "# Tool: pg_dump/pg_restore",
    "# Data-integrity gate:",
)


def zero_downtime_script() -> str:
    return "\n".join(block(marker) for marker in ZERO_DOWNTIME_MARKERS)


def zero_downtime_notice() -> str:
    return block("# Zero-downtime requested:")


@pytest.mark.parametrize("execute", [False, True])
def test_zero_downtime_notice_names_reason_and_prerequisites_and_never_exits(run_script, execute):
    script = block("# Data migration\n") + zero_downtime_notice()
    result, calls = run_script(script, *(["--execute"] if execute else []))
    assert result.returncode == 0
    assert "HOLD [zero-downtime-requested]" in result.stderr
    for needle in (
        "DMS MySQL source requirements", "confirm which your task type needs", "BACKUP_ADMIN",
        "cloudsql.logical_decoding", "max_replication_slots", "max_wal_senders", "restarts",
        "REPLICATION attribute", "cloudsqlsuperuser", "primary key or replica identity",
        "partition operations are not replicated", "binlog_format ROW", "binlog_row_image FULL",
        "binlog_expire_logs_seconds 86400", "binlog_checksum NONE", "REPLICATION SLAVE",
        "TRIGGER", "DMS replication instance", "AWS DMS documentation",
        "confirm Cloud SQL flag names in current Google Cloud documentation",
        "ACCEPT_OFFLINE_DOWNTIME=yes", "Downtime grows with database size",
    ):
        assert needle in result.stderr, needle
    assert calls == []


def test_zero_downtime_missing_input_list_includes_the_acknowledgement_in_one_message(run_script):
    instruction = SCRIPTS.read_text()
    match = re.search(r"reads `(for v in [^`]*ACCEPT_OFFLINE_DOWNTIME; do)`", instruction)
    assert match, "instruction must show the zero-downtime missing-input loop"
    generic = "for v in SOURCE_HOST TARGET_HOST SOURCE_DB_PASSWORD TARGET_DB_PASSWORD DATABASE_NAME; do"
    script = zero_downtime_script()
    assert generic in script
    script = script.replace(generic, match.group(1))
    result, calls = run_script(script, "--execute", DATABASE_NAME="", ACCEPT_OFFLINE_DOWNTIME="")
    assert result.returncode == 1
    assert "set these first" in result.stdout
    assert "DATABASE_NAME ACCEPT_OFFLINE_DOWNTIME" in result.stdout
    assert "HOLD [zero-downtime-requested]: set ACCEPT" not in result.stderr
    assert calls == []
def test_generic_blocks_carry_no_zero_downtime_text():
    for marker in ("missing=()", "# Cloud SQL → RDS data migration"):
        assert "zero-downtime" not in block(marker) and "ACCEPT_OFFLINE_DOWNTIME" not in block(marker)
def test_zero_downtime_small_postgres_dry_run_shows_notice_and_copy_steps(run_script):
    result, calls = run_script(zero_downtime_script())
    assert result.returncode == 0, result.stderr
    assert "HOLD [zero-downtime-requested]" in result.stderr
    assert "[DRY RUN] Would export from Cloud SQL using pg_dump" in result.stdout
    assert "[DRY RUN] Would import to RDS using pg_restore" in result.stdout
    assert calls == []


def test_zero_downtime_execute_needs_explicit_offline_acknowledgement(run_script):
    for value in ("", "no", "true"):
        result, calls = run_script(zero_downtime_script(), "--execute", ACCEPT_OFFLINE_DOWNTIME=value)
        assert result.returncode == 1, value
        assert "ACCEPT_OFFLINE_DOWNTIME=yes" in result.stderr
        assert calls == [], value
    result, calls = run_script(zero_downtime_script(), "--execute", ACCEPT_OFFLINE_DOWNTIME="yes")
    assert result.returncode == 0, result.stderr
    assert [call["name"] for call in calls] == ["psql", "pg_dump", "pg_restore", "verify-data"]


def test_non_zero_downtime_small_postgres_output_is_unchanged(run_script):
    script = database_script("pg_dump")
    assert "ACCEPT_OFFLINE_DOWNTIME:-" not in script and 'echo "HOLD [zero-downtime' not in script
    dry, dry_calls = run_script(script)
    assert dry.returncode == 0 and dry_calls == []
    assert dry.stderr == ""
    assert dry.stdout == (
        "Mode: DRY RUN\n=== Database Migration: Cloud SQL → RDS ===\n"
        "SKIP: actual-size check runs in execute mode with source credentials.\n"
        "[DRY RUN] Would export from Cloud SQL using pg_dump: orders\n"
        "[DRY RUN] Would import to RDS using pg_restore: target.example\n"
        "DRY RUN: copy is offline; a complete data verifier is required before execution.\n"
    )
    result, calls = run_script(script, "--execute")
    assert result.returncode == 0, result.stderr
    assert "zero-downtime-requested" not in result.stderr + result.stdout
    assert [call["name"] for call in calls] == ["psql", "pg_dump", "pg_restore", "verify-data"]


def _routing_texts() -> tuple[str, str]:
    text = SCRIPTS.read_text()
    start = text.index("Read `preferences.json` → `design_constraints.cutover_strategy` first.")
    paragraph = text[start:text.index("**Inventory cross-check", start)]
    heading = next(line for line in text.splitlines() if line.startswith("**If `cutover_strategy` is"))
    return paragraph, heading


def heading_section() -> str:
    text = SCRIPTS.read_text()
    _, heading = _routing_texts()
    start = text.index(heading)
    return text[start:text.index("```bash", start)]
def test_generate_routes_zero_downtime_to_the_named_notice():
    paragraph, heading = _routing_texts()
    for name, text in (("instruction paragraph", paragraph), ("block heading", heading)):
        assert "`zero-downtime`" in text, name
    assert "`zero-downtime-requested`" in paragraph
    assert "any engine" in heading
    assert "For the supported PostgreSQL bands (`\"<10GB\"`, `\"10-100GB\"`, `\"100-500GB\"`) with" in SCRIPTS.read_text()
    assert "the offline copy is still generated" in paragraph
    assert "do not emit connection setup" not in heading_section()
    assert "ACCEPT_OFFLINE_DOWNTIME=yes" in paragraph
    docs = DOCS.read_text()
    assert "design_constraints.cutover_strategy` is `zero-downtime`" in docs
    assert "HOLD [zero-downtime-requested]" in docs
    assert "ACCEPT_OFFLINE_DOWNTIME=yes" in docs
    assert "only the named HOLD above applies" in docs


def test_zero_downtime_notice_adds_no_replication_path():
    notice = zero_downtime_notice()
    allowed = (
        'echo "  - A network path from the AWS DMS replication instance to Cloud SQL '
        '(authorized network or private connectivity)" >&2'
    )
    assert allowed in notice.splitlines()
    rest = "\n".join(line for line in notice.splitlines() if line != allowed)
    # Prose mentions of DMS as a documentation source or a task count are not commands.
    for phrase in ("AWS DMS documentation", "concurrent DMS tasks", "DMS ignores", "DMS 3.4.7", "DMS MySQL source", "DMS homogeneous"):
        rest = rest.replace(phrase, "")
    assert not re.search(r"(?i)\b(dms|pgcopydb|pg_dump|psql|replication slot)\b", rest)


def test_zero_downtime_notice_gives_a_firestore_source_only_the_hold():
    notice = zero_downtime_notice()
    lines = notice.splitlines()
    hold = next(i for i, line in enumerate(lines) if 'echo "HOLD [zero-downtime-requested]' in line)
    gate = next(i for i, line in enumerate(lines) if line.startswith("# PostgreSQL or MySQL source only"))
    header = next(i for i, line in enumerate(lines) if 'echo "Prerequisites for a future online migration' in line)
    # Everything that points at an online route sits after the PostgreSQL/MySQL-only gate, so a Firestore source keeps the HOLD alone.
    assert hold < gate < header
    firestore_output = "\n".join(lines[: gate]).replace("\n", " ")
    assert "Cloud SQL" not in firestore_output and "DMS" not in firestore_output.replace("no tested replication workflow", "")
    for text in (SCRIPTS.read_text(), DOCS.read_text()):
        flat = " ".join(text.split())
        assert "Firestore is not Cloud SQL and is not a DMS source" in flat
    scripts = " ".join(SCRIPTS.read_text().split())
    assert "emit only the first `HOLD [zero-downtime-requested]` line: no prerequisite lines" in scripts
    assert "for a Firestore or other non-DMS source, the HOLD line alone and no prerequisite lines" in scripts
    assert "only for a PostgreSQL or MySQL source. For Firestore" in " ".join(DOCS.read_text().split())
def test_clarify_does_not_promise_prerequisites_to_every_zero_downtime_source() -> None:
    clarify = " ".join((ROOT / "skills/gcp-to-aws/references/phases/clarify/clarify-global.md").read_text().split())
    assert "Generate lists the DMS prerequisites for a PostgreSQL or MySQL source, and other sources get only the HOLD" in clarify
    assert "with the DMS prerequisites for a PostgreSQL or MySQL source, and the HOLD alone for other sources" in clarify
    assert "(Generate lists the prerequisites;" not in clarify
    assert "HOLD [zero-downtime-requested] with prerequisites" not in clarify
def test_existing_holds_keep_their_text_and_gain_the_reason_code_in_instructions():
    assert 'echo "HOLD: size and migration-window requirements need a reviewed data migration plan." >&2' in block("# Large/unknown database:")
    assert 'echo "HOLD: generate and verify a source/target-specific data migration adapter." >&2' in block("# Non-PostgreSQL data migration")
    text = SCRIPTS.read_text()
    assert text.count("begins `HOLD [zero-downtime-requested]:` instead of `HOLD:`") == 2
    assert text.count("without its\nfirst `HOLD [zero-downtime-requested]` line") == 1
    assert text.count("and without its first `HOLD [zero-downtime-requested]` line") == 1


STALE_PHRASES = (
    "DMS required", "AWS DMS required", "DMS fallback", "falls back to DMS", "default to pgcopydb",
    "Default to pgcopydb", "DMS-versus", "pgcopydb vs DMS", "wal_level=logical",
    "live replication via DMS is required", "pgcopydb / DMS",
)
STALE_SURFACES = (
    "design-refs/database.md",
    "phases/clarify/clarify-global.md",
    "phases/clarify/clarify-assemble.md",
    "phases/clarify/clarify-database.md",
    "shared/schema-preferences.md",
)


@pytest.mark.parametrize("surface", STALE_SURFACES)
def test_gcp_surfaces_no_longer_promise_dms_or_pgcopydb_defaults_generate_lacks(surface):
    text = (ROOT / "skills/gcp-to-aws/references" / surface).read_text()
    for phrase in STALE_PHRASES:
        assert phrase not in text, (surface, phrase)


def test_gcp_surfaces_state_what_generate_does_with_unknown_and_large_databases():
    refs = ROOT / "skills/gcp-to-aws/references"
    database = (refs / "design-refs/database.md").read_text()
    assert '`"unknown"` → HOLD in Generate' in database
    assert '`">500GB"` → HOLD in Generate' in database
    clarify = refs / "phases/clarify"
    glob = (clarify / "clarify-global.md").read_text()
    assert "online migration remains HOLD" in glob
    assert "zero-downtime-requested" in glob
    assert "the zero-downtime HOLD and the copy-tool choice" in glob
    assert (clarify / "clarify-database.md").read_text().count("DMS is not generated today") >= 2
    prefs = (refs / "shared/schema-preferences.md").read_text()
    assert "zero-downtime-requested" in prefs and "ACCEPT_OFFLINE_DOWNTIME" in prefs
    assert "selects pg_dump vs pgcopydb and storage allocation" in prefs
    assert '`"unknown"` → **HOLD**' in SCRIPTS.read_text()


def test_documented_protocol_requires_explicit_rollback_policy_and_real_data_gate():
    docs = DOCS.read_text()
    assert "user's informed acceptance recorded in preferences" in docs
    assert "RDS address output" in SCRIPTS.read_text()
    assert "the parser rejects `--final-sync`" in docs.lower()
    assert "inventory** checks" in docs
    assert "psql -X --no-password -v ON_ERROR_STOP=1" in docs
    assert "do not relabel a CLI failure as a registry failure" in docs
