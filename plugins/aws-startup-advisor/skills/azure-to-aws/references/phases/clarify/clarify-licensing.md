---
_fragment: licensing
_of_phase: clarify
_contributes:
  - preferences.json (licensing section)
---

# Clarify — Licensing

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing.** It returns rows; `clarify-assemble.md` presents them.

Category I, and **conditional** — it is the only Clarify fragment that can legitimately not
load. Azure's analogue of nothing in gcp or heroku: neither has a Windows-licensing story,
because neither has Azure's Windows install base.

## Firing rule

Loads when **any** of these is true:

- a `Microsoft.Compute/virtualMachines` or `virtualMachineScaleSets` entry has
  `os_type: "Windows"`, or an `image_publisher` of `MicrosoftWindowsServer`
- the inventory contains **any** `Microsoft.Sql/*` resource
- a VM's image signature indicates SQL Server on the guest — `image_publisher` of
  `MicrosoftSQLServer`, or an offer/sku naming a SQL Server edition

**When it does not fire, `licensing` is written as `N/A` — explicitly, never omitted**
(`clarify-assemble.md` rule 3). An absent key and a considered `N/A` are different facts:
_"we checked your estate for Windows and SQL licensing exposure and found none"_ is a real
statement, and silence is not.

## Step 1: Extract

| Read                                                                | Resolves                                                   |
| ------------------------------------------------------------------- | ---------------------------------------------------------- |
| every VM's `os_type`, `image_publisher`, `image_offer`, `image_sku` | which VMs are Windows, and which carry SQL Server          |
| VM `size` (vCPU count)                                              | the licensing unit — Windows and SQL are licensed per core |
| any `Microsoft.Sql/*` presence                                      | whether the SQL question fires independently of any VM     |

## Step 2: The rows

### Q-I1 — Windows licensing model — **ESSENTIAL**

**Disposition:** ESSENTIAL. **No default.**

```
How do you want to license Windows Server on AWS?

[A] License Included — the licence is bundled into the EC2 hourly rate.
    Simplest, no compliance tracking, no commitment.
[B] Bring Your Own Licence via Dedicated Hosts — reuses licences you
    already own, requires Software Assurance and dedicated tenancy.
```

There is no default because the two are **not variations on a price** — they are different
infrastructure. BYOL requires Dedicated Hosts, which changes tenancy, placement, instance
sizing granularity, and the minimum commitment. Defaulting either way would silently pick
an architecture.

**Feed the row with the extracted core count**, because that is what makes the question
answerable: _"4 Windows VMs, 14 vCPUs total"_ lets someone judge whether their existing
licences cover it. A bare question does not.

**Do not do the licence-cost arithmetic.** Core minimums, Software Assurance eligibility,
and Azure Hybrid Benefit portability are genuinely complicated, and this skill is
startup-weighted — it detects and warns rather than modelling. Estimate renders a single
licensing **delta** line, not a licence cost model.

### Q-I2 — SQL Server licensing — **ESSENTIAL when SQL is on a VM**

**Disposition:** ESSENTIAL when a SQL-Server-on-VM signature was found; **N/A** when the
only SQL is PaaS (`Microsoft.Sql/servers/databases` → RDS SQL Server, where the licence is
in the RDS rate).

```
Your vm-contoso-sql runs SQL Server on the guest.

[A] License Included on RDS SQL Server — if the database can move to
    a managed service
[B] BYOL on EC2 — keeps the current topology, including anything RDS
    does not support
```

**Note the split output.** The VM still maps to EC2 through `compute.md`; it is the
**SQL workload on it** that gets a `deferred[]` entry from the specialist gate. Deferring
the whole VM would drop a real compute line from the estimate and make the total quietly
too low.

### Azure Hybrid Benefit — a finding, not a question

If the inventory shows AHUB in use, record it as a finding: the benefit is
Azure-specific and **does not travel**. The customer is currently paying a reduced Azure
rate that has no AWS equivalent, so the honest comparison is against the _unreduced_ rate.
Getting this wrong makes AWS look worse than it is, and is the sort of error that is
noticed.

## Hard blocker — Azure Edition Windows Server

**Not a question. A statement.**

```
BLOCKER — vm-contoso-reporting

Its image is 2022-datacenter-azure-edition. AWS Application Migration
Service refuses an Azure Edition Windows Server image: it carries
Azure-specific platform integration (Hotpatch, SMB over QUIC, Azure
Extended Networking) and must be re-imaged to a standard Windows Server
edition before replication can start.

This is not a licensing choice. It is a prerequisite.
```

Presented as a `severity: "blocker"` warning, and it also suppresses option [A] on
`clarify-compute.md`'s Q-C6 for that VM. There is nothing to weigh, so offering a choice
would imply one of the answers works.

## Step 3: Rows returned

```jsonc
"licensing": {
  "windows_model": { "disposition": "ESSENTIAL", "value": null, "default": null,
                     "context": "4 Windows VMs, 14 vCPUs total" },
  "sql_model":     { "disposition": "N/A", "value": null, "default": null },
  "ahub_in_use":   { "disposition": "DETECTED", "value": false, "default": false },
  "blockers":      [ { "azure_id": "<azure_id>", "code": "azure_edition_windows_server" } ]
}
```

When the fragment does not fire at all, the assembler writes:

```jsonc
"licensing": { "disposition": "N/A", "value": null, "default": null,
               "reason": "no Windows VM image, no Microsoft.Sql/* resource, and no SQL-on-VM signature in the inventory" }
```

## Who consumes these

| Row             | Consumer                                                                                                          |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| `windows_model` | Estimate's licensing delta line; Generate's tenancy and placement config                                          |
| `sql_model`     | `specialist-gates.md`'s SQL-on-VM gate, which emits **two** entries — EC2 for the host, deferred for the database |
| `ahub_in_use`   | Estimate's baseline — the Azure side must be compared at the unreduced rate                                       |
| `blockers`      | the report, and `compute.md`'s Q-C6 option suppression                                                            |

## Status — build step 5

Implemented as detection-and-warn. Deliberately **not** implemented, per plan §7's
explicitly-not-ported list: AHUB core-minimum arithmetic, Software Assurance eligibility
rules, and elastic-pool licence bin-packing. Those are enterprise-weighted and belong with
a specialist, and a half-modelled licence calculation is worse than an honest delta line.

## `_fired` and `_firing_reason` are REQUIRED

This is the only Clarify fragment that can legitimately not load, so the artifact has to
record which happened and why. Two keys on the `licensing` object, always:

```jsonc
"licensing": {
  "_fired": true,
  "_firing_reason": "one Windows VM (azurerm_windows_virtual_machine.reporting, image_publisher MicrosoftWindowsServer). No Microsoft.Sql/* resource is present, which is why sql_model is N/A while the category still fires.",
  ...
}
```

- **`_fired`** — `true` when the firing rule matched, `false` when it did not. Never absent.
- **`_firing_reason`** — names the specific resource or resources that triggered it, or, when
  `_fired` is `false`, states what was looked for and not found.

**Why required rather than nice-to-have.** "The category did not fire" and "the category
fired and the fragment forgot to write it down" produce the same artifact otherwise, and the
first is correct while the second silently drops a licensing decision worth real money. It is
also the only thing that lets a user see **why** they are being asked about Windows
licensing — without it the question arrives with no context and the obvious response is to
guess.

An N/A category is written out with its reason, never omitted.
