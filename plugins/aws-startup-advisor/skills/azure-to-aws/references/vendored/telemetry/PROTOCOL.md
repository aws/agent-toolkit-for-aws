# Migration telemetry on CLI hosts

This protocol applies to Azure, GCP, Heroku, and LLM-to-Bedrock runs under
`.migration/`. It does not extend telemetry to `.agent-advisor/` runs.

## Resolve the reporting mode

Before starting or resuming this skill, resolve the absolute directory containing
its `SKILL.md`. The runtime is bundled in that skill's
`references/vendored/telemetry/` directory. Use Python 3.8 or newer (`python3`,
`python`, or `py -3` on Windows). If Python, the bundle, or permission to run the
command is unavailable, skip telemetry and continue the requested work.

Run the read-only check, substituting the actual absolute skill directory:

```sh
python3 "<absolute-skill-root>/references/vendored/telemetry/cli.py" status
```

Use `reportingMode` from its JSON output, not the model's name or the agent's
self-description. The check uses the shared client's host environment markers:
Claude Code and Cursor select `hook`; other sources select `cli`. Unknown sources
remain `OTHER`. Do not set or clear host markers to change this result.

- `hook`: do not invoke CLI reconciliation or duplicate the host's consent
  exchange. Existing hooks own reporting. Missing or delayed hook activity does
  not change this policy.
- `cli`: follow the consent exchange below, then reconcile at the state
  boundaries. A missing `pluginVersion`, invalid output, or command failure means
  telemetry is unavailable; continue the skill without reporting.

Recheck on resume, since the user may continue in a different host. Do not inspect
snapshot timestamps to select the reporting mode. Use absolute paths in every
tool call, or assign and use shell variables within the same invocation.

## Reuse the existing consent exchange

The only consent record is `~/.aws-startup-advisor/plugin-telemetry.json`.
Do not copy old project consent, assume an answer, or edit the record yourself.

- `consentStatus: "ACCEPTED"`: reporting is allowed.
- `consentStatus: "OPT_OUT"`: do not ask again or report. Continue the skill.
- `consentStatus: null`: if the notice has not already been raised in this session,
  run the bundled `consent/cli.py show`. Relay its output VERBATIM, including its
  question, and end that turn. Do not paraphrase, translate, add a second question,
  or start the migration work alongside the notice.

After the user replies, run the bundled `consent/accept.py` only for an explicit
acknowledgement, or `consent/opt_out.py` for an explicit opt-out. Then continue the
original request without asking the user to repeat it. If they ignore the notice
or ask to proceed, record nothing, continue without telemetry, and do not repeat
the notice in this session. A failure to save the choice is not consent and must
not block the migration. A later opt-out uses the same `consent/opt_out.py`.

These are the same notice and writers the plugin's hooks use. Telemetry consent
does not authorize cloud discovery, deployment, or other migration actions.

## Reconcile persisted state

In `cli` mode, from the project root containing `.migration/`, run:

```sh
python3 "<absolute-skill-root>/references/vendored/telemetry/cli.py" reconcile
```

Run this in the main workflow after initialization writes `.phase-status.json`,
after each phase-status update, after a gate failure is recorded and before
returning, and after selecting and validating a run on resume. Include sidebar
updates, decision-only completion, and completion after opted-in Generate. For
LLM-to-Bedrock, also reconcile after creating or resuming its own `.bedrock-*` run
and after writing its completion.

The emitter derives events and attribution from disk and rechecks consent.
Do not construct HTTP payloads, create new run IDs for reporting, edit snapshots,
or manually retry a failed request. Later boundaries reconcile unreported events.
Preserve the existing one-completion-per-runMode and gate-failure semantics.
The CLI fallback reports migration activity; it does not synthesize skill
invocation events. Reporting failure never changes a phase result or blocks work.
