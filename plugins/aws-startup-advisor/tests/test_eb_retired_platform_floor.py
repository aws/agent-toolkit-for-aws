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
    assert "add an `eb_platform_branch_retired` entry to `warnings[]`" in text
    assert "Do not pick the newest branch for a retired source version, and do not drop the version from the regex" in text
    assert "platforms-supported.html" in text


def test_the_warning_code_is_in_the_schema_and_the_report_emits_it() -> None:
    schema = json.loads(WARNINGS_SCHEMA.read_text(encoding="utf-8"))
    assert "eb_platform_branch_retired" in schema["$defs"]["warning"]["properties"]["code"]["enum"]
    assert "- `eb_platform_branch_retired` for each Elastic Beanstalk service" in _flat(REPORT_FRAGMENT)
    docs = _flat(RENDER / "references" / "phases" / "generate" / "generate-artifacts-docs.md")
    assert "each `eb_platform_branch_retired` warning (name the source runtime version" in docs


def test_golden_eb_variant_names_a_supported_branch() -> None:
    compute = EB_VARIANT.read_text(encoding="utf-8")
    regexes = re.findall(r'name_regex\s*=\s*"([^"]+)"', compute)
    assert regexes, "the EB variant must select its platform with a name_regex"
    for regex in regexes:
        for branch in RETIRED_BRANCHES:
            assert not regex.endswith(f"running {branch}$"), f"{regex!r} names the retired branch {branch}"
        assert re.search(r"running [A-Za-z.]+ [0-9.]+\$$", regex), f"{regex!r} must pin one language major version"
    assert 'running Node.js 22$' in compute


def test_gcp_mapping_example_does_not_hardcode_a_retired_python_version() -> None:
    compute = _flat(GCP_COMPUTE)
    assert "Elastic Beanstalk (Python 3.9" not in compute
    assert "the `python39` branch was retired on 2026-08-13" in compute
    eb = _flat(GCP_EB)
    assert "**Retired language versions.**" in eb
    assert "name the lowest supported branch of the same family" in eb and "never the newest" in eb
    assert "add a `warnings[]` entry to `aws-design.json`" in eb
