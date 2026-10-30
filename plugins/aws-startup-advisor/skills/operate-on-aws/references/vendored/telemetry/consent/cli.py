#!/usr/bin/env python3
"""Print the usage-data notice, or report its status.

    python3 scripts/telemetry/consent/cli.py show     # print the notice text
    python3 scripts/telemetry/consent/cli.py status   # the setting, for a human

`show` exists so the user reads the notice as *tool output* rather than as model
prose: tool output reaches the terminal byte for byte, and a paraphrased legal
notice is not the notice. It is read-only and mints no install ID — printing the
text is not acknowledgement. Only `accept.py` and `opt_out.py` write.

`status` always exits 0: "not recorded" is a state, not an error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import record  # noqa: E402  (path set above so this resolves in-plugin)

USAGE = "usage: cli.py {show|status}"

CONSENT_DIR = Path(__file__).resolve().parent


def status_report():
    """One human-readable paragraph describing the current setting.

    Reads the record and nothing else — there is no environment variable to rank
    against it, so what this prints is what the plugin acts on.
    """
    state = record.read_state()
    status = state["consentStatus"] if state else None

    if status == record.ACCEPTED:
        return (
            "Usage data collection: ON. You acknowledged the notice.\n"
            "Install ID: %s\n"
            "Recorded at: %s\n"
            "\n"
            "%s"
            % (
                state["installId"],
                record.state_path(),
                record.opt_out_help(),
            )
        )

    if status == record.OPT_OUT:
        return (
            "Usage data collection: OFF. You opted out, and nothing is sent.\n"
            "Recorded at: %s\n"
            'To turn it back on, run: python3 "%s/accept.py"'
            % (record.state_path(), CONSENT_DIR)
        )

    # Also what a corrupt record reports: the gate treats the two identically.
    return (
        "Usage data collection: OFF. Nothing is recorded yet, so nothing is "
        "sent.\n"
        "The notice will be shown at the start of your next session.\n"
        "Expected record location: %s" % record.state_path()
    )


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(USAGE, file=sys.stderr)
        return 0 if argv and argv[0] in ("-h", "--help") else 2

    command = argv[0]

    if command == "show":
        print(record.disclaimer(), end="")  # already ends with a newline
        return 0

    if command == "status":
        print(status_report())
        return 0

    print("%s\n%s" % ("unknown command: %s" % command, USAGE), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
