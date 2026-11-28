"""Tests for payment-user setup and v1 project resource discovery."""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


script = Path(__file__).with_name("setup_payment_user.py")
spec = importlib.util.spec_from_file_location("setup_payment_user", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

MANAGER_ARN = "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/test"
STATUS = {
    "resources": [{
        "resourceType": "payment-manager",
        "arn": MANAGER_ARN,
        "children": [{"resourceType": "payment-connector", "id": "connector-test"}],
    }],
}


def test_discovers_unique_payment_resources_from_v1_status(tmp_path, monkeypatch):
    (tmp_path / "agentcore").mkdir()
    (tmp_path / "agentcore" / "agentcore.json").write_text('{"version":2}')
    monkeypatch.chdir(tmp_path)

    with patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(STATUS)
        assert module._from_deployed_state() == (MANAGER_ARN, "connector-test")
        assert module._from_deployed_state(manager_arn="arn:other") == (None, None)

        second_manager = {
            "resourceType": "payment-manager",
            "arn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/other",
            "children": [{"resourceType": "payment-connector", "id": "other-connector"}],
        }
        run.return_value.stdout = json.dumps({
            "resources": [*STATUS["resources"], second_manager],
        })
        assert module._from_deployed_state() == (None, None)
        assert module._from_deployed_state(manager_arn=second_manager["arn"]) == (
            second_manager["arn"], "other-connector"
        )

        run.return_value.stdout = json.dumps({
            "resources": [{
                **STATUS["resources"][0],
                "children": [
                    *STATUS["resources"][0]["children"],
                    {"resourceType": "payment-connector", "id": "connector-2"},
                ],
            }],
        })
        assert module._from_deployed_state() == (MANAGER_ARN, None)
        assert run.call_count == 5


@pytest.mark.parametrize("missing_flag", ["--instrument-id", "--budget"])
def test_session_only_requires_instrument_and_budget(monkeypatch, missing_flag):
    arguments = [
        "setup_payment_user.py",
        "--user-id", "alice",
        "--session-only",
        "--instrument-id", "instrument-1",
        "--budget", "5",
    ]
    flag_index = arguments.index(missing_flag)
    del arguments[flag_index:flag_index + 2]
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit) as error:
        module.main()

    assert error.value.code == 2


def test_session_only_reuses_instrument_and_creates_bounded_session(monkeypatch, capsys):
    manager = Mock()
    manager.create_payment_session.return_value = {"paymentSessionId": "session-1"}
    payment_manager = Mock(return_value=manager)

    payments_module = types.ModuleType("bedrock_agentcore.payments")
    payments_module.PaymentManager = payment_manager
    agentcore_module = types.ModuleType("bedrock_agentcore")
    agentcore_module.payments = payments_module
    monkeypatch.setitem(sys.modules, "bedrock_agentcore", agentcore_module)
    monkeypatch.setitem(sys.modules, "bedrock_agentcore.payments", payments_module)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "approve")
    monkeypatch.setattr(sys, "argv", [
        "setup_payment_user.py",
        "--user-id", "alice",
        "--session-only",
        "--instrument-id", "instrument-1",
        "--budget", "5",
        "--manager-arn", MANAGER_ARN,
    ])

    module.main()

    payment_manager.assert_called_once_with(
        payment_manager_arn=MANAGER_ARN,
        region_name="us-east-1",
    )
    manager.create_payment_instrument.assert_not_called()
    manager.create_payment_session.assert_called_once_with(
        user_id="alice",
        expiry_time_in_minutes=60,
        limits={"maxSpendAmount": {"value": "5", "currency": "USD"}},
    )
    output = capsys.readouterr().out
    assert "Instrument ID : instrument-1" in output
    assert "Session ID    : session-1" in output


def test_session_creation_refuses_noninteractive_terminal(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "setup_payment_user.py", "--user-id", "alice", "--session-only",
        "--instrument-id", "instrument-1", "--budget", "5",
    ])
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit, match="interactive terminal"):
        module.main()
