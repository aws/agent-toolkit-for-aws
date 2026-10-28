# AWS account reporting helper

This optional component resolves an existing AWS account and prepares signed
telemetry requests. It does not enable account reporting, change consent, start
login, or send telemetry. Existing anonymous hooks do not import it.

The helper implements the proposed v1 proof format. The reporting API must
validate that format before a caller enables this path.

## Runtime

The helper uses Python 3.10+ and the dependencies in this directory's
`pyproject.toml`. The existing anonymous telemetry runtime still supports
Python 3.8+. Botocore's CRT extra supports existing AWS CLI login-session
profiles as well as the normal SDK credential chain.

For an explicit credential check from the plugin directory:

```sh
uv run --project scripts/telemetry/auth \
  python scripts/telemetry/auth/identity.py --profile my-existing-profile
```

This command queries STS and prints only a status or bounded error code.
It does not print the account, credentials, proof, or profile. Omit `--profile`
to use the SDK's configured environment and default profile.

Do not run it automatically for anonymous reporting or opt-out. Account setup
can return the account to an in-process sharing page through `setup()`.

## Caller API

Add the enclosing `telemetry` directory to the runtime's module path. The
sharing adapter owns the persisted choice and the endpoint configuration.
The two public operations are:

| Operation | Input | Output |
| --- | --- | --- |
| `AwsAccountReporter(audience, profile_name=None)` | Trusted deployment audience and selected SDK profile | Lazy reporter; construction does not resolve credentials |
| `reporter.setup()` | No additional input | `AccountIdentity(account_id, partition)` for the local sharing page |
| `reporter.prepare_report(payload, selected_account)` | Complete unsigned request and account from the accepted choice | `PreparedReport` containing canonical payload bytes and signed STS headers |
| `prepared.request_body()` | No additional input | UTF-8 JSON bytes with the top-level `awsIdentityProof` |
| `error.as_result()` | A caught `AccountReportingError` | Identity-free `{"status": ..., "reasonCode": ...}` for the adapter |

During account setup:

```python
from auth import AccountReportingError, AwsAccountReporter

try:
    reporter = AwsAccountReporter(
        audience=configured_reporting_audience,
        profile_name=selected_profile,
    )
    account = reporter.setup()
except AccountReportingError as error:
    result_for_adapter = error.as_result()
else:
    # Pass this result only to the local sharing page, never the agent.
    result_for_page = {"status": "READY", "awsAccountId": account.account_id}
```

Only after the user accepts the choice does the sharing adapter atomically
save the account, selected profile and notice version. The helper does not
write that preference record.

A later hook or CLI process reconstructs the selection from the validated
accepted record:

```python
from auth import AccountIdentity, AccountReportingError, AwsAccountReporter

# The adapter has already checked ACCEPTED, AWS_ACCOUNT and the notice policy.
account = AccountIdentity(accepted_state["expectedAwsAccountId"])
reporter = AwsAccountReporter(
    audience=configured_reporting_audience,
    profile_name=accepted_state.get("awsProfile"),
)
prepared = reporter.prepare_report(
    {
        **existing_request,
        "reportingMode": "AWS_ACCOUNT",
        "expectedAwsAccountId": account.account_id,
        "noticeVersion": accepted_state["noticeVersion"],
    },
    selected_account=account,
)
body_for_transport = prepared.request_body()
```

Use the saved profile, including an intentional default-profile selection.
Do not substitute a newly discovered profile or account. `prepare_report()`
does not call `GetCallerIdentity`. It obtains a fresh frozen credential
snapshot from the SDK provider on every call. A provider may itself contact
STS, refresh an SSO session, or run a configured `credential_process`.

The selected account remains fixed when credentials refresh. The reporting
API must compare it with the account returned by STS. An account mismatch
requires explicit account setup; it must not silently select a new account
or downgrade the event to anonymous reporting.

`AccountReportingError.code` contains a bounded diagnostic. Exceptions,
reporter representations, and prepared-report representations exclude
credential and proof values. The SDK's sensitive diagnostic loggers are
filtered during these calls without changing other callers' log levels.
Do not print or persist `prepared.headers`, `prepared.payload`, or the result
of `request_body()`.

### Error results

Catch `AccountReportingError` around construction, setup, account
reconstruction and proof preparation. `as_result()` returns the following
stable categories:

| `reasonCode` | `status` | Adapter action |
| --- | --- | --- |
| `CREDENTIALS_UNAVAILABLE`, `SIGN_IN_REQUIRED` | `SIGN_IN_REQUIRED` | Skip this event; offer sign-in on a later interactive invocation |
| `ACCOUNT_CHANGED`, `ACCOUNT_SELECTION_REQUIRED`, `ACCOUNT_REPORTING_REQUIRED` | `SETUP_REQUIRED` | Require a new explicit sharing/account choice |
| `INVALID_ACCOUNT`, `INVALID_PROFILE`, `NOTICE_VERSION_REQUIRED` | `SETUP_REQUIRED` | Treat the saved setup as incomplete or invalid |
| `PYTHON_VERSION_UNSUPPORTED`, `SDK_UNAVAILABLE` | `ERROR` | Report a bounded runtime-availability error |
| `INVALID_AUDIENCE`, `AMBIGUOUS_PROFILE`, `UNSUPPORTED_PARTITION` | `ERROR` | Correct the deployment or caller configuration |
| `IDENTITY_UNAVAILABLE`, `IDENTITY_RESPONSE_INVALID` | `ERROR` | Leave setup pending; do not save a successful account |
| `PAYLOAD_ALREADY_SIGNED`, `PAYLOAD_INVALID`, `PAYLOAD_TOO_LARGE` | `ERROR` | Skip the malformed event |
| `PROOF_INVALID`, `PROOF_UNAVAILABLE`, `INTERNAL_ERROR` | `ERROR` | Skip the failed preparation |

Every error result contains only `status` and `reasonCode`. Unknown error
details are normalized to `INTERNAL_ERROR`. These are local helper outcomes;
they are not HTTP results from the reporting API. The adapter continues
migration work on all of them and does not change the event to anonymous mode.

## Proof contract

- The commercial-partition target is fixed at
  `POST https://sts.us-east-1.amazonaws.com/`.
- The STS body is exactly
  `Action=GetCallerIdentity&Version=2011-06-15`.
- The audience comes from trusted endpoint configuration and has the form
  `startup-advisor:<deployment-id>:report:v1`. There is no default production
  audience and no caller-supplied STS URL.
- The digest is lowercase SHA-256 of RFC 8785 canonical UTF-8 request bytes,
  before adding the top-level `awsIdentityProof`.
- The digest covers `reportingMode`, `expectedAwsAccountId`, `noticeVersion`,
  and the rest of the request. The helper rejects an already-signed input.
- The output adds `awsIdentityProof` with `version: 1` and a lowercase
  `headers` map. All supplied headers except `authorization` are signed.
- The signed headers include `host`, `content-type`, `x-amz-date`,
  `x-startup-advisor-audience`, and `x-startup-advisor-event-sha256`.
  Temporary credentials also include the signed `x-amz-security-token`.
- The secret access key stays in the local process. Profile names and
  server-owned `identity`, `eventId`, and `receivedAt` fields are rejected
  from the request.

Both the canonical request and complete encoded request are bounded at
64 KiB. Missing values stay absent, arrays keep their order, and strings
are not normalized. Non-finite numbers, invalid Unicode and unsafe integers
are rejected by the canonicalizer. The API still owns event-schema and
notice-policy validation.

The receiver owns signature validation through STS, account comparison,
proof age, clock skew, replay storage and notice/source policy. A local
signature is not evidence that the server accepted or stored an event.
No sender or automatic retry behavior is included here.

### Request lifetime and verifier examples

Prepare the proof immediately before sending. Do not queue or persist a
`PreparedReport`, reuse it for another payload, or treat preparation as a
successful send. The proposed verifier limits are a 120-second proof age
and 30-second future clock skew. A reused proof may be rejected even while
it remains fresh.

The same payload, credentials and signing second produce the same signature.
The sender owns response handling. Under the proposed contract, it may retry
once only for the API's explicit pre-publication `VERIFICATION_UNAVAILABLE`
result, after advancing to a later signing second. It must not blindly retry
a timeout, unknown outcome, `PROOF_REPLAY` or `PUBLICATION_UNCERTAIN`.

The repository's `test/fixtures/account-reporting-signed-v1.json` provides
complete long-lived and temporary-credential examples for a verifier:

- Synthetic access key, secret and optional session token.
- Fixed signing time and complete request with `awsIdentityProof`.
- Expected canonical payload, payload digest, canonical STS request,
  string-to-sign and final signature.

The keys do not exist in AWS and the timestamp is fixed. Use the fixture's
clock for deterministic verification tests; these are not requests to send
to STS. The companion canonicalization vectors cover Unicode, number
encoding, object ordering and missing versus null fields.

## Provider and caller boundaries

This component creates no credential files or token store. Configured SDK
providers may maintain their existing caches. No credentials are copied into
the sharing preference file.

The default session's AssumeRole MFA prompt is replaced with a
`SIGN_IN_REQUIRED` result; an adapter must handle interactive sign-in separately.
SDK providers can still perform network calls, and a user-configured
`credential_process` has no built-in Botocore timeout. Background adapters must
run the helper with closed stdin and a bounded process lifetime. The explicit
STS setup request has 3-second connect/read timeouts and one attempt; these
limits do not bound provider resolution.

An injected SDK `session` is intended for tests or an adapter that owns its
session configuration. The adapter is responsible for making that session
noninteractive. Other AWS partitions are not enabled by this draft.

## Validation

From the plugin directory:

```sh
uv run --project scripts/telemetry/auth --with pytest \
  python -m pytest scripts/telemetry/test -k account_reporting -q
uv run --no-project --with pytest \
  python -m pytest scripts/telemetry/test -q
python3 scripts/telemetry/sync_bundles.py --check
```

Tests use synthetic credentials and stub STS. They do not read a developer's
AWS credentials or send requests to AWS. Real reporting API interoperability,
supported-host checks, and approved endpoint/notice configuration remain
integration requirements.

The repository also includes shared canonicalization vectors in
`scripts/telemetry/test/fixtures/account-reporting-v1.json`. They cover reordered
objects, Unicode key ordering, number encoding, absent/null fields, and a full
request whose top-level proof is excluded from the digest.
