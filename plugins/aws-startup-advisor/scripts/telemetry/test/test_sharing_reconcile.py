"""Reconcile through the real sharing sender, with transport replaced by a stub.

Each probe imports one shipped runtime in a fresh process so canonical imports
cannot conceal stale bundle behavior. Preferences and migration files are local
fixtures; no probe resolves credentials or opens a network connection.
"""

import json
import subprocess
import sys

import pytest
from conftest import PLUGIN_ROOT, TELEMETRY


INSTALL_ID = "3f9c2a7e-5b1d-4e8a-9c6f-2d7b8e1a4c53"
RUNTIMES = [("canonical", TELEMETRY)] + [
    (skill, PLUGIN_ROOT / "skills" / skill / "references/vendored/telemetry")
    for skill in ("azure-to-aws", "gcp-to-aws", "heroku-to-aws", "llm-to-bedrock", "operate-on-aws")
]


PROBE = r'''
import json
import sys
import threading
import time
from pathlib import Path

runtime = Path(sys.argv[1])
project = Path(sys.argv[2])
scenario = sys.argv[3]
install_id = sys.argv[4]
sys.path[:0] = [str(runtime), str(runtime / "consent"), str(runtime / "metric_emission")]
import client
import record

assert Path(client.__file__).resolve() == runtime / "metric_emission/client.py"
assert Path(record.__file__).resolve() == runtime / "consent/record.py"
preferences = Path.home() / ".aws-startup-advisor/plugin-telemetry.json"
preferences.parent.mkdir(parents=True, exist_ok=True)
preferences.write_text(json.dumps({"installId": install_id, "consentStatus": "ACCEPTED"}))

received = []
received_guard = threading.Lock()

class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

def send(request, timeout):
    body = json.loads(request.data)
    with received_guard:
        received.append(body)
    if scenario == "slow_batch":
        time.sleep(0.4)
    return Response()

client.urllib.request.urlopen = send
url = "https://telemetry.example.invalid/v1/plugin-telemetry-event"
event = {"skillInvoked": {"skill": "GCP_TO_AWS", "eventName": "SKILL_INVOKED"}}
result = {}

if scenario == "uuid":
    result["matchedStatus"] = client.post_event_status(event, install_id.lower(), url)
    result["matchedBodies"] = list(received)
    received.clear()
    result["differentStatus"] = client.post_event_status(
        event, "0badf00d-1111-4222-8333-444444444444", url
    )
    result["differentBodies"] = list(received)
    received.clear()

if (runtime / "metric_emission/migration.py").is_file():
    import migration

    assert Path(migration.__file__).resolve() == runtime / "metric_emission/migration.py"
    run_dir = project / ".migration/test-run"
    run_dir.mkdir(parents=True)
    status = {
        "migration_id": "test-run",
        "run_id": "9b2c4d6e-8f10-4a12-b345-6789abcdef01",
        "owning_skill": "GCP_TO_AWS",
        "current_phase": "complete",
        "run_mode": "decide_and_execute",
        "phases": {name: "completed" for name in ("discover", "clarify", "design", "estimate", "generate")},
    }
    (run_dir / migration.STATUS_FILE).write_text(json.dumps(status))
    result["expectedPhases"] = status["phases"]

    if scenario == "changed_choice":
        original_build_payload = client.build_payload
        changed = threading.Event()
        change_guard = threading.Lock()

        def change_after_read(*args, **kwargs):
            payload = original_build_payload(*args, **kwargs)
            with change_guard:
                if not changed.is_set():
                    # The sender has already read ACCEPTED. Use the real writer
                    # before it acquires the final send guard and checks again.
                    record.write_state(record.OPT_OUT)
                    changed.set()
            return payload

        client.build_payload = change_after_read

    def reconcile():
        budget = migration.SESSION_END_BUDGET_SECONDS - migration.SESSION_END_RESERVE_SECONDS
        migration.process_run(
            run_dir, "9b2c4d6e-8f10-4a12-b345-6789abcdef01", True,
            url, time.time() + budget, None, "hook",
        )

    started = time.monotonic()
    reconcile()
    result["elapsed"] = time.monotonic() - started
    result["budget"] = migration.SESSION_END_BUDGET_SECONDS - migration.SESSION_END_RESERVE_SECONDS
    result["reconciledBodies"] = list(received)
    snapshot_path = run_dir / migration.SNAPSHOT_FILE
    result["snapshot"] = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else None
    before = len(received)
    reconcile()
    result["resent"] = len(received) - before
    if scenario == "changed_choice":
        result["choiceChanged"] = changed.is_set()
        result["choice"] = record.consent_status()

print(json.dumps(result))
'''


def run_probe(tmp_path, runtime, scenario, install_id=INSTALL_ID):
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(  # nosec B603 - fixed probe, isolated fixture paths, no shell
        [sys.executable, "-c", PROBE, str(runtime.resolve()), str(tmp_path / "project"), scenario, install_id],
        env={
            "HOME": str(home), "USERPROFILE": str(home), "PATH": "/usr/bin:/bin",
            "AWS_STARTUP_ADVISOR_PLUGIN_TELEMETRY_ENDPOINT": "https://telemetry.example.invalid/v1/plugin-telemetry-event",
        },
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def assert_complete_reconcile(result):
    bodies = result["reconciledBodies"]
    activities = [body["pluginTelemetryEvent"]["migrationActivity"] for body in bodies]
    assert len(activities) == 7
    assert {activity["eventName"] for activity in activities} == {
        "RUN_STARTED", "PHASE_COMPLETED", "RUN_COMPLETED",
    }
    assert {activity["phase"] for activity in activities if activity["eventName"] == "PHASE_COMPLETED"} == {
        "DISCOVER", "CLARIFY", "DESIGN", "ESTIMATE", "GENERATE",
    }
    assert {body["installId"] for body in bodies} == {INSTALL_ID}
    assert result["snapshot"]["phases"] == result["expectedPhases"]
    assert result["snapshot"]["completed"] is True
    assert result["snapshot"].get("started", True) is True
    assert result["snapshot"]["completedRunModes"] == ["DECIDE_AND_EXECUTE"]
    assert result["resent"] == 0


def test_reconcile_sends_and_records_the_whole_batch_within_teardown_budget(tmp_path):
    result = run_probe(tmp_path, TELEMETRY, "slow_batch")
    assert_complete_reconcile(result)
    assert result["elapsed"] < result["budget"], result


@pytest.mark.parametrize("runtime_name,runtime", RUNTIMES, ids=[name for name, _ in RUNTIMES])
@pytest.mark.parametrize("install_id", [INSTALL_ID.upper(), "3F9c2A7e-5B1d-4E8a-9C6f-2D7b8E1a4C53"], ids=["uppercase", "mixed-case"])
def test_reconcile_and_sender_keep_existing_installation_uuid_case_compatible(
    tmp_path, runtime_name, runtime, install_id,
):
    result = run_probe(tmp_path, runtime, "uuid", install_id)
    assert result["matchedStatus"] == 200
    assert len(result["matchedBodies"]) == 1
    assert result["matchedBodies"][0]["installId"] == INSTALL_ID
    assert result["differentStatus"] == 0
    assert result["differentBodies"] == []
    # operate-on-aws deliberately ships the shared sender without migration.py.
    if runtime_name != "operate-on-aws":
        assert_complete_reconcile(result)


def test_reconcile_rechecks_a_choice_changed_after_the_sender_read(tmp_path):
    result = run_probe(tmp_path, TELEMETRY, "changed_choice")
    assert result["choiceChanged"] is True
    assert result["choice"] == "OPT_OUT"
    assert result["reconciledBodies"] == []
    assert result["snapshot"] is None
    assert result["resent"] == 0
