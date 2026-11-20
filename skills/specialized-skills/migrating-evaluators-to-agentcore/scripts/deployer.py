"""Generate migration.sh, which deploys code-based evaluators with the AgentCore CLI.

Also holds the preflight check and the judge-model and IAM helpers that
generate_handlers.py shares.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Lets the sibling modules import the same way whether installed or copied standalone.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from names import (  # noqa: E402
    generate_project_name,
    lambda_function_name,
    validate_evaluator_name,
    validate_framework,
    validate_handler_file,
    validate_project_name,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class PreflightResult:
    """Result of preflight checks."""

    ok: bool
    node_version: Optional[str] = None
    node_path: Optional[str] = None
    uv_available: bool = False
    typescript_version: Optional[str] = None
    aws_account: Optional[str] = None
    aws_region: Optional[str] = None
    agentcore_cli_version: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)


# =============================================================================
# Preflight checks
# =============================================================================


def preflight_check(region: str = "us-east-1") -> PreflightResult:
    """Check Node.js 20+, uv, TypeScript 5.x, AWS credentials and the agentcore CLI."""
    result = PreflightResult(ok=True, aws_region=region)

    node_path = _find_node_20_plus()
    if node_path:
        result.node_path = node_path
        result.node_version = _run_cmd([node_path, "--version"]).strip()
    else:
        result.ok = False
        result.errors.append("Node.js 20+ not found (required by agentcore CLI)")
        result.fixes.append("Install Node 20: mise install node@20.19.2 OR nvm install 20.19.2")

    uv_path = shutil.which("uv")
    if uv_path:
        result.uv_available = True
    else:
        result.ok = False
        result.errors.append("uv not found (required for Python Lambda packaging)")
        # Pinned pip install only; never pipe a remote install script into a shell.
        result.fixes.append("Install uv: pip install 'uv==0.12.10'")

    if node_path:
        node_dir = str(Path(node_path).parent)
        tsc_path = shutil.which("tsc", path=node_dir + ":" + os.environ.get("PATH", ""))
        if tsc_path:
            ts_version = _run_cmd([tsc_path, "--version"]).strip()
            result.typescript_version = ts_version
            major = _parse_major_version(ts_version.replace("Version ", ""))
            if major and major >= 6:
                result.warnings.append(
                    f"TypeScript {ts_version} detected. AgentCore CLI scaffolds tsconfig "
                    f"for TS 5.x. TS 6+ deprecates moduleResolution=node10. "
                    f"The migration.sh will install typescript@5.9.3."
                )
        else:
            result.warnings.append(
                "TypeScript not installed globally. migration.sh will install typescript@5.9.3."
            )

    try:
        import boto3

        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        result.aws_account = identity["Account"]
    except Exception as e:
        result.ok = False
        result.errors.append(f"AWS credentials invalid or expired: {e}")
        result.fixes.append(
            "Refresh the AWS credentials in the default credential chain (for example "
            "`aws sso login`) for a least-privilege role with bedrock-agentcore, lambda, iam, "
            "cloudformation, s3 and logs permissions — not an administrator role"
        )

    if node_path:
        node_dir = str(Path(node_path).parent)
        agentcore_path = shutil.which("agentcore", path=node_dir + ":" + os.environ.get("PATH", ""))
        if agentcore_path:
            version = _run_cmd([agentcore_path, "--version"]).strip()
            result.agentcore_cli_version = version
        else:
            result.warnings.append("agentcore CLI not installed. migration.sh will install it.")

    return result


def _find_node_20_plus() -> Optional[str]:
    """Return a Node.js 20+ binary from PATH, mise or nvm, in that order."""
    current_node = shutil.which("node")
    if current_node:
        version = _run_cmd([current_node, "--version"]).strip()
        major = _parse_major_version(version.lstrip("v"))
        if major and major >= 20:
            return current_node

    mise_base = Path.home() / ".local" / "share" / "mise" / "installs" / "node"
    if mise_base.exists():
        for version_dir in sorted(mise_base.iterdir(), reverse=True):
            major = _parse_major_version(version_dir.name)
            if major and major >= 20:
                node_bin = version_dir / "bin" / "node"
                if node_bin.exists():
                    return str(node_bin)

    nvm_base = Path.home() / ".nvm" / "versions" / "node"
    if nvm_base.exists():
        for version_dir in sorted(nvm_base.iterdir(), reverse=True):
            major = _parse_major_version(version_dir.name.lstrip("v"))
            if major and major >= 20:
                node_bin = version_dir / "bin" / "node"
                if node_bin.exists():
                    return str(node_bin)

    return None


#: Foundation model behind every LLM-as-a-Judge evaluator this skill deploys.
JUDGE_FOUNDATION_MODEL = "anthropic.claude-sonnet-4-5-20250929-v1:0"

#: Embeddings model for RAGAS metrics with ``needs_embeddings=True``. The handler template and
#: the IAM policy both read it from here, so they cannot drift apart.
EMBEDDINGS_MODEL = "amazon.titan-embed-text-v2:0"

#: Region -> cross-region inference-profile prefix.
_REGION_PREFIX_MAP = {
    "us-east-1": "us",
    "us-west-2": "us",
    "us-east-2": "us",
    "eu-central-1": "eu",
    "eu-west-1": "eu",
    "ap-southeast-2": "au",
    "ap-south-1": "apac",
    "ap-southeast-1": "apac",
    "ap-northeast-1": "jp",
}


def judge_model_id(region: str) -> str:
    """Return the judge model's inference-profile ID for ``region``.

    Raises ``ValueError`` for an unmapped region rather than guessing a prefix. The handler,
    the IAM ARN and the evaluator ``modelId`` all resolve through this function.
    """
    try:
        prefix = _REGION_PREFIX_MAP[region]
    except KeyError:
        raise ValueError(
            f"No cross-region inference-profile prefix is configured for region "
            f"{region!r}. Add it to _REGION_PREFIX_MAP or deploy to one of the "
            f"supported regions: {', '.join(sorted(_REGION_PREFIX_MAP))}."
        ) from None
    return f"{prefix}.{JUDGE_FOUNDATION_MODEL}"


def validate_region(region: str) -> str:
    """Return ``region`` unchanged, raising ``ValueError`` if it is unsupported."""
    judge_model_id(region)
    return region


#: Stands in for the account while generate_migration_sh writes the policy; the script
#: substitutes the STS-resolved account before anything is deployed.
_ACCOUNT_PLACEHOLDER = "__AWS_ACCOUNT__"

#: Marks generated handler code the agent must complete from the source script. Built from
#: two halves, here and in migration.sh, so a grep for unfinished markers finds only those.
_TODO_MARKER = "TODO(" + "EVAL-MIGRATION)"


def judge_invoke_resources(region: str, account_id: str) -> list[str]:
    """Least-privilege ``bedrock:InvokeModel`` resources for the generated handlers.

    Covers the judge inference profile, its foundation model and the embeddings model. The
    handlers call the profile and the embeddings model in their own Lambda's region, the
    deploy region; only the judge's foundation model takes a wildcard region, because the
    cross-region profile routes each request to one of several regions. ``account_id`` must
    be a 12-digit account ID.
    """
    if not (
        isinstance(account_id, str)
        and (account_id == _ACCOUNT_PLACEHOLDER or re.fullmatch(r"\d{12}", account_id))
    ):
        raise ValueError(
            f"account_id must be the caller's 12-digit AWS account ID, got {account_id!r}. "
            "Resolve it with sts:GetCallerIdentity; the inference-profile ARN is never "
            "widened to every account."
        )
    return [
        f"arn:aws:bedrock:{region}:{account_id}:inference-profile/{judge_model_id(region)}",
        f"arn:aws:bedrock:*::foundation-model/{JUDGE_FOUNDATION_MODEL}",
        f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDINGS_MODEL}",
    ]


def _assert_handler_region(handler_path: Path, region: str) -> None:
    """Fail if a handler invokes a judge model this region's IAM policy will not cover.

    The handlers and migration.sh receive the region separately. A mismatch deploys cleanly
    and then fails at invoke time with errors that do not name the cause.
    """
    expected = judge_model_id(region)
    # Built from the map so new prefixes are covered; longest first so none shadows another.
    prefixes = "|".join(
        re.escape(p) for p in sorted(set(_REGION_PREFIX_MAP.values()), key=lambda p: (-len(p), p))
    )
    found = set(
        re.findall(
            rf'model(?:_id)?="((?:{prefixes})\.anthropic\.[^"]+)"',
            handler_path.read_text(),
        )
    )
    mismatched = sorted(m for m in found if m != expected)
    if mismatched:
        raise ValueError(
            f"{handler_path.name} invokes {', '.join(mismatched)} but this deployment "
            f"scopes bedrock:InvokeModel to {expected} for region {region!r}. "
            f"Bedrock would reject the modelId and IAM would deny it. "
            f"Regenerate the handlers for this region:\n"
            f"  python3 generate_handlers.py --mapping mapping.json --names names.json "
            f"--output-dir handlers --region {region}"
        )


def _parse_major_version(version_str: str) -> Optional[int]:
    """Parse major version number from a version string like '20.18.0'."""
    try:
        return int(version_str.split(".")[0])
    except (ValueError, IndexError):
        return None


def _run_cmd(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and return stdout. Returns empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# =============================================================================
# Migration script generation
# =============================================================================

#: Exact versions for the CDK app that `agentcore create` scaffolds with `~` ranges and no
#: lockfile. @types/jest stays because tsc type-checks the scaffold's test/ directory.
CDK_NPM_PINS = {
    "dependencies": {
        "@aws/agentcore-cdk": "0.1.0-alpha.50",
        "aws-cdk-lib": "2.261.0",
        "constructs": "10.7.0",
    },
    "devDependencies": {
        "aws-cdk": "2.1126.0",
        "typescript": "5.9.3",
        "@types/node": "24.13.3",
        "@types/jest": "29.5.14",
    },
}
#: Scaffold test runner and formatter; the deploy never runs them, so they are not installed.
CDK_NPM_DROPPED = ("jest", "ts-jest", "prettier")
#: Exact pins injected into a DeepEval evaluator's pyproject. Module-level so assets/
#: requirements.txt can be generated from them rather than restating them.
DEEPEVAL_PINS = ("requests==2.34.2", "deepeval==4.2.3", "aiobotocore==3.9.1")
DEEPEVAL_EMBEDDING_PIN = "numpy==1.26.4"  # embedding and relevancy evaluators only
#: Requirements the DeepEval bundle drops, with the always-false marker the RAGAS path uses.
#: strands-agents-tools arrives through strands-agents-evals, is never imported by an
#: evaluator, and caps pillow below 13 (the release that fixes its advisories).
DEEPEVAL_OVERRIDES = 'strands-agents-tools; python_version < "3"\n'


def deepeval_injected_pins() -> tuple[str, ...]:
    """The exact pins step 10 writes into a DeepEval evaluator's pyproject.

    strands-agents is pinned to the RAGAS path's version: left to float it resolves to a
    release that requires mcp 2.x, whose 2.1.1 carries advisories that 1.30.0 does not.
    """
    from package_ragas_lambda import STRANDS_AGENTS_PIN

    return (*DEEPEVAL_PINS, f"strands-agents=={STRANDS_AGENTS_PIN}")


def deepeval_lambda_deps() -> list[str]:
    """Every exact pin a DeepEval evaluator's pyproject can end up with.

    The union of what step 10 injects and what verify_deps.verify_deepeval adds, so the
    hash-pinned resolved set can be generated from, and tested against, one list.
    """
    from package_ragas_lambda import BEDROCK_AGENTCORE_PIN, STRANDS_EVALS_PIN

    return [
        BEDROCK_AGENTCORE_PIN,
        STRANDS_EVALS_PIN,
        *deepeval_injected_pins(),
        DEEPEVAL_EMBEDDING_PIN,
    ]


#: Lists every declared pin for review; not an install target (see the file's header).
DEPENDENCY_MANIFEST = _SCRIPTS_DIR.parent / "assets" / "requirements.txt"
#: Hash-pinned resolved sets, one per framework path. Passed to the CDK's uv as UV_CONSTRAINT
#: with UV_REQUIRE_HASHES, which is what makes the bundle's checksums verified rather than
#: merely recorded. A superset constrains any handler subset: constraints cap only what
#: resolves, and each subset resolves to the full set's version of every package it shares.
RESOLVED_REQUIREMENTS = {
    "ragas": _SCRIPTS_DIR.parent / "assets" / "requirements" / "ragas.txt",
    "deepeval": _SCRIPTS_DIR.parent / "assets" / "requirements" / "deepeval.txt",
}
#: npm lockfile for the scaffold's package.json with CDK_NPM_PINS applied, so `npm ci` pins
#: every transitive dependency too and checks each tarball against its sha512. After changing
#: the pins, regenerate it with npm 10.8.2: apply them as migration.sh step 11 does, then run
#: `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`.
CDK_LOCKFILE = _SCRIPTS_DIR.parent / "assets" / "cdk-package-lock.json"
_NPM_REGISTRY = "https://registry.npmjs.org/"


def checked_cdk_lockfile() -> Path:
    """Return CDK_LOCKFILE, or raise ValueError unless it locks exactly CDK_NPM_PINS."""
    try:
        packages = json.loads(CDK_LOCKFILE.read_text())["packages"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"cannot read the CDK lockfile {CDK_LOCKFILE}: {exc}. Over MCP, fetch "
            "assets/cdk-package-lock.json into assets/ beside scripts/."
        ) from None
    root = packages.get("", {})
    for section, pins in CDK_NPM_PINS.items():
        if root.get(section) != pins:
            raise ValueError(
                f"{CDK_LOCKFILE.name} locks {section} {root.get(section)}, not CDK_NPM_PINS "
                f"{pins}. Regenerate it as the CDK_LOCKFILE comment describes."
            )
    for name, meta in packages.items():
        resolved, integrity = str(meta.get("resolved", "")), str(meta.get("integrity", ""))
        if name and not (resolved.startswith(_NPM_REGISTRY) and integrity.startswith("sha512-")):
            raise ValueError(f"{CDK_LOCKFILE.name}: {name} lacks a registry URL or sha512")
    return CDK_LOCKFILE


def checked_constraint_file(framework: str) -> Path | None:
    """Return the hash-pinned resolved set for ``framework``, or None if it has none.

    Raises ValueError when the file is missing or unusable, rather than letting the deploy
    reach uv and fail there: hash mode rejects the whole install, so a bad constraint file
    surfaces as an opaque resolution error several minutes in.
    """
    path = RESOLVED_REQUIREMENTS.get(framework)
    if path is None:
        return None
    try:
        text = path.read_text()
    except OSError as exc:
        raise ValueError(
            f"cannot read {path} ({exc}). Over MCP, fetch "
            f"assets/requirements/{path.name} into assets/requirements/ beside scripts/."
        ) from None
    if "--hash=sha256:" not in text:
        raise ValueError(
            f"{path.name} carries no hashes, so UV_REQUIRE_HASHES would reject every "
            "package. Regenerate it with --generate-hashes as its header describes."
        )
    return path


def generate_migration_sh(
    evaluator_names: list[tuple[str, str, str]] | None = None,
    handler_dir: str | Path = "handlers",
    output_dir: str | Path = "deploy",
    region: str = "us-east-1",
    project_name: str | None = None,
    framework: str = "deepeval",
    task: str = "eval",
    *,
    # Tolerated so a common wrong call does not raise TypeError; the manifest wins.
    mapping_file: str | Path | None = None,  # noqa: ARG001
    names_file: str | Path | None = None,  # noqa: ARG001
    handlers_dir: str | Path | None = None,
) -> Path:
    """Write ``output_dir/migration.sh``, which deploys code-based evaluators with the CLI.

    Args:
        evaluator_names: ``(name, level, handler_file)`` tuples. Defaults to the entries in
            ``handler_dir/evaluators.json``.
        handler_dir: Directory containing the generated handlers.
        output_dir: Directory for migration.sh, names.json and the handler copies.
        region: AWS region to deploy to.
        project_name: AgentCore project name. Defaults to the one in ``output_dir/names.json``,
            else a new ``names.generate_project_name(task)``.
        framework: Source framework (deepeval, ragas, phoenix, strands).
        task: Short task identifier used to name a new project.
        handlers_dir: Alias for ``handler_dir``.

    Returns:
        Path to the generated migration.sh.
    """
    if handlers_dir is not None and handler_dir == "handlers":
        handler_dir = handlers_dir
    handler_dir = Path(handler_dir)
    # Both are interpolated into the script, and the handler loop below may not run.
    validate_region(region)
    validate_framework(framework)

    _VALID_LEVELS = {"TRACE", "SESSION", "TOOL_CALL"}

    if evaluator_names is None:
        manifest = handler_dir / "evaluators.json"
        if manifest.exists():
            entries = json.loads(manifest.read_text())
            evaluator_names = [(e["name"], e["level"], e["handler_file"]) for e in entries]
            logger.info("Auto-resolved %d evaluator(s) from %s", len(evaluator_names), manifest)
        else:
            raise ValueError(
                "evaluator_names not provided and handlers/evaluators.json not found. "
                "Run generate_handlers.py first, then either pass the manifest path "
                "or provide evaluator_names as [(name, level, handler_file), ...]."
            )

    # Catch a swapped tuple, where handler_file lands in the level slot.
    for name, level, handler_file in evaluator_names:
        if level.endswith(".py") or (level not in _VALID_LEVELS and "_handler" in level):
            raise ValueError(
                f"evaluator_names tuple order is WRONG for '{name}': "
                f"got level='{level}' (looks like a filename). "
                f"Correct order is (name, level, handler_file). "
                f"Easiest fix: read handlers/evaluators.json instead of "
                f"constructing tuples manually:\n"
                f"  entries = json.load(open('handlers/evaluators.json'))\n"
                f"  evaluator_names = [(e['name'], e['level'], e['handler_file']) for e in entries]"
            )
        # Both become shell arguments and file paths.
        validate_evaluator_name(name)
        validate_handler_file(handler_file)

    if project_name is None:
        # Reuse names.json so the client script resolves the same evaluator IDs.
        output_dir = Path(output_dir)
        names_path = output_dir / "names.json"
        if names_path.exists():
            project_name = json.loads(names_path.read_text())["project_name"]
        else:
            project_name = generate_project_name(task)
            output_dir.mkdir(parents=True, exist_ok=True)
            with names_path.open("w") as fh:
                json.dump({"project_name": project_name, "framework": framework}, fh)
    else:
        output_dir = Path(output_dir)
    validate_project_name(project_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    handlers_out = output_dir / "handlers"
    handlers_out.mkdir(exist_ok=True)
    for _, _, handler_file in evaluator_names:
        src = handler_dir / handler_file
        # Also refuses a symlink that points outside handler_dir.
        if src.exists() and src.resolve().parent != handler_dir.resolve():
            raise ValueError(f"handler file {handler_file!r} resolves outside {handler_dir}")
        if not src.exists():
            # Fail now rather than as a bare cp error partway through the deploy.
            raise ValueError(
                f"handler file {handler_file!r} not found in {handler_dir}. Run "
                "generate_handlers.py first, or check the manifest's 'handler_file'."
            )
        if _TODO_MARKER in src.read_text():
            # A skeleton deploys cleanly and then fails on every invocation.
            raise ValueError(
                f"{handler_file} still has a {_TODO_MARKER} block. Complete it from the "
                "source script (see the block's comment), delete the marker, then "
                "generate migration.sh again."
            )
        _assert_handler_region(src, region)
        dest = handlers_out / handler_file
        # handler_dir may already be output_dir/handlers, which copy2 rejects.
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
    # Beside migration.sh, which installs the CDK app from it (step 11).
    shutil.copy2(checked_cdk_lockfile(), output_dir / CDK_LOCKFILE.name)
    constraint = checked_constraint_file(framework)
    if constraint is not None:
        shutil.copy2(constraint, output_dir / "constraints.txt")
    if framework == "deepeval":
        (output_dir / "overrides.txt").write_text(DEEPEVAL_OVERRIDES)

    # Keeps uv from treating a parent pyproject.toml as the workspace root.
    workspace_pyproject = output_dir / "pyproject.toml"
    if not workspace_pyproject.exists():
        workspace_pyproject.write_text(
            '[project]\nname = "evaluator-deploy"\nversion = "0.1.0"\n'
            'requires-python = ">=3.10"\n\n'
            "[tool.uv.workspace]\nmembers = []\n"
        )

    add_evaluator_cmds = []
    copy_handler_cmds = []
    extra_deps_cmds = []

    for name, level, handler_file in evaluator_names:
        # No default: a SESSION evaluator deployed at TRACE has no spans to score.
        if level not in _VALID_LEVELS:
            raise ValueError(
                f"invalid level '{level}' for evaluator '{name}'. "
                f"Expected one of {sorted(_VALID_LEVELS)}. "
                "Refusing to default to TRACE: deploying a SESSION-scoped evaluator at "
                "TRACE produces evaluations with no spans to score. Check the "
                "(name, level, handler_file) tuple order and the manifest's 'level' field."
            )
        # Quote every interpolated value: GEval names contain brackets, a glob character.
        app_dir = shlex.quote(f"app/{name}")
        add_evaluator_cmds.append(
            # The guard lets a re-run skip scaffolded evaluators. 300s because multi-step
            # metrics make several LLM calls per sample and exceed the 120s default.
            f"[ -d {app_dir} ] || agentcore add evaluator --name {shlex.quote(name)} "
            f"--level {shlex.quote(level)} --type code-based --timeout 300 --json"
        )
        copy_handler_cmds.append(
            f'cp "$SCRIPT_DIR/handlers/"{shlex.quote(handler_file)} '
            f"{shlex.quote(f'app/{name}/lambda_function.py')}"
        )
        pyproject = shlex.quote(f"app/{name}/pyproject.toml")
        if framework == "ragas":
            # package_ragas_lambda.py writes the RAGAS pyproject.
            continue
        if framework != "deepeval":
            continue
        # Replace the scaffold's bedrock-agentcore floor with the exact pin: the floor can
        # resolve below 1.23.0, which lacks third_party/deepeval.
        from package_ragas_lambda import BEDROCK_AGENTCORE_PIN as sdk_spec

        # Matches _SDK_REQ_RE in verify_deps.py. `'\''` is a literal ' inside the quotes.
        extra_deps_cmds.append(
            "sed -E -i 's|bedrock-agentcore[[:space:]]*[><=!~][^\"'\\'']*|"
            + f"{sdk_spec}|' "
            + pyproject
        )
        # Exact pins. The grep matches a quoted requirement, not the bare name, because the
        # project is named after its metric.
        for dep in deepeval_injected_pins():
            dep_name = dep.split("==")[0]
            extra_deps_cmds.append(
                f"""grep -qE '"{dep_name}["=<>!~ ]' {pyproject} || """
                f"sed -i 's/dependencies = \\[/dependencies = [\\n  \"{dep}\",/' {pyproject}"
            )
        if "embed" in name or "relevancy" in name:
            embed_name = DEEPEVAL_EMBEDDING_PIN.split("==")[0]
            extra_deps_cmds.append(
                f"""grep -qE '"{embed_name}["=<>!~ ]' {pyproject} || """
                f"sed -i 's/dependencies = \\[/dependencies = [\\n  \"{DEEPEVAL_EMBEDDING_PIN}\",/' "
                f"{pyproject}"
            )

    # Match the CDK bundle platform and Lambda architecture to this host; a mismatch fails at
    # import (pydantic_core). The self-test uses the same CDK_PLATFORM_CANDIDATES.
    from package_ragas_lambda import CDK_PLATFORM_CANDIDATES

    _platforms = "[" + ", ".join(f"'{t}'" for t in CDK_PLATFORM_CANDIDATES) + "]"
    ragas_cdk_patch_step = """
# ===========================================================================
# 11b. Match CDK packaging platform + Lambda architecture to this host
# ===========================================================================
if [ "$(uname -m)" = "x86_64" ]; then
    # -print -quit, not `| head -1`: under pipefail, head closing the pipe early kills
    # find with SIGPIPE (exit 141) and takes the whole script down with no message.
    PYJS=$(find agentcore/cdk/node_modules/@aws/agentcore-cdk -path "*packaging*" -name "python.js" -print -quit 2>/dev/null)
    if [ -n "$PYJS" ]; then
        sed -i "s/PLATFORM_CANDIDATES = \\[[^]]*\\]/PLATFORM_CANDIDATES = __PLATFORMS__/" "$PYJS"
        echo "[OK] Patched PLATFORM_CANDIDATES in $PYJS"
    fi
    # Search ALL of dist/: the hardcoded ARM_64 is not confined to dist/lib/.
    for f in $(grep -rlE "ARM_64|Architecture\\.ARM|'arm64'|\\"arm64\\"" agentcore/cdk/node_modules/@aws/agentcore-cdk/dist/ 2>/dev/null); do
        sed -i -e 's/ARM_64/X86_64/g' -e "s/'arm64'/'x86_64'/g" -e 's/"arm64"/"x86_64"/g' "$f"
        echo "[OK] Patched Lambda architecture in $f"
    done
    # Assert the END STATE, not that a sed fired: patching one target while the other
    # matches nothing leaves the mismatch this step exists to prevent.
    if [ -z "$PYJS" ]; then
        echo "[ERROR] CDK python.js not found — CDK layout may have changed."
        echo "        Refusing to deploy: the bundle platform cannot be set."
        exit 1
    fi
    if ! grep -q "x86_64-manylinux" "$PYJS"; then
        echo "[ERROR] PLATFORM_CANDIDATES in $PYJS is still not x86_64."
        echo "        Refusing to deploy: arm64 wheels would be bundled."
        exit 1
    fi
    if grep -rqE "ARM_64|Architecture\\.ARM|'arm64'|\\"arm64\\"" agentcore/cdk/node_modules/@aws/agentcore-cdk/dist/ 2>/dev/null; then
        echo "[ERROR] arm64 still present in the CDK dist/ after patching."
        echo "        Refusing to deploy: pydantic_core ImportError would follow."
        exit 1
    fi
fi
""".replace("__PLATFORMS__", _platforms)

    # Absolute, because the generated script may run from any directory.
    tools_dir = Path(__file__).parent

    ragas_packaging_step = ""
    if framework == "ragas":
        evaluator_flags = " ".join(
            f"--evaluator {shlex.quote(name)}" for name, _, _ in evaluator_names
        )
        ragas_packaging_step = f"""
# ===========================================================================
# 10b. RAGAS Lambda packaging (PyPI pins + overrides + stubs + Lambda-faithful self-test)
# ===========================================================================
echo "[DEPLOY] Packaging RAGAS evaluator Lambdas against the pinned PyPI versions..."
python3 {shlex.quote(str(tools_dir / "package_ragas_lambda.py"))} --project-dir "$PROJECT_DIR" \\
    {evaluator_flags}
# The CDK's uv invocation must see the overrides file: it excludes boto3/botocore
# and ragas's unused heavy transitives, without which the bundle exceeds 250MB.
export UV_OVERRIDE="$PROJECT_DIR/overrides.txt"
"""

    iam_patch_cmds = []
    for name, _, _ in evaluator_names:
        judge_resources = json.dumps(
            judge_invoke_resources(region, account_id=_ACCOUNT_PLACEHOLDER), indent=8
        )
        policy_file = shlex.quote(f"app/{name}/execution-role-policy.json")
        iam_patch_cmds.append(f"""\
# Add Bedrock InvokeModel permission for {name}, scoped to the judge model only
cat > {policy_file} << 'POLICY'
{{
  "Version": "2012-10-17",
  "Statement": [
    {{
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": {judge_resources}
    }}
  ]
}}
POLICY
sed -i "s/{_ACCOUNT_PLACEHOLDER}/$AWS_ACCOUNT/g" {policy_file}
""")

    # Both variables reach the CDK's uv the way UV_OVERRIDE does: its install command is a
    # fixed argv, but uv honours the environment. Without UV_CONSTRAINT the pyproject alone
    # fails hash mode ("all requirements must be pinned upfront with ==").
    deepeval_override_step = ""
    if framework == "deepeval":
        deepeval_override_step = """
# Drops strands-agents-tools (unused by the evaluators) from the bundle, as the RAGAS path
# does; constraints.txt is resolved with the same overrides.
if [ ! -f "$SCRIPT_DIR/overrides.txt" ]; then
    echo "[ERROR] $SCRIPT_DIR/overrides.txt is missing; regenerate migration.sh."
    exit 1
fi
export UV_OVERRIDE="$SCRIPT_DIR/overrides.txt"
"""
    hash_enforcement_step = ""
    if checked_constraint_file(framework) is not None:
        hash_enforcement_step = """
# Verify every wheel's checksum before it enters the bundle, transitives included. Fails the
# deploy if constraints.txt and the pins disagree; regenerate it as its header describes.
# Checked here because agentcore hides uv's own error behind "CDK synth failed".
if [ ! -f "$SCRIPT_DIR/constraints.txt" ]; then
    echo "[ERROR] $SCRIPT_DIR/constraints.txt is missing; regenerate migration.sh."
    exit 1
fi
export UV_CONSTRAINT="$SCRIPT_DIR/constraints.txt"
export UV_REQUIRE_HASHES=1
"""

    # Runs inside the script, just before the deploy, so what deploys is what was verified.
    verify_deps_step = ""
    if framework in ("deepeval", "ragas"):
        verify_deps_step = f"""
# ===========================================================================
# 12. Verify Lambda dependencies (auto-fixes what it can; stops before deploy)
# ===========================================================================
echo "[DEPLOY] Verifying Lambda dependencies..."
python3 {shlex.quote(str(tools_dir / "verify_deps.py"))} --deploy-dir "$PROJECT_DIR" \\
    --framework {shlex.quote(framework)}
"""

    # The deploy creates each evaluator's log group: the scaffold's cdk.json sets
    # @aws-cdk/aws-lambda:useCdkManagedLogGroup, so the stack declares /aws/lambda/<function>
    # with two-year retention and no CMK, and it will hold customer traces and prompts. This
    # step therefore runs after the deploy, before anything invokes the Lambdas. Creating the
    # groups first fails the deploy: CloudFormation cannot create a log group that exists. The
    # names must be the CDK's function names exactly: a group under any other name protects
    # nothing.
    log_groups = [
        f"/aws/lambda/{lambda_function_name(project_name, name)}" for name, _, _ in evaluator_names
    ]
    log_group_step = f"""
# ===========================================================================
# 14. Evaluator log groups (retention + encryption before the first invoke)
# ===========================================================================
# After the deploy, never before it: the stack creates these groups itself, and
# CloudFormation fails the deploy with AlreadyExists if one is already there.
echo ""
echo "[LOGS] Preparing CloudWatch Logs groups..."
python3 - <<'LOGGROUPS_EOF'
import os

import boto3
from botocore.exceptions import ClientError

REGION = "{region}"
LOG_GROUPS = {log_groups!r}
KEY = os.environ.get("EVAL_MIGRATION_LOGS_KMS_KEY_ARN", "")


def key_policy_hint(lg):
    print("[ERROR] KMS encryption failed for " + lg + ". Confirm the key policy grants")
    print("        logs." + REGION + ".amazonaws.com kms:Encrypt, kms:Decrypt and")
    print("        kms:GenerateDataKey*.")


logs = boto3.client("logs", region_name=REGION)
for lg in LOG_GROUPS:
    kwargs = dict(logGroupName=lg)
    if KEY:
        kwargs["kmsKeyId"] = KEY
    try:
        logs.create_log_group(**kwargs)
        print("[LOGS] created " + lg + (" (CMK-encrypted)" if KEY else ""))
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceAlreadyExistsException":
            # The usual case: the stack created it without a CMK. Nothing has invoked the
            # Lambda yet, so associating the key now covers every log it will write.
            if KEY:
                try:
                    logs.associate_kms_key(logGroupName=lg, kmsKeyId=KEY)
                except ClientError:
                    key_policy_hint(lg)
                    raise
                print("[LOGS] " + lg + " exists; CMK associated")
            else:
                print("[LOGS] " + lg + " exists")
        elif code in ("AccessDeniedException", "AccessDenied"):
            # The deploy already succeeded, so do not fail it over this.
            print("[WARN] not permitted to manage " + lg + " (needs logs:CreateLogGroup).")
            print("       It keeps the retention and encryption the CDK or Lambda gave it.")
            continue
        elif KEY:
            key_policy_hint(lg)
            raise
        else:
            raise
    try:
        logs.put_retention_policy(logGroupName=lg, retentionInDays=30)
    except ClientError:
        print("[WARN] could not set retention on " + lg + " (needs logs:PutRetentionPolicy)")
if LOG_GROUPS and not KEY:
    print("")
    print("[WARN] EVAL_MIGRATION_LOGS_KMS_KEY_ARN is not set, so these groups use the")
    print("       AWS-owned key. Evaluation logs hold customer traces, prompts and model")
    print("       responses in full: set EVAL_MIGRATION_LOGS_KMS_KEY_ARN to a CMK and")
    print("       re-run to satisfy the log-encryption control in SKILL.md.")
LOGGROUPS_EOF
"""

    # Built outside the f-string: a backslash in an f-string expression needs Python 3.12+.
    cdk_pins_json = json.dumps(CDK_NPM_PINS)
    cdk_dropped_json = json.dumps(list(CDK_NPM_DROPPED))
    deployed_summary_cmds = [
        "echo " + shlex.quote(f"  - {name} ({level})") for name, level, _ in evaluator_names
    ]
    evaluator_id_cmds = [
        "echo " + shlex.quote(f'    evaluatorId="{name}"') for name, _, _ in evaluator_names
    ]

    script_content = f"""\
#!/bin/bash
# pipefail is required: install steps pipe through `tail -1`, and without it a failed
# install exits 0 through the pipe so `set -e` never fires. Pipelines expected to fail
# carry `|| true`.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
echo "=== AgentCore Evaluator Deployment ==="
echo "Region: {region}"
echo ""

# ===========================================================================
# 1. Node 20+ check
# ===========================================================================
NODE_MIN_VERSION=20
CURRENT_NODE_VERSION=$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1 || true)

if [ -z "$CURRENT_NODE_VERSION" ] || [ "$CURRENT_NODE_VERSION" -lt "$NODE_MIN_VERSION" ]; then
    echo "[PREFLIGHT] Node.js 20+ required. Current: $(node --version 2>/dev/null || echo 'not found')"

    # Try mise
    MISE_NODE=$(ls -d "$HOME/.local/share/mise/installs/node"/{{24,23,22,21,20}}* 2>/dev/null | sort -V | tail -1 || true)
    if [ -n "$MISE_NODE" ] && [ -f "$MISE_NODE/bin/node" ]; then
        echo "[PREFLIGHT] Found Node 20+ at $MISE_NODE/bin, activating..."
        export PATH="$MISE_NODE/bin:$PATH"
    else
        # Try nvm
        NVM_NODE=$(ls -d "$HOME/.nvm/versions/node"/v{{24,23,22,21,20}}* 2>/dev/null | sort -V | tail -1 || true)
        if [ -n "$NVM_NODE" ] && [ -f "$NVM_NODE/bin/node" ]; then
            echo "[PREFLIGHT] Found Node 20+ at $NVM_NODE/bin, activating..."
            export PATH="$NVM_NODE/bin:$PATH"
        else
            echo "[ERROR] Node 20+ not found. Install with: mise install node@20.19.2"
            exit 1
        fi
    fi
fi
echo "[OK] Node $(node --version)"

# ===========================================================================
# 2. TypeScript check (pin to 5.x — TS 6+ breaks agentcore CDK tsconfig)
# ===========================================================================
# Compare the FULL version, not the major: a major-only check leaves any pre-installed
# 5.x in place and the pin never applies.
TSC_FULL=$(tsc --version 2>/dev/null | grep -oP '[0-9]+\\.[0-9]+\\.[0-9]+' | head -1 || true)
if [ "$TSC_FULL" != "5.9.3" ]; then
    echo "[PREFLIGHT] Installing TypeScript 5.x (TS 6+ incompatible with agentcore CDK)..."
    npm install -g --no-audit --no-fund typescript@5.9.3 2>&1 | tail -1
fi
echo "[OK] TypeScript $(tsc --version 2>/dev/null || echo 'installed')"

# ===========================================================================
# 3. uv check (required for Python Lambda packaging)
# ===========================================================================
# Version-checked, not presence-checked: `command -v` would accept any uv already
# installed and skip the pin.
UV_FULL=$(uv --version 2>/dev/null | grep -oP '[0-9]+\\.[0-9]+\\.[0-9]+' | head -1 || true)
if [ "$UV_FULL" != "0.12.10" ]; then
    echo "[PREFLIGHT] Installing uv (required for Lambda packaging)..."
    pip install 'uv==0.12.10' 2>&1 | tail -1
fi
echo "[OK] uv $(uv --version 2>/dev/null | head -1)"

# ===========================================================================
# 4. AWS credentials check
# ===========================================================================
# boto3, not the aws CLI: boto3 is already required by the deploy, the CLI is a
# separate install and is not always present.
AWS_ACCOUNT=$(python3 -c "import os, boto3; print(boto3.client('sts', region_name=os.environ.get('AWS_REGION', 'us-east-1')).get_caller_identity()['Account'])" 2>/dev/null || true)
if [ -z "$AWS_ACCOUNT" ]; then
    echo "[ERROR] AWS credentials not configured or expired."
    echo "  Refresh the credentials in the default AWS credential chain (e.g. aws sso login)."
    echo "  Needs bedrock-agentcore, lambda, iam, cloudformation, s3, logs; not Admin."
    exit 1
fi
echo "[OK] AWS Account: $AWS_ACCOUNT"

# ===========================================================================
# 5. AgentCore CLI check
# ===========================================================================
# Version-checked, not presence-checked: a presence check would run whatever CLI is on
# the box, defeating the pin.
AC_FULL=$(agentcore --version 2>/dev/null | grep -oP '[0-9]+\\.[0-9]+\\.[0-9]+' | head -1 || true)
if [ "$AC_FULL" != "0.28.1" ]; then
    echo "[PREFLIGHT] Installing AgentCore CLI..."
    # Pinned to the CLI version this skill is validated against.
    npm install -g --no-audit --no-fund @aws/agentcore@0.28.1 2>&1 | tail -1
fi
echo "[OK] agentcore $(agentcore --version)"

# ===========================================================================
# 6. Create project (in isolated directory to avoid uv workspace conflicts)
# ===========================================================================
DEPLOY_DIR="$SCRIPT_DIR/deploy_workspace"
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

# Workspace isolation: prevent uv from walking up to parent pyproject.toml
if [ ! -f "pyproject.toml" ]; then
    cat > pyproject.toml << 'PYPROJECT'
[project]
name = "evaluator-deploy"
version = "0.1.0"
requires-python = ">=3.10"

[tool.uv.workspace]
members = []
PYPROJECT
fi

# agentcore create puts project in a subdirectory named after --project-name
PROJECT_NAME={shlex.quote(project_name)}
PROJECT_DIR="$DEPLOY_DIR/$PROJECT_NAME"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "[SETUP] Creating AgentCore project..."
    agentcore create --project-name "$PROJECT_NAME" --no-agent --skip-git --skip-install --output-dir "$DEPLOY_DIR" --json
    echo "[OK] Project created at $PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# ===========================================================================
# 7. Configure AWS target
# ===========================================================================
AWS_TARGETS_FILE="agentcore/aws-targets.json"
if ! grep -q "$AWS_ACCOUNT" "$AWS_TARGETS_FILE" 2>/dev/null; then
    echo "[SETUP] Configuring deployment target: {region}:$AWS_ACCOUNT"
    cat > "$AWS_TARGETS_FILE" << TARGETS
[
  {{
    "name": "default",
    "account": "$AWS_ACCOUNT",
    "region": "{region}"
  }}
]
TARGETS
fi

# ===========================================================================
# 8. Add evaluators
# ===========================================================================
echo ""
echo "[DEPLOY] Adding evaluators..."
{chr(10).join(add_evaluator_cmds)}

# ===========================================================================
# 9. Copy handler code
# ===========================================================================
echo "[DEPLOY] Installing handler code..."
{chr(10).join(copy_handler_cmds)}

# ===========================================================================
# 10. Add extra dependencies and IAM permissions
# ===========================================================================
{chr(10).join(extra_deps_cmds)}
{chr(10).join(iam_patch_cmds)}
{ragas_packaging_step}{deepeval_override_step}{hash_enforcement_step}
# ===========================================================================
# 11. Install CDK dependencies at exact versions (required for deploy; crash-safe)
# ===========================================================================
# The scaffold declares `~` ranges and ships no lockfile, so this step pins package.json
# and installs with `npm ci` from the skill's lockfile, copied beside this script. On
# deploy the CLI rewrites its managed dependencies back to the ranges and runs its own
# `npm install`. Turn that off for this deploy only, through a private copy of the CLI
# config, so the pins stick.
ORIG_AGENTCORE_CONFIG="${{AGENTCORE_CONFIG_DIR:-$HOME/.agentcore}}/config.json"
export AGENTCORE_CONFIG_DIR="$DEPLOY_DIR/.agentcore-config"
python3 - "$ORIG_AGENTCORE_CONFIG" "$AGENTCORE_CONFIG_DIR" <<'AGENTCORE_CONFIG_EOF'
import json, pathlib, sys
source, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
config = json.loads(source.read_text()) if source.is_file() else {{}}
config["disableDependencyManagement"] = True
target.mkdir(parents=True, exist_ok=True)
(target / "config.json").write_text(json.dumps(config, indent=2))
AGENTCORE_CONFIG_EOF
# The marker is written only after npm exits 0, because an interrupted install leaves
# debris that `npm install` cannot reliably repair (ENOTEMPTY). Unmarked means wipe and
# reinstall; marked means skip.
if [ ! -f agentcore/cdk/node_modules/.cdk_npm_pinned_complete ]; then
    echo "[DEPLOY] Installing CDK dependencies (exact pins)..."
    python3 - agentcore/cdk/package.json <<'CDK_PINS_EOF'
import json, sys
PINS = {cdk_pins_json}
DROPPED = {cdk_dropped_json}
path = sys.argv[1]
with open(path) as fh:
    pkg = json.load(fh)
declared = {{name for section in PINS for name in pkg.get(section, {{}})}}
unexpected = sorted(declared - {{name for pins in PINS.values() for name in pins}} - set(DROPPED))
if unexpected:
    sys.exit("[ERROR] the CDK scaffold declares packages this skill has not pinned: "
             + ", ".join(unexpected) + ". Refusing to install unreviewed dependencies.")
for section, pins in PINS.items():
    pkg[section] = dict(pins)
with open(path, "w") as fh:
    json.dump(pkg, fh, indent=2)
    fh.write("\\n")
print("[OK] Pinned " + ", ".join(f"{{n}}@{{v}}" for pins in PINS.values() for n, v in pins.items()))
CDK_PINS_EOF
    rm -rf agentcore/cdk/node_modules
    cp "$SCRIPT_DIR/{CDK_LOCKFILE.name}" agentcore/cdk/package-lock.json
    cd agentcore/cdk && npm ci --no-audit --no-fund 2>&1 | tail -1 && cd ../..
    touch agentcore/cdk/node_modules/.cdk_npm_pinned_complete
else
    echo "[OK] CDK dependencies already installed"
fi
{ragas_cdk_patch_step}{verify_deps_step}
# ===========================================================================
# 12b. Refuse handlers that still need code from the source script
# ===========================================================================
# The marker is split in two so that grepping this file for it finds nothing.
UNFINISHED=$(grep -l "TODO(""EVAL-MIGRATION)" app/*/lambda_function.py 2>/dev/null || true)
if [ -n "$UNFINISHED" ]; then
    echo "[ERROR] Unfinished handlers: complete the TODO block generate_handlers.py left"
    echo "        in each, copying from the source script, then RE-RUN this script:"
    echo "$UNFINISHED"
    exit 1
fi

# ===========================================================================
# 13. Deploy (bounded: a healthy CDK deploy takes 2-4 min; >600s means stuck)
# ===========================================================================
# Scope the timeout to the deploy alone, never the whole script: killing it mid-`npm
# install` corrupts node_modules.
echo ""
echo "[DEPLOY] Deploying to AWS ({region})..."
timeout 600 agentcore deploy --target default --yes --verbose || {{
    RC=$?
    if [ "$RC" = "124" ]; then
        echo "[ERROR] agentcore deploy exceeded 600s — usually a stuck CloudFormation"
        echo "        stack (e.g. ROLLBACK_COMPLETE). Resolve the stack, then RE-RUN"
        echo "        this script: completed steps are skipped."
    else
        echo "[ERROR] agentcore deploy failed (exit $RC). Fix the cause, then RE-RUN"
        echo "        this script: completed steps are skipped."
    fi
    # The CDK sets DeletionPolicy: Retain on the log groups, so a failed stack leaves them.
    echo "        A failed stack leaves its log groups behind: after deleting the stack,"
    echo "        delete /aws/lambda/$PROJECT_NAME-eval-* too, or the re-run fails with"
    echo "        AlreadyExists."
    exit 1
}}
{log_group_step}
echo ""
echo "=== Deployment complete ==="
echo "Evaluators deployed:"
{chr(10).join(deployed_summary_cmds)}
echo ""
echo "Use these evaluator names in EvaluationClient.evaluate():"
{chr(10).join(evaluator_id_cmds)}
"""

    script_path = output_dir / "migration.sh"
    script_path.write_text(script_content)
    script_path.chmod(0o755)

    logger.info("Generated migration.sh at %s", script_path)
    return script_path
