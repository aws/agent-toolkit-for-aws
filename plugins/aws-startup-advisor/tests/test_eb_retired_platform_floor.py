"""Elastic Beanstalk `name_regex` must never name a retired platform branch.

Elastic Beanstalk retired the Node.js 20, Python 3.9 and Ruby 3.2 AL2023 branches on 2026-08-13
(Node.js 18 on 2025-08-11). A retired branch is not listed, so a `data
"aws_elastic_beanstalk_solution_stack"` regex that names it matches nothing and `terraform plan`
fails. render-to-aws builds the regex from the source service's runtime version with no floor, and
gcp-to-aws's mapping example hardcoded "Python 3.9". Both now fall back to the lowest supported
branch of the family and record a warning.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RENDER = PLUGIN_ROOT / "skills" / "render-to-aws"
GCP = PLUGIN_ROOT / "skills" / "gcp-to-aws"
COMPUTE_FRAGMENT = RENDER / "references" / "phases" / "generate" / "generate-infra-compute.md"
REPORT_FRAGMENT = RENDER / "references" / "phases" / "generate" / "generate-artifacts-report.md"
WARNINGS_SCHEMA = RENDER / "references" / "shared" / "schema-generation-warnings.json"
EB_VARIANT = RENDER / "fixtures" / "expected" / "generated-variants" / "compute-elastic-beanstalk" / "terraform" / "compute.tf"
GCP_COMPUTE = GCP / "references" / "design-refs" / "compute.md"
GCP_EB = GCP / "references" / "design-refs" / "elastic-beanstalk.md"
RENDER_COMPUTE = RENDER / "references" / "design-refs" / "compute.md"
BLUEPRINT_PARSER = RENDER / "scripts" / "parse-render-blueprint.py"

# AL2023 branches Elastic Beanstalk has retired (platform release notes, read 2026-11-20).
RETIRED_BRANCHES = ("Node.js 18", "Node.js 20", "Python 3.8", "Python 3.9", "Ruby 3.1", "Ruby 3.2")


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_render_compute_fragment_floors_a_retired_source_runtime_branch() -> None:
    text = _flat(COMPUTE_FRAGMENT)
    assert "retired on 2026-08-13" in text
    assert "add an `eb_platform_branch_retired` warning" in text
    # The version is a persisted design field, never a guess from source files at Generate time.
    assert "built from `aws_config.platform_family` and `aws_config.runtime_version` in the design and nothing else" in text
    assert "Generate never reads source files or guesses" in text
    # Branch choice is membership in the family's currently listed branches, so a retired branch and a
    # never-offered one (Python 3.10, Node.js 23) take the same path; `null` takes the third.
    assert "checking whether `runtime_version` is in the family's currently listed branches" in text
    assert "`runtime_version` is listed: use it." in text
    assert "`runtime_version` is not `null` and not listed, whether the branch was retired" in text
    assert "or never offered (Python 3.10, Node.js 23)" in text
    assert "name the nearest listed branch above the declared version" in text
    assert "whether the branch was retired or never offered in `detail`" in text
    assert "`runtime_version` is `null`: name the lowest listed branch of the family and add an `eb_platform_version_undeclared` warning" in text
    assert "Never drop the version step from a versioned family's regex" in text
    assert "platforms-supported.html" in text
def test_render_unversioned_platform_families_get_a_family_only_regex() -> None:
    """`... running Docker` and `... running Go 1` carry no language version, so the versioned regex
    shape can never match them and the undeclared-version warning does not apply."""
    text = _flat(COMPUTE_FRAGMENT)
    assert "Families whose platform name has no language version (`Docker`, `Go 1`)" in text
    assert "`^64bit Amazon Linux 2023 (.*) running <aws_config.platform_family>$` with no version step" in text
    assert "`runtime_version` is `null` for these by construction and no version warning is written" in text
    clarify = _flat(RENDER / "references" / "phases" / "clarify" / "clarify-compute.md")
    assert "Services whose platform name carries no language version (`docker`, services deployed from an `image`, and `go`) record this row as `not_applicable`" in clarify
    design = _flat(RENDER / "references" / "phases" / "design" / "design-infra.md")
    assert "`null` for `Go 1` and `Docker`, whose platform names carry no language version" in design
def test_render_design_family_labels_match_the_supported_platforms_page() -> None:
    """Every family label Design can write must appear after `running` on the supported-platforms
    page (read 2026-11-20), and only Render runtimes may be mapped: Render has no Java, PHP or .NET
    runtime, and `.NET Core` is not how the page names the .NET family."""
    design = (RENDER / "references" / "phases" / "design" / "design-infra.md").read_text(encoding="utf-8")
    page_families = {"Docker", "Go 1", "Corretto", "Tomcat", ".NET", "Node.js", "PHP", "Python", "Ruby"}
    labels = re.findall(r"`(?:node|python|ruby|go|docker)`(?: \(or a service deployed from an `image`\))? → `([^`]+)`", design)
    assert set(labels) == {"Node.js", "Python", "Ruby", "Go 1", "Docker"}
    assert set(labels) <= page_families
    assert ".NET Core" not in design and "Corretto" not in design and "PHP" not in design
    assert "Render's `rust` and `elixir` runtimes have no Elastic Beanstalk platform" in design
    compute = _flat(RENDER / "references" / "design-refs" / "compute.md")
    assert "The source-based Render runtimes with an Elastic Beanstalk platform are `node`, `python`, `ruby` and `go`" in compute
def test_render_generate_reads_a_design_saved_before_the_platform_fields_existed() -> None:
    text = _flat(COMPUTE_FRAGMENT)
    assert "A design saved without `platform_family` is read with the family `design-infra.md` derives from the service's effective runtime" in text
    # The old-design fallback follows the Build Source edge too, and never guesses when nothing yields a family.
    assert "otherwise the Git runtime or `image` form of the Build Source it links to through `service_uses_build_source`, otherwise the `compute.runtime_family` answer" in text
    assert "when none of those yields a family, return to Design rather than guess" in text
    assert "One saved without `runtime_version` is read as `runtime_version: null`" in text


def test_the_warning_code_is_in_the_schema_and_the_report_emits_it() -> None:
    schema = json.loads(WARNINGS_SCHEMA.read_text(encoding="utf-8"))
    codes = schema["$defs"]["warning"]["properties"]["code"]["enum"]
    assert "eb_platform_branch_retired" in codes and "eb_platform_version_undeclared" in codes
    report = _flat(REPORT_FRAGMENT)
    assert "- `eb_platform_branch_retired` for each Elastic Beanstalk service whose `compute.runtime_version` names no listed platform branch (retired, or never offered)" in report
    assert "`eb_platform_version_undeclared` for each Elastic Beanstalk service whose `compute.runtime_version` is `null`" in report
    docs = _flat(RENDER / "references" / "phases" / "generate" / "generate-artifacts-docs.md")
    assert "each `eb_platform_branch_retired` warning (name the declared runtime version, whether its branch was retired or never offered" in docs
    assert "each `eb_platform_version_undeclared` warning" in docs


def test_golden_eb_variant_names_a_supported_branch() -> None:
    compute = EB_VARIANT.read_text(encoding="utf-8")
    regexes = re.findall(r'name_regex\s*=\s*"([^"]+)"', compute)
    assert regexes, "the EB variant must select its platform with a name_regex"
    for regex in regexes:
        for branch in RETIRED_BRANCHES:
            assert not regex.endswith(f"running {branch}$"), f"{regex!r} names the retired branch {branch}"
        assert re.search(r"running [A-Za-z.]+ [0-9.]+\$$", regex), f"{regex!r} must pin one language major version"
    assert 'running Node.js 22$' in compute


def test_render_persists_the_language_version_from_clarify_through_design() -> None:
    """Render's Blueprint carries only the runtime family, so the version must come from a recorded
    Clarify answer and travel through the design; Generate cannot read source files or guess."""
    clarify = _flat(RENDER / "references" / "phases" / "clarify" / "clarify-compute.md")
    assert "ask `compute.runtime_version` (`resource_id` the service)" in clarify
    # Clarify takes only the inventory as input and the scanner records no version, so the row is
    # always asked; `schema-preferences.md` reserves `defaulted` for `provenance: default`.
    assert "Clarify reads no application files, so this row is always asked and recorded as `answered` with `provenance: \"user\"`" in clarify
    assert "runtime.declared_in_source" not in clarify and 'provenance: "discovered"' not in clarify
    assert "record `value: null` as `answered` with the consequence that Generate names the lowest supported branch" in clarify
    assert "Never invent a version" in clarify
    design = _flat(RENDER / "references" / "phases" / "design" / "design-infra.md")
    assert "write `aws_config.platform_family` from the service's effective runtime (`design-refs/compute.md`" in design
    assert "Write `aws_config.runtime_version` from the service's `compute.runtime_version` answer" in design
    assert "Generate builds the platform regex from these two fields and nothing else" in design


def test_gcp_producers_apply_the_floor_where_the_regex_and_guide_are_written() -> None:
    """The design reference alone is not reachable; the runtime-to-platform step, the Generate
    Compute row, the guide and the report must each apply or surface the rule."""
    design = _flat(GCP / "references" / "phases" / "design" / "design-infra.md")
    assert "when the version's platform branch is retired" in design
    assert "write the lowest supported branch of the family instead (Python 3.11 when this was written)" in design
    assert "add a `warnings[]` entry naming the service, the source version and the branch chosen" in design
    infra = _flat(GCP / "references" / "phases" / "generate" / "generate-artifacts-infra.md")
    assert "if it has been retired since Design ran, name the lowest supported branch of the same family instead" in infra
    assert "a retired branch is not listed, so its regex matches nothing and `terraform plan` fails" in infra
    docs = _flat(GCP / "references" / "phases" / "generate" / "generate-artifacts-docs.md")
    assert "For each `warnings[]` entry in `aws-design.json` about an Elastic Beanstalk platform branch" in docs
    report = _flat(GCP / "references" / "phases" / "generate" / "generate-artifacts-report.md")
    assert "A design warning about an Elastic Beanstalk platform branch" in report


def test_gcp_mapping_example_does_not_hardcode_a_retired_python_version() -> None:
    compute = _flat(GCP_COMPUTE)
    assert "Elastic Beanstalk (Python 3.9" not in compute
    assert "the `python39` branch was retired on 2026-08-13" in compute
    eb = _flat(GCP_EB)
    assert "**Retired language versions.**" in eb
    assert "name the lowest supported branch of the same family" in eb and "never the newest" in eb
    assert "add a `warnings[]` entry to `aws-design.json`" in eb


def test_render_effective_runtime_is_defined_once_and_follows_the_build_source_edge() -> None:
    """A schema-valid service that uses `buildSource` cannot carry `runtime`; the parser stores the
    runtime on the linked Build Source. Clarify, Design and the old-design Generate fallback must all
    read the same edge-aware lookup instead of the service's `config.runtime` alone."""
    compute = _flat(RENDER_COMPUTE)
    assert "**Effective runtime.**" in compute
    assert "Rule 4, Clarify's `compute.runtime_version` row and Design's Elastic Beanstalk platform step read a service's runtime through this one lookup and nothing else" in compute
    assert "`config.runtime` from a Blueprint, `config.serviceDetails.runtime` from a live capture" in compute
    assert "follow its unique `service_uses_build_source` edge to the `render.build_source` resource and read `config.git.runtime`" in compute
    assert "treat a Build Source with `config.image` as `docker`" in compute
    # A live-captured Build Source has no runtime field; the family is asked, never inferred.
    assert "A live-captured Build Source records repo and branch but no runtime" in compute
    assert "return `compute.runtime_family` to Clarify (one of `node`, `python`, `ruby`, `go`, `docker`" in compute
    assert "never inferred from the repository name, build command or start command" in compute
    clarify = _flat(RENDER / "references" / "phases" / "clarify" / "clarify-compute.md")
    assert "A service's runtime is its effective runtime from `design-refs/compute.md`" in clarify
    assert "otherwise the runtime of the Build Source it links to through `service_uses_build_source` (`config.git.runtime`, or `docker` for an `image` Build Source)" in clarify
    assert "ask `compute.runtime_family` (`resource_id` the service; one of `node`, `python`, `ruby`, `go`, `docker`)" in clarify
    assert "whose effective runtime is `node`, `python` or `ruby` that can select traditional Elastic Beanstalk, ask `compute.runtime_version`" in clarify
    assert "a service whose Build Source is an `image` is one of them" in clarify
    assert "with inventory `config.runtime` `node`" not in clarify
    design = _flat(RENDER / "references" / "phases" / "design" / "design-infra.md")
    assert "otherwise its Build Source's `config.git.runtime` or `docker` for an `image` Build Source, otherwise the `compute.runtime_family` answer" in design
    assert "from the service's inventory `config.runtime`" not in design


def _effective_runtime(inventory: dict, service: dict) -> str | None:
    """The lookup exactly as `design-refs/compute.md` states it, applied to real parser output."""
    config = service["config"]
    if config.get("runtime") is not None:
        return config["runtime"]
    details = config.get("serviceDetails")
    if isinstance(details, dict) and details.get("runtime") is not None:
        return details["runtime"]
    edges = [edge for edge in inventory["edges"] if edge["type"] == "service_uses_build_source" and edge["from_id"] == service["id"]]
    assert len(edges) == 1, "a buildSource service has exactly one Build Source edge"
    build_source = next(resource for resource in inventory["resources"] if resource["id"] == edges[0]["to_id"])
    assert build_source["kind"] == "render.build_source"
    if isinstance(build_source["config"].get("git"), dict):
        return build_source["config"]["git"].get("runtime")
    if "image" in build_source["config"]:
        return "docker"
    return None


def test_render_blueprint_parser_puts_the_runtime_of_a_build_source_service_on_the_build_source(tmp_path: Path) -> None:
    """Run the real parser on a Blueprint with a Node Git Build Source and an image Build Source: the
    services carry no `runtime`, and the documented lookup recovers `node` and `docker` from the edge."""
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    blueprint = workspace / "render.yaml"
    blueprint.write_text(
        """version: "1"
buildSources:
  - name: api-build
    git: {repo: https://github.com/example/api, branch: main, runtime: node}
  - name: img-build
    image: {url: docker.io/library/alpine:3.21}
services:
  - type: web
    name: api
    buildSource: api-build
    startCommand: node server.js
  - type: worker
    name: img-worker
    buildSource: img-build
  - type: web
    name: direct
    runtime: python
    startCommand: gunicorn app:app
""",
        encoding="utf-8",
    )
    output = migration / "inventory.json"
    result = subprocess.run(
        [sys.executable, str(BLUEPRINT_PARSER), "--source", str(blueprint), "--workspace-root", str(workspace), "--migration-dir", str(migration), "--output", str(output)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    inventory = json.loads(output.read_text(encoding="utf-8"))
    services = {resource["name"]: resource for resource in inventory["resources"] if resource["kind"] in {"render.web_service", "render.background_worker"}}
    assert set(services) == {"api", "img-worker", "direct"}
    for name in ("api", "img-worker"):
        assert "runtime" not in services[name]["config"], f"{name} must not carry runtime; the Blueprint schema forbids it with buildSource"
        assert services[name]["config"]["buildSource"]
    assert _effective_runtime(inventory, services["api"]) == "node"
    assert _effective_runtime(inventory, services["img-worker"]) == "docker"
    assert _effective_runtime(inventory, services["direct"]) == "python"
    # The parser rejects a service that carries both, so the lookup's "service runtime first" branch and
    # its "follow the edge" branch are disjoint on schema-valid input.
    blueprint.write_text(
        """version: "1"
buildSources:
  - name: api-build
    git: {repo: https://github.com/example/api, runtime: node}
services:
  - type: web
    name: both
    buildSource: api-build
    runtime: node
""",
        encoding="utf-8",
    )
    conflicting = subprocess.run(
        [sys.executable, str(BLUEPRINT_PARSER), "--source", str(blueprint), "--workspace-root", str(workspace), "--migration-dir", str(migration), "--output", str(migration / "conflict.json")],
        text=True, capture_output=True, check=False,
    )
    assert conflicting.returncode == 1 and "code=schema_invalid" in conflicting.stderr


def test_render_live_build_source_projection_has_no_runtime_so_the_family_is_asked() -> None:
    """The REST Build Source projection keeps repo/branch/commit/artifact but no runtime, which is why
    the lookup ends in a Clarify question instead of a guess."""
    projections = json.loads((RENDER / "references" / "shared" / "schema-render-rest-projections.json").read_text(encoding="utf-8"))
    build_source = projections["$defs"]["buildSource"]
    assert build_source["additionalProperties"] is False
    assert "runtime" not in build_source["properties"]
    assert {"repo", "branch"} <= set(build_source["required"])
    schema = json.loads((RENDER / "references" / "render" / "render-yaml.schema.json").read_text(encoding="utf-8"))
    assert "runtime" in schema["definitions"]["buildSourceGit"]["required"], "a Blueprint Git Build Source always declares its runtime"
