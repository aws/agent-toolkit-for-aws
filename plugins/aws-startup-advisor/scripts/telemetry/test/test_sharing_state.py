"""Preference transitions, stale setup completion, and process serialization."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import record
from conftest import run


def save_raw(home, data):
    record.state_dir().mkdir(parents=True, exist_ok=True)
    record.state_path().write_text(json.dumps(data), encoding="utf-8")


def test_pending_clears_old_account_and_does_not_authorize_reporting(home):
    first = record.begin_account("one", 3)
    accepted = record.complete_account(first, "123456789012")
    pending = record.begin_account("two", 3)
    assert pending["installId"] == accepted["installId"]
    assert pending["awsProfile"] == "two"
    assert "expectedAwsAccountId" not in pending
    assert record.consent_status() == record.PENDING
    assert record.sharing_mode(pending) == record.AWS_ACCOUNT
    assert record.reporting_state() is None
    assert not record.is_accepted()


@pytest.mark.parametrize("choice", ("anonymous", "opt_out", "account"))
def test_late_account_completion_cannot_overwrite_a_new_choice(home, choice):
    pending = record.begin_account("first", 3)
    if choice == "anonymous":
        current = record.write_anonymous()
    elif choice == "opt_out":
        current = record.write_state(record.OPT_OUT)
    else:
        current = record.begin_account("first", 3)
        # Even identical account/profile selections have separate setup attempts.
        assert current["setupId"] != pending["setupId"]
    assert record.complete_account(pending, "123456789012") is None
    assert record.read_state() == current


@pytest.mark.parametrize("status", (record.ACCEPTED, record.OPT_OUT))
def test_legacy_writers_clear_account_fields_and_keep_install_id(home, status):
    pending = record.begin_account("work", 3)
    accepted = record.complete_account(pending, "123456789012")
    written = record.write_state(status)
    assert written["installId"] == accepted["installId"]
    assert "awsProfile" not in written
    assert "expectedAwsAccountId" not in written
    assert "setupId" not in written
    assert record.sharing_mode(written) == (
        record.ANONYMOUS if status == record.ACCEPTED else None
    )


def test_legacy_missing_mode_and_version_means_anonymous_notice_one(home):
    written = record.write_anonymous()
    del written["identityMode"]
    del written["noticeVersion"]
    save_raw(home, written)
    assert record.sharing_mode(record.reporting_state()) == record.ANONYMOUS
    assert record.accepted_notice_version() == 1


@pytest.mark.parametrize("change", (
    {"identityMode": "unknown"},
    {"identityMode": None},
    {"noticeVersion": True},
    {"noticeVersion": "3"},
    {"noticeVersion": 0},
    {"noticeVersion": -1},
    {"awsProfile": "work"},
    {"expectedAwsAccountId": "123456789012"},
    {"awsIdentityProof": {}},
    {"secretAccessKey": "never-store-this"},
))
def test_invalid_or_mixed_anonymous_record_never_authorizes_reporting(home, change):
    written = record.write_anonymous()
    written.update(change)
    save_raw(home, written)
    assert record.read_state() is None
    assert record.reporting_state() is None


@pytest.mark.parametrize("field, value", (
    ("expectedAwsAccountId", None),
    ("expectedAwsAccountId", "123"),
    ("expectedAwsAccountId", 123456789012),
    ("awsProfile", ""),
    ("awsProfile", "x\nsecret"),
    ("awsProfile", None),
    ("noticeVersion", None),
    ("setupId", "00000000-0000-0000-0000-000000000000"),
))
def test_invalid_accepted_account_state_fails_closed(home, field, value):
    accepted = record.complete_account(record.begin_account(None, 3), "123456789012")
    accepted[field] = value
    save_raw(home, accepted)
    assert record.reporting_state() is None


def test_interrupted_replace_keeps_previous_complete_record_and_cleans_temp(home, monkeypatch):
    existing = record.write_anonymous()

    def fail_replace(*args):
        raise OSError("synthetic interrupted rename")

    monkeypatch.setattr(record.os, "replace", fail_replace)
    with pytest.raises(OSError):
        record.begin_account("work", 3)
    assert record.read_state() == existing
    assert list(record.state_dir().iterdir()) == [record.state_path()]


@pytest.mark.parametrize("shared", [False, True])
def test_state_lock_timeout_is_bounded_and_released_after_process_death(home, shared):
    module_path = Path(record.__file__).parent
    code = (
        "import sys,time; sys.path.insert(0,sys.argv[1]); import record; "
        "guard=record.state_guard(shared=sys.argv[2]=='True'); guard.__enter__(); "
        "print('locked',flush=True); time.sleep(10)"
    )
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(module_path), str(shared)],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        started = time.monotonic()
        with pytest.raises(record.StateBusyError):
            with record.state_guard(timeout=0.04):
                pytest.fail("concurrent lock was admitted")
        assert time.monotonic() - started < 0.3
    finally:
        proc.kill()
        proc.wait(timeout=2)
        proc.stdout.close()
    # No manual stale-lock recovery is needed after a crash.
    with record.state_guard(timeout=0.1):
        assert record.read_state() is None
    record.write_anonymous()


def test_final_submission_guard_excludes_concurrent_writer(home):
    record.write_anonymous()
    module_path = Path(record.__file__).parent
    code = (
        "import sys; sys.path.insert(0,sys.argv[1]); import record; "
        "record.write_state(record.OPT_OUT)"
    )
    with record.state_guard(shared=True):
        proc = subprocess.run(
            [sys.executable, "-c", code, str(module_path)],
            env={"HOME": str(home), "USERPROFILE": str(home)},
            capture_output=True, text=True, timeout=2,
        )
        assert proc.returncode != 0
        assert "SHARING_STATE_BUSY" in proc.stderr
        assert record.is_accepted()
    record.write_state(record.OPT_OUT)
    assert not record.is_accepted()


@pytest.mark.parametrize("holder_shared", [False, True])
@pytest.mark.parametrize("contender_shared", [False, True])
def test_shared_submissions_and_writers_coordinate_across_processes(home, holder_shared, contender_shared):
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import record
try:
    with record.state_guard(timeout=.04, shared=sys.argv[2]=='True'):
        print('acquired')
except record.StateBusyError:
    print('busy')
"""
    with record.state_guard(shared=holder_shared):
        contender = subprocess.run(
            [sys.executable, "-c", code, str(Path(record.__file__).parent), str(contender_shared)],
            env={"HOME": str(home), "USERPROFILE": str(home)},
            capture_output=True, text=True, timeout=2,
        )
    assert contender.returncode == 0, contender.stderr
    expected = "acquired" if holder_shared and contender_shared else "busy"
    assert contender.stdout.strip() == expected
    assert not contender.stderr


def test_write_permissions_keep_preference_file_private(home):
    record.write_anonymous()
    if os.name != "nt":
        assert record.state_path().stat().st_mode & 0o777 == 0o600


def test_recovery_pauses_reporting_without_changing_account_choice(home):
    selected = record.complete_account(record.begin_account("work", 3), "123456789012")
    paused = record.mark_recovery(selected, "SETUP_REQUIRED", "ACCOUNT_CHANGED")
    assert paused == {**selected, "recoveryStatus": "SETUP_REQUIRED", "recoveryReason": "ACCOUNT_CHANGED"}
    assert record.read_state() == paused
    assert record.reporting_state() is None
    assert record.sharing_mode(paused) == record.AWS_ACCOUNT
    assert not record.is_accepted()
    renewed = record.complete_account(record.begin_account("work", 3), "987654321098")
    assert "recoveryStatus" not in renewed
    assert "recoveryReason" not in renewed
    assert record.reporting_state() == renewed


def test_late_recovery_does_not_overwrite_opt_out(home):
    selected = record.complete_account(record.begin_account(None, 3), "123456789012")
    opted_out = record.write_state(record.OPT_OUT)
    assert record.mark_recovery(selected, "SIGN_IN_REQUIRED", "SIGN_IN_REQUIRED") is None
    assert record.read_state() == opted_out


@pytest.mark.parametrize("status,reason", (
    ("SETUP_REQUIRED", "unbounded vendor error"),
    ("SIGN_IN_REQUIRED", "ACCOUNT_CHANGED"),
    ("unknown", "ACCOUNT_CHANGED"),
))
def test_recovery_rejects_unbounded_or_conflicting_results(home, status, reason):
    selected = record.complete_account(record.begin_account(None, 3), "123456789012")
    with pytest.raises(ValueError):
        record.mark_recovery(selected, status, reason)
    assert record.reporting_state() == selected


def test_recovery_metadata_cannot_attach_to_anonymous_record(home):
    selected = record.write_anonymous()
    with pytest.raises(ValueError):
        record.mark_recovery(selected, "SETUP_REQUIRED", "ACCOUNT_CHANGED")
    selected.update(recoveryStatus="SETUP_REQUIRED", recoveryReason="ACCOUNT_CHANGED")
    save_raw(home, selected)
    assert record.read_state() is None


def test_repairing_invalid_choice_preserves_valid_install_id(home):
    selected = record.write_anonymous()
    selected["identityMode"] = "invalid"
    save_raw(home, selected)
    assert record.read_state() is None
    assert record.write_state(record.OPT_OUT)["installId"] == selected["installId"]


def test_duplicate_fields_are_not_treated_as_a_valid_choice(home):
    selected = record.write_anonymous()
    record.state_path().write_text(
        '{"installId":%s,"consentStatus":"OPT_OUT","consentStatus":"ACCEPTED"}'
        % json.dumps(selected["installId"]), encoding="utf-8",
    )
    assert record.read_state() is None
    assert not record.is_accepted()


def test_install_id_with_trailing_newline_is_invalid(home):
    selected = record.write_anonymous()
    selected["installId"] += "\n"
    save_raw(home, selected)
    assert not record.is_accepted()


def test_documented_hand_edit_opt_out_clears_account_for_readers_and_never_prompts(home):
    accepted = record.complete_account(record.begin_account("work", 3), "123456789012")
    accepted.update(recoveryStatus="SETUP_REQUIRED", recoveryReason="ACCOUNT_CHANGED")
    accepted["consentStatus"] = record.OPT_OUT
    save_raw(home, accepted)
    assert record.read_state() == {
        "installId": accepted["installId"], "consentStatus": record.OPT_OUT, "noticeVersion": 3,
    }
    assert record.sharing_mode(record.read_state()) is None
    assert record.reporting_state() is None
    assert run("consent/session_start.py", home=home).stdout == ""
