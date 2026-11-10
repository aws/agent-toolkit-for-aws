"""Every per-skill test suite must run in `mise run ci`.

GitHub CI runs only `mise -C plugins/aws-startup-advisor run ci`, so a skill directory with
test files that no `ci` dependency task covers never runs in CI. This guard fails when a new
skill test directory appears without a task.

A command covers a test directory when one of its arguments is that directory or one of its
ancestors under `skills/` (so `pytest skills/foo/scripts` covers `skills/foo/scripts/tests`) and
none of the same command's exclusions (`--ignore`, `--ignore-glob`, `--deselect`) is that
directory or an ancestor. Exclusions apply per command, before coverage is combined across tasks,
so `pytest skills/foo --ignore skills/foo/scripts` does not cover `skills/foo/scripts` unless
another task runs it. Relative selectors resolve against the working directory set by
`uv run --directory`, and a pytest command with explicit paths covers only those paths.

Requires Python 3.11+ for `tomllib`; the `test` task pins `uv run --python 3.12`.
"""
from __future__ import annotations

import fnmatch
import posixpath
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


# pytest options whose value is a separate token (so the value is not mistaken for a path).
PYTEST_VALUE_FLAGS = {
    "-k", "-m", "-p", "-c", "-o", "-n", "-r", "-W", "--rootdir", "--maxfail", "--import-mode",
    "--basetemp", "--confcutdir", "--junitxml", "--durations", "--tb", "--log-level",
}


def _normalize(path: str, base: str | None) -> str:
    """Resolve a selector against the command's working directory (`uv run --directory`)."""
    path = path.split("::", 1)[0].rstrip("/")  # `--deselect file::test` -> file
    if base and not path.startswith("skills/"):
        path = posixpath.join(base, path)
    return posixpath.normpath(path)


def _pytest_start(tokens: list[str]) -> int | None:
    """Index after the pytest command itself (not the `pytest` in `--with pytest`)."""
    hits = [i for i, t in enumerate(tokens) if t == "pytest" and (i == 0 or tokens[i - 1] != "--with")]
    return hits[-1] + 1 if hits else None


def _command_scope(command: str) -> tuple[list[PurePosixPath], list[str]]:
    """Return (paths the command runs, exclusion patterns), both relative to the plugin root."""
    tokens = shlex.split(command)
    base = None
    for i, token in enumerate(tokens):
        flag, eq, value = token.partition("=")
        if flag == "--directory":
            base = value if eq else (tokens[i + 1] if i + 1 < len(tokens) else None)
            break
    base = base.rstrip("/") if base else None

    start = _pytest_start(tokens)
    includes: list[str] = []
    excludes: list[str] = []
    positional: list[str] = []
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
        if start is not None and i >= start:
            if token in PYTEST_VALUE_FLAGS:
                skip_next = True
            elif not token.startswith("-"):
                positional.append(token)
        elif start is None:
            candidate = value if flag.startswith("--") and eq else token
            if candidate.startswith("skills/"):
                includes.append(candidate)

    if start is not None:
        # pytest runs its positional paths, or its working directory when none are given.
        includes = positional or ([base] if base else [])
    return (
        [PurePosixPath(_normalize(p, base)) for p in includes],
        [_normalize(e, base) for e in excludes],
    )


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


def test_relative_exclusions_resolve_against_uv_directory():
    nested = PurePosixPath("skills/foo/scripts/tests")
    own = PurePosixPath("skills/foo/scripts")
    for command in (
        "uv run --directory skills/foo/scripts python -m pytest --ignore tests",
        "uv run --directory skills/foo/scripts python -m pytest --ignore=tests",
        "uv run --directory=skills/foo/scripts python -m pytest --ignore ./tests/",
    ):
        assert _uncovered([nested], [command]) == [nested], command
        assert _uncovered([own], [command]) == [], command
    # Separate-task control: another task that runs the nested suite still covers it.
    assert _uncovered([nested], [
        "uv run --directory skills/foo/scripts python -m pytest --ignore tests",
        "uv run --directory skills/foo/scripts/tests python -m pytest -q",
    ]) == []


def test_explicit_pytest_paths_limit_coverage():
    unit = PurePosixPath("skills/foo/scripts/tests/unit")
    other = PurePosixPath("skills/foo/scripts/tests/other")
    command = "uv run --directory skills/foo/scripts python -m pytest -q tests/unit"
    assert _uncovered([unit, other], [command]) == [other]


def test_option_values_and_with_pytest_are_not_paths():
    suite = PurePosixPath("skills/foo/scripts")
    # `-k tests` is an expression, not a path; the whole directory still runs.
    assert _uncovered([suite], ["uv run --directory skills/foo/scripts python -m pytest -k tests"]) == []
    # The `pytest` after `--with` is a dependency, not the command.
    assert _uncovered([suite], ["uv run --no-project --with pytest python -m pytest -q skills/foo/scripts"]) == []
    assert _uncovered([suite], ["uv run --no-project --with pytest python -m pytest -q skills/bar"]) == [suite]
