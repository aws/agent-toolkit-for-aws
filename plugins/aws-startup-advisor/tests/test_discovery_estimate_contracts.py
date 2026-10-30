"""Regression guards for the source metadata and estimate shapes consumed later.

Discovery assembly is an agent instruction, so the metadata checks cover the
published contract and examples. The artifact-validator probes exercise the real
reader, including compatibility with inventories created before these fields.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HEROKU = PLUGIN_ROOT / "skills/heroku-to-aws/references"
GCP = PLUGIN_ROOT / "skills/gcp-to-aws/references"

spec = importlib.util.spec_from_file_location(
    "discovery_estimate_validator", PLUGIN_ROOT / "scripts/validate-artifacts.py"
)
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


def _example(document: Path, heading: str) -> dict:
    blocks = [
        block
        for block in validator.extract_blocks(document)
        if validator._heading_matches(block.heading, heading)
    ]
    assert len(blocks) == 1
    return json.loads(validator.strip_jsonc(blocks[0].text)[0])


def _validate(tmp_path: Path, artifact: str, data: dict, skill: str) -> list:
    (tmp_path / artifact).write_text(json.dumps(data), encoding="utf-8")
    findings = []
    manifest = validator.load_manifest(PLUGIN_ROOT / "scripts/artifact-contracts.json")
    validator.validate_run_dir(tmp_path, skill, manifest, findings)
    return findings


def test_heroku_examples_preserve_source_app_metadata():
    document = HEROKU / "shared/schema-discover-heroku.md"
    for heading in ("heroku-resource-inventory.json", "Complete Example"):
        inventory = _example(document, heading)
        assert inventory["apps"][0]["region"] == "us"
        assert inventory["apps"][0]["stack"] == "heroku-22"
        assert all({"region", "stack"} <= app.keys() for app in inventory["apps"])
    assert _example(document, "Complete Example")["apps"][1]["stack"] is None


@pytest.mark.parametrize("legacy", [False, True])
def test_heroku_reader_accepts_metadata_and_legacy_inventory(tmp_path: Path, legacy: bool):
    inventory = _example(HEROKU / "shared/schema-discover-heroku.md", "Complete Example")
    if legacy:
        for app in inventory["apps"]:
            app.pop("region")
            app.pop("stack")
    findings = _validate(tmp_path, "heroku-resource-inventory.json", inventory, "heroku-to-aws")
    assert not findings, findings


def test_estimate_contract_uses_keyed_breakdown_and_rejects_array(tmp_path: Path):
    document = GCP / "shared/schema-estimate-infra.md"
    assert isinstance(_example(document, "estimation-infra.json schema")["projected_costs"]["breakdown"], dict)

    estimate = json.loads(
        (PLUGIN_ROOT / "fixtures/gcp-decision-gate/after-decide-complete/estimation-infra.json").read_text()
    )
    assert not _validate(tmp_path, "estimation-infra.json", estimate, "gcp-to-aws")
    estimate["projected_costs"]["breakdown"] = [{"service": "Fargate", "monthly": 71}]
    findings = _validate(tmp_path, "estimation-infra.json", estimate, "gcp-to-aws")
    assert any(finding.path == "projected_costs.breakdown" for finding in findings), findings
