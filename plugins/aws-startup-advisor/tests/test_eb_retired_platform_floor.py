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
    assert "A design saved without `platform_family` is read with the family `design-infra.md` derives from the service's inventory `config.runtime`" in text
    assert "one saved without `runtime_version` is read as `runtime_version: null`" in text


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
    assert "write `aws_config.platform_family` from the service's inventory `config.runtime`" in design
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
