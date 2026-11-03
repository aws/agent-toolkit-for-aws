#!/usr/bin/env python3
"""Opt the user out of usage-data collection.

    python3 scripts/telemetry/consent/opt_out.py

The command the notice names, and the only way to opt out — there is no
environment variable, because the record file is the single source of truth.
Writes {"installId": "<uuid>", "consentStatus": "OPT_OUT"}.
The shared atomic writer clears the account, profile, mode, and pending setup.

Recording the opt-out is also what stops the session-start hook raising the notice
again, so it has to be written down as deliberately as an acknowledgement. An
install ID is written too, so a later change of heart is not a new install; nothing
emits it, since every telemetry path is gated on `is_accepted()`.

Sends nothing. `ConsentRecordedDetails` is empty and cannot say which way the user
answered, so a request from here would be indistinguishable from a yes.

The plugin is fully functional after opting out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import record  # noqa: E402  (path set above so this resolves in-plugin)


def main():
    try:
        record.write_state(record.OPT_OUT)
    except OSError as exc:
        print(
            "Could not record your choice at %s: %s\n"
            "Your previous sharing choice is unchanged. Sharing may continue "
            "until opt-out is saved. Retry this command, or edit consentStatus "
            "to OPT_OUT in that file." % (record.state_path(), exc),
            file=sys.stderr,
        )
        return 1

    print(
        "You are opted out — usage data collection is OFF and no data will be "
        "sent.\n"
        "Recorded at %s so you are not asked again.\n"
        "Every feature of the plugin still works." % record.state_path()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
