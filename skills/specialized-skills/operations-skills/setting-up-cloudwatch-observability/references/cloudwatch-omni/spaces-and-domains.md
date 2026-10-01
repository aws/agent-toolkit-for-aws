# Setting up a Domain and a Space

A **Domain** is the identity boundary: it carries the authorization provider and
owns the endpoint customers reach Omni through. A **Space** is the workspace that
holds telemetry and runs inside one account and Region. Setup is always
Domain first, then Space, because the Space is created against a domain ID.

> **Always state these, in any answer drawn from this file:**
> the quotas (one Domain per account, one Space per account per Region); that the
> domain name becomes the endpoint URL; that `create-space` never verifies the role
> can be assumed; and, before any delete, that deleting a Space is destructive and
> needs the customer's confirmation.
>
> **Two questions this file answers in full, each with every item below:**
>
> - *Can a Space be in a different Region from its Domain?* — depends on the Domain's
>   provider: yes under an IAM-only Domain; no under an Identity Center Domain, whose
>   Spaces must be in the Domain's own Region; Identity Center plus Spaces in several
>   Regions is what the org-scoped Domain is for. Never a bare "yes".
> - *The Space was created successfully but fails with an authorization error the
>   moment it is used.* — `create-space` checked only that the role ARN was present
>   and in the caller's account, never that the role can be assumed, so a wrong trust
>   policy is accepted at create time; check the space access role's trust policy for
>   the `cloudwatch.amazonaws.com` principal, all three of `sts:AssumeRole`,
>   `sts:TagSession`, and `sts:SetContext` (assume-role alone is accepted and fails in
>   use), and both confused-deputy conditions — `aws:SourceAccount` equal to the
>   account, `aws:SourceArn` matching the `cloudwatch` `space/` resource with Region
>   and space ID wildcarded, because the space ID does not exist when the role is
>   created; a successful create is not proof the role is right, so read the Space
>   back with `get-space` to verify; and recreating the Space is not the first remedy —
>   a new Space with the same role fails the same way.

## Contents

- [Which path](#which-path)
- [What you get when setup completes](#what-you-get-when-setup-completes)
- [Prerequisites](#prerequisites)
- [Step 1 — Interview the customer first](#step-1--interview-the-customer-first)
- [Step 2 — Create the Domain](#step-2--create-the-domain)
- [Step 3 — Create the space access role](#step-3--create-the-space-access-role)
- [Step 4 — Create the Space](#step-4--create-the-space)
- [Verifying the setup](#verifying-the-setup)
- [Cleanup](#cleanup)
- [Troubleshooting](#troubleshooting)
- [Security considerations](#security-considerations)
- [Additional resources](#additional-resources)

## Which path

Two decisions change which operations you call. Settle both before touching
anything.

**Who owns the Domain:**

| The customer wants | Path |
|---|---|
| A Domain for a single account | **Account-scoped** — `create-domain`, this file |
| A Domain shared across an AWS Organization | **Org-scoped** — `create-domain-for-organization`, management account only. See `references/cloudwatch-omni/org-domains.md` |

**Which authorization provider:**

| The customer authenticates with | `identityProviders` | Extra setup |
|---|---|---|
| IAM identities only | `["IAM"]` | None |
| IAM Identity Center | `["IAM", "IDC"]` | An Identity Center instance ARN, and the Domain MUST be created in that instance's primary Region |

**Constraints:**

- You MUST establish account-scoped versus org-scoped before calling anything. An
  org customer who gets an account-scoped Domain has to delete it and start over,
  and an account Domain blocks the org Domain from being created.
- You MUST NOT mix the two operation families. `create-domain` and
  `create-domain-for-organization` produce different Domains with different
  deletion operations.

## What you get when setup completes

- A **domain ID** shaped `d-` followed by up to 25 lowercase alphanumerics, a
  **domain ARN**, and a **domain endpoint URL**. The endpoint URL derives from the
  domain name, which is why the name is not cosmetic.
- A **space ID** (a UUID), a **space ARN**, and the Space's **Region**.

Quotas to state up front:

- **One Domain per account.** A second `create-domain` conflicts.
- **One Space per account per Region.** A second Space in the same Region
  conflicts; a Space in a different Region is a different Space.

**Constraints:**

- You MUST tell the customer the domain name becomes part of the endpoint URL
  before they choose it.
- You MUST state both quotas explicitly in any setup plan or answer you give —
  one Domain per account, and one Space per account per Region. Naming them is
  not optional detail: a customer who expects several Spaces in one Region will
  read the resulting conflict as a failure.

## Prerequisites

- **The AWS Region**, confirmed with the customer rather than inferred.
- **For an Identity Center Domain**, the instance ARN and its **primary Region**.
  The Domain must be created in that Region.
- **`iam:PassRole`** on the space access role, for whoever creates the Space.
  Without it the create fails after the role already exists.

**Region rules differ by provider, and the difference matters:**

- An **IAM-only Domain** supports Spaces in Regions other than the Domain's.
- An **Identity Center Domain** requires the Space in the **same Region** as the
  Domain. This is not relaxable.
- If the customer needs Identity Center *and* Spaces in more than one Region, the
  **org-scoped Domain** is the way to do it — see `references/cloudwatch-omni/org-domains.md`.

Never answer "yes, Spaces can be in other Regions" without naming which provider
that holds for. It is true for IAM-only and false for account-scoped Identity
Center.

**Constraints:**

- You MUST NOT promise a cross-Region Space under an account-scoped Identity
  Center Domain. If the customer needs Identity Center together with Spaces in
  more than one Region, the org-scoped Domain path supports that — see
  `references/cloudwatch-omni/org-domains.md`.

### Operations you will call

Every operation runs through the `aws___call_aws` tool as an `aws <service>
<operation>` CLI command — the service name in kebab-case, the operation in
kebab-case, and each input-shape member passed as a `--kebab-key` flag. Policy
documents appear below as standalone JSON blocks — pass each as the corresponding
flag value (`--assume-role-policy-document`).

**`aws cloudwatchomni` operations:**

| Intent | Command |
|---|---|
| Check whether a Domain already exists | `aws cloudwatchomni list-domains` |
| Create the Domain | `aws cloudwatchomni create-domain` |
| Read the Domain back | `aws cloudwatchomni get-domain` |
| Check whether a Space already exists | `aws cloudwatchomni list-spaces` |
| Create the Space | `aws cloudwatchomni create-space` |
| Read the Space back | `aws cloudwatchomni get-space` |
| Delete the Space | `aws cloudwatchomni delete-space` |
| Delete the Domain | `aws cloudwatchomni delete-domain` |

**`aws iam` operations:**

| Intent | Command |
|---|---|
| Create the space access role | `aws iam create-role` |
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
| Confirm the calling identity | `aws sts get-caller-identity` |

Report the caller identity before starting:

```
aws___call_aws → aws sts get-caller-identity
```

## Step 1 — Interview the customer first

Ask these in one message and wait for answers. Do not ask piecemeal, and do not
default silently.

1. **Region?**
2. **Domain name?** It becomes part of the endpoint URL. Lowercase letters, digits,
   and single hyphens between them; 3–63 characters.
3. **Authorization provider** — IAM, Identity Center, or both?
4. **If Identity Center:** the instance ARN, and confirmation that the Region from
   question 1 is that instance's primary Region.
5. **Space name?** Same character rules as the domain name; 3–64 characters.
6. **Space access role** — should the agent **create a new role** with the correct
   trust policy and managed policies, or will the customer **supply an existing
   role ARN**? Recommend creating one.
7. **AgentCore evaluation role ARN?** `create-space` requires this as well as the
   space access role, and the agent cannot create it. Ask for an existing ARN, or
   offer to look for a reusable one — see Step 3.
8. **Encryption** — service-owned, or a customer managed KMS key? If a customer
   managed key, the key ARN. It must be a symmetric `ENCRYPT_DECRYPT` key in the
   caller's account and Region, and its **key policy** must allow
   `cloudwatch.amazonaws.com` to perform `kms:Decrypt` and `kms:GenerateDataKey`.

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

- You SHOULD recommend creating the role rather than reusing one. The Space cannot
  function correctly unless the role's trust policy and permissions are right, and
  a purpose-built role is easier to verify and to clean up.
- You MUST confirm the key policy grants both KMS actions before offering
  customer managed encryption. A key the service cannot use produces a Space that
  cannot write.

## Step 2 — Create the Domain

### Check whether a Domain already exists first

**One Domain per account.** A second `create-domain` in the same account
conflicts, so check before creating and tell the customer the limit.

```
aws___call_aws → aws cloudwatchomni list-domains
```

If a Domain comes back, do NOT create another. Report the existing Domain to the
customer — its name and ID from the summary, and its endpoint URL from
`get-domain --domain-id <id>` (summaries do not carry it) — and confirm they want to use it. On
confirmation, take its `domainId` and continue from Step 3.

**Constraints:**

- You MUST run this check before `create-domain`.
- You MUST state the one-Domain-per-account limit to the customer as part of this
  step, not only when the check finds one. A customer who does not know the limit
  reads the resulting conflict as a failure.
- You MUST confirm with the customer before reusing an existing Domain. It may
  belong to someone else in the account, and its authorization provider may not be
  the one they asked for.
- If the check cannot be completed — access denied, or an ambiguous response — you
  MUST treat the result as **inconclusive, not negative**. Report that and stop.
  You MUST NOT create a Domain on that basis.

### Create it

For an **IAM-only** Domain there is no extra configuration:

```
aws___call_aws → aws cloudwatchomni create-domain --name <domain-name> --identity-providers IAM
```

For an **Identity Center** Domain, `identityProviderConfiguration` becomes
required and carries the instance ARN. The Domain must be created in the
instance's primary Region, which the service verifies:

```
aws___call_aws → aws cloudwatchomni create-domain --name <domain-name> --identity-providers IAM IDC --identity-provider-configuration '{"identityCenterConfiguration": {"identityCenterInstanceArn": "<idc-instance-arn>"}}'
```

If the customer does not have the Identity Center instance ARN to hand, do not leave
`<idc-instance-arn>` as a placeholder for them to fill — offer to look it up with
`list-instances` on `sso-admin` (see [Step 1](#step-1--interview-the-customer-first)),
which returns each instance's ARN and identity store ID.

Capture `domainId`, `domainArn`, and `domainEndpointUrl` from the `domain` object
in the response. `domainId` is the input to `create-space` in Step 4.

**Constraints:**

- You MUST create an Identity Center Domain in the instance's **primary** Region.
  Creating it elsewhere is rejected, and the rejection describes the Region rather
  than the mistake.
- `identityProviders` accepts one or two values from `IAM` and `IDC`, and they must
  be distinct. You MUST NOT send a repeated value.
- You MUST capture `domainEndpointUrl` and give it to the customer. It is how they
  reach Omni, and it is not derivable from the domain name alone.
- If the customer does not have the Identity Center instance ARN, You SHOULD offer to
  look it up with `list-instances` on `sso-admin` rather than leaving
  `<idc-instance-arn>` for them to resolve.

## Step 3 — Create the space access role

Only if the customer chose "create a new role" in Step 1. If they supplied an
existing role ARN, do NOT modify it — pass it straight through to Step 4 and, if
the create fails, use the [Troubleshooting](#troubleshooting) table rather than
editing their role.

This is the role the service assumes to operate on the Space.

**Constraints:**

- You SHOULD run the `list-spaces` check from [Step 4](#step-4--create-the-space)
  before creating a role. If a Space already exists in the target Region, no role
  is needed, and creating one leaves an unused IAM role behind.

### Create the role

Call `create-role` with `AssumeRolePolicyDocument` set to this trust policy. The
`aws:SourceAccount` and `aws:SourceArn` conditions are confused-deputy
protection — keep both.

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
          "aws:SourceAccount": "<account-id>"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:cloudwatch:*:<account-id>:space/*"
        }
      }
    }
  ]
}
```

```
aws___call_aws → aws iam create-role --role-name <role-name> --assume-role-policy-document <trust-policy-json>
```

**Constraints:**

- All three `sts` actions are required. `sts:TagSession` and `sts:SetContext` carry
  the session context the Space needs; a role trusted for `sts:AssumeRole` alone
  is accepted at create time and fails later when the Space is used.
- The `aws:SourceArn` pattern MUST stay wildcarded across Region and space ID
  (`space/*`). The space ID does not exist yet when the role is created, so a
  narrower pattern cannot match.
- You MUST create the role in the same account as the caller. `create-space`
  rejects a `dataAccessRoleArn` from another account.

### Attach the managed policies

Attach both with the IAM `attach-role-policy` operation. Do not write an inline
policy instead, and do not substitute a `*FullAccess` policy — the Space's
permissions are defined by these two managed policies and nothing else. If the role
was supplied by the customer rather than created here, ask before attaching anything
to it.

```
aws___call_aws → aws iam attach-role-policy --role-name <role-name> --policy-arn arn:aws:iam::aws:policy/CloudWatchOmniSpaceAccessPolicy

aws___call_aws → aws iam attach-role-policy --role-name <role-name> --policy-arn arn:aws:iam::aws:policy/CloudWatchOmniAgentObservabilityPolicy
```

**Constraints:**

- You MUST NOT substitute a `*FullAccess` policy or hand-write a broad inline
  policy. The Space's permissions are defined by these managed policies.
- You MUST NOT attach these policies to a role the customer supplied without
  asking. They may be reusing it, and widening someone else's role is not yours
  to do.

### Also resolve the AgentCore evaluation role

`create-space` requires a **second** role ARN, `agentCoreEvaluationRoleArn`, which is
not the space access role and is not created here. Resolve it now rather than at the
call:

1. **Reuse an existing role.** List roles and offer any whose name starts with
   `AgentCoreEvaluationRole` or `AgentCoreEvalRole`, or whose trust policy principal
   is `bedrock-agentcore.amazonaws.com`. An account already running evaluations
   usually has one — show the matches and let the customer pick.

```
aws___call_aws → aws iam list-roles
```

1. **Otherwise have the customer create one** — the AgentCore Evaluations console
   ("Create and use a new service role") or the AgentCore CLI/SDK
   (`auto_create_execution_role=True`) — then use the ARN it returns.

**Constraints:**

- You MUST have both role ARNs before calling `create-space`. Omitting either is
  rejected by the client before the request is sent.
- You MUST NOT hardcode this role's IAM policy. The console and CLI build the
  authoritative policy on creation.
- You MUST NOT attach the Space's managed policies to it. It is a different role
  with a different trust principal.

**When the customer asks what this role is** — typically because `create-space` just
asked them for it mid-setup — answer with all of the following, because each one
changes what they do next: it is a **second, separate** role from the space access
role and is not created as part of Space setup; offer to **reuse** one first by
listing roles and surfacing matches on the name prefixes or the
`bedrock-agentcore.amazonaws.com` trust principal, so they can pick; otherwise they
create it through the AgentCore Evaluations console's new-service-role option or the
AgentCore CLI/SDK auto-create option and bring back the ARN; **both** role ARNs must
be in hand before `create-space`, since omitting either is rejected by the client
before any request is sent; you will **not** hand-write its IAM policy (the console
and CLI build the authoritative one); and you will **not** attach the Space's managed
policies to it, because it is a different role with a different trust principal.

## Step 4 — Create the Space

### Check whether a Space already exists first

**One Space per account per Region.** A second Space in the same Region
conflicts; a Space in a different Region is a different Space. Check before
creating, scope the check to the target Region, and tell the customer the limit.

```
aws___call_aws → aws cloudwatchomni list-spaces --domain-id <domain-id>
```

If a Space already exists in the target Region, do NOT create another. Report it
to the customer — its name, ID, and Region — and confirm they want to use it.

**Constraints:**

- You MUST run this check before `create-space`.
- You MUST state the one-Space-per-account-per-Region limit to the customer as
  part of this step. It is what determines whether they need a Space in more than
  one Region.
- A Space in a different Region is a different Space and does not conflict. You
  MUST compare Regions rather than treating any returned Space as a conflict.
- If the check cannot be completed, you MUST treat the result as **inconclusive,
  not negative**, report that, and stop.

### Create it

> **`create-space` takes TWO required role ARNs, not one.** Alongside
> `--data-access-role-arn` it requires `--agent-core-evaluation-role-arn`. Both must be
> in the caller's account, and omitting either is rejected by the client before the
> request is sent. If you do not already have both from Step 1 and Step 3, resolve the
> AgentCore evaluation role there before calling.

```
aws___call_aws → aws cloudwatchomni create-space --name <space-name> --domain-id <domain-id> \
  --data-access-role-arn arn:aws:iam::<account-id>:role/<role-name> \
  --agent-core-evaluation-role-arn arn:aws:iam::<account-id>:role/<agentcore-eval-role-name>
```

`--domain-id` accepts the Domain's ID, its name, or its ARN.

For **customer managed encryption**, add `encryptionConfiguration`:

```
"encryptionConfiguration": {"encryptionStrategy": "CUSTOMER_MANAGED", "kmsKeyArn": "<kms-key-arn>"}
```

Omit `encryptionConfiguration` entirely for service-owned encryption; that is
equivalent to `"encryptionStrategy": "AWS_OWNED"`.

The customer managed key's key policy must allow the service to use it. This
statement belongs on the **key**, not on the space access role:

```json
{
  "Effect": "Allow",
  "Principal": {
    "Service": "cloudwatch.amazonaws.com"
  },
  "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
  "Resource": "*"
}
```

Capture `spaceId`, `spaceArn`, `region`, and `status` from the `space` object in
the response.

> **A successful create does not mean the role works.** `create-space` checks only
> that `dataAccessRoleArn` is present and in the caller's account — it never tries to
> assume it. A role with a wrong trust policy produces a Space that is created
> successfully and fails the moment anything uses it.

**Constraints:**

- You MUST use `encryptionConfiguration`; it is the only create-time encryption
  input. `create-space` has no top-level `kmsKeyArn` member (the CLI has no
  `--kms-key-arn` flag). There is no top-level `kmsKeyArn` on read either:
  `get-space` always reports `encryptionConfiguration`, and `list-spaces` summaries
  carry no encryption fields at all.
- A customer managed key MUST be a symmetric `ENCRYPT_DECRYPT` key in the caller's
  account and Region.
- You MUST NOT author or modify the KMS key policy yourself. Show the customer the
  statement above and direct them to whoever administers the key.
- `create-space` does not verify that the role can actually be assumed. It checks
  only that the ARN is present and in the caller's account, so a role with a wrong
  trust policy creates a Space that fails in use. You MUST NOT treat a successful
  create as proof the role is correct — verify per the next section.

## Verifying the setup

Read both resources back rather than trusting the create responses:

```
aws___call_aws → aws cloudwatchomni get-domain --domain-id <domain-id>

aws___call_aws → aws cloudwatchomni get-space --space-id <space-id>
```

Confirm the Domain reports the expected endpoint URL, and the Space reports
`ACTIVE` in the expected Region with the role ARN you passed.

Then report to the customer, in one line: the domain endpoint URL, the space ID,
and the Region.

**Constraints:**

- You MUST NOT begin dependent setup — such as telemetry forwarding — until the
  Space reports `ACTIVE`.

## Cleanup

> **Before any delete step, in every answer from this section:** say plainly that
> deleting a Space destroys its telemetry and the deletion cannot be undone, and ask
> the customer to confirm before you run anything. State this first, ahead of the
> ordering and the API details — an answer that gets the order right but never warns
> the customer is wrong.

**Confirm with the customer before running anything in this section.** Deleting a
Space is destructive and its telemetry goes with it.

Order matters. Delete the Space first.

1. **Confirm first, then delete the Space.** Deleting a Space is destructive: the
   Space's telemetry goes with it and cannot be recovered. Get the customer's
   explicit confirmation before running this call.

   ```
   aws___call_aws → aws cloudwatchomni delete-space --space-id <space-id>
   ```

2. Delete the Domain. This fails while any Space still exists under it:

   ```
   aws___call_aws → aws cloudwatchomni delete-domain --domain-id <domain-id>
   ```

3. The space access role — branch on who created it:
   - **The agent created it in Step 3:** detach both managed policies with
     `detach-role-policy`, then `delete-role`. A role with policies attached
     cannot be deleted.
   - **The customer supplied it:** do NOT delete or modify it. Tell them the Space
     is gone and the role is untouched.

**Constraints:**

- You MUST delete Spaces before the Domain. `delete-domain` returns a conflict
  naming the number of remaining Spaces, and the fix is always to delete those
  first — never to retry the Domain delete.
- Deleting a Space is destructive. You MUST confirm with the customer first and
  say plainly that the Space's telemetry goes with it.
- You MUST NOT poll `get-space` after `delete-space` to confirm removal. Once
  delete returns success the Space is gone, and a follow-up read can fail in ways
  that look like the delete did not work.

## Troubleshooting

**Rule:** When a call returns an error, surface the error code and message
**verbatim**, then map to the mitigation below. Do NOT invent error text, do NOT
paraphrase what the service returned, and do NOT synthesize a mitigation for an
error that is not listed.

| Error signal | Cause | Mitigation to surface |
|---|---|---|
| `ConflictException` on `create-domain` | A Domain already exists in this account, or an org Domain covers it | Read it with `list-domains`, confirm with the customer, and continue from Step 3. Do NOT retry the create |
| `ConflictException` on `create-space` | A Space already exists in this account and Region | Read it with `list-spaces` and compare Regions. A different Region is a different Space |
| `ValidationException` naming the Region on `create-domain` | Identity Center Domain not being created in the instance's primary Region | Ask the customer for the instance's primary Region and create the Domain there. `list-instances` on `sso-admin` shows the instances they can reach |
| `ValidationException` on `create-space` naming the Domain's Region | Space Region differs from the Domain's, and the Domain uses Identity Center | Create the Space in the Domain's Region. If the customer needs Identity Center across several Regions, the org-scoped Domain path supports that |
| `ValidationException` that `dataAccessRoleArn` must be in the caller's account | Role ARN belongs to a different account | Ask the customer for a role in this account; do NOT attempt a cross-account role |
| `ParamValidationError` naming a missing required parameter on `create-space` | `agentCoreEvaluationRoleArn` (or `dataAccessRoleArn`) was omitted — both are required and the client rejects the call before sending | Resolve the AgentCore evaluation role as described in Step 4 and pass both ARNs |
| `ValidationException` on `encryptionConfiguration` | `encryptionStrategy` and `kmsKeyArn` inside `encryptionConfiguration` do not agree | Send the key ARN nested inside `encryptionConfiguration` only with `encryptionStrategy` `CUSTOMER_MANAGED`; omit the block entirely for `AWS_OWNED` |
| `AccessDeniedException` naming `iam:PassRole` | Caller may create the Space but cannot pass the role | Ask the customer to add `iam:PassRole` on that specific role ARN to their calling identity |
| `AccessDeniedException` on the operation itself | Caller lacks `cloudwatch:CreateDomain` or `cloudwatch:CreateSpace` | Ask the customer to add the specific action to their calling role |
| `ResourceNotFoundException` on `create-space` | `domainId` typo, or the Domain is in another account or Region | Re-read the Domain with `list-domains` and use the exact `domainId` |
| `ConflictException` on `delete-domain` naming remaining Spaces | Spaces still exist under the Domain | Delete every Space first, then retry. Do NOT retry the Domain delete on its own |

If the error does not match a row above, quote it verbatim, say it is unmapped,
and ask the customer how to proceed.

### If the Space was created but cannot be used

An authorization error *after* a successful `create-space` almost always means the
space access role's trust policy is wrong, not that access is missing.

`create-space` validates only that `dataAccessRoleArn` is non-blank and in the
caller's account. It never attempts to assume the role, so a role missing
`sts:TagSession` or `sts:SetContext`, naming the wrong service principal, or carrying
condition keys that do not match is accepted at create time and fails in use. Note
the asymmetry: the organization path *does* verify its role by performing a real
`sts:AssumeRole` at create time, so a reader who did that flow first will reasonably
expect this one to validate too.

**Telling this apart from a missing grant** is a matter of timing:

- The Space **was created and then failed in use** — suspect the role's trust policy.
  Check the service principal, all three `sts` actions, and both condition keys.
- **Nobody could ever reach the Space**, from the start, for everyone — suspect
  missing access grants. See `references/cloudwatch-omni/access-grants.md`.

You MUST check the trust policy before proposing new grants. Creating a grant to fix a
trust-policy problem leaves the customer with the same error and two things to unwind.

**What to check on the space access role**, against the trust policy in
[Step 3](#step-3--create-the-space-access-role):

1. The principal is the service, `cloudwatch.amazonaws.com` — not an account or a
   user.
2. All three actions are allowed: `sts:AssumeRole`, `sts:TagSession`, and
   `sts:SetContext`. A role trusted for `sts:AssumeRole` alone is the classic case:
   accepted at create time, denied the first time the Space assumes it.
3. Both confused-deputy conditions are present and match: `aws:SourceAccount` equal
   to the account, and `aws:SourceArn` matched with `ArnLike` against
   `arn:aws:cloudwatch:*:<account-id>:space/*` — Region and space ID **wildcarded**.
   A condition that spells out the space ID cannot have been right when the role was
   created, because the ID did not exist yet; a condition pinned to one Region breaks
   the moment a Space is created elsewhere.

Then **read the Space back** with `get-space` and confirm it reports `ACTIVE` with the
role ARN you expect. A successful `create-space` response is not evidence the role is
correct — the create never exercised it — so the read-back after the fix is the check.

**Do not recreate the Space as the first remedy.** The role is what is wrong; a new
Space created with the same role fails the same way, and if telemetry has started
arriving the delete is destructive. Fix the trust policy on the existing role instead.

### Expectations that look like faults

- **`create-space` succeeded but using the Space fails with an authorization
  error.** The create does not verify the role is assumable. Check the trust
  policy's principal, all three `sts` actions, and both condition keys.
- **A Space encrypted with a customer managed key cannot write.** The key policy
  does not allow `cloudwatch.amazonaws.com` the required KMS actions. Nothing about
  the Space or the role is wrong.
- **A second Space in the same Region conflicts.** One Space per account per
  Region. This is the quota, not an error in the request.

## Security considerations

- Keep both `aws:SourceAccount` and `aws:SourceArn` conditions on the space access
  role's trust policy. They are the confused-deputy protection.
- The `aws:SourceArn` wildcard covers Region and space ID because neither is known
  when the role is created. Do not widen it further — the account ID and the
  `space/` resource type MUST stay pinned.
- If the customer supplied the role, attach only these two managed policies and change
  nothing else about its existing permissions.
- Do not attach `*FullAccess` policies to the space access role. Its permissions
  come from the Omni managed policies and nothing else.
- A Space encrypted with a customer managed key needs the key policy to grant the
  service `kms:Decrypt` and `kms:GenerateDataKey`. Do not author or modify the key
  policy; if it needs changing, direct the customer to their key administrator.
- Access to query a Space is granted separately through access grants and access
  profiles, so read access can be given without the ability to change the Space.

## Additional resources

- `references/cloudwatch-omni/org-domains.md` — Domains shared across an AWS Organization
- `references/cloudwatch-omni/instrumentation/collector.md` — deploying a collector that exports to
  CloudWatch's OTLP endpoints, for telemetry not yet reaching CloudWatch
- `references/cloudwatch-omni/data-forwarding-and-centralization.md` — forwarding telemetry that is
  already in CloudWatch log groups into the Dataset
