# AWS End User Messaging: Customer go-to-production guide

> The onboarding quickstarts run in constrained modes — an RCS test agent reaches only verified
> testers, the SMS sandbox reaches only verified destination numbers under a low spend limit, and
> Notify Basic has per-day and per-country limits. This guide is the production procedures for
> lifting those constraints: exiting the SMS sandbox, launching RCS in a country with carrier
> monitoring and SMS fallback, upgrading Notify to Advanced, and the production hygiene every
> identity needs. It does NOT repeat the registration lifecycle itself (create → derive fields →
> fill → submit → poll → recover from denial) — that engine lives in
> [references/registration-core-engine.md](registration-core-engine.md), and which
> registration a country needs is a live-discovery question answered by
> [references/registration-requirements-by-country.md](registration-requirements-by-country.md).

You run every command yourself. The user provides inputs and confirms results. Production
reviews run from about a day to several months — submit correctly, set expectations, and leave
the user a monitoring loop. Stop and consult the Failure modes table on any error.

## Session state

| Value | Format | Source |
|---|---|---|
| `REGION` | e.g. `us-east-1` | same as the quickstart |
| `VDN_ID` | `vdn-...` | CreateVerifiedDestinationNumber response |
| `PHONE_NUMBER_ID` | `phone-...` | RequestPhoneNumber response |
| `POOL_ID` | `pool-...` | CreatePool response |
| `AGENT_ID` | `rcs-...` | from the RCS quickstart, if continuing |

## Prerequisites

- AWS account with the AWS End User Messaging SMS and Voice service enabled.
- IAM role with least-privilege `sms-voice:` permissions for the actions used below (for example
  `DescribeAccountAttributes`, `DescribeSpendLimits`, `SetTextMessageSpendLimitOverride`,
  `CreateVerifiedDestinationNumber`, `RequestPhoneNumber`, `CreatePool`,
  `AssociateOriginationIdentity`, `PutKeyword`, `DescribeRcsAgentCountryLaunchStatus`,
  `DescribeNotifyConfigurations`). Scope the policy to the actions the chosen path uses; do not
  grant `sms-voice:*` or `*FullAccess`. Prefer assuming an IAM role with ephemeral credentials
  over long-lived access keys.
- Validate all input parameters (region, phone numbers in E.164, ISO country code, spend
  amounts) before calling APIs.
- These operations are available through the AWS MCP Server, which provides sandboxed execution,
  audit logging, and observability. When the MCP server is not available, use the AWS CLI
  commands shown below.
- Confirm the AWS CLI is available (`aws --version`). On CLI v1, URL-valued fields need the
  `--cli-input-json` form and `aws logs tail` is unavailable.

## Choose the path

Ask the user what they need to send, to whom, and where:

| The user wants | Path |
|---|---|
| SMS to real customers | A. Exit the SMS sandbox, then get a registered origination identity |
| A registered number, short code, or sender ID | The registration engine — [references/registration-core-engine.md](registration-core-engine.md) |
| RCS to real customers | B. Country launch on the agent, with monitoring and fallback |
| Notify at higher volume or more countries | C. Advanced tier upgrade |

Paths compose: a production RCS agent should sit in a pool with an SMS number for fallback — set
up the SMS identity before or alongside the RCS launch. Never quote a review ETA from memory —
get the current one from the live sources in
[references/registration-requirements-by-country.md](registration-requirements-by-country.md).

## Path A — Exit the SMS sandbox

New accounts start in the SMS sandbox: sends reach only verified destination numbers, and spend
is capped at a low per-month default. This is account-plus-region state, independent of any
registration. Check the current values live:

```bash
aws pinpoint-sms-voice-v2 describe-account-attributes --region <REGION>
aws pinpoint-sms-voice-v2 describe-spend-limits --region <REGION>
```

Exiting is a Support case (quota: "SMS Production Access"), per region — a console step: Support
Center → Create case → Service limit increase → Pinpoint SMS. The case asks for use case
description, website, expected volume, and opt-in process. Answer specifically; vague opt-in
descriptions are the top rejection cause.

While still sandboxed, add test recipients with the three-step verification flow (the code send
requires an ACTIVE origination identity in the account, or use simulator numbers — simulator-to-simulator
only). Provide the destination in E.164 format (e.g., `+12065550123`):

```bash
aws pinpoint-sms-voice-v2 create-verified-destination-number \
  --destination-phone-number <PHONE_E164> --region <REGION>
aws pinpoint-sms-voice-v2 send-destination-number-verification-code \
  --verified-destination-number-id <VDN_ID> --verification-channel TEXT \
  --origination-identity <ACTIVE_ORIGINATOR> --region <REGION>
aws pinpoint-sms-voice-v2 verify-destination-number \
  --verified-destination-number-id <VDN_ID> --verification-code <CODE> --region <REGION>
```

Raise the spend limit as part of, or after, the same case — the account limit is a Support
change; the enforced limit is then self-serve. This is a REQUIRED step, not optional: even after
the sandbox is lifted, sends still fail at the low sandbox spend cap until you raise it. Set it
above expected monthly volume:

```bash
aws pinpoint-sms-voice-v2 set-text-message-spend-limit-override --monthly-limit <AMOUNT> --region <REGION>
```

Sandbox exit removes the destination restriction but does NOT provide an origination identity
for countries that require one — that is the registration engine, and whether the destination
country requires one is a live-discovery question:
[references/registration-requirements-by-country.md](registration-requirements-by-country.md).

## Path B — RCS production launch (carrier monitoring and fallback)

The RCS launch registration itself runs through the core engine
([references/registration-core-engine.md](registration-core-engine.md), RCS launch
section — `ASSOCIATE_BEFORE_SUBMIT`). This section covers the production operations AROUND that
registration: monitoring carrier status and setting up SMS fallback. Carrier review runs for
months; set that expectation up front.

Once the launch registration is submitted, monitor per-carrier progress:

```bash
aws pinpoint-sms-voice-v2 describe-rcs-agent-country-launch-status \
  --rcs-agent-id <AGENT_ID> --region <REGION>
```

Carrier statuses are `PENDING`, `ACTIVE`, or `REJECTED`; the country aggregate is `PENDING`,
`PARTIAL`, `ACTIVE`, or `REJECTED`. You can send in a country as soon as ONE carrier is
`ACTIVE` — recipients on non-approved carriers get SMS fallback if a pool is set up.

Set up a fallback pool (strongly recommended). The pool must contain BOTH the RCS agent AND at
least one SMS-capable number — an agent-only pool cannot fall back:

```bash
aws pinpoint-sms-voice-v2 create-pool \
  --origination-identity <AGENT_ID> --iso-country-code <ISO2> \
  --message-type TRANSACTIONAL --region <REGION>
aws pinpoint-sms-voice-v2 associate-origination-identity \
  --pool-id <POOL_ID> --origination-identity <PHONE_NUMBER_ID> \
  --iso-country-code <ISO2> --region <REGION>
```

Then send via `--origination-identity <POOL_ID>`. Fallback behavior: RCS is tried first; if no
delivery signal within a short interval, SMS goes out and the RCS message is revoked (rare dual
delivery is possible — both billed). Sticky sending pins each destination to its last-working
channel for about a day, with periodic RCS retries. Keywords and the two-way SNS destination
live on the agent (shared across all countries); brand assets live per registration.

**Two fallback mechanisms — pick per use case.** The pool above gives *automatic* fallback: when
you send via `SendTextMessage` through a pool holding the agent + an SMS number, RCS is tried
first and SMS goes out on failure, reusing the same body. For finer control, `SendRcsMessage` also
takes an explicit per-message `--fallback-configuration`:

```bash
aws pinpoint-sms-voice-v2 send-rcs-message \
  --destination-phone-number <PHONE_E164> --origination-identity <AGENT_ID> \
  --rcs-message-content '{"Content":{"TextMessage":{"Body":"<rich body>"}}}' \
  --time-to-live 60 \
  --fallback-configuration '{"Channel":"SMS","MessageBody":"<concise SMS copy>","OriginationIdentity":"<PHONE_OR_SENDER_ID>"}' \
  --region <REGION>
```

Per-message fallback differs from the pool path: it fires on *immediate* RCS failure OR when a
`--time-to-live` timer expires (useful for OTPs and time-sensitive sends); it can fall back to
**SMS or MMS** (`Channel`); and you supply **separate, tailored** content — the fallback body has a
shorter character limit than the RCS body, so write concise copy and inline any URLs from
suggestion chips. `OriginationIdentity` must be a phone number or sender ID (not a pool or agent);
omit it and a pooled send auto-selects one. Use the pool path for zero-config coarse fallback; use
per-message when you need MMS, tailored copy, or TTL-based expiry. Confirm the current character
limits and field constraints from the linked doc or the API's validation error output rather than
assuming fixed values. See
[RCS per-message fallback](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-fallback-per-message.html).

## Path C — Notify Basic to Advanced

Needed only for higher volume or TPS, or countries outside the Basic set. Check
`CustomerOwnedIdentityRequired` via `list-notify-countries` — some Advanced countries also
require your own identity from the registration engine; the country lists are live data (see
[references/registration-requirements-by-country.md](registration-requirements-by-country.md)).

Registration type names drift — before using them, discover the current `NOTIFY_*` type name
live rather than trusting any name verbatim:

```bash
aws pinpoint-sms-voice-v2 describe-registration-type-definitions --region <REGION> \
  --query "RegistrationTypeDefinitions[?contains(RegistrationType,'NOTIFY')].RegistrationType"
```

Use the returned tier-upgrade type as `<NOTIFY_UPGRADE_TYPE>` in the create call:

```bash
aws pinpoint-sms-voice-v2 create-registration \
  --registration-type <NOTIFY_UPGRADE_TYPE> --region <REGION>
```

A separate brand-verification type (matching `NOTIFY_*` in the discovery output above) resolves a
configuration stuck in `REQUIRES_VERIFICATION`. Derive fields, populate (brand verification and
proof of opt-in flow), and submit through the core engine. Track the upgrade via
`TierUpgradeStatus` on `describe-notify-configurations`: `BASIC`, `PENDING_UPGRADE`, `ADVANCED`,
or `REJECTED`.

## Production hygiene (all paths)

Apply to every production identity:

1. **Keywords** — set HELP (must include a support contact) and STOP (must confirm cessation) on
   every long code and short code. `put-keyword` requires `--origination-identity`, `--keyword`,
   and `--keyword-message`; `--keyword-action` is optional (`AUTOMATIC_RESPONSE` or `OPT_OUT`):
   `aws pinpoint-sms-voice-v2 put-keyword --origination-identity <ID> --keyword HELP --keyword-message "<help text with support contact>" --keyword-action AUTOMATIC_RESPONSE --region <REGION>`
   (repeat for the STOP keyword with a cessation-confirmation message, using `--keyword-action OPT_OUT`).
2. **Event visibility** — create a configuration set with an event destination and pass
   `--configuration-set-name` on every send. Without it there are NO delivery events, and they
   are not retroactive. Use an SNS topic with KMS encryption (`alias/aws/sns` or a customer-managed
   key) and add a resource policy with `aws:SourceAccount` and `aws:SourceArn` condition keys to
   prevent confused-deputy access. Restrict `sns:Subscribe` via the topic policy to known,
   authorized AWS accounts or endpoint patterns so only trusted recipients receive delivery
   metadata, and subscribe HTTPS-only endpoints.
3. **Protect configuration** — block countries you never send to.
4. **Pool per use case** — put identities for one use case in one pool and send via the pool;
   mixing use cases on shared identities risks carrier filtering.
5. **Resource policy** — required if another service (for example SNS) will use the number, even
   in the same account. Include `aws:SourceAccount` and `aws:SourceArn` condition keys in the
   policy to prevent confused-deputy access.
6. **Rate-limit outbound sends** — implement application-side throttling (per-recipient and
   per-minute caps) to prevent abuse, SMS pumping, and toll fraud, and to stay within service
   quotas.
7. **CloudWatch alarms** — create alarms on key metrics: send-failure-rate exceeding a threshold,
   monthly spend approaching the `set-text-message-spend-limit-override` value, and throttling
   events. Without alarms, failures and cost overruns are detected only after impact. Route alarm
   actions to an SNS topic with KMS encryption and the same `aws:SourceAccount`/`aws:SourceArn`
   condition keys and authorized-subscriber controls (restricted `sns:Subscribe`, HTTPS-only
   subscriptions) as the event destination in item 2 — alarm notifications about failure rates,
   spend, and throttling carry operationally sensitive information.

## Verify

Production-readiness checklist — confirm each with a describe call, not from memory:

- [ ] Account attributes show the sandbox removed (Path A).
- [ ] Registration(s) `COMPLETE`; identity `ACTIVE`, or at least one carrier `ACTIVE` for RCS,
  or `ADVANCED` for Notify.
- [ ] HELP and STOP keywords set on every production identity.
- [ ] A configuration set is attached to sends and a test send produces a delivery event.
- [ ] Spend limit raised above expected monthly volume.
- [ ] For RCS: the fallback pool contains the agent AND an SMS number.
- [ ] CloudTrail logging enabled for `sms-voice` API calls; CloudTrail logs and CloudWatch Log
  groups encrypted with a KMS CMK.

**Demonstrable outcome.** The artifacts are state transitions — capture them as before/after
describe output the user can see: the sandbox attribute clearing, a carrier row moving to
`ACTIVE`, `TierUpgradeStatus` reaching `ADVANCED`, then one test send that produces a delivery
event. Reviews take days to months, so most sessions end mid-transition; when yours does, say so
and leave the user the exact poll command.

## Next steps

- Registration lifecycle mechanics: [references/registration-core-engine.md](registration-core-engine.md)
- Which registration a country needs, and its requirements — always live: [references/registration-requirements-by-country.md](registration-requirements-by-country.md)
- RCS test agent quickstart: [references/hello-rcs-test-agent.md](hello-rcs-test-agent.md)
- Notify OTP quickstart: [references/hello-notify-otp.md](hello-notify-otp.md)

## Security Considerations

- **Least-privilege IAM.** Scope policies to the specific `sms-voice:` actions each path uses;
  never use `*FullAccess` or `sms-voice:*`.
- **Ephemeral credentials.** Assume an IAM role with ephemeral credentials; never embed
  long-lived access keys in code, config, or environment variables.
- **Event destinations.** Use SNS topics with KMS encryption, `aws:SourceAccount` and
  `aws:SourceArn` condition keys, and HTTPS-only subscriptions. Message bodies and delivery
  metadata may contain sensitive information — encrypt CloudTrail logs and CloudWatch Log groups
  with a KMS CMK.
- **CloudTrail.** Enable CloudTrail logging for `sms-voice` API calls in the account to maintain
  an audit trail of production operations — sandbox exits, spend-limit changes, pool associations,
  and keyword configurations.
- **Consent and spend.** Message only recipients who have opted in; honor STOP. Raise spend
  limits deliberately and monitor them.
- **Input validation.** Validate all user inputs (E.164 for phones, ISO country code, spend
  amounts, URL scheme allowlist) before passing them to APIs.
- **AWS security references.** These recommendations follow AWS security best practices — see
  [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) for
  least-privilege and ephemeral credentials, and
  [AWS KMS Best Practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html)
  for encryption of CloudTrail logs, CloudWatch Log groups, and SNS topics.

## Failure modes

| Error / symptom | Cause | Fix |
|---|---|---|
| Sends fail right after sandbox exit | Spend limit still at the sandbox default | Raise it with `set-text-message-spend-limit-override` (Path A) |
| RCS country send fails, aggregate `PARTIAL` | Recipient's carrier not `ACTIVE`, no fallback pool | Build the Path B fallback pool (agent + SMS number) |
| Throughput stuck at the default MPS after approval | MPS increases are not automatic | Separate Support request for MPS |
| Sends show "NOTICE"/"Unverified" sender | Registration not yet `COMPLETE` | Wait for `COMPLETE`; see the core engine |
| Notify upgrade stuck | Awaiting review, or `REQUIRES_VERIFICATION` | Poll `TierUpgradeStatus`; if verification is required, discover the brand-verification type via `describe-registration-type-definitions` (match `NOTIFY_*` containing `BRAND_VERIFICATION`) and submit through the core engine |
| Sender ID sends fail despite approval | Case-sensitivity mismatch — carriers match exact casing | Use the exact casing from the registration record |

## Cleanup (destructive — confirm with the user first)

Production identities bill monthly while owned. To stop: `release-phone-number`,
`release-sender-id`, or `delete-registration` — all irreversible. Confirm with the user, and
note released numbers may not be recoverable.
