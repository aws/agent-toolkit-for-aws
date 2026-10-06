#!/usr/bin/env python3
"""Standalone skill entry: read-only status, or consent-gated reconciliation.

    python3 cli.py status
    python3 cli.py reconcile

Status chooses the migration reporting policy from the shared client's host
markers. It does not send events, create consent, or inspect migration artifacts.
The reporting action rechecks the same policy inside the existing emitter.
"""

import json
import sys
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parent
sys.path[:0] = [str(TELEMETRY / "consent"), str(TELEMETRY / "metric_emission")]


def main(argv):
    # Imports can fail when a standalone bundle is incomplete. Keep them inside
    # the guarded invocation so optional telemetry still exits without blocking.
    import client
    import migration
    import record

    if argv == ["status"]:
        print(json.dumps({
            "source": client.detect_source(),
            "reportingMode": client.migration_reporting_mode(),
            "consentStatus": record.consent_status(),
            "pluginVersion": client.plugin_version(),
        }))
        return 0
    if argv == ["reconcile"]:
        return migration.main(["--reconcile", "--via", "cli"])
    print("usage: cli.py {status|reconcile}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)  # telemetry must not block the skill
