# Local sharing choices

The plugin and standalone skills share one preference file and sender. Opening
the page or showing a notice does not accept sharing. Pending, invalid, opted-out,
and renewal-required choices send nothing. Anonymous sharing never loads the
credential adapter. Reporting errors never turn an account report into an
anonymous report.

```sh
python3 scripts/telemetry/cli.py sharing-status
python3 scripts/telemetry/cli.py sharing
python3 scripts/telemetry/cli.py sharing --change
```

`sharing` opens a short-lived page on an ephemeral `127.0.0.1` port. The account
number and selected profile stay in the local page and preference file. CLI
output contains only the sharing mode and bounded status/reason. The page is
closed after a choice or its two-minute deadline. Browser failure or closing the
page before choosing leaves the existing choice unchanged. Failed account setup
leaves it pending.

Successful anonymous or account acceptance saves the choice, then makes one
best-effort `consentRecorded` submission through the shared sender. A reporting
failure does not undo the choice. Display, cancellation, opt-out, and failed
setup do not send an acknowledgement.

The three buttons select account sharing, anonymous sharing, or no sharing.
Starting account setup clears the previous account and records a unique pending
setup. Completion uses that setup ID, so a late lookup cannot overwrite a later
opt-out or account switch. All writers use a process lock and atomic replacement.
The preference file has owner-only permissions on POSIX. The lock contains no
choice or credential data.

A legacy accepted record without `identityMode` remains anonymous under its
existing notice. `accept.py` explicitly selects anonymous sharing; it cannot finish
account setup. `opt_out.py` clears account/profile fields. Editing only
`consentStatus` to `OPT_OUT` also stops submissions and avoids another prompt.

## Account reporting configuration

The shipped `policy.json` contains `{"accountReporting": null}`. Account sharing
is disabled. The existing anonymous notice remains unchanged. A release can enable
account sharing only after its notice and intended data uses are approved and the
corresponding verifier is deployed. The bundled configuration then contains:

```json
{
  "accountReporting": {
    "enabled": true,
    "approved": true,
    "noticeVersion": 3,
    "noticeText": "Replace with the complete approved account-sharing notice.",
    "endpoint": "https://report.example.com/v1/plugin-telemetry-event",
    "audience": "startup-advisor:deployment-id:report:v1"
  }
}
```

This is a schema example, not approved text or a working deployment. The notice
must cover the actual permitted uses. Changing purpose requires a new notice
version. Release configuration is packaged with the runtime; browser requests
and environment variables cannot supply or enable it. Account proofs are sent
only to its exact HTTPS endpoint. Redirects and mismatched endpoint overrides
are rejected. A changed account notice requires a new local choice.

Install the T01 locked SDK dependencies explicitly before using account sharing:

```sh
uv sync --frozen --project scripts/telemetry/auth
```

The account worker uses that environment, or an already installed supported
Python environment. Background hooks never download dependencies. Standalone
installs use their bundled `references/vendored/telemetry/auth` project instead.
Anonymous reporting and the page retain Python 3.8 support; the account worker
requires Python 3.10 or newer on POSIX. Account setup and reporting are disabled
on Windows until process-tree cleanup is implemented and validated there.
Windows anonymous reporting remains available. Sign in using the existing AWS provider's flow.
For a configured IAM Identity Center profile, use `aws sso login --profile NAME`.
For a console-login profile, use its AWS CLI `aws login --profile NAME` flow.
Then retry account setup on the page. Startup Advisor creates no credential store.

## Shared sender and recovery

Hooks and CLI call `client.send_event_result` through the existing sender adapters.
It validates the preference itself, prepares the account proof privately, and
rechecks the same record under a shared lock immediately before submission.
Sends may overlap, while preference writers require an exclusive lock until
those submissions finish. Installation UUIDs are compared and sent in lowercase;
their spelling in the local preference file is preserved.
Account lookup/signing run with a total subprocess deadline and closed stdin.
The caller suppresses raw worker output and terminates provider descendants.
Worker and network deadlines share the hook's remaining time budget.

The sender returns `SENT`, `SKIPPED`, `SIGN_IN_REQUIRED`, `SETUP_REQUIRED`, or
`ERROR`, plus a bounded reason. Account mismatch and expired sign-in attempt to
save bounded recovery metadata while retaining the accepted account and notice.
Recovery writes wait for other sends within the remaining deadline. When the
metadata is saved, background reporting pauses and the next interactive invocation
offers setup. If the local write fails or times out, the caller still receives
the original account error, but subsequent invocations may try reporting again.
Explicit new setup clears that metadata. There is no automatic anonymous fallback.

Unknown HTTP outcomes and account-proof rejection are not retried automatically.
No proofs, credential values, or event bodies are persisted. A later opt-out
stops new submissions from this client; backend requests already accepted may
finish processing. Deleting existing data follows the separate AWS privacy
request process.

Tests use synthetic credentials, stubbed STS, isolated home directories, and local
collectors. Supported-provider sign-in, real STS, verifier interoperability,
notice approval, and supported-host acceptance remain release requirements.
