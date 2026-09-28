# Bounding a workload with an Access Profile

An **Access Profile** limits what CloudWatch Omni is allowed to do on a customer's
behalf when it acts without a person present. Everything that runs under a profile
is an **async workload** — an alert running an investigation, with no user in the loop
to approve what it does, which is why the profile is the boundary it operates inside.

A profile is a **named container**, nothing more. Creating one grants no
permissions: `create-access-profile` takes only the Space, a name, and a
description — there is no permission, action, or resource-scope input on the create
call at all. What makes a profile useful is two sets of access grants: grants that
say what the profile can do, and grants that say which workloads may assume it — plus
the workload itself naming the profile. All three are described below, and none is
optional.

> **Always state these, in any answer drawn from this file:**
> that a profile carries no permissions of its own, and that `create-access-profile`
> accepts only a Space, a name, and a description — no scoping input of any kind, so
> creating one by itself produces an empty container; that it needs BOTH a permission
> grant (principal `ACCESS_PROFILE`) and a trust grant (principal the workload); that
> a trust grant for an alert MUST use `principalId` `ALL` for the alert to be
> creatable, on a `CUSTOM` grant carrying only the assume action; that the profile ARN
> must be taken from the API response
> rather than assembled by hand; that an invalid permission value is rejected with a
> message naming the supported set; and that profile names are
> unique within a Space.

## Contents

- [Which path](#which-path)
- [How a profile actually works](#how-a-profile-actually-works)
- [Prerequisites](#prerequisites)
- [Step 1 — Interview the customer first](#step-1--interview-the-customer-first)
- [Step 2 — Create the profile](#step-2--create-the-profile)
- [Step 3 — Give the profile its permissions](#step-3--give-the-profile-its-permissions)
- [Step 4 — Let the workload assume the profile](#step-4--let-the-workload-assume-the-profile)
- [Step 5 — Bind the profile to the workload](#step-5--bind-the-profile-to-the-workload)
- [Verifying the setup](#verifying-the-setup)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)
- [Security considerations](#security-considerations)
- [Additional resources](#additional-resources)

## Which path

| The customer wants | Path |
|---|---|
| To limit what an alert can do on their behalf | **This file** |
| To give a person or an IAM identity access to a Space | `references/cloudwatch-omni/access-grants.md` |
| To administer a Domain across an organization | `references/cloudwatch-omni/org-domains.md` |

A profile is not a way to give people access. Its principals are workloads.

**Constraints:**

- You MUST NOT create an Access Profile to grant a person or a team access. Grant
  them directly — see `references/cloudwatch-omni/access-grants.md`.
- You MUST NOT treat a profile as an administrative role. The service refuses to
  grant administrative actions to a profile.

## How a profile actually works

Three pieces have to line up. A profile with any of them missing fails closed, and
the failure surfaces when the workload runs rather than when the profile was set up.

1. **The profile** — a name in a Space. Carries no permissions of its own.
2. **Permission grants** — access grants whose principal is the profile. These
   define what the profile can do. Without them the workload assumes the profile
   successfully and is then permitted nothing.
3. **Trust grants** — access grants whose principal is the workload, carrying the
   action that lets it assume the profile, scoped to the profile itself. Without
   them the workload cannot assume the profile at all. A trust grant uses `ALL` to
   cover every alert in the Space, which is what an alert needs to be created at all,
   or names one existing alert by its ARN.

`get-access-profile` does not report either set — it returns only the profile itself
(`profileId`, `spaceId`, `arn`, `name`, `description`, `createdAt`, `updatedAt`,
`assumeStatus`, `profileType`). Read the two sets from the grants: permission grants
with `list-access-grants --space-id <space-id> --principal-type ACCESS_PROFILE
--principal-id <profile-id>`, and trust grants by listing the Space's grants and
keeping those whose scope names the profile ARN. Reviewing them as two lists is the
quickest way to see which piece is missing.

Finally, the workload has to **name the profile**. Nothing binds a profile to a
workload implicitly, and there is no separate bind operation — the profile's ID is a
field on the workload's own configuration.

**Constraints:**

- You MUST complete all of Steps 2 through 5. Stopping after creating the profile
  produces something that looks configured and does nothing.
- You MUST explain the two grant kinds to the customer as separate things. A
  customer who creates only permission grants will see the workload fail to assume
  the profile; one who creates only trust grants will see it assume the profile and
  then be denied everything. The two failures look nothing alike.

## Prerequisites

- **The Space's `spaceId`**, and the `domainId` for creating grants. See
  `references/cloudwatch-omni/spaces-and-domains.md` if the Space does not exist.
- **A grant of your own that permits managing grants** in that Domain. Both grant
  kinds below require it.
- **The workload's identifier** — `ALL`, or an existing alert's ARN. Trust grants
  are keyed on it, and never on the alert's name.

**Constraints:**

- You MUST have the workload's identifier before Step 4. A trust grant cannot be
  written against a workload that has not been named, and creating the workload
  first will fail if its profile has no trust grant yet.

### Operations you will call

Every operation runs through the `aws___call_aws` tool, which executes an
`aws <service> <operation>` CLI command — here `aws cloudwatchomni <operation>`, with
each input passed as a CLI flag (top-level keys become `--kebab-case` flags, and
nested objects and arrays of objects are passed as single-quoted JSON strings).

**`aws cloudwatchomni` (CloudWatch Omni control-plane operations):**

| Intent | CLI command |
|---|---|
| Check which profiles exist in the Space | `aws cloudwatchomni list-access-profiles` |
| Create the profile | `aws cloudwatchomni create-access-profile` |
| Read the profile (ID, ARN, name, description, status — not its grants) | `aws cloudwatchomni get-access-profile` |
| Rename the profile or change its description | `aws cloudwatchomni update-access-profile` |
| Delete the profile | `aws cloudwatchomni delete-access-profile` |
| Create a permission grant or a trust grant | `aws cloudwatchomni create-access-grant` |
| Review the grants involved | `aws cloudwatchomni list-access-grants` |
| Revoke a grant | `aws cloudwatchomni delete-access-grant` |

## Step 1 — Interview the customer first

Ask these in one message and wait for answers. Do not ask piecemeal, and do not
default silently.

1. **Which Space?** The `spaceId`, and the `domainId`.
2. **What workload is being bounded?** Which alert — and its identifier.
3. **What should that workload be allowed to do?** Ask in terms of the task, not in
   terms of actions. This becomes the permission grant in Step 3.
4. **A name for the profile?** 1–256 characters, and unique within the Space.
   Something that describes the boundary rather than the workload, since one profile
   can serve several workloads.
5. **A description?** Optional, up to 1024 characters. Worth having — a profile's
   purpose is not evident from its grants.
6. **Which alerts will run under this profile?** Useful context for naming and for
   Step 5, but it does not change the trust grant: an alert cannot be created unless the
   trust grant uses `ALL`. See Step 4.

Confirm the choices back in one line, then execute.

**Constraints:**

- You MUST ask question 3 in terms of the task the workload performs. A customer
  asked which actions to grant will over-grant, and the whole point of a profile is
  the boundary.
- You SHOULD name the profile after the boundary it expresses rather than after one
  workload. Several workloads can share a profile, and a profile named for one of
  them becomes misleading.

## Step 2 — Create the profile

### Check what exists first

Profile names are unique within a Space, so a duplicate name conflicts. An existing
profile may also already express the boundary the customer wants.

```
aws cloudwatchomni list-access-profiles --space-id <space-id>
```

If a suitable profile exists, report it and confirm the customer wants to reuse it
rather than creating another. Reusing means skipping to Step 4.

### Create it

```
aws cloudwatchomni create-access-profile --space-id <space-id> --name <profile-name> --description <description>
```

Capture both the profile ID and the profile **ARN** from the `accessProfile` object in
the response (the same object `get-access-profile` and `update-access-profile` return). Step 3 needs the ID, and Step 4 needs the ARN. The ARN takes the form
`arn:aws:cloudwatch:<region>:<account-id>:access-profile/<profile-id>` — read it
from the response rather than assembling it.

**Constraints:**

- You MUST run the existence check first. A name collision is rejected, and the
  message names the profile that already holds it.
- `create-access-profile` accepts no permissions, no actions, and no resource
  scopes. You MUST NOT look for a scoping parameter here or report the profile as
  configured once it exists.

## Step 3 — Give the profile its permissions

This is an ordinary access grant whose principal is the profile — the **permission
grant**. Everything the workload will be allowed to do comes from this one grant, so it
is the entire security boundary of the profile: a named permission (`READ`,
`READ_WRITE_DELETE`) or `CUSTOM` with `scopedActions` applies **here**, on the
permission grant, not on the trust grant in Step 4. Three things about it matter:

- `principalType` is `ACCESS_PROFILE` and `principalId` is the **profile's ID** —
  not a user, and not the workload.
- This grant is the **profile's** entire boundary. Anything it permits, the workload
  can do unattended, so grant the narrowest permission that lets it do its job. It bounds what runs
  *under this profile* — not everything the principal can do: the same `ALERT`
  principal may also hold its own direct grants on the Space, which this profile does not constrain.
  When reviewing what a workload can reach, check `list-access-grants` for that principal too.
- **Administrative actions cannot be granted to a profile.** The service rejects
  them.

```
aws cloudwatchomni create-access-grant --domain-id <domain-id> --space-id <space-id> \
  --name <grant-name> \
  --principal '{"principalType": "ACCESS_PROFILE", "principalId": "<profile-id>"}' \
  --permission READ
```

Use `CUSTOM` with `scopedActions` when a named permission is broader than the
workload needs. The permission model, the action format, and resource narrowing all
work exactly as described in `references/cloudwatch-omni/access-grants.md` — including
its one exception: a `DataSet` scope cannot be narrowed with `resourceArns` (a dataset
ARN is rejected with `Invalid observe resource type in ARN`). To confine an alert or
agent profile to one signal, such as traces only, scope the `DataSet` entry with
`signalTypes` (`TRACES`) together with `rowScopeGroups` — the two must be present
together, so give `rowScopeGroups` a condition that matches every record you want it
to see.

**Constraints:**

- You SHOULD grant the profile the narrowest permission that lets the workload do
  its job. This grant is the entire boundary **of the profile** — anything it permits, the workload
  can do unattended. It is not the whole of what the principal can reach: the same principal may
  also hold direct grants on the Space, which the profile does not constrain.
- You MUST NOT grant administrative actions to a profile. The service rejects it.
- You MUST NOT skip this step on the assumption that the trust grant in Step 4 also
  conveys permissions. It does not. A profile with only a trust grant is assumable
  and permitted nothing.

## Step 4 — Let the workload assume the profile

The workload needs its own grant, carrying the action that permits assuming a
profile. Without it the workload cannot assume the profile, and the failure appears
when the workload is created or when it next runs.

This grant is always `CUSTOM`, it carries the assume action and nothing else, and it
is scoped to the profile's own ARN so it cannot be used to assume any other profile.

### The trust grant must use `ALL`

**`principalId` MUST be `ALL`.** An alert's ID is minted by the service when the alert
is created, so `create-alert` authorizes the ALERT principal against the *wildcard*
alert ARN — `arn:<partition>:cloudwatch:<region>:<account-id>:alert/*` — and only a
grant on `ALL` matches a wildcard. A grant naming one alert cannot satisfy that check,
because the alert it names does not exist yet.

`ALL` is accepted for **`ALERT` only**; every other principal type rejects it. The scope
to the profile ARN still applies, so the grant is broad in *who* may assume and narrow in
*what* they may assume. Take `<access-profile-arn>` from the `create-access-profile`
response (or `get-access-profile`) — never assemble it by hand, because a hand-built ARN
that is off by one segment is accepted and then matches nothing:

```
aws cloudwatchomni create-access-grant --domain-id <domain-id> --space-id <space-id> \
  --name <grant-name> \
  --principal '{"principalType": "ALERT", "principalId": "ALL"}' \
  --permission CUSTOM \
  --scoped-actions '[{"actions": ["cloudwatch:AssumeAccessProfile"], "resources": [{"resourceType": "AccessProfile", "resourceArns": ["<access-profile-arn>"]}]}]'
```

**Never key a trust grant to an alert's name.** The identity an alert presents is its
ARN, so a name-keyed grant is accepted with a `200` and then matches nothing, at create
time or afterwards. It is inert in every state.

### Narrowing after the alert exists

Once the alert exists it has a concrete ARN, and the runtime assume is keyed on that
ARN. You may then replace the `ALL` grant with one naming that alert, using the ARN
`create-alert` returned:

```
aws cloudwatchomni create-access-grant --domain-id <domain-id> --space-id <space-id> \
  --name <grant-name> \
  --principal '{"principalType": "ALERT", "principalId": "<alert-arn>"}' \
  --permission CUSTOM \
  --scoped-actions '[{"actions": ["cloudwatch:AssumeAccessProfile"], "resources": [{"resourceType": "AccessProfile", "resourceArns": ["<access-profile-arn>"]}]}]'
```

Revoke the `ALL` grant only after the narrower grant is in place, and only if no further
alert needs to be created under this profile — creating the next one requires `ALL`
again.

**Constraints:**

- The trust grant MUST be `CUSTOM`, MUST carry only the assume action, and MUST be
  scoped to the profile's ARN with `resourceType` `AccessProfile`. An unscoped trust
  grant lets the workload assume any profile in the Space, which defeats the point of
  having a boundary.
- You MUST take the ARN from the profile's own response rather than assembling it.
  The ARN's service segment must match the service's vendor code, and a hand-built
  ARN is the usual way that goes wrong.
- The trust grant MUST use `principalId` `ALL`. Do NOT offer an alert's name as an
  alternative, and do NOT ask the customer to choose between `ALL` and a named alert
  before the alert exists — `ALL` is the only value that lets the alert be created.
- `ALL` is accepted only for `ALERT`, and only on a `CUSTOM` grant carrying only the
  assume action. Any other use is rejected.
- The action prefix MUST match the service's vendor code. If the grant is rejected
  on the prefix, use the one the message names.
- You MUST NOT add other actions to a trust grant. Whatever the workload should be
  able to *do* belongs on the profile in Step 3, not here.

## Step 5 — Bind the profile to the workload

The workload names the profile. There is no separate operation for this — the
profile's ID is a field on the workload's own configuration, set when the workload
is created or updated. For an alert, it is part of the alert's setup.

Because the binding lives on the workload, this step happens in whichever setup flow
creates that workload rather than here.

**Constraints:**

- You MUST complete Steps 3 and 4 before the workload is created. Some workloads
  validate the trust grant at creation time and refuse to be created without it.
- You MUST NOT report the profile as in effect until a workload names it. An
  unbound profile with both grants in place still does nothing.

## Verifying the setup

Read the two grant sets back. `get-access-profile` does not report grants — it returns
only the profile's own fields — so read them from `list-access-grants`:

```
# Permission grants — what the profile can do
aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type ACCESS_PROFILE --principal-id <profile-id>

# Trust grants — who may assume it: grants whose scope names the profile ARN
aws cloudwatchomni list-access-grants --space-id <space-id>
```

For the trust grants, read each candidate grant's detail with `get-access-grant` and
keep those whose `scopedActions` resources name the profile ARN. Confirm there is at
least one grant in each set. Then report to the customer, in one
line: which workload is bounded, what the profile permits, and which Space it is in.

**Constraints:**

- You MUST confirm both sets are non-empty before declaring the setup complete. One
  empty set is the single most common way this configuration fails, and it fails
  silently until the workload runs.

## Cleanup

> **In every answer from this section:** state that profile names are unique within a
> Space, so reusing a deleted profile's name is fine but a name still in use will be
> rejected as a conflict. Say this even when the customer only asked how to delete.

Deleting a profile is **not** blocked by the grants that reference it, and it is not
reversible. Profile names are unique within a Space, so re-creating a profile under the
same name after deleting it works, but creating a second one alongside it conflicts.

Two things follow from how the delete behaves, and both belong in any answer about it:

- **The profile's own permission grants go with it.** A grant whose `principalType` is
  `ACCESS_PROFILE` and whose `principalId` is this profile has no subject once the
  profile is gone, so the delete removes those grants for you. You do not need to revoke
  them first, and the delete is not rejected if you don't.
- **Trust grants that name the profile survive.** A grant whose principal is an `ALERT`
  and whose resource scope names the profile's ARN is left in place: it can carry other
  resources, and profile IDs are never reused. If the workload is going away too, revoke
  those separately.

1. List the grants that reference the profile (`get-access-profile` does not report
   them), and confirm the deletion with the customer:

   ```
   aws cloudwatchomni list-access-grants --space-id <space-id> --principal-type ACCESS_PROFILE --principal-id <profile-id>
   ```

   Trust grants naming the profile ARN are found by listing the Space's grants and
   reading each candidate's `scopedActions` with `get-access-grant`.

2. Delete the profile:

   ```
   aws cloudwatchomni delete-access-profile --space-id <space-id> --profile-id <profile-id>
   ```

3. Revoke any trust grants that named it, if their workload is going away too:

   ```
   aws cloudwatchomni delete-access-grant --grant-id <grant-id>
   ```

**Constraints:**

- You MUST tell the customer the delete is immediate and takes the profile's own
  permission grants with it. You MUST NOT present revoking them as a precondition, and
  MUST NOT say the delete is rejected while grants exist — it is not.
- You MUST state that trust grants naming the profile's ARN are left behind, and revoke
  them separately when the workload is going away too.
- You MUST check whether any workload still names this profile before deleting it.
  Removing a profile a live alert depends on breaks that workload,
  and the breakage appears the next time it runs rather than now.
- You MUST NOT delete a profile to "reset" it. Renaming or re-granting is
  non-destructive; deleting requires unwinding every workload that names it.

## Troubleshooting

**Diagnose from the grants first.** `get-access-profile` does not report grants. List
the permission grants with `list-access-grants --space-id <space-id> --principal-type
ACCESS_PROFILE --principal-id <profile-id>`, and the trust grants by listing the
Space's grants and keeping those whose scope names the profile ARN — an empty set names
the missing piece immediately. Reach for that before reasoning from the symptom.

Three states account for nearly every profile complaint, and a complete answer names
all three:

- **Can assume, then everything is denied** — the permission grant (principal
  `ACCESS_PROFILE`, Step 3) is missing or too narrow.
- **Cannot assume at all** — the trust grant (Step 4: `CUSTOM`, `AssumeAccessProfile`,
  scoped to the profile ARN, `principalId` `ALL` for alerts) is missing.
- **Both grants present, still no effect** — no workload names the profile (Step 5). A
  profile with a complete permission grant and a complete trust grant still does
  nothing until an alert, agent, or integration is bound to it.

**Rule:** When a call returns an error, surface the error code and message
**verbatim**, then map to the mitigation below. Do NOT invent error text, do NOT
paraphrase what the service returned, and do NOT synthesize a mitigation for an
error that is not listed.

| Error signal | Cause | Mitigation to surface |
|---|---|---|
| Conflict stating a profile with that name already exists in the Space | Profile names are unique per Space | Read the existing profile with `list-access-profiles` and either reuse it or pick another name |
| The profile's permission grants are gone after deleting the profile | Expected. The delete removes the grants where the profile was the principal | Nothing to fix. Trust grants that named the profile's ARN are still there and are revoked separately |
| An authorization error stating the caller is not authorized to assume the access profile | No trust grant exists for that workload, or it names a different profile | Create the trust grant from [Step 4](#step-4--let-the-workload-assume-the-profile) for that workload's type and identifier |
| An error naming an alert and stating it does not have trust to assume the profile | The alert was created before its trust grant existed | Create the trust grant with `principalType` `ALERT`, `principalId` set to `ALL`, and the assume action, then retry creating the alert |
| `ValidationException` that access profiles cannot be granted admin actions | An administrative action was requested in the Step 3 permission grant | Remove the administrative actions. A profile bounds a workload; it does not administer the Space |
| `ValidationException` that a wildcard principal identifier is not supported for this principal type | `ALL` was used with a type other than `ALERT` | Name the principal explicitly. `ALL` is only available for `ALERT` |
| `ValidationException` that type-scoped workload grants must be `CUSTOM` with the assume action | An `ALL` grant carried a named permission, or extra actions | Resend as `CUSTOM` carrying only the assume action |
| `ValidationException` that the action prefix must match the service vendor code | The assume action was written with the wrong prefix | Use the prefix the message names |
| `ConflictException` that an active grant already exists for the principal | The trust or permission grant is already in place | Read it with `list-access-grants`. Nothing further is needed for that grant |
| `ValidationException` about a malformed ARN | The profile ARN in the trust grant's resource scope is not a well-formed ARN | Read the ARN from `get-access-profile` and use it as returned. Do not assemble it by hand |
| `ValidationException` that the ARN service segment must match the service vendor code | The ARN was hand-built with the wrong service segment | Use the ARN the API returned, or the prefix the message names |
| `ResourceNotFoundException` on `get-access-profile` | Wrong `profileId`, or the profile is in a different Space | Both `spaceId` and `profileId` are required and must match. Re-read with `list-access-profiles` |

If the error does not match a row above, quote it verbatim, say it is unmapped,
and ask the customer how to proceed.

### Expectations that look like faults

- **The workload assumes the profile and then can do nothing.** The trust grant
  exists but the permission grant does not. Step 3 is missing.
- **The workload cannot assume the profile at all.** The permission grant exists but
  the trust grant does not. Step 4 is missing.
- **Creating the profile appeared to do nothing.** It did nothing on purpose. A
  profile carries no permissions until grants reference it.
- **A profile with both grants still has no effect.** No workload names it. The
  binding lives on the workload, not on the profile.
- **`create-access-profile` has no scoping parameters.** That is the design. Scope
  comes from grants.
- **A newly created alert works but an older one does not.** A grant narrowed to one
  alert's ARN does not cover others. `ALL` covers every alert, including future ones,
  and is what a new alert needs at create time.

## Security considerations

- The permission grant on a profile is the entire boundary for anything running
  under it, unattended and without a person to notice. Grant the narrowest
  permission that lets the workload do its job. When you audit what a workload can reach, check the
  principal's own grants too (`list-access-grants`) — the profile bounds what runs under the profile,
  not everything that principal holds.
- Trust grants and permission grants do different things and should be reviewed
  separately. A broad trust grant with a narrow permission grant is usually fine; a
  narrow trust grant with a broad permission grant is not.
- `ALL` is a standing trust for alerts that do not exist yet, and it is required to
  create an alert at all — so the boundary that matters is the profile ARN scope on the
  trust grant and the permission grant in Step 3, not the breadth of the principal. Where
  a customer wants a tighter principal, narrow to the alert's ARN after it exists.
- One profile per boundary, not one per workload. Several workloads sharing a
  profile is the intended pattern and keeps the number of grants reviewable.
- A profile's name and description are the only human-readable record of what the
  boundary is for. Write the description.
- Review profiles and their grants with `list-access-profiles` and
  `get-access-profile` periodically. A profile whose workloads were deleted keeps
  its grants and remains assumable by anything still trusted.

## Additional resources

- `references/cloudwatch-omni/access-grants.md` — the permission model, action format, and resource
  narrowing used by both grant kinds above
- `references/cloudwatch-omni/spaces-and-domains.md` — creating the Space a profile lives in
- `references/cloudwatch-omni/org-domains.md` — Domain-wide administration across an organization
