# AWS End User Messaging: The core registration engine

> Every registered origination identity — 10DLC brand/campaign, toll-free, short code, sender
> ID, RCS country launch, and Notify tier upgrade — runs through the SAME registration engine.
> This file is that engine: create a registration, derive its field set live, fill every field,
> submit, poll two independent state machines, and recover from a denial by re-filling ALL
> fields. WHICH type a given country and identity needs, and what that type requires, is a
> live-discovery question and is deliberately not here:
> [references/registration-requirements-by-country.md](registration-requirements-by-country.md).
> Production reviews range from about a day to several months by type and country — the job is
> to submit correctly, set expectations, and leave the user a monitoring loop.

You run every command yourself. The user provides inputs and confirms results. Stop and consult
the Failure modes table on any error.

## Session state

| Value | Format | Source |
|---|---|---|
| `REGION` | e.g. `us-east-1` | ask the user (default `us-east-1`) |
| `REG_TYPE` | e.g. `<ISO2>_RCS_LAUNCH_REGISTRATION` | discovery per registration-requirements-by-country |
| `REG_ID` | `registration-...` | CreateRegistration response |
| `RESOURCE_ID` | `rcs-...` / `phone-...` | the resource the registration gates, if any |
| `ATTACHMENT_ID` | `attachment-...` | CreateRegistrationAttachment response, if the schema has ATTACHMENT fields |

## Prerequisites

- AWS account with the AWS End User Messaging SMS and Voice service enabled.
- IAM role with least-privilege `sms-voice:` permissions for the registration actions used below
  (`CreateRegistration`, `CreateRegistrationAssociation`, `DescribeRegistrationFieldDefinitions`,
  `PutRegistrationFieldValue`, `SubmitRegistrationVersion`, `DescribeRegistrations`,
  `CreateRegistrationVersion`, and `RequestPhoneNumber` where a number is acquired). Scope the
  policy to these actions; do not grant `sms-voice:*` or `*FullAccess`. Prefer assuming an IAM
  role with ephemeral credentials over long-lived access keys.
- Validate all input parameters (region, ISO country code, field values, attachment paths)
  before calling APIs.
- These operations are available through the AWS MCP Server, which provides sandboxed execution,
  audit logging, and observability. When the MCP server is not available, use the AWS CLI
  commands shown below.
- Confirm the AWS CLI is available (`aws --version`). On CLI v1, URL-valued TEXT fields fail via
  a legacy paramfile behavior — use the `--cli-input-json` form shown in step 5, which works on
  both versions.

## The engine — one lifecycle for every registration type

### 1. Pick the type

Which registration type the target country and identity type need is discovered live, never
memorized — commands and doc pointers in
[references/registration-requirements-by-country.md](registration-requirements-by-country.md).
Save `REG_TYPE` and the type's `AssociationBehavior`.

### 2. Create, and associate if the resource already exists

```bash
aws pinpoint-sms-voice-v2 create-registration \
  --registration-type <REG_TYPE> --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-association \
  --registration-id <REG_ID> --resource-id <RESOURCE_ID> --region <REGION>
```

Save `RegistrationId` as `REG_ID`. The second call applies only when the type gates an existing
resource (for example, an RCS agent). `AssociationBehavior` on the type definition says when the
association must happen:

- `ASSOCIATE_BEFORE_SUBMIT` — **you MUST link the resource before submitting, or the submission
  is invalid** (RCS agents, including RCS country launches).
- `ASSOCIATE_ON_APPROVAL` — the resource is auto-provisioned on approval (sender IDs — no
  separate request step).
- `ASSOCIATE_AFTER_COMPLETE` — buy or associate the resource only after COMPLETE (phone numbers).

### 3. Derive the field set — the schema is always live

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type <REG_TYPE> --region <REGION>
```

Save per field: `FieldPath`, `FieldType`, `FieldRequirement`, and validation constraints. Field
sets vary by type and drift over time — derive, do not memorize. Do not filter this output;
conditional field requirements depend on the complete definition shape.

### 4. Upload attachments first

Only if the schema has ATTACHMENT fields: one `create-registration-attachment` per file
(`--attachment-body` and `--attachment-url` are mutually exclusive), within the size and format
constraints the field definition reports for that attachment field. Poll to `UPLOAD_COMPLETE`
before any field references the attachment ID. Prefer `--attachment-body` with a local
`fileb://` path over a public URL for documents that contain business-identifying information.

### 5. Fill every field — one call per field, parameter set by the field's type

**Where the values come from depends on the registration type.** For a **TEST** registration
(e.g. `TEST_RCS_LAUNCH_REGISTRATION`, which only reaches verified testers), default to synthetic
placeholder values — do not interview the user field-by-field or run live field discovery to
decide what to ask; go straight to synthetic defaults, then **show the user the full set of
placeholder values and let them opt out** ("these are synthetic; tell me if you'd rather provide
your own for any field") and confirm before submitting. For a **PRODUCTION** registration (10DLC
brand/campaign, toll-free, short code, sender ID, RCS country launch), do NOT use synthetic
values: these are submitted to carrier/partner review and synthetic `.example.com` contacts or an
invented description will be denied. Collect **real but non-sensitive business contacts** from the
user (as the Security Considerations require), show them the full set, and confirm before submit.
In both cases never submit invented data unconfirmed. Treat any real values the user provides as
sensitive business-identifying PII (contact details, legal names, addresses): use them only to
populate the registration and to confirm back — do not echo them into responses or logs beyond
what confirmation requires. Because tooling may log API payloads (CloudTrail data events, MCP
server or agent-framework audit logs), the `put-registration-field-value` values can land in those
logs too — ensure any such log destinations are encrypted with a KMS key so the PII is protected at
the infrastructure layer, not just in the agent's own output: CloudWatch Logs log groups with a KMS
CMK, and the CloudTrail trail's S3 destination bucket with SSE-KMS (a dedicated CMK if the trail
records these data events).

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> \
  --field-path "<FIELD_PATH>" --text-value "<value>" --region <REGION>
```

| FieldType | Parameter |
|---|---|
| TEXT | `--text-value "<value>"` |
| SELECT | `--select-choices "<choice>"` |
| ATTACHMENT | `--registration-attachment-id "<id>"` |

`--field-values` does not exist; do not invent it. SELECT options live under
`SelectValidation.Options` as a list of plain strings. On AWS CLI v1, URL-valued TEXT fields
fail because a legacy paramfile feature fetches `https://` values as remote files — use the
`--cli-input-json` form, which works on both versions:

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --region <REGION> --cli-input-json \
  '{"RegistrationId":"<REG_ID>","FieldPath":"<FIELD_PATH>","TextValue":"https://www.example.com"}'
```

Where a field takes a phone number, provide it in E.164 format (e.g., `+12065550123`).

### 6. Audit, submit, and poll BOTH state machines

Audit what is SET against what is REQUIRED before submitting:

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-values \
  --registration-id <REG_ID> --region <REGION> \
  --query 'RegistrationFieldValues[].FieldPath' --output text | tr '\t' '\n' | sort > /tmp/set.txt
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type <REG_TYPE> --region <REGION> \
  --query "RegistrationFieldDefinitions[].FieldPath" --output text | tr '\t' '\n' | sort > /tmp/req.txt
comm -13 /tmp/set.txt /tmp/req.txt
```

Do not hardcode a filter on the requirement value — derive the field set from the full
definition and let the live schema decide applicability (the same reason you do not filter the
definition output above). Any line printed is a defined field you have not set; confirm from the
field's own definition whether it applies to your case before submitting. Then submit and
**poll BOTH state machines — they move independently, and you MUST check both**: registration
status via `describe-registrations` AND version status via `describe-registration-versions`:

```bash
aws pinpoint-sms-voice-v2 submit-registration-version --registration-id <REG_ID> --region <REGION>
aws pinpoint-sms-voice-v2 describe-registrations --registration-ids <REG_ID> \
  --query 'Registrations[0].RegistrationStatus' --region <REGION>
aws pinpoint-sms-voice-v2 describe-registration-versions --registration-id <REG_ID> --region <REGION>
```

Registration status: `CREATED → SUBMITTED → REVIEWING → COMPLETE`, with branches
`REQUIRES_UPDATES` and `AUTHENTICATION_REQUIRED` (a human step, typically email 2FA). Version
status: `DRAFT → SUBMITTED → REVIEWING → APPROVED | DENIED`. The rules that never vary:

- **Only COMPLETE counts.** While SUBMITTED or REVIEWING, the identity behaves as unregistered —
  messages may go out with a generic "NOTICE"/"Unverified" sender or not at all, by country.
  Never tell the user "submitted, so we're good."
- **Locked while REVIEWING.** No field edits, no disassociation — wait for the verdict or discard
  the version.
- **Denied means a FULL RESET — this is the #1 cause of a second denial.** On
  `REQUIRES_UPDATES`/`DENIED`, read every per-field `DeniedReason` (some types include generated
  fix suggestions — read them), then call `create-registration-version`. **The new version
  starts EMPTY: every field value is reset, not just the denied ones.** You MUST re-run
  `put-registration-field-value` for EVERY field (attachments re-reference by existing ID), then
  re-audit set-vs-required and resubmit. Updating only the denied field on the existing version
  does not work.
- **Billing continues regardless.** Purchased numbers bill monthly whatever the registration
  status; releasing the number is the only off switch.

### 7. Acquire the resource (for `ASSOCIATE_AFTER_COMPLETE` types)

Once COMPLETE, request the number against the registration:

```bash
aws pinpoint-sms-voice-v2 request-phone-number \
  --iso-country-code <ISO2> --message-type TRANSACTIONAL \
  --number-capabilities SMS --number-type <TYPE> \
  --registration-id <REG_ID> --region <REGION>
```

Save `PhoneNumberId`; lifecycle `PENDING → ACTIVE`. Capabilities (SMS/MMS/VOICE) are immutable
after purchase — choose them now. Throughput (MPS) does not auto-raise on approval; increases
are a separate Support request. Which number types a country offers, prerequisite
registrations, and throughput and ETAs are live-discovery questions:
[references/registration-requirements-by-country.md](registration-requirements-by-country.md).

## RCS country launch — the same engine, one wrinkle

A production RCS launch is one more registration type run through the engine above. The test
agent from the RCS quickstart stays; production adds a per-country launch registration to the
SAME agent (`ASSOCIATE_BEFORE_SUBMIT`: associate the agent before submitting). Discover the
launch type for the target country (names follow `<ISO2>_RCS_LAUNCH_REGISTRATION`;
`TEST_RCS_LAUNCH_REGISTRATION` exists for exercising the launch flow against a test device),
create it, associate
the agent, then run steps 3–6. The launch field set is larger than the test registration
(launch details, carrier-tester access instructions, messaging samples, opt-in evidence) and a
compliance video demonstrating the agent's HELP/STOP/opt-in flows is typically required — record
the real agent behavior. Carrier review runs for months; set that expectation up front.

Per-carrier launch monitoring, SMS fallback pools, and production hygiene (keywords,
configuration sets, protect configurations) are covered in
[references/customer-go-to-production-guide.md](customer-go-to-production-guide.md).

## Verify

**Demonstrable outcome.** The engine's artifacts are state transitions — capture them as
before/after describe output the user can see: `RegistrationStatus` reaching `COMPLETE`, the
identity flipping to `ACTIVE`. Confirm each with a describe call, not from memory. Reviews take
days to months, so most sessions end mid-transition. When yours does, say so explicitly and
leave the user the exact poll:

```bash
aws pinpoint-sms-voice-v2 describe-registrations --registration-ids <REG_ID> \
  --region <REGION> --query 'Registrations[0].RegistrationStatus'
```

The day that returns `COMPLETE`, the transition in that output — next to the earlier `REVIEWING`
the user recorded — is the demonstrable finish.

## Next steps

- Which registration type a country needs, and what it requires — always live:
  [references/registration-requirements-by-country.md](registration-requirements-by-country.md)
- RCS test agent quickstart (verified testers only): [references/hello-rcs-test-agent.md](hello-rcs-test-agent.md)
- Notify OTP quickstart: [references/hello-notify-otp.md](hello-notify-otp.md)
- Production launch procedures — sandbox exit, RCS carrier monitoring and fallback pools, Notify
  tier upgrade, production hygiene: [references/customer-go-to-production-guide.md](customer-go-to-production-guide.md)

## Security Considerations

- **Least-privilege IAM.** Scope policies to the specific `sms-voice:` registration actions;
  never use `*FullAccess` or `sms-voice:*`.
- **Ephemeral credentials.** Assume an IAM role with ephemeral credentials; never embed
  long-lived access keys in code, config, or environment variables.
- **Sensitive registration content.** Registration contact fields (email, phone, URLs) and
  attachments are submitted to partner review; use real but non-sensitive business contacts, and
  prefer local `fileb://` attachment bodies over public URLs. Enable CloudTrail logging for
  `sms-voice` API calls and encrypt CloudTrail logs and CloudWatch Log groups with a KMS CMK.
- **Monitoring.** Registrations can sit in `REVIEWING` for weeks or fail silently to
  `REQUIRES_UPDATES`/`DENIED`. Create a CloudWatch alarm or EventBridge rule on registration
  status changes so the user is notified proactively rather than relying solely on manual polling.
  Status-change notifications can carry sensitive business information (e.g. per-field denial
  reasons), so encrypt the notification target: use an SNS topic with KMS encryption
  (`alias/aws/sns` or a customer-managed key), add a resource policy with `aws:SourceAccount` and
  `aws:SourceArn` condition keys to prevent confused-deputy access, restrict `sns:Subscribe` to
  known authorized accounts, and subscribe HTTPS-only endpoints so only authorized personnel
  receive registration status details.
- **Input validation.** Validate all user inputs (E.164 for phones, URL scheme allowlist, length
  checks) before passing them to APIs.
- **AWS security references.** These recommendations follow AWS security best practices — see
  [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) for
  least-privilege and ephemeral credentials, and
  [AWS KMS Best Practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html)
  for encrypting CloudTrail logs and CloudWatch Log groups.

## Failure modes

| Error / symptom | Cause | Fix |
|---|---|---|
| Registration `REQUIRES_UPDATES` | Field(s) denied | `describe-registration-field-values` → per-field `DeniedReason` → `create-registration-version` → re-populate ALL fields → resubmit. Rejection feedback may include generated guidance — read it |
| Registration stuck in REVIEWING | Reviews take days to months by type | Poll daily, not per-minute; give the user the current ETA from the live sources in registration-requirements-by-country |
| Sends show "NOTICE"/"Unverified" sender | Registration not yet COMPLETE | Wait for COMPLETE; only COMPLETE counts |
| `ConflictException` editing a registration | Locked while REVIEWING | Wait for a terminal state, or discard the version |
| Number request fails with a registration error | `ASSOCIATE_AFTER_COMPLETE` type requires COMPLETE before purchase | Finish the registration first, then `request-phone-number` |
| Throughput stuck at default MPS after approval | MPS increases are not automatic | Separate Support request for MPS |
| Registration type name from a doc or memory rejected as invalid | Type names drift | Discover live via `describe-registration-type-definitions` — see registration-requirements-by-country |

## Cleanup (destructive — confirm with the user first)

Registrations and any purchased identities persist until removed; purchased numbers bill monthly
while owned. To stop: `delete-registration`, and `release-phone-number` / `release-sender-id`
for acquired identities — all irreversible. Confirm with the user, and note released numbers may
not be recoverable.

```bash
aws pinpoint-sms-voice-v2 delete-registration --registration-id <REG_ID> --region <REGION>
```
