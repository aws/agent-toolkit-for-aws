#!/usr/bin/env python3
"""Build a deterministic, local-only gamma skillset ZIP.

Use the repository's Python 3.12 environment; a system Python may be older.

Usage:
  python3 scripts/build-gamma-skillset.py --skill gcp-to-aws --output /tmp/gcp.zip
  python3 scripts/build-gamma-skillset.py --verify /tmp/gcp.zip

This only packages source files. It never publishes, authenticates, runs skill
scripts, or sends telemetry. The ZIP is an integrity-checked candidate for
testing, not a claim of platform compatibility or end-to-end migration success.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_SKILLS = ("gcp-to-aws", "heroku-to-aws")
# This is intentionally explicit: mentioned migration alternatives are not
# executable dependencies. Both migrations require the policy gate and offers.
DEPENDENCIES = {
    "gcp-to-aws": ("tf-best-practices", "contextual-offers-for-startups"),
    "heroku-to-aws": ("tf-best-practices", "contextual-offers-for-startups"),
    "contextual-offers-for-startups": ("knowledge-base-for-startups",),
    "knowledge-base-for-startups": (),
    "tf-best-practices": (),
}
# The contextual-offers entrypoint lists its callers to explain when it applies;
# these links do not invoke those callers or require their code.
REFERENCE_ONLY_LINKS = {
    "contextual-offers-for-startups": {
        "architect-for-startups", "start-building-for-startups", "agent-advisor",
        "gcp-to-aws", "heroku-to-aws", "llm-to-bedrock",
    },
}
REQUIRED_FILES = {
    "tf-best-practices": (
        "scripts/validate-terraform-policy.py",
        "scripts/validate-migration-artifacts.py",
        "scripts/rds_windows.py",
        "references/terraform-validation.md",
    ),
    "contextual-offers-for-startups": (),
    "knowledge-base-for-startups": ("references/offers.md",),
    "gcp-to-aws": (
        "references/shared/validate-migration-report.md",
        "references/phases/generate/generate.md",
    ),
    "heroku-to-aws": (
        "scripts/validate-heroku-migration-report.py",
        "scripts/emit-plan-json.py",
        "references/vendored/dsl/INTERPRETER.md",
    ),
}
GCP_HELPERS = (
    "validate-migration-report.py",
    "emit-plan-json.py",
    "validate-startup-program-artifacts.py",
)
ROOT_HELPER_REFERENCE = re.compile(
    r"(?<![\w./-])(?:plugins/aws-startup-advisor/)?scripts/([A-Za-z0-9_-]+\.py)"
)
WORKERS = ("generic-phase-worker-rw.md", "generic-phase-worker-rwx.md")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MANIFEST_NAME = "package-manifest.json"
IGNORED_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".git"}


class PackageError(ValueError):
    """The source or archive cannot be safely packaged."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def manifest_path(skill: str) -> str:
    return f"skills/{skill}/references/gamma/{MANIFEST_NAME}"


def dependency_closure(skill: str) -> list[str]:
    if skill not in SUPPORTED_SKILLS:
        raise PackageError(f"unsupported primary skill: {skill}")
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name not in DEPENDENCIES:
            raise PackageError(f"undeclared dependency: {name}")
        visited.add(name)
        for dependency in DEPENDENCIES[name]:
            visit(dependency)

    visit(skill)
    return sorted(visited)


def safe_source_file(source: Path, relative: str) -> Path:
    path = source / relative
    for part in (path, *path.parents):
        if part == source.parent:
            break
        if part.is_symlink():
            raise PackageError(f"source symlink is not allowed: {relative}")
    if not path.is_file():
        raise PackageError(f"missing required source file: {relative}")
    if not path.resolve().is_relative_to(source):
        raise PackageError(f"source escapes input tree: {relative}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise PackageError(f"source is not a regular file: {relative}")
    return path


def source_tree(source: Path, relative: str):
    root = source / relative
    if root.is_symlink() or not root.is_dir():
        raise PackageError(f"missing or unsafe dependency directory: {relative}")
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            if (Path(directory) / name).is_symlink():
                raise PackageError(f"source symlink is not allowed: {Path(directory) / name}")
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_NAMES)
        for name in sorted(filenames):
            if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo")):
                continue
            yield safe_source_file(source, (Path(directory) / name).relative_to(source).as_posix())


def validate_source_bytes(relative: str, data: bytes) -> None:
    """Catch broken inputs without importing or running any packaged module."""
    try:
        if relative.endswith(".json"):
            json.loads(data.decode("utf-8"))
        elif relative.endswith(".py"):
            ast.parse(data.decode("utf-8"), filename=relative)
    except (UnicodeError, ValueError, SyntaxError) as error:
        raise PackageError(f"corrupt source file {relative}: {error}") from error


def source_revision(source: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(source), *args], text=True, stderr=subprocess.DEVNULL
        ).strip()

    try:
        commit = git("rev-parse", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=normal", "--", "."))
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "working_tree_dirty": None, "note": "not a Git checkout"}
    return {"commit": commit, "working_tree_dirty": dirty}


def validate_portable_references(payload: dict[str, bytes], skills: list[str]) -> None:
    """Fail on new external dependencies until the explicit package map is updated."""
    for name, data in payload.items():
        if not name.endswith(".md") or "/references/gamma/" in name:
            continue
        text = data.decode("utf-8")
        if "$PLUGIN_ROOT/" in text:
            raise PackageError(f"unmapped plugin-root dependency in {name}")
        if name.startswith("skills/gcp-to-aws/"):
            missing = ROOT_HELPER_REFERENCE.search(text)
            if missing:
                raise PackageError(
                    f"unmapped root helper {missing.group(1)} in {name}"
                )
        if name.endswith("/SKILL.md"):
            reference_only = REFERENCE_ONLY_LINKS.get(name.split("/")[1], set())
            for target in re.findall(r"\.\./([a-z][a-z0-9-]+)/", text):
                if target not in skills and target not in reference_only:
                    raise PackageError(f"undeclared sibling dependency {target} in {name}")
        for target in re.findall(r"<SKILL_BASE>/\.\./([a-z][a-z0-9-]+)/", text):
            if target not in skills:
                raise PackageError(f"undeclared sibling dependency {target} in {name}")


def adapt_markdown(relative: str, data: bytes, skill: str) -> tuple[bytes, list[str]]:
    """Only portability substitutions; source files themselves remain untouched."""
    if not relative.endswith(".md") or "/references/gamma/" in relative:
        return data, []
    text = data.decode("utf-8")
    reasons = []
    replacements = {
        "$PLUGIN_ROOT/skills/tf-best-practices/": (
            "<SKILL_BASE>/" if skill == "tf-best-practices"
            else "<SKILL_BASE>/../tf-best-practices/"
        ),
    }
    if skill in SUPPORTED_SKILLS:
        replacements["$PLUGIN_ROOT/.claude-plugin/plugin.json"] = (
            "<SKILL_BASE>/references/gamma/plugin.json"
        )
    if skill == "gcp-to-aws":
        for helper in GCP_HELPERS:
            replacements[f"$PLUGIN_ROOT/scripts/{helper}"] = f"<SKILL_BASE>/scripts/{helper}"
        if relative == "skills/gcp-to-aws/SKILL.md":
            heading = "# GCP-to-AWS Migration Skill\n"
            if heading not in text:
                raise PackageError("GCP entry heading changed; review package path adaptation")
            text = text.replace(
                heading,
                heading + "\nFor this gamma package, `<SKILL_BASE>` is the directory containing "
                "this SKILL.md, as reported by the harness. Resolve packaged helper and "
                "dependency paths relative to that directory.\n",
                1,
            )
            reasons.append("define portable skill base for relocated helpers")
        if relative.endswith("/references/phases/feedback/feedback.md"):
            replacements.update({
                "`.claude-plugin/plugin.json`": "`<SKILL_BASE>/references/gamma/plugin.json`",
                "`.cursor-plugin/plugin.json`": "`<SKILL_BASE>/references/gamma/plugin.json`",
                "(relative to the plugin install root)": "(the source manifest copied into this package)",
            })
    if relative == "skills/heroku-to-aws/references/phases/feedback/feedback-collect.md":
        replacements["nearest `plugin.json`"] = "`<SKILL_BASE>/references/gamma/plugin.json`"
    for original, replacement in replacements.items():
        if original in text:
            text = text.replace(original, replacement)
            reasons.append(f"path: {original} -> {replacement}")
    if skill == "gcp-to-aws":
        # Older references use bare paths (some are executable inline commands),
        # so adapting only $PLUGIN_ROOT forms misses real completion gates.
        for helper in GCP_HELPERS:
            portable = f"<SKILL_BASE>/scripts/{helper}"
            for prefix in ("plugins/aws-startup-advisor/", ""):
                old_path = f"{prefix}scripts/{helper}"
                for quote in ('"', "'"):
                    original = f"{quote}{old_path}{quote}"
                    if original in text:
                        text = text.replace(original, f"{quote}{portable}{quote}")
                        reasons.append(f"path: {old_path} -> {portable}")
                pattern = re.compile(rf"(?<![\w./-]){re.escape(old_path)}(?![\w.-])")
                text, count = pattern.subn(f'"{portable}"', text)
                if count:
                    reasons.append(f"path: {old_path} -> {portable}")
            # A path used as the first token of a command must invoke Python;
            # source helpers are intentionally packaged as ordinary files.
            pattern = re.compile(rf'`("{re.escape(portable)}")(?=[\s`])')
            text, count = pattern.subn(r"`python3 \1", text)
            if count:
                reasons.append(f"explicit Python invocation for {helper}")
    return text.encode("utf-8"), reasons


def package_readme(skill: str, skills: list[str]) -> bytes:
    return f"""# {skill} gamma test package

This local build contains the selected skill plus its explicit dependencies:
{", ".join(f"`{name}`" for name in skills)}. Import the literal `skills/`
directory as the skillset content; `{manifest_path(skill)}` records source hashes,
the Git commit (and dirty status), and every package-only path adaptation.

The primary skill's `references/gamma/plugin.json` is the real source manifest,
copied without changing its version. GCP's plugin-level report validator,
startup-program validator, and plan emitter are copied into that skill's `scripts/`; their command references
are adapted to `<SKILL_BASE>`. Policy checks resolve the sibling
`tf-best-practices` skill. Source repository files are never rewritten.
The offers skill's informational links to its other callers are retained;
those alternative workflows are outside this package's execution scope.

## Required runtime verification

The source `agents/` directory is deliberately omitted: this skillset format does
not register plugin worker definitions. Copies of the available worker
instructions live under the primary skill's `references/gamma/workers/` only for
provenance. They are **not registered agents**. Before a Heroku run can be called
compatible, verify the harness can dispatch the worker tiers required by the
phase interpreter. A dispatch permission error (including 403) is unresolved by
this ZIP; having a dispatch tool does not authorize skipping it or executing
fragments inline. Preserve the skill's existing dispatch and failure rules.

Packaging success does not establish runtime availability, agent registration,
model compliance, Terraform provider validity, or successful deployment. Test
the complete workflow in gamma before accepting the package.

## Local inspection

Use the repository's Python 3.12 environment for these commands.
Run `python3 scripts/build-gamma-skillset.py --verify <zip>` from the source
plugin directory to check the archive against its manifest. Hashes detect
accidental corruption; this manifest is not a cryptographic signature.

The builder and verifier do not use credentials, upload, run skill scripts, or
send telemetry. The packaged skills retain their original consent rules;
running them is a separate action.
""".encode()


def build_payload(source: Path, primary: str) -> dict[str, bytes]:
    source = source.resolve()
    skills = dependency_closure(primary)
    payload: dict[str, bytes] = {}
    records: dict[str, dict] = {}

    def add(source_relative: str, destination: str, skill: str | None = None) -> None:
        if destination in payload:
            raise PackageError(f"duplicate package path: {destination}")
        path = safe_source_file(source, source_relative)
        original = path.read_bytes()
        validate_source_bytes(source_relative, original)
        data, changes = adapt_markdown(destination, original, skill) if skill else (original, [])
        # Both emitter copies compute their default from their own scripts/
        # parent. Point them at the unaltered source manifest in the same skill.
        if destination.endswith("/scripts/emit-plan-json.py"):
            before = 'default=PLUGIN_ROOT / ".claude-plugin" / "plugin.json",'
            after = 'default=PLUGIN_ROOT / "references" / "gamma" / "plugin.json",'
            text = data.decode("utf-8")
            if text.count(before) != 1:
                raise PackageError(f"plan emitter default changed: {source_relative}")
            data = text.replace(before, after).encode("utf-8")
            changes.append("default plan-emitter metadata path -> references/gamma/plugin.json")
        payload[destination] = data
        records[destination] = {
            "source_path": source_relative,
            "source_sha256": sha256(original),
            "sha256": sha256(data),
            "size": len(data),
            "adaptations": changes,
        }

    for skill in skills:
        entry = safe_source_file(source, f"skills/{skill}/SKILL.md").read_text(encoding="utf-8")
        if not re.search(rf"(?m)^name:\s*{re.escape(skill)}\s*$", entry):
            raise PackageError(f"invalid skill entrypoint: {skill}")
        for needed in REQUIRED_FILES[skill]:
            safe_source_file(source, f"skills/{skill}/{needed}")
        for path in source_tree(source, f"skills/{skill}"):
            relative = path.relative_to(source).as_posix()
            add(relative, relative, skill)

    source_manifest_path = ".claude-plugin/plugin.json"
    manifest_bytes = safe_source_file(source, source_manifest_path).read_bytes()
    try:
        plugin_manifest = json.loads(manifest_bytes)
        if not isinstance(plugin_manifest.get("version"), str) or not plugin_manifest["version"]:
            raise ValueError("source manifest has no version")
    except (UnicodeError, ValueError, AttributeError) as error:
        raise PackageError(f"invalid source plugin manifest: {error}") from error
    add(source_manifest_path, f"skills/{primary}/references/gamma/plugin.json")
    if primary == "gcp-to-aws":
        for helper in GCP_HELPERS:
            add(f"scripts/{helper}", f"skills/{primary}/scripts/{helper}")
    for worker in WORKERS:
        add(f"agents/{worker}", f"skills/{primary}/references/gamma/workers/{worker}")

    validate_portable_references(payload, skills)
    payload["README.md"] = package_readme(primary, skills)
    records["README.md"] = {
        "source_path": None,
        "source_sha256": None,
        "sha256": sha256(payload["README.md"]),
        "size": len(payload["README.md"]),
        "adaptations": ["generated package usage and runtime limitations"],
    }
    manifest = {
        "format_version": 1,
        "primary_skill": primary,
        "skills": skills,
        "source": source_revision(source),
        "plugin_version": plugin_manifest["version"],
        "builder_sha256": sha256(Path(__file__).read_bytes()),
        "workers_registered": False,
        "informational_skill_links_omitted": sorted(
            set().union(*REFERENCE_ONLY_LINKS.values()) - set(skills)
        ),
        "files": records,
    }
    manifest_name = manifest_path(primary)
    if manifest_name in payload:
        raise PackageError(f"source contains reserved generated manifest: {manifest_name}")
    payload[manifest_name] = canonical_json(manifest)
    return payload


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name) and "\\" not in name and ":" not in name and not path.is_absolute()
        and not name.endswith("/") and ".." not in path.parts
        and name == path.as_posix() and "\x00" not in name
    )


def verify_archive(archive: Path) -> dict:
    try:
        with zipfile.ZipFile(archive) as handle:
            names = handle.namelist()
            if len(names) != len(set(names)) or any(not safe_member(name) for name in names):
                raise PackageError("archive contains duplicate or unsafe member paths")
            if any(name != "README.md" and not name.startswith("skills/") for name in names):
                raise PackageError("archive root must contain only README.md and skills/")
            for member in handle.infolist():
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise PackageError(f"archive contains symlink: {member.filename}")
            if handle.testzip() is not None:
                raise PackageError("archive CRC check failed")
            candidates = [manifest_path(skill) for skill in SUPPORTED_SKILLS if manifest_path(skill) in names]
            if len(candidates) != 1:
                raise PackageError("archive must have exactly one primary skill manifest")
            manifest_name = candidates[0]
            manifest = json.loads(handle.read(manifest_name))
            if not isinstance(manifest, dict):
                raise PackageError("package manifest must be an object")
            if manifest["format_version"] != 1:
                raise PackageError("unsupported package manifest version")
            primary = manifest["primary_skill"]
            if manifest["skills"] != dependency_closure(primary):
                raise PackageError("manifest dependency closure is incomplete")
            records = manifest["files"]
            if not isinstance(records, dict) or not all(
                isinstance(record, dict) for record in records.values()
            ):
                raise PackageError("package file records must be objects")
            if manifest_name != manifest_path(primary):
                raise PackageError("manifest path does not match primary skill")
            if set(names) != set(records) | {manifest_name}:
                raise PackageError("archive files do not match manifest")
            for name, record in records.items():
                data = handle.read(name)
                if record["sha256"] != sha256(data) or record["size"] != len(data):
                    raise PackageError(f"archive hash mismatch: {name}")
            for skill in manifest["skills"]:
                required = ("SKILL.md", *REQUIRED_FILES[skill])
                for relative in required:
                    if f"skills/{skill}/{relative}" not in records:
                        raise PackageError(f"archive missing required dependency: {skill}/{relative}")
            for relative in ("references/gamma/plugin.json",):
                if f"skills/{primary}/{relative}" not in records:
                    raise PackageError(f"archive missing required helper: {relative}")
            if primary == "gcp-to-aws":
                for helper in GCP_HELPERS:
                    if f"skills/{primary}/scripts/{helper}" not in records:
                        raise PackageError(f"archive missing required helper: {helper}")
            return manifest
    except (OSError, zipfile.BadZipFile, KeyError, TypeError, ValueError) as error:
        if isinstance(error, PackageError):
            raise
        raise PackageError(f"invalid package archive: {error}") from error


def build_archive(source: Path, skill: str, output: Path, *, force: bool = False) -> dict:
    """Write and verify a temporary ZIP, then atomically publish the local file."""
    source = source.resolve()
    if output.is_symlink():
        raise PackageError("output symlink is not allowed")
    resolved_output = output.absolute().resolve()
    if resolved_output.is_relative_to(source):
        raise PackageError("output must be outside the source tree")
    output = resolved_output
    if output.suffix.lower() != ".zip":
        raise PackageError("output must have a .zip suffix")
    if output.exists() and (not force or not output.is_file()):
        raise PackageError("output exists; use --force only to replace a regular ZIP file")
    if not output.parent.is_dir():
        raise PackageError("output parent directory does not exist")
    payload = build_payload(source, skill)
    fd, temporary = tempfile.mkstemp(prefix=".gamma-skillset-", suffix=".zip", dir=output.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
                for name, data in sorted(payload.items()):
                    if not safe_member(name):
                        raise PackageError(f"unsafe package member: {name}")
                    member = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
                    member.create_system = 3
                    member.external_attr = (stat.S_IFREG | 0o644) << 16
                    member.compress_type = zipfile.ZIP_DEFLATED
                    handle.writestr(member, data, compresslevel=9)
            stream.flush()
            os.fsync(stream.fileno())
        result = verify_archive(temp_path)
        if force:
            # Do not follow a symlink introduced after the initial check.
            if output.is_symlink() or (output.exists() and not output.is_file()):
                raise PackageError("output changed to an unsafe file")
            os.replace(temp_path, output)
        else:
            # A hard link atomically creates a new output without a check/write
            # overwrite race. The temporary file is on the same filesystem.
            try:
                os.link(temp_path, output)
            except FileExistsError as error:
                raise PackageError("output appeared during build; refusing overwrite") from error
        return result
    finally:
        temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PLUGIN_ROOT, help="plugin source directory")
    parser.add_argument("--skill", choices=SUPPORTED_SKILLS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing regular output ZIP")
    parser.add_argument("--verify", type=Path, metavar="ZIP", help="verify an existing ZIP; do not build")
    args = parser.parse_args(argv)
    if args.verify and (args.skill or args.output or args.force):
        parser.error("--verify cannot be combined with build options")
    if not args.verify and (not args.skill or not args.output):
        parser.error("a build requires --skill and --output")
    try:
        if args.verify:
            manifest = verify_archive(args.verify)
            print(f"PACKAGE_OK | skill={manifest['primary_skill']} | files={len(manifest['files'])}")
        else:
            manifest = build_archive(args.source, args.skill, args.output, force=args.force)
            print(
                f"PACKAGE_BUILT | skill={manifest['primary_skill']} | "
                f"files={len(manifest['files'])} | path={args.output}"
            )
    except PackageError as error:
        print(f"PACKAGE_FAIL | {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
