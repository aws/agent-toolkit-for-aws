---
name: usage-data
description: Show or change whether AWS Startup Advisor collects optional usage data
argument-hint: "[status | opt-out | opt-in | show]"
---

The user wants to see or change their usage-data setting for the AWS Startup
Advisor plugin. They typed this themselves, so they have already asked for it.
Do not argue for either answer, and do not ask them to confirm a choice they
already stated in the argument.

One file decides everything: `~/.aws-startup-advisor/plugin-telemetry.json`. There
is no environment variable. Opting out means setting `"consentStatus"` to
`"OPT_OUT"` in that file, which is what the notice tells the user and what the
script below does in one step — the script also keeps their install ID, so prefer
it over editing by hand.

Each block below is one command: run it whole, in a single shell invocation. The
two setup lines are repeated in every block on purpose — shell variables do not
survive between separate invocations, so a block that omitted them would run
`python3` against an empty path.

`${CLAUDE_PLUGIN_ROOT}` has to appear as exactly that token to be substituted, so
it carries no shell default. If it does not resolve, the script path will not exist
and Python will say so: relay that and stop. Do not hunt for the files yourself and
do not hand-edit the record.

Act on `$ARGUMENTS`, case-insensitively, treating anything unrecognised as empty:

**Empty or `status`**

```bash
CONSENT="${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/consent"
PY="$(command -v python3 || command -v python || echo 'py -3')"
$PY "$CONSENT/cli.py" status
```

Relay that output as-is, then mention they can pass `opt-out`, `opt-in`, or
`show`.

**`opt-out`**

```bash
CONSENT="${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/consent"
PY="$(command -v python3 || command -v python || echo 'py -3')"
$PY "$CONSENT/opt_out.py"
```

No confirmation. Asking someone to confirm twice in order to decline is a dark
pattern.

**`opt-in`** — show the notice first, since acknowledging it is what opting in
means:

```bash
CONSENT="${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/consent"
PY="$(command -v python3 || command -v python || echo 'py -3')"
$PY "$CONSENT/cli.py" show
```

Reproduce that output VERBATIM: no summarizing, shortening, translating,
reordering, or rewriting. It is a legal notice and the exact wording is the
point. Then ask them to confirm, and only if they do:

```bash
CONSENT="${CLAUDE_PLUGIN_ROOT}/scripts/telemetry/consent"
PY="$(command -v python3 || command -v python || echo 'py -3')"
$PY "$CONSENT/accept.py"
```

**`show`** — print the notice, verbatim as above, and change nothing. It writes
nothing, so do not report it as having changed their setting.

## Rules

- Never run `accept.py` unless the user asked to opt in or acknowledged
  the notice in this conversation. Printing the notice is not acknowledgement.
- If a script exits non-zero, relay its stderr as-is. It says exactly what was
  not saved; guessing is worse.
- Opting out disables nothing. Every skill works identically either way. Say so
  if asked, and never imply otherwise.
