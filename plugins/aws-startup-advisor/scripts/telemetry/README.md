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
  migration.py       migration-run hooks: PostToolUse (Write|Edit|Bash), Stop, SessionEnd
  migration_attributes.py   the MigrationActivity attribute vocabularies and lookups

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

## Migration telemetry

`migration.py` reports a migration run's progress without any instruction to the
agent. The migration skills already keep `.migration/<id>/.phase-status.json` (and
`.gate-failures.json`) for their own gate enforcement; the hooks run the script,
which diffs those files against a snapshot it keeps beside them
(`.telemetry-snapshot.json`) and POSTs one `migrationActivity` event per
transition: RUN_STARTED, PHASE_COMPLETED, GATE_FAILED, RUN_COMPLETED. The diff is
idempotent and each run is locked while it runs, so overlapping hooks never report
a transition twice.

- Three triggers: PostToolUse on `Write|Edit|Bash` (incremental, async; Bash
  because the agent sometimes writes a state file through a heredoc rather than
  the Write tool, and a Bash payload carries no file path, so the emitter
  reconciles every run under the hook's cwd), Stop with `--reconcile` (re-reads
  state however it was written), SessionEnd with `--session-end` (final sweep,
  self-budgeted to Claude Code's default 1.5 s SessionEnd budget). Cursor
  registers `afterFileEdit`/`afterShellExecution`/`stop`/`sessionEnd` in
  `.cursor-plugin/hooks.json`.
- The state is read again once the run lock is held: hooks run concurrently, and
  one that read the state before another reported a newer transition must not
  diff against what it read.
- `RUN_COMPLETED` is sent once per `runMode`, and each mode at most once for the
  life of the run: a workshop re-entry that clears `run_mode` and reopens the
  decision gate does not make either ending reportable again. When the optional
  `current_phase` is absent, the run is complete only when every backbone phase,
  Generate included, is completed, as the owning skill evaluates it.
- Attribution comes from disk: the run's `owning_skill` (fail closed when absent),
  `run_id` (lower-cased; the data lake accepts only lower case), `initiated_by`.
- Attributes are lookups over the run's own artifacts (`migration_attributes.py`);
  an unmodelled value drops the attribute, never the event.
- RUN_COMPLETED is sent once per `runMode`: a run that ends decision-only and is
  later executed ends again under `DECIDE_AND_EXECUTE`, once Generate is
  completed. Consumers read a run's `runMode` from its latest RUN_COMPLETED and
  count completed runs by distinct `runId`. The same ending is never repeated,
  even after a confirmed re-entry re-reports its phases.
- A refusal the service may withdraw (403 while the launch gate is closed, 429,
  5xx), or no connection at all, leaves that event unrecorded so only it is
  re-sent; a 400, or a timeout after the request left, is not retried.
- Nothing is read into a snapshot without an accepted consent record, so a user
  who never agreed, or opted out, leaves no trace. Once consent exists, whatever
  the state file already holds is reported, which is the legal position for the
  IDE extension as well: data may be kept locally before consent, never sent.
- Teardown reports only runs the session itself touched (the snapshot names its
  owner); a hook that merely scans past a run leaves its owner alone.
