#!/usr/bin/env python3
"""The consent record: one reader, one writer, one source of truth.

    ~/.aws-startup-advisor/plugin-telemetry.json
    {"installId": "<uuid>", "consentStatus": "ACCEPTED" | "OPT_OUT"}

That file is the only thing that decides whether telemetry may be emitted. There
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

import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notice  # noqa: E402  (path set above so this resolves in-plugin)

STATE_DIR_NAME = ".aws-startup-advisor"
STATE_FILE_NAME = "plugin-telemetry.json"

# Two answers, and only ACCEPTED permits emitting anything.
ACCEPTED = "ACCEPTED"
OPT_OUT = "OPT_OUT"

VALID_STATUSES = (ACCEPTED, OPT_OUT)

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
    return isinstance(value, str) and bool(_UUID_PATTERN.match(value))


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
    try:
        with open(state_path(), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    if data.get("consentStatus") not in VALID_STATUSES:
        return None
    if data["consentStatus"] == ACCEPTED and not _valid_install_id(
        data.get("installId")
    ):
        return None
    return data


def consent_status():
    """'ACCEPTED', 'OPT_OUT', or None when nothing is decided."""
    state = read_state()
    return state["consentStatus"] if state else None


def is_accepted():
    """The single gate every telemetry path must call.

    Deliberately not `!= OPT_OUT`: a missing or corrupt record must block too.
    """
    return consent_status() == ACCEPTED


def write_state(status):
    """Record `status`, return the record written, raise on failure.

    Atomic, so an interrupted write cannot leave a half-written record that
    `read_state` rejects and the hook then re-prompts on forever. An existing
    `installId` is preserved, so changing the answer is not a new install — but
    only if it is a UUID, since a hand-edited record may carry no ID at all or
    something the service would reject.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            "consentStatus must be one of %s, got %r" % (VALID_STATUSES, status)
        )

    existing = read_state() or {}
    install_id = existing.get("installId")
    if not _valid_install_id(install_id):
        install_id = str(uuid.uuid4())
    record = {"installId": install_id, "consentStatus": status}

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
