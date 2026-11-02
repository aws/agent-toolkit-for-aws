"""Check workshop identities and content fingerprints across complete snapshots."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_accept_migration_run import acceptance


class ScenarioSnapshotAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenarios = self.root / "scenarios"
        self.scenarios.mkdir()
        inventory = self.root / "gcp-resource-inventory.json"
        inventory.write_text('{"resources": []}\n')
        self.index = {
            "baseline_scenario_id": "scenario-001",
            "active_scenario_id": "scenario-001",
            "max_scenarios": 5,
            "inventory_fingerprint": hashlib.sha256(inventory.read_bytes()).hexdigest(),
            "scenarios": [{
                "scenario_id": "scenario-001",
                "manifest": "scenarios/scenario-001.json",
            }],
        }
        self.manifest = {"scenario_id": "scenario-001", "paths": {}}
        for key, suffix, fingerprint in [
            ("preferences", "preferences.json", "preferences_fingerprint"),
            ("aws_design", "aws-design.json", "aws_design_fingerprint"),
            ("estimation_infra", "estimation-infra.json", None),
        ]:
            relative = f"scenarios/scenario-001.{suffix}"
            path = self.root / relative
            path.write_text("{}\n")
            current = {"workshop": {"active_scenario_id": "scenario-001"}} if key == "preferences" else {}
            (self.root / suffix).write_text(json.dumps(current))
            self.manifest["paths"][key] = relative
            if fingerprint:
                self.manifest[fingerprint] = hashlib.sha256(path.read_bytes()).hexdigest()

    def result(self):
        (self.scenarios / "index.json").write_text(json.dumps(self.index))
        (self.scenarios / "scenario-001.json").write_text(json.dumps(self.manifest))
        return acceptance.scenario_consistency(self.root)

    def test_complete_snapshots_pass_without_rewriting(self):
        self.assertEqual(self.result()["status"], "PASS")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(acceptance.scenario_consistency(self.root)["status"], "PASS")
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_inventory_drift_is_detected(self):
        (self.root / "gcp-resource-inventory.json").write_text('{"changed": true}')
        self.assertEqual(self.result()["status"], "FAIL")

    def test_missing_active_or_baseline_is_rejected(self):
        for field in ["active_scenario_id", "baseline_scenario_id"]:
            with self.subTest(field=field):
                original = self.index.pop(field)
                self.assertEqual(self.result()["status"], "FAIL")
                self.index[field] = original

    def test_duplicate_ids_and_wrong_manifest_are_rejected(self):
        self.index["scenarios"].append(dict(self.index["scenarios"][0]))
        self.assertEqual(self.result()["status"], "FAIL")
        self.index["scenarios"].pop()
        self.index["scenarios"][0]["manifest"] = "../outside.json"
        self.assertEqual(self.result()["status"], "FAIL")

    def test_cross_scenario_reference_is_rejected(self):
        self.manifest["paths"]["preferences"] = "scenarios/scenario-002.preferences.json"
        self.assertEqual(self.result()["status"], "FAIL")

    def test_missing_or_tampered_snapshot_is_rejected(self):
        path = self.scenarios / "scenario-001.preferences.json"
        path.write_text('{"changed": true}')
        self.assertEqual(self.result()["status"], "FAIL")
        path.unlink()
        self.assertEqual(self.result()["status"], "FAIL")

    def test_active_working_artifacts_must_match_selected_snapshot(self):
        for filename in ("aws-design.json", "estimation-infra.json", "preferences.json"):
            with self.subTest(filename=filename):
                path = self.root / filename
                original = path.read_bytes()
                value = json.loads(original)
                value["changed"] = True
                path.write_text(json.dumps(value))
                self.assertEqual(self.result()["status"], "FAIL")
                path.write_bytes(original)

    def test_workshop_bookkeeping_must_select_the_indexed_scenario(self):
        path = self.root / "preferences.json"
        path.write_text('{"workshop": {"active_scenario_id": "scenario-999"}}')
        self.assertEqual(self.result()["status"], "FAIL")
        path.write_text('{"workshop": {"active_scenario_id": "scenario-001", "active": false, "last_sheet_at": "changed"}}')
        self.assertEqual(self.result()["status"], "PASS")

    def test_inactive_snapshot_must_parse_even_if_its_hash_matches(self):
        sid = "scenario-002"
        other = {"scenario_id": sid, "paths": {}}
        self.index["scenarios"].append({
            "scenario_id": sid, "manifest": f"scenarios/{sid}.json",
        })
        for key, suffix in [
            ("preferences", "preferences.json"), ("aws_design", "aws-design.json"),
            ("estimation_infra", "estimation-infra.json"),
        ]:
            relative = f"scenarios/{sid}.{suffix}"
            path = self.root / relative
            path.write_text("{this is not JSON" if key == "aws_design" else "{}")
            other["paths"][key] = relative
            if key == "aws_design":
                other["aws_design_fingerprint"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.scenarios / f"{sid}.json").write_text(json.dumps(other))
        self.assertEqual(self.result()["status"], "FAIL")

    def test_boolean_does_not_equal_integer_snapshot_value(self):
        path = self.scenarios / "scenario-001.aws-design.json"
        path.write_text('{"desired_count": 1}')
        self.manifest["aws_design_fingerprint"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / "aws-design.json").write_text('{"desired_count": true}')
        self.assertEqual(self.result()["status"], "FAIL")

    def test_equivalent_numeric_serialization_does_not_change_scenario(self):
        (self.scenarios / "scenario-001.estimation-infra.json").write_text('{"cost": 1}')
        (self.root / "estimation-infra.json").write_text('{"cost": 1.0}')
        self.assertEqual(self.result()["status"], "PASS")

    def test_semantic_workshop_note_is_not_ignored_as_bookkeeping(self):
        path = self.scenarios / "scenario-001.preferences.json"
        path.write_text('{"workshop": {"graviton_note": "1 incompatible"}}')
        self.manifest["preferences_fingerprint"] = hashlib.sha256(path.read_bytes()).hexdigest()
        current = self.root / "preferences.json"
        current.write_text('{"workshop": {"active_scenario_id": "scenario-001", "graviton_note": "0 incompatible"}}')
        self.assertEqual(self.result()["status"], "FAIL")
        current.write_text('{"workshop": {"active_scenario_id": "scenario-001", "graviton_note": "1 incompatible"}}')
        self.assertEqual(self.result()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
