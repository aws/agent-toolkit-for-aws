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

Run the scripts from this plugin's consent directory:

```bash
CONSENT="${CLAUDE_PLUGIN_ROOT:?plugin root not set}/scripts/telemetry/consent"
```

If that variable is unset, do not hunt for the files and do not hand-edit the
record. Say the plugin root could not be resolved and stop.

Act on `$ARGUMENTS`, case-insensitively, treating anything unrecognised as empty:

**Empty or `status`**

```bash
python3 "$CONSENT/cli.py" status
```

Relay that output as-is, then mention they can pass `opt-out`, `opt-in`, or
`show`.

**`opt-out`**

```bash
python3 "$CONSENT/opt_out.py"
```

No confirmation. Asking someone to confirm twice in order to decline is a dark
pattern.

**`opt-in`** — show the notice first, since acknowledging it is what opting in
means:

```bash
python3 "$CONSENT/cli.py" show
```

Reproduce that output VERBATIM: no summarizing, shortening, translating,
reordering, or rewriting. It is a legal notice and the exact wording is the
point. Then ask them to confirm, and only if they do:

```bash
python3 "$CONSENT/accept.py"
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
