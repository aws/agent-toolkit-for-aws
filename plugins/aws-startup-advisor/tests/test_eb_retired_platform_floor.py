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
    assert "name the lowest supported branch of the same family instead" in text
    assert "add an `eb_platform_branch_retired` warning" in text
    # The version is a persisted design field, never a guess from source files at Generate time.
    assert "`<version>` is `aws_config.runtime_version` from the design" in text
    assert "Generate never reads source files or guesses" in text
    # Both cases are stated: a declared retired version, and no declared version.
    assert "`runtime_version` names a retired branch:" in text
    assert "`runtime_version` is `null`: name the lowest supported branch of the family and add an `eb_platform_version_undeclared` warning" in text
    assert "Do not pick the newest branch in either case, and do not drop the version from the regex" in text
    assert "platforms-supported.html" in text


def test_the_warning_code_is_in_the_schema_and_the_report_emits_it() -> None:
    schema = json.loads(WARNINGS_SCHEMA.read_text(encoding="utf-8"))
    codes = schema["$defs"]["warning"]["properties"]["code"]["enum"]
    assert "eb_platform_branch_retired" in codes and "eb_platform_version_undeclared" in codes
    report = _flat(REPORT_FRAGMENT)
    assert "- `eb_platform_branch_retired` for each Elastic Beanstalk service" in report
    assert "`eb_platform_version_undeclared` for each Elastic Beanstalk service whose `compute.runtime_version` is `null`" in report
    docs = _flat(RENDER / "references" / "phases" / "generate" / "generate-artifacts-docs.md")
    assert "each `eb_platform_branch_retired` warning (name the declared runtime version" in docs
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
    assert "record `compute.runtime_version` (`resource_id` the service)" in clarify
    assert '`default_rule: "runtime.declared_in_source"`' in clarify
    assert "record `value: null` as `answered` with the consequence that Generate names the lowest supported branch" in clarify
    assert "Never invent a version" in clarify
    design = _flat(RENDER / "references" / "phases" / "design" / "design-infra.md")
    assert "write `aws_config.platform_family` from the Blueprint `runtime`" in design
    assert "`aws_config.runtime_version` from the service's `compute.runtime_version` answer" in design
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
