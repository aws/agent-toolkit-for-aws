#!/usr/bin/env python3
"""Record that the user ACKNOWLEDGED the usage-data notice.

    python3 scripts/telemetry/consent/accept.py

Run only after `cli.py show` has printed the notice and the user has acknowledged
it in their own words. Nothing here can verify that, which is why accept and
opt-out are two scripts rather than one script with a flag: the agent's action is
unambiguous in the transcript and a host can permission-gate them separately.

Writes {"installId": "<uuid>", "consentStatus": "ACCEPTED"}, minting the install ID
on first write and preserving any existing one. Exits non-zero and explains itself
if the write fails, so a failure is never silently taken as consent.

Then sends a `consentRecorded` event. The record is written first and is what gates
every future emission, so a failed POST costs one event and nothing else. It cannot
fail this script and is not mentioned in the output — a user who just said yes
learns nothing from being told whether one HTTPS request succeeded.
"""

import sys
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

import client  # noqa: E402  (paths set above so these resolve in-plugin)
import record  # noqa: E402


def main():
    try:
        written = record.write_state(record.ACCEPTED)
    except OSError as exc:
        print(
            "Could not record your choice at %s: %s\n"
            "Nothing was saved, so no usage data will be collected. The notice "
            "will be shown again next session." % (record.state_path(), exc),
            file=sys.stderr,
        )
        return 1

    client.send_consent_recorded()  # fire and forget

    print(
        "Acknowledged — usage data collection is ON.\n"
        "Recorded at %s (install ID %s).\n"
        "\n"
        "%s"
        % (
            record.state_path(),
            written["installId"],
            record.opt_out_help(),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
