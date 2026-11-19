"""heroku-to-aws sets the RDS/Aurora engine_version from the source database's PostgreSQL version.

Discover captures `pg_version` on every heroku-postgresql add-on (`pg:info` prints it as `16.4`).
Design used to write a literal `"15"` for every database, so a source on 16, 17 or 18 was mapped
to an older major. A dump restores into the same or a newer major, never an older one.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HEROKU = PLUGIN_ROOT / "skills" / "heroku-to-aws"
MAPPING = HEROKU / "references" / "phases" / "design" / "design-mapping.md"
DESIGN = HEROKU / "references" / "phases" / "design" / "design.md"
GENERATE_TF = HEROKU / "references" / "phases" / "generate" / "generate-terraform.md"
SCHEMA = HEROKU / "references" / "shared" / "schema-discover-heroku.md"
FIXTURE = PLUGIN_ROOT / "fixtures" / "heroku-live-capture" / "seed-estimate"


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _major(pg_version: str) -> str:
    match = re.match(r"\s*(\d+)", pg_version)
    assert match, pg_version
    return match.group(1)


def test_design_mapping_has_no_hard_coded_engine_version() -> None:
    text = MAPPING.read_text(encoding="utf-8")
    # The RDS/Aurora template must not carry a literal major. (The ElastiCache template keeps
    # its own placeholder.)
    assert not re.search(r'"engine_version":\s*"\d+"', text)
    assert "<major from step 6a" in text


def test_design_rule_reads_pg_version_and_never_lowers_the_major() -> None:
    text = _flat(MAPPING)
    rule = text.split("6a. **Engine version**", 1)[1].split("7. **Multi-AZ deployment**", 1)[0]
    assert "`config.pg_version`" in rule
    assert "integer before the first `.`" in rule
    assert '"16.4"` -> `"16"`' in rule
    assert "never a lower one" in rule
    # Fallback: the newest major both services offer, with a warning that names the cause.
    assert 'use `"18"`' in rule
    assert "was not captured" in rule
    assert "cannot be restored into" in rule
    assert "Do not choose a version from the plan" in rule


def test_design_phase_asserts_the_engine_version() -> None:
    text = _flat(DESIGN)
    assert "aws_config.engine_version equal to the integer part" in text
    assert "no such entry has an engine_version lower than its source major" in text.lower()


def test_generate_derives_the_parameter_group_family_from_engine_version() -> None:
    text = _flat(GENERATE_TF)
    assert 'family = "postgres<major_version>" # <major_version> is the integer part of aws_config.engine_version' in text
    assert ('family = "aurora-postgresql<major_version>" # <major_version> is the integer part of '
            "aws_config.engine_version") in text


def test_discover_schema_documents_the_captured_shape() -> None:
    text = _flat(SCHEMA)
    assert '`pg_version` (string, as `pg:info` prints it, e.g. `"16.4"`' in text


def _resumed_version(saved: str, pg_version: str | None) -> str:
    """The rule in generate-terraform.md, 'Normalize aws_config.engine_version first'."""
    if not pg_version or not re.match(r"\s*\d+", pg_version):
        return saved  # no captured version: leave the entry exactly as saved
    source = int(_major(pg_version))
    return str(source) if int(saved) < source else saved  # only ever raise


def test_generate_raises_an_older_saved_version_to_the_source_major() -> None:
    text = _flat(GENERATE_TF)
    rule = text.split("**Normalize `aws_config.engine_version` first**", 1)[1].split("### RDS PostgreSQL", 1)[0]
    # What the rule says, so a reworded rule has to update the examples below with it.
    assert "`heroku-resource-inventory.json`" in rule and "`config.pg_version`" in rule
    assert "integer before the first `.`" in rule
    assert "lower than that major" in rule
    assert 'family = "postgres<major_version>"' in rule and 'family = "aurora-postgresql<major_version>"' in rule
    assert "`generation-warnings.json`" in rule
    assert "Only ever raise the version" in rule
    assert "no captured `pg_version` is left exactly as saved" in rule
    assert "Never error on the older value" in rule
    # The decide-complete resume path is the reason the rule exists.
    assert "decide-complete resume" in rule
    # The warning scenario is listed with the others in Step 10.
    assert "A resumed design whose saved PostgreSQL `engine_version` was raised" in text


def test_resume_rule_examples() -> None:
    # (saved, source pg_version) -> generated engine_version
    cases = [
        ("15", "16.4", "16"),   # the old literal against a 16 source: raised, and the family follows
        ("15", "18", "18"),
        ("15", "15.8", "15"),   # already matches: unchanged
        ("17", "16.4", "17"),   # saved above the source: never lowered
        ("15", None, "15"),     # no captured pg_version: left as saved
        ("15", "", "15"),
        ("16", "not a version", "16"),
    ]
    for saved, source, expected in cases:
        assert _resumed_version(saved, source) == expected, (saved, source)


def test_resume_rule_applied_to_the_fixtures_old_design_would_change_it() -> None:
    # The fixture's design at the base commit carried "15" for two 16.4 sources. That is the
    # shape a design saved before this change has, so the rule must raise it to 16.
    inventory = json.loads((FIXTURE / "heroku-resource-inventory.json").read_text(encoding="utf-8"))
    versions = {r["resource_id"]: r["config"].get("pg_version") for r in inventory["resources"]
                if r.get("config", {}).get("addon_service") == "heroku-postgresql"}
    design = json.loads((FIXTURE / "aws-design.json").read_text(encoding="utf-8"))
    entries = [s for s in design["services"] if s["aws_service"] in ("RDS PostgreSQL", "Aurora PostgreSQL")]
    assert len(entries) >= 2
    for entry in entries:
        assert _resumed_version("15", versions[entry["source_resource_id"]]) == entry["aws_config"]["engine_version"]


def test_fixture_design_matches_each_source_databases_major() -> None:
    inventory = json.loads((FIXTURE / "heroku-resource-inventory.json").read_text(encoding="utf-8"))
    source_major: dict[str, str] = {}
    for resource in inventory["resources"]:
        config = resource.get("config", {})
        if config.get("addon_service") == "heroku-postgresql" and config.get("pg_version"):
            source_major[resource["resource_id"]] = _major(config["pg_version"])
    assert source_major, "the fixture must contain at least one captured pg_version"

    design = json.loads((FIXTURE / "aws-design.json").read_text(encoding="utf-8"))
    checked = 0
    for service in design["services"]:
        if service["aws_service"] not in ("RDS PostgreSQL", "Aurora PostgreSQL"):
            continue
        expected = source_major[service["source_resource_id"]]
        actual = service["aws_config"]["engine_version"]
        assert actual == expected, (service["service_id"], actual, expected)
        assert int(actual) >= int(expected)
        checked += 1
    assert checked >= 2
