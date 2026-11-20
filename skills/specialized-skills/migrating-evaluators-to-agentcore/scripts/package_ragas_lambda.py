#!/usr/bin/env python3
"""Package RAGAS evaluator Lambdas against exact PyPI pins.

For each evaluator app dir, pins the dependencies in pyproject.toml, writes overrides.txt and
prepends the ragas import stubs to the handler. The self-test then resolves the bundle as CDK
does, checks Lambda's 250MB unzipped limit and imports each handler in an isolated venv.

Usage:
    python3 package_ragas_lambda.py --project-dir <agentcore-project> \\
        --evaluator <name> [--evaluator <name> ...] [--skip-self-test]
"""

from __future__ import annotations

import argparse
import ast
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

LAMBDA_UNZIPPED_LIMIT = 262_144_000  # bytes (250 MiB)
# CDK bundling prefers the first tag; the self-test must resolve for the same one.
CDK_PLATFORM_CANDIDATES = ("x86_64-manylinux_2_28", "x86_64-manylinux2014")
LAMBDA_PYTHON = "3.12"

# Sized for a cold uv cache (~200MB download); exceeding one means a stalled download.
RESOLVE_TIMEOUT_S = 300
STEP_TIMEOUT_S = 120

# These are runtime-provided or unused; an always-false marker drops them to fit the 250MB limit.
OVERRIDES = (
    'boto3; python_version < "3"\n'
    'botocore; python_version < "3"\n'
    'strands-agents-tools; python_version < "3"\n'
    'datasets; python_version < "3"\n'
    'langchain-community; python_version < "3"\n'
    'networkx; python_version < "3"\n'
    'scikit-network; python_version < "3"\n'
    # Imported only by ragas's opt-in DiskCacheBackend, which no handler constructs; it has no
    # release fixing GHSA-w8v5-vhqr-4h9v (unsafe pickle deserialization).
    'diskcache; python_version < "3"\n'
)

#: Pinned exactly, so a new PyPI release cannot change what ships to a customer Lambda.
BEDROCK_AGENTCORE_PIN = "bedrock-agentcore==1.23.0"
RAGAS_PIN = "ragas==0.4.4"
STRANDS_EVALS_PIN = "strands-agents-evals==1.2.0"

# The handler imports strands.plugins, missing below ~1.44; strands-agents-evals allows >= 1.42.
STRANDS_AGENTS_PIN = "1.50.1"

# Only the Lambdas whose handler needs one of these get it. Leaving one out moves no other
# pin: each subset resolves to the full set's version of every package it shares.
LANGCHAIN_AWS_PIN = "langchain-aws==1.7.8"  # ChatBedrockConverse / BedrockEmbeddings
RAPIDFUZZ_PIN = "rapidfuzz==3.14.6"
SACREBLEU_PIN = "sacrebleu==2.6.0"
#: ragas metrics that import rapidfuzz / sacrebleu when constructed (in __post_init__).
RAPIDFUZZ_METRICS = frozenset(
    {"NonLLMStringSimilarity", "NonLLMContextRecall", "NonLLMContextPrecisionWithReference"}
)
SACREBLEU_METRICS = frozenset({"BleuScore", "ChrfScore"})

#: The Lambda runtime provides boto3, so the bundle excludes it; the self-test venv stands in
#: for the runtime with the version the skill pins everywhere else.
SELF_TEST_BOTO3_PIN = "boto3==1.43.75"

# Stubs for modules ragas imports at load time but the adapter never calls (OVERRIDES drops them).
STUB_PRELUDE = """\
# RAGAS_IMPORT_STUBS — must run before any ragas import (do not remove)
import sys as _sys, types as _types
if "datasets" not in _sys.modules:
    _d = _types.ModuleType("datasets")
    _d.Dataset = type("Dataset", (), {})
    _sys.modules["datasets"] = _d
if "langchain_community" not in _sys.modules:
    _lc = _types.ModuleType("langchain_community")
    _cm = _types.ModuleType("langchain_community.chat_models")
    _vx = _types.ModuleType("langchain_community.chat_models.vertexai")
    _vx.ChatVertexAI = type("ChatVertexAI", (), {})
    _ll = _types.ModuleType("langchain_community.llms")
    _ll.VertexAI = type("VertexAI", (), {})
    _cm.vertexai = _vx
    _lc.chat_models = _cm
    _lc.llms = _ll
    _sys.modules.update({
        "langchain_community": _lc,
        "langchain_community.chat_models": _cm,
        "langchain_community.chat_models.vertexai": _vx,
        "langchain_community.llms": _ll,
    })
# END RAGAS_IMPORT_STUBS

"""


def _handler_imports(handler_source: str) -> tuple[set[str], set[str]]:
    """Return (top-level modules the handler imports, names it imports from ragas.metrics)."""
    try:
        tree = ast.parse(handler_source)
    except SyntaxError as exc:
        raise SystemExit(f"[ERROR] handler does not parse: {exc}") from None
    modules: set[str] = set()
    metrics: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
            if node.module == "ragas.metrics":
                metrics |= {alias.name for alias in node.names}
    return modules, metrics


def lambda_deps(handler_source: str | None = None) -> list[str]:
    """Return the pinned dependency list for a RAGAS evaluator Lambda.

    Given the handler's source, only the optional pins it needs are added; without one, all
    of them are (the superset the harness warms its cache with). Each entry must resolve from
    PyPI as a wheel (CDK bundles with ``--only-binary :all:``); metrics whose dependencies
    cannot are refused in classify.py (``RAGAS_UNSUPPORTED``).
    """
    deps = [
        BEDROCK_AGENTCORE_PIN,  # ships the third_party adapters from 1.23.0
        RAGAS_PIN,  # heavy transitives are excluded via OVERRIDES
        STRANDS_EVALS_PIN,  # default span mapping in the adapter
        f"strands-agents=={STRANDS_AGENTS_PIN}",  # provides strands.plugins
        "setuptools==84.1.0",  # pkg_resources (sacrebleu et al.)
    ]
    if handler_source is None:
        return deps + [LANGCHAIN_AWS_PIN, RAPIDFUZZ_PIN, SACREBLEU_PIN]
    modules, metrics = _handler_imports(handler_source)
    if "langchain_aws" in modules:
        deps.append(LANGCHAIN_AWS_PIN)
    if metrics & RAPIDFUZZ_METRICS:
        deps.append(RAPIDFUZZ_PIN)
    if metrics & SACREBLEU_METRICS:
        deps.append(SACREBLEU_PIN)
    return deps


def write_pyproject(app_dir: Path, deps: list[str]) -> None:
    pyproject = app_dir / "pyproject.toml"
    deps_toml = ",\n".join(f'  "{d}"' for d in deps)
    if pyproject.exists():
        content = pyproject.read_text()
        new_content, n = re.subn(
            r"dependencies\s*=\s*\[[^\]]*\]",
            f"dependencies = [\n{deps_toml},\n]",
            content,
            count=1,
            flags=re.DOTALL,
        )
        if n == 0:
            # Insert into the existing [project] table; uv rejects a duplicate one at bundle time.
            block = f"dependencies = [\n{deps_toml},\n]"
            if re.search(r"^\[project\]", content, flags=re.MULTILINE):
                new_content = re.sub(
                    r"^(\[project\][ \t]*\n)",
                    lambda m: m.group(1) + block + "\n",
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                new_content = content + f"\n[project]\n{block}\n"
        pyproject.write_text(new_content)
    else:
        name = app_dir.name.lower().replace("_", "-")
        pyproject.write_text(
            f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
            f'requires-python = ">={LAMBDA_PYTHON}"\ndependencies = [\n{deps_toml},\n]\n'
        )
    print(f"  [PYPROJECT] {len(deps)} declarative deps written")


# Matches an existing prelude of any version, so re-packaging replaces it instead of stacking.
_STUB_BLOCK_RE = re.compile(r"# RAGAS_IMPORT_STUBS.*?# END RAGAS_IMPORT_STUBS\n*", re.DOTALL)


def inject_stubs(app_dir: Path) -> None:
    handler = app_dir / "lambda_function.py"
    if not handler.exists():
        raise SystemExit(f"[ERROR] {handler} not found — copy handler code first")
    content = handler.read_text()
    content, replaced = _STUB_BLOCK_RE.subn("", content)
    if replaced:
        print("  [STUBS] existing stub prelude found — replacing with current version")
    handler.write_text(STUB_PRELUDE + content)
    print(
        "  [STUBS] datasets/langchain_community stub prelude injected "
        "(strands.plugins is NOT stubbed — the real package is pinned in)"
    )


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class SelfTestEnv:
    """Lambda-faithful resolve-and-import environment, built once per distinct dependency set.

    Handlers import in a fresh Python 3.12 venv that sees only the bundle plus boto3, as on
    Lambda, so a missing dependency fails here instead of after a deploy.
    """

    def __init__(self, deps: list[str], overrides_file: Path):
        self._tmp = tempfile.TemporaryDirectory(prefix="ragas_selftest.")
        tmp = Path(self._tmp.name)
        self.target = tmp / "bundle"
        self.venv_python = tmp / "venv" / "bin" / "python"

        cmd = [
            "uv",
            "pip",
            "install",
            "--only-binary",
            ":all:",
            "--overrides",
            str(overrides_file),
            "--python-version",
            LAMBDA_PYTHON,
            "--python-platform",
            CDK_PLATFORM_CANDIDATES[0],
            "--target",
            str(self.target),
            *deps,
        ]
        print(
            f"[SELF-TEST] resolving once (CDK-equivalent): uv pip install "
            f"--only-binary :all: ... ({len(deps)} declared deps)"
        )
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RESOLVE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise SystemExit(
                f"[ERROR] dependency resolution timed out after {RESOLVE_TIMEOUT_S}s — "
                "likely a cold uv cache or a broken network. The first cold resolve "
                "downloads ~200MB; re-running is cheap once it has been cached, so "
                "check connectivity and retry."
            )
        if proc.returncode != 0:
            print(proc.stdout[-2000:])
            print(proc.stderr[-4000:])
            raise SystemExit(
                "[ERROR] dependency resolution FAILED — this is exactly what CDK "
                "bundling would hit. Fix before deploying."
            )

        if (self.target / "botocore").exists() or (self.target / "boto3").exists():
            raise SystemExit(
                "[ERROR] boto3/botocore leaked into the bundle — the overrides file "
                "was not honored. Check the uv version supports --overrides/UV_OVERRIDE."
            )
        print("  [OK] boto3/botocore excluded from the bundle")

        self.resolved_size = _dir_size(self.target)

        try:
            subprocess.run(
                ["uv", "venv", "--python", LAMBDA_PYTHON, str(tmp / "venv")],
                check=True,
                capture_output=True,
                text=True,
                timeout=STEP_TIMEOUT_S,
            )
            # The Lambda runtime provides boto3, so it goes in the venv rather than the bundle.
            # PYTHONPATH precedes venv site-packages, so bundle versions still win.
            proc = subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(self.venv_python),
                    "--only-binary",
                    ":all:",
                    SELF_TEST_BOTO3_PIN,
                ],
                capture_output=True,
                text=True,
                timeout=STEP_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise SystemExit(
                f"[ERROR] self-test venv provisioning timed out ({STEP_TIMEOUT_S}s) — "
                "likely a cold uv cache or a broken network. Check connectivity and "
                "retry; the download is cached after the first success."
            )
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
            raise SystemExit(
                "[ERROR] could not provision boto3 into the self-test venv — "
                "cannot run a Lambda-faithful import test."
            )
        # Checked before any handler, so a venv problem is never misreported as a bundle problem.
        proc = subprocess.run(
            [str(self.venv_python), "-c", "import boto3"],
            capture_output=True,
            text=True,
            timeout=STEP_TIMEOUT_S,
        )
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
            raise SystemExit("[ERROR] boto3 not importable from the self-test venv.")

    def check_app(self, app_dir: Path) -> None:
        """Size-gate an app dir, and isolated-import it when the host can load the bundle."""
        bundle_size = self.resolved_size + _dir_size(app_dir)
        pct = bundle_size / LAMBDA_UNZIPPED_LIMIT * 100
        print(
            f"  [SIZE] unzipped bundle: {bundle_size / 1e6:.0f}MB "
            f"({pct:.0f}% of the 250MB Lambda limit)"
        )
        if bundle_size >= LAMBDA_UNZIPPED_LIMIT:
            raise SystemExit(f"[ERROR] bundle exceeds Lambda's unzipped limit for {app_dir.name}")

        # The bundle holds x86_64 native wheels, which other architectures cannot import.
        if platform.machine() != "x86_64":
            print(
                f"  [SKIP] isolated import: bundle is x86_64, host is {platform.machine()} "
                "— the wheels cannot load here. Size gate above still applies."
            )
            return

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            "PYTHONPATH": f"{app_dir}:{self.target}",
            "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
            # Stops ragas sending usage analytics from this host during the import below.
            "RAGAS_DO_NOT_TRACK": "true",
        }
        try:
            proc = subprocess.run(
                [str(self.venv_python), "-c", "import lambda_function; print('IMPORT_OK')"],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(app_dir),
                timeout=STEP_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise SystemExit(
                f"[ERROR] isolated handler import timed out ({STEP_TIMEOUT_S}s) for "
                f"{app_dir.name} — the handler is blocking at import time (network "
                "call or model download at module level?). Fix before deploying."
            )
        if proc.returncode != 0 or "IMPORT_OK" not in proc.stdout:
            print(proc.stdout[-1000:])
            print(proc.stderr[-4000:])
            raise SystemExit(
                f"[ERROR] isolated handler import FAILED for {app_dir.name} — a "
                "dependency is missing from the bundle. Fix before deploying."
            )
        print("  [SELF-TEST] handler imports cleanly in a Lambda-faithful environment")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--project-dir", required=True, help="agentcore project dir (contains app/)"
    )
    parser.add_argument(
        "--evaluator", action="append", required=True, help="evaluator name (repeatable)"
    )
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    from names import validate_evaluator_name  # names.py ships beside this script

    # Files in each app dir get rewritten, so every name must be a bare evaluator name resolving
    # inside app/ (symlinks included). All are checked before anything is written.
    apps_root = (project_dir / "app").resolve()
    app_dirs = []
    for name in args.evaluator:
        try:
            validate_evaluator_name(name)
        except ValueError as exc:
            raise SystemExit(f"[ERROR] {exc}") from None
        app_dir = project_dir / "app" / name
        if not app_dir.is_dir():
            raise SystemExit(f"[ERROR] {app_dir} not found — run 'agentcore add evaluator' first")
        if app_dir.resolve().parent != apps_root:
            raise SystemExit(f"[ERROR] {app_dir} resolves outside {apps_root}")
        app_dirs.append((name, app_dir))

    overrides_file = project_dir / "overrides.txt"
    overrides_file.write_text(OVERRIDES)
    print(f"[PACKAGE] overrides file: {overrides_file} (excludes boto3/botocore)")

    # One self-test environment per distinct dependency set, built when first needed.
    test_envs: dict[tuple[str, ...], SelfTestEnv] = {}
    for name, app_dir in app_dirs:
        print(f"[PACKAGE] {name}")
        handler = app_dir / "lambda_function.py"
        if not handler.exists():
            raise SystemExit(f"[ERROR] {handler} not found — copy handler code first")
        deps = lambda_deps(handler.read_text())
        optional = [d for d in deps if d in (LANGCHAIN_AWS_PIN, RAPIDFUZZ_PIN, SACREBLEU_PIN)]
        print(f"  [DEPS] optional pins this handler needs: {', '.join(optional) or 'none'}")
        write_pyproject(app_dir, deps)
        # Also copied into the app dir so CDK bundling finds one in its working directory.
        shutil.copy2(overrides_file, app_dir / "overrides.txt")
        inject_stubs(app_dir)
        if not args.skip_self_test:
            key = tuple(deps)
            if key not in test_envs:
                test_envs[key] = SelfTestEnv(deps, overrides_file)
            test_envs[key].check_app(app_dir)

    print(
        "[DONE] all evaluators packaged — deploy with UV_OVERRIDE exported; "
        "migration.sh does this"
    )


if __name__ == "__main__":
    main()
