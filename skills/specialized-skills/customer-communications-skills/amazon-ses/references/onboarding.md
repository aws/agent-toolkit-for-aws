# SES Onboarding

> Operations below use AWS CLI syntax. For sandboxed execution, use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html).
> SKILL.md's "Invariants" own the domain-setup-complete gate, the sandbox recipient rule, and the
> value-validation rules. Each consent gate below is owned by the step that performs the action.

One flow. Onboarding a domain that is not yet set up starts with the **[Default setup](#default-setup)**: it builds the
recommended setup for the domain and proves SES accepts one simulator message. A request that only
asks to set up email ends there, in the account's current production-access state. When the user
also wants production access, a send to a real inbox, a resume, or a `MessageRejected` diagnosis,
continue with the **[Full journey](#full-journey)**, which builds on the default setup. A default
the request explicitly forbids (for example "do not enable VDM" or "do not change account
suppression") is skipped and reported.

## Session state

Carry these forward; re-read rather than assume. If `PROFILE` is set, append `--profile '{PROFILE}'`
to every command; every `sesv2` command takes `--region '{REGION}'`. Validate and quote every
substituted value first.

| Value | Source |
|---|---|
| `REGION`, `PROFILE` | per SKILL.md's Critical Rules; `PROFILE` only if the user names one |
| `DOMAIN` | user |
| `MAIL_FROM` | `bounce.{DOMAIN}` unless the user names a subdomain |
| `FROM_ADDRESS` | defaulted to `onboarding@{DOMAIN}`, stated not asked, overridable |
| `TEST_RECIPIENT` | user, collected at Step 1, Step 4 or Step 5 |
| `MAIL_TYPE`, `WEBSITE_URL` | user, Step 3 only |
| `CASE_ID`, `MAX_24_HOUR_SEND` | `get-account` → `Details.ReviewDetails.CaseId`, `SendQuota.Max24HourSend` (`-1` = unlimited) |
| `CHOSEN_RECIPIENT_OPTION`, `CHOSEN_RECIPIENT` | bound in Step 4's "Sandbox recipient options"; with `ProductionAccessEnabled: true`, from `TEST_RECIPIENT` (never a null) or asked in Step 5 |
| `PA_DECLINED` | `true` when the user declines production access at Step 3 |
| `ACCOUNT_ID`, `MESSAGE_ID` | `sts get-caller-identity`; `send-email` |

## Required IAM actions

This file's calls only; the domain-setup leg in `setting-up-ses-domain-identity.md` has its own list,
and the full journey needs the union. Scope as SKILL.md describes. Never wildcard Action names; use `Resource: "*"` only where
SKILL.md explicitly requires it.

- **Always read:** `sts:GetCallerIdentity`, `ses:GetAccount`, `ses:ListEmailIdentities`,
  `ses:GetEmailIdentity`. Scope `GetEmailIdentity` to every identity read: the domain, and on the
  full journey `identity/{CHOSEN_RECIPIENT}` (option 1) or the other verified domain (option 3).
- **Default setup adds:** reads `ses:ListConfigurationSets`, `ses:GetConfigurationSet`,
  `ses:GetConfigurationSetEventDestinations`, `route53:ListHostedZones`,
  `route53:ListHostedZonesByName`, `route53:GetHostedZone`, `route53:ListResourceRecordSets`,
  `route53:GetChange`; writes when missing `ses:CreateEmailIdentity`,
  `ses:PutEmailIdentityMailFromAttributes`, `ses:PutAccountSuppressionAttributes`,
  `ses:PutAccountVdmAttributes`, `ses:CreateConfigurationSet`,
  `ses:PutEmailIdentityConfigurationSetAttributes`, `route53:ChangeResourceRecordSets`,
  `ses:SendEmail`. Scope `GetHostedZone`, `ListResourceRecordSets` and `ChangeResourceRecordSets` to the matched
  zone and `GetChange` to the returned change (`arn:aws:route53:::change/{change_id}`, with the
  `/change/` prefix of the returned `ChangeInfo.Id` stripped, as for the hosted-zone ID);
  `ListHostedZones` and `ListHostedZonesByName` need `Resource: "*"`, as SKILL.md lists.
  Never grant `ses:PutAccountDetails` for the default setup alone.
- **Full journey:** the Default setup list, plus only for the scope being run:
  `ses:PutAccountDetails` (Step 3); `ses:SendEmail` (Step 5); `ses:CreateEmailIdentity` scoped to
  `identity/{CHOSEN_RECIPIENT}` for sandbox option 1.
- **Pin `ses:SendEmail`** to the identity that authorizes `{FROM_ADDRESS}` — `identity/{DOMAIN}`,
  the address's own identity, or another verified domain — with the exact-match
  `ses:FromAddress` condition:

  ```json
  {
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": "arn:aws:ses:{REGION}:{ACCOUNT_ID}:identity/{DOMAIN}",
    "Condition": {"StringEquals": {"ses:FromAddress": "{FROM_ADDRESS}"}}
  }
  ```

  When the send uses a configuration set, including the identity's default one, also list
  `arn:aws:ses:{REGION}:{ACCOUNT_ID}:configuration-set/{name}` in `Resource`.

## Default setup

An opinionated default, not a menu. Read before writing, reuse matching state, and stop on
conflicts rather than overwriting anything.

### Inputs and consent

Ask every question once, upfront. If the domain is missing, ask for it first. Then run the
read-only discovery (step 1 below) and, before any write, ask in ONE question for everything
still missing:

1. permission to `CREATE` only the missing SES records in the named Route 53 zone
   (`{zone_name}`, `{hosted_zone_id}`), replacing or deleting nothing;
2. how to handle any conflict the discovery found.

If the request already gave that permission, or no Route 53 zone hosts the domain, and discovery
found no conflict, ask nothing. The one simulator check needs no question: it goes to an AWS test
address and reaches no mailbox. Do not ask the user to choose a MAIL FROM name, DKIM mode, DMARC policy,
configuration-set name, TLS policy, suppression reasons, or test recipient, and do not collect a website URL or mail type before the full journey's Step 3. After that, execute the whole path in the same turn without stopping to
ask again; stop only for a service error, a bounded verification timeout, or a new conflict.

### Fixed defaults

| Setting | Value |
|---|---|
| Identity | one domain identity |
| DKIM | Easy DKIM, RSA 2048, signing enabled |
| Custom MAIL FROM | `{MAIL_FROM}` (`bounce.{DOMAIN}` unless the user names one), failure behavior `USE_DEFAULT_VALUE` |
| DMARC | preserve valid `p=quarantine` or `p=reject`; otherwise `v=DMARC1; p=none` |
| Account suppression | `BOUNCE` and `COMPLAINT` |
| VDM | enabled; when this flow enables it, engagement metrics disabled |
| Configuration set | one dedicated set, named by the rule below |
| Delivery TLS | `OPTIONAL` |
| Configuration-set sending, reputation metrics | enabled |
| Sending pool | shared; do not set `SendingPoolName` |
| Per-set suppression and VDM | inherit the account; omit both options |
| Tracking and event destinations | none |
| Test send | from `onboarding@{DOMAIN}` to `success@simulator.amazonses.com` |

Do not create an email-address identity, dedicated IP or pool, tenant, multi-Region endpoint,
template, contact list, tracking domain, event destination, or any inbound resource. Do not call
`PutAccountDetails`.

### Configuration-set name

1. Remove one trailing dot and lowercase the domain.
2. Convert an internationalized domain to canonical UTS #46 non-transitional Punycode.
3. Replace each dot with an underscore and prepend `default-`.
4. If that exceeds 64 characters, use `default-`, the rightmost 45 characters of the step-3 underscored
   domain, `-`, and the first 10 lowercase hex characters of SHA-256 over the canonical domain.

Examples: `shop.example.com` → `default-shop_example_com`; `bücher.example` →
`default-xn--bcher-kva_example`. Only overflow needs hashing: through AWS MCP a pure local
`hashlib.sha256` in `aws___run_script` is allowed (no AWS calls); otherwise use a local SHA-256
tool. If the runtime cannot do UTS #46 conversion, ask for the canonical Punycode rather than use
another IDNA algorithm.

### Execute the setup

- **AWS MCP:** use `aws___run_script`. Do not run the AWS CLI through a local shell. Keep the
  Route 53 change batch and the final `SendEmail` in separate calls; related reads may share one
  script. Keep each script short — no long sleeps; do later status reads in separate calls. If a call returns a `task_id`, poll `aws___get_tasks` with that ID
  until it is terminal and keep the completed result.
- **Without AWS MCP:** use AWS CLI v2 (`aws sesv2 <operation-in-kebab-case>`,
  `aws route53 change-resource-record-sets`) with the same sequence and gates, inline JSON
  payloads, and the DNS change and send as separate commands with their raw responses kept.

1. Read `GetCallerIdentity`, `GetAccount`, `ListEmailIdentities`, `ListConfigurationSets`, and
   the identity if it exists. Find and check the Route 53 zone and read all its records as
   `setting-up-ses-domain-identity.md`'s Route 53 steps 1-4 describe. Stop on disabled sending,
   an unhealthy enforcement state, or an ambiguous or non-authoritative zone. A different existing
   MAIL FROM, or a record this setup would have to replace (including an MX or TXT at `{MAIL_FROM}`), is a conflict for the upfront question; this path never changes the
   subdomain or replaces a record. If the account already has email identities other than
   `{DOMAIN}`, its current account suppression is the customer's: when it differs from the table,
   name it as a conflict and keep it unless the user agrees. If `GetAccount` shows no
   `PricingAttributes.CurrentPlan` (absent or `NONE`), enabling VDM adds a per-email charge: make
   that a conflict too, asked in plain words with the [pricing](https://aws.amazon.com/ses/pricing/)
   link. Otherwise VDM is included and needs no question.
2. Create the domain identity only if absent. For existing state, follow
   `setting-up-ses-domain-identity.md` and change only missing settings. Never rotate successful
   DKIM.
3. Configure `{MAIL_FROM}` as custom MAIL FROM with `USE_DEFAULT_VALUE`, using that file's
   MAIL FROM collision rules.
4. Build one Route 53 `CREATE` batch of only the absent records: the three SES DKIM CNAMEs, the
   MAIL FROM MX and SPF TXT, and DMARC when no valid policy exists. TTL 1800. Never `UPSERT` or
   `DELETE`. Show the zone and the exact batch before the call; the permission is the upfront
   one.
5. Read `GetAccount`. Skip any account setting that step 1 raised as a conflict and the user chose
   to keep, and any the request explicitly forbids changing; record each skipped default. Otherwise: if suppression is not exactly `["BOUNCE", "COMPLAINT"]`, you MUST call
   `PutAccountSuppressionAttributes` with those reasons. If `VdmAttributes.VdmEnabled` is not
   `ENABLED`, you MUST call `PutAccountVdmAttributes` with `VdmEnabled: ENABLED` and
   `DashboardAttributes.EngagementMetrics: DISABLED`, preserving any existing Guardian setting.
   Re-read `GetAccount` and do not continue until each is confirmed, or is the existing value the user chose to keep; if a write or the read
   fails, stop and report that default as incomplete. An engagement-metrics setting on an
   already-enabled VDM account is preserved and is not a gate.
6. Read the configuration-set name before creating it. Reuse it only if every setting matches the
   table; otherwise stop on the conflict. When absent, call `CreateConfigurationSet` with:

   ```json
   {
     "ConfigurationSetName": "<deterministic name from the configuration-set name rule>",
     "DeliveryOptions": {"TlsPolicy": "OPTIONAL"},
     "ReputationOptions": {"ReputationMetricsEnabled": true},
     "SendingOptions": {"SendingEnabled": true}
   }
   ```

   `OPTIONAL` means SES tries TLS but sends unencrypted when the receiver cannot negotiate it;
   the completion summary says so. Omit `SendingPoolName`, `TrackingOptions`,
   `SuppressionOptions`, `VdmOptions`, `ArchivingOptions`, and event destinations. Associate the
   set with `PutEmailIdentityConfigurationSetAttributes`; that association is authoritative. If the
   identity already has a different default configuration set, that is a conflict for the upfront
   question; never replace it without the user's agreement.
7. After Route 53 reports `INSYNC`, re-read `GetEmailIdentity` at most once a minute for up to 10
   minutes. Wait within the same turn: do not end the turn, schedule a later check, or hand the wait
   to the user. Continue only when it is verified for sending, DKIM is `SUCCESS`, and MAIL FROM is
   `SUCCESS`; otherwise report the outstanding status and a resumable next step.
8. Hard gate: re-read the account, identity, configuration set, event destinations, and records.
   You MUST NOT send unless VDM is `ENABLED` and suppression is `BOUNCE` plus `COMPLAINT` — for
   either one, the existing value also passes when the user chose to keep it or the request
   forbids changing it — and every identity, configuration-set, and DNS value
   matches the table (with `{MAIL_FROM}` as the MAIL FROM). Repair or stop; never send after
   observing a mismatch.
9. Send exactly one message from `onboarding@{DOMAIN}` to `success@simulator.amazonses.com` with
   `SendEmail`, without `ConfigurationSetName`, so the identity's default association is used.

### Completion

Return a short summary naming the domain, `{MAIL_FROM}`, the dedicated configuration set, the
account protections applied, and the From address. Report every skipped default
(kept by the user or forbidden by the request), its current value, and that it differs from the
recommended default. Include the exact `MessageId` from the
`SendEmail` result and say "SES accepted one simulator test message to
`success@simulator.amazonses.com`." Do not say "I sent",
"message sent", "successfully sent", or "delivered". State that the `MessageId` does not prove
inbox delivery, placement, or recipient-side authentication. State in one line that delivery TLS
is `OPTIONAL`, so mail to a receiver without TLS is sent unencrypted, and that the set can be
switched to `REQUIRE` later if the user prefers such mail to bounce. If any required state or the
raw `MessageId` is missing, do not call the setup successful.

## Full journey

The full journey builds on the default setup: its Step 2 is the Default setup. Every step is
**check, then do**: read state first; if a step is already satisfied, say so in one
line and move on. **Identity state is evaluated before review state**; a `Details.ReviewDetails`
value never overrides it. Step 3 needs the full domain-setup-complete gate; a send needs only the
narrower send prerequisite in Step 2.

| State you read | Do this |
|---|---|
| `ProductionAccessEnabled: true` and `SendQuota.SentLast24Hours > 0` | Already sending in this Region (the count is Region-wide, not per identity). A new domain or Region → Step 2, then Step 5. A question about an existing send → [Failure modes](#failure-modes), or the DKIM / MAIL FROM troubleshooting in `setting-up-ses-domain-identity.md`. If unclear, ask which. |
| `ProductionAccessEnabled: true`, no sending yet | Skip Steps 3 and 4 (identity rows still apply). Bind `CHOSEN_RECIPIENT` from `TEST_RECIPIENT` or ask in Step 5. |
| No domain identity | Step 2. |
| Identity exists and the domain-setup-complete gate passes | Skip Step 2: a domain that is already set up keeps its existing configuration; apply the default setup's account and configuration-set defaults only if the user asks. |
| Identity exists but the gate fails — DKIM not `SUCCESS`, MAIL FROM `PENDING`/`FAILED`/`TEMPORARY_FAILURE` or absent, or `VerifiedForSendingStatus: false` | Step 2, which adds only what is missing; never re-create the identity or re-run DKIM signing. Name the field that failed. Whether a send may still proceed is Step 2's send prerequisite. |
| `Details.ReviewDetails.Status: PENDING` | Do not resubmit. Meet the send prerequisite first, then Step 4. |
| `GRANTED` | Skip Step 3. `ProductionAccessEnabled` alone governs the sandbox: `true` → Step 5; still `false` → Step 4's "Sandbox recipient options", then Step 5. |
| `DENIED` | Do not resubmit; Step 4 owns this branch. |
| `FAILED` | AWS did not receive it; Step 3 may resubmit, then Step 4. |
| `Details.ReviewDetails` absent | No request yet in this Region. Step 3 once the gate passes, only if the user wants production access and `PA_DECLINED` is unset; otherwise Step 4's "Sandbox recipient options", then Step 5. |

### Step 1: Preflight — one question set, then read state

Run `aws sts get-caller-identity` **before** composing questions; if it fails, say how to refresh
credentials and ask which account and Region to use once back. Resolve and state the Region per
SKILL.md before any `aws sesv2` call. Then ask in ONE message for only what the request needs:

| The user asked for… | Ask only for | Defer |
|---|---|---|
| Domain setup only | sending domain | everything else |
| Full journey to a delivered email | sending domain; test recipient | mail type and website URL, to Step 3 |
| Production access | sending domain | mail type and website URL to Step 3; test recipient to Step 5 |

When domain setup is in scope, the Default setup's read-only discovery and its one upfront
question cover DNS and conflicts; add the test recipient to that question when a real send is in
scope.

Never ask for the From address: default it to `onboarding@{DOMAIN}`, state it in the same message,
and invite an override (bounce notices go there by default). An override not at `{DOMAIN}` must be
at another identity verified in this Region. **Never ask for mail type or website URL before Step
3**, even when the user says they want production access.

```bash
aws sesv2 get-account --region '{REGION}'
aws sesv2 list-email-identities --region '{REGION}'
```

From `get-account` read `ProductionAccessEnabled`, `Details.ReviewDetails.Status`,
`SendQuota.SentLast24Hours` and `SendQuota.MaxSendRate`; record `CASE_ID` and `MAX_24_HOUR_SEND`;
route with the table. `SendingEnabled: false` or `EnforcementStatus` `PROBATION`/`SHUTDOWN` means
this workflow cannot proceed — surface it and stop. If `{DOMAIN}` is listed, read it with
`get-email-identity` before deciding anything.

### Step 2: Verify the sending domain

Run the [Default setup](#default-setup) for `{DOMAIN}`, including its simulator check; for an
existing identity it adds only what is missing. Then continue here. SES detects records on its own;
if records resolve while the status has not moved, use `setting-up-ses-domain-identity.md`'s DKIM
troubleshooting.

Step 2 is complete when SKILL.md's domain-setup-complete gate passes in one
`aws sesv2 get-email-identity --email-identity '{DOMAIN}' --region '{REGION}'` response.

**Send prerequisite.** A send may proceed when the identity is verified for sending with
`DkimAttributes.Status: SUCCESS` **and** either `MailFromDomainStatus` is `SUCCESS` or it is
unresolved with `BehaviorOnMxFailure: USE_DEFAULT_VALUE`. It may not proceed while MAIL FROM is
unresolved with `REJECT_MESSAGE` (SES returns `MailFromDomainNotVerified`), or while
`MailFromAttributes` is absent (custom MAIL FROM is a MUST here, so go back through Step 2). In the
`USE_DEFAULT_VALUE` case, say the `amazonses.com` envelope sender will not align with `{DOMAIN}`, so
DMARC must pass on DKIM alone. Never report the domain complete in either unresolved state. DKIM
`SUCCESS` is required because this journey promises an authenticated email; if the user wants to
send sooner, say what they give up — never relax it silently.

**Scope gate.** A domain-setup-only request ends here: report the result and any outstanding field,
say in one line that production access and a test send are available on request, and stop.

### Step 3: Request production access

**MUST** confirm the domain-setup-complete gate first — AWS documents that verifying the domain first
helps approval. **MUST** get explicit consent; the API makes the console's acknowledgement on the
user's behalf. Say this and wait for a yes:

> Submitting this tells AWS you will only send to people who asked for your mail, and that you
> have a way to handle bounces and complaints. It submits a production-access request for AWS review, and AWS documents
> that you cannot edit your details until the review completes — there is no API to cancel or
> withdraw it. Shall I submit it? (You can also fill in the form yourself in the SES console.)

If the user declines, accept it, set `PA_DECLINED`, do not collect `MAIL_TYPE` or `WEBSITE_URL`, do
not raise it again this session, and go to Step 4's "Sandbox recipient options", then Step 5.

Collect, explaining each in one line and never inventing either: `MAIL_TYPE` — `TRANSACTIONAL`
(mail a user's own action triggers) or `MARKETING` (mail to a list); `WEBSITE_URL` — the business
site the mail relates to, not necessarily at the sending domain.

```bash
aws sesv2 put-account-details \
  --production-access-enabled \
  --mail-type '{MAIL_TYPE}' \
  --website-url '{WEBSITE_URL}' \
  --region '{REGION}'
```

- Do NOT pass the deprecated `UseCaseDescription`.
- Optional `--additional-contact-email-addresses` (up to 4) and `--contact-language EN|JA`: offer only
  addresses controlled by authorized members of the user's own team.
- Success is an empty HTTP 200 — no case ID, no status.
- Whenever you present or run this command, tell the user how to check status afterwards
  (`aws sesv2 get-account`, `Details.ReviewDetails.Status`) and that they can already send today,
  naming all three options from "Sandbox recipient options" in that numbering.
- A repeat while a review is pending returns `ConflictException` (409); there is no cancel.
  `BadRequestException` (400) is an invalid input — see [Failure modes](#failure-modes).

### Step 4: Check the decision

Read the full `aws sesv2 get-account --region '{REGION}'` response. **`ProductionAccessEnabled`
alone decides the sandbox**: while it is `false`, "Sandbox recipient options" applies whatever
`Details.ReviewDetails.Status` says, `GRANTED` included. When it is `true`, bind `CHOSEN_RECIPIENT`
from `TEST_RECIPIENT` (or ask in Step 5), offer to change it, and go to Step 5.

- **`PENDING`** — do not tell the user to wait. AWS documents an initial response within 96 hours,
  may grant within that window "If we're able to do so", and may take longer; never promise a
  decision in 96 hours. Open the sandbox options with: *"Your request is in. In the meantime you can
  test everything end to end right now — you just have to send to a recipient AWS already knows
  about."*
- **`DENIED`** — do not resubmit. Read the Support case at `CASE_ID`; it may be absent or closed, so
  also point the user to the SES account dashboard and a new Support case referencing the denial.
  Open the sandbox options with: *"The review came back denied — nothing about sandbox testing is
  lost."*
- **`FAILED`** — AWS did not receive it; Step 3 may resubmit, returning here as `PENDING`.
- **`Details.ReviewDetails` absent** — no request yet. Step 3 if the user wants production access;
  otherwise, or with `PA_DECLINED`, open the sandbox options with: *"You're still in the SES sandbox,
  so the first send has to go to a recipient AWS already knows about."*

### Sandbox recipient options

Applies whenever `ProductionAccessEnabled` is `false`. No sandbox path reaches Step 5 without binding
`CHOSEN_RECIPIENT_OPTION` and `CHOSEN_RECIPIENT` here and reading them back.

> Pick whichever fits:
>
> 1. **Verify the mailbox you want to test with, as its own email identity** — *recommended.* AWS
>    sends a verification message to that address; open it and click the link, which expires 24
>    hours after the message was sent. This is the option that lets you read the delivered message
>    and check its authentication headers.
> 2. **`success@simulator.amazonses.com`** — the Amazon SES mailbox simulator. Nothing lands in a
>    real inbox, so it is a fast check of the send path only, with no authentication headers to
>    read. It works while the account is in the sandbox, is billed like any other send, and does
>    not count against the daily sending quota (the sending rate still applies).
> 3. **A real mailbox at a domain already verified in this account** — only if such a mailbox
>    actually exists. Verifying a domain in SES creates no mailboxes and no MX records, so an
>    address at the domain you just set up receives nothing unless that domain already has real
>    mail hosting. If it does, name that mailbox; no extra verification is needed.

Never invent an address, derive one from `{DOMAIN}`, or substitute the simulator for an option the
user did not choose. Option 1 needs an address the user can open (ask in the same message if
missing); option 3 needs a real mailbox at a verified domain.

- **Option 1:** `get-email-identity` on `{TEST_RECIPIENT}`. `NotFoundException` → `create-email-identity`
  (sends the verification message); verified → Step 5; unverified → do not re-create. Do not send
  until `VerifiedForSendingStatus` reads `true` — sending first returns `MessageRejected`. Bound the
  wait: suggest the spam folder; the link expires after 24 hours; there is no SESv2 resend
  (`AlreadyExistsException`), so an expired link is renewed from the SES console.
- **Option 3:** the address's domain must be an identity in this Region (`list-email-identities`)
  and verified (`get-email-identity`); otherwise offer option 1 or 2. No API can confirm the mailbox
  exists — confirm it with the user.

If the user asks about limits, answer from the `SendQuota` values read in Step 1 (counted by
recipients; `-1` is unlimited). Do not raise limits unprompted.

### Step 5: Send the first email

A send must have been asked for. Re-read `get-email-identity` for `{DOMAIN}` and apply Step 2's send
prerequisite; if it fails, name the field and return to Step 2 — a permitted recipient does not
substitute for it. If `{FROM_ADDRESS}` is unbound, default it to `onboarding@{DOMAIN}` and state it.
If `{CHOSEN_RECIPIENT}` is unbound, ask once now — in the sandbox only through "Sandbox recipient
options". Never invent a recipient.

**MUST ask before sending:**

> The next command sends a real email from `{FROM_ADDRESS}` to `{CHOSEN_RECIPIENT}`.
> Ready?

```bash
aws sesv2 send-email \
  --from-email-address '{FROM_ADDRESS}' \
  --destination '{"ToAddresses":["{CHOSEN_RECIPIENT}"]}' \
  --content '{"Simple":{"Subject":{"Data":"SES first send check"},"Body":{"Text":{"Data":"If you are reading this, Amazon SES is set up correctly."}}}}' \
  --region '{REGION}'
```

Bounce and complaint notices go to `{FROM_ADDRESS}` unless `--feedback-forwarding-email-address`
names a monitored team address at `{DOMAIN}`; omit it rather than guess. Say that SES bills per
recipient ([pricing](https://aws.amazon.com/ses/pricing/)) before sending.

**A `MessageId` means SES accepted the message, not that it was delivered.** Say so, then:

| Situation | How you know it worked |
|---|---|
| Production access, option 1, or option 3 | Open the message's raw headers (Gmail: **More** → **Show original**) and confirm `Authentication-Results` shows `dkim=pass`, `spf=pass` and `dmarc=pass`. `dmarc=pass` needs a published `_dmarc` record. |
| Option 2 (simulator) | No inbox and no `Authentication-Results`: the `MessageId` proves the send path only. Return to "Sandbox recipient options" for option 1 or 3 before calling authentication confirmed. |
| Option 3 but nothing arrives | No real mailbox there; go back and pick option 1. |

If nothing arrived, check spam, then [Failure modes](#failure-modes).

### Step 6: Optional extras

Only after the test send lands, offer once: dedicated IPs and tenants, one line each. Do not raise
pricing plans.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `MessageRejected: Email address is not verified` | Read `ProductionAccessEnabled` and the named address. In the sandbox with the recipient named: the restriction is on the recipient. Otherwise the sender is unverified (required in production too). | Recipient: "Sandbox recipient options". Sender: verify that identity in this Region or send from `{DOMAIN}`; if it is verified but DKIM is not `SUCCESS`, finish DKIM first. |
| `MessageRejected` right after verifying a recipient | Link not clicked. | Wait for `VerifiedForSendingStatus: true`. |
| `AlreadyExistsException` on `create-email-identity` | Identity exists in this Region. | Read it and add only what is missing. |
| `ConflictException` on `put-account-details` | A review is in flight. | Read the status; do not resubmit. |
| `BadRequestException` on `put-account-details` | Invalid input. | `MailType` `MARKETING`/`TRANSACTIONAL`; `WebsiteURL` 1–1000 chars; ≤4 contacts; `ContactLanguage` `EN`/`JA`. |
| `MailFromDomainStatus: FAILED` / `TEMPORARY_FAILURE` | `FAILED` is terminal; `TEMPORARY_FAILURE` is still searching. | In `setting-up-ses-domain-identity.md`'s MAIL FROM step: exactly one MX on the subdomain; restart setup only for `FAILED`. |
| `ThrottlingException`, `Daily message quota exceeded` | `SentLast24Hours` reached `Max24HourSend` (not applicable when it is `-1`). | Rolling 24-hour window; production access is not an instant fix. |
| `ThrottlingException`, `Maximum sending rate exceeded` | Over `MaxSendRate`. | Slow down, one recipient per call, retry after up to 10 minutes. |
| `MessageId` but nothing arrived | Accepted ≠ delivered. | Spam, DMARC policy, the forwarded bounce notice. |
| `dmarc=none`/`fail`, `spf=fail`/`neutral` | Missing or misaligned DNS. | Fix in `setting-up-ses-domain-identity.md` (DMARC and MAIL FROM steps); send from the verified domain. |
| `AccessDeniedException` | Missing `ses:` permissions. | Compare with "Required IAM actions" here and in the domain-setup file. |
| Works in one Region only | Identities, production access and quotas are per-Region. | Repeat per Region. |
| Every send fails | `SendingEnabled: false`. | This workflow cannot change it; contact AWS Support. |
