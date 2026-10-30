"""Local package integration, reproducibility, and unsafe-input regressions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import zipfile

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BUILDER = PLUGIN_ROOT / "scripts" / "build-gamma-skillset.py"
spec = importlib.util.spec_from_file_location("gamma_builder", BUILDER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    root = tmp_path_factory.mktemp("gamma-packages")
    archives = {}
    for skill in builder.SUPPORTED_SKILLS:
        archive = root / f"{skill}.zip"
        builder.build_archive(PLUGIN_ROOT, skill, archive)
        archives[skill] = archive
    return archives


@pytest.fixture
def source_copy(tmp_path):
    """Copy only package inputs, retaining realistic cross-skill references."""
    source = tmp_path / "source"
    all_skills = set().union(
        *(builder.dependency_closure(skill) for skill in builder.SUPPORTED_SKILLS)
    )
    for skill in all_skills:
        shutil.copytree(
            PLUGIN_ROOT / "skills" / skill,
            source / "skills" / skill,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    for relative in [
        ".claude-plugin/plugin.json",
        *(f"agents/{worker}" for worker in builder.WORKERS),
        *(f"scripts/{helper}" for helper in builder.GCP_HELPERS),
    ]:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PLUGIN_ROOT / relative, destination)
    return source


@pytest.mark.parametrize("skill", builder.SUPPORTED_SKILLS)
def test_package_closes_dependencies_and_preserves_source_bytes(packages, skill):
    archive = packages[skill]
    manifest = builder.verify_archive(archive)
    assert manifest["source"]["commit"] == subprocess.check_output(
        ["git", "-C", str(PLUGIN_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    assert manifest["workers_registered"] is False
    assert manifest["skills"] == sorted([
        skill, "tf-best-practices", "contextual-offers-for-startups", "knowledge-base-for-startups",
    ])
    with zipfile.ZipFile(archive) as handle:
        assert {name.split("/")[0] for name in handle.namelist()} == {"README.md", "skills"}
        assert all(member.date_time == builder.FIXED_ZIP_TIME for member in handle.infolist())
        assert handle.namelist() == sorted(handle.namelist())
        for name, record in manifest["files"].items():
            data = handle.read(name)
            assert hashlib.sha256(data).hexdigest() == record["sha256"]
            if record["source_path"] is None:
                assert name == "README.md"
                continue
            original = (PLUGIN_ROOT / record["source_path"]).read_bytes()
            assert hashlib.sha256(original).hexdigest() == record["source_sha256"]
            if not record["adaptations"]:
                assert data == original, name
        metadata = handle.read(f"skills/{skill}/references/gamma/plugin.json")
        assert metadata == (PLUGIN_ROOT / ".claude-plugin/plugin.json").read_bytes()
        assert manifest["plugin_version"] == json.loads(metadata)["version"]
        policy = "skills/tf-best-practices/scripts/validate-terraform-policy.py"
        assert handle.read(policy) == (PLUGIN_ROOT / policy).read_bytes()
        readme = handle.read("README.md").decode()
        assert "not registered agents" in readme
        assert "403" in readme
        assert "executing\nfragments inline" in readme
        assert not any(name.startswith("agents/") for name in handle.namelist())
        for worker in builder.WORKERS:
            name = f"skills/{skill}/references/gamma/workers/{worker}"
            assert handle.read(name) == (PLUGIN_ROOT / "agents" / worker).read_bytes()


@pytest.mark.parametrize("skill", builder.SUPPORTED_SKILLS)
def test_identical_inputs_produce_identical_archives(tmp_path, skill):
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    builder.build_archive(PLUGIN_ROOT, skill, first)
    builder.build_archive(PLUGIN_ROOT, skill, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("skill", builder.SUPPORTED_SKILLS)
def test_packaged_helpers_execute_independently_of_source_tree(packages, skill, tmp_path):
    with zipfile.ZipFile(packages[skill]) as handle:
        handle.extractall(tmp_path)
    scripts = tmp_path / "skills" / skill / "scripts"
    helpers = [scripts / "emit-plan-json.py"]
    report = "validate-migration-report.py" if skill == "gcp-to-aws" else "validate-heroku-migration-report.py"
    helpers.append(scripts / report)
    if skill == "gcp-to-aws":
        helpers.append(scripts / "validate-startup-program-artifacts.py")
    helpers.append(tmp_path / "skills" / "tf-best-practices" / "scripts" / "validate-terraform-policy.py")
    helpers.append(tmp_path / "skills" / "tf-best-practices" / "scripts" / "validate-migration-artifacts.py")
    for helper in helpers:
        result = subprocess.run(
            [sys.executable, str(helper), "--help"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0, (helper, result.stderr)
        assert "usage:" in result.stdout
    # Default metadata must resolve inside the extracted skill rather than the
    # original checkout or an absent plugin root.
    helper_spec = importlib.util.spec_from_file_location(f"{skill}_emitter", helpers[0])
    emitter = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(emitter)
    golden = (
        PLUGIN_ROOT / "fixtures" / "gcp-decision-gate" / "after-decide-complete"
        if skill == "gcp-to-aws"
        else PLUGIN_ROOT / "fixtures" / "heroku-iac-terraform" / "after-estimate"
    )
    # The GCP golden run exercises real plan emission. The shared emitter's
    # Heroku route is covered by its native tests; adapting only the default
    # metadata path must leave the rest of the script identical.
    if skill == "gcp-to-aws":
        run = tmp_path / "run"
        shutil.copytree(golden, run)
        result = subprocess.run(
            [sys.executable, str(helpers[0]), "--migration-dir", str(run)],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "PLAN_OK" in result.stdout
        plan = json.loads((run / "plan.json").read_text())
        assert plan["producerVersion"] == json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text()
        )["version"]


def test_gcp_paths_resolve_inside_package(packages):
    with zipfile.ZipFile(packages["gcp-to-aws"]) as handle:
        base = "skills/gcp-to-aws"
        for name in [
            f"{base}/SKILL.md",
            f"{base}/references/phases/estimate/estimate.md",
            f"{base}/references/phases/generate/generate.md",
            f"{base}/references/phases/generate/generate-artifacts-report.md",
            f"{base}/references/shared/validate-migration-report.md",
        ]:
            text = handle.read(name).decode()
            assert "$PLUGIN_ROOT/scripts/" not in text
            assert "$PLUGIN_ROOT/.claude-plugin/" not in text
        assert "<SKILL_BASE>/scripts/validate-migration-report.py" in handle.read(
            f"{base}/SKILL.md"
        ).decode()
        assert "<SKILL_BASE>/../tf-best-practices/scripts/validate-terraform-policy.py" in handle.read(
            f"{base}/SKILL.md"
        ).decode()
        assert "<SKILL_BASE>/scripts/validate-terraform-policy.py" in handle.read(
            "skills/tf-best-practices/SKILL.md"
        ).decode()


def test_gcp_startup_gate_runs_from_documented_command_in_unrelated_cwd(packages, tmp_path):
    extraction = tmp_path / "extracted skillset"
    with zipfile.ZipFile(packages["gcp-to-aws"]) as handle:
        handle.extractall(extraction)
    base = extraction / "skills" / "gcp-to-aws"
    helper = base / "scripts" / "validate-startup-program-artifacts.py"
    assert helper.read_bytes() == (PLUGIN_ROOT / "scripts" / helper.name).read_bytes()
    invocation = f'python3 "<SKILL_BASE>/scripts/{helper.name}"'
    for relative in (
        "references/phases/generate/generate-ai.md",
        "references/shared/validate-artifacts.md",
        "references/shared/report-decision-core.md",
    ):
        assert invocation in (base / relative).read_text()
    gate_text = (base / "references/shared/validate-artifacts.md").read_text()
    command = re.search(r"`(python3 [^`]*validate-startup-program-artifacts\.py[^`]*)`", gate_text).group(1)
    run = tmp_path / "test-run"
    run.mkdir()
    (run / "preferences.json").write_text(json.dumps({
        "startup_constraints": {"startup_program_status": {"value": "unknown"}}
    }))
    artifact = run / "STARTUP_PROGRAMS.md"
    artifact.write_text("Review AWS Activate at https://aws.amazon.com/startups/credits/\n")
    elsewhere = tmp_path / "unrelated working directory"
    elsewhere.mkdir()
    arguments = shlex.split(command)
    arguments[0] = sys.executable
    arguments = [
        arg.replace("<SKILL_BASE>", str(base)).replace("$MIGRATION_DIR", str(run))
        for arg in arguments
    ]
    valid = subprocess.run(arguments, cwd=elsewhere, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert "STARTUP_OK" in valid.stdout
    artifact.write_text("Your status: eligible founders tier\n")
    invalid = subprocess.run(arguments, cwd=elsewhere, capture_output=True, text=True)
    assert invalid.returncode == 1
    assert "STARTUP_FAIL" in invalid.stderr


def test_refuses_output_within_source_even_when_not_previously_present(source_copy):
    with pytest.raises(builder.PackageError, match="outside the source"):
        builder.build_archive(source_copy, "gcp-to-aws", source_copy / "new.zip")
    assert not (source_copy / "new.zip").exists()


def test_refuses_output_parent_symlink_into_source(source_copy, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(source_copy, target_is_directory=True)
    with pytest.raises(builder.PackageError, match="outside the source"):
        builder.build_archive(source_copy, "gcp-to-aws", alias / "new.zip")


def test_refuses_output_symlink_and_preserves_target(packages, tmp_path):
    target = tmp_path / "target.zip"
    target.write_bytes(b"original")
    link = tmp_path / "link.zip"
    link.symlink_to(target)
    with pytest.raises(builder.PackageError, match="symlink"):
        builder.build_archive(PLUGIN_ROOT, "gcp-to-aws", link, force=True)
    assert target.read_bytes() == b"original"


def test_existing_output_is_preserved_until_explicit_force(tmp_path):
    output = tmp_path / "out.zip"
    output.write_bytes(b"leave me unchanged")
    with pytest.raises(builder.PackageError, match="output exists"):
        builder.build_archive(PLUGIN_ROOT, "gcp-to-aws", output)
    assert output.read_bytes() == b"leave me unchanged"
    builder.build_archive(PLUGIN_ROOT, "gcp-to-aws", output, force=True)
    assert builder.verify_archive(output)["primary_skill"] == "gcp-to-aws"
    assert not list(tmp_path.glob(".gamma-skillset-*"))


@pytest.mark.parametrize("relative", [
    "skills/tf-best-practices/scripts/validate-terraform-policy.py",
    "skills/tf-best-practices/scripts/validate-migration-artifacts.py",
    "skills/tf-best-practices/scripts/rds_windows.py",
    "skills/knowledge-base-for-startups/SKILL.md",
    "scripts/validate-migration-report.py",
    "scripts/validate-startup-program-artifacts.py",
])
def test_missing_dependency_fails_before_writing_archive(source_copy, tmp_path, relative):
    (source_copy / relative).unlink()
    output = tmp_path / "output.zip"
    with pytest.raises(builder.PackageError, match="missing"):
        builder.build_archive(source_copy, "gcp-to-aws", output)
    assert not output.exists()


def test_broken_python_dependency_fails_closed(source_copy, tmp_path):
    helper = source_copy / "scripts" / "validate-migration-report.py"
    helper.write_text("def broken(\n")
    with pytest.raises(builder.PackageError, match="corrupt source"):
        builder.build_archive(source_copy, "gcp-to-aws", tmp_path / "output.zip")


def test_broken_metadata_fails_closed(source_copy, tmp_path):
    (source_copy / ".claude-plugin" / "plugin.json").write_text('{"name":"no-version"}')
    with pytest.raises(builder.PackageError, match="no version"):
        builder.build_archive(source_copy, "gcp-to-aws", tmp_path / "output.zip")


@pytest.mark.parametrize("new_reference,match", [
    ('Run "$PLUGIN_ROOT/scripts/new-required-validator.py".', "unmapped plugin-root"),
    ('Run `scripts/new-required-validator.py`.', "unmapped root helper"),
    ("Load `../new-helper/SKILL.md`.", "undeclared sibling dependency"),
])
def test_unmapped_new_dependencies_fail_closed(source_copy, tmp_path, new_reference, match):
    path = source_copy / "skills" / "gcp-to-aws" / "SKILL.md"
    path.write_text(path.read_text() + "\n" + new_reference + "\n")
    with pytest.raises(builder.PackageError, match=match):
        builder.build_archive(source_copy, "gcp-to-aws", tmp_path / "output.zip")


def test_source_symlink_escape_is_rejected(source_copy, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("not part of the skill")
    (source_copy / "skills" / "gcp-to-aws" / "leak.txt").symlink_to(secret)
    with pytest.raises(builder.PackageError, match="symlink"):
        builder.build_archive(source_copy, "gcp-to-aws", tmp_path / "output.zip")


def rewrite_zip(source: Path, destination: Path, change):
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(destination, "w") as after:
        for name in before.namelist():
            result = change(name, before.read(name))
            if result is not None:
                after.writestr(name, result)


def test_changed_file_hash_is_rejected(packages, tmp_path):
    output = tmp_path / "corrupt.zip"
    rewrite_zip(
        packages["gcp-to-aws"], output,
        lambda name, data: data + b"\ncorrupt" if name.endswith("/SKILL.md") else data,
    )
    with pytest.raises(builder.PackageError, match="hash mismatch"):
        builder.verify_archive(output)


def test_missing_file_is_rejected_even_if_manifest_was_edited(packages, tmp_path):
    output = tmp_path / "missing-policy.zip"
    removed = "skills/tf-best-practices/scripts/validate-terraform-policy.py"

    def remove(name, data):
        if name == removed:
            return None
        if name == builder.manifest_path("gcp-to-aws"):
            manifest = json.loads(data)
            del manifest["files"][removed]
            return builder.canonical_json(manifest)
        return data

    rewrite_zip(packages["gcp-to-aws"], output, remove)
    with pytest.raises(builder.PackageError, match="missing required dependency"):
        builder.verify_archive(output)


@pytest.mark.parametrize("member", ["../outside.txt", "/absolute.txt", r"C:\outside.txt"])
def test_archive_traversal_is_rejected(packages, tmp_path, member):
    archive = tmp_path / "unsafe.zip"
    shutil.copy2(packages["gcp-to-aws"], archive)
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr(member, b"unsafe")
    with pytest.raises(builder.PackageError, match="unsafe member"):
        builder.verify_archive(archive)


def test_duplicate_archive_member_is_rejected(packages, tmp_path):
    archive = tmp_path / "duplicate.zip"
    shutil.copy2(packages["gcp-to-aws"], archive)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(archive, "a") as handle:
            handle.writestr("README.md", b"duplicate")
    with pytest.raises(builder.PackageError, match="duplicate"):
        builder.verify_archive(archive)


def test_unsupported_root_content_is_rejected(packages, tmp_path):
    archive = tmp_path / "unsupported-root.zip"
    shutil.copy2(packages["gcp-to-aws"], archive)
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("agents/unregistered.md", b"unsupported root")
    with pytest.raises(builder.PackageError, match="root must contain only"):
        builder.verify_archive(archive)


def test_cli_reports_invalid_archive_without_traceback(tmp_path):
    archive = tmp_path / "not-a-zip.zip"
    archive.write_bytes(b"invalid")
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--verify", str(archive)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "PACKAGE_FAIL" in result.stderr
    assert "Traceback" not in result.stderr
