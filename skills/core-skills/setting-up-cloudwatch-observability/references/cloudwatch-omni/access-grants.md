# CloudWatch Omni access grants

An **access grant** binds one **principal** — a person, group, IAM identity, Access
Profile, or alert — to one **permission level** on one **Space**. Grants are the Space's
own authorization records, and the only way anyone reaches telemetry **through the
Space** for people and profiles: an Identity Center user, console session, or Access
Profile with no matching grant can do nothing in the Space. (A direct IAM caller in the
owning account is the one exception: with no matching grant it falls through to its own
IAM policy — see [Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles).)
The caller who creates a Space receives a **service-managed `SPACE_ADMIN` grant**
(`grantType` `SERVICE_MANAGED`) at creation, so a new Space is never grant-less; that
grant cannot be deleted (`ConflictException`), and the service also refuses to revoke
the **last** `ADMIN`/`SPACE_ADMIN` grant on a Space.

So "how do I give X access", "who has access here", "what can X do", and "how is grant
`<id>` scoped" are all answered from — and acted on through — the Space's grants. One
authorization error is **not** a grant question: a Space that was just created
successfully and fails the moment anyone uses it has a space access role whose trust
policy `create-space` never verified — see the first callout under
[Troubleshooting](#troubleshooting) and answer it from
[spaces-and-domains.md](spaces-and-domains.md).

This file covers both halves: **configuring** grants (create, narrow, change, revoke)
and **looking them up** (who has access, at what level, how a specific grant is scoped).

Grants govern the Omni plane only: log groups a Space's data came from stay readable
under their own IAM (see [Security considerations](#security-considerations)).

> **Always state these, in any answer drawn from this file:**
>
> - Only four permissions are requestable: `READ`, `READ_WRITE_DELETE`,
>   `SPACE_ADMIN`, `CUSTOM`. There is no caller-usable `WRITE` or `DELETE`, and
>   `ADMIN` cannot be granted on a Space through the API at all.
> - `SPACE_ADMIN` is a **delegation** level — it lets the holder manage grants in the
>   Space (grant access to others) on top of read, write, and delete. It is not a
>   higher read level, nor a higher data-access tier — what it adds over
>   `READ_WRITE_DELETE` is delegation.
> - **"Make X an admin" is answered in this order, every time**, even when the customer
>   asks you not to pause: (1) the first sentence is the question — *what does X need to
>   do: read and change data, or grant other people access?*; (2) `READ_WRITE_DELETE` is
>   the recommendation, because that is what "admin" almost always means; (3)
>   `SPACE_ADMIN` only if X must manage others' access, and it is delegation, not a
>   higher data tier; (4) `ADMIN` cannot be granted on a Space through the API; (5) the
>   caller creating the grant needs `SPACE_ADMIN` on the Space or an administrative
>   grant on the Domain (see [Permission levels](#permission-levels)).
> - **Resolve the principal before any action** — grant, upgrade, revoke, or lookup.
>   A person or team named by alias, username, or email is not a `principalId`. Run
>   `search-principals --domain-id … --search-query <name>` and use the returned
>   `principalId` (UUID) with `principalType` from the result (`USER` → `IDC_USER`,
>   `GROUP` → `IDC_GROUP`). Stop if it does not resolve to exactly one principal. An
>   IAM identity is named by its ARN, and the type follows the ARN (`:user/` →
>   `IAM_USER`, `:role/` → `IAM_ROLE`, `:root` → `IAM_ROOT`). Never invent an ARN or
>   a UUID, and never assume `IAM_USER` for a name you have not resolved.
> - `create-access-grant` needs **all** of `--domain-id`, `--space-id`, `--name`,
>   `--principal`, and `--permission`. `--name` is required and the call is rejected
>   without it — never show a create command that omits it. A grant is not done when
>   the create returns: read it back, then tell the customer in their own words who can
>   now do what ("test-user can now read telemetry in this Space"), and that it applies
>   at the next authorization-cache turnover, so a session already open may need to be
>   re-established before it shows.
> - **Check before you create**: `list-access-grants --space-id … --principal-id …
>   --principal-type …` first. A second grant at the same named level conflicts.
> - Access is **deny-by-default** for people and profiles: an Identity Center user,
>   console session, or Access Profile with no matching grant can do nothing in the
>   Space. The one exception is a direct IAM caller in the owning account, which falls
>   through to its own IAM policy when no grant matches (see
>   [Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles)). Access is
>   opened deliberately, one grant at a time.
> - Grants **do not expire**. There is no expiry field on a grant; it stays in effect
>   until it is revoked. Revocation is **not instantaneous**: each Omni call is
>   re-authorized against the grants, so a revoke takes effect at the next
>   authorization-cache turnover (minutes) — even though credentials already issued
>   remain valid until they expire (up to an hour) or the session is re-established.
> - There is **no update operation**. For a **level change** (up- or downgrade), create
>   the new-level grant first, then delete the old one — different levels coexist, so
>   there is no gap and no lockout. For a **same-level** scope or name change, revoke
>   first (a duplicate conflicts), accepting a brief gap. Either way the replacement has
>   a **new grant ID** to update everywhere the old one was recorded.
> - `list-access-grants` is **paginated**: follow `nextToken` until it is absent, and
>   say how many grants you read. An **empty list is a successful finding**; an error
>   (`AccessDeniedException`) is **inconclusive**, never "nobody has access".
> - `ResourceNotFoundException` from `get-access-grant` is a finding, not a failure: no
>   grant has that ID — it was mistyped or already revoked. List the Space's grants to
>   find the right ID; never retry with a guessed one. Whenever you explain this error,
>   also say that `delete-access-grant` is **idempotent** — deleting a grant that no
>   longer exists succeeds rather than raising it — because "should I just delete it?"
>   is the customer's next question.
> - Identity Center principals appear as **UUIDs**. Resolve names with
>   `search-principals` in the Space's Domain — not the Identity Center console or the
>   `identitystore` CLI. An `IDC_GROUP` grant reaches **every member** and shows only
>   the group ID.
> - An alert principal is identified by its **ARN**, never its name (resolve with
>   `list-alerts`), and a grant with `principalId` `ALL` covers **every** alert.
> - Cross-account IAM grants are **not supported at the Space grant level**; the
>   principal must be in the caller's account. When the customer's goal is
>   cross-account access, **lead with the organization Domain path**
>   (`get-space-credentials-for-organization` vends credentials for a target account —
>   see [org-domains.md](org-domains.md)); do not present an IAM assume-role hop or a
>   different permission level as the answer.
> - `scopedActions` works with **any** permission, and does a different job in each
>   case: with `CUSTOM` it *defines* the grant (only the listed actions are allowed);
>   with a named permission such as `READ` it *narrows* that permission to the listed
>   resources, and every action named must be within that permission's tier — nothing
>   mutating can be scoped under `READ`.
> - A scope's shape and validation, all of which belong in any answer about a rejected
>   `scopedActions`: `resources` is a plain list of scopes (not an object with a
>   `scopes` member), each with a required `resourceType` and up to five optional
>   `resourceArns` (`DataSet` is the one type that takes none — it is narrowed by rows);
>   `resourceType` is a plain string validated **per (action,
>   resourceType) pair**, case-sensitively — an unknown spelling such as `Dataset` is
>   rejected with a message that lists the accepted values (`DataSet`), while a known
>   type paired with an action that does not operate on it is rejected with a message
>   that lists nothing; and **both `Space` and `Domain`** are invalid inside a scope —
>   omit `resources` to cover the whole Space.
> - Within a single `scopedActions` entry, **all actions must share the same prefix**;
>   use a separate entry per prefix.
> - Whenever you show a scoped grant, say that `resources` **inside** a `scopedActions`
>   entry is a plain list of scopes, not an object with a `scopes` member. There is no
>   top-level `resources` or `customActions` on a grant — `scopedActions` is the only
>   scope field.
> - Access questions are answered from the **grants** — never by pivoting to IAM
>   identity or IAM policy APIs (not even `sts get-caller-identity`), and never by
>   sending the customer to the console when the CLI answers directly.

## Where to look, by kind of question

Every access question is one of five kinds. Find the kind, read that section, and apply
the rules in the block above — they hold for all five.

| Kind of question | Examples | Section |
|---|---|---|
| **Give or widen access** | give a person or team access; make someone an "admin"; grant a role, alert, or profile | [Granting access](#granting-access) — Step 2 resolves the principal, Step 3 creates the grant |
| **Change a grant** | upgrade or downgrade a level; re-scope or rename; remove your own admin grant | [Changing a grant](#changing-a-grant) |
| **Remove access** | revoke one grant; revoke everything a person holds; "I revoked but they still have access" | [Revoking a grant](#revoking-a-grant) |
| **Look up who has what** | who has access and at what level; what does X hold; does alert or profile Y have a grant; audit who can grant, write, or delete; how is grant Z scoped | [Looking up access](#looking-up-access) |
| **Interpret an error or a surprise** | `AccessDeniedException`, `ResourceNotFoundException`, `ConflictException`, `ValidationException` on `scopedActions`; a grant that "does not work" in another Region; cross-account requests | [Troubleshooting](#troubleshooting), [Gotchas](#gotchas--expectations-that-look-like-faults) |

## Contents

- [Where to look, by kind of question](#where-to-look-by-kind-of-question)
- [What an access grant is](#what-an-access-grant-is)
  - [Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles)
  - [What a grant reaches](#what-a-grant-reaches)
- [Permission levels](#permission-levels)
  - [When the customer asks for an "admin"](#when-the-customer-asks-for-an-admin)
- [Operations you will call](#operations-you-will-call)
- [Prerequisites](#prerequisites)
- [Granting access](#granting-access)
  - [Cross-account access](#cross-account-access)
  - [Step 1 — Interview the customer first](#step-1--interview-the-customer-first)
  - [Step 2 — Identify the principal](#step-2--identify-the-principal)
  - [Step 3 — Create the grant](#step-3--create-the-grant)
  - [Step 4 — Narrow the grant with scoped actions](#step-4--narrow-the-grant-with-scoped-actions)
  - [Step 5 — Verify, then report](#step-5--verify-then-report)
- [Changing a grant](#changing-a-grant)
- [Revoking a grant](#revoking-a-grant)
- [Looking up access](#looking-up-access)
  - [Who has access to the Space](#who-has-access-to-the-space)
  - [What a given principal holds](#what-a-given-principal-holds)
  - [Finding a person by name or alias](#finding-a-person-by-name-or-alias)
  - [How a specific grant is scoped](#how-a-specific-grant-is-scoped)
  - [Reporting a lookup](#reporting-a-lookup)
- [Troubleshooting](#troubleshooting)
- [Gotchas — expectations that look like faults](#gotchas--expectations-that-look-like-faults)
- [Security considerations](#security-considerations)
- [Additional resources](#additional-resources)

## What an access grant is

The model is **Domain → Space → grant**. A Domain is the identity boundary (how members
sign in — IAM and/or IAM Identity Center); a Space is the account-scoped boundary for
Omni resources; grants are written inside a Space. See `aws-observability` → `references/cloudwatch-omni/concepts.md`
for how the pieces connect and [spaces-and-domains.md](spaces-and-domains.md) for
creating a Domain and Space.

Every grant names three things, and every lookup answers a question about one of them:

- **A principal** — `principalType` plus, normally, `principalId`. What `principalId`
  holds depends on the type:

  | `principalType` | `principalId` |
  |---|---|
  | `IDC_USER`, `IDC_GROUP` | The Identity Center user or group ID (a UUID, not an alias). Verified against the Domain's identity store |
  | `IAM_USER`, `IAM_ROLE`, `IAM_ROOT` | The IAM ARN. Must be in the caller's account |
  | `ACCESS_PROFILE` | The Access Profile's ID — see [access-profiles.md](access-profiles.md) |
  | `ALERT` | An alert's ARN — the `alertArn` that `list-alerts` returns — or the reserved, case-sensitive token `ALL` meaning every alert in the Space. **Never the alert's name or its `alertId`.** `ALL` is accepted only for `ALERT`, and only on a `CUSTOM` grant whose single action is `AssumeAccessProfile`; any other use is rejected ("Wildcard principal identifier is not supported for this principal type"). A profile that alerts created later must assume needs `ALL`: `CreateAlert` authorizes against the wildcard `alert/*` ARN, which only `ALL` matches |
  | `AGENT` | An agent workload principal — a service-defined identifier for the agent, not an IAM ARN |

- **A permission** — one of `READ`, `READ_WRITE_DELETE`, `SPACE_ADMIN`, or `CUSTOM`.
  See [Permission levels](#permission-levels).
- **A scope** — the actions and resources a `CUSTOM` grant allows, or the narrowing
  applied to a named permission. Scope is **not** on a list summary; it is only on a
  single grant's detail (`get-access-grant`).

A grant also carries a required `name`, and its detail records **who created it and
when** — `createdBy`, `createdAt`, `updatedAt`. It carries **no expiry**: there is no
expiry field on either the summary or the detail. Never tell a customer a grant expires
or report an expiry time; if asked when access ends, say grants do not expire and are
removed by revoking them.

### Grants, IAM, and Access Profiles

Three mechanisms sit near each other and are routinely confused. Keep them apart:

| Mechanism | What it governs | Where it is documented |
|---|---|---|
| **Access grant** | What a principal may do **through a Space** — the Omni plane | This file |
| **IAM policy** | Whether a caller can reach the AWS API at all, and access to source data (for example the CloudWatch log groups a Space ingests from) that sits **outside** the Space | IAM, and `aws-observability` → `references/cloudwatch-omni/programmatic-access.md` for how IAM callers and grants combine |
| **Access Profile** | A named container a workload (an alert, agent, or integration) **assumes**; it does nothing until grants are attached to it | [access-profiles.md](access-profiles.md) |

- **Grants are not IAM, and they bind the two caller types differently.** A human
  identity — an IAM Identity Center user, a console session, or a workload that has
  assumed an Access Profile — must hold a matching grant: with none, the Space denies
  the call regardless of IAM. An IAM principal calling the API directly with its own
  credentials (no Omni session context) is treated as a machine identity, for which a
  grant is optional: grants that match it are enforced (their row and column scopes
  apply, and an explicit deny wins), but when none match the Space does not deny — the
  request falls through to the caller's IAM policy, which alone decides, with no row
  restriction applied. Direct IAM callers reach only Spaces owned by their own account.
  So "who has access to this Space" is the grants for people and profiles, plus IAM
  policy for direct IAM callers that hold no grant — check both.
- **Grants are not Access Profiles.** A profile bounds what a workload may do; it is
  itself the *principal* of the grants that describe its permissions, and the *target*
  of trust grants that say which workloads may assume it. Give a person or a team
  access with a grant directly — never by creating a profile for them.
- **Deny-by-default.** A human principal or profile with no matching grant can do
  nothing in the Space (a direct IAM caller with no grant is governed by IAM, above).
  There is nothing to "lock down" after creating a Space; there is only access to open,
  one grant at a time.

### What a grant reaches

A grant is scoped to **one principal in one Space**. It does not span Spaces, Regions,
or accounts.

Limits worth stating before the customer designs their access model, because they
surface as conflicts rather than as advice:

- **50 grants per principal**, and **500 grants per Space**.
- **10 `CUSTOM` grants per principal per Space.** Named-permission grants are
  additionally **one per principal per Space per level** — a second `READ` grant for
  the same principal conflicts rather than replacing the first.
- A grant enforces at most **10 scoped-action entries**, **25 actions per entry**, and
  **50 actions per grant** in total, with up to **10 resource scopes** per entry and
  **5 `resourceArns`** per scope — report these as the effective limits. (The API
  schema's ceilings are higher, but the service rejects anything above the effective
  limits, so only the effective limits are worth telling a customer.)

**Constraints:**

- You MUST tell the customer that a grant covers one Space only. A customer with
  Spaces in several Regions needs a grant per Space, and will otherwise read the
  missing access as a bug.
- You MUST NOT create a second grant at the same named permission for a principal
  already holding one. Read the existing grant instead — see
  [Step 2](#step-2--identify-the-principal).
- You MUST NOT create a Space grant when the customer describes organization-wide
  administration. A grant here names exactly one Space; a Domain grant is a different
  operation in [org-domains.md](org-domains.md).

## Permission levels

The permission decides the shape of the whole create call:

| The customer wants | `permission` | Extra input |
|---|---|---|
| Read the Space's telemetry | `READ` | None |
| Read, write, and delete within the Space | `READ_WRITE_DELETE` | None |
| Manage grants in the Space, i.e. delegate access to others (includes read, write, and delete) | `SPACE_ADMIN` | None |
| "Make X an admin" | Ask what X needs to do first. `READ_WRITE_DELETE` — unless X must grant other people access, in which case `SPACE_ADMIN`. The caller needs `SPACE_ADMIN` or Domain administration to create either | None |
| Exactly the actions they name, and nothing else | `CUSTOM` | `scopedActions` is required |

Those four are the only values a caller may request. The service rejects anything else
with a message naming the supported set. `ADMIN` exists only through Domain-level
administration and cannot be granted on a Space.

**`SPACE_ADMIN` is a delegation level, not a higher read level.** It conveys the
ability to manage grants in the Space — to give other principals access. The other
three levels confer no delegation ability. Someone who simply needs broad access to the
data wants `READ_WRITE_DELETE` instead.

### When the customer asks for an "admin"

"Admin" is not a permission, and the most common mistake in this file is granting
`SPACE_ADMIN` because the customer used the word. Find out what the person needs to
*do* — even when answering in a single message, open with that question and then answer
both branches:

- **Read, write, and delete telemetry and resources** in the Space. This is what
  "admin" almost always means, and it is the recommendation: **`READ_WRITE_DELETE`**.
- **Give other people access** (manage grants). Only then **`SPACE_ADMIN`**, which
  includes read, write, and delete and adds grant management on top. What it adds is
  delegation, not more data.
- **`ADMIN`** cannot be granted on a Space through the API; only `READ`,
  `READ_WRITE_DELETE`, `SPACE_ADMIN`, and `CUSTOM` are requestable.

A good opening reads: *"It depends on what test-user needs to do. If they need to read,
write, and delete in the Space — which is what admin usually means — grant
`READ_WRITE_DELETE`. Grant `SPACE_ADMIN` only if they also need to give other people
access."*

**Constraints:**

- You MUST put the question — what does the person need to *do*? — before any
  permission name, even when the customer asked you not to pause. Asking it and then
  answering both branches in the same message satisfies both. An answer that opens with
  `SPACE_ADMIN`, or that silently assumes one branch, has skipped the step.
- You MUST recommend `READ_WRITE_DELETE` as the default reading of "admin", and offer
  `SPACE_ADMIN` only for the case where the person must manage others' access.
- You MUST state that `ADMIN` is not grantable on a Space, and that the caller creating
  the grant needs `SPACE_ADMIN` on the Space or an administrative grant on the Domain.
- The person still has to be resolved to a `principalId` and `principalType` before any
  command is written (Step 2).

Any of the four can additionally be **narrowed to particular resources** with
`scopedActions` — see [Step 4](#step-4--narrow-the-grant-with-scoped-actions). That is
a separate decision from the permission itself.

**What a caller may delegate** is bounded by what the caller holds:

- A caller with Domain administration may grant any of the four requestable
  permissions. **No caller can grant `ADMIN`** — it is not requestable through the API
  at all, whatever the caller holds.
- A caller with `SPACE_ADMIN` on the Space may grant `SPACE_ADMIN`, `READ`,
  `READ_WRITE_DELETE`, and `CUSTOM` within it.
- A caller with a lesser grant may not manage grants.
- No caller, at any level, can grant to a principal outside the Space's own account —
  cross-account IAM grants are not supported at the Space grant level.

**Least privilege** is per-grant narrowing: prefer several narrow grants over one broad
one, and the narrowest named level over `CUSTOM`.

**Constraints:**

- You MUST NOT offer a write-only or delete-only grant. There is no caller-usable
  `WRITE` or `DELETE` permission — `READ_WRITE_DELETE` is the only value that conveys
  mutation.
- You SHOULD start from the narrowest named permission that satisfies the request and
  reach for `CUSTOM` only when no named level fits. `CUSTOM` grants carry more ways to
  be wrong and count against a tighter quota.
- You MUST NOT attempt to grant a permission broader than the caller holds. The
  rejection names both levels, so read it rather than retrying.

## Operations you will call

Every operation is an `aws cloudwatchomni <operation>` CLI command, with the
operation's input-shape members passed as `--flags`. Run it through the `aws___call_aws`
tool when that tool is available; otherwise run the same command in a shell. See
`aws-observability` → `references/cloudwatch-omni/programmatic-access.md` for the service name, signing
name, and what to do when the local CLI does not know `cloudwatchomni`.

**`aws cloudwatchomni` (Omni control-plane):**

| Intent | CLI command |
|---|---|
| Find an Identity Center principal in the Domain by name or email | `aws cloudwatchomni search-principals` |
| List grants on a Space — who has access, what a principal holds | `aws cloudwatchomni list-access-grants` |
| Read one grant back — its scope and who created it | `aws cloudwatchomni get-access-grant` |
| Create a grant | `aws cloudwatchomni create-access-grant` |
| Revoke a grant | `aws cloudwatchomni delete-access-grant` |

There is **no update operation** for a grant. Changing a grant's level, scope, or name
means revoking it and creating a new one — see [Changing a grant](#changing-a-grant).

If the API is not reachable from where you are running — `aws cloudwatchomni` is
unknown to the installed CLI, `call_aws`/boto3 reports the service as unsupported, or
the CLI knows the service but cannot resolve its endpoint — say so in one sentence and
answer from this file: give the exact commands, in order, with the customer's
identifiers filled in, and what each result means. Do not spend the answer hunting for
service models, endpoint rule sets, or alternative SDKs on the local machine; that is
never what the customer asked.

These five are the only grant operations an access question needs; resolving a
principal's name may additionally use `list-alerts` or `list-access-profiles` (Step 2).
Do not reach for IAM or STS (`iam get-role`, `iam simulate-principal-policy`, `sts get-caller-identity`,
`identitystore describe-user`) to answer who has access or why a lookup was denied —
the grants are the authorization records, and an `AccessDeniedException` on a grant
lookup is answered by the caller's own grant, not by their IAM identity.

## Prerequisites

- **The Space's `spaceId` and its Domain's `domainId`.** Both are required on the
  create. See [spaces-and-domains.md](spaces-and-domains.md) if the Space does not
  exist yet. Lookups need the `spaceId`; `search-principals` needs the `domainId`.
- **A `SPACE_ADMIN` grant on that Space, or an administrative grant on the Domain.** A
  caller holding neither cannot manage grants at all.
- **For Identity Center principals**, the Domain must use Identity Center, and the
  principal must exist in the Domain's identity store. The service verifies this at
  create time.
- **Cross-account IAM grants are not supported at the Space grant level.** No caller,
  at any permission level, can create a Space access grant for a principal outside
  their own account. Say this plainly rather than implying it by describing the
  principal as being "in your account". Scope the claim to Space grants — it is not
  true of Omni as a whole. The organization Domain path reaches across accounts by a
  different mechanism: `get-space-credentials-for-organization` vends temporary
  credentials **for a target account** (see [org-domains.md](org-domains.md)). If a
  customer's actual goal is cross-account access, point them there instead of telling
  them it is impossible — and lead with it, rather than mentioning it as a footnote.

**Constraints:**

- You MUST NOT create grants for principals in another account. Cross-account IAM
  grants are not supported, and the rejection says so explicitly.
- You MUST NOT present a workaround as the answer to a cross-account ask — neither
  retrying `create-access-grant` at a different permission level (the check is on the
  principal's account, not the level) nor an IAM assume-role hop through a local role.
  The organization Domain path is the mechanism that reaches across accounts; describe
  it first, and describe anything else only if the customer rules that path out.

## Granting access

First, confirm the grant belongs at the Space level at all:

| The customer wants | Path |
|---|---|
| A principal to have access to one Space | **This file** |
| A principal to administer an entire Domain across an organization | **Domain access grant** — see [org-domains.md](org-domains.md) |
| A workload (alert, agent, integration) bounded by a set of actions it may assume | **Access Profile** — see [access-profiles.md](access-profiles.md) |
| A principal in **another AWS account** | **Not a Space grant** — see [Cross-account access](#cross-account-access) below |

### Cross-account access

A Space access grant cannot name a principal outside the Space's own account. The
service rejects the attempt with a `ValidationException` saying cross-account grants
are not supported, at every permission level — there is no level, flag, or retry that
changes this. Say that plainly, and scope it to Space grants: it is not true of Omni as
a whole.

The mechanism that reaches across accounts is the **organization Domain**. In a Domain
shared across an AWS Organization, `get-space-credentials-for-organization` vends
temporary credentials **for a target account's Space** to the organization's management
account or a delegated administrator, and `create-domain-access-grant-for-organization`
grants Domain-level administration. When the customer's goal is cross-account access,
point them there — [org-domains.md](org-domains.md) — as the answer, not as a footnote.

Do not offer an IAM assume-role hop through a local role, or a retry at a different
permission level, as the way to do this. The first moves the problem into IAM and gives
the customer a same-account principal; the second fails identically.

### Step 1 — Interview the customer first

Ask these in one message and wait for answers. Do not ask piecemeal, and do not
default silently.

1. **Which Space?** The `spaceId`, and the `domainId` it belongs to.
2. **Who is getting access?** A person or group in Identity Center, an IAM role or
   user, or a workload such as an alert or an Access Profile.
3. **What do they need to do?** Map the answer to one of the four permissions in
   [Permission levels](#permission-levels). Ask what they need to *do*, not which
   permission they want — customers routinely ask for more than the task requires.
4. **If `CUSTOM`:** exactly which actions. Wildcards are not accepted, so the list has
   to be explicit.
5. **Should the grant be limited to particular resources?** Optional, and only worth
   raising if the customer has a reason — see
   [Step 4](#step-4--narrow-the-grant-with-scoped-actions).
6. **A name for the grant?** Required. Letters, digits, underscores and hyphens; 1–64
   characters. Pick one that tells the grant apart when a principal holds several.

Confirm the choices back in one line, then execute.

**Constraints:**

- You MUST ask what the principal needs to do before proposing a permission. A
  customer asking for "admin" usually needs `READ_WRITE_DELETE`, and `SPACE_ADMIN`
  lets them re-grant access to others.
- You MUST NOT assume `CUSTOM`. Reach for it only when the customer's answer to
  question 3 does not fit a named level.

### Step 2 — Identify the principal

This step is not optional and not specific to granting: **every** action that names a
principal — grant, upgrade, downgrade, revoke, "what does X hold" — starts by turning the
name the customer used into an exact `principalId` **and** `principalType`.

| The customer gave you | `principalType` | `principalId` |
|---|---|---|
| A person's or team's name, alias, username, or email | `IDC_USER` or `IDC_GROUP` — from the `search-principals` result's `principalType` (`USER`/`GROUP`) | The UUID `search-principals` returns |
| An IAM ARN containing `:user/` | `IAM_USER` | The ARN as given |
| An IAM ARN containing `:role/` | `IAM_ROLE` | The ARN as given |
| An IAM ARN ending in `:root` | `IAM_ROOT` | The ARN as given |
| An alert's name | `ALERT` | The `alertArn` from `list-alerts --space-id <space-id> --filter-criteria '{"names": ["<name>"]}'` |
| An Access Profile's name | `ACCESS_PROFILE` | The profile ID from `list-access-profiles` |

If a name resolves to zero or to more than one principal, stop and say so. Do not
substitute a principal from the Space's grant list, do not guess a UUID, and do not
fabricate an IAM ARN from the name.

#### Find an Identity Center principal

If the customer knows the person or group by name rather than by ID, look it up rather
than asking them to find it:

```
aws cloudwatchomni search-principals --domain-id <domain-id> --search-query <name-or-email>
```

Use the returned `principalId` (the Identity Center UUID) as the grant's `principalId`,
and map the result's `principalType` — `USER` or `GROUP` — to `IDC_USER` or
`IDC_GROUP`. Each result also carries `displayName` and, for users, `userName`; there
is no email field. A name search returns at most 10 results and does not paginate. To
pull the whole directory (for resolving many UUIDs from a grant list), search for `*`:

```
aws cloudwatchomni search-principals --domain-id <domain-id> --search-query '*' --max-results 50
```

Only the `*` search accepts `--max-results` (1–50) and `--next-token`. This operation
searches Identity Center only, and only works when the Domain uses Identity Center.

#### Check what the principal already has

Pass both `principalId` and `principalType` — the same identifier can be valid for more
than one type, and filtering on both keeps the result unambiguous.

```
aws cloudwatchomni list-access-grants --space-id <space-id> --principal-id <principal-id> --principal-type <principal-type>
```

`--principal-type` also decides *which* grants you see. For an Identity Center user,
`--principal-id` alone returns the person's **effective** grants — their own plus the
ones inherited through `IDC_GROUP` membership (those keep the group as `principal`);
adding `--principal-type IDC_USER` narrows to the grants made to the user directly.
Use both when the question is "does this person already hold their own `READ` grant";
drop the type when the question is "what can this person do here".

Read the result before creating anything. If a grant at the requested named permission
already exists, report it and stop — a duplicate conflicts rather than replacing it. If
the customer wants a *different* level, see [Changing a grant](#changing-a-grant).

**Constraints:**

- You MUST run this check before `create-access-grant`. A conflict after the fact is
  avoidable and confusing.
- You MUST prefer `IDC_GROUP` over `IDC_USER` when the customer is describing a team
  or a role rather than one person. Group membership changes without touching grants.
- If the check cannot be completed — access denied, or an ambiguous response — you
  MUST treat the result as **inconclusive, not negative**. Report that and stop. You
  MUST NOT create a grant on that basis.

### Step 3 — Create the grant

#### A named permission

```
aws cloudwatchomni create-access-grant --domain-id <domain-id> --space-id <space-id> --name <grant-name> \
  --principal '{"principalType": "<principal-type>", "principalId": "<principal-id>"}' --permission READ
```

Substitute `READ_WRITE_DELETE` or `SPACE_ADMIN` as the interview decided. `--name` is
required; the call is rejected without it.

#### A `CUSTOM` permission

`CUSTOM` requires `scopedActions`, which names the actions the principal may perform.
Nothing outside that list is permitted.

```
aws cloudwatchomni create-access-grant --domain-id <domain-id> --space-id <space-id> --name <grant-name> \
  --principal '{"principalType": "<principal-type>", "principalId": "<principal-id>"}' --permission CUSTOM \
  --scoped-actions '[{"actions": ["<prefix>:<Action>"]}]'
```

Action names are `prefix:Action` — a lowercase service prefix, a colon, then the action
name in upper camel case with no underscores or hyphens. **Wildcards are not
permitted**, so every action is named explicitly. All actions within one
`scopedActions` entry must share the same prefix; use separate entries for separate
prefixes.

Capture the grant ID from the response. It is what `get-access-grant` and
`delete-access-grant` take.

**Constraints:**

- `permission` is always required. There is no default, and `CUSTOM` is never inferred
  from the presence of `scopedActions`.
- You MUST NOT attempt a wildcard action. Expand the customer's intent into an explicit
  list, and if they cannot enumerate it, a named permission is the right answer
  instead.
- The action prefix MUST match the service's vendor code. A prefix that does not is
  rejected, and the message names the expected one.
- With a named permission, every action you name in `scopedActions` MUST be within
  that permission's tier. Naming a mutating action under `READ` is rejected, and the
  message names both the action and the permission.
- You MUST NOT grant administrative actions to an `ACCESS_PROFILE` principal. The
  service rejects it, and a profile is not the right place for administration.

### Step 4 — Narrow the grant with scoped actions

`scopedActions` does two different jobs, and which one applies depends on the
permission:

- With **`CUSTOM`**, it defines the grant. The principal may perform exactly the
  actions named and nothing else.
- With a **named permission**, it narrows that permission. The actions named are
  restricted to the resources listed in the same entry, rather than applying across the
  whole Space.

Each entry requires `actions` and may add `resources`. The shape of a scope, which any
answer about a rejected scope should restate:

| Field | Shape | Rule |
|---|---|---|
| `resources` | **plain list** of scopes (a JSON array, not an object with a `scopes` member), up to 10 per entry | Omit it to cover every resource in the Space |
| `resourceType` | required plain string | Validated **per (action, resourceType) pair**, case-sensitively. `Space` and `Domain` are never valid. Unknown spelling → `Unknown resourceType. Allowed values: …` (lists them); known type with an action that does not operate on it → `Resource type X is not valid for action Y` (lists nothing) |
| `resourceArns` | optional, **up to five** ARNs | Omit to cover every resource of that type. `DataSet` accepts none — it is narrowed by rows instead |
| `signalTypes` + `rowScopeGroups` | optional, together, `DataSet` only | Row-level filtering; see below |

Every scope requires a `resourceType` and may add:

- **`resourceArns`** — up to 5 ARNs. Omit to cover every resource of that type.
  (One exception: a `DataSet` scope takes no `resourceArns` — the service rejects a
  dataset ARN with `Invalid observe resource type in ARN` — and is narrowed by *rows*
  instead, with `signalTypes` + `rowScopeGroups` below.)
- **`signalTypes`** and **`rowScopeGroups`** — row-level filtering, and only on the
  `DataSet` resource type. See below.

`resourceType` is a plain string, not an enum, and the service validates it **per
(action, resourceType) pair**: a type is accepted only alongside actions that operate
on that kind of resource. The types the service knows are `AccessGrant`, `DataStore`,
`DataSet`, `DataStream`, `Source`, `Route`, `Processor`, `Integration`,
`OmniIntelligenceRule`, `AccessProfile`, `OmniThread`, `OmniAgentAsset`,
`AccountConfiguration`, `OmniDashboard`, `DataSource`, `Alert`, `EvaluationJob`,
`Evaluator`, `OnlineEvaluation`, `View`, `IngestionEndpoint`.

- `Space` and `Domain` are **not** valid here — neither of them, for the same reason: a
  grant is already scoped to a single Space or Domain, so a parent-typed scope is
  rejected with a 400. To cover the whole Space, omit `resources` instead.
- Casing matters: `DataSet` is accepted; `Dataset` is rejected as an unknown type, and
  that message lists the accepted spellings. A known type paired with an action that
  does not operate on it is rejected with `Resource type X is not valid for action Y`,
  which does not.

- The Console's scope picker offers only four of these types; its "Dashboard" entry
  sends `OmniDashboard`.

```
"scopedActions": [{"actions": ["<prefix>:<Action>"], "resources": [{"resourceType": "<resource-type>", "resourceArns": ["<arn>"]}]}]
```

**`resources` inside a `scopedActions` entry is a plain list of scopes** — a JSON
array — *not* an object with a `scopes` member. `scopedActions` is the only scope
field on a grant; there is no top-level `resources` or `customActions`.

#### Row-level scoping, on `DataSet` only

`rowScopeGroups` restricts which *records* a principal sees, rather than which
resources — and only which records. It is not field-level redaction: a record the
principal is allowed to retrieve comes back whole, with every field in it. It is available only on a scope whose `resourceType` is `DataSet`, and
`signalTypes` and `rowScopeGroups` must appear together — either both or neither.

> **`DataSet` names the plane this scope acts on, and it is the only one.** Row scoping
> filters retrieval through the Dataset. It does not restrict the CloudWatch log groups
> the Dataset was populated from, which remain readable through the native `logs:` APIs
> under separate IAM. Never present row scoping as sufficient to keep a principal away
> from data — see **Grants do not bound the CloudWatch Logs plane** under
> [Security considerations](#security-considerations).

A `DataSet` scope may only name the actions `GetRecords`, `GetMetricData`, and
`ListMetrics`. Any other action alongside a `DataSet` scope is rejected.

The structure is a list of groups. A record matches if it satisfies **any** group, and
within a group **every** condition must hold. Each condition names a `field`, the
operator `IN`, and up to **50** `values`. Up to **5** groups, each with up to **5**
conditions — the service rejects anything larger with `exceeds the maximum of 50` /
`exceeds the maximum of 5`, whatever higher ceilings the API schema advertises.

Anything not named in `values` is excluded, and **excluded data is indistinguishable
from absent data** — the principal sees a smaller result set with nothing to indicate
that a filter removed anything.

```
"scopedActions": [{"actions": ["<prefix>:GetRecords"], "resources": [{"resourceType": "DataSet", "signalTypes": ["LOGS"], "rowScopeGroups": [[{"field": "<field>", "operator": "IN", "values": ["<value>"]}]]}]}]
```

**Constraints:**

- `signalTypes` and `rowScopeGroups` MUST both be present or both absent, and MUST
  appear only on a `DataSet` scope. Either half alone is rejected, and so is their use
  on any other resource type.
- `IN` is the only operator. There is no negation, no comparison, and no pattern match,
  so a row scope can only ever be an allowlist of values.
- You MUST NOT use row scoping to restrict metrics. The `METRICS` signal type is not
  supported and the grant is rejected.
- You MUST explain the any-group / all-conditions structure back to the customer before
  creating it. A customer who reads the groups as "and" will believe the grant is
  broader than it is, and one who reads the conditions as "or" will believe it is
  narrower.
- You SHOULD skip scoping entirely unless the customer has a specific reason. A
  narrowed grant that excludes the wrong thing is indistinguishable from a broken one.
- When a `scopedActions` call is rejected, you MUST explain the model the service
  applies, not just the one bad value: `resources` is a plain list of scopes, each with
  a required `resourceType` and up to five optional `resourceArns`; `resourceType` is a
  plain string validated **per (action, resourceType) pair**, case-sensitively; `Space`
  and `Domain` are never accepted inside a scope (omit `resources` to cover the whole
  Space); and every action must be within the named permission's tier.

### Step 5 — Verify, then report

1. Read the grant back rather than trusting the create response:

   ```
   aws cloudwatchomni get-access-grant --grant-id <grant-id>
   ```

   Confirm the principal, the permission, the Space, and — if the grant was narrowed —
   the scoped actions and resources are what the customer asked for.

2. Report the outcome in the customer's own terms as well as the API value: "test-user
   can now read telemetry in this Space (`READ`)". The plain-language half is what the
   customer can check; the API value alone is not.

3. Say when it takes effect: a new grant, like a revoke, applies at the next
   authorization-cache turnover (minutes), not the instant it is created, so a session
   the person already has open may need to be refreshed or re-established before they
   see the Space.

## Changing a grant

There is no update operation. Changing a grant's permission level, its scope, or its
name is a revoke plus a create — but **the order depends on whether the new grant is at
the same named level as the old one**, and getting it wrong either fails or opens a gap:

**Changing to a *different* level (an up- or downgrade, e.g. `READ` → `READ_WRITE_DELETE`,
or `SPACE_ADMIN` → `READ`) — create first, then delete.** Named-permission grants are
one per principal per Space *per level*, so a grant at a different level coexists with
the old one. Create the new grant first, verify it, then revoke the old one. The
principal is never without access. Two separate protections matter when the grant being
removed is an administrative one:

- **Create-first avoids a gap and a lockout** for the caller's own downgrade: the new
  same-principal grant (say, `READ`) exists before the `SPACE_ADMIN` grant goes, so the
  caller is never without access.
- **Last-admin protection is independent of that.** The service refuses to delete the
  Space's last `ADMIN`/`SPACE_ADMIN` grant *regardless* of what other grants the caller
  holds — a `READ` grant does not count. If the caller is the only administrator,
  another principal must be granted `SPACE_ADMIN` before the delete will succeed.

1. Read the existing grant with `get-access-grant` and confirm with the customer which
   grant is changing and what it conveys.
2. Create the new-level grant with `create-access-grant` (Step 3), then verify it with
   `get-access-grant`.
3. Revoke the old grant with `delete-access-grant`.

**Changing the scope or name at the *same* level — revoke first, then create.** A second
grant at the same named level conflicts, so the old one has to go before the replacement
can be made. This is the only case with an unavoidable brief gap; do it when the gap is
acceptable.

1. Read the existing grant with `get-access-grant` and confirm.
2. Revoke it with `delete-access-grant` — see [Revoking a grant](#revoking-a-grant).
3. Create the replacement with `create-access-grant` (Step 3), then verify it.

Either way the replacement has a **new grant ID**, so anything that recorded the old ID
(a runbook, an audit note) needs updating — say so.

### Downgrading or removing your own or the last admin grant

Removing the caller's own `SPACE_ADMIN`, or the Space's only administrative grant, needs
care because the service **refuses to revoke the last `ADMIN`/`SPACE_ADMIN` grant**
(`ConflictException`), and even where it would succeed, doing the delete first can lock
the caller out of grant management:

Procedure for a self-downgrade (for example `SPACE_ADMIN` → `READ`, a different level):

1. **Warn first**: revoking your own `SPACE_ADMIN` removes your ability to manage grants
   in this Space; only another `SPACE_ADMIN` (or Domain administration) can restore it.
2. **Confirm the grant you are about to remove** by listing it, not from memory:
   `list-access-grants --space-id <space-id> --principal-id <caller> --principal-type
   <type>`. Note the `SPACE_ADMIN` grant's ID and confirm what it conveys.
3. **If you are the only `SPACE_ADMIN`**, the delete will be refused — the Space must
   keep one administrator — so first grant another principal `SPACE_ADMIN` and verify
   it with `get-access-grant`.
4. **Create the `READ` grant before deleting anything**: `create-access-grant … --name
   … --permission READ`, then `get-access-grant` to verify it exists. Different levels
   coexist, so there is no gap.
5. **Only now** `delete-access-grant --grant-id <space-admin-grant-id>`. It does not
   affect the new `READ` grant or any other grant you hold.
6. The change takes effect on the timeline described under
   [Revoking a grant](#revoking-a-grant); refresh the session before expecting the
   console to show `READ` only.

**Constraints:**

- For a **same-level** change you MUST NOT create the second grant first — it conflicts;
  revoke first. For a **level change** you SHOULD create the new-level grant first and
  delete the old one after, so the principal is never without access and an admin
  downgrade does not lock anyone out.
- You MUST NOT revoke a customer's grant to "change" it without first confirming the
  replacement's exact permission and scope; a revoke with no agreed replacement is
  simply a revocation.
- You MUST describe the change as what it is — a new grant created plus the old one
  revoked — never as an in-place update, edit, or "downgrade" of the existing grant,
  because no such operation exists. Say that the replacement carries a **new grant
  ID**, so anything that recorded the old one (a runbook, an audit note) needs updating.

## Revoking a grant

```
aws cloudwatchomni delete-access-grant --grant-id <grant-id>
```

Revoking a grant removes the access it conveyed for **future** requests. It does not
delete anything in the Space, and it does not affect the principal's other grants. It
is **not** instantaneous, and it does not invalidate credentials. The one model to
state, every time: Each Omni call is re-authorized against the Space's grants, so a revoke takes effect at the next authorization-cache turnover (minutes) — even though the session credentials already issued to the principal remain valid until they expire (up to an hour) or the session is re-established.
So a revoke is not a way to cut off access already in flight this second, and a direct
IAM caller in the owning account keeps whatever its own IAM policy allows regardless of
grants.

Revocation is the *only* way a grant ends — grants carry no expiry, so "remove their
access" always means a `delete-access-grant`.

**Revoking everything a person holds** is a destructive action aimed at someone named
only by alias, so the order matters:

1. **Resolve the exact principal first.** `search-principals --domain-id <domain-id>
   --search-query <name>`. Use the returned UUID as `principalId` with `principalType`
   `IDC_USER` (or `IDC_GROUP` if it resolves to a group).
2. **Stop if the name does not resolve to exactly one principal.** Zero results, or more
   than one plausible match, means you report that and stop. You MUST NOT fall back to
   a principal that happens to appear in the Space's grant list, and you MUST NOT guess
   a UUID — revoking the wrong person's access is the failure this step prevents.
3. **List what they hold**: `list-access-grants --space-id <space-id> --principal-id
   <uuid> --principal-type IDC_USER`, following `nextToken`. An empty list is a valid
   finding: nothing to revoke.
4. **Present the list and confirm before deleting.** Show every grant by its `grantId`,
   its permission in plain words alongside the API value, and the resolved name **and**
   UUID it belongs to. Get the customer's confirmation on that list before running any
   delete — the confirmation is the only thing standing between a typo and a wrong-target
   revoke.
5. **Revoke one grant at a time**: `delete-access-grant --grant-id <grant-id>` for each
   confirmed grant. If one of them is the Space's last `ADMIN`/`SPACE_ADMIN` grant, the
   service refuses it (`ConflictException`) until another principal holds `SPACE_ADMIN`.
6. **Verify and report**: run the step-3 list again and confirm it is empty — or, if a
   last `ADMIN`/`SPACE_ADMIN` grant was intentionally retained because the delete was
   refused, confirm that only that grant remains and say why. Note the revocation
   timeline above, and that access through an `IDC_GROUP` grant is unaffected because
   those grants belong to the group, not the person.

**"I revoked the grant and they still have access."** Two things are true at once, and
the answer names both:

1. **Revocation takes effect at the next authorization-cache turnover, not at the
   instant of the delete** (the timeline above). Five minutes of continued access is
   inside that window. This is expected behaviour, not a bug — do not delete
   the grant again and do not call the revoke broken.
2. **The person may hold another grant.** The revoke removed one grant and nothing
   else. Check what they still hold, directly and through their groups:

   ```
   aws cloudwatchomni list-access-grants --space-id <space-id> --principal-id <principal-id> --principal-type <principal-type>
   aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type IDC_GROUP
   ```

   An `IDC_GROUP` grant reaches every member and shows only the group ID, so a person
   with no direct grant can still reach the Space through a group.

**Constraints:**

- You MUST confirm which grant is being revoked before revoking it, by grant ID and by
  what it conveys. A principal often holds several, and "remove their access" rarely
  means all of them — list them first ([What a given principal holds](#what-a-given-principal-holds)).
- You MUST NOT revoke the caller's own `SPACE_ADMIN` grant without warning them that
  they may lose the ability to manage grants in that Space.
- The service refuses to revoke the **last** `ADMIN`/`SPACE_ADMIN` grant on a Space
  (`ConflictException`: at least one permanent `ADMIN` or `SPACE_ADMIN` grant must
  remain) and refuses to delete a service-managed grant (`grantType`
  `SERVICE_MANAGED`). Grant another principal `SPACE_ADMIN` first if the customer's
  goal is to hand the Space over.

## Looking up access

`list-access-grants` is the entry point for every "who has access", "what grants does X
hold", and "at what permission level" question. `get-access-grant` answers the "detail of
one grant" questions — how it is scoped, and who created it when. Start from the list,
and reach for the detail only once you have a grant ID and the customer wants its scope
or timestamps. The summaries alone answer "who has access / what does X have"; do not
fetch the detail of every listed grant by default. A deliberate full-scope audit ("how
is each of these scoped?") is the one case that warrants details for the whole list.

Both are read-only. Neither pivots to IAM — the grants are the authorization records.

### Who has access to the Space

```
aws cloudwatchomni list-access-grants --space-id <space-id>
```

Returns grant **summaries** (`items`) — for each grant the `grantId`, `grantArn`, `name`,
`principal` (`principalType` and `principalId`), `permission`, `grantType`, `spaceId`,
and `domainId`. A
summary carries **no scope** and **no timestamps**; those are on the detail only.

The result is **paginated**. If the response carries a `nextToken`, call again with
`--next-token <token>` and keep going until it is absent. Do not report a partial page
as the full set — say how many grants you have read if you stop early.

An **empty list is a success**: the Space has no grant matching the filters. That is a
finding, and it is different from a failed call (see [Reporting a lookup](#reporting-a-lookup)).

**An access audit** has three questions, and a complete answer covers all six points:

- *Who can grant access to others?* `list-access-grants --space-id <space-id>
  --permission SPACE_ADMIN`. `SPACE_ADMIN` is delegation of grant management, so this is
  the first question of any audit.
- *Who can write or delete?* `--permission READ_WRITE_DELETE`, plus the `SPACE_ADMIN`
  holders, because that level includes write and delete.
- *Does anyone reach the Space without a grant?* For people, console sessions, and
  Access Profiles, no — access is deny-by-default and the grants are the complete
  answer. A direct IAM caller in the owning account with no matching grant falls through
  to its own IAM policy, so a full audit also reviews IAM policies for direct IAM callers.
- Both filtered lists are paginated: follow `nextToken` to the end, and say what each
  filter narrowed over (all grants on the Space) and how many grants came back.
- **Grants never expire**, so unused ones accumulate until someone revokes them.
- Attribution comes from the detail, not the summary: `get-access-grant` returns
  `createdBy` and `createdAt` — name those two fields when saying who added a grant and
  when.

#### Resolving Identity Center UUIDs to names

`IDC_USER` and `IDC_GROUP` grants carry only the principal's Identity Center **UUID**
(occasionally a `userName` such as an email) — never a display name. There is **no
by-ID lookup**: `search-principals` has no principal-ID parameter, and `identitystore`
is not the answer. Resolve names the way the console's **Manage permissions** page does:
pull the Domain's whole roster once and join it to the grants yourself.

1. List the grants (following `nextToken`). Each summary carries `principal.principalId`
   and the Space's `domainId`:

   ```
   aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type IDC_USER
   aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type IDC_GROUP
   ```

2. Pull the roster with the match-all query `*`, paging until `nextToken` is absent
   (the console caps this at 20 pages of 50 — 1,000 principals):

   ```
   aws cloudwatchomni search-principals --domain-id <domain-id> --search-query '*' --max-results 50
   aws cloudwatchomni search-principals --domain-id <domain-id> --search-query '*' --max-results 50 --next-token <token>
   ```

   Each result carries `principalId` (the UUID), `principalType` (`USER` or `GROUP`),
   `displayName`, and — for users — `userName`. `--max-results` and `--next-token` are
   accepted **only** with `*`; a name search returns at most 10 results and does not
   paginate.
3. Join client-side: a grant's `principalId` matches a roster entry's `principalId`
   **or** its `userName` (grants are sometimes keyed by the userName). Map `USER` →
   `IDC_USER` and `GROUP` → `IDC_GROUP`.
4. Report each principal as `displayName` (plus `userName` for a user) **alongside** the
   UUID, with its permission in plain words and the API value. For a group, say the
   grant reaches every member and the grant shows only the group's ID.
5. Anything the roster does not resolve is reported as its raw UUID with a plain
   statement that it could not be resolved — the principal may have been removed from
   the directory, the roster may have been cut off at the page cap, or the Domain may
   not use Identity Center (in which case `search-principals` itself returns a 400
   saying the Domain must be provisioned with Identity Center). Never guess a name.

Narrow the list **server-side** with the filters the operation supports, whenever the
ask names an exact value:

| The ask | Filter |
|---|---|
| "Which roles have access?" | `--principal-type IAM_ROLE` |
| "Who has admin here?" / "Who can grant access?" | `--permission SPACE_ADMIN` |
| "Who can write or delete?" | `--permission READ_WRITE_DELETE` |
| "Which Identity Center groups are granted?" | `--principal-type IDC_GROUP` |
| "Does alert `<name>` have access?" | `--principal-type ALERT --principal-id <alert-arn>` — an alert is identified by its ARN, never its name; resolve the name to its `alertArn` with `aws cloudwatchomni list-alerts --space-id <space-id> --filter-criteria '{"names": ["<name>"]}'` first. Check for a grant made to every alert as well — it has `principalId` `ALL` and covers this alert too. The summary tells you the permission but not the scope; `get-access-grant` on the returned grant shows the `scopedActions`, which for an alert's trust grant name the Access Profile it may assume. An empty result is a finding — no grant matched — not an error |
| "What does profile `<id>` hold?" | `--principal-type ACCESS_PROFILE --principal-id <profile-id>` |

### What a given principal holds

```
aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type <principal-type> --principal-id <principal-id>
```

Pass both `--principal-type` and `--principal-id`; the same identifier can be valid for
more than one type. A principal may legitimately hold **several** grants on one Space —
one per named level, plus up to ten `CUSTOM` grants — so report all of them, with the
permission of each, not just the first.

If the customer wants to know what those grants *allow* (their scope), follow up with
`get-access-grant` on the grant(s) they ask about.

### Finding a person by name or alias

A grant identifies a person by `principalId`, and what that is depends on the
principal type — so how you find "jdoe" depends on how jdoe signs in.

**An IAM user or role.** The ARN embeds the name, so list the Space's IAM grants and
match on the ARN client-side:

```
aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type IAM_ROLE \
  --query "items[?contains(principal.principalId, 'jdoe')]"
```

Repeat with `--principal-type IAM_USER` if the person may be an IAM user. JMESPath
`contains` is case-sensitive, so match the alias as it appears in the ARN. Follow
`nextToken` across pages before concluding there is no match.

**An Identity Center user or group.** The grant holds only the Identity Center **UUID**
— the summary carries no display name, so no substring of an alias will ever match a
grant directly. Resolve the name to an ID first, in the Space's Domain (for the reverse
direction — many UUIDs to names — use the roster join in
[Resolving Identity Center UUIDs to names](#resolving-identity-center-uuids-to-names)):

```
aws cloudwatchomni search-principals --domain-id <domain-id> --search-query <name-or-email>
```

Then filter the grants by that ID:

```
aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type IDC_USER --principal-id <idc-user-id>
```

Also check the person's **groups**: a grant to an `IDC_GROUP` reaches every member, and
the grant shows the group ID, not its members. If the direct lookup is empty, say that
the person holds no grant of their own and may still reach the Space through a group
grant — list the Space's `IDC_GROUP` grants and, if the customer knows the person's
groups, match on those IDs.

When the name cannot be resolved — the Domain does not use Identity Center,
`search-principals` returns nothing, or the caller cannot run it:

- **Say so plainly.** Identity Center principals appear as UUIDs, and this lookup could
  not resolve the alias to one.
- **Offer to list the Space's Identity Center grants** (`--principal-type IDC_USER` or
  `IDC_GROUP`) so the customer can identify the principal from the UUIDs and names.
- **Never pretend an alias was resolved**, and never invent or guess a UUID.

### How a specific grant is scoped

```
aws cloudwatchomni get-access-grant --grant-id <grant-id>
```

Use this after the list when the customer wants a **single** grant's **scope** — the
actions and resources it allows — or **who created it and when**. Neither is on the
summary. Read the detail and report from it:

- A grant's scope is `scopedActions` — each entry a set of `actions` over `resources`,
  with optional `contextConditions` — and it comes back exactly as the service holds
  it. That is the only scope field on a grant.
- A grant with **no** scope fields grants its permission level **unscoped** across the
  whole Space — say that, rather than reading the absence as an error or as "no
  access".
- For a workload principal (`ALERT`, `AGENT`), the detail is how you learn **which
  Access Profile it may assume**: a trust grant is a `CUSTOM` grant whose single action
  is `AssumeAccessProfile`, and the profile's ARN sits in that entry's `resources`. The
  summary shows only that a `CUSTOM` grant exists.
- The detail carries `createdBy`, `createdAt`, and `updatedAt` — use these to answer
  "who granted this / when". There is still no expiry.
- A grant ID that matches **no** grant comes back from `get-access-grant` as
  `ResourceNotFoundException`. That is a successful lookup whose finding is "nothing
  found" — the ID is wrong, or the grant was revoked — not a failure of the lookup. Say
  so and offer to list the Space's grants; do not retry with a guessed ID.
  (`delete-access-grant` is idempotent: deleting a grant that no longer exists succeeds.)

### Reporting a lookup

- **Answer in the customer's terms**, from the operation's own output — "jdoe has
  `READ_WRITE_DELETE` on this Space, granted as an IAM role: they can read, write, and
  delete within it" — not a dump of the raw JSON. Give every permission value its
  plain-language meaning, not just the unusual one:

  | API value | Say |
  |---|---|
  | `READ` | can read the Space's telemetry |
  | `READ_WRITE_DELETE` | can read, write, and delete within the Space |
  | `SPACE_ADMIN` | can manage grants — give or revoke others' access — and also read, write, and delete |
  | `CUSTOM` | can perform exactly the listed actions and nothing else (read the detail for the list) |

- **Only report what you read.** A summary gives you the principal and permission; you
  do not know a grant's scope until `get-access-grant` has returned it. Do not describe
  a scope you have not fetched, and do not describe an expiry that does not exist.
- **Say what you narrowed over.** If you filtered server-side, or matched client-side,
  or stopped before the last page, tell the customer how many grants you looked at — a
  filtered answer presented as complete is worse than an honest partial one. For an
  audit, name the population each filter ran over (all grants on the Space) and how
  many came back at each level.
- **Attribute grants from the detail.** When the question is who added a grant, or when
  an audit turns up grants nobody recognizes, `get-access-grant` carries `createdBy` and
  `createdAt`; summaries do not. Grants never expire, so stale ones stay until revoked.
- **A lookup that fails, fails.** `AccessDeniedException`, expired credentials, a
  missing `--space-id`, or a service error is a broken call, never a conclusion about
  the Space. Never report "nobody has access" or "X has no access" from a failed call;
  say the lookup failed, quote the error, and — when it points at expired credentials
  or a missing permission — relay that rather than retrying the same call.
- **`AccessDeniedException` on a grant lookup means the caller holds no grant on this
  Space.** `list-access-grants` and `get-access-grant` are read actions: every named
  permission (`READ`, `READ_WRITE_DELETE`, `SPACE_ADMIN`) includes them, and a `CUSTOM`
  grant includes them only if it names `ListAccessGrants`/`GetAccessGrant`. So the
  denial says the caller has no grant here at all (or a `CUSTOM` one that omits those
  actions). The answer is "someone who holds `SPACE_ADMIN` here either runs the lookup
  or grants you access — `READ` is enough to look up grants" — not an IAM policy edit,
  not `sts get-caller-identity`, and not "retry once you have permission". Contrast it
  explicitly with an empty list, which is a successful answer meaning no grant
  matched.

## Troubleshooting

> **Not every authorization error is a missing grant.** If `create-space` succeeded
> and the Space then fails in use, suspect the **space access role's trust policy**,
> not a grant — and answer from
> [spaces-and-domains.md](spaces-and-domains.md) ("If the Space was created but cannot
> be used"), whose checklist is the complete answer. In short: `create-space`
> validates only that `dataAccessRoleArn` is non-blank and in the caller's account —
> it never attempts to assume the role, so a wrong trust policy is accepted at create
> time and fails in use, and a successful create is not proof the role is right. Check,
> on that role: the service principal is `cloudwatch.amazonaws.com`; all three of
> `sts:AssumeRole`, `sts:TagSession`, and `sts:SetContext` are allowed (assume-role
> alone is accepted at create and fails in use); and both confused-deputy conditions
> are present — `aws:SourceAccount` equal to the account, and `aws:SourceArn` matched
> against the `cloudwatch` `space/` resource with Region and space ID **wildcarded**,
> since the space ID did not exist when the role was created. Then read the Space back
> with `get-space` to verify. Do not recreate the Space as the first remedy — the same
> role fails the same way — and do not create a grant to fix a trust-policy problem. A
> missing grant instead means nobody could reach the Space from the start, for
> everyone.

**Rule:** When a call returns an error, surface the error code and message
**verbatim**, then map to the mitigation below. Do NOT invent error text, do NOT
paraphrase what the service returned, and do NOT synthesize a mitigation for an error
that is not listed.

| Error signal | Cause | Mitigation to surface |
|---|---|---|
| `ValidationException` naming the supported permission values | A permission outside `READ`, `READ_WRITE_DELETE`, `SPACE_ADMIN`, `CUSTOM` was requested | Pick one of the four. There is no caller-usable write-only or delete-only level |
| `ValidationException` that `scopedActions` is required for `CUSTOM` grants | `CUSTOM` was sent with no actions | Ask the customer which actions they need and resend with `scopedActions`, or use a named permission |
| `ValidationException` about the action format | An action is not `prefix:Action`, or uses a wildcard | Name each action explicitly in `prefix:Action` form. Wildcards are not accepted |
| `ValidationException` that the action prefix must match the service vendor code | The prefix is not the one this service expects | Use the prefix named in the message |
| `ValidationException` that all actions in an entry must share the same prefix | One entry mixes prefixes | Split into one `scopedActions` entry per prefix |
| `ValidationException` naming an unknown action | The action does not exist | Ask the customer what the principal needs to do and map it to a real action, or use a named permission |
| `ValidationException` that an action is not allowed for the grant type | A named permission was narrowed with an action outside its tier | Either widen the permission or drop the action. A mutating action cannot be scoped under `READ` |
| `ValidationException` that an action is not allowed for the `DataSet` resource type | A `DataSet` scope named something other than `GetRecords`, `GetMetricData`, or `ListMetrics` | Restrict the entry to those three actions, or drop the `DataSet` scope |
| `ValidationException` that `signalTypes` and `rowScopeGroups` may only be specified on `DataSet` resource scopes | Row scoping was attached to another resource type | Move the row scope to a `DataSet` scope, or remove it |
| `ValidationException` that `signalTypes` may only be specified together with `rowScopeGroups` (or the reverse) on a `DataSet` resource scope | One was sent without the other | Send both, or neither |
| `ValidationException` that the `METRICS` signal type is not supported | Row scoping was requested for metrics | Row scoping covers logs and traces only |
| `ValidationException` that a principal type cannot be granted an action | That action is not available to that kind of principal | Choose a different principal type, or drop the action |
| `ValidationException` that access profiles cannot be granted `ADMIN` or `SPACE_ADMIN` permissions | `SPACE_ADMIN` (or an administrative action) was requested for an `ACCESS_PROFILE` principal | Use `READ`, `READ_WRITE_DELETE`, or `CUSTOM`. A profile bounds a workload; it does not administer the Space |
| `ValidationException` that the wildcard principal identifier is not supported for this principal type | `principalId` `ALL` was used with a type other than `ALERT`, or on a grant that is not `CUSTOM` with the single action `AssumeAccessProfile` | Name the principal explicitly, or restructure as a `CUSTOM` `AssumeAccessProfile` trust grant for `ALERT` |
| `ValidationException` that cross-account grants are not supported | The IAM principal is in another account | Grants only reach principals in the caller's account. Ask the customer for a principal in this account |
| `ValidationException` that the principal was not found in Identity Center | The user or group ID is wrong, or is not in this Domain's identity store | Look the principal up with `search-principals` and use the returned ID |
| `AccessDeniedException` that a caller with one grant cannot manage another kind (`Caller with <X> grant cannot manage <Y> grants`) | The caller is trying to grant more than they hold — a `SPACE_ADMIN` may grant `READ`, `READ_WRITE_DELETE`, `CUSTOM`, and another `SPACE_ADMIN`, but never `ADMIN` | The caller needs a broader grant themselves. Report both levels and stop |
| `AccessDeniedException` that the caller has no grants in this Domain and cannot manage grants | The caller holds nothing and cannot manage grants — an IAM policy allowing `cloudwatch:CreateAccessGrant` is not enough | The caller needs `SPACE_ADMIN` on the Space or an administrative grant on the Domain first |
| `ValidationException` that `Space` and `Domain` are not valid resource scope `resourceType` values | A parent-typed scope was sent; a grant is already scoped to a single Space or Domain | Omit `resources` to cover the whole Space, or name a resource type inside the Space. Then restate the scope model so the next attempt is right: `resources` is a plain list of scopes, each a required `resourceType` plus up to five optional `resourceArns`, and `resourceType` is validated per (action, resourceType) pair |
| `ValidationException` `Unknown resourceType. Allowed values: …` | The `resourceType` is misspelled or miscased (`Dataset` for `DataSet`); the value is matched case-sensitively against the fixed list in Step 4 | Use the exact spelling from the message's list (it does not echo your input). Contrast it with the per-(action, resourceType) mismatch message below, which lists nothing — the two errors are different checks |
| `ValidationException` that a resource type is not valid for an action (for example `Resource type Dashboard is not valid for action ListSpaceAccess`) | The `resourceType` is a known type, but not one that action operates on — validation is per (action, resourceType) pair. This message does not list the alternatives | Pair the action with the resource type it acts on, or drop the scope |
| `ConflictException` that an active grant already exists for the principal | A grant at that named permission is already in place | Read it with `list-access-grants`. To change the level, revoke the existing grant first |
| `ConflictException` that the maximum `CUSTOM` grants was reached | 10 `CUSTOM` grants already exist for that principal in that Space | Consolidate the actions into fewer grants, or revoke one that is no longer needed |
| `ValidationException` that the principal or Space grant maximum was met | 50 per principal, or 500 per Space | Revoke grants that are no longer needed, or grant to a group rather than to individuals |
| `ValidationException` `Grant has N scoped-action groups, which exceeds the maximum of 10` / `… actions … exceeds the maximum of 25` | More than 10 `scopedActions` entries, or more than 25 actions in one entry (50 per grant in total) | Consolidate or split across grants; report the effective limits, not the API schema's |
| `ValidationException` `… exceeds the maximum of 50` / `… exceeds the maximum of 5` on a row scope | More than 50 `values` in a condition, more than 5 conditions in a group, or more than 5 groups | Tighten the allowlist or split it across grants |
| `ValidationException` `Invalid observe resource type in ARN` | A `resourceArns` entry names a dataset (or another type the service does not accept as a scope ARN) | Drop `resourceArns` on the `DataSet` scope and narrow with `signalTypes` + `rowScopeGroups` instead |
| `ResourceNotFoundException` from `get-access-grant` | No grant with that ID exists — the ID is wrong, or the grant was already revoked | A successful lookup with nothing found, not a failure. List the Space's grants to find the right ID; do not retry with a guessed one. `delete-access-grant` does not raise this — it is idempotent, and deleting a grant that no longer exists succeeds |
| `AccessDeniedException` from `list-access-grants` or `get-access-grant` | The caller holds no grant on this Space — listing and reading grants are read actions included in `READ`, `READ_WRITE_DELETE`, and `SPACE_ADMIN` alike, so any named-permission holder can look up grants; only a caller with no grant (or a `CUSTOM` grant that omits `ListAccessGrants`/`GetAccessGrant`) is denied | The lookup is **inconclusive**, not "no grants". Someone holding `SPACE_ADMIN` on the Space (or an administrative grant on the Domain) runs the lookup, or grants the caller a level — `READ` suffices. Do not retry, and do not turn to IAM |
| `ConflictException` that the last `ADMIN` grant on the Space cannot be revoked | The grant being deleted is the Space's only `ADMIN`/`SPACE_ADMIN` grant | Grant another principal `SPACE_ADMIN` first, then revoke |
| `ConflictException` that a service-managed grant cannot be deleted | The grant is the creator's bootstrap `SPACE_ADMIN` grant (`grantType` `SERVICE_MANAGED`) | Leave it; revoke customer-managed grants instead |

If the error does not match a row above, quote it verbatim, say it is unmapped, and ask
the customer how to proceed.

Two error classes have more to them than one row can hold. When one of them is the
question, the complete answer covers every point below:

**A rejected `scopedActions` scope** (`ValidationException` on `resourceType`):

- `Space` and `Domain` are both invalid as a scope's `resourceType` — name both. The
  grant is already bound to one Space or Domain; to cover the whole Space, omit
  `resources`.
- `resourceType` is a plain string matched case-sensitively: `DataSet`, not `Dataset`.
  An unknown spelling is rejected with `Unknown resourceType. Allowed values: …`, which
  lists the accepted spellings.
- Validation is per (action, resourceType) pair: a known type next to an action that
  does not operate on it is rejected with `Resource type X is not valid for action Y`,
  which lists nothing.
- `resources` is a plain list of scopes — not an object with a `scopes` member — and
  each scope has a required `resourceType` and up to five optional `resourceArns`.
- Every action in an entry must be within the named permission's tier.

**`ResourceNotFoundException` from `get-access-grant`:**

- It is a successful lookup whose finding is "no such grant": the ID is wrong or the
  grant was already revoked. It is not an authorization problem and not a failed call.
- Find the right ID with `list-access-grants`, optionally filtered by principal; never
  retry with a guessed ID.
- `delete-access-grant` is **idempotent** — deleting a grant that no longer exists
  succeeds rather than raising this error, so a revoke never needs a pre-check for
  existence.

## Gotchas — expectations that look like faults

- **A principal with a grant still cannot see anything.** Check the Space, not the
  grant. A grant names one Space, and a principal working in a different Region is
  working against a different Space. Nothing is wrong with the existing grant. Confirm
  which Space the person is in, check that Space's grants for them first
  (`list-access-grants --space-id <other-space-id> --principal-id … --principal-type …`),
  then create a separate `READ` grant on that Space. Do not broaden the original
  grant to avoid a second one, and do not reach for an IAM policy change — grants do
  not span Regions or Spaces at any permission level.
- **A second grant at the same level is rejected.** Named-permission grants are one per
  principal per Space per level. Revoke and re-create to change a level.
- **There is no write-only permission.** `READ_WRITE_DELETE` is the only mutating named
  level. A customer expecting to grant writes without deletes needs `CUSTOM`.
- **There is no update operation.** Renaming, re-leveling, or re-scoping a grant is a
  revoke plus a create, and the grant ID changes.
- **A narrowed grant appears to be missing data.** Row scoping is an allowlist with `IN`
  only. Anything not named in `values` is excluded, and excluded data is
  indistinguishable from absent data.
- **A revoked grant seems to still work.** Each Omni call is re-authorized against the Space's grants, so a revoke takes effect at the next authorization-cache turnover (minutes) — even though the session credentials already issued to the principal remain valid until they expire (up to an hour) or the session is re-established. If access persists beyond
  that, the principal holds another grant (directly or through an `IDC_GROUP`), or is a
  direct IAM caller whose own IAM policy allows the call.
- **A grant "should have expired" by now.** Grants never expire. If access was meant to
  be temporary, someone has to revoke it; nothing does so automatically.
- **The list shows no scope for a `CUSTOM` grant.** Summaries never carry scope. Read
  the grant with `get-access-grant`.
- **A person's alias matches nothing.** Identity Center principals are UUIDs in the
  grant; resolve the name with `search-principals` first, and remember access may
  arrive through an `IDC_GROUP` grant that shows only the group ID.
- **An empty list looks like an error.** It is not. `list-access-grants` returning no
  grants is a successful answer: nothing matched. Only an actual error (access denied,
  not found, throttled) is a failed lookup — and a failed lookup says nothing about who
  has access.
- **The caller has valid credentials and is still denied.** Credentials say who the
  caller is; grants say what they may do in the Space. Check for a grant before
  suspecting IAM — see `aws-observability` → `references/cloudwatch-omni/programmatic-access.md`.

## Security considerations

- Grant to Identity Center groups rather than individual users where possible.
  Offboarding a person then requires no change to grants.
- Prefer the narrowest named permission over `CUSTOM` with a long action list. A named
  level is auditable at a glance; a list of 50 actions is not.
- `SPACE_ADMIN` conveys the ability to grant access to others. Treat it as delegation of
  administration, not as a higher read level. Reviewing who holds it
  (`--permission SPACE_ADMIN`) is the first question of any access audit — and because
  it includes write and delete, "who can write or delete" is the `READ_WRITE_DELETE`
  holders **plus** the `SPACE_ADMIN` holders.
- `IAM_ROOT` has no session identity to attribute actions to. Avoid it unless the
  customer explicitly asks.
- **Grants do not bound the CloudWatch Logs plane.** Row scoping is an access control,
  not a redaction, and it binds one plane only. It restricts which records a principal
  can retrieve **through the Space's DataSet**; it does not remove sensitive fields from
  records they can retrieve, and it does not touch the CloudWatch log groups the Dataset
  was populated from — those stay readable via `logs:GetLogEvents`,
  `logs:FilterLogEvents` and `logs:StartQuery` under IAM no grant constrains.
  Account-wide `log-group:*` forwarding is the onboarding default and every record
  carries `@logGroupName`, so a row-scoped grant is **not sufficient on its own**:
  restrict the principal's `logs:*` on the source log groups too. And because a row
  scope is an `IN` allowlist, **excluded data is indistinguishable from absent data** to
  the principal — they cannot tell a service with no records from one the scope hides —
  so it is not a way to signal that something is being withheld either.
- Review grants periodically with `list-access-grants`. Grants never expire and the
  per-Space limit of 500 is high enough that unused grants accumulate unnoticed. Use
  `createdBy` / `createdAt` on the detail to find who added a grant nobody remembers.
- Grants are per Space by design. Resist the temptation to give a principal a broader
  permission in one Space to avoid creating grants in others.

## Additional resources

- [spaces-and-domains.md](spaces-and-domains.md) — creating the Domain and Space a
  grant applies to
- [org-domains.md](org-domains.md) — Domain access grants, for administration across an
  organization, and the cross-account credential path
- [access-profiles.md](access-profiles.md) — bounding what an agent, alert, or
  integration can do, and the permission and trust grants that make a profile work
- `aws-observability` → `references/cloudwatch-omni/concepts.md` — how Domains, Spaces, grants, and profiles fit
  together, and the setup order
- `aws-observability` → `references/cloudwatch-omni/programmatic-access.md` — calling Omni from the CLI,
  SDKs, or code, and why an IAM caller still needs a grant
