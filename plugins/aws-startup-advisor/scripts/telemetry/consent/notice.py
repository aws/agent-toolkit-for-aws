#!/usr/bin/env python3
"""The approved usage-data notice. Text only — no state, no filesystem, no imports
but textwrap, so legal can review this file without reading any logic.

Do not rephrase, reorder or trim NOTICE_BODY. Line breaks are the only formatting
liberty, and they are applied at print time rather than written here.
"""

import textwrap

NOTICE_TITLE = "AWS Startup Advisor plugin — usage data notice"

# One unwrapped paragraph; render() wraps it. Do not wrap it here: {opt_out} is
# substituted before wrapping, so a line that fits in this source need not fit in
# the output.
NOTICE_BODY = (
    "You've installed the AWS Startup Advisor plugin, which provides skills that "
    "help you build on AWS through your AI coding agent. To help us improve it, "
    "we'd like to collect optional usage data about how the plugin is used. What "
    "we collect: which skill you invoked, the plugin version, the host tool "
    "you're using, a randomly generated install identifier, and, for migration "
    "skills, the source cloud provider and which migration phase you start and "
    "complete. The usage data above is not linked to your identity. You can "
    "opt-out by {opt_out}. Opting out does not change any plugin functionality."
)

# The approved source ends in "[Acknowledge]", a GUI button label. In a terminal
# that renders as a dead string asking the user nothing, so it becomes a question
# they can answer in words.
ACKNOWLEDGE_PROMPT = (
    'Do you acknowledge this notice? Reply "yes" to acknowledge, or "opt out" if '
    "you would rather no usage data was collected. Either answer is fine, and "
    "nothing is collected until you answer."
)

# TODO(StartupEngBlend-3621): confirm both substitutions with legal.

# 79, not 80, so a terminal reserving a cell for the cursor does not re-wrap.
WRAP_WIDTH = 79


def _wrap(text):
    # break_* off so a path or variable name is never split across lines.
    return textwrap.fill(
        text,
        width=WRAP_WIDTH,
        break_long_words=False,
        break_on_hyphens=False,
    )


def render(opt_out):
    """The notice as the user must see it.

    `opt_out` completes "You can opt-out by ...". Substitute first, then wrap.
    """
    body = _wrap(NOTICE_BODY.format(opt_out=opt_out))
    return "%s\n\n%s\n\n%s\n" % (NOTICE_TITLE, body, _wrap(ACKNOWLEDGE_PROMPT))
