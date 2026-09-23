---
_fragment: identity
_of_phase: clarify
_contributes:
  - preferences.json (identity section)
---

# Clarify — Identity

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing.** It returns rows; `clarify-assemble.md` presents them.

Category J, and it **always fires** — every Azure estate has an Entra ID tenant behind it,
even when no identity resource appears in the inventory. That is exactly why the category is
unconditional: absence of `Microsoft.ManagedIdentity/*` resources means the workloads use
keys, not that there is no identity story.

**One shallow question.** Human identity migration is a large topic and this is a
startup-weighted skill, so the row establishes a direction and stops.

## Two different things called "identity"

Keeping these apart is the whole reason this fragment is small:

|                                                                                              | Where it lives                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Workload identity** — managed identities, role assignments, what an app is allowed to read | already handled without a question. `Microsoft.ManagedIdentity/userAssignedIdentities` → IAM Role is a fast-path row; `roleAssignments` is a Skip Mapping because IAM policy is _authored_ against the AWS design rather than translated |
| **Human identity** — who logs in, from where, with what MFA                                  | **this fragment**, and it is not a resource mapping at all                                                                                                                                                                               |

A one-to-one translation of Azure RBAC would encode Azure's scope hierarchy
(management group → subscription → resource group → resource) into IAM, which has no such
nesting. That is why the workload half is deliberately not a question.

## Step 1: Extract

| Read                                                        | Resolves                                                 |
| ----------------------------------------------------------- | -------------------------------------------------------- |
| count of `Microsoft.ManagedIdentity/userAssignedIdentities` | how much workload identity exists, for the row's context |
| presence of `Microsoft.Authorization/roleAssignments`       | whether RBAC is in active use                            |
| presence of `Microsoft.KeyVault/vaults`                     | whether secrets are already centralised                  |

None of these change the answer. They make the row's context line concrete.

## Step 2: The row

### Q-J1 — Human identity approach

**Disposition:** PROPOSED. **Default:** `identity_center_reinvite`.

```
How should people sign in to AWS?

[A] Fresh start with IAM Identity Center — create users and groups
    in AWS and re-invite your team                              (default)
[B] Federate with Entra ID — keep Entra as the identity provider
    and use it for AWS sign-in via SAML or OIDC
```

**Consequence line:** _Assuming a fresh IAM Identity Center directory → the simplest path,
and no dependency on Azure after cutover. Choose federation if you are keeping Entra ID for
other reasons, such as Microsoft 365._

**Why [A] is the default rather than [B].** Federation is the more sophisticated answer and
the wrong assumption here. Defaulting to it would mean the migration **retains a dependency
on the cloud the customer is leaving** — the exit is not an exit if AWS sign-in breaks when
the Entra tenant lapses. A team keeping Microsoft 365 has a real reason to federate, and
that is precisely the sort of reason only they know.

For a startup-sized team, re-inviting people to a fresh directory is usually hours of work.
Say that in the row so [A] does not read as a cop-out.

## Step 3: Rows returned

```jsonc
"identity": {
  "disposition": "PROPOSED",
  "value": null,
  "default": "identity_center_reinvite",
  "context": "3 user-assigned managed identities, 0 role assignments, 1 Key Vault in the inventory"
}
```

## Who consumes this

| Row        | Consumer                                                                                                 |
| ---------- | -------------------------------------------------------------------------------------------------------- |
| `identity` | `design-refs/identity.md` (build step 5, not yet written) and Generate's IAM Identity Center scaffolding |

`identity.md` is still missing, and `index.md` routes one type to it. That is a real gap
rather than a decision: this row is currently recorded and not yet consumed by any rubric.
Note it on the sheet as recorded-for-later rather than implying it shapes the design today.

## What this fragment deliberately does not ask

Each of these is a genuine question that a real migration has to answer, and each is out of
scope for a startup-weighted skill. Listing them is the honest alternative to pretending
one shallow row covers identity:

- conditional access policy translation
- MFA enrolment strategy
- guest / B2B user handling
- privileged-access review, or anything resembling PIM
- SCIM provisioning and directory sync

If the estate shows heavy Entra investment — many role assignments, custom role
definitions, several app registrations — say on the sheet that identity migration is likely
to need its own workstream. That is a more useful thing to tell someone than a fourth
question they cannot answer here.

## Status — build step 5

Implemented. Sourced from `architect-for-startups/references/migration-azure-to-aws.md`,
which keeps the pre-decision advisory conversation while this skill handles real migration
intent.
