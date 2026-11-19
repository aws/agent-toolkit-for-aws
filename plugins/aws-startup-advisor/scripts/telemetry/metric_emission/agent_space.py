#!/usr/bin/env python3
"""Report the AWS DevOps Agent Space the operate-on-aws skill created.

Called only by the skill, through devops_agent_cli.py, after it has verified the
space it created, so a space another tool creates is never reported.
"""

import re
import sys
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

import client  # noqa: E402  (paths set above so these resolve in-plugin)
import record  # noqa: E402

# The AWS DevOps Agent AgentSpaceId format. Anything else is dropped here: a value the
# service cannot represent would be rejected, and only an id may leave the machine.
AGENT_SPACE_ID = re.compile(r"^[a-zA-Z0-9-]{1,64}$")

# The first notice version that names the Agent Space ID. An acknowledgement of an
# earlier notice does not cover sending it.
DISCLOSED_IN_NOTICE_VERSION = 2


def consent_covers_agent_space():
    return record.accepted_notice_version() >= DISCLOSED_IN_NOTICE_VERSION


def send_created(agent_space_id):
    """Report a newly created Agent Space; False if the id is not one or nothing was sent."""
    if not isinstance(agent_space_id, str) or not AGENT_SPACE_ID.match(agent_space_id):
        return False
    if not consent_covers_agent_space():
        return False
    return client.send_event({"devOpsAgentSpaceCreated": {"agentSpaceId": agent_space_id}})
