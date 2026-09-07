# AWS End User Messaging: Registration requirements by country — live discovery

> Country- and number-type-specific registration requirements change over time: registration
> types appear, field sets grow, review ETAs shift, and countries move between
> optional-registration and required-registration. Do not rely on this file's — or any cached
> copy's — per-country specifics. Inspect the live sources at the start of every run. This file
> is deliberately mostly pointers: the discovery commands that stay current, and the official
> docs pages that hold the human-readable per-country rules. The universal mechanics of working
> a registration (state machines, field filling, denial recovery) live in
> [references/registration-core-engine.md](registration-core-engine.md) — this file
> answers only "which type, and what does it require."

You run every command yourself. **Your FIRST action MUST be to run
`describe-registration-type-definitions` for the region — before you write any part of the
answer. You MUST NOT state which registration a country needs, or name any registration type,
until that command's output has returned this session; then you MUST run
`describe-registration-field-definitions` on the matched type for the authoritative field set.**
A memorized or example-derived answer — including anything from this file's examples or your own
training knowledge — is a defect, no matter how plausible. Before stating any conclusion you MUST
also state the reconciliation rule (where docs and live field definitions disagree, the live
definitions win). Treat the API output as the source of truth. Stop and
consult the Failure modes table on any error.

## Session state

| Value | Format | Source |
|---|---|---|
| `REGION` | e.g. `us-east-1` | ask the user (default `us-east-1`) |
| `ISO2` | ISO 3166-1 alpha-2, e.g. `XX` | the user's target country |
| `REG_TYPE` | e.g. `<ISO2>_RCS_LAUNCH_REGISTRATION` | matched from discovery below |

## Prerequisites

- AWS account with the AWS End User Messaging SMS and Voice service enabled.
- IAM role with least-privilege permissions for the read-only `sms-voice:` describe actions used
  below (`DescribeRegistrationTypeDefinitions`, `DescribeRegistrationFieldDefinitions`,
  `DescribeRegistrationSectionDefinitions`). Prefer assuming an IAM role with ephemeral
  credentials over long-lived access keys.
- Validate all input parameters (region, ISO country code, registration type) before calling APIs.
- These operations are available through the AWS MCP Server, which provides sandboxed execution,
  audit logging, and observability. When the MCP server is not available, use the AWS CLI
  commands shown below.
- Confirm the AWS CLI is available (`aws --version`). On CLI v1, URL-valued fields and
  `aws logs tail` behave differently — the core-engine file flags v1 forms where they matter.

## Live discovery — the API is the authority

Three read-only calls give the current truth for the account and region.

First, list every registration type available in the region:

```bash
aws pinpoint-sms-voice-v2 describe-registration-type-definitions --region <REGION>
```

Match the returned names against the user's goal:

| Goal | Type-name patterns to look for |
|---|---|
| RCS launch in a country | `<ISO2>_RCS_LAUNCH_REGISTRATION`; also `TEST_RCS_LAUNCH_REGISTRATION` for the testing flow |
| Sender ID in a country | `<ISO2>_SENDER_ID_REGISTRATION` |
| Short code in a country | `<ISO2>_SHORT_CODE_REGISTRATION` |
| Long code in a country | `<ISO2>_LONG_CODE_REGISTRATION` |
| US 10DLC | `US_TEN_DLC_*` (brand registration, brand vetting, campaign registration) |
| US toll-free | `US_TOLL_FREE_REGISTRATION` |
| Notify tier / brand | `NOTIFY_*` (filter the live output for types containing `NOTIFY` — e.g. the tier-upgrade and brand-verification variants) |

Save the matched type name as `REG_TYPE`, plus its `SupportedAssociations` and
`AssociationBehavior`. If no type matches the country/identity combination, that combination is
not registrable via the API — check the docs pages below for whether it needs a Support case or
is unsupported.

Then derive the authoritative field set for that type, and optionally its section grouping:

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type <REG_TYPE> --region <REGION>
aws pinpoint-sms-voice-v2 describe-registration-section-definitions \
  --registration-type <REG_TYPE> --region <REGION>
```

The field definitions output is the only authoritative statement of what a registration
requires: field paths, types (TEXT/SELECT/ATTACHMENT), REQUIRED vs OPTIONAL, and validation
constraints. It is paginated — walk all pages. Do not filter this output; conditional field
requirements depend on context from the complete definition shape.

## Official docs pages — the human-readable per-country rules

Fetch the relevant page(s) each run over HTTPS (append `.md` to any slug for a markdown variant):

| Page | URL | What it holds |
|---|---|---|
| Registration overview | <https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations.html> | Which registrations exist per country/identity type; console forms vs Support cases; status-vs-sending-behavior rules |
| Review ETAs | <https://docs.aws.amazon.com/sms-voice/latest/userguide/registration-eta.html> | Estimated review time per country + identity type |
| Sender ID rules | <https://docs.aws.amazon.com/sms-voice/latest/userguide/sender-id.html> | Sender ID character rules, registered-vs-dynamic per country, the casing rule |
| Country capabilities hub | <https://docs.aws.amazon.com/sms-voice/latest/userguide/phone-numbers-sms-support-by-country.html> | SMS/MMS capabilities and restrictions; links to per-country supported-countries tables |
| RCS country launches | <https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-country-launch.html> | Per-country RCS launch process: use-case categories, carrier states, timelines |

## The reconciliation rule

1. Run the discovery commands for the target country and identity type.
2. Fetch the matching docs page(s) for the human context: prerequisites, evidence to prepare
   (opt-in proof, compliance video, letters of authorization), ETAs, and country specifics.
3. Reconcile. Where the docs and the live field definitions disagree — a field the docs do not
   mention, a type the docs still call by an old name — the live field definitions win. They are
   the tiebreaker; docs lag the service.
4. Execute the mechanics from [references/registration-core-engine.md](registration-core-engine.md)
   with the discovered `REG_TYPE` and field set.

## Worked example: "the user wants to send SMS to a country `<ISO2>`"

This example uses the placeholder `<ISO2>` for the user's target country. It never names a real
country or a real registration type — substitute what your own discovery returns this run.

Discover what the region offers for `<ISO2>`:

```bash
aws pinpoint-sms-voice-v2 describe-registration-type-definitions --region <REGION>
```

Inspect the returned `RegistrationType` names for entries starting with `<ISO2>_`. Then read, each
run: the country capabilities hub (follow its supported-countries link to the `<ISO2>` row for
which origination identity types that country supports, whether registration is required, two-way
support); the registration overview page (is there an `<ISO2>` form, or a Support-case country);
and the ETA page (review time for the identity type you land on).

Conclude from what the pages and `describe-registration-type-definitions` returned this run —
for example, whether `<ISO2>` supports sender IDs without registration or a registered long code
via an `<ISO2>_LONG_CODE_REGISTRATION` type with an N-day review. State it from this run's output,
never from this example, and never from prior knowledge of any specific country.

**State the reconciliation rule in your answer.** Treat `describe-registration-field-definitions`
as the authoritative field set, and say so explicitly: *where the documentation pages and the
live field definitions disagree, the live definitions win, because the docs lag the service.*
Name `describe-registration-field-definitions` as the source of the field list. If the live
output disagrees with the pages, follow this rule and note the discrepancy to the user. Then
run the machinery: [references/registration-core-engine.md](registration-core-engine.md).

## Verify

**Demonstrable outcome.** This file's artifact is the live discovery itself, on screen this run:
the `describe-registration-type-definitions` output naming the matched `REG_TYPE`, the
`describe-registration-field-definitions` field list for it (all pages), and the
one-paragraph conclusion derived for the user's country from this run's output — "country XX
needs `<REG_TYPE>`; N required fields including `<example fields>`; review ETA per the docs
page." If the live output and the docs pages disagreed, the note of that discrepancy is part of
the deliverable. Nothing here is demonstrable from memory — if the discovery commands were not
run this session, the job is not done; leave the user the three read-only calls above as the
exact sequence that produces the answer.

## Next steps

- The mechanics — state machines, field filling, denial recovery:
  [references/registration-core-engine.md](registration-core-engine.md)
- Quickstart RCS test agent (verified testers only): [references/hello-rcs-test-agent.md](hello-rcs-test-agent.md)
- Quickstart Notify OTP: [references/hello-notify-otp.md](hello-notify-otp.md)

## Security Considerations

- **Least-privilege IAM.** This flow is read-only discovery — scope the policy to the specific
  `sms-voice:` describe actions used above (`DescribeRegistrationTypeDefinitions`,
  `DescribeRegistrationFieldDefinitions`, `DescribeRegistrationSectionDefinitions`); never use
  `*FullAccess` or `sms-voice:*`.
- **Ephemeral credentials.** Assume an IAM role with ephemeral credentials; never embed
  long-lived access keys in code, config, or environment variables.
- **Input validation.** Validate all inputs (region, ISO country code, registration type)
  before passing them to APIs, and fetch the docs pages over HTTPS.
- **Logging.** Enable CloudTrail logging for `sms-voice` API calls in the account and encrypt
  CloudTrail logs and CloudWatch Log groups with a KMS CMK to maintain an audit trail of discovery
  queries — who queried registration type definitions and when — for compliance and incident
  response.
- **AWS security references.** These recommendations follow AWS security best practices — see
  [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) for
  least-privilege and ephemeral credentials, and
  [AWS KMS Best Practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html)
  for encrypting CloudTrail logs and CloudWatch Log groups.

## Failure modes

| Error / symptom | Cause | Fix |
|---|---|---|
| A remembered or documented registration type name is rejected as invalid | Type names drift (e.g. a stale `MANAGED_ROUTES_BRAND_VERIFICATION`) | `describe-registration-type-definitions` — use only names it returns |
| Submit fails on a field no doc mentioned | Field sets grow over time; docs lag | Re-derive with `describe-registration-field-definitions`; the live schema is the tiebreaker |
| A docs URL above returns 404 | Docs pages get reorganized | Search the user guide root (`what-is-service.html`) for the topic's current slug; do not skip the fetch |
| No `<ISO2>_*` type exists for the target country | Combination not API-registrable | Check the registration overview page — Support-case-only country, or unsupported |
