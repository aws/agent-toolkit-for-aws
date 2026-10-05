"""Executing-path tests for the migration emitter (metric_emission/migration.py).

Each test builds an ephemeral project with a `.migration/` run, an accepted consent
record in an isolated HOME, points the emitter at the local collector, runs it
exactly as a hook would (subprocess, hook JSON on stdin) and asserts on the bytes
the collector received and the snapshot left on disk. Nothing inside the emitter
is mocked.
"""

import json
import os
import socket
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
import time

import pytest
from conftest import EMISSION, PLUGIN_ROOT, run

RUN_ID = "3f9c2a7e-5b1d-4e8a-9c6f-2d7b8e1a4c53"
SESSION_ID = "9b2c4d6e-8f10-4a12-b345-6789abcdef01"
OTHER_SESSION = "0badf00d-1111-4222-8333-444444444444"
ENDPOINT_ENV = "AWS_STARTUP_ADVISOR_PLUGIN_TELEMETRY_ENDPOINT"

GCP_INVENTORY = {
    "resources": [
        {"type": "google_sql_database_instance", "name": "db"},
        {"type": "google_cloud_run_service", "name": "api"},
    ]
}


def phase_status(**overrides):
    status = {
        "migration_id": "0226-1430",
        "run_id": RUN_ID,
        "owning_skill": "GCP_TO_AWS",
        "last_updated": "2026-02-26T15:35:22Z",
        "current_phase": "clarify",
        "phases": {
            "discover": "completed",
            "clarify": "in_progress",
            "design": "pending",
            "estimate": "pending",
            "workshop": "pending",
            "generate": "pending",
            "feedback": "pending",
        },
    }
    status.update(overrides)
    return status


def with_phases(**phases):
    merged = dict(phase_status()["phases"])
    merged.update(phases)
    return merged


def all_completed():
    return {name: "completed" for name in phase_status()["phases"]}


def accept(home, install_id=RUN_ID, status="ACCEPTED"):
    directory = home / ".aws-startup-advisor"
    directory.mkdir(exist_ok=True)
    (directory / "plugin-telemetry.json").write_text(
        json.dumps({"installId": install_id, "consentStatus": status}), encoding="utf-8"
    )


class Project:
    def __init__(self, tmp_path, home, collector, status, consent="ACCEPTED", artifacts=None, run_name="0226-1430"):
        self.home = home
        self.collector = collector
        self.root = tmp_path / ("project-%s" % run_name)  # one project per run, so tests with several stay apart
        self.run_dir = self.root / ".migration" / run_name
        self.run_dir.mkdir(parents=True)
        if consent:
            accept(home, status=consent)
        for name, value in (artifacts if artifacts is not None else {"gcp-resource-inventory.json": GCP_INVENTORY}).items():
            (self.run_dir / name).write_text(json.dumps(value), encoding="utf-8")
        self.status_file = self.run_dir / ".phase-status.json"
        self.write_status(status)

    def write_status(self, status):
        self.status_file.write_text(json.dumps(status, indent=2), encoding="utf-8")

    def write_gates(self, gates):
        (self.run_dir / ".gate-failures.json").write_text(json.dumps(gates), encoding="utf-8")

    def snapshot(self):
        return json.loads((self.run_dir / ".telemetry-snapshot.json").read_text(encoding="utf-8"))

    def has_snapshot(self):
        return (self.run_dir / ".telemetry-snapshot.json").exists()

    def hook(self, *args, session_id=SESSION_ID, payload=None, env=None):
        """Run the emitter as a host would and return the events this run produced."""
        before = len(self.collector.received)
        body = {"session_id": session_id, "cwd": str(self.root), "reason": "other"}
        body.update(payload or {})
        full_env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "PATH": "/usr/bin:/bin",
                    ENDPOINT_ENV: self.collector.url, "CLAUDECODE": "1"}
        full_env.update(env or {})
        result = subprocess.run(  # nosec B603 — fixed argv, no shell
            [sys.executable, str(EMISSION / "migration.py"), *args],
            input=json.dumps(body), capture_output=True, text=True, env=full_env, cwd=str(self.root),
        )
        assert result.returncode == 0, "the emitter is fail-open and always exits 0: %s" % result.stderr
        return [json.loads(r["body"]) for r in self.collector.received[before:]]

    def reconcile(self, session_id=SESSION_ID):
        return self.hook("--reconcile", session_id=session_id)

    def session_end(self, session_id=SESSION_ID):
        return self.hook("--session-end", session_id=session_id)

    def post_write(self, file_path, session_id=SESSION_ID):
        return self.hook(session_id=session_id, payload={"tool_input": {"file_path": str(file_path)}})


def activity(body):
    return body["pluginTelemetryEvent"]["migrationActivity"]


def summary(bodies):
    return sorted((activity(b)["eventName"], activity(b).get("phase"), activity(b).get("status")) for b in bodies)


@pytest.fixture
def project(tmp_path, home, collector):
    def make(status=None, consent="ACCEPTED", artifacts=None, run_name="0226-1430"):
        return Project(tmp_path, home, collector, status or phase_status(), consent, artifacts, run_name)
    return make


# ---------------------------------------------------------------- lifecycle


def test_reports_a_new_run_once_under_the_state_file_run_id(project):
    p = project()
    first = p.reconcile()
    second = p.reconcile()
    assert summary(first) == [("PHASE_COMPLETED", "DISCOVER", "SUCCESS"), ("RUN_STARTED", None, None)]
    for body in first:
        assert activity(body)["runId"] == RUN_ID
        assert activity(body)["skill"] == "GCP_TO_AWS"
        assert activity(body)["sessionId"] == SESSION_ID
        assert body["source"] == "CLAUDE_CODE"
        assert body["installId"] == RUN_ID
        assert isinstance(body["occurredAt"], int)
        assert activity(body)["attributes"]["sourceProvider"] == "GCP"
    assert second == [], "an unchanged run is not re-reported"
    assert p.snapshot()["runId"] == RUN_ID


def test_sends_an_upper_case_run_id_in_lower_case(project):
    p = project(phase_status(run_id=RUN_ID.upper()))
    bodies = p.reconcile()
    assert len(bodies) == 2
    assert {activity(b)["runId"] for b in bodies} == {RUN_ID}
    assert p.snapshot()["runId"] == RUN_ID


def test_reports_each_later_transition_once_and_the_terminal_event_with_its_run_mode(project):
    p = project()
    p.reconcile()
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    later = p.reconcile()
    p.write_status(phase_status(current_phase="complete", run_mode="decide", phases=all_completed()))
    done = p.reconcile()
    again = p.reconcile()
    assert summary(later) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")]
    finished = [activity(b) for b in done if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert len(finished) == 1 and finished[0]["attributes"]["runMode"] == "DECIDE"
    assert again == []
    assert p.snapshot()["completed"] is True


def test_sends_nothing_and_leaves_no_trace_without_accepted_consent(project):
    for index, consent in enumerate((None, "OPT_OUT", "REJECTED")):
        p = project(consent=consent, run_name="0226-14%02d" % index)
        assert p.reconcile() == []
        assert p.session_end() == []
        assert not p.has_snapshot()
        assert not (p.run_dir / ".telemetry-lock").exists()


def test_sends_nothing_for_an_accepted_record_without_a_valid_install_id(project, home):
    p = project()
    accept(home, install_id="not-a-uuid")
    assert p.reconcile() == []
    assert not p.has_snapshot()


def test_sends_nothing_for_a_run_that_names_no_owning_skill(project):
    p = project(phase_status(owning_skill=None))
    assert p.reconcile() == []
    assert not p.has_snapshot()
    q = project(phase_status(owning_skill="AGENT_ADVISOR"), run_name="0226-1500")
    assert q.reconcile() == []


def test_keeps_one_run_identity_when_the_state_file_is_rebuilt_with_a_fresh_run_id(project):
    p = project()
    p.reconcile()
    p.write_status(phase_status(run_id="0f0f0f0f-1111-4222-8333-444444444444", current_phase="design",
                                phases=with_phases(clarify="completed")))
    later = p.reconcile()
    assert [(activity(b)["eventName"], activity(b)["phase"], activity(b)["runId"]) for b in later] == [
        ("PHASE_COMPLETED", "CLARIFY", RUN_ID)
    ]
    assert p.snapshot()["runId"] == RUN_ID


def test_omits_an_enum_attribute_whose_value_is_an_inherited_key(project):
    p = project(phase_status(current_phase="complete", run_mode="__proto__", phases=all_completed()))
    done = [activity(b) for b in p.reconcile() if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert len(done) == 1
    assert "runMode" not in (done[0].get("attributes") or {})


# ------------------------------------------------------------ hold and retry


def test_holds_the_snapshot_while_the_service_refuses_with_403_then_reports_in_full(project, collector):
    p = project()
    collector.status = 403
    refused = p.reconcile()
    assert len(refused) == 2 and not p.has_snapshot(), "nothing taken, nothing recorded"
    collector.status = 200
    accepted = p.reconcile()
    assert summary(accepted) == [("PHASE_COMPLETED", "DISCOVER", "SUCCESS"), ("RUN_STARTED", None, None)]
    assert p.reconcile() == []


def test_re_sends_only_the_throttled_events_of_a_batch(project, collector):
    p = project()
    p.reconcile()
    p.write_status(phase_status(current_phase="estimate", phases=with_phases(clarify="completed", design="completed")))
    collector.status = 429
    throttled = p.reconcile()
    assert len(throttled) == 2
    assert p.snapshot()["phases"]["clarify"] == "in_progress", "a held phase keeps its previous state"
    collector.status = 200
    retried = p.reconcile()
    assert summary(retried) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS"), ("PHASE_COMPLETED", "DESIGN", "SUCCESS")]
    assert p.reconcile() == []


def test_a_400_is_not_retried(project, collector):
    p = project()
    collector.status = 400
    rejected = p.reconcile()
    assert len(rejected) == 2
    collector.status = 200
    assert p.reconcile() == [], "a refusal the event would earn again is not repeated"


# ----------------------------------------------------------------- sessions


def test_hands_a_run_to_the_session_that_last_changed_it_so_its_teardown_reports_it(project):
    p = project()
    p.reconcile()
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    p.reconcile(session_id=OTHER_SESSION)
    p.write_status(phase_status(current_phase="estimate", phases=with_phases(clarify="completed", design="completed")))
    by_first = p.session_end(session_id=SESSION_ID)
    by_other = p.session_end(session_id=OTHER_SESSION)
    assert by_first == [], "the first session no longer owns the run"
    assert summary(by_other) == [("PHASE_COMPLETED", "DESIGN", "SUCCESS")]


def test_transfers_ownership_on_an_edit_inside_the_run_and_leaves_scanned_runs_alone(project, tmp_path):
    p = project()
    sibling = p.root / ".migration" / "0226-1500"
    sibling.mkdir()
    (sibling / ".phase-status.json").write_text(json.dumps(phase_status(migration_id="0226-1500", run_id="5a5a5a5a-1111-4222-8333-444444444444")))
    p.reconcile()
    unchanged = p.post_write(p.run_dir / "preferences.json", session_id=OTHER_SESSION)
    assert unchanged == []
    assert json.loads((sibling / ".telemetry-snapshot.json").read_text())["sessionId"] == SESSION_ID, "a run merely scanned keeps its owner"
    assert p.snapshot()["sessionId"] == OTHER_SESSION
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    assert p.session_end(session_id=SESSION_ID) == []
    assert summary(p.session_end(session_id=OTHER_SESSION)) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")]


def test_a_pathless_reconcile_keeps_the_existing_owner(project):
    p = project()
    p.reconcile()
    assert p.reconcile(session_id=OTHER_SESSION) == []
    assert p.snapshot()["sessionId"] == SESSION_ID


def test_reports_a_phase_that_completes_again_after_a_confirmed_re_entry_reset(project):
    p = project(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    p.reconcile()
    p.write_status(phase_status(current_phase="clarify", phases=with_phases(clarify="pending")))
    reset = p.reconcile()
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    again = p.reconcile()
    assert reset == []
    assert summary(again) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")]


def test_teardown_stays_inside_the_host_budget_and_never_repeats_what_it_attempted(project, collector):
    p = project(phase_status(current_phase="complete", run_mode="decide", phases=all_completed()))
    started = time.time()
    sent = p.session_end()
    elapsed = time.time() - started
    assert len(sent) >= 1
    assert elapsed < 3.0
    assert p.session_end() == []


def test_an_artifact_of_an_unexpected_shape_costs_its_attributes_never_the_event(project):
    # total_models_detected as a string used to raise inside the send pool: the
    # events went out, the snapshot was never written, and every later hook
    # repeated the whole batch.
    p = project(phase_status(current_phase="complete", run_mode="decide", phases=all_completed()), artifacts={
        "gcp-resource-inventory.json": GCP_INVENTORY,
        "ai-workload-profile.json": {"summary": {"ai_source": "openai", "total_models_detected": "2"}},
    })
    first = p.reconcile()
    assert ("PHASE_COMPLETED", "DISCOVER", "SUCCESS") in summary(first) and p.has_snapshot()
    assert p.reconcile() == []


def test_a_service_that_cannot_be_reached_leaves_the_run_unrecorded_until_it_can(project, collector):
    p = project()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        refused = "http://127.0.0.1:%d/v1/plugin-telemetry-event" % probe.getsockname()[1]
    assert p.hook("--reconcile", env={ENDPOINT_ENV: refused}) == []
    assert not p.has_snapshot(), "nothing could have reached the service, so nothing is recorded"
    assert summary(p.reconcile()) == [("PHASE_COMPLETED", "DISCOVER", "SUCCESS"), ("RUN_STARTED", None, None)]


def test_a_corrupt_snapshot_is_rebuilt_without_sending_so_the_run_reports_again(project):
    p = project()
    p.reconcile()
    (p.run_dir / ".telemetry-snapshot.json").write_text("{\"runId\": \"" + RUN_ID[:12], encoding="utf-8")
    assert p.reconcile() == [], "what the corrupt snapshot had reported is unknowable, so nothing is re-sent"
    assert p.snapshot()["phases"] == phase_status()["phases"] and p.snapshot()["runId"] == RUN_ID
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    assert summary(p.reconcile()) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")]


def test_reports_azure_runs_with_their_own_inventory_vocabulary(project):
    # azure discover writes the canonical ARM type under `azure_type`, never azurerm_*.
    p = project(phase_status(owning_skill="AZURE_TO_AWS"), artifacts={"azure-resource-inventory.json": {"resources": [
        {"azure_type": "Microsoft.DocumentDB/databaseAccounts", "name": "db"},
        {"azure_type": "Microsoft.CognitiveServices/accounts", "name": "ai"},
        {"azure_type": "Microsoft.App/containerApps", "name": "api"},
    ]}})
    events = {activity(b).get("phase") or activity(b)["eventName"]: activity(b) for b in p.reconcile()}
    assert events["RUN_STARTED"]["skill"] == "AZURE_TO_AWS"
    assert events["DISCOVER"]["attributes"] == {"sourceProvider": "AZURE", "resourceCount": 3, "hasDatabase": True, "hasAi": True}


def test_a_run_executed_after_a_decide_only_finish_ends_again_under_its_new_run_mode(project):
    decided = phase_status(current_phase="complete", run_mode="decide", phases=with_phases(
        clarify="completed", design="completed", estimate="completed", workshop="completed"))
    p = project(decided)
    first = [activity(b) for b in p.reconcile() if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert [e.get("attributes", {}).get("runMode") for e in first] == ["DECIDE"]
    p.write_status({**decided, "run_mode": "decide_and_execute", "current_phase": "generate",
                    "phases": with_phases(clarify="completed", design="completed", estimate="completed",
                                          workshop="completed", generate="in_progress")})
    assert p.reconcile() == [], "opting in is not yet an ending"
    p.write_status({**decided, "run_mode": "decide_and_execute", "phases": all_completed()})
    again = p.reconcile()
    assert summary(again) == [("PHASE_COMPLETED", "FEEDBACK", "SUCCESS"), ("PHASE_COMPLETED", "GENERATE", "SUCCESS"),
                              ("RUN_COMPLETED", None, "SUCCESS")]
    assert next(activity(b) for b in again if activity(b)["eventName"] == "RUN_COMPLETED")["attributes"]["runMode"] == "DECIDE_AND_EXECUTE"
    assert p.snapshot()["completedRunModes"] == ["DECIDE", "DECIDE_AND_EXECUTE"]
    assert p.reconcile() == [], "the same ending is never reported twice"


def test_an_explicit_execute_request_ends_the_run_only_once_generate_is_completed(project):
    # The skill flips run_mode before loading Generate and leaves current_phase
    # at "complete" from the decision-only finish, so the flip alone is not an ending.
    decided = phase_status(current_phase="complete", run_mode="decide", phases=with_phases(
        clarify="completed", design="completed", estimate="completed", workshop="completed"))
    p = project(decided)
    assert ("RUN_COMPLETED", None, "SUCCESS") in summary(p.reconcile())
    p.write_status({**decided, "run_mode": "decide_and_execute"})
    assert p.reconcile() == [], "run_mode flipped, Generate not yet run: nothing has ended"
    assert p.snapshot()["completedRunModes"] == ["DECIDE"]
    p.write_status({**decided, "run_mode": "decide_and_execute", "phases": all_completed()})
    ended = [activity(b) for b in p.reconcile() if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert [e["attributes"]["runMode"] for e in ended] == ["DECIDE_AND_EXECUTE"]
    assert p.reconcile() == []


def test_reports_an_llm_to_bedrock_run_in_its_dot_directory_at_run_level_only(project):
    # llm-to-bedrock keeps its own thin run state in .migration/.bedrock-<id>/ with
    # phases the model does not know (assess, execute): only run-level events leave.
    p = project(phase_status(migration_id=".bedrock-0226-1430", owning_skill="LLM_TO_BEDROCK", current_phase="execute",
                             phases={"assess": "completed", "execute": "in_progress"}),
                run_name=".bedrock-0226-1430", artifacts={})
    first = p.reconcile()
    assert summary(first) == [("RUN_STARTED", None, None)]
    assert activity(first[0])["skill"] == "LLM_TO_BEDROCK"
    p.write_status(phase_status(migration_id=".bedrock-0226-1430", owning_skill="LLM_TO_BEDROCK", current_phase="complete",
                                phases={"assess": "completed", "execute": "completed"}))
    assert summary(p.reconcile()) == [("RUN_COMPLETED", None, "SUCCESS")]


def test_maps_the_azure_producer_fields_from_the_committed_fixtures(project):
    # The real azure-to-aws fixtures: 30 ARM resources (PostgreSQL, Redis, DocumentDB among
    # them) and an estimate whose baseline is the customer's stated USD 4200.
    fixtures = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform"
    inventory = json.loads((fixtures / "after-discover" / "azure-resource-inventory.json").read_text())
    estimate = json.loads((fixtures / "after-estimate" / "estimation-infra.json").read_text())
    p = project(phase_status(owning_skill="AZURE_TO_AWS", current_phase="complete", run_mode="decide",
                             phases=with_phases(clarify="completed", design="completed", estimate="completed")),
                artifacts={"azure-resource-inventory.json": inventory, "estimation-infra.json": estimate})
    events = {activity(b).get("phase") or activity(b)["eventName"]: activity(b) for b in p.reconcile()}
    discover = events["DISCOVER"]["attributes"]
    assert (discover["sourceProvider"], discover["resourceCount"], discover["hasDatabase"]) == ("AZURE", 30, True)
    estimate_attrs = events["ESTIMATE"]["attributes"]
    assert estimate_attrs["spendBand"] == "FROM_1K_TO_10K"
    assert estimate_attrs["spendBasis"] == "USER_PROVIDED"
    assert estimate_attrs["recommendationOutcome"] == "CONDITIONAL_GO"
    assert "estimateAccuracyBand" not in estimate_attrs, "'as stated by the customer' is not a percentage band"


def test_honours_the_backbone_fallback_when_current_phase_is_absent(project):
    # current_phase is optional in the shared schema; without it gcp-to-aws evaluates
    # the backbone in order and is complete only when every phase, Generate included, is.
    finished = phase_status(run_mode="decide_and_execute", phases=all_completed())
    del finished["current_phase"]
    done = project(finished)
    ended = [activity(b) for b in done.reconcile() if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert [e["attributes"]["runMode"] for e in ended] == ["DECIDE_AND_EXECUTE"]
    assert done.reconcile() == []
    # A decision-only run that omits the field has not ended: Generate stays opt-in.
    decided = phase_status(run_mode="decide", phases=with_phases(clarify="completed", design="completed", estimate="completed"))
    del decided["current_phase"]
    open_run = project(decided, run_name="0226-1500")
    assert ("RUN_COMPLETED", None, "SUCCESS") not in summary(open_run.reconcile())
    assert open_run.snapshot()["completed"] is False


def test_each_run_mode_ends_once_even_across_a_workshop_re_entry(project):
    # heroku's workshop re-entry clears run_mode, resets Generate and reopens the
    # decision gate; the run has already ended under both modes and must not again.
    decided = phase_status(current_phase="complete", run_mode="decide", phases=with_phases(
        clarify="completed", design="completed", estimate="completed", workshop="completed"))
    p = project(decided)
    endings = lambda bodies: [activity(b)["attributes"]["runMode"] for b in bodies if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert endings(p.reconcile()) == ["DECIDE"]
    p.write_status({**decided, "run_mode": "decide_and_execute", "phases": all_completed()})
    assert endings(p.reconcile()) == ["DECIDE_AND_EXECUTE"]
    assert p.snapshot()["completedRunModes"] == ["DECIDE", "DECIDE_AND_EXECUTE"]
    reentered = {**decided, "current_phase": "estimate", "phases": with_phases(
        clarify="completed", design="completed", estimate="completed", workshop="in_progress")}
    del reentered["run_mode"]
    p.write_status(reentered)
    assert endings(p.reconcile()) == []
    p.write_status({**decided, "phases": with_phases(clarify="completed", design="completed", estimate="completed", workshop="completed")})
    assert endings(p.reconcile()) == [], "a second decision-only ending is not reported again"
    p.write_status({**decided, "run_mode": "decide_and_execute", "phases": all_completed()})
    assert endings(p.reconcile()) == [], "nor a second executed one"
    assert p.snapshot()["completedRunModes"] == ["DECIDE", "DECIDE_AND_EXECUTE"]


def test_an_older_snapshot_that_kept_only_the_last_completed_mode_is_honoured(project):
    decided = phase_status(current_phase="complete", run_mode="decide", phases=with_phases(
        clarify="completed", design="completed", estimate="completed", workshop="completed"))
    p = project(decided)
    p.reconcile()
    snapshot = p.snapshot()
    snapshot["completedRunMode"] = snapshot.pop("completedRunModes")[0]  # the shape earlier builds wrote
    (p.run_dir / ".telemetry-snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    assert p.reconcile() == [], "the recorded DECIDE ending is still known"
    p.write_status({**decided, "run_mode": "decide_and_execute", "phases": all_completed()})
    ended = [activity(b)["attributes"]["runMode"] for b in p.reconcile() if activity(b)["eventName"] == "RUN_COMPLETED"]
    assert ended == ["DECIDE_AND_EXECUTE"]
    assert p.snapshot()["completedRunModes"] == ["DECIDE", "DECIDE_AND_EXECUTE"]


def test_reads_the_state_under_the_lock_so_a_stale_reader_cannot_undo_a_newer_report(project, monkeypatch):
    # Two async hooks: the older one has read the state (clarify in_progress) when the
    # newer one completes CLARIFY, reports it and releases the lock; the older one then
    # takes the lock. It must diff against what is on disk now, not what it read.
    import migration

    p = project()
    p.reconcile()
    real_acquire = migration.acquire_lock

    def acquire_after_a_newer_report(run_dir):
        monkeypatch.setattr(migration, "acquire_lock", real_acquire)
        p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
        migration.process_run(run_dir, SESSION_ID, False, p.collector.url, float("inf"), None, "hook")
        return real_acquire(run_dir)

    monkeypatch.setattr(migration, "acquire_lock", acquire_after_a_newer_report)
    before = len(p.collector.received)
    migration.process_run(p.run_dir, SESSION_ID, False, p.collector.url, float("inf"), None, "hook")
    sent = [json.loads(r["body"]) for r in p.collector.received[before:]]
    assert summary(sent) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")], "the newer hook's report, once"
    assert p.snapshot()["phases"]["clarify"] == "completed", "the stale reader did not move the snapshot back"
    assert p.reconcile() == []


def test_reports_a_state_file_written_through_a_shell_command_when_the_bash_hook_fires(project):
    # The agent sometimes writes .phase-status.json with a heredoc instead of the Write
    # tool; the Bash payload carries no file path, so every run under cwd is reconciled.
    p = project()
    bash = lambda command: {"tool_name": "Bash", "tool_input": {"command": command}}
    first = p.hook(payload=bash("cat > .migration/0226-1430/.phase-status.json <<'EOF'\n{...}\nEOF"))
    assert summary(first) == [("PHASE_COMPLETED", "DISCOVER", "SUCCESS"), ("RUN_STARTED", None, None)]
    assert p.hook(payload=bash("git status")) == [], "an unrelated command finds nothing new"


# ---------------------------------------------------------------- attributes


def test_derives_attributes_from_producer_shaped_artifacts_including_the_ai_only_route(project):
    done = phase_status(current_phase="complete", run_mode="decide", phases=all_completed())
    gcp = project(done, artifacts={
        "gcp-resource-inventory.json": GCP_INVENTORY,
        "preferences.json": {"metadata": {"clarify_mode": "wizard", "migration_type": "full"},
                             "design_constraints": {"gcp_monthly_spend": {"value": "$1K-$5K", "chosen_by": "user"}}},
        "estimation-infra.json": {"recommendation": {"outcome": "defer_for_evidence"},
                                  "pricing_source": {"status": "cached", "fallback_staleness": {"is_stale": False}},
                                  "current_costs": {"source": "preferences", "gcp_monthly_spend": 2500}},
    })
    ai_only = project({**done, "initiated_by": "LLM_TO_BEDROCK"}, run_name="0226-1500", artifacts={
        "ai-workload-profile.json": {"summary": {"ai_source": "openai", "total_models_detected": 2}},
        "preferences.json": {"metadata": {"clarify_mode": "fast_path", "migration_type": "ai-only"}},
    })
    g = {activity(b).get("phase") or activity(b)["eventName"]: activity(b) for b in gcp.reconcile()}
    a = {activity(b).get("phase") or activity(b)["eventName"]: activity(b) for b in ai_only.reconcile()}
    assert g["DISCOVER"]["attributes"] == {"sourceProvider": "GCP", "resourceCount": 2, "hasDatabase": True, "hasAi": False}
    assert g["CLARIFY"]["attributes"] == {"sourceProvider": "GCP", "clarifyMode": "WIZARD"}
    assert g["ESTIMATE"]["attributes"] == {"sourceProvider": "GCP", "recommendationOutcome": "DEFER", "pricingSource": "CACHED",
                                           "spendBand": "FROM_1K_TO_10K", "spendBasis": "USER_PROVIDED"}
    assert g["RUN_COMPLETED"]["attributes"] == {"sourceProvider": "GCP", "runMode": "DECIDE"}
    assert a["DISCOVER"]["attributes"] == {"sourceProvider": "OPENAI", "hasAi": True}
    assert a["CLARIFY"]["attributes"] == {"sourceProvider": "OPENAI", "clarifyMode": "AI_ONLY"}
    assert a["RUN_STARTED"]["initiatingSkill"] == "LLM_TO_BEDROCK"


def test_detects_a_heroku_database_from_the_add_on_service(project):
    formation = {"resource_type": "formation", "name": "web"}
    with_db = project(phase_status(owning_skill="HEROKU_TO_AWS"), artifacts={
        "heroku-resource-inventory.json": {"resources": [formation, {"resource_type": "addon", "config": {"addon_service": "heroku-postgresql"}}]}})
    without = project(phase_status(owning_skill="HEROKU_TO_AWS"), run_name="0226-1500", artifacts={
        "heroku-resource-inventory.json": {"resources": [formation, {"resource_type": "addon", "config": {"addon_service": "papertrail"}}]}})
    d = next(activity(b) for b in with_db.reconcile() if activity(b).get("phase") == "DISCOVER")
    n = next(activity(b) for b in without.reconcile() if activity(b).get("phase") == "DISCOVER")
    assert d["attributes"] == {"sourceProvider": "HEROKU", "resourceCount": 2, "hasDatabase": True, "hasAi": False}
    assert n["attributes"]["hasDatabase"] is False


def test_reads_heroku_clarify_answers_from_preferences_global(project):
    preferences = json.loads((PLUGIN_ROOT / "fixtures" / "heroku-workshop" / "seed" / "preferences.json").read_text())
    p = project(phase_status(owning_skill="HEROKU_TO_AWS", current_phase="design", phases=with_phases(clarify="completed")),
                artifacts={"heroku-resource-inventory.json": {"resources": []}, "preferences.json": preferences})
    clarify = next(activity(b) for b in p.reconcile() if activity(b).get("phase") == "CLARIFY")["attributes"]
    assert {k: clarify.get(k) for k in ("compliance", "availability", "targetRegion", "computePosture")} == {
        "compliance": ["NONE"], "availability": "SINGLE_AZ", "targetRegion": "US_EAST_1", "computePosture": "ELASTIC_BEANSTALK"}


def test_maps_the_gcp_clarify_answers_the_producer_writes(project):
    def clarified(design_constraints, run_name):
        return project(phase_status(current_phase="design", phases=with_phases(clarify="completed")), run_name=run_name,
                       artifacts={"gcp-resource-inventory.json": GCP_INVENTORY, "preferences.json": {"design_constraints": design_constraints}})
    explicit = clarified({"compliance": {"value": []}, "database_traffic": {"value": "write-heavy-global"}}, "0226-1501")
    absent = clarified({"database_traffic": {"value": "rapidly-growing"}}, "0226-1502")
    unsupported = clarified({"compliance": {"value": ["iso-27001"]}}, "0226-1503")
    attrs_of = lambda p: next(activity(b) for b in p.reconcile() if activity(b).get("phase") == "CLARIFY")["attributes"]
    a, b, c = attrs_of(explicit), attrs_of(absent), attrs_of(unsupported)
    assert (a.get("compliance"), a.get("databaseTraffic")) == (["NONE"], "WRITE_HEAVY")
    assert (b.get("compliance"), b.get("databaseTraffic")) == (None, None)
    assert c.get("compliance") is None


def test_drops_a_generation_tier_once_a_confirmed_re_entry_resets_generate(project):
    p = project(phase_status(current_phase="complete", run_mode="execute", phases=all_completed()), artifacts={
        "gcp-resource-inventory.json": GCP_INVENTORY,
        "generation-infra.json": {"complexity_tier": "small"},
        "migration-preview.json": {"complexity_signal": "likely_simple"},
    })
    first = {activity(b).get("phase"): activity(b) for b in p.reconcile()}
    (p.run_dir / "migration-preview.json").write_text(json.dumps({"complexity_signal": "complex"}))
    p.write_status(phase_status(current_phase="estimate", phases=with_phases(clarify="completed", design="pending")))
    p.reconcile()
    p.write_status(phase_status(current_phase="estimate", phases=with_phases(clarify="completed", design="completed")))
    redesign = next(activity(b) for b in p.reconcile() if activity(b).get("phase") == "DESIGN")
    assert first["DESIGN"]["attributes"]["complexityTier"] == "SMALL"
    assert redesign["attributes"]["complexityTier"] == "LARGE"


def test_reports_the_provenance_of_a_preferences_sourced_spend_figure(project):
    def estimated(spend, run_name):
        return project(phase_status(current_phase="workshop", phases=with_phases(clarify="completed", design="completed", estimate="completed")),
                       run_name=run_name, artifacts={
                           "gcp-resource-inventory.json": GCP_INVENTORY,
                           "preferences.json": {"design_constraints": {"gcp_monthly_spend": spend}},
                           "estimation-infra.json": {"current_costs": {"source": "preferences", "gcp_monthly": 3000}}})
    cases = {
        "default": estimated({"value": "$1K-$5K", "chosen_by": "default", "source": "default:Q3"}, "0226-1511"),
        "user": estimated({"value": "$1K-$5K", "chosen_by": "user"}, "0226-1512"),
        "extracted": estimated({"value": "$1K-$5K", "chosen_by": "extracted", "source": "billing:monthly_total=$3000"}, "0226-1513"),
        "unknown": estimated({"value": "$1K-$5K"}, "0226-1514"),
    }
    got = {}
    for name, p in cases.items():
        attributes = next(activity(b) for b in p.reconcile() if activity(b).get("phase") == "ESTIMATE")["attributes"]
        got[name] = (attributes.get("spendBand"), attributes.get("spendBasis"))
    assert got == {
        "default": ("FROM_1K_TO_10K", "DEFAULTED"),
        "user": ("FROM_1K_TO_10K", "USER_PROVIDED"),
        "extracted": ("FROM_1K_TO_10K", "BILLING_DATA"),
        "unknown": (None, None),
    }


def test_derives_the_enriched_estimate_attributes(project):
    p = project(phase_status(current_phase="workshop", phases=with_phases(clarify="completed", design="completed", estimate="completed")), artifacts={
        "gcp-resource-inventory.json": {"resources": GCP_INVENTORY["resources"], "summary": {"classification_coverage": "97%"}},
        "estimation-infra.json": {
            "recommendation": {"outcome": "go", "confidence": "high"},
            "current_costs": {"source": "billing_data", "gcp_monthly": 1200, "accuracy": "±5-10%"},
            "migration_cost_considerations": {"billing_data_available": True},
            "projected_costs": {"aws_monthly_optimized": 62.4, "aws_monthly_balanced": 85, "aws_monthly_premium": "110"},
            "estimation_summary": {"complexity_tier": "medium"},
        },
    })
    by_phase = {activity(b).get("phase"): activity(b) for b in p.reconcile()}
    assert by_phase["DISCOVER"]["attributes"]["classificationCoverage"] == "NEAR_COMPLETE"
    assert by_phase["ESTIMATE"]["attributes"] == {
        "sourceProvider": "GCP", "recommendationOutcome": "GO", "recommendationConfidence": "HIGH",
        "estimateAccuracyBand": "HIGH", "billingDataAvailable": True,
        "awsProjectedCostOptimized": 62, "awsProjectedCostBalanced": 85, "awsProjectedCostPremium": 110,
        "spendBand": "FROM_1K_TO_10K", "spendBasis": "BILLING_DATA", "complexityTier": "MEDIUM",
    }


# -------------------------------------------------------------------- gates


def test_reports_a_failed_gate_once_per_phase_and_the_later_pass_as_its_own_event(project):
    p = project()
    p.write_gates({"clarify": {"reason": "missing", "field": "preferences.json", "at": "2026-02-26T15:40:00Z"}})
    first = p.reconcile()
    p.write_gates({"clarify": {"reason": "invalid", "field": "preferences.json", "at": "2026-02-26T15:41:00Z"}})
    repeat = p.reconcile()
    p.write_status(phase_status(current_phase="design", phases=with_phases(clarify="completed")))
    passed = p.reconcile()
    gate = next(activity(b) for b in first if activity(b)["eventName"] == "GATE_FAILED")
    assert (gate["phase"], gate["status"], gate["attributes"]["failureReason"]) == ("CLARIFY", "FAILED", "MISSING")
    assert repeat == [], "a repeat failure of the same phase is not a new event"
    assert summary(passed) == [("PHASE_COMPLETED", "CLARIFY", "SUCCESS")]
    assert p.snapshot()["gateFailures"] == ["CLARIFY"]


def test_ignores_malformed_gate_entries_and_unknown_reasons_without_consuming_the_phase(project):
    p = project()
    p.write_gates({"clarify": None, "design": {"reason": "__proto__", "at": "x"}, "nonsense": {"reason": "missing"}, "estimate": ["bad"]})
    first = [activity(b) for b in p.reconcile() if activity(b)["eventName"] == "GATE_FAILED"]
    p.write_gates({"clarify": {"reason": "missing", "field": "preferences.json", "at": "x"}, "design": {"reason": "__proto__", "at": "x"}})
    second = [activity(b) for b in p.reconcile() if activity(b)["eventName"] == "GATE_FAILED"]
    assert [(a["phase"], (a.get("attributes") or {}).get("failureReason")) for a in first] == [("DESIGN", None)]
    assert [(a["phase"], a["attributes"]["failureReason"]) for a in second] == [("CLARIFY", "MISSING")]


def test_carries_the_complexity_tier_on_a_design_onward_gate_failure(project):
    p = project(phase_status(current_phase="design", phases=with_phases(clarify="completed")),
                artifacts={"gcp-resource-inventory.json": GCP_INVENTORY, "migration-preview.json": {"complexity_signal": "complex"}})
    p.write_gates({"design": {"reason": "missing", "field": "aws-design.json", "at": "x"}})
    gate = next(activity(b) for b in p.reconcile() if activity(b)["eventName"] == "GATE_FAILED")
    assert gate["attributes"]["complexityTier"] == "LARGE"


def test_re_sends_a_held_gate_failure_alone(project, collector):
    p = project()
    p.reconcile()
    p.write_gates({"design": {"reason": "invalid", "field": "aws-design.json", "at": "x"}})
    collector.status = 403
    held = p.reconcile()
    collector.status = 200
    retried = p.reconcile()
    assert summary(held) == [("GATE_FAILED", "DESIGN", "FAILED")]
    assert summary(retried) == [("GATE_FAILED", "DESIGN", "FAILED")]
    assert p.snapshot()["gateFailures"] == ["DESIGN"]
    assert p.reconcile() == []


# ------------------------------------------------------------ registration


def test_registers_the_three_telemetry_hooks_through_the_portable_interpreter_chain():
    hooks = json.loads((PLUGIN_ROOT / "com.anthropic.claude-code" / "hooks" / "hooks.json").read_text())["hooks"]
    modes = {"PostToolUse": "", "Stop": " --reconcile", "SessionEnd": " --session-end"}
    for event, flag in modes.items():
        commands = [h["command"] for group in hooks[event] for h in group["hooks"] if "migration.py" in h["command"]]
        assert len(commands) == 1, "%s registers the migration emitter once" % event
        assert commands[0].startswith("sh -c 'python3 \"$0\" \"$@\"")
        assert commands[0].endswith('"${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/metric_emission/migration.py"' + flag)
    post_write = next(g for g in hooks["PostToolUse"] if g.get("matcher") == "Write|Edit|Bash")
    assert post_write["hooks"][0]["async"] is True, "post-write runs off the turn"
    # Bash because the agent sometimes writes a state file through a heredoc rather than the Write tool.
    assert "timeout" not in hooks["SessionEnd"][0]["hooks"][0], "the sweep budgets itself to the default SessionEnd budget"


def test_wires_the_cursor_manifest_to_cursor_hooks_that_reach_the_emitter():
    manifest = json.loads((PLUGIN_ROOT / ".cursor-plugin" / "plugin.json").read_text())
    hooks = json.loads((PLUGIN_ROOT / manifest["hooks"]).read_text())["hooks"]
    assert set(hooks) == {"afterFileEdit", "afterShellExecution", "stop", "sessionEnd"}
    for event, entries in hooks.items():
        for entry in entries:
            assert '"${CURSOR_PLUGIN_ROOT}/scripts/telemetry/metric_emission/migration.py"' in entry["command"]
            assert entry["command"].endswith("--session-end" if event == "sessionEnd" else "--reconcile")



def test_the_registered_stop_command_runs_the_emitter_through_the_shell_as_the_host_does(project, collector):
    # Arrange: the exact command string from hooks.json, with the plugin root the host would supply
    p = project()
    hooks = json.loads((PLUGIN_ROOT / "com.anthropic.claude-code" / "hooks" / "hooks.json").read_text())["hooks"]
    command = next(h["command"] for g in hooks["Stop"] for h in g["hooks"] if "migration.py" in h["command"])
    env = {"HOME": str(p.home), "USERPROFILE": str(p.home), "PATH": "/usr/bin:/bin:" + os.path.dirname(sys.executable),
           "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), ENDPOINT_ENV: collector.url, "CLAUDECODE": "1"}

    # Act
    result = subprocess.run(  # nosec B602 — the registered command string is the thing under test
        command, shell=True, input=json.dumps({"session_id": SESSION_ID, "cwd": str(p.root)}),
        capture_output=True, text=True, env=env, cwd=str(p.root),
    )

    # Assert
    assert result.returncode == 0
    assert summary([json.loads(r["body"]) for r in collector.received]) == [
        ("PHASE_COMPLETED", "DISCOVER", "SUCCESS"), ("RUN_STARTED", None, None)]
