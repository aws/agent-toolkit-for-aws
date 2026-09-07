# SES Onboarding: Zero to First Delivered Email

> Operations below use AWS CLI syntax. For sandboxed execution, use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html).
> The two risks here — sending on someone's behalf, and the commitments in a production-access request — are
> gated at the steps that perform them. SKILL.md's "Invariants" own the domain-setup-complete gate, the
> sandbox recipient rule, and the value-validation rules.

## Session state

Carry these forward between steps; re-read rather than assume.

| Value | Format | Source |
|---|---|---|
| `REGION` | `us-east-1` | user if named, else `AWS_REGION`, `AWS_DEFAULT_REGION`, then `aws configure get region`; asked for only if none of those resolves |
| `PROFILE` | CLI profile name, may be empty | user only if they name one |
| `DOMAIN` | `example.com` | user |
| `MAIL_FROM` | `mail.example.com` | user, Step 1 |
| `FROM_ADDRESS` | `onboarding@{DOMAIN}` default (stated, overridable), at `{DOMAIN}` or another verified identity | defaulted at Step 1 or Step 5; overridable |
| `TEST_RECIPIENT` | `you@example.com` | user, collected at Step 1, Step 4 or Step 5 |
| `MAIL_TYPE` | `TRANSACTIONAL` or `MARKETING` | user, Step 3 |
| `WEBSITE_URL` | `https://example.com` | user, Step 3 |
| `CASE_ID` | Support case ID, may be absent | `get-account` → `Details.ReviewDetails.CaseId` |
| `MAX_24_HOUR_SEND` | number; `-1` means unlimited | `get-account` → `SendQuota.Max24HourSend` |
| `CHOSEN_RECIPIENT_OPTION` | `1` (verify the mailbox as its own identity), `2` (mailbox simulator) or `3` (existing mailbox at a verified domain) | selected in Step 4's "Sandbox recipient options"; **consumed in Step 5**, which picks its delivery check from it |
| `CHOSEN_RECIPIENT` | the address the send goes to; a single address, validated like every other substituted value | in the sandbox, bound in Step 4 from the option chosen — option 1: `TEST_RECIPIENT`; option 2: `success@simulator.amazonses.com`; option 3: the mailbox the user names at an already-verified domain. With `ProductionAccessEnabled: true`, from `TEST_RECIPIENT` if it was collected, never from a null, else asked for in Step 5 |
| `PA_DECLINED` | `true`, else unset | set `true` when the user declines production access at Step 3; routing must not re-propose it |
| `MESSAGE_ID` | returned by the send | `send-email` |
| `ACCOUNT_ID` | 12 digits | `sts get-caller-identity` |

If `PROFILE` is set, append `--profile '{PROFILE}'` to every command; all `sesv2` commands also take
`--region '{REGION}'`. Every substituted value is validated and single-quoted first.

## Required IAM actions

**This list covers only the actions this file calls.** The domain-setup leg is owned by
`setting-up-ses-domain-identity.md`, which has its own list; the **full journey** needs the union, because
Step 2 hands the DNS and identity-creation work to that file. Scope as SKILL.md describes; never a wildcard.

- **Read, always needed:** `sts:GetCallerIdentity`, `ses:GetAccount`, `ses:ListEmailIdentities`,
  `ses:GetEmailIdentity`. **Scope the `ses:GetEmailIdentity` statement to every identity this file reads**,
  not only `identity/{DOMAIN}`: Step 4 reads `identity/{CHOSEN_RECIPIENT}` for option 1, and for **option 3**
  the **exact identity ARN of the other verified domain the user names**. A policy scoped only to the sending
  domain denies those reads, and the failure looks like a missing recipient rather than a missing permission.
- **Write, only for the scope actually being run.** A read-only or domain-setup-only request needs
  **none of the three writes below**, though domain setup still needs the other file's writes:
  - `ses:PutAccountDetails` — only when requesting production access (Step 3).
  - `ses:SendEmail` — only when a first or test send is in scope (Step 5).
  - `ses:CreateEmailIdentity` — **two distinct scopes, and only one belongs here.** Creating the **domain**
    identity is owned by `setting-up-ses-domain-identity.md`, scoped to `identity/{DOMAIN}`. What this file
    calls it for is narrower: verifying an individual **address** as a sandbox recipient (Step 4, option 1),
    scoped to `identity/{CHOSEN_RECIPIENT}`. A policy scoped only to the domain denies that call.
- Narrow `ses:SendEmail` so a confused or compromised caller cannot send as anyone from this domain.
  **Scope the statement to the identity that authorizes `{FROM_ADDRESS}`** — three cases: an address at
  `{DOMAIN}` (the default and common case) → `identity/{DOMAIN}`; an address verified as its **own email
  identity** → `identity/{FROM_ADDRESS}`; an address at a **different** verified domain → that domain's
  identity ARN. Then pin the sender with the `ses:FromAddress` condition key:

  ```json
  {
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": "arn:aws:ses:{REGION}:{ACCOUNT_ID}:identity/{DOMAIN}",
    "Condition": {"StringEquals": {"ses:FromAddress": "{FROM_ADDRESS}"}}
  }
  ```

  `ses:FromAddress` is an exact string match, so pin it to the `{FROM_ADDRESS}` collected for this workflow —
  pinned elsewhere it denies every send and reads like a broken permission.

## How to run this: check, then do

Every step is **check, then do**: read current state first, and if a step is already satisfied say so in one
line (`✓ Domain already verified`) and move on.

**Precedence: identity state is evaluated before review state**, and a `Details.ReviewDetails` row never
overrides identity state. **The table is ordered to match**: account-state rows, then identity rows, then
review rows. Two thresholds matter and differ: the **full** domain-setup-complete gate, which Step 3
requires, and the narrower **send prerequisite** stated in Step 2. Route to Step 2 before a send only when
that prerequisite fails — read it in Step 2, not from a row.

| State you read | Do this |
|---|---|
| `ProductionAccessEnabled: true` **and** `SendQuota.SentLast24Hours > 0` | Already sending **in this Region** — `SentLast24Hours` is account-wide within the Region, so it says nothing about this identity. **The user's stated intent decides what happens next.** A **new domain or Region** → Step 2, then Step 5; Steps 3 and 4 are already satisfied. A question about an existing send → do NOT run the journey; route it to [Failure modes](#failure-modes), or to `setting-up-ses-domain-identity.md`'s "Troubleshooting: DKIM Stuck in PENDING" and "Step 7" sections for stuck DKIM or MAIL FROM. If intent is ambiguous, ask: setting something new up, or debugging an existing send? |
| `ProductionAccessEnabled: true`, no sending yet | Skip Steps 3 and 4 — **the identity rows below still apply**, so this row does not skip Step 2. Bind `CHOSEN_RECIPIENT` from `TEST_RECIPIENT` if it was collected, never from a null; if not, Step 5 asks. Then Step 5. |
| No domain identity | Start at Step 2. |
| Domain identity exists and the domain-setup-complete gate passes | Skip Step 2. |
| Domain identity exists, `DkimAttributes.Status` is not `SUCCESS` | Do NOT create it again — that returns `AlreadyExistsException`. Go to Step 2, which routes to `setting-up-ses-domain-identity.md`'s Step 2 existing-identity branch and adds only what is missing. |
| Domain identity exists, `MailFromDomainStatus` is `PENDING`, `FAILED` or `TEMPORARY_FAILURE` | The full gate has not passed, so Step 3 is unavailable. Whether a **send** may proceed turns on `BehaviorOnMxFailure` — apply Step 2's send prerequisite: `USE_DEFAULT_VALUE` permits it, `REJECT_MESSAGE` does not. Either way, do not re-create the identity or re-run DKIM signing setup. |
| Domain identity exists, `MailFromAttributes` **absent** | No custom MAIL FROM was ever configured — the field is optional, so this differs from `PENDING`. The full gate has not passed, so Step 3 is unavailable. Go to Step 2 for the MAIL FROM step only; do not re-create the identity or re-run DKIM signing setup. |
| Domain identity exists and **any** other reason leaves the gate unmet — including `VerifiedForSendingStatus: false` while DKIM and MAIL FROM both read `SUCCESS` | Treat it like the rows above: the gate has not passed, so Step 3 is unavailable. Go to Step 2, and **name the field that failed** rather than reporting the two that passed. Do not re-create the identity. |
| `Details.ReviewDetails.Status: PENDING` | A request is in flight. Do NOT submit another. If Step 2's send prerequisite is not met, go to Step 2 first — a pending review does not give you a verified sender. Once met, Step 4 owns this branch and routes to "Sandbox recipient options". |
| `Details.ReviewDetails.Status: GRANTED` | Skip Step 3 — the request has already been decided, so never resubmit. `ProductionAccessEnabled` alone governs the sandbox: `true` → confirm with Step 4, then Step 5. Still `false` → the sandbox applies, so bind a permitted recipient through Step 4's "Sandbox recipient options" before Step 5. |
| `Details.ReviewDetails.Status: DENIED` | Do NOT resubmit. Step 4 owns this branch — the Support case at `CASE_ID`, an absent or closed `CaseId`, and the route into "Sandbox recipient options" that keeps Step 5 available while the case is pursued. |
| `Details.ReviewDetails.Status: FAILED` | AWS did not receive the request. Submitting again at Step 3 is safe, then through Step 4 (the new review is `PENDING` — bind the recipient there) to Step 5. |
| `Details.ReviewDetails` absent | No request has ever been submitted in this Region. Step 3 is safe once the domain gate passes — but only run it if the user wants production access and `PA_DECLINED` is not set. Otherwise the account is still in the sandbox: go to Step 4's "Sandbox recipient options" to bind a permitted recipient, then Step 5. |

## Step 1: Preflight — one question set, then read state

**Ask in ONE message, and ask only for what the request needs.** Do not drip-feed questions; equally, do not
block domain setup on inputs belonging to a later step. **Never ask for anything already supplied, and never
ask for the AWS CLI profile or Region** — SKILL.md's Critical Rules own both, including the two
credential/Region cases where you do ask. Two ordering requirements here.

First, **run `aws sts get-caller-identity` before composing the question set** — credentials found dead
afterwards throw the answers away and may have pointed at the wrong account. If it fails, say how to refresh
them and ask, in the same message, which account (profile) and Region to use once back.

Second, **resolve the Region by SKILL.md's precedence chain before any `aws sesv2` call** — user-named,
`AWS_REGION`, `AWS_DEFAULT_REGION`, then `aws configure get region` (profile-aware). If none yields a value,
ask for one in the same question set. Bind it as `REGION` and **state it before any mutation**.

**Scope the question set to the request:**

| The user asked for… | Ask only for | Defer |
|---|---|---|
| Domain setup / verification only | sending domain; MAIL FROM subdomain | everything else, until they ask to send |
| The full journey to a delivered email | sending domain; MAIL FROM subdomain; test recipient (From address is defaulted, not asked) | mail type and website URL — collected **at Step 3**, never at preflight |
| Production access | sending domain; MAIL FROM subdomain | mail type and website URL — collected **at Step 3**; From address defaulted, test recipient deferred to Step 5. Production access requires the domain gate first, so this routes through Step 2 then Step 3; it is not a shortcut past domain setup. |

**The From address is never one of the questions.** Default it to `onboarding@{DOMAIN}` — the bare address,
with no display name — **state** it in the same message as the question set, and invite an override in the
same breath. Bounce notices arrive there by default, so a real mailbox is worth having. Because it is stated
rather than asked, the question set **for the full journey** carries three items.

> Example, for the full journey:
>
> To get you from nothing to a delivered email I need three things:
>
> 1. **Sending domain** — the domain you want mail to come from, e.g. `example.com`. You need to be
>    able to add DNS records for it.
> 2. **MAIL FROM subdomain** — a subdomain used as the envelope sender, which is what makes SPF
>    align. Common choices are `mail.example.com` or `bounce.example.com`; pick one.
> 3. **Test recipient** — an email address you can actually open, to receive the first message.

**MUST NOT ask for mail type or website URL before Step 3 — not even when the user says they want production
sending.** Production access requires a verified domain first, so asking up front delays the identity
creation that has to happen anyway.

**If the user overrides the From address, check it against the sending domain.** An override not at
`{DOMAIN}` is held until the state read below — an address at another identity already verified in this
Region is also legitimate. At no verified identity, say so and ask for one that is.

Then read state before doing anything:

```bash
aws sts get-caller-identity
aws configure get region          # last resort only, after AWS_REGION and AWS_DEFAULT_REGION; add --profile '{PROFILE}' if named
aws sesv2 get-account --region '{REGION}'
aws sesv2 list-email-identities --region '{REGION}'
```

From `get-account` read `ProductionAccessEnabled`, `Details.ReviewDetails.Status`,
`SendQuota.SentLast24Hours` and `SendQuota.MaxSendRate`, and record `CASE_ID` and
`MAX_24_HOUR_SEND` — read the account's own limits here rather than asserting a figure
later — then route with the table above. Two fields decide whether the journey can run at all:
`SendingEnabled: false` means sending is switched off in this Region and no send will succeed;
`EnforcementStatus` of `PROBATION` or `SHUTDOWN` means a reputation problem this workflow does not address
(`HEALTHY` is the good value). Surface either and stop.

From `list-email-identities`, note whether `{DOMAIN}` is present. If it is, read it with
`get-email-identity` before deciding anything — presence alone does not mean the gate passes.

## Step 2: Verify the sending domain

Create a domain identity with Easy DKIM, add a custom MAIL FROM subdomain for SPF alignment, and publish a
DMARC record — then present **all** DNS records in a single batch.

**Do not run any create or put call from here, and do not improvise the record shapes.** The whole procedure
lives in `setting-up-ses-domain-identity.md`, which owns the entire DNS leg — including asking the user to add
the records and confirm they are live, so **do not ask for either a second time here**. Follow it, then return
carrying whatever its handoff produces.

SES detects the records on its own once they resolve; there is no API to force a re-check. **Do not wait
open-endedly:** re-read the identity once the lookups resolve rather than polling on a timer, and if every
record resolves publicly while the status has not moved, go to that file's DKIM troubleshooting section.

Step 2 is complete when the domain-setup-complete gate in SKILL.md's "Invariants" passes — all three
of its fields true in one response:

```bash
aws sesv2 get-email-identity --email-identity '{DOMAIN}' --region '{REGION}'
```

**The send prerequisite — stated here, and applied rather than redefined elsewhere.** A send may proceed when
the identity is verified for sending with `DkimAttributes.Status: SUCCESS`, **and** either
`MailFromAttributes.MailFromDomainStatus` is `SUCCESS` or it is unresolved with `BehaviorOnMxFailure` set to
`USE_DEFAULT_VALUE`. It may **not** proceed while MAIL FROM is unresolved and `BehaviorOnMxFailure` is
`REJECT_MESSAGE`: AWS documents that SES then returns `MailFromDomainNotVerified` and does not attempt
delivery. **`MailFromAttributes` absent entirely** → no custom MAIL FROM in effect, and this journey routes
to Step 2 because custom MAIL FROM is a MUST here. In the `USE_DEFAULT_VALUE` case SES falls back to a
subdomain of `amazonses.com` as the envelope sender — say plainly that it will not align with `{DOMAIN}` and
DMARC must pass on DKIM alignment alone, then go to Step 5. Never report the domain as complete in either
state.

**Why DKIM `SUCCESS` is in that prerequisite when SES itself does not require it.** Per SKILL.md's sender
invariant, the service minimum is a verified sender; this journey holds the higher bar because it promises a
*delivered, authenticated* first email whose `Authentication-Results` shows `dkim=pass`. If the user
explicitly wants to send sooner, say what they give up and never silently relax the prerequisite.

**Scope gate — check the requested scope before going on to Step 3 or Step 5.** A **domain-setup-only**
request ends here: report the result, name any outstanding field, and **stop**. Do not prompt for production
access and do not offer or perform a test send — neither was asked for, and Step 3 opens an AWS Support case
while Step 5 sends real mail. Say in one line that both are available on request. Continue only when the
request asked for production access, a send, or the full journey.

## Step 3: Request production access

**MUST confirm the domain-setup-complete gate passes before submitting.** AWS documents that "verifying your
domain with SES before requesting production access is a best practice that helps to get your production
access request approved faster." If the user asks to submit first, explain that and complete the domain first.

**MUST get explicit consent before submitting.** The console form makes the user tick an acknowledgement box;
the API has no parameter for it, so submitting via the CLI makes that commitment on the user's behalf. Say
this in one paragraph and wait for a yes:

> Submitting this tells AWS you will only send to people who asked for your mail, and that you
> have a way to handle bounces and complaints. It opens an AWS Support case, and AWS documents
> that you cannot edit your details until the review completes — there is no API to cancel or
> withdraw it. Shall I submit it? (You can also fill in the form yourself in the SES console.)

**If the user declines, accept it and move on — do NOT re-propose it.** Production access is not needed for a
first delivered email. Say that plainly, **set `PA_DECLINED`**, skip the rest of Step 3 (do not collect
`MAIL_TYPE` or `WEBSITE_URL`), and go to **Step 4's "Sandbox recipient options"** to bind a permitted
recipient, then Step 5 — the account is in the sandbox, so that binding is required before the send. Do not
raise production access again this session unless the user brings it up.

Two inputs are required and collected here. Ask now if the request did not supply them — never invent either.
Explain each in one line, because the user is choosing:

- `MAIL_TYPE` — `TRANSACTIONAL` for mail a user's own action triggers, such as password resets and receipts;
  `MARKETING` for mail sent to a list, such as promotions and newsletters.
- `WEBSITE_URL` — the business site the email relates to; it need not be at the sending domain.

```bash
aws sesv2 put-account-details \
  --production-access-enabled \
  --mail-type '{MAIL_TYPE}' \
  --website-url '{WEBSITE_URL}' \
  --region '{REGION}'
```

- **Do NOT pass `UseCaseDescription`.** The SESv2 API marks that parameter deprecated.
- Optional: `--additional-contact-email-addresses` (up to 4) and `--contact-language EN|JA`. AWS uses those
  contacts for correspondence about this account, so offer only addresses **controlled by authorized members
  of the user's own team** — never an external recipient, a customer address, or a public list.
- **Success looks like nothing.** The API returns an empty HTTP 200 — no case ID, no status. That is
  expected, not a failure. Read the status back in Step 4.
- **Whenever you present or run this command, tell the user two things:** how to check the review status
  afterwards (`aws sesv2 get-account`, read `Details.ReviewDetails.Status`), and that they can already send
  today — naming all three options from Step 4's "Sandbox recipient options", in that numbering.
- A second call while a review is pending returns `ConflictException` (HTTP 409); there is no API to cancel
  or withdraw. `BadRequestException` (HTTP 400) means an input is invalid, not a refusal — see
  [Failure modes](#failure-modes).

## Step 4: Check the decision

Read the whole response, not a projection — these branches turn on several nested fields:

```bash
aws sesv2 get-account --region '{REGION}'
```

Read `ProductionAccessEnabled` at the top level, and `Details.ReviewDetails.Status` and `CaseId` if
`Details.ReviewDetails` is present at all — it is optional, and its absence is a branch below.

**`ProductionAccessEnabled` alone decides whether the sandbox applies, so read that field before the review
status.** While it is `false`, SKILL.md's sandbox recipient rule and "Sandbox recipient options" below apply
whatever `Details.ReviewDetails.Status` says, `GRANTED` included. A `GRANTED` status does still mean the
request has been decided, so skip Step 3 and do not resubmit.

**`ProductionAccessEnabled: true`** — and only this field — lifts the sandbox restriction, so "Sandbox
recipient options" does not apply. Bind `CHOSEN_RECIPIENT` from the `TEST_RECIPIENT` collected in Step 1 if
there is one, never from a null; if it was never collected, Step 5 asks. Any address works now, so offer to
change it. Then Step 5.

**`ReviewDetails.Status: PENDING`** — under review. Do not tell the user to wait, and never that the account
will be out of review in 24 hours: AWS documents an initial response within 24 hours, grants inside that
window only "If we're able to do so", and may take longer. After that window the Support case is where AWS
responds — read it as the `DENIED` branch describes. The account is still in the sandbox, so **go to "Sandbox
recipient options" below**, opening with: *"Your request is in. In the meantime you can test everything end to
end right now — you just have to send to a recipient AWS already knows about."*

**`ReviewDetails.Status: DENIED`** — do not resubmit. Read the Support case at `CASE_ID`. **`CaseId` is
optional, so it may be absent — and the case may have been closed.** Either way do not stop at "read the
case": have the user open the SES account dashboard in the console, which shows the production-access state,
and re-engage AWS Support with a new case referencing the denial if they want the decision revisited. **This
is not the end of the journey:** the account is still in the sandbox, not switched off. **Go to "Sandbox
recipient options" below**, opening with: *"The review came back denied — nothing about sandbox testing is
lost."*

**`ReviewDetails.Status: FAILED`** — AWS did not receive the request; it is safe to submit again at Step 3.
The resubmitted review is `PENDING`, which returns here.

**`Details.ReviewDetails` absent** — no request has been submitted in this Region. If the user wants
production access, Step 3 is the next action and it is not a resubmit. If they do not, or `PA_DECLINED` is
set, do not send them back to Step 3 — **go to "Sandbox recipient options" below**, opening with:
*"You're still in the SES sandbox, so the first send has to go to a recipient AWS already knows
about."*

### Sandbox recipient options

**This subsection is state-neutral. It applies whenever `ProductionAccessEnabled` is `false` — on all six of
these paths:** review `PENDING`; review `DENIED`; review `GRANTED` while `ProductionAccessEnabled` is still
`false`; review `FAILED` where the user declines to resubmit at Step 3; `PA_DECLINED` set at Step 3; and
`Details.ReviewDetails` absent. Where a branch above supplies its own
opening sentence, use it; the options, numbering and binding rules are identical on every one of the six.
**No sandbox path reaches Step 5 without binding `CHOSEN_RECIPIENT` here and reading it back.**

Ask which option they want, and record `CHOSEN_RECIPIENT_OPTION` and the address it resolves to as
`CHOSEN_RECIPIENT`:

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

**Set `CHOSEN_RECIPIENT` per the session-state table and read it back before Step 5.** Step 5 sends to
`CHOSEN_RECIPIENT`, not the Step 1 answer.

**Inputs differ by option.** Option 1 needs an address the user can open — if `TEST_RECIPIENT` was never
collected, ask for it in the same message as the option choice, so it stays one question. Option 2 needs no
address. Option 3 needs a real mailbox at a verified domain. **Never invent an address, never derive one from
`{DOMAIN}`, and never substitute the simulator for an option the user did not choose.**

**Option 1 is check-then-do.** Read the identity before creating it:

```bash
aws sesv2 get-email-identity --email-identity '{TEST_RECIPIENT}' --region '{REGION}'
```

- `NotFoundException` → create it, which sends the verification message:
  `aws sesv2 create-email-identity --email-identity '{TEST_RECIPIENT}' --region '{REGION}'`
- Exists with `VerifiedForSendingStatus: true` → say so in one line and go to Step 5.
- Exists with `false` → the verification link is outstanding. Do **not** re-create it.

**Then gate the send on the verification completing.** The user clicks the link out of band, so read
the state back and do not call `send-email` until it is `true`:

```bash
aws sesv2 get-email-identity --email-identity '{TEST_RECIPIENT}' --region '{REGION}' \
  --query 'VerifiedForSendingStatus'
```

If still `false`, wait and re-read; sending first returns `MessageRejected`, which looks like a generic
sandbox restriction and is not one. **Bound that wait rather than looping:** have the user check that
mailbox's spam folder, and remember that AWS documents the link expiring 24 hours after the message was sent
— that window is the escape point, not an interval to poll through. **There is no resend here:** re-running
`create-email-identity` returns `AlreadyExistsException` and sends no second message, and
`SendCustomVerificationEmail` is a separate templated feature this skill does not use. An expired link is
handled from the SES console, per [Failure modes](#failure-modes).

**Option 3 is check-then-do too — verify the domain rather than trusting the name.** The user names the
mailbox; confirm the account can send to it with `aws sesv2 list-email-identities --region '{REGION}'`:

- The domain part of the named address must appear in that list as an identity in this Region. If not, this
  option does not apply: say so and have the user pick option 1 or 2.
- Read that identity's state before relying on it
  (`aws sesv2 get-email-identity --email-identity '{that-domain}' --region '{REGION}'`). An unverified domain
  identity does not make its addresses permitted recipients.
- **Whether a mailbox exists there is not something any API can tell you.** Confirm it with the user in words.

While `ProductionAccessEnabled` is `false`, SKILL.md's sandbox recipient rule applies, per Region. If the user
asks about limits, answer from the `SendQuota` values read in Step 1 rather than asserting a figure, and note
that AWS counts that quota by **recipients**, not messages. A `MAX_24_HOUR_SEND` of `-1` means the daily quota
is unlimited, so report it that way. Do not raise limits unprompted.

## Step 5: Send the first email

**A send must have been asked for** — Step 2's scope gate stops a domain-setup-only request.

**Apply Step 2's send prerequisite first, re-reading the identity rather than trusting a carried value** —
DKIM may have moved since:

```bash
aws sesv2 get-email-identity --email-identity '{DOMAIN}' --region '{REGION}'
```

If it is not met — `DkimAttributes.Status` not `SUCCESS`, or MAIL FROM unresolved with `BehaviorOnMxFailure`
at `REJECT_MESSAGE` — do **not** send: name the outstanding field and go back to Step 2. In the sandbox a
permitted recipient does not substitute for this; the recipient rule and the send prerequisite are separate
gates and both apply.

**Then bind the sender and recipient.** If `{FROM_ADDRESS}` is not bound, default it to
`onboarding@{DOMAIN}` and STATE it with Step 1's override invitation — do not ask. If `{CHOSEN_RECIPIENT}` is
not bound — a domain-setup-only request defers it — ask for it now, in ONE question, at the point of use; in
the sandbox it must be bound by Step 4's "Sandbox recipient options" rather than asked for freely, because an
arbitrary address is not a permitted recipient there. **Never invent a recipient**: the From default is the
one derived value this skill permits, because any mailbox at the verified domain is a legal sender.

`{FROM_ADDRESS}` must be at `{DOMAIN}` or at another identity verified in this Region, per SKILL.md's sender
invariant; if it is not, ask for an address at `{DOMAIN}` rather than sending.

**MUST ask before sending.** A real message is about to reach a real person:

> The next command sends a real email from `{FROM_ADDRESS}` to `{CHOSEN_RECIPIENT}`.
> Ready?

**Use `aws sesv2 send-email`, never the v1 form**, per SKILL.md's Critical Rules.

```bash
aws sesv2 send-email \
  --from-email-address '{FROM_ADDRESS}' \
  --destination '{"ToAddresses":["{CHOSEN_RECIPIENT}"]}' \
  --content '{"Simple":{"Subject":{"Data":"SES first send check"},"Body":{"Text":{"Data":"If you are reading this, Amazon SES is set up correctly."}}}}' \
  --region '{REGION}'
```

`--feedback-forwarding-email-address` sets where SES sends bounce and complaint notifications; left off, they
go to `{FROM_ADDRESS}`. If that is not a monitored mailbox, set it to a deliverable address at the verified
`{DOMAIN}` controlled by an authorized member of the user's own team — bounce notifications carry recipient
addresses, so never an external recipient or public list. Omit the flag rather than guessing. SES is billed
per recipient — see [Amazon SES pricing](https://aws.amazon.com/ses/pricing/) — so say that before sending.

**A returned `MessageId` means Amazon SES accepted the message — not that it was delivered.** Say that
plainly, then run the check matching `CHOSEN_RECIPIENT_OPTION`:

| Situation | How you know it worked |
|---|---|
| `ProductionAccessEnabled: true`, or option 1 (the mailbox just verified), or option 3 (a real mailbox at a verified domain) | Open the message and view its raw headers. Find `Authentication-Results` and confirm `dkim=pass`, `spf=pass` and `dmarc=pass`. This is the only check that proves authentication. |
| Option 2, the mailbox simulator | `success@simulator.amazonses.com` has no inbox, so there is no `Authentication-Results` header. A `MessageId` proves the send path only and proves **nothing** about DKIM, SPF or DMARC. Say so, then send the user back to Step 4's "Sandbox recipient options" to pick **option 1 or option 3** — a mailbox they can open — re-bind `CHOSEN_RECIPIENT_OPTION` and `CHOSEN_RECIPIENT` there, and return here. Do not call authentication confirmed until that second send's headers have been read. |
| Option 3, but nothing arrives because no real mailbox exists there | Verifying a domain creates no MX records and no mailboxes, so authentication is unproven. Go back to "Sandbox recipient options", pick **option 1**, re-bind `CHOSEN_RECIPIENT` there and return here. |

Where raw headers live differs by mail client — in Gmail, **More** (three vertical dots) then **Show
original**. `dmarc=pass` appears only if a `_dmarc` TXT record is published for `{DOMAIN}` — a precondition,
not automatic; if DMARC is missing or shows `none`, go back to the DMARC step in
`setting-up-ses-domain-identity.md`.

**If it has not arrived:** check the spam folder first, then see [Failure modes](#failure-modes). A bounce,
if there is one, arrives by email at the feedback-forwarding address.

## Step 6: After it arrives — optional extras

**Only offer these once the test send has landed.** Offer once, act on a yes, do not push. **Dedicated IPs and
tenants** exist for higher volume and for isolating senders — one line each. Do not raise pricing plans.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `MessageRejected: Email address is not verified` | Two causes — read `ProductionAccessEnabled` and the address named in the error before choosing. `false` and the named address is the recipient: the sandbox restriction is on the **recipient**, and a verified sending domain does not change it. Otherwise the unverified identity is the **sender**, which must be verified in production too. | Recipient case: go to Step 4's "Sandbox recipient options" and re-bind `CHOSEN_RECIPIENT`. Production access removes the restriction but is not the only fix. Sender case: verify the named From or Return-Path identity in this Region, or send from an address at `{DOMAIN}`. **If that identity is verified but its `DkimAttributes.Status` is not `SUCCESS`, this is not the fix** — re-apply Step 2's send prerequisite and complete DKIM first, because this journey's bar is an authenticated message, not merely an accepted one. |
| `MessageRejected` right after verifying a recipient address | The verification link has not been clicked. | Read `VerifiedForSendingStatus` on that identity and wait for `true` — Step 4's gate. |
| `AlreadyExistsException` on `create-email-identity` | The identity already exists in this Region. | Read it with `get-email-identity` and add only what is missing. Never create over an existing identity. |
| `ConflictException` on `put-account-details` | A review is in flight. | Read `Details.ReviewDetails.Status`. Do not resubmit. |
| `BadRequestException` on `put-account-details` | An input is invalid — not a refusal. | `MailType` must be `MARKETING` or `TRANSACTIONAL`; `WebsiteURL` 1–1000 characters; at most 4 extra contacts; `ContactLanguage` `EN` or `JA`. Fix and resubmit. |
| `MailFromDomainStatus: FAILED` or `TEMPORARY_FAILURE` | `FAILED` is terminal — AWS documents that SES then "no longer attempts to detect the required MX record", so re-reading never clears it. `TEMPORARY_FAILURE` means SES could not determine the status and is still searching. | Both belong to the MAIL FROM step in `setting-up-ses-domain-identity.md`: confirm **exactly one** MX record on the subdomain in the authoritative zone, then restart the setup there for `FAILED` only. Do not re-create the identity, and do not re-call `put-email-identity-mail-from-attributes` with unchanged values. |
| `ThrottlingException` (HTTP 400), `Daily message quota exceeded` | Sends in the last 24 hours reached `SendQuota.Max24HourSend`. | Compare `SentLast24Hours` against `Max24HourSend` — **unless `Max24HourSend` is `-1`, which means the daily quota is unlimited: the comparison does not apply and this is not the cause, so look at `MaxSendRate` instead.** With a real limit, the quota is computed over a rolling 24-hour window, so it clears only as that window advances — do not present production access as an instant fix. |
| `ThrottlingException` (HTTP 400), `Maximum sending rate exceeded` | Sends exceeded `SendQuota.MaxSendRate`. | Reduce the send rate and send one recipient per `SendEmail` call; AWS documents waiting an interval (up to 10 minutes) and then retrying. |
| `MessageId` returned but nothing arrived | Accepted ≠ delivered. | Check spam, then the domain's DMARC policy, and read the bounce notification SES forwards to the feedback-forwarding address. |
| Header shows `dmarc=none`, `dmarc=fail`, `spf=fail`/`neutral`, or `spf=pass` with DMARC's SPF leg failing | Missing or misaligned DNS, not a send problem: no `_dmarc` record; a From domain aligning with neither the DKIM `d=` domain nor SPF; an SPF record on the MAIL FROM subdomain that is missing, wrong or duplicated; or no custom MAIL FROM, so the `amazonses.com` envelope sender does not align. | All are fixed in `setting-up-ses-domain-identity.md` — its DMARC step for `_dmarc.{DOMAIN}`, its MAIL FROM step for SPF and envelope alignment. Also send from an address at the verified domain so `d=` matches. DKIM alignment alone can satisfy DMARC, so a failing SPF leg is not necessarily fatal. |
| `AccessDeniedException` | Missing `ses:` permissions. | Compare the caller's policy against "Required IAM actions" above, plus `setting-up-ses-domain-identity.md`'s for the domain-setup leg. |
| Works in one Region, fails in another | Identities, production access and quotas are per-Region. | Verify the domain and request production access in each Region you send from. |
| Verification email link does not work | AWS documents the link expiring 24 hours after the message was sent. | Request a new verification message from the SES console identity details page; there is no SESv2 resend operation. |
| Every send fails regardless of recipient | `SendingEnabled: false` for the account in this Region. | Read `aws sesv2 get-account`. This workflow cannot change that account-level state; contact AWS Support. |
