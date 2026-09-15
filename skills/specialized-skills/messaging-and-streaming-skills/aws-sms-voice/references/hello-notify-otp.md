# Hello AWS End User Messaging: Send an OTP with AWS End User Messaging Notify in minutes

> By the end of this task, the user has received a real one-time-passcode text on their phone,
> sent through AWS End User Messaging Notify. No phone number to buy, no carrier registration,
> no wait times — AWS manages the sending identities, routing, and pre-approved message
> templates. Working time is about 5 minutes end to end. This is the fastest possible path to a
> production-grade verification message; the Basic tier works in many countries out of the box (use `list-notify-countries` to see the current set).

You run every command yourself. The user provides inputs and confirms what arrives on their
phone. Stop and consult the Failure modes table on any error.

## Session state

| Value | Format | Source |
|---|---|---|
| `REGION` | e.g. `us-east-1` | ask the user (default `us-east-1`) |
| `PROFILE` | AWS CLI profile name | credential bootstrap (may be empty) |
| `DISPLAY_NAME` | ≤15 chars; letters, digits, `_`, `-`, space | ask the user (their brand/app name) |
| `NC_ID` | `notify-` + 32 hex | CreateNotifyConfiguration response |
| `TEMPLATE_ID` | e.g. `notify-code-verification-english-001` | DescribeNotifyTemplates response |
| `PHONE` | E.164 | ask the user (their real phone) |

## Prerequisites

1. **AWS CLI** — check the version: `aws --version`. v2 recommended; v1 verified working
   for every command in this task.
2. **Credentials** — run `aws sts get-caller-identity --region <REGION>`. Pass `--region` so
   STS uses the regional endpoint (`sts.<region>.amazonaws.com`); the global endpoint
   (`sts.amazonaws.com`) is legacy and best avoided. If it fails, ask the user how they
   authenticate. Prefer assuming an IAM role with ephemeral credentials over long-lived access keys (named profile / IAM Identity Center (SSO) / access keys), configure accordingly, and from then on
   append `--profile <PROFILE>` to EVERY command if a profile is in play. Enable AWS CloudTrail in
   the account so all `pinpoint-sms-voice-v2` API calls (notably `SendNotifyTextMessage`) are
   logged — OTP flows are abuse-sensitive (toll fraud, OTP pumping) and need an audit trail.
3. **Service access** — read-only check:
   `aws pinpoint-sms-voice-v2 describe-notify-configurations --region <REGION>`
   Minimum IAM actions for this task: `sms-voice:CreateNotifyConfiguration`,
   `DescribeNotifyConfigurations`, `DescribeNotifyTemplates`, `ListNotifyCountries`,
   `SendNotifyTextMessage`, and `DeleteNotifyConfiguration` (for cleanup).
4. **Input validation** — validate display name (≤15 chars, allowed characters), phone (E.164), and country before mutating APIs.
5. **Inputs** — ask the user for: a display name (their brand or app name, 15 chars max — this
   is what recipients may see, and it goes through an automated brand review; a made-up brand
   is fine for testing, but a well-known third-party brand name will be flagged), their phone
   number in E.164, and the destination country if not obvious from the number.

## Steps

### 1. Create the Notify configuration

```bash
aws pinpoint-sms-voice-v2 create-notify-configuration \
  --display-name "<DISPLAY_NAME>" \
  --use-case CODE_VERIFICATION \
  --enabled-channels SMS \
  --region <REGION>
```

Save `NotifyConfigurationId` as `NC_ID`. (`CODE_VERIFICATION` is the only use case Notify
supports.)

### 2. Poll until ACTIVE

Most configurations activate within seconds. Only `ACTIVE` can send.

```bash
aws pinpoint-sms-voice-v2 describe-notify-configurations \
  --notify-configuration-ids <NC_ID> --region <REGION> \
  --query 'NotifyConfigurations[0].Status'
```

- `PENDING` → wait a few seconds and re-poll (control-plane APIs are rate-limited to ~1
  request/second — do not poll faster than every 2–3 seconds).
- `ACTIVE` → proceed.
- `REQUIRES_VERIFICATION` or `REJECTED` → see Failure modes.

### 3. Pick a template

You cannot write your own message — Notify uses AWS-managed, pre-approved templates. List the
SMS templates available on the Basic tier:

```bash
aws pinpoint-sms-voice-v2 describe-notify-templates \
  --filters '[{"Name":"channels","Values":["SMS"]},{"Name":"tier-access","Values":["BASIC"]}]' \
  --region <REGION>
```

The unfiltered payload is very large (every template lists all supported countries) — add a
`language-code` filter to keep it manageable, e.g. append
`{"Name":"language-code","Values":["en"]}` to the filters array — values are lowercase ISO
codes (`en`, `es`, `fr-CA`, ...); uppercase fails with `INVALID_FILTER_VALUES`. Save the chosen `TemplateId`
as `TEMPLATE_ID`, and read its variable definitions: variables marked `CUSTOMER` you supply;
variables marked `SYSTEM` are filled automatically — notably `brandName`, which comes from
your configuration's display name, so you do NOT pass it. Most English code-verification
templates take only `code` (must match `^\d{4,8}$`), but some variants require additional
variables (e.g. `time`) — read the `Variables` list of the specific template you pick rather
than assuming; a missing required variable fails the send with `ValidationException`.

### 4. Confirm the destination country is enabled (cheap, avoids a failed send)

```bash
aws pinpoint-sms-voice-v2 list-notify-countries \
  --channels SMS --tier BASIC --region <REGION>
```

The Basic tier covers a curated set of countries — the `list-notify-countries` output above
shows the current list. If the user's country is not listed, tell them — the fix is the Advanced tier (see Next steps), not a
different command.

### 5. Dry run, then send

Generate a 6-digit code (this is a demo — in production your app generates and stores it).
First validate everything without sending or charging:

```bash
aws pinpoint-sms-voice-v2 send-notify-text-message \
  --notify-configuration-id <NC_ID> \
  --destination-phone-number "<PHONE>" \
  --template-id <TEMPLATE_ID> \
  --template-variables '{"code":"482913"}' \
  --dry-run \
  --region <REGION>
```

(All template variable values are passed as strings, even numbers and booleans.)

> **Production note:** In production, pass template variables via `--cli-input-json` from a
> file rather than inline to avoid shell history exposure. Ensure CloudTrail logs are encrypted
> with a KMS CMK since they will contain OTP codes.

A passing dry run returns the same shape as a real send — `MessageId` plus
`ResolvedMessageBody` (the rendered text) — with nothing transmitted or charged. If the dry
run passes, confirm with the user — "the next command sends a real text to `<PHONE>`, ready?" —
then send for real by repeating the command **without** `--dry-run`. If the user only wanted
validation, stop here: the dry run already proved the configuration end to end.

Save `MessageId`. The response also contains `ResolvedMessageBody` — the exact rendered text.
Show it to the user and ask: "This should be on your phone now — did it arrive?"
Treat `ResolvedMessageBody` as sensitive — it contains the OTP code. Do not log or persist it beyond this confirmation.

## Verify

- The user confirms the OTP text arrived and the code matches.
- `ResolvedMessageBody` in the response shows the rendered template.

Print a summary: display name, `NC_ID`, `TEMPLATE_ID`, region, and the daily-limit reminder
below.

**Testing note**: Notify enforces a non-adjustable per-day cap per destination number, applied at both the configuration and account level — check the applicable value in the Service Quotas console or documentation. Don't burn the day's budget on retries.

## Next steps

- **Production hardening for OTP**: set a default template
  (`update-notify-configuration --default-template-id <TEMPLATE_ID>`), route delivery events to
  your systems via a configuration set (the configuration-sets-and-event-destinations guide),
  and read the Notify compliance prerequisites (terms, privacy policy, opt-in) before real traffic.
- **Observability (required before production)**: Enable CloudTrail logging and attach a
  configuration set with an event destination (SNS with SSE/KMS, `aws:SourceArn`/`aws:SourceAccount` condition keys, and authorized subscriptions only; CloudWatch Logs encrypted with a
  KMS CMK, or Kinesis Firehose with server-side encryption) for delivery event
  monitoring. Create CloudWatch alarms on send failure rates and spend
  approaching the daily cap to detect misuse early.
- **Rate-limit OTP verification**: Implement application-side rate limiting on verification
  attempts (max 3–5 per code, lockout after failures) to prevent brute-force attacks.
- **Rate-limit OTP sends**: Implement application-side throttling on send requests (max 1 OTP per
  phone per 60s, progressive backoff) to prevent SMS pumping and toll fraud.
- **Voice OTP**: add `VOICE` to `--enabled-channels`, then `send-notify-voice-message ...
  --voice-id JOANNA`. Format the code as `"4. 8. 2. 9. 1. 3."` so text-to-speech reads digits
  individually.
- **Higher volume / more countries**: upgrade Basic → Advanced (higher daily limits, higher TPS, broader country coverage — see
  applicable limits in the AWS End User Messaging Notify documentation) via a tier-upgrade registration with opt-in proof; review timeline
  per the [ETA page](https://docs.aws.amazon.com/sms-voice/latest/userguide/registration-eta.html): see [references/customer-go-to-production-guide.md](customer-go-to-production-guide.md) (Path C), which discovers the exact registration type live. This is OPTIONAL — Basic is
  production-usable within its limits. Countries that additionally need your own identity are
  live data — see the registration-requirements-by-country guide.
- **Beyond OTP** — conversational and rich messaging needs your own origination identity:
  start with `references/hello-rcs-test-agent.md` or [references/customer-go-to-production-guide.md](customer-go-to-production-guide.md).

## Security Considerations

- **Ephemeral credentials**: Prefer IAM roles over long-lived access keys.
- **OTP codes in logs**: CloudTrail and downstream logs contain OTP codes; encrypt with KMS CMK.
- **Rate limiting**: Throttle both send requests and verification attempts at the application layer.
- **Event destination encryption**: Use SSE/KMS on SNS topics, encrypt CloudWatch Logs, restrict subscriptions.
- **Input validation**: Validate display name, phone (E.164), and country before mutating APIs.

## Failure modes

| Error / symptom | Cause | Fix |
|---|---|---|
| `AccessDeniedException` | Missing IAM actions or expired session | Re-auth; attach the IAM actions from Prerequisites step 3 |
| Status stays `PENDING` | Validation in progress | Re-poll every few seconds; escalate only after several minutes |
| Status `REQUIRES_VERIFICATION` | Brand/display name needs verification (third-party brand names need a letter of authorization ≤30 days old, via a Support case) | Easiest for a demo: create a new configuration with a generic display name |
| Status `REJECTED` | Automated review rejected the display name (profanity, URLs, impersonation) | Read `RejectionReason` in describe output; recreate with a compliant name |
| `ConflictException` on send | Configuration not ACTIVE | Wait for ACTIVE (step 2) |
| `ValidationException` on send | Missing/invalid template variable, malformed E.164, or destination country not enabled | Check required variables against step 3's definitions; re-verify phone format; re-run step 4 |
| `ResourceNotFoundException` | Wrong `NC_ID` or `TEMPLATE_ID` | Re-list and re-save the IDs |
| `ServiceQuotaExceededException` | Daily limit (per-destination and account daily caps (check applicable limits via Service Quotas)) or spend limit hit | Wait for the daily reset; for spend, `SetNotifyMessageSpendLimitOverride` (account-level change — confirm with the user; Notify's override is separate from SMS) |
| Send succeeds but nothing arrives | Carrier filtering or wrong number | Confirm the number; retry once; check delivery events if a configuration set was attached |
| User replies STOP and worries | On AWS-managed identities STOP is informational only for OTP — each new OTP request is an implicit opt-in | No action needed; explain the semantics |

## Cleanup (destructive — confirm with the user first)

```bash
aws pinpoint-sms-voice-v2 delete-notify-configuration \
  --notify-configuration-id <NC_ID> --region <REGION>
```
