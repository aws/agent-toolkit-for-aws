#!/usr/bin/env python3
"""The consent record: one reader, one writer, one source of truth.

    ~/.aws-startup-advisor/plugin-telemetry.json
    {"installId": "<uuid>", "consentStatus": "ACCEPTED" | "PENDING" | "OPT_OUT", ...}

`noticeVersion` is the notice the answer was given to; a legacy anonymous record
without one answered version 1. That file is the only thing that decides whether telemetry may be emitted. There
is no environment variable, so a user cannot end up opted out according to their
shell and opted in according to their disk.

Opting out is a change to that file, and the notice says so in those words, so a
hand-edited record is a supported input and not a corrupt one. `opt_out.py` does
the same edit in one step and keeps the install ID, which a hand-edit cannot.

Fail-closed on read, fail-loud on write. A missing, unreadable or schema-invalid
record reads as *no consent*, never as acceptance. Writes raise, so `accept.py`
cannot report success it did not achieve.

`notice.py` owns the wording and knows nothing about any of this; `disclaimer()`
is the seam between the two.
"""

import errno
import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notice  # noqa: E402  (path set above so this resolves in-plugin)

STATE_DIR_NAME = ".aws-startup-advisor"
STATE_FILE_NAME = "plugin-telemetry.json"

# Only ACCEPTED permits emitting anything. A pending account setup is not consent.
ACCEPTED = "ACCEPTED"
OPT_OUT = "OPT_OUT"
PENDING = "PENDING"
AWS_ACCOUNT = "AWS_ACCOUNT"
ANONYMOUS = "ANONYMOUS"

VALID_STATUSES = (ACCEPTED, OPT_OUT, PENDING)
_ACCOUNT_PATTERN = re.compile(r"[0-9]{12}\Z")
_STATE_KEYS = frozenset((
    "installId", "consentStatus", "noticeVersion", "identityMode",
    "awsProfile", "expectedAwsAccountId", "setupId", "recoveryStatus", "recoveryReason",
))
_RECOVERY_REASONS = {
    "SIGN_IN_REQUIRED": frozenset(("CREDENTIALS_UNAVAILABLE", "SIGN_IN_REQUIRED")),
    "SETUP_REQUIRED": frozenset((
        "ACCOUNT_CHANGED", "ACCOUNT_MISMATCH", "ACCOUNT_SELECTION_REQUIRED", "ACCOUNT_REPORTING_REQUIRED",
        "INVALID_ACCOUNT", "INVALID_PROFILE", "NOTICE_VERSION_REQUIRED",
        "NOTICE_RENEWAL_REQUIRED",
    )),
}
MAX_STATE_BYTES = 8192
LOCK_FILE_NAME = ".aws-startup-advisor-telemetry.lock"

# The service's UUID shape, from model/types/scalars.smithy. installId is sent
# verbatim as a @required UUID, so a record holding anything else is unusable.
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# The record as a human should see it: `~`, not an expanded home directory.
DISPLAY_STATE_PATH = "~/%s/%s" % (STATE_DIR_NAME, STATE_FILE_NAME)

# The opt-out the notice names: a config setting, not a command. It is prose, so
# it wraps; it names no absolute install path; and it needs no Python.
OPT_OUT_INSTRUCTION = 'setting "consentStatus" to "%s" in %s' % (
    OPT_OUT,
    DISPLAY_STATE_PATH,
)

# The one-step equivalent, for a human reading script output rather than the
# notice. It preserves the install ID, which a hand-edit cannot. `py -3` on
# Windows, where python3 is usually not on PATH at all.
OPT_OUT_SCRIPT = Path(__file__).resolve().parent / "opt_out.py"
INTERPRETER = "py -3" if os.name == "nt" else "python3"
OPT_OUT_COMMAND = '%s "%s"' % (INTERPRETER, OPT_OUT_SCRIPT)


def disclaimer():
    """The notice, with the opt-out mechanism filled in."""
    return notice.render(opt_out=OPT_OUT_INSTRUCTION)


def opt_out_help():
    """The copy-pasteable opt-out, for a human reading script output."""
    return "\n".join(
        [
            "To opt out later, run:",
            "  %s" % OPT_OUT_COMMAND,
            'Or edit %s by hand and set "consentStatus" to "%s".'
            % (state_path(), OPT_OUT),
            "That file is the only thing that decides whether anything is sent.",
            "Opting out disables no plugin features.",
        ]
    )


def state_dir():
    return Path.home() / STATE_DIR_NAME


def state_path():
    return state_dir() / STATE_FILE_NAME


def _valid_install_id(value):
    return isinstance(value, str) and bool(_UUID_PATTERN.fullmatch(value))


def normalize_install_id(value):
    """Canonical wire/comparison spelling, without rewriting the user's record."""
    return value.lower() if _valid_install_id(value) else None


def _valid_notice_version(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _valid_profile(value):
    return (
        isinstance(value, str) and bool(value.strip()) and len(value) <= 256
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _valid_state(data):
    if not isinstance(data, dict) or not set(data).issubset(_STATE_KEYS):
        return False
    status = data.get("consentStatus")
    if status not in VALID_STATUSES:
        return False
    if "noticeVersion" in data and not _valid_notice_version(data["noticeVersion"]):
        return False
    recovery_keys = {"recoveryStatus", "recoveryReason"}.intersection(data)
    if recovery_keys:
        recovery_status = data.get("recoveryStatus")
        if (
            status != ACCEPTED or data.get("identityMode") != AWS_ACCOUNT
            or recovery_keys != {"recoveryStatus", "recoveryReason"}
            or not isinstance(recovery_status, str)
            or not isinstance(data.get("recoveryReason"), str)
            or data["recoveryReason"] not in _RECOVERY_REASONS.get(recovery_status, ())
        ):
            return False
    if status == OPT_OUT:
        # A user can opt out by writing this one field by hand, without a UUID.
        return not any(key in data for key in (
            "identityMode", "awsProfile", "expectedAwsAccountId", "setupId",
        ))
    if not _valid_install_id(data.get("installId")):
        return False
    mode = data.get("identityMode")
    if mode is None and "identityMode" not in data:
        # Records written before account sharing remain anonymous. Their
        # absent notice version means version 1, rather than the current notice.
        return status == ACCEPTED and not any(key in data for key in (
            "awsProfile", "expectedAwsAccountId", "setupId",
        ))
    if mode not in (ANONYMOUS, AWS_ACCOUNT) or "noticeVersion" not in data:
        return False
    if mode == ANONYMOUS:
        return status == ACCEPTED and not any(key in data for key in (
            "awsProfile", "expectedAwsAccountId", "setupId",
        ))
    if "awsProfile" in data and not _valid_profile(data["awsProfile"]):
        return False
    if status == PENDING:
        return (
            "expectedAwsAccountId" not in data
            and _valid_install_id(data.get("setupId"))
        )
    return (
        "setupId" not in data and isinstance(data.get("expectedAwsAccountId"), str)
        and bool(_ACCOUNT_PATTERN.fullmatch(data["expectedAwsAccountId"]))
    )


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_SHARING_FIELD")
        result[key] = value
    return result


def _read_document():
    """Read bounded JSON without treating an ambiguous object as a choice."""
    try:
        with open(state_path(), "r", encoding="utf-8-sig") as handle:
            body = handle.read(MAX_STATE_BYTES + 1)
        if len(body) > MAX_STATE_BYTES:
            return None
        data = json.loads(body, object_pairs_hook=_unique_json_object)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_state():
    """The record, or None if absent, unparseable, or invalid.

    In order: the file exists, parses as JSON, is an object, and carries an allowed
    `consentStatus`. Every caller has to treat "cannot establish consent" and "no
    consent" identically, so failure is None rather than an exception.

    `installId` is required only when the status is ACCEPTED, because that is the
    only status that sends anything and it is sent verbatim as a @required UUID.
    The notice tells the user to opt out by setting `consentStatus` to OPT_OUT in
    this file; demanding a UUID they have no way to invent would make that
    instruction produce a record we then read as corrupt, and the notice would be
    raised at them again next session.
    """
    # utf-8-sig, not utf-8: the notice tells the user to edit this file, and a
    # Windows editor adds a BOM that json.load rejects. Reading that as "nothing
    # recorded" would raise the notice again at someone who just did what it asked.
    # It reads a BOM-less file identically, so this costs nothing.
    data = _read_document()
    if data and data.get("consentStatus") == OPT_OUT:
        # The approved notice tells a user to edit only consentStatus. That
        # documented opt-out must work even if account-selection fields remain
        # on disk. No identity or setup metadata is returned to any caller.
        safe = {"consentStatus": OPT_OUT}
        if _valid_install_id(data.get("installId")):
            safe["installId"] = data["installId"]
        if _valid_notice_version(data.get("noticeVersion")):
            safe["noticeVersion"] = data["noticeVersion"]
        return safe
    return data if _valid_state(data) else None


def sharing_mode(state):
    """The validated choice, with legacy accepted records treated as anonymous."""
    if not _valid_state(state) or state["consentStatus"] == OPT_OUT:
        return None
    return state.get("identityMode", ANONYMOUS)


def reporting_state():
    """One valid accepted snapshot; notice policy is checked by the sender."""
    state = read_state()
    return state if (
        state and state["consentStatus"] == ACCEPTED and "recoveryStatus" not in state
    ) else None


def consent_status():
    """'ACCEPTED', 'PENDING', 'OPT_OUT', or None for invalid/missing state."""
    state = read_state()
    return state["consentStatus"] if state else None


def is_accepted():
    """The single gate every telemetry path must call.

    Deliberately not `!= OPT_OUT`: a missing or corrupt record must block too.
    """
    return reporting_state() is not None


def accepted_notice_version():
    """The notice version an ACCEPTED answer covers, or 0 when nothing is accepted."""
    state = read_state()
    if not state or state["consentStatus"] != ACCEPTED:
        return 0
    return state.get("noticeVersion", 1)


class StateBusyError(OSError):
    """Another preference change or submission holds the local record lock."""


@contextmanager
def state_guard(timeout=0.25, *, shared=False):
    """Exclude preference writers while allowing simultaneous shared submissions.

    The stable lock inode contains no preferences. OS locks are released on
    process exit, including a killed credential worker. Never unlink the lock
    file: another process may already be waiting on that same inode. Writers
    keep the exclusive default; senders hold a shared lock from their final
    consent check through submission. Acquisition always has a bounded wait.
    """
    timeout = max(0.0, float(timeout))
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(Path.home() / LOCK_FILE_NAME), flags, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes

            # CRT _locking modes do not offer shared locks. LockFileEx does,
            # including on an empty file, and coordinates separate processes.
            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped),
            ]
            kernel.LockFileEx.restype = wintypes.BOOL
            kernel.UnlockFileEx.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, ctypes.POINTER(Overlapped),
            ]
            kernel.UnlockFileEx.restype = wintypes.BOOL
            handle = msvcrt.get_osfhandle(fd)
            overlapped = Overlapped()
            lock_flags = 0x1 | (0 if shared else 0x2)  # fail immediately; exclusive

            def lock():
                if not kernel.LockFileEx(handle, lock_flags, 0, 1, 0, ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())

            def unlock():
                if not kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
        else:
            import fcntl

            def lock():
                mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                fcntl.flock(fd, mode | fcntl.LOCK_NB)

            def unlock():
                fcntl.flock(fd, fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                lock()
                acquired = True
                break
            except OSError as error:
                if os.name == "nt":
                    if error.winerror != 33:  # ERROR_LOCK_VIOLATION
                        raise
                elif error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StateBusyError("SHARING_STATE_BUSY") from None
                time.sleep(min(0.01, remaining))
        yield
    finally:
        try:
            if acquired:
                unlock()
        finally:
            os.close(fd)


def _new_record(status, notice_version):
    if not _valid_notice_version(notice_version):
        raise ValueError("INVALID_NOTICE_VERSION")

    # A malformed sharing choice cannot authorize reporting, but a valid
    # installation UUID in it still identifies this same installation.
    existing = _read_document() or {}
    install_id = existing.get("installId")
    if not _valid_install_id(install_id):
        install_id = str(uuid.uuid4())
    return {"installId": install_id, "consentStatus": status, "noticeVersion": notice_version}


def _save_record(record):
    if not _valid_state(record):
        raise ValueError("INVALID_SHARING_STATE")
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)

    # Renamed into place from the same directory, so the replace is atomic.
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(directory),
        prefix=STATE_FILE_NAME + ".",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, str(state_path()))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise

    return record


def write_anonymous(notice_version=None):
    """Accept anonymous sharing and clear all account-selection fields."""
    if notice_version is None:
        notice_version = notice.NOTICE_VERSION
    with state_guard():
        written = _new_record(ACCEPTED, notice_version)
        written["identityMode"] = ANONYMOUS
        return _save_record(written)


def write_state(status):
    """Legacy commands explicitly choose anonymous sharing or opt out."""
    if status == ACCEPTED:
        return write_anonymous()
    if status != OPT_OUT:
        raise ValueError("consentStatus must be ACCEPTED or OPT_OUT")
    with state_guard():
        return _save_record(_new_record(OPT_OUT, notice.NOTICE_VERSION))


def begin_account(profile_name=None, notice_version=None):
    """Start explicit account setup, clearing the old expected account first."""
    if profile_name is not None and not _valid_profile(profile_name):
        raise ValueError("INVALID_PROFILE")
    if notice_version is None:
        raise ValueError("NOTICE_VERSION_REQUIRED")
    with state_guard():
        written = _new_record(PENDING, notice_version)
        written.update(identityMode=AWS_ACCOUNT, setupId=str(uuid.uuid4()))
        if profile_name is not None:
            written["awsProfile"] = profile_name
        return _save_record(written)


def complete_account(pending_state, account_id):
    """Accept the still-current setup, or return None if the choice changed."""
    if not isinstance(account_id, str) or not _ACCOUNT_PATTERN.fullmatch(account_id):
        raise ValueError("INVALID_ACCOUNT")
    if not _valid_state(pending_state) or pending_state["consentStatus"] != PENDING:
        raise ValueError("INVALID_PENDING_STATE")
    with state_guard():
        if read_state() != pending_state:
            return None
        written = dict(pending_state)
        del written["setupId"]
        written.update(consentStatus=ACCEPTED, expectedAwsAccountId=account_id)
        return _save_record(written)


def mark_recovery(selected_state, status, reason, *, timeout=0.25):
    """Pause reporting after a bounded account error while keeping its choice.

    A concurrent opt-out or account selection takes precedence over the error
    from an older request. The caller can then prompt on its next interactive
    invocation without treating credential failure as a new sharing choice.
    """
    if (
        not isinstance(status, str) or not isinstance(reason, str)
        or reason not in _RECOVERY_REASONS.get(status, ())
    ):
        raise ValueError("INVALID_RECOVERY_RESULT")
    if (
        not _valid_state(selected_state) or selected_state["consentStatus"] != ACCEPTED
        or sharing_mode(selected_state) != AWS_ACCOUNT
    ):
        raise ValueError("INVALID_ACCOUNT_STATE")
    with state_guard(timeout=timeout):
        if read_state() != selected_state:
            return None
        written = dict(selected_state)
        written.update(recoveryStatus=status, recoveryReason=reason)
        return _save_record(written)
