"""Exercise the azure-to-aws generated scripts with stub tools, without cloud access.

The scripts exist only as ```bash blocks in the Generate scripts fragment. These tests
extract the blocks, assemble them the way Generate does, and run them under bash with stub
`az`, `aws`, `docker`, `psql`, `pg_dump` and friends on PATH. No replication workflow is
tested because none exists: the `dms` and unsupported-engine cases assert a named HOLD.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "skills/azure-to-aws/references/phases/generate/generate-artifacts-scripts.md"
)
BLOCKS = re.findall(r"```bash\n(.*?)```", SOURCE.read_text(encoding="utf-8"), re.DOTALL)

POSTGRES_ENV = {
    "SOURCE_HOST": "source.postgres.database.azure.com",
    "TARGET_HOST": "target.example.rds.amazonaws.com",
    "SOURCE_DB_USER": "src_user",
    "TARGET_DB_USER": "tgt_user",
    "DATABASE_NAME": "orders",
    "SOURCE_DB_PASSWORD": "source-test-password",
    "TARGET_DB_PASSWORD": "target-test-password",
    "SOURCE_WRITES_FROZEN": "yes",
    "TARGET_WRITES_FROZEN": "yes",
}


def block(marker: str) -> str:
    matches = [value for value in BLOCKS if marker in value]
    assert len(matches) == 1, (marker, len(matches))
    return textwrap.dedent(matches[0])


def preamble(name: str) -> str:
    text = block("# Script preamble (shared rules)")
    return text.replace("NN-name", name)


def data_script(engine: str) -> str:
    label = "PostgreSQL" if engine == "postgresql" else "MySQL"
    copy = "pg_dump, then pg_restore" if engine == "postgresql" else "mysqldump, then mysql"
    return "\n".join(
        (
            preamble("02-migrate-data"),
            block(f"# Data migration (Azure) — offline copy inputs ({label})"),
            block("# Offline-copy guard (shared)"),
            block(f"# Offline copy credentials ({label})"),
            block(f"# Offline copy ({label}): {copy}"),
            block("# Data-integrity gate"),
        )
    )


def hold_script(marker: str) -> str:
    return preamble("02-migrate-data") + "\n" + block(marker)


def containers_script() -> str:
    return preamble("03-migrate-containers") + "\n" + block("# App migration: container images")


def secrets_script() -> str:
    return preamble("04-migrate-secrets") + "\n" + block("# Secrets migration: Azure Key Vault")


@pytest.fixture
def runner(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "calls.jsonl"
    stub = f"""#!{sys.executable}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["CALLS"], "a") as output:
    entry = [name, *sys.argv[1:]]
    for key in ("PGPASSFILE", "MYSQL_SOURCE_DEFAULTS_FILE", "PGSSLMODE", "PGPASSWORD"):
        if os.environ.get(key):
            entry.append(key + "=" + os.environ[key])
    output.write(json.dumps(entry) + "\\n")
if name == "docker" and "--password-stdin" in sys.argv:
    sys.stdin.read()
if os.environ.get("STUB_FAIL") == name:
    sys.exit(7)
if os.environ.get("STUB_FAIL_ON") and os.environ["STUB_FAIL_ON"] in " ".join(sys.argv[1:]):
    sys.exit(9)
if name == "az" and "download" in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index("--file") + 1]).write_text("TOPSECRETVALUE")
if name == "aws" and "--secret-string" in sys.argv:
    source = sys.argv[sys.argv.index("--secret-string") + 1]
    if source.startswith("file://"):
        mode = os.stat(source[len("file://"):]).st_mode & 0o777
        pathlib.Path(os.environ["CALLS"] + ".mode").write_text(format(mode, "o"))
def marker(secret):
    return pathlib.Path(os.environ["CALLS"] + ".created." + secret)
if name == "aws" and "create-secret" in sys.argv:
    marker(sys.argv[sys.argv.index("--name") + 1]).write_text("1")
if name == "aws" and "describe-secret" in sys.argv and os.environ.get("STUB_SECRET_EXISTS") != "yes" \\
        and not marker(sys.argv[sys.argv.index("--secret-id") + 1]).exists():
    sys.exit(254)
print("stub-result")
"""
    for name in (
        "aws", "az", "docker", "skopeo", "psql", "pg_dump", "pg_restore",
        "mysql", "mysqldump", "terraform", "jq", "verifier",
    ):
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
        for old in log.parent.glob("calls.jsonl.created.*"):
            old.unlink()
        (log.parent / "calls.jsonl.mode").unlink(missing_ok=True)
        env = {
            "PATH": f"{tools}:/usr/bin:/bin",
            "CALLS": str(log),
            "TMPDIR": str(tmp_path),
            "DATA_VERIFIER": str(tools / "verifier"),
            **extra,
        }
        result = subprocess.run(
            ["bash", str(script), *args],
            cwd=unrelated,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls, script

    return run


def leftovers(tmp_path: Path) -> list[Path]:
    return [p for p in tmp_path.glob("azure-migration-*")]


# --- dry-run and argument contract (every script) -------------------------------------


@pytest.mark.parametrize(
    "name,text",
    [
        ("01", lambda: block("# Prerequisite checks: no cloud calls")),
        ("02-pg", lambda: data_script("postgresql")),
        ("02-mysql", lambda: data_script("mysql")),
        ("03", containers_script),
        ("04", secrets_script),
    ],
)
def test_default_dry_run_exits_zero_and_changes_nothing(runner, tmp_path, name, text):
    result, calls, script = runner(text())
    assert result.returncode == 0, result.stderr
    assert ("DRY RUN" if name == "01" else "Mode: DRY RUN") in result.stdout
    # 01 checks local tool availability only; every other script makes no tool call at all.
    assert [c for c in calls if c[0] in {"aws", "az", "docker", "psql", "pg_dump", "mysqldump"}] == []
    assert not (script.parent.parent / "logs").exists()
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize(
    "name,text",
    [
        ("01", lambda: block("# Prerequisite checks: no cloud calls")),
        ("02-pg", lambda: data_script("postgresql")),
        ("02-dms", lambda: hold_script("# Data migration (Azure) — HOLD: dms")),
        ("03", containers_script),
        ("04", secrets_script),
        ("05", lambda: block("# Post-migration validation")),
    ],
)
def test_unknown_arguments_exit_two_without_running_tools(runner, name, text):
    for args in (("--dry-run",), ("--execute", "--dry-run"), ("--final-sync",)):
        result, calls, _ = runner(text(), *args)
        assert result.returncode == 2, (args, result.stderr)
        assert calls == []


def test_inventory_script_takes_no_argument_at_all(runner):
    for args in (("--execute",), ("--dry-run",), ("",), ("a", "b")):
        result, calls, _ = runner(block("# Post-migration validation"), *args)
        assert result.returncode == 2, (args, result.stderr)
        assert "Usage:" in result.stderr
        assert calls == []


@pytest.mark.parametrize(
    "name,text",
    [
        ("02", lambda: data_script("postgresql")),
        ("03", containers_script),
        ("04", secrets_script),
        ("05", lambda: block("# Post-migration validation")),
    ],
)
def test_an_empty_string_argument_exits_two_on_every_script(runner, name, text):
    result, calls, _ = runner(text(), "")
    assert result.returncode == 2, result.stderr
    assert "Usage:" in result.stderr
    assert calls == []


def test_every_emitted_script_uses_strict_bash_mode():
    for marker in ("# Prerequisite checks: no cloud calls", "# Post-migration validation", "# Script preamble"):
        assert "set -euo pipefail" in block(marker)


# --- 01 prerequisites -----------------------------------------------------------------


def test_prerequisites_execute_makes_only_read_only_identity_checks(runner):
    result, calls, _ = runner(block("# Prerequisite checks: no cloud calls"), "--execute")
    assert result.returncode == 0, result.stderr
    assert ["aws", "sts", "get-caller-identity"] in calls
    assert all(c[0] == "aws" for c in calls)


def test_prerequisites_failure_returns_nonzero(runner):
    result, _, _ = runner(block("# Prerequisite checks: no cloud calls"), "--execute", STUB_FAIL="aws")
    assert result.returncode == 1
    assert "FAILED prerequisite" in result.stderr


# --- 02 data: offline copy ------------------------------------------------------------


@pytest.mark.parametrize("engine", ["postgresql", "mysql"])
def test_execute_lists_all_missing_inputs_before_running_tools(runner, engine):
    result, calls, _ = runner(data_script(engine), "--execute", DATA_VERIFIER="")
    assert result.returncode == 1
    for name in (
        "SOURCE_HOST", "TARGET_HOST", "SOURCE_DB_USER", "TARGET_DB_USER", "DATABASE_NAME",
        "SOURCE_DB_PASSWORD", "TARGET_DB_PASSWORD", "DATA_VERIFIER",
    ):
        assert name in result.stderr
    assert calls == []


def test_execute_without_write_freeze_acknowledgement_holds(runner):
    env = {**POSTGRES_ENV, "SOURCE_WRITES_FROZEN": "no"}
    result, calls, _ = runner(data_script("postgresql"), "--execute", **env)
    assert result.returncode == 1
    assert "HOLD[WRITES_NOT_FROZEN]" in result.stderr
    assert calls == []


def test_execute_with_non_executable_verifier_holds(runner, tmp_path):
    result, calls, _ = runner(
        data_script("postgresql"), "--execute", **{**POSTGRES_ENV, "DATA_VERIFIER": str(tmp_path / "missing")}
    )
    assert result.returncode == 1
    assert "HOLD[VERIFIER_MISSING]" in result.stderr
    assert calls == []


@pytest.mark.parametrize(
    "override",
    [
        {"SOURCE_HOST": "host.example:5432"},
        {"SOURCE_HOST": "postgresql://user@host/db"},
        {"SOURCE_PORT": "99999"},
        {"DATABASE_NAME": "dbname=other host=evil"},
        {"DATABASE_NAME": "-oops"},
        {"SOURCE_DB_PASSWORD": "line1\nline2"},
        {"TARGET_HOST": "source.postgres.database.azure.com"},
        {"DUMP_DIR_BASE": "/nonexistent/azure-migration-test"},
    ],
)
def test_execute_rejects_unsafe_connection_inputs(runner, override):
    result, calls, _ = runner(data_script("postgresql"), "--execute", **{**POSTGRES_ENV, **override})
    assert result.returncode == 1
    assert "HOLD[BAD_INPUT]" in result.stderr
    assert calls == []


def test_postgres_offline_copy_runs_dump_restore_then_verifier_without_leaking_passwords(runner, tmp_path):
    result, calls, script = runner(data_script("postgresql"), "--execute", **POSTGRES_ENV)
    assert result.returncode == 0, result.stderr
    assert [c[0] for c in calls] == ["pg_dump", "pg_restore", "verifier"]
    dump, restore, verifier = calls
    assert dump[dump.index("-h") + 1] == "source.postgres.database.azure.com" and "--no-password" in dump
    assert restore[restore.index("-h") + 1] == "target.example.rds.amazonaws.com" and "--exit-on-error" in restore
    for command in (dump, restore):
        assert "--no-owner" in command and "--no-acl" in command
    assert verifier[verifier.index("--engine") + 1] == "postgresql"
    combined = result.stdout + result.stderr + json.dumps(calls)
    assert "source-test-password" not in combined
    assert "target-test-password" not in combined
    assert (script.parent.parent / "logs").is_dir()
    log_text = (script.parent.parent / "logs/02-migrate-data.log").read_text()
    assert "source-test-password" not in log_text
    # Dump directory and credentials directory are removed on exit.
    assert leftovers(tmp_path) == []


def test_postgres_password_file_is_restricted_and_cleaned_up(runner, tmp_path):
    script_text = data_script("postgresql").replace(
        "# Data-integrity gate",
        'stat -f %Lp "$PGPASSFILE" > "$MIGRATION_DIR/mode.txt" 2>/dev/null '
        '|| stat -c %a "$PGPASSFILE" > "$MIGRATION_DIR/mode.txt"\n'
        'grep -c "" "$PGPASSFILE" > "$MIGRATION_DIR/lines.txt"\n# Data-integrity gate',
    )
    result, _, script = runner(script_text, "--execute", **POSTGRES_ENV)
    assert result.returncode == 0, result.stderr
    assert (script.parent.parent / "mode.txt").read_text().strip() == "600"
    assert (script.parent.parent / "lines.txt").read_text().strip() == "2"
    assert leftovers(tmp_path) == []


def test_postgres_requires_tls_and_ignores_a_callers_password_variable(runner):
    result, calls, _ = runner(data_script("postgresql"), "--execute", PGPASSWORD="leaky-global", **POSTGRES_ENV)
    assert result.returncode == 0, result.stderr
    for command in calls[:2]:
        assert "PGSSLMODE=require" in command
        assert not any(arg.startswith("PGPASSWORD=") for arg in command)
    assert "leaky-global" not in json.dumps(calls)
    result, calls, _ = runner(data_script("postgresql"), "--execute", PGSSLMODE="verify-full", **POSTGRES_ENV)
    assert "PGSSLMODE=verify-full" in calls[0]


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_postgres_rejects_a_mode_that_does_not_require_tls(runner, mode):
    result, calls, _ = runner(data_script("postgresql"), "--execute", PGSSLMODE=mode, **POSTGRES_ENV)
    assert result.returncode == 1
    assert "HOLD[BAD_INPUT]" in result.stderr and "TLS" in result.stderr
    assert calls == []


def test_postgres_password_file_escapes_colon_and_backslash(runner):
    script_text = data_script("postgresql").replace(
        "# Data-integrity gate", 'cp "$PGPASSFILE" "$MIGRATION_DIR/pgpass.copy"\n# Data-integrity gate'
    )
    env = {**POSTGRES_ENV, "SOURCE_DB_PASSWORD": "pa:ss\\word"}
    result, _, script = runner(script_text, "--execute", **env)
    assert result.returncode == 0, result.stderr
    first = (script.parent.parent / "pgpass.copy").read_text().splitlines()[0]
    assert first == "source.postgres.database.azure.com:5432:orders:src_user:pa\\:ss\\\\word"


def test_dump_goes_to_dump_dir_base_when_set(runner, tmp_path):
    base = tmp_path / "bigdisk"
    base.mkdir()
    result, calls, _ = runner(data_script("postgresql"), "--execute", DUMP_DIR_BASE=str(base), **POSTGRES_ENV)
    assert result.returncode == 0, result.stderr
    dump = calls[0]
    assert dump[dump.index("-f") + 1].startswith(f"{base}/azure-migration-dump.")
    assert list(base.iterdir()) == []


@pytest.mark.parametrize("engine,tool", [("postgresql", "pg_dump"), ("mysql", "mysqldump")])
def test_passwords_do_not_appear_under_xtrace(runner, engine, tool):
    result, calls, _ = runner(data_script(engine), "--execute", SHELLOPTS="xtrace", **POSTGRES_ENV)
    assert result.returncode == 0, result.stderr
    assert calls[0][0] == tool
    for secret in ("source-test-password", "target-test-password"):
        assert secret not in result.stdout + result.stderr


def test_failed_dump_stops_before_restore_and_cleans_up(runner, tmp_path):
    result, calls, _ = runner(data_script("postgresql"), "--execute", STUB_FAIL="pg_dump", **POSTGRES_ENV)
    assert result.returncode == 7
    assert [c[0] for c in calls] == ["pg_dump"]
    assert leftovers(tmp_path) == []


def test_failed_verifier_holds_cutover(runner):
    result, calls, _ = runner(data_script("postgresql"), "--execute", STUB_FAIL="verifier", **POSTGRES_ENV)
    assert result.returncode == 1
    assert "HOLD[VERIFICATION_FAILED]" in result.stderr
    assert [c[0] for c in calls] == ["pg_dump", "pg_restore", "verifier"]


def test_mysql_offline_copy_uses_option_files_not_password_arguments(runner, tmp_path):
    env = {
        **POSTGRES_ENV,
        "SOURCE_HOST": "source.mysql.database.azure.com",
        "SOURCE_DB_PASSWORD": 'pa"ss\\word#1',
    }
    result, calls, script = runner(data_script("mysql"), "--execute", **env)
    assert result.returncode == 0, result.stderr
    assert [c[0] for c in calls] == ["mysqldump", "mysql", "verifier"]
    dump, load, verifier = calls
    assert any(arg.startswith("--defaults-extra-file=") for arg in dump)
    assert any(arg.startswith("--defaults-extra-file=") for arg in load)
    assert dump[1].startswith("--defaults-extra-file=") and load[1].startswith("--defaults-extra-file=")
    assert "--single-transaction" in dump
    assert verifier[verifier.index("--engine") + 1] == "mysql"
    combined = result.stdout + result.stderr + json.dumps(calls)
    assert 'pa"ss' not in combined and "target-test-password" not in combined
    assert leftovers(tmp_path) == []


def test_mysql_option_file_escapes_quotes_and_is_restricted(runner):
    script_text = data_script("mysql").replace(
        "# Data-integrity gate",
        'cp "$SOURCE_CNF" "$MIGRATION_DIR/source.cnf.copy"\n'
        'stat -f %Lp "$SOURCE_CNF" > "$MIGRATION_DIR/mode.txt" 2>/dev/null '
        '|| stat -c %a "$SOURCE_CNF" > "$MIGRATION_DIR/mode.txt"\n# Data-integrity gate',
    )
    env = {**POSTGRES_ENV, "SOURCE_DB_PASSWORD": 'pa"ss\\word#1'}
    result, _, script = runner(script_text, "--execute", **env)
    assert result.returncode == 0, result.stderr
    assert (script.parent.parent / "mode.txt").read_text().strip() == "600"
    option_file = (script.parent.parent / "source.cnf.copy").read_text()
    assert 'password="pa\\"ss\\\\word#1"' in option_file
    assert "ssl-mode=REQUIRED" in option_file


# --- 02 data: HOLD branches (no replication workflow exists) --------------------------


@pytest.mark.parametrize(
    "marker,code",
    [
        ("# Data migration (Azure) — HOLD: dms", "DMS_NOT_IMPLEMENTED"),
        ("# Data migration (Azure) — HOLD: unsupported engine", "ENGINE_NOT_SUPPORTED"),
        ("# Data migration (Azure) — HOLD: cutover unconfirmed", "CUTOVER_UNCONFIRMED"),
    ],
)
def test_hold_branches_are_named_and_fail_closed_at_execute(runner, marker, code):
    result, calls, _ = runner(hold_script(marker))
    assert result.returncode == 0, result.stderr
    assert f"HOLD[{code}]" in result.stderr
    result, calls, _ = runner(hold_script(marker), "--execute")
    assert result.returncode == 1
    assert f"HOLD[{code}]" in result.stderr
    assert calls == []


def test_dms_hold_says_the_operator_runs_replication_and_never_connects(runner):
    result, calls, _ = runner(hold_script("# Data migration (Azure) — HOLD: dms"), "--execute", **POSTGRES_ENV)
    assert "replication is run by the operator in AWS DMS following MIGRATION_GUIDE.md" in result.stderr
    assert calls == []


@pytest.mark.parametrize(
    "marker",
    [
        "# Data migration (Azure) — HOLD: dms",
        "# Data migration (Azure) — HOLD: unsupported engine",
        "# Data migration (Azure) — HOLD: cutover unconfirmed",
    ],
)
def test_generated_hold_text_has_no_angle_bracket_placeholder(runner, marker):
    result, _, _ = runner(hold_script(marker))
    hold_lines = [line for line in result.stderr.splitlines() if line.startswith("HOLD[")]
    assert len(hold_lines) == 1
    assert not re.search(r"<[A-Za-z_ ]+>", hold_lines[0]), hold_lines[0]


def test_unsupported_engine_hold_names_the_resource_type(runner):
    result, _, _ = runner(hold_script("# Data migration (Azure) — HOLD: unsupported engine"))
    assert "Microsoft.Sql/servers has no tested migration path" in result.stderr


def test_fragment_never_emits_replication_flags_or_commands():
    text = SOURCE.read_text(encoding="utf-8")
    code = "\n".join(BLOCKS)
    assert "--final-sync" not in code
    assert "start-replication-task" not in code and "create-replication-task" not in code
    assert "pgcopydb" not in code
    assert "No tested replication workflow" in text or "no tested replication workflow" in text


# --- 03 containers ---------------------------------------------------------------------


def test_containers_execute_lists_all_missing_inputs(runner):
    result, calls, _ = runner(containers_script(), "--execute")
    assert result.returncode == 1
    assert "ACR_NAME" in result.stderr and "IMAGE_LIST" in result.stderr
    assert calls == []


def test_containers_execute_copies_each_image_acr_to_ecr(runner):
    result, calls, _ = runner(
        containers_script(),
        "--execute",
        ACR_NAME="contosoreg",
        IMAGE_LIST="web/app:1.2 worker:latest",
        AWS_ACCOUNT_ID="123456789012",
        AWS_REGION="us-west-2",
    )
    assert result.returncode == 0, result.stderr
    assert ["az", "acr", "login", "--name", "contosoreg"] in calls
    pushed = [c[1:] for c in calls if c[0] == "docker" and c[1] == "push"]
    assert ["push", "123456789012.dkr.ecr.us-west-2.amazonaws.com/web/app:1.2"] in pushed
    assert ["push", "123456789012.dkr.ecr.us-west-2.amazonaws.com/worker:latest"] in pushed
    pulls = [c for c in calls if c[0] == "docker" and c[1] == "pull"]
    assert [c[4] for c in pulls] == ["contosoreg.azurecr.io/web/app:1.2", "contosoreg.azurecr.io/worker:latest"]
    assert all(c[2:4] == ["--platform", "linux/amd64"] for c in pulls)
    assert all(
        c[c.index("--region") + 1] == "us-west-2" for c in calls if c[0] == "aws" and "--region" in c
    )


CONTAINER_ENV = {"ACR_NAME": "contosoreg", "IMAGE_LIST": "web/app:1.2", "AWS_ACCOUNT_ID": "123456789012"}


def test_containers_platform_is_overridable(runner):
    result, calls, _ = runner(containers_script(), "--execute", **{**CONTAINER_ENV, "IMAGE_PLATFORM": "linux/arm64"})
    assert result.returncode == 0, result.stderr
    pull = next(c for c in calls if c[:2] == ["docker", "pull"])
    assert pull[2:4] == ["--platform", "linux/arm64"]


def test_containers_ecr_token_goes_through_stdin_and_sessions_are_logged_out(runner):
    result, calls, _ = runner(containers_script(), "--execute", **CONTAINER_ENV)
    assert result.returncode == 0, result.stderr
    login = next(c for c in calls if c[:2] == ["docker", "login"])
    assert "--password-stdin" in login and "--password" not in login
    assert "stub-result" not in login
    logouts = [c[2] for c in calls if c[:2] == ["docker", "logout"]]
    assert logouts == ["contosoreg.azurecr.io", "123456789012.dkr.ecr.us-east-1.amazonaws.com"]


def test_containers_dry_run_never_logs_in_or_out(runner):
    result, calls, _ = runner(containers_script(), IMAGE_LIST="web/app:1.2")
    assert result.returncode == 0, result.stderr
    assert calls == []


def test_containers_create_a_missing_repository_with_scan_on_push(runner):
    result, calls, _ = runner(containers_script(), "--execute", STUB_FAIL_ON="describe-repositories", **CONTAINER_ENV)
    assert result.returncode == 0, result.stderr
    create = next(c for c in calls if "create-repository" in c)
    assert "scanOnPush=true" in create


def test_containers_do_not_create_a_repository_terraform_already_made(runner):
    result, calls, _ = runner(containers_script(), "--execute", **CONTAINER_ENV)
    assert not any("create-repository" in c for c in calls)


@pytest.mark.parametrize(
    "override",
    [
        {"ACR_NAME": "bad;name"},
        {"ACR_NAME": "bad-name"},
        {"ACR_LOGIN_SERVER": "--config=/tmp/x"},
        {"ACR_LOGIN_SERVER": "contosoreg.azurecr.io/evil"},
        {"ACR_LOGIN_SERVER": "contosoreg.x;y"},
        {"ACR_LOGIN_SERVER": "-evil.io"},
        {"ACR_LOGIN_SERVER": "other.azurecr.io"},
        {"AWS_ACCOUNT_ID": "1;x"},
        {"AWS_ACCOUNT_ID": "12345"},
        {"AWS_ACCOUNT_ID": "12345678901x"},
        {"AWS_REGION": "e/../x"},
        {"AWS_REGION": "US_EAST"},
        {"IMAGE_PLATFORM": "--evil"},
    ],
)
def test_containers_reject_unsafe_registry_and_platform_inputs(runner, override):
    result, calls, _ = runner(containers_script(), "--execute", **{**CONTAINER_ENV, **override})
    assert result.returncode == 1
    assert not [c for c in calls if c[0] == "docker"]


def test_containers_accept_a_login_server_that_starts_with_the_registry_name(runner):
    result, calls, _ = runner(
        containers_script(), "--execute", **{**CONTAINER_ENV, "ACR_LOGIN_SERVER": "contosoreg.azurecr.us"}
    )
    assert result.returncode == 0, result.stderr
    assert next(c for c in calls if c[:2] == ["docker", "pull"])[4].startswith("contosoreg.azurecr.us/")


def test_containers_validate_the_whole_list_before_any_login_or_copy(runner):
    result, calls, _ = runner(containers_script(), "--execute", **{**CONTAINER_ENV, "IMAGE_LIST": "good:1 bad"})
    assert result.returncode == 1
    assert "bad needs an explicit repository:tag" in result.stderr
    assert not [c for c in calls if c[0] in {"docker", "aws", "az"}]


def test_containers_reject_digest_references(runner):
    result, calls, _ = runner(containers_script(), "--execute", **{**CONTAINER_ENV, "IMAGE_LIST": "app@sha256:abc"})
    assert result.returncode == 1
    assert "use repository:tag" in result.stderr
    assert not any("create-repository" in c for c in calls)
    assert not [c for c in calls if c[0] == "docker" and c[1] in {"pull", "push"}]


def test_containers_verification_failure_fails_the_script(runner):
    result, calls, _ = runner(containers_script(), "--execute", STUB_FAIL_ON="describe-images", **CONTAINER_ENV)
    assert result.returncode != 0
    assert any(c[0] == "docker" and c[1] == "push" for c in calls)


def test_containers_verification_says_presence_only(runner, tmp_path):
    result, _, script = runner(containers_script(), "--execute", **CONTAINER_ENV)
    assert "presence only; digests were not compared" in (script.parent.parent / "logs/03-migrate-containers.log").read_text()


def test_containers_never_expand_a_glob_in_the_image_list(runner, tmp_path):
    cwd = tmp_path / "unrelated"
    (cwd / "evil:tag").write_text("x")
    (cwd / "localfile.txt").write_text("x")
    for args in ((), ("--execute",)):
        result, calls, _ = runner(containers_script(), *args, **{**CONTAINER_ENV, "IMAGE_LIST": "*"})
        assert "evil:tag" not in result.stdout + result.stderr + json.dumps(calls)
        assert "localfile.txt" not in result.stdout + result.stderr + json.dumps(calls)
        assert not [c for c in calls if c[0] == "docker" and c[1] in {"pull", "push"}]


def test_containers_reject_an_image_without_a_tag(runner):
    result, calls, _ = runner(
        containers_script(), "--execute", ACR_NAME="contosoreg", IMAGE_LIST="notag", AWS_ACCOUNT_ID="123456789012"
    )
    assert result.returncode == 1
    assert not [c for c in calls if c[0] == "docker" and c[1] in {"pull", "push"}]


# --- 04 secrets ------------------------------------------------------------------------


def test_secrets_dry_run_does_not_read_secret_values_or_call_az(runner):
    result, calls, _ = runner(secrets_script(), SECRET_NAMES="db-password api-key", KEY_VAULT_NAME="kv")
    assert result.returncode == 0, result.stderr
    assert "value not read" in result.stdout
    assert calls == []


def test_secrets_execute_lists_all_missing_inputs(runner):
    result, calls, _ = runner(secrets_script(), "--execute")
    assert result.returncode == 1
    assert "KEY_VAULT_NAME" in result.stderr and "SECRET_NAMES" in result.stderr
    assert calls == []


def test_secrets_execute_copies_through_a_restricted_file_and_never_prints_values(runner, tmp_path):
    result, calls, script = runner(
        secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-password api-key"
    )
    assert result.returncode == 0, result.stderr
    downloads = [c for c in calls if c[0] == "az" and "download" in c]
    assert len(downloads) == 2
    creates = [c for c in calls if c[0] == "aws" and "create-secret" in c]
    assert len(creates) == 2
    for create in creates:
        assert create[create.index("--secret-string") + 1].startswith("file://")
        assert create[create.index("--tags") + 1] == "Key=MigrationSource,Value=azure-key-vault"
    combined = result.stdout + result.stderr + json.dumps(calls)
    assert "TOPSECRETVALUE" not in combined
    assert "TOPSECRETVALUE" not in (script.parent.parent / "logs/04-migrate-secrets.log").read_text()
    assert leftovers(tmp_path) == []


def test_secrets_execute_updates_an_existing_secret(runner):
    result, calls, script = runner(
        secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-password", STUB_SECRET_EXISTS="yes"
    )
    assert result.returncode == 0, result.stderr
    puts = [c for c in calls if c[0] == "aws" and "put-secret-value" in c]
    assert len(puts) == 1
    assert puts[0][puts[0].index("--secret-string") + 1].startswith("file://")
    assert not any(c[0] == "aws" and "create-secret" in c for c in calls)
    assert "TOPSECRETVALUE" not in json.dumps(calls)
    assert (script.parent.parent.parent / "calls.jsonl.mode").read_text() == "600"


def test_secret_file_mode_is_600_when_the_secret_is_created(runner):
    result, _, script = runner(secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-password")
    assert result.returncode == 0, result.stderr
    assert (script.parent.parent.parent / "calls.jsonl.mode").read_text() == "600"


def test_secrets_reject_a_name_that_starts_with_a_hyphen(runner):
    result, calls, _ = runner(secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="ok -x")
    assert result.returncode == 1
    assert "Unsupported secret name: -x" in result.stderr
    assert calls == []


def test_secrets_warn_about_a_name_ending_in_a_hyphen_and_six_characters(runner):
    result, calls, _ = runner(secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-secret db-password")
    assert result.returncode == 0, result.stderr
    assert "WARNING: db-secret ends with a hyphen and six characters" in result.stderr
    assert "WARNING: db-password" not in result.stderr
    assert len([c for c in calls if "create-secret" in c]) == 2


@pytest.mark.parametrize("override", [{"AWS_REGION": "e/../x"}, {"AWS_REGION": "US_EAST"}])
def test_secrets_reject_a_bad_region_before_any_call(runner, override):
    result, calls, _ = runner(secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="a", **override)
    assert result.returncode == 1
    assert calls == []


def test_secrets_reject_unsafe_names_before_any_call(runner):
    result, calls, _ = runner(secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="ok bad;rm")
    assert result.returncode == 1
    assert calls == []


def test_secrets_verification_failure_fails_the_script(runner):
    result, calls, _ = runner(
        secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-password", STUB_FAIL_ON="describe-secret"
    )
    assert result.returncode != 0
    assert any("create-secret" in c for c in calls)


@pytest.mark.parametrize("mode", [(), ("--execute",)])
def test_secrets_never_expand_a_glob_in_the_secret_list(runner, tmp_path, mode):
    cwd = tmp_path / "unrelated"
    (cwd / "id_rsa").write_text("x")
    (cwd / "localfile.txt").write_text("x")
    result, calls, _ = runner(secrets_script(), *mode, KEY_VAULT_NAME="kv", SECRET_NAMES="*")
    seen = result.stdout + result.stderr + json.dumps(calls)
    assert "id_rsa" not in seen and "localfile.txt" not in seen
    assert not [c for c in calls if c[0] == "az"]


def test_secrets_failed_download_leaves_no_temp_files(runner, tmp_path):
    result, _, _ = runner(
        secrets_script(), "--execute", KEY_VAULT_NAME="kv", SECRET_NAMES="db-password", STUB_FAIL="az"
    )
    assert result.returncode == 7
    assert leftovers(tmp_path) == []


# --- 05 validation ---------------------------------------------------------------------


def test_inventory_checks_pass_and_do_not_claim_data_integrity(runner):
    result, calls, script = runner(
        block("# Post-migration validation"),
        AWS_REGION="us-west-2",
        ECS_CLUSTER_NAME="generated-ecs",
        EKS_CLUSTER_NAME="generated-eks",
        S3_BUCKET="example-assets",
    )
    assert result.returncode == 0, result.stderr
    assert calls[0] == ["terraform", f"-chdir={script.parent.parent}/terraform", "state", "list"]
    aws_calls = [c for c in calls if c[0] == "aws"]
    assert {c[1] for c in aws_calls} == {"ecs", "eks", "elasticbeanstalk", "lambda", "rds", "ecr", "s3api", "secretsmanager"}
    assert all(c[c.index("--region") + 1] == "us-west-2" for c in aws_calls)
    assert "does not establish application health or data integrity" in result.stdout


@pytest.mark.parametrize("failing_tool", ["aws", "terraform"])
def test_inventory_failures_block_cutover(runner, failing_tool):
    result, _, _ = runner(block("# Post-migration validation"), STUB_FAIL=failing_tool)
    assert result.returncode == 1
    assert "Do not proceed to cutover" in result.stderr


def test_inventory_requires_generated_names_instead_of_guessing(runner):
    result, calls, _ = runner(block("# Post-migration validation"))
    assert result.returncode == 1
    for name in ("ECS_CLUSTER_NAME", "EKS_CLUSTER_NAME", "S3_BUCKET"):
        assert f"set {name}" in result.stderr


# --- fragment text contracts ------------------------------------------------------------
def fragment_text() -> str:
    return " ".join(SOURCE.read_text(encoding="utf-8").split())


def test_01_checks_only_tools_the_scripts_call_and_lists_engine_tools_per_line():
    prerequisites = block("# Prerequisite checks: no cloud calls")
    assert "for tool in aws terraform; do" in prerequisites
    assert "jq" not in prerequisites
    for tool in ("pg_dump", "pg_restore", "mysqldump", "mysql", "docker", "az"):
        assert f"check command -v {tool}" in prerequisites
    # az is required only when 03 or 04 is generated, so its checks are commented lines.
    assert "# 03 or 04:       check command -v az" in prerequisites
    assert "# 03 or 04:     check az account show" in prerequisites
    assert "\n  check az account show" not in prerequisites


def test_cutover_and_region_are_read_from_value_never_default():
    text = fragment_text()
    assert "`data.db_cutover.value` (never `.default`)" in text
    assert (
        "Read the confirmed cutover choice from `data.db_cutover.value` and the target region from "
        "`design_constraints.target_region.value`. Never read `data.db_cutover.default`: that field "
        "holds `dump_restore` even when the user chose `dms`."
    ) in text
    assert "| `data.db_cutover.value` | Engine | Emit |" in text
    assert "`design_constraints.target_region.value`" in text
    assert "A `null` or absent `value` means the choice is unconfirmed (`CUTOVER_UNCONFIRMED`)" in text
    assert "| `null`, absent, or any other value | PostgreSQL or MySQL Flexible Server | HOLD `CUTOVER_UNCONFIRMED` |" in text
    assert "azure-resource-inventory.json" not in text


def test_unsupported_engine_reaches_the_assembler_as_a_warning_not_a_file():
    text = fragment_text()
    assert '`warnings[]` entry `{ "code": "ENGINE_NOT_SUPPORTED", "subject": "<azure_id>"' in text
    assert "Do not write `generation-warnings.json`: only the assembler creates it." in text
    assert "NOTE[ENGINE_NOT_SUPPORTED]" not in text
    assemble = " ".join((SOURCE.parent / "generate-assemble.md").read_text(encoding="utf-8").split())
    assert "The scripts fragment reports each database that `scripts/02-migrate-data.sh` does not handle" in assemble
    assert 'as a `warnings[]` entry `{ code: "ENGINE_NOT_SUPPORTED", subject, detail }`' in assemble
    assert "no password value or literal credential" in assemble


def test_a_database_only_of_an_unsupported_engine_gets_engine_not_supported_whatever_the_value():
    """A Cosmos DB-only or Redis-only design has data.db_cutover N/A (null): no Decision gate row can
    clear CUTOVER_UNCONFIRMED, so the engine rule must win, warn the assembler and have a guide note."""
    text = fragment_text()
    unsupported = "| any value, `null` and absent included | any other engine (Azure SQL, Cosmos DB, Redis, ...) | HOLD `ENGINE_NOT_SUPPORTED` |"
    assert unsupported in text
    # The engine rule comes before every cutover-value row, so it cannot be shadowed by CUTOVER_UNCONFIRMED.
    assert text.index(unsupported) < text.index("| `dump_restore` | PostgreSQL Flexible Server |")
    assert text.index(unsupported) < text.index("| `null`, absent, or any other value | PostgreSQL or MySQL Flexible Server | HOLD `CUTOVER_UNCONFIRMED` |")
    assert "| `dms` | any |" not in text
    assert "`null` included" in text and "never `CUTOVER_UNCONFIRMED`" in text
    assert "including the database a HOLD names and including an estate whose only databases are unsupported" in text
    docs = " ".join((SOURCE.parent / "generate-artifacts-docs.md").read_text(encoding="utf-8").split())
    assert "write just the **Not covered by this runbook** note below" in docs
    assert "`scripts/02-migrate-data.sh` prints `ENGINE_NOT_SUPPORTED` for them and cites that note" in docs


def test_postgres_copy_guidance_says_the_dump_includes_extensions_and_the_restore_stops_on_one_it_cannot_create():
    text = fragment_text()
    assert "pg_restore --no-password --exit-on-error" in text
    assert "does include `CREATE EXTENSION` for each of the database's non-system" in text
    assert "`pg_restore --exit-on-error` stops at one the target engine version cannot create" in text
    assert "install the extensions" not in text and "dump roles, grants or extensions" not in text
    docs = " ".join((SOURCE.parent / "generate-artifacts-docs.md").read_text(encoding="utf-8").split())
    assert "A PostgreSQL dump does include `CREATE EXTENSION` for each non-system extension" in docs
    assert "confirm every extension in use is available there before the window" in docs
    assert "target roles and extensions must exist first" not in docs and "install the extensions in use" not in docs


def test_both_engines_in_one_estate_emit_the_first_and_report_the_second():
    text = fragment_text()
    assert "emit the data script for the engine that appears first in `services[]` order" in text
    assert '`detail` "second engine; run the data script once per database"' in text
    assemble = " ".join((SOURCE.parent / "generate-assemble.md").read_text(encoding="utf-8").split())
    assert "its warning satisfies this handoff: write one entry per `azure_id`, not two" in assemble


def test_secret_names_are_equal_on_both_sides_and_the_hyphen_six_rule_is_stated():
    text = fragment_text()
    assert "The infra fragment names each Secrets Manager secret exactly as its Key Vault secret" in text
    assert "should not end with a hyphen followed by six characters (for example `db-secret`)" in text
    infra = " ".join((SOURCE.parent / "generate-artifacts-infra.md").read_text(encoding="utf-8").split())
    assert "named exactly as its Key Vault secret, so the map sends each name to itself" in infra
    assert "secret `name` equals the Key Vault secret name" in infra
    docs = " ".join((SOURCE.parent / "generate-artifacts-docs.md").read_text(encoding="utf-8").split())
    assert "has the same name as its Key Vault secret" in docs
    assert "should not end with a hyphen followed by six characters (for example `db-secret`)" in docs


def test_rules_scope_dry_run_and_exit_two_for_script_05():
    text = fragment_text()
    assert "`05-validate-migration.sh` only reads: it takes no argument, never writes, and exits **2** on any argument" in text
    assert "Every script except 05 defaults to dry-run and exits 2 on an unknown argument" in text
    assert "set +x" in block("# Script preamble (shared rules)")


def test_terraform_ordering_is_stated_for_secrets_images_and_the_guide():
    text = fragment_text()
    assert text.count("**Ordering with Terraform.** Run `terraform apply` first") == 2
    assert "writes a new version of that existing secret" in text
    assert "lifecycle { ignore_changes = [secret_string] }" in text
    assert "creates a repository only when Terraform did not already create it" in text
    assert "It does not dump roles or grants (`--no-owner --no-acl`)" in text
    infra = " ".join((SOURCE.parent / "generate-artifacts-infra.md").read_text(encoding="utf-8").split())
    assert "lifecycle { ignore_changes = [secret_string] }" in infra
    assert "**`secret_names`** output" in infra
    docs = " ".join((SOURCE.parent / "generate-artifacts-docs.md").read_text(encoding="utf-8").split())
    step = docs.split("## Step 1b:", 1)[1].split("## Step 2:", 1)[0]
    assert "Run `terraform apply` first and set each `SECRET_NAMES` entry" in step
    assert "`IMAGE_PLATFORM`" in step and "manifest list" in step
    assert "`DUMP_DIR_BASE`" in step and "free space against the database size" in step
    assert "--no-owner --no-acl" in step and "verify-full" in step
    assert "confirm in current MySQL and Azure documentation" in step
    assert "does not dump roles or grants" in docs
    assert "Inputs: `AWS_REGION` and, for the sections the script contains, `ECS_CLUSTER_NAME`, `EKS_CLUSTER_NAME` and `S3_BUCKET`, all from `terraform output`. It takes no argument." in step


def test_fragment_is_registered_and_the_scripts_are_postconditions():
    skill = SOURCE.parents[3]
    generate = (skill / "references/phases/generate/generate.md").read_text(encoding="utf-8")
    assemble = (skill / "references/phases/generate/generate-assemble.md").read_text(encoding="utf-8")
    assert "_id: artifacts-scripts" in generate
    assert "phases/generate/generate-artifacts-scripts.md" in generate
    for name in ("01-validate-prerequisites.sh", "02-migrate-data.sh", "03-migrate-containers.sh",
                 "04-migrate-secrets.sh", "05-validate-migration.sh"):
        assert f"scripts/{name}" in generate
    assert "artifacts-scripts" in assemble
    assert "No script was executed during Generate" in generate
