"""Generate and independent acceptance share the same runtime record gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / (
    "skills/tf-best-practices/scripts/validate-terraform-report.py"
)
SPEC = importlib.util.spec_from_file_location("terraform_report_contract", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(REPORT)


def complete_report() -> dict:
    return {
        "$schema": "validation-report/v2",
        "status": "passed",
        "policy_status": "POLICY_OK",
        "attempts": 0,
        "errors_found": [],
        "errors_fixed": [],
        "policy_violations": [],
        "offline_fallback_used": False,
        "timestamp": "2026-10-30T20:00:00Z",
        "terraform_version": "1.13.5",
    }


class TerraformReportContractTest(unittest.TestCase):
    def test_research_partial_report_cannot_complete(self):
        value = {
            "status": "passed_degraded_offline",
            "note": "CLI unavailable; fmt/init/validate skipped",
            "check": "policy",
            "policy_status": "POLICY_OK",
            "violations": [],
            "attempts": 1,
            "errors_fixed": 0,
        }
        errors = REPORT.validation_report_errors(value)
        self.assertIn("$schema must be validation-report/v2", errors)
        self.assertIn("errors_fixed must be an array", errors)
        self.assertIn("offline_fallback_used must match passed_degraded_offline", errors)

    def test_cli_checks_without_mutating_report(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            for status, expected in [
                ("passed", 0), ("skipped_user_abort", 1), ("policy_failed", 1),
            ]:
                with self.subTest(status=status):
                    value = complete_report()
                    value["status"] = status
                    path.write_text(json.dumps(value))
                    before = path.read_bytes()
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), str(path)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, expected, result.stdout)
                    self.assertEqual(path.read_bytes(), before)

    def test_offline_and_explicit_skip_records_remain_distinct(self):
        value = complete_report()
        value["status"] = "passed_degraded_offline"
        value["offline_fallback_used"] = True
        self.assertEqual(REPORT.validation_report_errors(value), [])
        value["status"] = "skipped_user_continue"
        value["terraform_version"] = ""
        self.assertTrue(REPORT.validation_report_errors(value))
        value["offline_fallback_used"] = False
        self.assertEqual(REPORT.validation_report_errors(value), [])

    def test_malformed_input_is_a_failed_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            for text in ["[1]", "{", "null"]:
                path.write_text(text)
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(path)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("RUNTIME_REPORT_FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
