---
name: context-hooks
description: Show or change the AWS Context hooks (prompt steering and session traces)
argument-hint: "[status | steering off|hint|search | feedback on|off]"
---

The user wants to see or change the AWS Context hook settings. They typed this
themselves. Do not argue for any setting.

Read `${CLAUDE_PLUGIN_ROOT}/skills/aws-context/references/hooks.md` (the `hooks.md` reference of this plugin's aws-context skill) and act on `$ARGUMENTS`:

- Empty or `status`: show the current settings and what each one does.
- `steering off|hint|search`: set the steering mode.
- `feedback on|off`: turn session traces on or off.

Follow the steps in its "Changing a setting" section.
