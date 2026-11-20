#!/usr/bin/env python3
"""Verify and fix Lambda app dependencies before deploy.

DeepEval: adds missing requirements to each app's pyproject.toml and pins deepeval and
bedrock-agentcore exactly. RAGAS: checks that app/ has a handler and overrides.txt exists.

Usage:
    python3 verify_deps.py --deploy-dir deploy/deploy_workspace/<Project> --framework deepeval

Exit codes:
    0 = all deps verified (possibly after auto-fix)
    1 = unfixable issue found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Put scripts/ on sys.path so sibling modules resolve by static import, whether the package is
# installed or copied standalone. Dynamic import is disallowed here for security reasons.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

#: Any bedrock-agentcore requirement, exact or not, as written in a pyproject.
_SDK_REQ_RE = re.compile(r"bedrock-agentcore\s*[><=!~][^\"']*")

#: Any deepeval requirement, exact or not, as written in a pyproject.
_DEEPEVAL_REQ_RE = re.compile(r"deepeval\s*[><=!~][^\"']*")

#: A bare, unversioned deepeval requirement, which _DEEPEVAL_REQ_RE cannot rewrite (no operator).
_BARE_DEEPEVAL_RE = re.compile(r"([\"'])deepeval\1")

#: Captures an ``==`` pin's version; the lookbehind rejects matches inside longer names.
_PIN_RE_TEMPLATE = r"(?<![\w.-]){name}\s*==\s*([^\"'\s,\]]+)"

#: Quoted: app dirs are named after their metric, so a bare-name search matches the project name.
_REQ_RE_TEMPLATE = r"[\"']{name}\s*(?:[><=!~]|[\"'])"


def _has_requirement(content: str, name: str) -> bool:
    """True if ``content`` declares a requirement on ``name`` (any version)."""
    return re.search(_REQ_RE_TEMPLATE.format(name=re.escape(name)), content) is not None


def _pinned_exactly(content: str, spec: str) -> bool:
    """True if ``content`` pins ``spec``'s package to exactly ``spec``'s version.

    Parses the version, because a substring test would accept ``==1.23.0.post1`` for ``==1.23.0``.
    """
    name, _, wanted = spec.partition("==")
    match = re.search(_PIN_RE_TEMPLATE.format(name=re.escape(name)), content)
    return match is not None and match.group(1) == wanted


#: Keep in sync with the deepeval pin in deployer.py (generate_migration_sh), so the Lambda
#: scores with the same metric code as the original evaluator.
_DEEPEVAL_PIN = "deepeval==4.2.3"


def _sdk_spec() -> str:
    """Return the exact bedrock-agentcore pin defined in package_ragas_lambda.py.

    Raises SystemExit rather than returning a default, so a broken install cannot skip the check.
    """
    try:
        from package_ragas_lambda import BEDROCK_AGENTCORE_PIN
    except ImportError as exc:
        raise SystemExit(
            f"[verify] ERROR: cannot import package_ragas_lambda to read the SDK pin "
            f"({exc}). It ships beside this script; restore it rather than deploying "
            f"without the pin check."
        ) from None
    sdk_spec = str(BEDROCK_AGENTCORE_PIN or "")
    if not sdk_spec:
        raise SystemExit(
            "[verify] ERROR: package_ragas_lambda defines no BEDROCK_AGENTCORE_PIN. The "
            "DeepEval handler "
            "imports its adapter from that pinned wheel, so there is nothing to verify "
            "against and the check cannot be skipped silently."
        )
    return sdk_spec


def contained_app_dirs(app_dir: Path) -> list[Path] | None:
    apps_root = app_dir.resolve()
    contained = []
    for d in sorted(app_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.resolve().parent != apps_root:
            print(f"ERROR: app dir {d} resolves outside {apps_root}")
            return None
        contained.append(d)
    return contained


def contained_pyproject(app_dir: Path) -> Path | None:
    pyproject = app_dir / "pyproject.toml"
    if pyproject.exists() and pyproject.resolve().parent != app_dir.resolve():
        print(f"ERROR: {pyproject} resolves outside {app_dir}")
        return None
    return pyproject


def verify_deepeval(deploy_dir: Path) -> bool:
    """Check and fix DeepEval Lambda app directories."""
    app_dir = deploy_dir / "app"
    if not app_dir.exists():
        print(f"ERROR: {app_dir} does not exist")
        return False

    app_dirs = contained_app_dirs(app_dir)
    if app_dirs is None:
        return False
    if not app_dirs:
        print(f"ERROR: no app subdirectories in {app_dir}")
        return False

    # Resolved up front so a broken install fails before any app dir is changed or reported.
    sdk_spec = _sdk_spec()
    from package_ragas_lambda import STRANDS_EVALS_PIN

    all_ok = True
    for ad in app_dirs:
        pyproject = contained_pyproject(ad)
        if pyproject is None:
            all_ok = False
            continue
        if not pyproject.exists():
            print(f"ERROR: {pyproject} missing")
            all_ok = False
            continue

        content = pyproject.read_text()
        fixed = False

        if not _has_requirement(content, "deepeval"):
            content = content.replace(
                "dependencies = [",
                f'dependencies = [\n    "{_DEEPEVAL_PIN}",',
            )
            fixed = True
            print(f"  FIXED: added deepeval to {ad.name}/pyproject.toml")

        if not _pinned_exactly(content, _DEEPEVAL_PIN):
            patched = _DEEPEVAL_REQ_RE.sub(_DEEPEVAL_PIN, content)
            if patched == content:
                # A bare "deepeval" has no operator to rewrite. Replace it in place: uv resolves
                # duplicates last-wins, so a pin added beside it could lose to the bare one.
                patched = _BARE_DEEPEVAL_RE.sub(f'"{_DEEPEVAL_PIN}"', content, count=1)
            if patched != content:
                content = patched
                fixed = True
                print(f"  FIXED: pinned {_DEEPEVAL_PIN} in {ad.name}/pyproject.toml")

        if not _has_requirement(content, "strands-agents-evals"):
            content = content.replace(
                "dependencies = [",
                f'dependencies = [\n    "{STRANDS_EVALS_PIN}",',
            )
            fixed = True
            print(f"  FIXED: added strands-agents-evals to {ad.name}/pyproject.toml")

        if fixed:
            pyproject.write_text(content)

        # The adapter ships in bedrock-agentcore 1.23.0+. The scaffold's >= floor can resolve
        # lower, which fails at invoke time, after deploy has reported success.
        if not _pinned_exactly(content, sdk_spec):
            patched = _SDK_REQ_RE.sub(sdk_spec, content)
            if patched != content:
                content = patched
                pyproject.write_text(content)
                print(f"  FIXED: pinned {sdk_spec} in {ad.name}/pyproject.toml")
            else:
                # Nothing to rewrite: add the pin and warn, since the scaffold normally writes one.
                content = content.replace(
                    "dependencies = [", f'dependencies = [\n    "{sdk_spec}",', 1
                )
                pyproject.write_text(content)
                print(
                    f"  FIXED: {ad.name}/pyproject.toml had no bedrock-agentcore "
                    f"requirement — added {sdk_spec}. Check the scaffold output; it is "
                    f"expected to write one."
                )

        # Re-check from disk: the additions above are literal replaces on "dependencies = [",
        # which silently no-op on any other spacing.
        final_content = pyproject.read_text()
        if not _has_requirement(final_content, "deepeval"):
            print(f"  ERROR: deepeval still missing in {ad.name}/pyproject.toml")
            all_ok = False
        if not _pinned_exactly(final_content, _DEEPEVAL_PIN):
            print(f"  ERROR: deepeval not pinned to {_DEEPEVAL_PIN} in {ad.name}/pyproject.toml")
            all_ok = False
        if not _has_requirement(final_content, "strands-agents-evals"):
            print(f"  ERROR: strands-agents-evals still missing in {ad.name}/pyproject.toml")
            all_ok = False
        if not _pinned_exactly(final_content, sdk_spec):
            print(f"  ERROR: {sdk_spec} not pinned in {ad.name}/pyproject.toml")
            all_ok = False

    return all_ok


def verify_ragas(deploy_dir: Path) -> bool:
    """Check that app/ holds at least one handler and that overrides.txt exists."""
    all_ok = True

    app_dir = deploy_dir / "app"
    if not app_dir.exists():
        print(f"ERROR: {app_dir} does not exist")
        return False

    app_dirs = contained_app_dirs(app_dir)
    if app_dirs is None:
        return False

    handlers = sorted(h for h in (ad / "lambda_function.py" for ad in app_dirs) if h.exists())
    if not handlers:
        print(
            f"ERROR: no app/*/lambda_function.py found under {app_dir} — there is "
            "nothing to verify. Check that --deploy-dir points at the project dir "
            "containing app/, and that the handler copy step ran."
        )
        return False
    print(f"  OK: {len(handlers)} handler(s) present")

    overrides = deploy_dir / "overrides.txt"
    if not overrides.exists():
        overrides = deploy_dir.parent / "overrides.txt"
    if overrides.exists():
        print(f"  OK: overrides.txt present ({overrides})")
    else:
        print(
            "ERROR: overrides.txt not found — the excluded transitives would install "
            "and the bundle would exceed Lambda's 250MB limit. Run "
            "scripts/package_ragas_lambda.py first."
        )
        all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Verify Lambda deploy dependencies")
    parser.add_argument("--deploy-dir", required=True, help="Path to deploy workspace project dir")
    parser.add_argument("--framework", required=True, choices=["deepeval", "ragas"])
    args = parser.parse_args()

    deploy_dir = Path(args.deploy_dir).resolve()

    if not deploy_dir.is_dir():
        print(f"ERROR: deploy dir {deploy_dir} does not exist")
        sys.exit(1)

    print(f"Verifying {args.framework} dependencies in {deploy_dir}...")

    if args.framework == "deepeval":
        ok = verify_deepeval(deploy_dir)
    else:
        ok = verify_ragas(deploy_dir)

    if ok:
        print("DEPS VERIFIED: all checks passed")
        sys.exit(0)
    else:
        print("DEPS INCOMPLETE: see errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
