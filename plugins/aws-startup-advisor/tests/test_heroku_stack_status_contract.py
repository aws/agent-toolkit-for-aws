"""The stack-status enrichment Discover always writes must pass the inventory contract.

Review finding (leon1418, PR #610): assembly rule 10 emits
`metadata.apps_by_stack_status` and `metadata.eol_stack_apps` on every inventory, but
the artifact contract is built from the fenced JSON example in
schema-discover-heroku.md, so the keys were UNKNOWN_KEY until the example carried them.
Cover: a legacy inventory without the fields, an enriched zero-EOL inventory, and an
enriched inventory with an EOL app and an unknown-stack app.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = PLUGIN_ROOT / "skills/heroku-to-aws/references/shared/schema-discover-heroku.md"
SUPPORT = PLUGIN_ROOT / "skills/heroku-to-aws/knowledge/discover/heroku-stack-support.json"

spec = importlib.util.spec_from_file_location("stack_status_validator", PLUGIN_ROOT / "scripts/validate-artifacts.py")
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


def _example() -> dict:
    blocks = [b for b in validator.extract_blocks(SCHEMA) if validator._heading_matches(b.heading, "Complete Example")]
    assert len(blocks) == 1
    return json.loads(validator.strip_jsonc(blocks[0].text)[0])


def _validate(tmp_path: Path, inventory: dict) -> list:
    (tmp_path / "heroku-resource-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    findings: list = []
    manifest = validator.load_manifest(PLUGIN_ROOT / "scripts/artifact-contracts.json")
    validator.validate_run_dir(tmp_path, "heroku-to-aws", manifest, findings)
    return findings


def _strip_stack_status(inventory: dict) -> dict:
    inv = copy.deepcopy(inventory)
    inv["metadata"].pop("apps_by_stack_status", None)
    inv["metadata"].pop("eol_stack_apps", None)
    for app in inv["apps"]:
        app.pop("stack_status", None)
        app.pop("stack_eol_date", None)
    return inv


def _enrich(inventory: dict, statuses: list[str]) -> dict:
    inv = _strip_stack_status(inventory)
    assert len(statuses) == len(inv["apps"])
    counts = {"eol": 0, "deprecated": 0, "supported": 0, "container": 0, "unknown": 0}
    eol = []
    for app, status in zip(inv["apps"], statuses):
        app["stack_status"] = status
        app["stack_eol_date"] = "2025-04-30" if status == "eol" else None
        counts[status] += 1
        if status == "eol":
            eol.append(app["app_name"])
    inv["metadata"]["apps_by_stack_status"] = counts
    inv["metadata"]["eol_stack_apps"] = sorted(eol)
    return inv


def test_legacy_inventory_without_stack_status_still_passes(tmp_path: Path):
    findings = _validate(tmp_path, _strip_stack_status(_example()))
    assert not findings, findings


def test_enriched_zero_eol_inventory_passes(tmp_path: Path):
    example = _example()
    findings = _validate(tmp_path, _enrich(example, ["supported"] * len(example["apps"])))
    assert not findings, findings


def test_enriched_inventory_with_eol_and_unknown_passes(tmp_path: Path):
    example = _example()
    statuses = ["eol"] + ["unknown"] * (len(example["apps"]) - 1)
    inv = _enrich(example, statuses)
    inv["apps"][1]["stack"] = None  # unknown stack: null source value
    findings = _validate(tmp_path, inv)
    assert not findings, findings
    assert inv["metadata"]["eol_stack_apps"] == [example["apps"][0]["app_name"]]


@pytest.mark.parametrize("key", ["apps_by_stack_status", "eol_stack_apps"])
def test_metadata_example_declares_both_summary_keys(key: str):
    # The contract is built from the fenced example, so the keys must live there, not only in the table.
    blocks = [b for b in validator.extract_blocks(SCHEMA)
              if validator._heading_matches(b.heading, "heroku-resource-inventory.json")]
    assert blocks and key in json.loads(validator.strip_jsonc(blocks[0].text)[0])["metadata"]


def test_support_table_status_values_match_contract_enum():
    rows = json.load(open(SUPPORT, encoding="utf-8"))["rows"]
    allowed = {"eol", "deprecated", "supported", "container", "unknown"}
    assert {row["status"] for row in rows.values()} <= allowed
