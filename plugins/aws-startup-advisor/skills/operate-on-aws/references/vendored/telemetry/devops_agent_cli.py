#!/usr/bin/env python3
"""operate-on-aws's telemetry entry: read-only status, or report the Agent Space it created.

    python3 devops_agent_cli.py status
    python3 devops_agent_cli.py space-created --agent-space-id <id>

The skill runs `space-created` itself, after it has verified the space it created, on
every host. `status` sends nothing; `needsNotice` is true when no answer is recorded
or the accepted notice did not name the Agent Space ID.
"""

import json
import sys
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parent
sys.path[:0] = [str(TELEMETRY / "consent"), str(TELEMETRY / "metric_emission")]


def main(argv):
    # Imports can fail when a standalone bundle is incomplete. Keep them inside
    # the guarded invocation so optional telemetry still exits without blocking.
    import agent_space
    import client
    import record

    if argv == ["status"]:
        status = record.consent_status()
        print(json.dumps({
            "source": client.detect_source(),
            "consentStatus": status,
            "needsNotice": status != record.OPT_OUT and not agent_space.consent_covers_agent_space(),
            "pluginVersion": client.plugin_version(),
        }))
        return 0
    if len(argv) == 3 and argv[:2] == ["space-created", "--agent-space-id"]:
        agent_space.send_created(argv[2])
        return 0
    print("usage: devops_agent_cli.py {status|space-created --agent-space-id <id>}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)  # telemetry must not block the skill
