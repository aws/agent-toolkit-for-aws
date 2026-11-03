#!/usr/bin/env python3
"""SessionStart hook: offer the shared page when local setup needs attention.

    python3 scripts/telemetry/consent/session_start.py

Silent for a usable accepted choice or saved opt-out. Missing, pending, invalid,
renewal-required and account-recovery choices produce an instruction to open the
local sharing page at the next interactive skill invocation. The hook itself
does not open a browser, resolve credentials, or change the preference.

Only one of the three parts is trustworthy, which is the design:

  - this hook is the *alarm clock*; it notices the record is missing and cannot
    prompt anyone itself, since no host lets a session-start hook ask
  - the model is the *messenger*, and the weakest link: it may paraphrase, skip, or
    invent an answer, which is why nothing here trusts it with the decision
  - `accept.py` / `opt_out.py` are the *notary* and the only writers, so an ignored
    instruction means no record, which means no telemetry. The failure mode is
    silence, not unconsented collection.

Claude Code takes plain stdout on SessionStart as extra context, so that is all
this writes. A host wanting a JSON envelope needs its own wrapper.

Always exits 0. A consent prompt is not worth breaking a session over.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import record  # noqa: E402  (path set above so this resolves in-plugin)

CONSENT_DIR = Path(__file__).resolve().parent

# Absolute paths, not ${CLAUDE_PLUGIN_ROOT}: this is read by a model, not a shell,
# so an unexpanded variable would reach it as literal text. Same reason the
# interpreter is resolved here rather than written as a bare `python3`, which is
# usually not on PATH on Windows — the model would run it and the notice would
# never be recorded.
INSTRUCTION = """\
[AWS Startup Advisor] The local sharing choices need attention.

At the next interactive Startup Advisor invocation, first run:
  {py} "{telemetry}/cli.py" sharing

This opens the local three-choice sharing page. The user selects account-linked
sharing, anonymous sharing, or no sharing there. Its output contains only the
reporting mode and bounded status. Never inspect account IDs, credentials, proofs,
or the page URL. Continue the requested work after the page returns; telemetry
errors do not authorize or block product actions. Do not repeat a saved opt-out.
Run sharing --change only when the user asks to change their sharing choice.

Only if the page reports BROWSER_UNAVAILABLE, use the existing anonymous notice
exchange below. This fallback cannot select AWS account sharing.

The first time in this session that a request would use an AWS Startup Advisor
skill, stop before doing that work and run this exchange instead:

1. Run: {py} "{consent}/cli.py" show
2. Reproduce that command's output to the user VERBATIM. Do not summarize,
   shorten, translate, reorder, or rewrite it — it is a legal notice and the
   exact wording is the point. Its last paragraph already asks the question and
   offers both answers, so do not restate it, re-ask it in your own words, or
   add your own version underneath. Relaying it is the whole job.
3. END YOUR TURN THERE. Send the notice and the question, and nothing else: do
   not answer their request in the same message, do not call any other tool, and
   do not begin the work. A question delivered alongside its own answer gets
   skipped — the user reads the answer they asked for and never replies to the
   notice, which makes showing it pointless.
4. When they reply, record it by running exactly one of:
     acknowledged     -> {py} "{consent}/accept.py"
     wants to opt out -> {py} "{consent}/opt_out.py"
5. Then answer their original request in full, in that same turn. They asked
   once; do not make them repeat themselves or re-ask.

Rules: Do not guess or assume a response, and do not run either script until the
user has actually responded. If they ignore the notice, change the subject, or
tell you to get on with it, then get on with it: record nothing, answer them, and
do not raise this again in this session. Nothing recorded means no usage data is
sent and the notice will simply be raised again next session, so an unanswered
notice costs nothing and is never worth nagging over.

This pause is one turn, once per install. It is not a gate on using the plugin:
every feature works identically whatever they choose, and opting out disables
nothing. There is no environment variable: the record file the scripts above
write is the only thing that decides whether anything is collected, and the
notice tells the user they may edit it themselves instead.
"""


def build_message():
    return INSTRUCTION.format(consent=CONSENT_DIR, telemetry=CONSENT_DIR.parent, py=record.INTERPRETER)


def main():
    # Deliberately does not read stdin. Hosts write the hook payload there and
    # nothing here needs it. Reading it would risk hanging: a host that holds the
    # pipe open never sends the EOF that read() waits for, the host kills the hook
    # at its timeout, and the notice silently never appears.

    sys.path.insert(0, str(CONSENT_DIR.parent))
    from sharing.ui import status_result
    if status_result()["status"] in ("READY", "SKIPPED"):
        return 0  # already answered, accepted or opted out — stay quiet

    print(build_message(), end="")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(0)  # never break session start
