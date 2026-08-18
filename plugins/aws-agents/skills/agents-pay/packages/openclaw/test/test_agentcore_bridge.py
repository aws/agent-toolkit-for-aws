from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


BRIDGE_PATH = Path(__file__).resolve().parents[1] / "runtime" / "agentcore_bridge.py"
SPEC = importlib.util.spec_from_file_location("agentcore_bridge", BRIDGE_PATH)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_payment_session(self, **kwargs):
        self.calls.append(("get_payment_session", kwargs))
        return {
            "paymentSession": {
                "createdAt": datetime(2026, 8, 7, tzinfo=timezone.utc),
            }
        }

    def process_payment(self, **kwargs):
        self.calls.append(("process_payment", kwargs))
        return {
            "paymentOutput": {
                "cryptoX402": {
                    "payload": {"signature": "signed"},
                }
            }
        }


class BridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.regions: list[str] = []

    def factory(self, region: str) -> FakeClient:
        self.regions.append(region)
        return self.client

    def test_get_payment_session_maps_exact_service_request(self) -> None:
        result = bridge._dispatch(
            {
                "operation": "get_payment_session",
                "region": "us-east-1",
                "payment_manager_arn": "arn:manager",
                "payment_session_id": "session-1",
                "user_id": "user-1",
                "agent_name": "openclaw-aws-agents-pay",
            },
            self.factory,
        )

        self.assertEqual(self.regions, ["us-east-1"])
        self.assertEqual(
            self.client.calls,
            [
                (
                    "get_payment_session",
                    {
                        "paymentManagerArn": "arn:manager",
                        "paymentSessionId": "session-1",
                        "userId": "user-1",
                        "agentName": "openclaw-aws-agents-pay",
                    },
                )
            ],
        )
        encoded = json.dumps(result, default=bridge._json_default)
        self.assertIn("2026-08-07T00:00:00+00:00", encoded)

    def test_process_payment_maps_exact_service_request(self) -> None:
        payload = {
            "scheme": "exact",
            "network": "eip155:84532",
            "amount": "1000",
            "payTo": "0xmerchant",
        }
        token = "a" * 64
        result = bridge._dispatch(
            {
                "operation": "process_payment",
                "region": "us-west-2",
                "payment_manager_arn": "arn:manager",
                "payment_session_id": "session-1",
                "payment_instrument_id": "instrument-1",
                "user_id": "user-1",
                "agent_name": "openclaw-aws-agents-pay",
                "client_token": token,
                "version": "2",
                "payload": payload,
            },
            self.factory,
        )

        self.assertEqual(self.regions, ["us-west-2"])
        self.assertEqual(
            self.client.calls,
            [
                (
                    "process_payment",
                    {
                        "paymentManagerArn": "arn:manager",
                        "paymentSessionId": "session-1",
                        "userId": "user-1",
                        "agentName": "openclaw-aws-agents-pay",
                        "paymentInstrumentId": "instrument-1",
                        "clientToken": token,
                        "paymentType": "CRYPTO_X402",
                        "paymentInput": {
                            "cryptoX402": {
                                "version": "2",
                                "payload": payload,
                            }
                        },
                    },
                )
            ],
        )
        self.assertEqual(
            result["paymentOutput"]["cryptoX402"]["payload"]["signature"],
            "signed",
        )

    def test_bridge_rejects_every_field_outside_the_contract(self) -> None:
        request = {
            "operation": "get_payment_session",
            "region": "us-east-1",
            "payment_manager_arn": "arn:manager",
            "payment_session_id": "session-1",
            "user_id": "user-1",
            "agent_name": "openclaw-aws-agents-pay",
            "unexpected": "value",
        }
        with self.assertRaises(bridge.BridgeInputError):
            bridge._dispatch(request, self.factory)
        self.assertEqual(self.regions, [])

    def test_bridge_rejects_invalid_payment_inputs_before_aws(self) -> None:
        base = {
            "operation": "process_payment",
            "region": "us-east-1",
            "payment_manager_arn": "arn:manager",
            "payment_session_id": "session-1",
            "payment_instrument_id": "instrument-1",
            "user_id": "user-1",
            "agent_name": "openclaw-aws-agents-pay",
            "client_token": "a" * 64,
            "version": "2",
            "payload": {"amount": "1000"},
        }
        for mutation in (
            {"version": "1"},
            {"client_token": "not-a-token"},
            {"payload": ["not", "an", "object"]},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(bridge.BridgeInputError):
                    bridge._dispatch({**base, **mutation}, self.factory)
        self.assertEqual(self.regions, [])

    def test_invalid_stdin_fails_without_diagnostics(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BRIDGE_PATH)],
            input=b'{"operation":"not-supported"}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, b"")
        self.assertEqual(
            json.loads(completed.stdout),
            {"ok": False, "error": "invalid bridge request"},
        )


if __name__ == "__main__":
    unittest.main()
