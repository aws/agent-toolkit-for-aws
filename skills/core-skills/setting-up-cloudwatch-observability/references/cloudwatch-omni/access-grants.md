# CloudWatch Omni access grants

An **access grant** binds one **principal** — a person, group, IAM identity, Access
Profile, or alert — to one **permission level** on one **Space**. Grants are the Space's
own authorization records, and the only way anyone reaches telemetry **through the
Space** for people and profiles: a Space with no grants is readable by no Identity
Center user, console session, or Access Profile — including the person who created it.
(A direct IAM caller in the owning account is the one exception: with no matching grant
it falls through to its own IAM policy — see
[Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles).) So "how do I give X access", "who has access here", "what can
X do", and "how is grant `<id>` scoped" are all answered from — and acted on through —
the Space's grants.

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
>   Space (grant access to others). It is not a higher read level, nor a higher
>   data-access tier.
> - Access is **deny-by-default** for people and profiles: an Identity Center user,
>   console session, or Access Profile with no matching grant can do nothing in the
>   Space. The one exception is a direct IAM caller in the owning account, which falls
>   through to its own IAM policy when no grant matches (see
>   [Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles)). Access is
>   opened deliberately, one grant at a time.
> - Grants **do not expire**. There is no expiry field on a grant; it stays in effect
>   until it is revoked.
> - Cross-account IAM grants are **not supported at the Space grant level**; the
>   principal must be in the caller's account. (The organization Domain path is
>   separate — it vends credentials for a target account. See
>   [org-domains.md](org-domains.md).)
> - `scopedActions` works with **any** permission: with `CUSTOM` it defines the grant,
>   with a named permission it narrows that permission to the listed resources.
> - Within a single `scopedActions` entry, **all actions must share the same prefix**;
>   use a separate entry per prefix.
> - Whenever you show a scoped grant, say that `resources` **inside** a `scopedActions`
>   entry is a plain list of scopes, not an object with a `scopes` member. There is no
>   top-level `resources` or `customActions` on a grant — `scopedActions` is the only
>   scope field.
> - Access questions are answered from the **grants** — never by pivoting to IAM
>   identity or IAM policy APIs, and never by sending the customer to the console when
>   the CLI answers directly.

## Contents

- [What an access grant is](#what-an-access-grant-is)
  - [Grants, IAM, and Access Profiles](#grants-iam-and-access-profiles)
  - [What a grant reaches](#what-a-grant-reaches)
- [Permission levels](#permission-levels)
- [Operations you will call](#operations-you-will-call)
- [Prerequisites](#prerequisites)
- [Granting access](#granting-access)
  - [Step 1 — Interview the customer first](#step-1--interview-the-customer-first)
  - [Step 2 — Identify the principal](#step-2--identify-the-principal)
  - [Step 3 — Create the grant](#step-3--create-the-grant)
  - [Step 4 — Narrow the grant with scoped actions](#step-4--narrow-the-grant-with-scoped-actions)
  - [Verifying the grant](#verifying-the-grant)
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
  | `ALERT` | An alert's ARN (`arn:<partition>:cloudwatch:<region>:<account-id>:alert/<alertId>`), or the reserved token `ALL` meaning any alert — **never the alert's name**. A profile that alerts created later must assume needs `ALL`: `CreateAlert` authorizes against the wildcard `alert/*` ARN, which only `ALL` matches |
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

- A grant may carry up to **20 scoped-action entries**, each naming up to **50

  actions**.

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
| Manage grants in the Space, i.e. delegate access to others | `SPACE_ADMIN` | None |
| Exactly the actions they name, and nothing else | `CUSTOM` | `scopedActions` is required |

Those four are the only values a caller may request. The service rejects anything else
with a message naming the supported set. `ADMIN` exists only through Domain-level
administration and cannot be granted on a Space.

**`SPACE_ADMIN` is a delegation level, not a higher read level.** It conveys the
ability to manage grants in the Space — to give other principals access. The other
three levels confer no delegation ability. Someone who simply needs broad access to the
data wants `READ_WRITE_DELETE` instead.

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

Every operation is an `aws cloudwatch-omni <operation>` CLI command, with the
operation's input-shape members passed as `--flags`. Run it through the `aws___call_aws`
tool when that tool is available; otherwise run the same command in a shell. See
`aws-observability` → `references/cloudwatch-omni/programmatic-access.md` for the service name, signing
name, and what to do when the local CLI does not know `cloudwatch-omni`.

**`aws cloudwatch-omni` (Omni control-plane):**

| Intent | CLI command |
|---|---|
| Find an Identity Center principal in the Domain by name or email | `aws cloudwatch-omni search-principals` |
| List grants on a Space — who has access, what a principal holds | `aws cloudwatch-omni list-access-grants` |
| Read one grant back — its scope and who created it | `aws cloudwatch-omni get-access-grant` |
| Create a grant | `aws cloudwatch-omni create-access-grant` |
| Revoke a grant | `aws cloudwatch-omni delete-access-grant` |

There is **no update operation** for a grant. Changing a grant's level, scope, or name
means revoking it and creating a new one — see [Changing a grant](#changing-a-grant).

**`aws sts`:**

| Intent | CLI command |
|---|---|
| Confirm the calling identity | `aws sts get-caller-identity` |

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
  them it is impossible.

**Constraints:**

- You MUST NOT create grants for principals in another account. Cross-account IAM

  grants are not supported, and the rejection says so explicitly.

## Granting access

First, confirm the grant belongs at the Space level at all:

| The customer wants | Path |
|---|---|
| A principal to have access to one Space | **This file** |
| A principal to administer an entire Domain across an organization | **Domain access grant** — see [org-domains.md](org-domains.md) |
| A workload (alert, agent, integration) bounded by a set of actions it may assume | **Access Profile** — see [access-profiles.md](access-profiles.md) |

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

#### Find an Identity Center principal

If the customer knows the person or group by name rather than by ID, look it up rather
than asking them to find it:

```
aws cloudwatch-omni search-principals --domain-id <domain-id> --search-query <name-or-email>
```

Use the returned ID as `principalId`. This only works when the Domain uses Identity
Center.

#### Check what the principal already has

Pass both `principalId` and `principalType` — the same identifier can be valid for more
than one type, and filtering on both keeps the result unambiguous.

```
aws cloudwatch-omni list-access-grants --space-id <space-id> --principal-id <principal-id> --principal-type <principal-type>
```

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
aws cloudwatch-omni create-access-grant --domain-id <domain-id> --space-id <space-id> --name <grant-name> \
  --principal '{"principalType": "<principal-type>", "principalId": "<principal-id>"}' --permission READ
```

Substitute `READ_WRITE_DELETE` or `SPACE_ADMIN` as the interview decided. `--name` is
required; the call is rejected without it.

#### A `CUSTOM` permission

`CUSTOM` requires `scopedActions`, which names the actions the principal may perform.
Nothing outside that list is permitted.

```
aws cloudwatch-omni create-access-grant --domain-id <domain-id> --space-id <space-id> --name <grant-name> \
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

Each entry requires `actions` and may add `resources`, a list of scopes. Every scope
requires a `resourceType`, and may add:

- **`resourceArns`** — up to 5 ARNs. Omit to cover every resource of that type.
- **`signalTypes`** and **`rowScopeGroups`** — row-level filtering, and only on the

  `DataSet` resource type. See below.

`resourceType` is a plain string, not an enum, and the service validates it **per
(action, resourceType) pair**: a type is accepted only alongside actions that operate
on that kind of resource. The types the service knows are `AccessGrant`, `DataStore`,
`DataSet`, `DataStream`, `Source`, `Route`, `Processor`, `Integration`,
`OmniIntelligenceRule`, `AccessProfile`, `OmniThread`, `OmniAgentAsset`,
`AccountConfiguration`, `OmniDashboard`, `DataSource`, `Alert`, `EvaluationJob`,
`Evaluator`, `OnlineEvaluation`, `View`, `IngestionEndpoint`.

- `Space` and `Domain` are **not** valid here. A grant is already scoped to a single

  Space or Domain, so a parent-typed scope is rejected with a 400. To cover the whole
  Space, omit `resources` instead.

- Casing matters: `DataSet` is accepted, `Dataset` is rejected.
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
resources. It is available only on a scope whose `resourceType` is `DataSet`, and
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
operator `IN`, and up to 100 `values`. Up to 20 groups, each with up to 20 conditions.

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

### Verifying the grant

Read it back rather than trusting the create response:

```
aws cloudwatch-omni get-access-grant --grant-id <grant-id>
```

Confirm the principal, the permission, the Space, and — if the grant was narrowed — the
scoped actions and resources are what the customer asked for. Then report in one line:
who now has what, on which Space.

**Constraints:**

- You MUST report the permission in the customer's own terms as well as the API value.

  "Can read telemetry in this Space" is checkable by the customer;
  `READ_WRITE_DELETE` is not.

- A grant taking effect is not instantaneous for a principal whose credentials are

  already vended. You SHOULD tell the customer that an existing session may need to be
  re-established before the change is visible.

## Changing a grant

There is no update operation. To change a grant's permission level, its scope, or its
name, revoke the existing grant and create a new one:

1. Read the existing grant with `get-access-grant` and confirm with the customer which

   grant is changing and what it currently conveys.

2. Revoke it with `delete-access-grant` — see [Revoking a grant](#revoking-a-grant).
3. Create the replacement with `create-access-grant` (Step 3), then verify it.

The replacement has a **new grant ID**. Anything that recorded the old ID (a runbook, an
audit note) needs updating. Between steps 2 and 3 the principal holds no grant at that
level, so tell the customer there is a brief gap, and do it at a time that gap is
acceptable.

**Constraints:**

- You MUST NOT try to change a level by creating a second grant alongside the first at

  the same named permission — it conflicts. Revoke first.

- You MUST NOT revoke a customer's grant to "change" it without first confirming the

  replacement's exact permission and scope; a revoke with no agreed replacement is
  simply a revocation.

## Revoking a grant

```
aws cloudwatch-omni delete-access-grant --grant-id <grant-id>
```

Revoking a grant removes the access it conveyed for **future** credential requests. It
does not delete anything in the Space, and it does not affect the principal's other
grants. It is **not** immediate: credentials already issued to the principal stay valid
until they expire or the session is re-established, so tell the customer a revocation is
not a way to cut off access already in flight.

Revocation is the *only* way a grant ends — grants carry no expiry, so "remove their
access" always means a `delete-access-grant`.

**Constraints:**

- You MUST confirm which grant is being revoked before revoking it, by grant ID and by

  what it conveys. A principal often holds several, and "remove their access" rarely
  means all of them — list them first ([What a given principal holds](#what-a-given-principal-holds)).

- You MUST NOT revoke the caller's own `SPACE_ADMIN` grant without warning them that

  they may lose the ability to manage grants in that Space.

- Deleting a Space's last administrative grant leaves the Space unreachable. You MUST

  say so before doing it.

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
aws cloudwatch-omni list-access-grants --space-id <space-id>
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

Narrow the list **server-side** with the filters the operation supports, whenever the
ask names an exact value:

| The ask | Filter |
|---|---|
| "Which roles have access?" | `--principal-type IAM_ROLE` |
| "Who has admin here?" / "Who can grant access?" | `--permission SPACE_ADMIN` |
| "Who can write or delete?" | `--permission READ_WRITE_DELETE` |
| "Which Identity Center groups are granted?" | `--principal-type IDC_GROUP` |
| "Does alert `<name>` have access?" | `--principal-type ALERT --principal-id <alert-arn>` — an alert is identified by its ARN, never its name; resolve the name to its `alertArn` with `aws cloudwatch-omni list-alerts --space-id <space-id> --filter-criteria '{"names": ["<name>"]}'` first. A grant made to every alert has `principalId` `ALL` |
| "What does profile `<id>` hold?" | `--principal-type ACCESS_PROFILE --principal-id <profile-id>` |

### What a given principal holds

```
aws cloudwatch-omni list-access-grants --space-id <space-id> --principal-type <principal-type> --principal-id <principal-id>
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
aws cloudwatch-omni list-access-grants --space-id <space-id> --principal-type IAM_ROLE \
  --query "items[?contains(principal.principalId, 'jdoe')]"
```

Repeat with `--principal-type IAM_USER` if the person may be an IAM user. JMESPath
`contains` is case-sensitive, so match the alias as it appears in the ARN. Follow
`nextToken` across pages before concluding there is no match.

**An Identity Center user or group.** The grant holds only the Identity Center **UUID**
— the summary carries no display name, so no substring of an alias will ever match a
grant directly. Resolve the name to an ID first, in the Space's Domain:

```
aws cloudwatch-omni search-principals --domain-id <domain-id> --search-query <name-or-email>
```

Then filter the grants by that ID:

```
aws cloudwatch-omni list-access-grants --space-id <space-id> --principal-type IDC_USER --principal-id <idc-user-id>
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
aws cloudwatch-omni get-access-grant --grant-id <grant-id>
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
  delete within it" — not a dump of the raw JSON. Report the permission in plain
  language alongside the API value.

- **Only report what you read.** A summary gives you the principal and permission; you

  do not know a grant's scope until `get-access-grant` has returned it. Do not describe
  a scope you have not fetched, and do not describe an expiry that does not exist.

- **Say what you narrowed over.** If you filtered server-side, or matched client-side,

  or stopped before the last page, tell the customer how many grants you looked at — a
  filtered answer presented as complete is worse than an honest partial one.

- **A lookup that fails, fails.** `AccessDeniedException`, expired credentials, a

  missing `--space-id`, or a service error is a broken call, never a conclusion about
  the Space. Never report "nobody has access" or "X has no access" from a failed call;
  say the lookup failed, quote the error, and — when it points at expired credentials
  or a missing permission — relay that rather than retrying the same call.

## Troubleshooting

> **Not every authorization error is a missing grant.** If `create-space` succeeded
> and the Space then fails in use, suspect the **space access role's trust policy**,
> not a grant. `create-space` validates only that `dataAccessRoleArn` is non-blank and
> in the caller's account — it never attempts to assume the role, so a wrong trust
> policy is accepted at create time and fails in use. Check, on that role: the service
> principal is `cloudwatch.amazonaws.com`; all three of `sts:AssumeRole`,
> `sts:TagSession`, and `sts:SetContext` are allowed; and both the `aws:SourceAccount`
> and `aws:SourceArn` conditions are present and match. A missing grant instead means
> nobody could reach the Space from the start, for everyone. Do not create a grant to
> fix a trust-policy problem.

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
| `ValidationException` that `signalTypes` and `rowScopeGroups` must be specified together | One was sent without the other | Send both, or neither |
| `ValidationException` that the `METRICS` signal type is not supported | Row scoping was requested for metrics | Row scoping covers logs and traces only |
| `ValidationException` that a principal type cannot be granted an action | That action is not available to that kind of principal | Choose a different principal type, or drop the action |
| `ValidationException` that access profiles cannot be granted admin actions | An administrative action was requested for an `ACCESS_PROFILE` principal | Remove the administrative actions. A profile bounds a workload; it does not administer the Space |
| `ValidationException` that cross-account grants are not supported | The IAM principal is in another account | Grants only reach principals in the caller's account. Ask the customer for a principal in this account |
| `ValidationException` that the principal was not found in Identity Center | The user or group ID is wrong, or is not in this Domain's identity store | Look the principal up with `search-principals` and use the returned ID |
| `ValidationException` that a caller with one grant cannot manage another kind | The caller is trying to grant more than they hold | The caller needs a broader grant themselves. Report both levels and stop |
| `ValidationException` that the caller has no grants in this Domain | The caller holds nothing and cannot manage grants | The caller needs `SPACE_ADMIN` on the Space or an administrative grant on the Domain first |
| `ValidationException` that `Space` and `Domain` are not valid resource scope `resourceType` values | A parent-typed scope was sent; a grant is already scoped to a single Space or Domain | Omit `resources` to cover the whole Space, or name a resource type inside the Space |
| `ValidationException` that a resource type is not valid for an action (for example `Resource type Dashboard is not valid for action ListSpaceAccess`) | The `resourceType` is misspelled or miscased (`Dataset` for `DataSet`), or is not a type that action operates on. The message does NOT list the allowed values | Check the spelling against the list in Step 4, and pair the action with the resource type it acts on |
| `ConflictException` that an active grant already exists for the principal | A grant at that named permission is already in place | Read it with `list-access-grants`. To change the level, revoke the existing grant first |
| `ConflictException` that the maximum `CUSTOM` grants was reached | 10 `CUSTOM` grants already exist for that principal in that Space | Consolidate the actions into fewer grants, or revoke one that is no longer needed |
| `ValidationException` that the principal or Space grant maximum was met | 50 per principal, or 500 per Space | Revoke grants that are no longer needed, or grant to a group rather than to individuals |
| `ResourceNotFoundException` from `get-access-grant` | No grant with that ID exists — the ID is wrong, or the grant was already revoked | A successful lookup with nothing found, not a failure. List the Space's grants to find the right ID; do not retry with a guessed one. `delete-access-grant` does not raise this — it is idempotent, and deleting a grant that no longer exists succeeds |
| `AccessDeniedException` from `list-access-grants` or `get-access-grant` | The caller's own grant does not permit reading grants on this Space | The lookup is **inconclusive**, not "no grants". The caller needs `SPACE_ADMIN` on the Space or an administrative grant on the Domain to read grants (**unverified** whether a lesser level can list grants — if a `READ` caller gets this error, that is the answer) |

If the error does not match a row above, quote it verbatim, say it is unmapped, and ask
the customer how to proceed.

## Gotchas — expectations that look like faults

- **A principal with a grant still cannot see anything.** Check the Space, not the

  grant. A grant names one Space, and a principal working in a different Region is
  working against a different Space.

- **A second grant at the same level is rejected.** Named-permission grants are one per

  principal per Space per level. Revoke and re-create to change a level.

- **There is no write-only permission.** `READ_WRITE_DELETE` is the only mutating named

  level. A customer expecting to grant writes without deletes needs `CUSTOM`.

- **There is no update operation.** Renaming, re-leveling, or re-scoping a grant is a

  revoke plus a create, and the grant ID changes.

- **A narrowed grant appears to be missing data.** Row scoping is an allowlist with `IN`

  only. Anything not named in `values` is excluded, and excluded data is
  indistinguishable from absent data.

- **A revoked grant seems to still work.** Credentials already issued to the principal

  stay valid until they expire or the session is re-established.

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
  (`--permission SPACE_ADMIN`) is the first question of any access audit.

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
  restrict the principal's `logs:*` on the source log groups too.

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
