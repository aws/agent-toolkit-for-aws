# Telemetry

Optional usage data: asking for consent, recording the answer, and emitting
metrics once the answer is yes. Nothing here is required for any skill to work.

## Layout

```
consent/           deciding whether anything may be sent
  notice.py          the approved wording, text only — legal reviews this file
  record.py          ~/.aws-startup-advisor/plugin-telemetry.json: read/write/gate
  cli.py             show | status
  accept.py          writes ACCEPTED
  opt_out.py         writes OPT_OUT — the command the notice names
  session_start.py   SessionStart hook: asks the agent to raise the notice, once

metric_emission/   sending events, only ever when consent/ says yes
  client.py          builds and POSTs a PluginTelemetryEvent
  skill_invoked.py   PostToolUse hook, matcher "Skill"

test/              the whole suite
```

Two directories, two jobs: `consent/` decides, `metric_emission/` sends. Every
path in `metric_emission/` is gated on `record.is_accepted()`, re-checked inside
`client.post_event` so a new call site cannot emit by forgetting to ask.

## The one rule

`~/.aws-startup-advisor/plugin-telemetry.json` is the single source of truth.
There is no environment variable, so a user cannot be opted out according to
their shell and opted in according to their disk.

The notice names that file as the opt-out — set `"consentStatus"` to `"OPT_OUT"`.
`opt_out.py` makes the same edit in one step and keeps the install ID.

The only environment variable here is `AWS_STARTUP_ADVISOR_PLUGIN_TELEMETRY_ENDPOINT`,
which chooses *where* an event goes (beta/gamma for the service team) and never
whether one is sent.

## Running the tests

```
uv run --with pytest python -m pytest -q
```

`python3 -m pytest` does not work on a homebrew Python with no pytest installed.
