"""Execute only the repository's trusted PostgreSQL template with fake clients.

No generated customer script is executed. The clients record calls and never
contact a database, so these tests exercise the actual --verify control path
without credentials or migration side effects.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest


PLUGIN = Path(__file__).resolve().parents[1]
TEMPLATE = (
    PLUGIN / "skills/heroku-to-aws/references/phases/generate/generate-docs.md"
)


@pytest.fixture
def trusted_script(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    source = TEMPLATE.read_text(encoding="utf-8")
    section = source.split("### 3A: PostgreSQL Migration Script", 1)[1]
    script = section.split("```bash\n", 1)[1].split("\n```", 1)[0] + "\n"
    values = {
        f"{side}_DB_{field}": value
        for side in ("SOURCE", "TARGET")
        for field, value in (
            ("HOST", f"{side.lower()}.test"),
            ("PORT", "5432"),
            ("USER", "test_user"),
            ("PASSWORD", "test-only"),
            ("NAME", side.lower()),
        )
    }
    for name, value in values.items():
        script = script.replace("{{" + name + "}}", value)
    assert not re.search(r"\{\{(?:SOURCE|TARGET)_DB_", script)
    path = tmp_path / "migrate-postgres.sh"
    path.write_text(script, encoding="utf-8")
    commands = tmp_path / "bin"
    commands.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake_client = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"command": command, "args": args}) + "\\n")
if command != "psql":
    sys.exit(91)
if "-X" not in args and "--no-psqlrc" not in args:
    sys.exit(92)
query = args[args.index("-c") + 1]
if query == "SELECT 1;":
    print("1")
    sys.exit(0)
database = args[args.index("-d") + 1]
if os.environ.get("QUERY_FAILURE") == database:
    sys.exit(93)
rows = "8" if os.environ.get("MISMATCH") == database else "7"
print("public.orders|" + rows)
"""
    # The shebang uses an explicit interpreter rather than relying on the fake
    # client's PATH, which is deliberately restricted.
    import sys

    fake_client = fake_client.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1)
    for name in ("psql", "pg_dump", "pg_restore"):
        client = commands / name
        client.write_text(fake_client, encoding="utf-8")
        client.chmod(0o700)
    startup = tmp_path / "psqlrc"
    startup.write_text("DROP TABLE should_never_execute;\n", encoding="utf-8")
    env = {
        "PATH": str(commands) + os.pathsep + "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LC_ALL": "C",
        "CALL_LOG": str(calls),
        "PSQLRC": str(startup),
        "BASH_ENV": "/dev/null",
        "ENV": "/dev/null",
    }
    return path, env, calls


def run_verify(
    fixture: tuple[Path, dict[str, str], Path], *args: str, **overrides: str
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    script, env, calls = fixture
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", str(script), *args],
        cwd=script.parent,
        env={**env, **overrides},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    recorded = (
        [json.loads(line) for line in calls.read_text().splitlines()]
        if calls.exists()
        else []
    )
    return result, recorded


def assert_read_only_calls(calls: list[dict]) -> None:
    assert calls
    assert {call["command"] for call in calls} == {"psql"}
    assert all("-X" in call["args"] for call in calls)
    assert all(
        call["args"][call["args"].index("-c") + 1].lstrip().startswith("SELECT")
        for call in calls
    )


def test_verify_matches_without_migration_or_startup_files(trusted_script) -> None:
    result, calls = run_verify(trusted_script, "--verify")
    assert result.returncode == 0, result.stdout + result.stderr
    assert_read_only_calls(calls)
    assert len(calls) == 4


def test_verify_mismatch_fails_without_migration(trusted_script) -> None:
    result, calls = run_verify(trusted_script, "--verify", MISMATCH="target")
    assert result.returncode == 1
    assert_read_only_calls(calls)


@pytest.mark.parametrize("side", ["source", "target"])
def test_verify_query_failure_does_not_compare_empty_success(trusted_script, side) -> None:
    result, calls = run_verify(trusted_script, "--verify", QUERY_FAILURE=side)
    assert result.returncode == 1
    assert_read_only_calls(calls)


def test_unknown_mode_never_reaches_database_clients(trusted_script) -> None:
    result, calls = run_verify(trusted_script, "--unsupported-mode")
    assert result.returncode == 2
    assert calls == []
