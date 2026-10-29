# Pausing and stopping AWS DevOps Agent

Cover this **in the DISCLOSE notice, before anything is created** — not only when they ask. A founder deciding
whether to enable a metered agent needs to know the exit before they take the entrance.

## What pausing stops

Say all four. A partial answer makes the pause look safer than it is:

1. **Autonomous incident investigation.** If something breaks while paused, they are investigating by hand.
2. **Proactive incident-prevention recommendations.**
3. **Release-readiness review** on pull requests.
4. **Continuous learning of their environment.** This is the one people do not expect — on resume, the
   agent needs time to rebuild that context. Investigations immediately after a resume may be less sharp.

A pause turns off what starts work automatically and cancels what is running. It does not stop the user
starting an investigation or review themselves, from the console or a coding agent, and that work bills
as usual, so never say a pause stops all charges. Setup is preserved, so resuming does not mean starting
over. Say both parts — the second is what makes pausing feel safe enough to actually use.

## Pausing

A pause turns off everything that starts a task automatically and cancels the tasks still running. Tell
the user each step below, including what they will redo to resume, and wait for
their yes before changing anything. Then, in the Agent Space they mean:

Turn off what starts tasks first, then cancel what is running, so nothing starts in between.

1. **Turn off automatic reviews.** For each repository association (`list-associations`), set the
   `RELEASE_READINESS_REVIEW` and `RELEASE_READINESS_REVIEW_AUTOMATED_TESTING` capabilities to
   `enabled: false` with `update-association`, keeping every other field of its configuration. The
   repositories stay connected and their filters are kept, so re-enabling restores them.
2. **Disconnect what starts investigations.** Disassociate the space's incident and observability
   integrations (PagerDuty, ServiceNow, generic webhooks, Datadog, Dynatrace, New Relic, Splunk, Grafana)
   with `disassociate-service`. This removes them from this space only: the registration in the account
   stays, so reconnecting needs no new sign-in. Warn the user first that the webhook goes with the
   association, so after reconnecting they paste the new webhook URL into that tool again. Keep the AWS
   account associations, the repositories and Slack.
3. **Stop scheduled work.** Set each trigger (`list-triggers`) to `Inactive` with
   `update-trigger --status Inactive`, and each goal's evaluation schedule (`list-goals`) to disabled with
   `update-goal --evaluation-schedule state=DISABLED`.
4. **Verify the starters are off.** Read each change back before going on.
5. **Stop what is running.** Only now list the running tasks of every kind that bills and cancel them all,
   as in [Cancelling a running investigation](#cancelling-a-running-investigation); a pause has nothing to
   pick. List again afterwards and confirm nothing is running. Anything still running is a pause not done.
6. **Report.** List exactly what was turned off, disconnected and cancelled. That list is what resuming
   turns back on. Say that anything they start themselves still bills, and that usage shows in the AWS
   DevOps Agent console.

Do not disable the Operator App to pause. It only turns off sign-in to the web app; investigations, reviews
and scheduled evaluations keep running and billing.

If a step fails or is denied, say which one and what can still bill. Do not report the pause as done.

## Cancelling a running investigation

An investigation runs 5–8 minutes and bills per second throughout. If a user starts one by mistake, cancel
it rather than letting it finish — that is real money, roughly $0.50 per minute.

If the user names the tasks to cancel (by task ID), cancel exactly those. Otherwise, find out what is
running before cancelling anything:

1. List the Agent Space's tasks that are still running, of every kind that bills: investigations,
   evaluations, release reviews and release tests. Check the space the user means; if they have more than
   one, ask which.
2. If nothing is running, say so and stop. There is nothing to cancel.
3. Show what is running (each task's title, kind, and when it started) and ask which to cancel: one,
   several, or all. Do not pick for them, even when only one is running.
4. Cancel the ones they chose, then confirm each one, as below. If something else is still running, say so,
   but do not cancel it without asking.

For each task, set its status to `CANCELED` with `UpdateBacklogTask`, then read it back and confirm the
status changed. Do not assume it stopped:

```bash
aws devops-agent update-backlog-task --agent-space-id <id> --task-id <id> --task-status CANCELED --region <region>
aws devops-agent get-backlog-task --agent-space-id <id> --task-id <id> --region <region> --query task.status
```

## Stopping completely

Disconnecting the MCP server stops *this client* from invoking the agent. It does **not** disable the
agent itself — anything scheduled or autonomous inside the Agent Space keeps running and keeps billing.

So when a user says "turn it off," establish which they mean:

- **"Stop it costing me money"** → pause (above) to turn off everything that starts work automatically, or
  delete the Agent Space to stop it for good. Removing the MCP config is not enough.
- **"Get it out of my editor"** → removing the MCP server config is sufficient.

Pausing and removing the MCP config delete neither the Agent Space, the access role, nor investigation records. Remove those only when the
user explicitly asks to delete the setup. Rolling back resources applies only to an onboarding the user
cancelled before it finished.

Getting this wrong is the expensive direction. If in doubt, do both and say so.

## Revoking a token

If a bearer token was used and may be exposed:

1. Web app → Settings → Access Tokens → select → **Revoke**. Immediate and irreversible.
2. To block all token access at once: Agent Space → Configuration → Access tokens → **Disable**. Existing
   tokens survive but stop working until re-enabled.

Rotating preserves the token's name, scopes, and IP allowlist while invalidating the old value — usually
what someone wants when a token has simply aged rather than leaked.

## Removing web app access

The Operator App is the Agent Space's web app. `disable-operator-app` turns off sign-in to it, and nothing
else: investigations, reviews, scheduled evaluations and billing continue. Use it only when the user wants
to remove web app access; to stop spend, pause or delete the Agent Space.

To turn it back on, `enable-operator-app` needs a role whose trust policy lets `aidevops.amazonaws.com`
assume it for this Agent Space (`aws:SourceArn`) with `sts:AssumeRole` and `sts:TagSession`. A role
created for another space is rejected.

## Never do this unprompted

Do not pause, disable, revoke, or cancel on the user's behalf without asking — even when it would clearly
save them money. Pausing during an active incident could leave them blind at the worst moment.

Surface the cost, recommend the action, and let them decide. The decision is theirs to make.
