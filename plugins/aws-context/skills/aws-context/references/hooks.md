# AWS Context hooks

The plugin has two hooks. Both are off until the user turns them on with `/context-hooks`.
One file holds every setting: `~/.aws-context/config.json`. Read it to show status. Write it
only after the user has chosen a setting, and keep any keys you did not change.

## The two hooks

| Setting | Values | Default | What happens | Data sent to AWS Context |
|---|---|---|---|---|
| `steering` | `off`, `hint`, `search` | `off` | On each prompt, `hint` adds one line telling the agent AWS Context is available. `search` also runs a quick search with the prompt and adds the top matches as hints | `hint`: none. `search`: the prompt text, up to 500 characters, to the user's graph |
| `feedback` | `off`, `on` | `off` | When a session in which the agent called an AWS Context tool ends, sends the session transcript with PutTrace so the graph can learn from it | The session log as the agent recorded it, one line per document, to the user's graph. A resumed session sends only the lines not yet sent. When more than 16 MB is waiting, only the newest 16 MB goes, and a single line over 4 MB is left out |

The hooks send text as it is. Nothing is removed from prompts or transcripts first.

## Settings for search and feedback

Hooks cannot use the agent's sign-in, so they call AWS Context with an AWS profile on this
machine. Before turning on `steering search` or `feedback on`, collect:

- `graphArn`: the graph's agent context ARN (`arn:aws:context:<region>:<account>:agent-context/<id>`), from its Settings tab in the AWS Context console.
- `profile`: an AWS profile with `context:SearchAgentContext` (search) or `context:PutTrace` (feedback). If the user has none, follow the SigV4 section of `connecting.md`. For an SSO, assume-role or credential-process profile, the AWS CLI v2 must be on the path; the hooks use it to read the profile's credentials. Steering searches as this profile. On a graph with access control, a profile that is not an IAM Identity Center sign-in sees only entries every reader can see, so steering can show fewer matches than the agent's own search, never more.
- For feedback, `readers`: who may see what AWS Context learns from the traces. Offer three choices, with only the user as the default, and store the answer as a list of entries:
  - Only the user (default): one entry, `{"access": "ALLOW", "principalType": "USER", "principalId": "<their sign-in email>"}`. Ask for the email they sign in to AWS Context with. Do not leave `readers` empty: the hooks sign with an AWS profile, so the service cannot tell who the user is and refuses a trace with no readers.
  - Specific people or groups: one `ALLOW` entry each, with `principalType` `USER` and the person's sign-in email, or `GROUP` and the group ID the user gives you.
  - Everyone who can read the graph: `[{"access": "ALLOW", "principalId": "*"}]`. Use it only when the user chooses it.

  Ask for exact values. A wrong value matches no one, so nobody sees the insights.

Done when every setting the user's choice needs is filled in. If one is missing, leave the hook off and tell the user what is missing.

For feedback, also tell the user the graph needs trace analysis turned on. An administrator turns it on, with a trace analysis role, in the graph's settings, and new graphs have it off. You cannot check it from here, so do not wait for it: if it is off, traces wait on this machine and the status shows `trace-analysis-disabled`.

## Data notice

Fill in the values:

> This setting sends [the text of each prompt | the full transcript of each session that called an AWS Context tool, including commands, file contents and tool output] from this agent to your AWS Context graph `<graphArn>`, signed with the AWS profile `<profile>`. Nothing is removed before sending, so keep secrets and personal data out of sessions while it is on. [Readers: `<readers>`.] You can turn it off at any time with `/context-hooks`.

## Changing a setting

1. Show the current value and the new value.
2. For `steering search` or `feedback on`, collect the settings above, then show the data notice and wait for a yes. Done when the user says yes after seeing the notice.
3. When turning feedback off, or changing `graphArn` or `readers` while it is on, delete the sessions still waiting in `~/.aws-context/spool/` and tell the user how many. They were queued under the old settings. Lines already sent keep the readers they were sent with; a session's later lines go with the new readers.
4. Write the file and confirm the change. It applies from the next prompt (steering) or the next session end (feedback).

## Showing status

Show each setting from the config file. If `~/.aws-context/feedback-status.json` exists,
also show its `state`, `detail` and `since`, and count the sessions waiting in `~/.aws-context/spool/`.
Their unsent lines go at the next session end after the cause is fixed.

| `state` | Meaning | What the user does |
|---|---|---|
| `sent` | Every waiting session was stored; `detail` has how many log lines went and the latest session ID | Nothing |
| `trace-analysis-disabled` | The graph refused traces because trace analysis is off | An administrator turns it on in the graph's settings |
| `no-credentials` | The AWS CLI could not read credentials for the profile | Sign in again for that profile, or install the AWS CLI v2 |
| `credentials-rejected` | AWS refused the profile's credentials, for example because they expired | Sign in again for that profile |
| `access-denied` | The profile lacks `context:PutTrace` on the graph, or a session was started under another identity and is resumed under this one | Add the permission to the profile's role, or switch back to the profile the session started with |
| `unreachable` | AWS Context did not answer, was throttling, had a server error, or the send ran out of time | Nothing; the unsent lines go at a later session end. If `detail` says `UnknownOperationException`, the plugin calls a route the service no longer serves: update the plugin |
| `rejected` | The service refused part of a session as invalid, shown in `detail`. Those lines are not sent again; the rest of the session went | Fix the setting `detail` names, such as `readers` |
