from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ADMIN_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "agents-pay"
    / "scripts"
    / "agents_pay_admin.py"
)
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("agents_pay_admin", ADMIN_PATH)
assert SPEC and SPEC.loader
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)


class OpenClawSetupTests(unittest.TestCase):
    def test_usd_to_atomic_is_exact_and_rejects_excess_precision(self) -> None:
        self.assertEqual(admin.usd_to_atomic(Decimal("0.10")), "100000")
        self.assertEqual(admin.usd_to_atomic(Decimal("0.000001")), "1")
        with self.assertRaisesRegex(ValueError, "at most 6 decimal places"):
            admin.usd_to_atomic(Decimal("0.0000001"))

    def test_generated_config_preserves_policy_inputs(self) -> None:
        config = admin.build_openclaw_config(
            region="us-east-1",
            manager_arn="arn:manager",
            instrument_id="instrument-1",
            session_id="session-1",
            user_id="user-1",
            network="eip155:84532",
            asset="0xasset",
            max_payment_atomic="100000",
            recipients=["0xmerchant"],
            allow_any=False,
            origins=["https://sandbox.example"],
            return_body=True,
        )

        plugin = config["plugins"]["entries"]["aws-agents-pay"]["config"]
        self.assertEqual(plugin["maxPaymentAmountAtomic"], "100000")
        self.assertEqual(plugin["allowedOrigins"], ["https://sandbox.example"])
        self.assertEqual(plugin["allowedRecipients"], ["0xmerchant"])
        self.assertTrue(plugin["returnBody"])
        self.assertNotIn("allowAnyRecipient", plugin)

    def test_explicit_project_dir_finds_agentcore_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            state = project / "agentcore" / ".cli" / "deployed-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(
                json.dumps(
                    {
                        "targets": {
                            "default": {
                                "resources": {
                                    "payments": {
                                        "payments": {
                                            "managerArn": "arn:manager",
                                            "connectors": {
                                                "connector": {
                                                    "connectorId": "connector-1"
                                                }
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                )
            )

            self.assertEqual(
                admin.discover_deployed(project),
                {
                    "manager_arn": "arn:manager",
                    "connector_id": "connector-1",
                    "role_arn": None,
                },
            )

    def test_duration_review_includes_hours_for_full_hours(self) -> None:
        self.assertEqual(admin.format_duration(1440), "1440 minutes (24 hours)")
        self.assertEqual(admin.format_duration(90), "90 minutes")


if __name__ == "__main__":
    unittest.main()
