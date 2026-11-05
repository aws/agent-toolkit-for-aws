"""Every per-skill test suite must run in `mise run ci`.

GitHub CI runs only `mise -C plugins/aws-startup-advisor run ci`, so a skill directory with
test files that no `ci` dependency task covers never runs in CI. This guard fails when a new
skill test directory appears without a task.

A task covers a test directory when one of its command arguments is that directory or one of
its ancestors under `skills/` (so `pytest skills/foo/scripts` covers `skills/foo/scripts/tests`).
Arguments that only exclude a path (`--ignore`, `--deselect`) do not count.

Requires Python 3.11+ for `tomllib`; CI runs it under the mise-pinned Python 3.12 via uv.
"""
from __future__ import annotations

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


def _covered_paths(commands: list[str]) -> list[PurePosixPath]:
    paths = []
    for command in commands:
        tokens = shlex.split(command)
        for i, token in enumerate(tokens):
            flag, _, value = token.partition("=")
            if flag in EXCLUDING_FLAGS:
                continue  # `--ignore=path`: an exclusion, not coverage
            if i and tokens[i - 1] in EXCLUDING_FLAGS:
                continue  # `--ignore path`
            candidate = value if flag.startswith("--") and value else token
            if candidate.startswith("skills/"):
                paths.append(PurePosixPath(candidate.rstrip("/")))
    return paths


def _skill_test_dirs() -> list[PurePosixPath]:
    dirs = set()
    for pattern in TEST_FILE_PATTERNS:
        for path in (PLUGIN_ROOT / "skills").rglob(pattern):
            rel = path.relative_to(PLUGIN_ROOT)
            if SKIP_PARTS.isdisjoint(rel.parts):
                dirs.add(PurePosixPath(rel.parent.as_posix()))
    return sorted(dirs)


def _uncovered(test_dirs, covered):
    return [d for d in test_dirs if not any(d == c or d.is_relative_to(c) for c in covered)]


def test_every_skill_test_directory_runs_in_ci():
    missing = _uncovered(_skill_test_dirs(), _covered_paths(_ci_commands()))
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
    assert _uncovered(nested, _covered_paths(["pytest -q skills/foo/scripts"])) == []
    assert _uncovered(nested, _covered_paths(["uv run --directory skills/foo/scripts pytest"])) == []
    assert _uncovered(nested, _covered_paths(["pytest skills/bar --ignore skills/foo/scripts"])) == nested
    assert _uncovered(nested, _covered_paths(["pytest skills/bar --ignore=skills/foo"])) == nested
    # A sibling whose name shares a prefix is not an ancestor.
    assert _uncovered(nested, _covered_paths(["pytest skills/foo/scr"])) == nested
