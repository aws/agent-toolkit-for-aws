"""Every per-skill test suite must run in `mise run ci`.

GitHub CI runs only `mise -C plugins/aws-startup-advisor run ci`, so a skill directory with
test files that no `ci` dependency task covers never runs in CI. This guard fails when a new
skill test directory appears without a task.

A command covers a test directory when one of its arguments is that directory or one of its
ancestors under `skills/` (so `pytest skills/foo/scripts` covers `skills/foo/scripts/tests`) and
none of the same command's exclusions (`--ignore`, `--ignore-glob`, `--deselect`) is that
directory or an ancestor. Exclusions apply per command, before coverage is combined across tasks,
so `pytest skills/foo --ignore skills/foo/scripts` does not cover `skills/foo/scripts` unless
another task runs it.

Requires Python 3.11+ for `tomllib`; the `test` task pins `uv run --python 3.12`.
"""
from __future__ import annotations

import fnmatch
import shlex
import tomllib
from pathlib import PurePosixPath, Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.test.ts", "*.test.js", "*.test.mjs")
EXCLUDING_FLAGS = ("--ignore", "--ignore-glob", "--deselect")
SKIP_PARTS = {".venv", "node_modules", "__pycache__"}


def _ci_commands() -> list[str]:
    tasks = tomllib.loads((PLUGIN_ROOT / "mise.toml").read_text())["tasks"]
    seen: set[str] = set()
    commands: list[str] = []

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        task = tasks.get(name, {})
        run = task.get("run", [])
        commands.extend(run if isinstance(run, list) else [run])
        for dep in task.get("depends", []):
            visit(dep if isinstance(dep, str) else dep.get("task", ""))

    visit("ci")
    return commands


def _command_scope(command: str) -> tuple[list[PurePosixPath], list[str]]:
    """Return (included paths, exclusion patterns) named by one command."""
    includes: list[PurePosixPath] = []
    excludes: list[str] = []
    tokens = shlex.split(command)
    skip_next = False
    for i, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        flag, eq, value = token.partition("=")
        if flag in EXCLUDING_FLAGS:
            if eq:
                excludes.append(value)
            elif i + 1 < len(tokens):
                excludes.append(tokens[i + 1])
                skip_next = True
            continue
        candidate = value if flag.startswith("--") and eq else token
        if candidate.startswith("skills/"):
            includes.append(PurePosixPath(candidate.rstrip("/")))
    # `--deselect path::test` deselects within a file; keep only the path part.
    return includes, [e.split("::", 1)[0].rstrip("/") for e in excludes]


def _excluded(directory: PurePosixPath, patterns: list[str]) -> bool:
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatch(str(directory), pattern) or any(
                fnmatch.fnmatch(str(parent), pattern) for parent in directory.parents
            ):
                return True
        elif directory == PurePosixPath(pattern) or directory.is_relative_to(pattern):
            return True
    return False


def _command_covers(directory: PurePosixPath, command: str) -> bool:
    includes, excludes = _command_scope(command)
    included = any(directory == inc or directory.is_relative_to(inc) for inc in includes)
    return included and not _excluded(directory, excludes)


def _uncovered(test_dirs, commands):
    return [d for d in test_dirs if not any(_command_covers(d, c) for c in commands)]


def _skill_test_dirs() -> list[PurePosixPath]:
    dirs = set()
    for pattern in TEST_FILE_PATTERNS:
        for path in (PLUGIN_ROOT / "skills").rglob(pattern):
            rel = path.relative_to(PLUGIN_ROOT)
            if SKIP_PARTS.isdisjoint(rel.parts):
                dirs.add(PurePosixPath(rel.parent.as_posix()))
    return sorted(dirs)


def test_every_skill_test_directory_runs_in_ci():
    missing = _uncovered(_skill_test_dirs(), _ci_commands())
    assert missing == [], (
        f"skill test directories not run by any `mise run ci` dependency: {[str(m) for m in missing]}; "
        "add them to a test task in plugins/aws-startup-advisor/mise.toml"
    )


def test_guard_sees_the_known_suites():
    assert {
        PurePosixPath("skills/agent-advisor/scripts"),
        PurePosixPath("skills/llm-to-bedrock/scripts"),
        PurePosixPath("skills/heroku-to-aws/scripts"),
        PurePosixPath("skills/tf-best-practices/scripts"),
    } <= set(_skill_test_dirs())


def test_ancestor_covers_nested_dir_and_exclusions_do_not_count():
    nested = [PurePosixPath("skills/foo/scripts/tests")]
    assert _uncovered(nested, ["pytest -q skills/foo/scripts"]) == []
    assert _uncovered(nested, ["uv run --directory skills/foo/scripts pytest"]) == []
    assert _uncovered(nested, ["pytest skills/bar --ignore skills/foo/scripts"]) == nested
    assert _uncovered(nested, ["pytest skills/bar --ignore=skills/foo"]) == nested
    # A sibling whose name shares a prefix is not an ancestor.
    assert _uncovered(nested, ["pytest skills/foo/scr"]) == nested


SUITE = PurePosixPath("skills/foo/scripts")


def test_exclusion_under_an_included_ancestor_is_uncovered():
    # Space and equals forms; the ancestor is included by the same command.
    assert _uncovered([SUITE], ["pytest skills/foo skills/bar --ignore skills/foo/scripts"]) == [SUITE]
    assert _uncovered([SUITE], ["pytest skills/foo skills/bar --ignore=skills/foo/scripts"]) == [SUITE]
    assert _uncovered([SUITE], ["pytest skills/foo --ignore-glob=skills/foo/scr*"]) == [SUITE]
    assert _uncovered([SUITE], ["pytest skills/foo --deselect skills/foo/scripts/test_x.py::test_y"]) == []


def test_another_task_that_runs_the_excluded_suite_covers_it():
    commands = ["pytest skills/foo skills/bar --ignore skills/foo/scripts", "pytest -q skills/foo/scripts"]
    assert _uncovered([SUITE], commands) == []
    commands = ["pytest skills/foo --ignore=skills/foo/scripts", "uv run --directory skills/foo/scripts pytest"]
    assert _uncovered([SUITE], commands) == []


def test_exclusion_in_one_task_does_not_leak_into_another():
    commands = ["pytest skills/bar --ignore skills/foo", "pytest skills/foo"]
    assert _uncovered([SUITE], commands) == []
