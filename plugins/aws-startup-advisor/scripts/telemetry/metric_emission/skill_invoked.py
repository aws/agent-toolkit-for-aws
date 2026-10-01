#!/usr/bin/env python3
"""Hook: report that one of this plugin's skills was invoked.

    python3 scripts/telemetry/metric_emission/skill_invoked.py   # payload on stdin
    python3 scripts/telemetry/metric_emission/skill_invoked.py --skill gcp-to-aws

Claude Code has no skill-specific hook event. Skills run through the `Skill` tool,
so this is wired to `PostToolUse` with `matcher: "Skill"` and reads the name from
`tool_input.skill`. PostToolUse rather than PreToolUse because it fires after the
skill actually ran, and because a PreToolUse hook can block a tool call — which
telemetry must never be in a position to do.

The flow, stopping at the first thing that is not true:

  1. the consent record exists, parses, and has a UUID installId and an allowed
     consentStatus                                            (record.read_state)
  2. that status is exactly ACCEPTED
  3. resolve the endpoint: prod, or the ENDPOINT_ENV override
  4. emit_skill_invocation_metric(installId, skillId, url)

Silent, and always exits 0. The user asked for the skill, not for this.
"""

import json
import sys
import threading
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

import client  # noqa: E402  (paths set above so these resolve in-plugin)
import record  # noqa: E402

# Skill directory name -> PluginSkillId. UPPER_SNAKE_CASE of the directory, so this
# could be computed — it is written out because an allowlist is what stops us
# reporting a skill the service cannot represent, which would 400 the whole request.
# `skills/shared` is absent on purpose: it is imported by skills, not one itself.
SKILL_IDS = {
    "agent-advisor": "AGENT_ADVISOR",
    "architect-for-startups": "ARCHITECT_FOR_STARTUPS",
    "azure-to-aws": "AZURE_TO_AWS",
    "contextual-offers-for-startups": "CONTEXTUAL_OFFERS_FOR_STARTUPS",
    "gcp-to-aws": "GCP_TO_AWS",
    "heroku-to-aws": "HEROKU_TO_AWS",
    "knowledge-base-for-startups": "KNOWLEDGE_BASE_FOR_STARTUPS",
    "llm-to-bedrock": "LLM_TO_BEDROCK",
    "operate-on-aws": "OPERATE_ON_AWS",
    "prompt-library-for-startups": "PROMPT_LIBRARY_FOR_STARTUPS",
    "start-building-for-startups": "START_BUILDING_FOR_STARTUPS",
    "tf-best-practices": "TF_BEST_PRACTICES",
}

# A host may hand a hook a pipe it holds open, and a bare read() then blocks until
# an EOF that never comes, stalling the turn after every skill call.
STDIN_TIMEOUT_SECONDS = 2.0


def read_hook_payload(stream=None, timeout=STDIN_TIMEOUT_SECONDS):
    """The hook's stdin parsed as a dict, or {}.

    Read on a daemon thread so the deadline is enforceable: a blocking pipe read
    cannot be interrupted portably, but it cannot stop the interpreter exiting.
    """
    stream = sys.stdin if stream is None else stream
    box = {}

    def read():
        try:
            box["raw"] = stream.read()
        except Exception:
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)

    try:
        payload = json.loads(box.get("raw") or "")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def skill_name(argv, payload):
    """The skill the host says was invoked, or None.

    `--skill` wins, so this is runnable by hand and usable from a host that does
    not write the Claude Code payload shape.
    """
    if argv:
        if argv[0] == "--skill" and len(argv) >= 2:
            return argv[1]
        if argv[0].startswith("--skill="):
            return argv[0].split("=", 1)[1]

    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        name = tool_input.get("skill")
        if isinstance(name, str):
            return name
    return None


def skill_id(name):
    """Map a host's skill name onto a PluginSkillId, or None if it is not ours.

    Handles the qualified form, `aws-startup-advisor:gcp-to-aws`. An unrecognized
    qualifier is not a reason to drop the event — hosts qualify differently and
    undocumentedly — but an unrecognized name is.
    """
    if not isinstance(name, str):
        return None
    return SKILL_IDS.get(name.strip().rsplit(":", 1)[-1].strip().lower())


def main(argv, stdin=None):
    state = record.read_state()
    if not state or state["consentStatus"] != record.ACCEPTED:
        return 0

    skill = skill_id(skill_name(argv, read_hook_payload(stdin)))
    if skill is None:
        return 0

    client.emit_skill_invocation_metric(state["installId"], skill, client.endpoint())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BaseException:
        # Telemetry must not make a skill invocation look like it failed.
        sys.exit(0)
