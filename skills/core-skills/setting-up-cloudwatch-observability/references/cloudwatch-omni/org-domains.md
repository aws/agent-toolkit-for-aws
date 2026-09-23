# Setting up a Domain for an AWS Organization

An **org-scoped Domain** is created once from the organization's management
account and shared by every member account. Spaces are then created in member
accounts under it. It is a separate operation family from the account-scoped
Domain, with a different required role, a different deletion operation, and a
prerequisite that lives in AWS Organizations rather than in Omni.

> **Always state these, in any answer drawn from this file:**
>
> - Trusted access for `observabilityadmin.amazonaws.com` must be enabled in AWS
>   Organizations first, and because that is an organization-wide change you MUST ask
>   the customer before enabling it — even if they already said to proceed.
> - `create-domain-for-organization` is **management account only**; a registered
>   delegated administrator can do everything else but not that. An account-scoped
>   Domain on the management account **blocks** an org Domain and must be deleted
>   first, which is the customer's decision.
> - A Domain grant is **`ADMIN` only** and reaches **every Space** in the Domain,
>   including future ones. Prefer `IDC_GROUP`; do not use `IAM_ROOT` unless asked.
> - Teardown order: every Space first, then the Domain, from its **home Region**, using
>   `delete-domain-for-organization` (`delete-domain` rejects an org Domain). Deleting
>   the Domain removes its grants, so do not revoke them first.

## Contents

- [Which path](#which-path)
- [What you get when setup completes](#what-you-get-when-setup-completes)
- [Prerequisites](#prerequisites)
- [Step 1 — Interview the customer first](#step-1--interview-the-customer-first)
- [Step 2 — Enable trusted access](#step-2--enable-trusted-access)
- [Step 3 — Create the domain access role](#step-3--create-the-domain-access-role)
- [Step 4 — Create the Domain](#step-4--create-the-domain)
- [Step 5 — Create the Spaces](#step-5--create-the-spaces)
- [Step 6 — Grant Domain access](#step-6--grant-domain-access)
- [Verifying the setup](#verifying-the-setup)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)
- [Security considerations](#security-considerations)
- [Additional resources](#additional-resources)

## Which path

| The customer wants | Path |
|---|---|
| A Domain shared across an AWS Organization | **Org-scoped** — this file |
| A Domain for a single account | **Account-scoped** — see `references/cloudwatch-omni/spaces-and-domains.md` |

The two are mutually exclusive on the same account. A Domain of either scope
already on the management account blocks creating the other.

**Who may call what** differs across the org operations. Establish the caller's
account up front and match it against this table before calling anything:

| Operation | Eligible caller |
|---|---|
| `enable-aws-service-access` on `organizations` | **Management account only** |
| `create-domain-for-organization` | **Management account only** |
| Every other `*-for-organization` operation | Management account, or a registered **delegated administrator** |
| `create-space` | The **member account** that will own the Space, or the management account using credentials vended for that account |

**Constraints:**

- You MUST confirm the caller is in the management account before attempting

  trusted access or `create-domain-for-organization`. A delegated administrator can
  do everything else but neither of those.

- You MUST NOT use `create-domain` or `delete-domain` on an org Domain. Those are

  the account-scoped operations and the service rejects the mismatch.

## What you get when setup completes

- A **domain ID** shaped `d-` followed by up to 25 lowercase alphanumerics, a

  **domain ARN**, and a **domain endpoint URL** derived from the domain name.

- The Domain also reports the **organization ID** and the **owner account ID**,

  which is the management account.

- A **Space per member account per Region**.
- One or more **domain access grants**, each with a grant ID (a UUID), naming the

  principals who administer the Domain.

An org Domain ARN uses the resource type `organization-domain`, where an
account-scoped Domain uses `domain`. That difference is how you tell them apart in
a listing.

Quotas and scope rules to state up front:

- **One Domain per organization**, keyed on the management account.
- **One Space per account per Region**, unchanged from the account-scoped path.
- A domain access grant applies to the **whole Domain**. It conveys access to every

  Space in the Domain, present and future — it is not scoped to one Space or one
  account.

- Domain access grants carry exactly one permission and it is always `ADMIN`.

  There is no read-only or scoped variant at the Domain level; narrower access is
  granted per Space.

**Constraints:**

- You MUST tell the customer the domain name becomes part of the endpoint URL

  before they choose it.

- You MUST tell the customer that a Domain-level grant reaches every Space in the

  organization's Domain and is `ADMIN`-only. A customer who expects it to be
  limited to one account or one Space has misunderstood the blast radius.

## Prerequisites

- **Trusted access for CloudWatch Observability Admin enabled in AWS

  Organizations.** Step 2 checks and enables it. Without it every org operation
  fails authorization, and the failure does not name the missing prerequisite
  clearly.

- **A caller in the management account** for trusted access and Domain creation.
- **An IAM role in the management account** to pass as `domainAccessRoleArn`. See

  Step 3.

- **For an Identity Center Domain**, the instance ARN. The Domain must be created

  in the instance's primary Region; the service verifies this.

**Region rules:**

- An org Domain supports Spaces in Regions other than the Domain's own.
- If the Domain uses **Identity Center**, a Space's Region must also be one the

  Identity Center instance is replicated to.

- Not every Region is available for Spaces under a given org Domain. Confirm

  rather than assume, and read the rejection message when one comes back.

**Constraints:**

- You MUST resolve trusted access before doing anything else. Every other failure

  mode in this document is easier to diagnose once it is ruled out.

- You MUST NOT promise a Space in a given Region under an Identity Center org

  Domain without confirming Identity Center is replicated there.

### Operations you will call

Every operation runs through the `aws___call_aws` tool as an `aws <service>
<operation>` CLI command, with the operation's inputs passed as CLI flags
(`--kebab-key`). Policy documents appear below as standalone JSON blocks — pass each
as the corresponding flag value (`--assume-role-policy-document`).

**`aws organizations` operations:**

| Intent | Command |
|---|---|
| Check whether trusted access is enabled | `aws organizations list-aws-service-access-for-organization` |
| Enable trusted access | `aws organizations enable-aws-service-access` |

**`aws cloudwatch-omni` operations:**

| Intent | Command |
|---|---|
| Discover which Domains exist, and of which scope | `aws cloudwatch-omni list-domains` |
| Create the Domain | `aws cloudwatch-omni create-domain-for-organization` |
| Read the Domain back | `aws cloudwatch-omni get-domain-for-organization` |
| Change the Domain's name or providers | `aws cloudwatch-omni update-domain-for-organization` |
| Delete the Domain | `aws cloudwatch-omni delete-domain-for-organization` |
| List every Space across the organization | `aws cloudwatch-omni list-spaces-for-organization` |
| Vend credentials for a member account | `aws cloudwatch-omni get-space-credentials-for-organization` |
| Create a Space | `aws cloudwatch-omni create-space` — requires BOTH `--data-access-role-arn` and `--agent-core-evaluation-role-arn`; see `references/cloudwatch-omni/spaces-and-domains.md` |
| Grant a principal Domain administration | `aws cloudwatch-omni create-domain-access-grant-for-organization` |
| List Domain grants | `aws cloudwatch-omni list-domain-access-grants-for-organization` |
| Read one Domain grant | `aws cloudwatch-omni get-domain-access-grant-for-organization` |
| Revoke one Domain grant | `aws cloudwatch-omni delete-domain-access-grant-for-organization` |

**`aws iam` operations:**

| Intent | Command |
|---|---|
| Create the domain access role | `aws iam create-role` |
| Attach a managed policy | `aws iam attach-role-policy` |
| Detach a managed policy | `aws iam detach-role-policy` |
| Delete the role | `aws iam delete-role` |

**`aws sso-admin` operations:**

| Intent | Command |
|---|---|
| Find the customer's Identity Center instances | `aws sso-admin list-instances` |

**`aws sts` operations:**

| Intent | Command |
|---|---|
| Confirm the calling identity and account | `aws sts get-caller-identity` |

Report the caller identity before starting, and confirm the account is the
management account:

```
aws___call_aws → aws sts get-caller-identity
```

## Step 1 — Interview the customer first

Ask these in one message and wait for answers. Do not ask piecemeal, and do not
default silently.

1. **Region for the Domain?**
2. **Domain name?** It becomes part of the endpoint URL. Lowercase letters, digits,

   and single hyphens between them; 3–63 characters.

3. **Authorization provider** — IAM, Identity Center, or both?
4. **If Identity Center:** the instance ARN. Also ask which Regions Spaces will be

   needed in, so replication can be checked before promises are made.

5. **Domain access role** — should the agent **create a new role** in the

   management account, or will the customer **supply an existing role ARN**?
   Recommend creating one.

6. **Which member accounts need Spaces, and in which Regions?** Also ask whether

   those accounts will create their own Spaces, or whether the management account
   should create them on their behalf.

7. **Who administers the Domain?** The principals to grant `ADMIN` to in Step 6.

Confirm the choices back in one line, then execute.

If the customer does not know their Identity Center instance ARN, look it up for
them rather than sending them away to find it:

```
aws___call_aws → aws sso-admin list-instances
```

Each entry carries the instance ARN and its identity store ID. The public
reference for this operation is
[sso-admin list-instances](https://docs.aws.amazon.com/cli/latest/reference/sso-admin/list-instances.html).

**Constraints:**

- You SHOULD recommend creating the role rather than reusing one. Unlike the

  account-scoped path, the service actually attempts to assume this role at create
  time, so a role with the wrong trust policy fails the create outright.

- You MUST ask which Regions Spaces are needed in when the Domain uses Identity

  Center. Discovering a Region is unavailable after the Domain exists means the
  Domain has to be recreated elsewhere or the Region abandoned.

- You MUST tell the customer in this same message that a Domain-level grant reaches

  every Space in the Domain, so they choose the Step 6 principals accordingly.

## Step 2 — Enable trusted access

Omni's organization operations depend on CloudWatch Observability Admin having
trusted access in AWS Organizations. The service principal is
`observabilityadmin.amazonaws.com`.

### Check first

```
aws___call_aws → aws organizations list-aws-service-access-for-organization
```

The response carries `EnabledServicePrincipals`, a list of entries each with a
`ServicePrincipal` and a `DateEnabled`. Look for `observabilityadmin.amazonaws.com`
among them. This call works from the management account or a registered delegated
administrator. The public reference is
[organizations list-aws-service-access-for-organization](https://docs.aws.amazon.com/cli/latest/reference/organizations/list-aws-service-access-for-organization.html).

### Enable it if absent

Ask the customer before enabling — this changes an organization-wide setting.
Present the `enable-aws-service-access` command and get the customer's explicit
confirmation before running it; do not enable trusted access as an implied step of
the overall setup, because it affects every account in the organization.

```
aws___call_aws → aws organizations enable-aws-service-access --service-principal observabilityadmin.amazonaws.com
```

This call is **management account only** and returns no body. Re-run the check to
confirm the principal now appears.

**Constraints:**

- You MUST ask before enabling, and you MUST ask even when the customer has already

  told you to proceed. It is an organization-wide change affecting every account in
  the organization, their administrator may need to authorize it, and "go ahead" on
  the overall task is not consent for this specific change. Surface the command and
  wait.

- You MUST use exactly `observabilityadmin.amazonaws.com`. Do NOT use

  `telemetry-pipelines.observabilityadmin.amazonaws.com` — that is a different
  principal for a different purpose and enabling it does not grant trusted access.

- If the check cannot be completed — access denied, or an ambiguous response — you

  MUST treat the result as **inconclusive, not negative**. Report that and stop.
  You MUST NOT enable trusted access on that basis.

- If the enable call is denied, you MUST report that the caller is not in the

  management account and stop. A delegated administrator can read the setting but
  cannot change it.

## Step 3 — Create the domain access role

This is the role the service assumes to operate on Spaces across the organization.
It MUST live in the **management account**, and unlike the account-scoped Space
role it is **verified at create time** — the service performs a real
`sts:AssumeRole` against it while handling `create-domain-for-organization`, and
the create fails if that does not succeed.

The ARN must match `arn:` followed by the partition, then
`:iam::<management-account-id>:role/<role-name>`, and be 20–2048 characters.

### Create the role

Call `create-role` with `AssumeRolePolicyDocument` set to this trust policy. The
`aws:SourceAccount` and `aws:SourceArn` conditions are confused-deputy
protection — keep both. Note the resource type is `organization-domain`, not
`domain`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudwatch.amazonaws.com"
      },
      "Action": ["sts:AssumeRole", "sts:TagSession", "sts:SetContext"],
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "<management-account-id>"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:cloudwatch:*:<management-account-id>:organization-domain/*"
        }
      }
    }
  ]
}
```

```
aws___call_aws → aws iam create-role --role-name <role-name> --assume-role-policy-document <trust-policy-json>
```

### Attach the managed policy

```
aws___call_aws → aws iam attach-role-policy --role-name <role-name> --policy-arn arn:aws:iam::aws:policy/CloudWatchOmniDomainAccessPolicy
```

**Constraints:**

- The role MUST be in the management account. A role in any other account is

  rejected, and the message names the management account requirement.

- The `aws:SourceArn` pattern MUST use the `organization-domain` resource type and

  MUST stay wildcarded across Region and domain ID. The domain ID does not exist
  yet when the role is created, so a narrower pattern cannot match.

- You MUST NOT substitute a `*FullAccess` policy or hand-write a broad inline

  policy. The Domain's permissions are defined by the managed policy above.

- You MUST NOT skip creating the role and hope `create-domain-for-organization`

  provisions one. The role ARN is a required input.

- If the create-time assume check fails, you MUST report the trust policy as the

  cause and stop. Do NOT retry the Domain create — it will fail identically until
  the trust policy is fixed.

- You MUST NOT attach the managed policy to a role the customer supplied without

  asking. They may be reusing it, and widening someone else's role is not yours
  to do.

## Step 4 — Create the Domain

### Check what already exists first

`list-domains` reports the Domains visible to the caller, of both scopes, and each
entry carries its ARN. Use the ARN's resource type to tell them apart —
`organization-domain` for an org Domain, `domain` for an account-scoped one. This
is the check to run when the customer has no domain ID yet.

```
aws___call_aws → aws cloudwatch-omni list-domains
```

Read the result before creating anything:

- **An `organization-domain` entry exists** — the org Domain is already set up.

  Report its name and ID from the summary and its endpoint URL from
  `get-domain-for-organization` (summaries do not carry it), confirm the customer wants to use it, and
  continue from Step 5 with its `domainId`.

- **Only a `domain` entry exists** — an account-scoped Domain occupies the

  management account, and **it blocks the org Domain**. **Tell the customer it must be deleted before an org Domain can
  be created, and that deleting it is their decision.** Then stop. Do not create
  anything, and do not describe the situation merely as blocking.

- **Nothing comes back** — proceed.

**Constraints:**

- You MUST run this check before `create-domain-for-organization`.
- If an account-scoped Domain occupies the management account, you MUST say plainly

  that it has to be **deleted** before an org Domain can be created, and that
  deleting it is the customer's decision. Do NOT describe it vaguely as blocking.

- You MUST distinguish the two ARN resource types rather than treating any returned

  Domain as the org Domain. Acting on an account-scoped Domain as though it were
  org-scoped produces confusing failures several steps later.

- If the check cannot be completed — access denied, or an ambiguous response — you

  MUST treat the result as **inconclusive, not negative**. Report that and stop.
  You MUST NOT create a Domain on that basis.

### Create it

For an **IAM-only** Domain:

```
aws___call_aws → aws cloudwatch-omni create-domain-for-organization \
  --name <domain-name> --identity-providers IAM \
  --domain-access-role-arn arn:aws:iam::<management-account-id>:role/<role-name>
```

For an **Identity Center** Domain, `identityProviderConfiguration` becomes
required and carries the instance ARN:

```
aws___call_aws → aws cloudwatch-omni create-domain-for-organization \
  --name <domain-name> --identity-providers IAM IDC \
  --domain-access-role-arn arn:aws:iam::<management-account-id>:role/<role-name> \
  --identity-provider-configuration '{"identityCenterConfiguration": {"identityCenterInstanceArn": "<idc-instance-arn>"}}'
```

Capture `domainId`, `domainArn`, `domainEndpointUrl`, `organizationId`, and
`ownerAccountId` from the `organizationDomain` object in the response (the same
object `get-domain-for-organization` and `update-domain-for-organization` return).

**Constraints:**

- You MUST create an Identity Center Domain in the instance's **primary** Region.

  The service verifies this; the rejection names the primary Region and the current
  Region, so read it rather than guessing.

- You MUST capture `domainEndpointUrl` and give it to the customer. Every member

  account reaches Omni through it.

## Step 5 — Create the Spaces

A Space lives in a member account. There are two ways to create one, and the
choice was made in Step 1.

The Space itself — its name, its space access role, its encryption — works exactly
as it does under an account-scoped Domain. See
`references/cloudwatch-omni/spaces-and-domains.md`, picking up at its Space steps. The space
access role is still required and still belongs in the account that will own the
Space.

### Path A — the member account creates its own Space

The member account calls `create-space` directly, passing the shared `domainId`.
Nothing about the call differs from the account-scoped path except that the Domain
was not created by that account.

### Path B — the management account creates it on the member's behalf

The management account, or a registered delegated administrator, vends credentials
for the target account and uses them to create the Space:

```
aws___call_aws → aws cloudwatch-omni get-space-credentials-for-organization \
  --context '{"domainId": "<domain-id>", "targetAccountId": "<target-account-id>"}'
```

The response carries temporary credentials for the target account. Use them to call
`create-space` against that account. Once a Space exists, credentials can be vended
for it directly by passing `spaceId` in the `context` instead of the
`domainId`/`targetAccountId` pair.

Enumerate what exists across the organization at any point:

```
aws___call_aws → aws cloudwatch-omni list-spaces-for-organization
```

**Constraints:**

- You MUST NOT tell a member account to call `create-domain` first. The org Domain

  already exists and a second Domain in the member account is neither needed nor
  permitted alongside it.

- On Path B you MUST use the vended credentials for the `create-space` call itself.

  Calling `create-space` with the management account's own credentials creates a
  Space in the management account, not the target account.

- Region availability is narrower than it looks. A Space may live in a Region other

  than the Domain's, but not every Region is available, and under an Identity
  Center Domain the Region must also be one Identity Center is replicated to.

## Step 6 — Grant Domain access

A Domain with no grants has no administrators. Grant the principals the customer
named in Step 1.

A grant applies to the **entire Domain**. It conveys administration of every Space
in the Domain, including Spaces created later. There is no way to scope a
Domain-level grant to one account or one Space — that is what per-Space grants are
for.

```
aws___call_aws → aws cloudwatch-omni create-domain-access-grant-for-organization \
  --domain-id <domain-id> \
  --name <grant-name> \
  --principal '{"principalType": "<principal-type>", "principalId": "<principal-id>"}' \
  --permission ADMIN
```

`name` is required: 1–64 characters matching `^[a-zA-Z0-9_-]+$`. `permission` takes
the single value `ADMIN`. `principalType` is one of `IDC_USER`, `IDC_GROUP`,
`IAM_USER`, `IAM_ROLE`, or `IAM_ROOT`.

Capture the grant ID from the `accessGrant` object; it is what
`delete-domain-access-grant-for-organization` takes if a single grant needs
revoking later.

Review the grants with:

```
aws___call_aws → aws cloudwatch-omni list-domain-access-grants-for-organization --domain-id <domain-id>
```

**Constraints:**

- `permission` is a single value and it must be `ADMIN`. The account-scoped

  permission values — `READ`, `READ_WRITE_DELETE`, `SPACE_ADMIN`, and `CUSTOM` — are
  not valid at the Domain level.

- You MUST state the blast radius when confirming a grant: the principal will

  administer every Space in the organization's Domain.

- For an Identity Center Domain you SHOULD prefer `IDC_GROUP` over `IDC_USER`.

  Group membership changes without touching grants.

- You MUST NOT grant `IAM_ROOT` unless the customer explicitly asks. It is the

  broadest principal available and rarely what they mean.

## Verifying the setup

Read the Domain back rather than trusting the create response, and confirm the
Spaces and grants landed:

```
aws___call_aws → aws cloudwatch-omni get-domain-for-organization --domain-id <domain-id>

aws___call_aws → aws cloudwatch-omni list-spaces-for-organization

aws___call_aws → aws cloudwatch-omni list-domain-access-grants-for-organization --domain-id <domain-id>
```

Then report to the customer, in one line: the domain endpoint URL, the domain ID,
the organization ID, how many Spaces exist, and how many administrators were
granted.

**Constraints:**

- You MUST confirm at least one `ADMIN` grant exists before declaring setup

  complete. A Domain nobody administers is not a working setup.

## Cleanup

Order matters, and it spans accounts.

1. **Every Space is deleted.** The Domain cannot be deleted while any Space is

   associated with it. Use `list-spaces-for-organization` to enumerate what
   remains. A Space is deleted by its owning account, or by the management account
   using credentials vended through `get-space-credentials-for-organization`.

2. Delete the Domain, from its **home Region** — the Region it was created in:

   ```
   aws___call_aws → aws cloudwatch-omni delete-domain-for-organization --domain-id <domain-id>
   ```

   Use `delete-domain-for-organization`, not `delete-domain` — the account-scoped
   operation rejects an org Domain and tells you to use this one instead.

   Deleting the Domain removes its access grants. Do **not** revoke them first as
   hygiene; it is unnecessary work. `delete-domain-access-grant-for-organization` is
   for revoking one principal's access while the Domain stays in use.

3. The domain access role — branch on who created it:
   - **The agent created it in Step 3:** detach the managed policy with

     `detach-role-policy`, then `delete-role`. A role with policies attached cannot
     be deleted.

   - **The customer supplied it:** do NOT delete or modify it.

4. Trusted access can be left enabled. If the customer wants it off, that is an

   organization-wide change made through CloudWatch's own telemetry configuration
   controls rather than by disabling the Organizations integration directly.

**Constraints:**

- You MUST delete every Space before the Domain, and you MUST say plainly which

  accounts are involved. Spaces in member accounts need either that account's
  credentials or credentials vended for it.

- You MUST delete the Domain from its home Region. A delete from anywhere else is

  rejected and the message names the home Region.

- You MUST use `delete-domain-for-organization`. `delete-domain` rejects an org

  Domain and tells you to use this operation instead.

- Deleting Spaces is destructive. You MUST confirm with the customer first and say

  plainly that each Space's telemetry goes with it.

- You SHOULD NOT disable trusted access as part of cleaning up a Domain. It is

  organization-wide and other CloudWatch features depend on it.

## Troubleshooting

**Rule:** When a call returns an error, surface the error code and message
**verbatim**, then map to the mitigation below. Do NOT invent error text, do NOT
paraphrase what the service returned, and do NOT synthesize a mitigation for an
error that is not listed.

| Error signal | Cause | Mitigation to surface |
|---|---|---|
| Authorization error stating trusted access is disabled | CloudWatch Observability Admin trusted access is not enabled for the organization | Run Step 2 — check with `list-aws-service-access-for-organization` and enable `observabilityadmin.amazonaws.com`. Nothing else works until it is on |
| `AccessDeniedException` on `enable-aws-service-access` | Caller is not in the management account | Only the management account can enable trusted access. A delegated administrator can read the setting but not change it |
| Authorization error stating only the management account can create an organization domain | Caller is a member account or a delegated administrator | Domain creation must run from the management account. A delegated administrator can perform every other org operation |
| `ValidationException` that the management account ID could not be resolved | Caller is not in an organization, or trusted access is off | Confirm the account belongs to an organization and that trusted access is enabled |
| `ValidationException` that `domainAccessRoleArn` must be a role in the management account | Role lives in a member account | Create the role in the management account. A member-account role cannot be used |
| An error stating the data access role could not be assumed, naming the trust policy | The create-time assume check failed | Fix the role's trust policy so the CloudWatch service can assume it, and confirm the `aws:SourceArn` uses the `organization-domain` resource type. Do NOT retry unchanged — it fails identically |
| `ConflictException` naming a management account that already has a Domain | The management account already has a Domain. This fires whether that Domain is org-scoped or account-scoped — the two are mutually exclusive on one account | Run `list-domains` and read the ARN resource type. If it is `organization-domain`, use it. If it is `domain`, the account-scoped Domain must be deleted before an org Domain can be created. Do NOT retry the create |
| `ValidationException` naming the Identity Center primary Region | Domain not being created in the instance's primary Region | Create the Domain in the primary Region the message names. `list-instances` on `sso-admin` shows the instances the caller can reach |
| `ValidationException` that Identity Center is not replicated to a Region | A Space was requested in a Region where the Identity Center instance is not replicated | Either create the Space in a Region where Identity Center is replicated, or have the customer replicate Identity Center to that Region |
| Error stating Spaces for organization domains must be created in the same Region as the organization domain | The target Region is not available for Spaces under this Domain | Create the Space in the Domain's Region, or ask the customer which Regions are enabled for Spaces in their organization |
| Error stating cross-account access requires management account or registered delegated administrator | Caller is an ordinary member account | Run the operation from the management account, or register the account as a delegated administrator |
| A Space appears in the management account instead of the target account | `create-space` was called with the management account's own credentials rather than the vended ones | Delete that Space, re-vend credentials with `get-space-credentials-for-organization`, and call `create-space` with those |
| `ResourceNotFoundException` that the Domain is not an organization-scoped domain | `delete-domain-for-organization` was called on an account-scoped Domain | Use `delete-domain` for that Domain |
| `ValidationException` that an organization-scoped domain cannot be deleted via `DeleteDomain` | Wrong deletion operation | Use `delete-domain-for-organization` |
| Error stating the Domain must be deleted from its home Region | Delete attempted from another Region | Retry from the Region named in the message |
| `ConflictException` stating Spaces are still associated with the Domain | Spaces still exist under the Domain | Enumerate them with `list-spaces-for-organization` and delete each, then retry |

If the error does not match a row above, quote it verbatim, say it is unmapped,
and ask the customer how to proceed.

### Expectations that look like faults

- **Every org operation fails authorization at once.** That is trusted access being

  off, not a permissions problem on the caller.

- **A Domain-level grant cannot be made read-only, or scoped to one account.**

  `ADMIN` over the whole Domain is the only shape. Narrower access is granted per
  Space.

- **A Space cannot be created in some Region.** Region availability under an org

  Domain is narrower than it appears, and under an Identity Center Domain the
  Region must also have Identity Center replicated. Nothing about the Domain or the
  Space request is wrong.

- **Grants disappear when the Domain is deleted.** That is expected — the service

  removes them with the Domain.

## Security considerations

- The domain access role is assumed for callers across the whole organization. It

  is the broadest role in this setup — keep both `aws:SourceAccount` and
  `aws:SourceArn` conditions on its trust policy, keep the `organization-domain`
  resource type pinned, and keep the role out of any workflow that does not need
  it.

- Keep the domain access role in the management account and nowhere else. The

  service requires this, and it keeps organization-wide capability from sitting in
  a member account.

- A Domain access grant reaches every Space in the Domain. Treat it as an

  organization-wide grant, not an account-level one, and keep the list short.

- Prefer `IDC_GROUP` over `IDC_USER` for Domain administrators so that offboarding

  a person does not require finding and revoking their grant.

- Avoid `IAM_ROOT` as a grant principal. Root has no session identity to attribute

  actions to.

- Credentials from `get-space-credentials-for-organization` are temporary and act

  in another account. Do not persist or log them, and do not reuse them beyond the
  operation they were vended for.

- Enumerate grants with `list-domain-access-grants-for-organization` periodically.
- Delegated administrator is a standing organization-wide capability. Register only

  accounts the customer intends to keep in that role.

- Trusted access is organization-wide and shared with other CloudWatch features.

  Enabling it is a deliberate decision for the organization administrator, not a
  side effect of setting up one Domain.

## Additional resources

- `references/cloudwatch-omni/spaces-and-domains.md` — account-scoped Domains, and the Space steps

  used under an org Domain

- `references/cloudwatch-omni/instrumentation/collector.md` — deploying a collector that exports to

  CloudWatch's OTLP endpoints, for telemetry not yet reaching CloudWatch

- `references/cloudwatch-omni/data-forwarding-and-centralization.md` — forwarding telemetry that is

  already in CloudWatch log groups into the Dataset
