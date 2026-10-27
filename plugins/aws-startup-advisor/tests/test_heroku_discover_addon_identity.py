"""Guard: same-plan add-ons on the same app don't collide on resource_id.

Review finding (leon1418, PR #434 round 5, databaseId 4242786523,
discover-live.md): two heroku-postgresql add-ons on the same app and the
same plan (e.g. postgresql-alpha, postgresql-beta, both standard-0) minted
the identical resource_id `addon:{app_name}:{addon_service}:{plan}`. The
schema requires unique resource_ids and discover-assemble.md's "one entry
per resource_id" merge rule then silently collapsed the two databases into
one, losing one database's pool data and cost contribution.

Fix: incorporate the add-on's existing per-instance identifier (`addon_name`
— already captured since the round-4 capture fix, via the
`pg-advanced-<app>-<addon_name>.out` filenames) into the resource_id, so two
same-plan add-ons on the same app get distinct IDs. Update the
discover-assemble.md merge contract to match (pairing across live/Terraform
sources no longer assumes resource_id equality for addons).

This is a documentation-contract check (string/shape assertions against the
markdown), matching the existing `test_heroku_postgres_advanced_pricing.py`
pattern — this plugin's skill files are instructions read by an LLM agent,
not executable code.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_HEROKU = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "shared"
    / "schema-discover-heroku.md"
)

DISCOVER_LIVE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-live.md"
)

DISCOVER_TERRAFORM = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-terraform.md"
)

DISCOVER_ASSEMBLE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-assemble.md"
)


def test_schema_resource_id_format_includes_addon_name() -> None:
    text = SCHEMA_HEROKU.read_text(encoding="utf-8")
    assert "addon:{app_name}:{addon_service}:{plan}:{addon_name}" in text


def test_schema_addon_name_is_required_config_field() -> None:
    text = SCHEMA_HEROKU.read_text(encoding="utf-8")
    # The `addon` config required-fields table must list addon_name as a
    # required (not merely optional/enrichment) field.
    assert "`addon_name`" in text
    idx = text.index("| `addon_name`    | string | ✅")
    assert idx > 0


def test_discover_live_resource_entry_includes_addon_name_discriminator() -> None:
    text = DISCOVER_LIVE.read_text(encoding="utf-8")
    assert ':{addon_name}"' in text
    assert "addons.json" in text
    assert "pg-advanced-<app>-<addon_name>.out" in text


def test_discover_terraform_resource_id_and_attribute_table_include_addon_name() -> None:
    text = DISCOVER_TERRAFORM.read_text(encoding="utf-8")
    assert ":{addon_name}" in text
    assert "tf_resource_name_fallback" in text
    # Step 1c's #heroku_addon attribute table must have an addon_name row.
    heroku_addon_idx = text.index("#### `heroku_addon`")
    heroku_formation_idx = text.index("#### `heroku_formation`")
    section = text[heroku_addon_idx:heroku_formation_idx]
    assert "addon_name" in section


def test_discover_assemble_rule_1b_reports_ambiguous_addon_groups() -> None:
    text = DISCOVER_ASSEMBLE.read_text(encoding="utf-8")
    assert "ambiguous_addon_groups" in text
    assert "do **not** pair heuristically" in text or "do not pair heuristically" in text
    assert "1b" in text


def test_discover_assemble_rule_1a_pairs_only_when_unambiguous() -> None:
    text = DISCOVER_ASSEMBLE.read_text(encoding="utf-8")
    rule1a_idx = text.index("1a.")
    rule1b_idx = text.index("1b.")
    rule1a = text[rule1a_idx:rule1b_idx]
    assert "exactly one live-sourced and one" in rule1a
