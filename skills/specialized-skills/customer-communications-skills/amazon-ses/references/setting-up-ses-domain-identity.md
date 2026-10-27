# Setting Up SES Domain Identity

> Operations below use AWS CLI syntax. For sandboxed execution, use the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html).
> SKILL.md's "Invariants" own the domain-setup-complete gate and the value-validation and single-quoting
> rules this file relies on.

## Overview

This file owns the whole DNS and identity leg of SES domain setup. It assumes the sending domain is not yet
fully set up in this Region, and it is finished when SKILL.md's domain-setup-complete gate passes.

**Rules this file owns:**

- **MUST** ask which MAIL FROM subdomain to use; suggest one, never default it (Step 4).
- **MUST** publish DMARC `p=none` or stronger, and preserve a stronger existing policy (Step 5).
- **MUST** build each DKIM value as `{token}.{SIGNING_HOSTED_ZONE}` from the API response (Step 6).
- **MUST** read `DkimAttributes.SigningAttributesOrigin` before any Easy DKIM handling (Step 2), and stop at the DKIM leg on any value other than `AWS_SES` — this file configures Easy DKIM only.
- **MUST** present one batch containing only records absent or incorrect this run (Step 6).
- **MUST NOT** use Route 53 `UPSERT` or `DELETE`. `CREATE` only.
- **SHOULD** detect whether Route 53 hosts the domain and offer to create records there. **MUST** get permission before writing, after showing the zone, each record, TTL, conflicts, and no-overwrite or no-delete behavior.
- **SHOULD NOT** present SES's documented 72-hour DNS search limit as the expected wait.

## Required IAM actions

Apply SKILL.md's IAM scoping, and grant only the actions the path actually taken reaches — a request that
stops at reading state needs none of the writes. On the full journey the caller also needs `onboarding.md`'s
list, because that file owns the account and send legs.

| Condition | Actions |
|---|---|
| Always | `sts:GetCallerIdentity`, `ses:GetEmailIdentity` |
| Direct invocation only | `ses:GetAccount` to read account state before a write. Reuse `onboarding.md`'s result when entering from there. |
| Identity absent | `ses:CreateEmailIdentity` |
| Easy DKIM status `FAILED` or `NOT_STARTED`, and `SigningAttributesOrigin` absent or exactly `AWS_SES` | `ses:PutEmailIdentityDkimSigningAttributes`. Never grant or call it for `SUCCESS`, `PENDING`, `TEMPORARY_FAILURE`, or any `SigningAttributesOrigin` other than `AWS_SES`. |
| Configure custom MAIL FROM for the first time (`MailFromAttributes` absent), restart it, or change the fallback with consent | `ses:PutEmailIdentityMailFromAttributes` |

Scope SES identity actions to `arn:aws:ses:{region}:{account-id}:identity/{domain}`.

**Route 53 splits into reads and one write.** The reads — `route53:ListHostedZonesByName`,
`route53:GetHostedZone`, `route53:ListResourceRecordSets` — are needed whenever the agent checks whether
Route 53 hosts the domain, so grant them for that check alone. Add `route53:TestDNSAnswer` only for Step 1's
narrow lookup fallback, and `route53:ChangeResourceRecordSets` only after the user has approved a write. Scope
them per SKILL.md, using the **bare** zone ID; `ListHostedZonesByName` and `TestDNSAnswer` require
`Resource: *`.

## Parameters

**Entry from `onboarding.md`:** reuse its `DOMAIN`, `REGION`, `MAIL_FROM` and `PROFILE`. Do not ask again.

**Direct invocation:** run `aws sts get-caller-identity` before collecting any inputs. If it fails, explain how
to refresh credentials and ask which account and Region to use once they are back. Resolve the Region by
SKILL.md's precedence chain — a Region the user named, `AWS_REGION`, `AWS_DEFAULT_REGION`, then
`aws configure get region` with `--profile '{profile}'` when the user named a profile; that last command reads
the CLI configuration files and not the environment, which is why the two environment variables come first.
Only if none of them yields a value, ask for it in the same message as the other missing inputs. Ask once for
the remaining scope, never for a profile or Region that resolved, and state the Region before any mutation.

The user chooses `domain` and `mail_from_subdomain`; never derive either. Do not ask about `behavior_on_mx_failure` during normal setup. Validate and single-quote every substituted value per SKILL.md.

| Parameter | Source and constraints |
|---|---|
| `domain` | User. DNS domain to authenticate. |
| `region` | User if named, otherwise resolved by SKILL.md's precedence chain. SES state is Region-scoped. |
| `profile` | User only if named. Append `--profile '{profile}'` to every command, including Route 53, so identity and DNS changes use the same account. |
| `mail_from_subdomain` | User. Suggest `mail.{domain}` or `bounce.{domain}`. It must be a subdomain of `{domain}` — the domain being verified as this identity — and should not carry sent or received mail. |
| `behavior_on_mx_failure` | The API defines no server default, so pass `USE_DEFAULT_VALUE` for a new identity or when `MailFromAttributes` is absent, and **preserve the existing value** on every re-setup of an identity that has it. While MAIL FROM is unresolved, `USE_DEFAULT_VALUE` sends from an `amazonses.com` subdomain and `REJECT_MESSAGE` returns `MailFromDomainNotVerified` without attempting delivery — so replacing `REJECT_MESSAGE` with the default changes sending behavior and needs Step 4's disclosure and consent. |

Carry these values forward:

| Value | Source |
|---|---|
| `DKIM_TOKENS` | `DkimAttributes.Tokens`, 3 tokens |
| `SIGNING_HOSTED_ZONE` | `DkimAttributes.SigningHostedZone` |
| `DKIM_ORIGIN` | `DkimAttributes.SigningAttributesOrigin`: `AWS_SES`, `EXTERNAL` (customer-managed BYODKIM keys), `AWS_SES_<REGION>` (a replica managed from another Region), or absent. Read it before any Easy DKIM handling; Step 2's gate turns on it. |
| `hosted_zone_id` | Matched Route 53 `HostedZones[].Id` with `/hostedzone/` stripped: store the bare `Z123ABC`, which CLI flags and the IAM ARN both assume. |
| `zone_name` | Zone matched for `{domain}` or by Step 6's parent walk; delegation and authority checks query it. |
| `parent` | `{domain}` with its leftmost label removed, for the parent walk |
| `RECORDS_NEEDED` | The records that are absent or incorrect this run. Step 6 owns the omission rules and presents this set, never an unconditional six records. |

## Step 1: Verify Prerequisites

```bash
aws sts get-caller-identity
aws sesv2 get-account --region '{region}'   # direct invocation only — reuse onboarding.md's result when entering from there
```

Confirm AWS CLI v2 is configured, that the Region supports SES, and that `dig` is available — it ships in
`bind-utils` or `dnsutils`. If `dig` is absent, use `nslookup -type=CNAME|MX|TXT '{name}'` wherever `dig`
appears below, dropping `+short` and reading the answer section instead.

If neither tool exists, do not skip or guess: ask the user to run the lookup or check the record at their DNS provider and report back. For a known Route 53 public zone, `aws route53 test-dns-answer` (which needs `route53:TestDNSAnswer`) covers record read-back only — it proves nothing about public propagation, returns no subdomain name servers, and does not work with private zones, so those still need the user's result.

Stop and surface `SendingEnabled: false` or `EnforcementStatus: PROBATION|SHUTDOWN`; this workflow fixes neither. `onboarding.md` Step 1 owns `ProductionAccessEnabled`, `Details.ReviewDetails.Status`, `SendQuota` and their routing — do not repeat those reads. On direct invocation, read that step before finishing, because `ProductionAccessEnabled: false` restricts recipients even after domain verification.

## Step 2: Check Existing Identity State

**Read before you create** — creating over an existing identity returns `AlreadyExistsException`:

```bash
aws sesv2 get-email-identity --email-identity '{domain}' --region '{region}'
```

**If `NotFoundException`** → the identity does not exist. This is the only route into Step 3.

**If identity exists** → skip Step 3 and add only what's missing.

**First, before any DKIM status handling, read `DkimAttributes.SigningAttributesOrigin` into `DKIM_ORIGIN`.**
This gate comes before the status branches: the whole Easy DKIM flow — the three DKIM CNAMEs and
`put-email-identity-dkim-signing-attributes` — is wrong for an identity whose DKIM is managed elsewhere,
whatever the status says.

- **`DKIM_ORIGIN` is exactly `AWS_SES`, or absent** → Easy DKIM. Continue with the status branches below.
- **Any other value → this identity's DKIM is outside the scope of this onboarding. Leave DKIM entirely
  alone.** Do **not** present the three DKIM CNAMEs, do **not** put them in `RECORDS_NEEDED`, and do **not**
  call `put-email-identity-dkim-signing-attributes`. `EXTERNAL` means the customer manages their own signing
  keys, which SES calls BYODKIM. An `AWS_SES_<REGION>` value means this identity is a replica whose DKIM is
  managed from another Region, so there is no DNS or DKIM change to make here either. Tell the user which of
  the two you read and that this workflow neither configures nor troubleshoots it, then split on
  `DkimAttributes.Status`:
  - `SUCCESS` → the DKIM leg is already satisfied. Continue with custom MAIL FROM (Step 4) and DMARC
    (Step 5) only.
  - Anything else → the domain-setup-complete gate cannot pass from here. Report that DKIM has to be
    resolved outside this workflow, name `DkimAttributes.Status` as the outstanding field, and **stop**. The
    full journey stops with it, because its send prerequisite needs `SUCCESS`.

With `DKIM_ORIGIN` cleared, branch on `DkimAttributes.Status`:

| Status | Do this |
|---|---|
| `SUCCESS` | DKIM verified. Do not touch DKIM, and **omit the DKIM CNAMEs from `RECORDS_NEEDED`** — they already resolve, so re-presenting them invites re-adding records the user has. |
| `PENDING` | DKIM creation done, DNS may be propagating. Record `DkimAttributes.Tokens` and `SigningHostedZone`, check the DNS records, and re-create or re-initialise nothing. |
| `TEMPORARY_FAILURE` | SES could not determine the status — a temporary issue determining it, not wrong records. Confirm the records resolve and re-read the identity. Do **not** re-initialise signing; that risks changing the tokens under an identity that is fine. |
| `FAILED` | Verify the DNS records first (same steps as Troubleshooting below). If DNS is correct and the status stays `FAILED`, re-initialise signing with the call below — running it on a `FAILED` identity whose records *do* resolve is the intended path, because the published records are not being honoured anyway, which is what `FAILED` means. |
| `NOT_STARTED` | The identity exists but signing was never initialised, so there are no tokens to publish. Do **not** go to Step 3 — that returns `AlreadyExistsException`. Enable Easy DKIM in place below. |

**Re-initialising signing — the one call the `FAILED` and `NOT_STARTED` rows use.** The origin gate
above has already been applied, so reaching here means the origin is absent or exactly `AWS_SES`:

```bash
aws sesv2 put-email-identity-dkim-signing-attributes \
  --email-identity '{domain}' \
  --signing-attributes-origin AWS_SES \
  --region '{region}'
```

**Gate on status, not on whether the records resolve** — never run it on a `SUCCESS` identity, because
re-initialising can change its tokens. The response returns `DkimStatus`, `DkimTokens` and
`SigningHostedZone`: bind `DKIM_TOKENS` and `SIGNING_HOSTED_ZONE` from it, or re-read the identity. Compare
those against what is published, put only the records that differ into `RECORDS_NEEDED`, and do not tell the
user their DKIM records were rotated unless the values changed.

Then branch on `MailFromAttributes`:

| MAIL FROM state | Do this |
|---|---|
| `MailFromAttributes` **absent** | No custom MAIL FROM was ever configured. The field is optional, so this is not `PENDING`, and there is no `BehaviorOnMxFailure` to preserve. Treat it as a **fresh configuration**: run Step 4 with `USE_DEFAULT_VALUE`, and add the MAIL FROM MX and SPF TXT records to `RECORDS_NEEDED`. |
| `MailFromDomain` equals the chosen `mail_from_subdomain` **and** `MailFromDomainStatus` is `SUCCESS` | MAIL FROM configured. Skip Step 4 and omit the MAIL FROM records from `RECORDS_NEEDED`. |
| `MailFromDomain` is populated with a **different** subdomain | **Stop and ask.** Changing it re-points the envelope sender for every message from this identity, and setup returns to `PENDING` until the new subdomain's MX is detected; meanwhile this identity's `BehaviorOnMxFailure` governs sending. Disclose that, and offer keeping the existing subdomain as the default. **Only if the user confirms**, call `put-email-identity-mail-from-attributes` with the new subdomain (Step 4), **then** present its new MX and TXT records in Step 6 — attributes first, records after, because SES will not search a subdomain it has not been told about. |
| `MailFromDomainStatus` is `PENDING` or `TEMPORARY_FAILURE` | SES has not finished searching for the MX record, or could not determine the status. Re-present the Step 6 MAIL FROM records, confirm they resolve, and re-read the identity. Do not re-call `put-email-identity-mail-from-attributes` **with the same values** — that does not force a re-check. Calling it to change `--behavior-on-mx-failure` is allowed here; that is Step 4's unblock. |
| `MailFromDomainStatus` is `FAILED` | **Terminal.** AWS documents that in this state SES no longer attempts to detect the MX record and the setup process has to be restarted ([Using a custom MAIL FROM domain](https://docs.aws.amazon.com/ses/latest/dg/mail-from.html)); re-reading will not clear it. Fix the DNS — exactly one MX record on the subdomain, in the authoritative zone — then re-run Step 4 with the same `--mail-from-domain`, preserving this identity's current `BehaviorOnMxFailure` per the Parameters table. |

**The DMARC check is not in this branch** — it lives in Step 5 and runs on every path through this file.

## Step 3: Create Domain Identity with DKIM

Run this only after Step 2 returns `NotFoundException`. Existing identities, including `NOT_STARTED`, stay in Step 2.

```bash
aws sesv2 create-email-identity \
  --email-identity '{domain}' \
  --region '{region}'
```

This creates an Easy DKIM identity whose signing keys are SES-managed 2048-bit RSA keys. Bind `DKIM_TOKENS`
from `DkimAttributes.Tokens` and `SIGNING_HOSTED_ZONE` from `DkimAttributes.SigningHostedZone`, re-reading the
identity if either is absent from this response. Re-query once DNS has propagated; there is no API that forces
a re-check. If a published record does not resolve, use "Troubleshooting: DKIM Stuck in PENDING".

## Step 4: Configure Custom MAIL FROM

Use the collected `mail_from_subdomain`. If missing, ask:

> What subdomain would you like for MAIL FROM? Common choices are `mail.{domain}` or `bounce.{domain}`. It appears in the Return-Path and enables SPF alignment.

Validate that the answer is at least one label below `{domain}`. SES rejects the apex, because MAIL FROM must
be a subdomain of `{domain}` — the domain being verified as this identity. If the user answers with the apex,
explain that and re-ask; never quietly substitute one of the suggestions. Left unvalidated, the call returns
`BadRequestException` (HTTP 400), which is invalid input rather than a permissions or service failure.

```bash
aws sesv2 put-email-identity-mail-from-attributes \
  --email-identity '{domain}' \
  --mail-from-domain '{mail_from_subdomain}' \
  --behavior-on-mx-failure '{behavior_on_mx_failure}' \
  --region '{region}'
```

Preserve the identity's current `BehaviorOnMxFailure` on every re-setup, including Step 2's `FAILED` restart and subdomain-change paths, per the Parameters table. MAIL FROM configuration does not wait for DKIM verification.

SES requires **exactly one MX record** on the MAIL FROM subdomain ([Using a custom MAIL FROM domain](https://docs.aws.amazon.com/ses/latest/dg/mail-from.html)). Check with `dig MX '{mail_from_subdomain}' +short`. **An existing MX takes the same show-user, user-removal path as an existing TXT — never a silent omission.** Show each MX record found and explain that SES needs only its own MX at this name. Removing MX can break inbound mail, so get explicit confirmation for each removal; the user performs removals themselves, because this skill issues no `DELETE` or `UPSERT`. If they decline, or the name receives mail, have them move MAIL FROM to a different empty subdomain and re-run Step 4 with that name. `CREATE` the SES MX only once nothing else answers there, and wait for status only after exactly the SES MX remains.

If the MX cannot be published at all, offer the documented `USE_DEFAULT_VALUE` fallback only after disclosing its effect, and repeat the command with it **only on explicit agreement**. That is the allowed repeat while status is `PENDING` or `TEMPORARY_FAILURE`, because it changes fallback behavior rather than forcing detection.

**The fallback does not complete domain setup — never report it as complete.** `MailFromDomainStatus` stays unresolved, so SKILL.md's gate does not pass. Report setup as **incomplete**, name `MailFromDomainStatus` as outstanding, and state the consequences: the envelope sender is a subdomain of `amazonses.com`, so SPF passes without aligning to `{domain}`, DMARC can pass only on its DKIM leg, and the Return-Path recipients see is not at `{domain}`. A **domain-setup-only** request **stops** there. On the **full journey** it is not a dead end — `onboarding.md`'s send prerequisite permits a send with `USE_DEFAULT_VALUE` and owns that decision — so return there rather than declaring the domain done.

## Step 5: Build DMARC Record

**Check for an existing DMARC record first — on every path**, whether the identity was just created in
Step 3 or already existed at Step 2, because a domain can carry a DMARC record long before SES:

```bash
dig TXT '_dmarc.{domain}' +short
```

**Normalise the answer one resource record at a time.** `dig TXT +short` prints **one line per TXT resource
record**, and a long record appears within a line as several quoted character-strings. Strip the quotes and
concatenate **within a single line only — never across lines**: joining two lines invents a record that does
not exist and can make two broken records look valid. Test each line independently:

- **No line begins `v=DMARC1`** → no effective DMARC policy. If some other TXT record sits on `_dmarc`,
  say it is not a policy record and receivers will not evaluate it as one. Build the record below.
- **More than one line begins `v=DMARC1`** → **invalid, and a blocking user action before Step 6.**
  Receivers have no single policy to apply. Show **every** record found, in full, say that exactly one may
  exist, and have the user decide which to keep and remove the others; this file issues no `DELETE`, so the
  removal is their own action. **Do not put a `p=none` record into `RECORDS_NEEDED`** — a further record
  deepens the ambiguity, and which policy survives is the user's choice. If any record found is valid with
  `p=quarantine` or `p=reject`, **never propose the weaker policy**: what remains must be the stronger one.
  Continue to Step 6 only after the user confirms exactly one effective policy is left, then re-run this
  check and follow whichever single-record branch it lands on.
- **Exactly one line begins `v=DMARC1`** → read it back. **Skip creating a record only when it is valid:
  exactly one `p=` tag whose value is `none`, `quarantine` or `reject`.** No `p=` tag, more than one, or an
  unrecognised value means the policy is unusable — warn, say which it is, and treat the existing record as
  the value the user replaces.
- **An existing valid `p=quarantine` or `p=reject` → preserve it. Never downgrade to `p=none`.** It is
  stronger than what this file would create, and lowering it silently weakens the domain. Say it is in force
  **now**, while the DKIM and MAIL FROM records are still propagating, so mail failing alignment meanwhile
  may be quarantined or rejected rather than merely reported — and that changing it is the user's decision.
- **It sets `aspf=s`** → the custom MAIL FROM subdomain will not align with a `From` at `{domain}`, so
  DMARC's SPF leg fails even though SPF passes; DKIM alignment is then the only leg that can pass.

A per-line string test is enough; do not build a DMARC parser. **Both DNS paths in Step 6
follow this result**, and the DMARC record enters `RECORDS_NEEDED` only when the check found no
`v=DMARC1` line at all, or found exactly one that is not valid — never while more than one exists,
which is the blocking branch above.

When a record is needed, construct the DMARC TXT record for `_dmarc.{domain}`:

```
v=DMARC1; p=none;
```

Start at `p=none` to monitor, progress to `p=quarantine` once DKIM and SPF alignment pass consistently,
and to `p=reject` when quarantine shows no legitimate mail failing. A domain left at `p=none` indefinitely
has no spoofing protection.

**What DMARC requires, and what this file chooses.** AWS documents that "a message passes DMARC if one or
both of the described SPF or DKIM checks pass" — one aligned mechanism is enough. This file sets up both
anyway, so forwarded mail (which breaks SPF) still authenticates on DKIM. That is this file's choice, not a
DMARC requirement: never tell the user DKIM alignment is mandatory and SPF optional. The record omits
`aspf` deliberately, because AWS documents SPF alignment as requiring the policy not to specify `aspf=s`.

**No aggregate reports arrive** from that record — no `rua=` tag. Judge progression either by adding a
`rua=mailto:` tag naming an address the user picks and accepts exposing in public DNS, or from the
`Authentication-Results` header of test mail received; say which.

## Step 6: Present ALL DNS Records Together

**Present `RECORDS_NEEDED` as a single batch** — never one record at a time, and never a record the user
already has. Omit the DKIM CNAMEs when DKIM is `SUCCESS` with unchanged tokens, and omit all three whenever
Step 2's origin gate read a `DKIM_ORIGIN` other than `AWS_SES`; omit the MAIL FROM MX and TXT when MAIL FROM
is already `SUCCESS` on the chosen subdomain; omit DMARC when Step 5 found exactly one valid record, or found
more than one `v=DMARC1` record — a blocking user action reached before this step, not a record to add. If
`RECORDS_NEEDED` is empty, say the DNS side is complete and go to Step 7.

```
## DNS Records to Add

### DKIM (3 CNAME records)
{DKIM_TOKENS[0]}._domainkey.{domain}  CNAME  {DKIM_TOKENS[0]}.{SIGNING_HOSTED_ZONE}
{DKIM_TOKENS[1]}._domainkey.{domain}  CNAME  {DKIM_TOKENS[1]}.{SIGNING_HOSTED_ZONE}
{DKIM_TOKENS[2]}._domainkey.{domain}  CNAME  {DKIM_TOKENS[2]}.{SIGNING_HOSTED_ZONE}

### MAIL FROM (2 records)
{mail_from_subdomain}         MX     10 feedback-smtp.{region}.amazonses.com
{mail_from_subdomain}         TXT    "v=spf1 include:amazonses.com ~all"

### DMARC (1 TXT record)
_dmarc.{domain}               TXT    "v=DMARC1; p=none;"
```

**Build each DKIM record value as `{token}.{SIGNING_HOSTED_ZONE}` from the values read in Step 2 or Step 3 —
never from a remembered literal.** AWS documents this construction and states that the hosted-zone portion
varies by AWS Region and cell
([Creating and verifying identities](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)).
If `SIGNING_HOSTED_ZONE` is missing, re-read the identity.

**Check for an existing TXT record on `{mail_from_subdomain}` before publishing the SPF record — on both
paths below**, Route 53 and external provider alike:

```bash
dig TXT '{mail_from_subdomain}' +short
```

**Normalise one resource record at a time**, exactly as Step 5's DMARC check does. Pick the line beginning
`v=spf1`; any other TXT record on the name is unrelated and left alone. Then:

- Nothing published → add the SES SPF record as shown above.
- An unrelated TXT record (a verification token, say) → the two may coexist, because the one-record rule
  applies to SPF records specifically. The existing value must still be preserved.
- Another record starting with `v=spf1` → **merge it; never publish a second.** Two SPF records on one name
  is a `permerror`, which fails SPF outright. Show the user the existing value and merge the mechanisms into
  one record by inserting `include:amazonses.com` **immediately before the terminal `all` mechanism**
  (`~all`, `-all` or `?all`) — evaluation stops at `all`, so a mechanism after it is unreachable. If
  `include:amazonses.com` is already present, no change is needed.

**In Route 53, every TXT value for one name lives in a single record set**, so `CREATE` cannot add a value to
a name that already has one. A merge — and equally, keeping an unrelated TXT value alongside the SES one — is
therefore the **user's** action: present the complete updated value list, have them confirm it, and have them
apply it. Never publish only the SES record on a name that already carries a TXT value; that drops what was
there.

**Determine whether Route 53 hosts the domain (steps below); if no authoritative zone is found, use the
external DNS provider path:**

1. Find the zone: `aws route53 list-hosted-zones-by-name --dns-name '{domain}'`

   **Pick the zone explicitly — never the first result.** This call returns zones from that name onward in
   lexical order, so it can include neighbouring domains and private zones, and one domain can have more
   than one zone. Take only the entry whose `Name` is exactly `{domain}.` **and** whose
   `Config.PrivateZone` is `false`. **Normalise its `Id` before storing it as `{hosted_zone_id}`: strip the
   `/hostedzone/` prefix and keep the bare `Z123ABC`**, which CLI flags and the IAM ARN both assume. If more
   than one entry matches, stop and ask.

   **If no entry matches `{domain}.` exactly, walk up to the parent before concluding Route 53 cannot host
   the records.** A sending domain is often a subdomain whose records live in an ancestor's zone: strip the
   leftmost label to get `{parent}` and search again (`list-hosted-zones-by-name --dns-name '{parent}'`),
   applying the same exact-name, public-zone rule at each level until a zone matches or no labels remain.
   Record the matched zone's `Name` as `{zone_name}` — every later delegation and authority check queries
   that name, not `{domain}`. Records for `{domain}` live in that zone as fully-qualified names.

   **If the walk matched an ancestor, check it has not delegated the branch away before writing anything
   into it** — records placed in a parent for a delegated name are never served. Either of these is a
   **STOP**:

   - In the `list-resource-record-sets` read below, an `NS` record set whose `Name` is `{domain}.` or any
     intermediate label between `{zone_name}` and `{domain}` — with `{domain}` = `mail.sub.example.com` and
     `{zone_name}` = `example.com`, an NS set on `sub.example.com.` counts. Ignore the NS set on
     `{zone_name}.` itself; that is the zone's own delegation.
   - `dig NS '{domain}' +short` returning name servers that **differ** from the found zone's
     `DelegationSet.NameServers`. **Empty output is not a STOP** — a subdomain with no zone of its own has
     no NS record, the normal case this walk serves.

   On either signal, do not write to the ancestor zone. If the delegated child zone is in this account, find
   it under the same exact-name, public-zone rule and use it; otherwise use the external DNS provider path
   below.

   **MUST NOT create a hosted zone — out of scope.** A child zone does not resolve until the parent
   publishes NS delegation for it, it adds a monthly charge, and an undelegated parent zone can carry the
   records directly. Say all of that, and if the user wants separately delegated management have them create
   the zone and publish its delegation themselves, then return here. Never call `route53:CreateHostedZone`:
   it is deliberately absent from this file's Required IAM actions.
2. Verify the zone is authoritative — its delegated name servers must match what public DNS answers:

   ```bash
   aws route53 get-hosted-zone --id '{hosted_zone_id}' --query 'DelegationSet.NameServers'
   dig NS '{zone_name}' +short   # the found zone's own name — an ancestor, not '{domain}', when the walk matched one
   ```

   A null or empty `DelegationSet.NameServers` means the zone is **not** authoritative for public DNS — what a
   private hosted zone returns — not that the command produced no output. Treat it as not authoritative and use
   the external-provider path.

3. **If they do not match, do not write to the zone.** Records added there will not resolve and SES will never
   detect them. Say which name servers the domain actually delegates to, and use the external DNS provider
   path below.
4. **Read what already exists before building the batch:**

   ```bash
   aws route53 list-resource-record-sets --hosted-zone-id '{hosted_zone_id}'
   ```

   Apply step 1's delegation check to this output **first**: an `NS` record set whose `Name` is `{domain}.` or
   an intermediate label below `{zone_name}` is a STOP, not a record to skip over. Otherwise include only
   absent records — the change batch is transactional ("either makes all or none of the changes"), so one
   already-existing record set fails every other change in the request. For any record that exists with a
   different value, show the user that value and what SES needs, and let them decide. Two collisions must
   never be silently omitted, because omitting them leaves the SES record unpublished: **a TXT set on
   `{mail_from_subdomain}`** goes to the merge rule above, and **an MX set on `{mail_from_subdomain}`** goes to
   Step 4's MX rule.
5. **MUST ask for explicit permission before creating DNS records — and show the whole change first.**
   Route 53 mutations can affect live traffic. Present all of this before asking:

   - the zone: `{zone_name}` and `{hosted_zone_id}`;
   - every record to be created, each with its **name, type, value and TTL** — the TTL is part of the change
     batch, so disclosing it for **every** record is what makes the consent informed, and a user who wants a
     different TTL has to say so before the write;
   - any conflict the `list-resource-record-sets` read found, and what happens to it (left alone and taken to
     the show-user path, not overwritten);
   - the confirmation that nothing existing is overwritten or deleted.

   Then ask in these terms, and proceed only on an explicit yes:

   > I'll add these records to `{zone_name}` (`{hosted_zone_id}`) as new records only, each with the
   > TTL shown above — this CREATEs them and replaces or deletes nothing already in the zone. Go
   > ahead?

   If the user declines, use the external DNS provider path below.
6. If permission is granted, write the absent records with an explicit `CREATE` action in one call.
   **Never use `UPSERT`:** AWS documents it as updating a record set that already exists with the request's
   values, so it silently replaces a live record. This file issues no `UPSERT` and no `DELETE`. Pass the change
   batch **inline** — `file://` is AWS-CLI-specific and does not resolve through the AWS MCP server:

   ```bash
   aws route53 change-resource-record-sets \
     --hosted-zone-id '{hosted_zone_id}' \
     --change-batch '{
       "Comment": "Amazon SES domain authentication records",
       "Changes": [
         {"Action": "CREATE", "ResourceRecordSet": {
           "Name": "{DKIM_TOKENS[0]}._domainkey.{domain}", "Type": "CNAME", "TTL": 1800,
           "ResourceRecords": [{"Value": "{DKIM_TOKENS[0]}.{SIGNING_HOSTED_ZONE}"}]}},
         {"Action": "CREATE", "ResourceRecordSet": {
           "Name": "{mail_from_subdomain}", "Type": "MX", "TTL": 1800,
           "ResourceRecords": [{"Value": "10 feedback-smtp.{region}.amazonses.com"}]}},
         {"Action": "CREATE", "ResourceRecordSet": {
           "Name": "{mail_from_subdomain}", "Type": "TXT", "TTL": 1800,
           "ResourceRecords": [{"Value": "\"v=spf1 include:amazonses.com ~all\""}]}}
       ]
     }'
   ```

   Repeat the CNAME entry for `DKIM_TOKENS[1]` and `DKIM_TOKENS[2]`, and add `_dmarc.{domain}` as a TXT entry
   unless **Step 5's DMARC check** found exactly one valid existing record, or found more than one
   `v=DMARC1` record — that is its blocking branch, where the extras come down to one effective policy
   before any record is added here. Up to six records, but **only
   those in `RECORDS_NEEDED` that the `list-resource-record-sets` read showed absent**: the batch is
   all-or-nothing, so one already-present record fails every change with `InvalidChangeBatch`, whose response
   carries one error message per failed change — read them to see which record collided. An existing but
   **invalid** `_dmarc` record is not omitted by that rule: like an existing TXT on the MAIL FROM name it
   takes the show-user path, where Step 5's record is the replacement value. Two shapes matter: **TXT values
   keep their own enclosing double quotes inside `Value`**, escaped as shown, and the MX priority `10` is part
   of the value string. `TTL` is the caller's choice; 1800 is an example, and whatever is used must be what
   the consent step disclosed.

**If external DNS provider:**

- Present the records in `RECORDS_NEEDED` — **only those**, each with name, type, value **and the TTL to
  set** — and have the user add them at their provider, applying the same omissions as the Route 53 path.
- Apply the SPF-collision check above before the SPF TXT record is added: the user publishes the merged value
  rather than a second record. Apply Step 4's MX rule the same way — another MX on the MAIL FROM name is
  removed, or MAIL FROM moves to another empty subdomain, before the SES MX is added.
- Apply Step 5's DMARC result the same way: a valid record means do not ask for another; more than one
  `v=DMARC1` record is the blocking branch, so the extras come down to one effective policy first.
- Warn about provider quirks: some append the domain automatically, so `{token}._domainkey` becomes
  `{token}._domainkey.example.com.example.com`.
- Once the user confirms the records are live, go to Step 7.

## Step 7: Verify DNS Propagation

After the user confirms the records are added:

```bash
# DKIM — all three, not just the first. Status cannot reach SUCCESS until all three resolve.
dig CNAME '{DKIM_TOKENS[0]}._domainkey.{domain}' +short
dig CNAME '{DKIM_TOKENS[1]}._domainkey.{domain}' +short
dig CNAME '{DKIM_TOKENS[2]}._domainkey.{domain}' +short

dig MX  '{mail_from_subdomain}' +short   # MAIL FROM MX
dig TXT '{mail_from_subdomain}' +short   # MAIL FROM SPF
dig TXT '_dmarc.{domain}' +short         # DMARC
```

Then confirm SES has picked up the changes:

```bash
aws sesv2 get-email-identity --email-identity '{domain}' --region '{region}'
```

Domain setup is complete only when all three fields in SKILL.md's domain-setup-complete gate are true in this
one response. Report which are outstanding rather than reporting "verified" on two.

## Troubleshooting: DKIM Stuck in PENDING

If DKIM remains PENDING after the records are added:

1. **Get the expected values from the API, not from memory:**

   ```bash
   aws sesv2 get-email-identity --email-identity '{domain}' --region '{region}' \
     --query 'DkimAttributes.{tokens:Tokens, zone:SigningHostedZone}'
   ```

2. **Check that all three CNAMEs resolve** — Step 7's three `dig CNAME` lookups. All three must resolve
   before the status can reach `SUCCESS`. Expected value: `{token}.{SIGNING_HOSTED_ZONE}`, built from the
   zone read in this session, never a literal remembered from another Region or account.

3. **Common causes:**
   - Value built from the wrong signing zone (a remembered literal, not this identity's `SigningHostedZone`)
   - DNS provider appended the domain (record is `{token}._domainkey.example.com.example.com`)
   - Records in a zone that exists but isn't authoritative — re-run Step 6's authority check, querying `{zone_name}`, not `{domain}`; if the name servers differ, add the records at the authoritative provider
   - Wildcard CNAME conflict overriding the specific DKIM record, or TTL propagation delay
   - More than one MX record on the MAIL FROM subdomain — does not affect DKIM, but blocks the MAIL FROM half of the gate

4. **If the records are correct but SES still shows `PENDING`:** there is no API to force re-verification;
   SES will find them on its own. The SESv2 API reference documents SES searching the domain's DNS
   configuration "for up to 72 hours"
   ([DkimAttributes](https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_DkimAttributes.html)) —
   the outer bound of the search, not the expected wait. Re-query after DNS propagates.

## Security Considerations

Apply SKILL.md's IAM, credential, CloudTrail and value-validation rules; the consent gate for any DNS write is
owned by Step 6 and must not be bypassed. When a domain identity is deleted or its DKIM keys are rotated, tell
the user to remove the DKIM CNAMEs the retired tokens point at: a CNAME left pointing at a target nobody owns
any more is a dangling-DNS record, the same class of exposure as a subdomain takeover. Large mailbox providers
publish their own authentication requirements for bulk senders, DMARC among them — check each provider's
current requirements rather than assuming a threshold.

## Next: what happens after the domain is set up

**This depends on what the user asked for — check the requested scope first.**

- **Domain setup only** (the common direct-invocation case: "set up my domain", "fix my DKIM") → **report the
  gate result as it stands, naming all three gate fields, and stop.** Say "complete" only when all three are
  true in one response; otherwise say it is incomplete and name the outstanding field. Step 4's
  `USE_DEFAULT_VALUE` fallback ends here **incomplete**, and so does an identity whose DKIM is out of scope
  per Step 2's origin gate and not already `SUCCESS`. Do not raise production access, do not offer a test
  send, and do not route into `onboarding.md`: neither was asked for, and one opens an AWS Support case while
  the other sends real mail. Say in one line that both are available when they want them.
- **The user asked for the full journey, production access, or a first/test send** → a verified domain is not
  yet a delivered email. Return to `onboarding.md` carrying `region` and `domain`; it re-reads identity state
  with `get-email-identity` rather than relying on values carried back, so hand back no DKIM tokens or signing
  zone. Report the gate result as it stands, and when Step 2's origin gate read a `DKIM_ORIGIN` other than
  `AWS_SES`, report that origin and `DkimAttributes.Status` with it.

If the scope is ambiguous, ask one question rather than assuming the larger one.
