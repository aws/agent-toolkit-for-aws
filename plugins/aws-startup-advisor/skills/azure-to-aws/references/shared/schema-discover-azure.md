# Schema — Azure discovery artifacts

Contract for the two artifacts the discover phase produces. `discover-assemble.md` is
their single creator and owns the validation checklist at the bottom.

## `azure-resource-inventory.json`

```jsonc
{
  "phase": "discover",
  "metadata": {
    "discovery_timestamp": "<ISO 8601>",
    "discovery_sources": ["terraform"], // only sources that CONTRIBUTED, never merely ran
    "subscriptions_discovered": ["<subscription id>"],
    "total_resources": 0,
    "confidence": "inferred" // deterministic | measured | inferred | billing_inferred
  },
  "resources": [
    {
      "azure_id": "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/serverfarms/<name>",
      "azure_type": "Microsoft.Web/serverfarms", // canonical ARM type; never azurerm_*
      "azure_type_provenance": "table", // REQUIRED — table | derived | derived_uncorroborated | user_confirmed
      "name": "<name>",
      "resource_group": "<rg>",
      "subscription_id": "<sub>",
      "location": "<azure region>",
      "source": "terraform", // terraform | bicep | arm | live | rdfa | billing (or a "+"-joined set)
      "config": {}, // per-type; NAMES only for app settings, connection strings, Key Vault entries
      "tags": {},
      "edges": [], // see § Typed edges
      "drift": [] // see § Drift records
    }
  ],
  "iac_metadata": {}, // present only when a dialect actually contributed
  "warnings": [], // see § Warnings — ALWAYS present, `[]` when clean
  "unclustered": [] // azure_ids no cluster claimed
}
```

`azure_id` is the artifact's primary key and its stable address. It is preferred over
a Terraform address because it embeds the subscription and the resource group, so one
field supplies the cluster seed key, the environment scope, and uniqueness with no
derivation. Only Terraform-sourced resources need it reconstructed; Bicep, ARM, live
`az`, and RDfA all supply it.

### Typed edges

Each edge is `{ "type": "<edge type>", "to": "<azure_id>", "via": "<property>" }`.
Azure embeds full ARM resource IDs inside resource _properties_, so edges survive
every discovery source — unlike GCP, where the graph comes from Terraform reference
expressions and therefore exists only when IaC does.

| Edge type           | Signal                                                                                          | Why it matters                                                                                                                                                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hosted_on`         | `serverFarmId` on a web app → App Service Plan                                                  | hard edge; also what fixes the plan cost trap                                                                                                                                                                                          |
| `network`           | `subnetId` / `virtualNetworkSubnetId`                                                           | VNet colocation                                                                                                                                                                                                                        |
| `private_link`      | private endpoint → the resource it fronts                                                       | explicit app-to-data edge                                                                                                                                                                                                              |
| `secret_ref`        | Key Vault reference in app settings                                                             | secret dependency                                                                                                                                                                                                                      |
| `data_ref`          | a compute resource's config referencing a data resource's `fqdn` / `hostname` / `endpoint` / id | **the app-to-data edge** — the commonest real form is an app setting interpolating a database or cache address. It is what merges an app and its database when they sit in different resource groups, so dropping it defeats the merge |
| `identity_grant`    | managed identity + role-assignment scope                                                        | "app X reads storage Y"                                                                                                                                                                                                                |
| `declared_affinity` | `app=` / `workload=` tags                                                                       | declared intent, when present                                                                                                                                                                                                          |

This table is the **canonical** edge vocabulary. A per-dialect ref (e.g.
`extract-terraform.md` § Edges) maps its own surface syntax onto these types and must
not introduce a type that is absent here.

**Two relationships that are deliberately NOT edges:**

- **Containment.** A child resource's link to its parent needs no edge, because an ARM
  `azure_id` _contains_ its parent's as a literal prefix —
  `…/storageAccounts/assets/fileServices/default/shares/reports` yields the parent
  account by truncation, for every source and with no extraction step. `resource_group`
  inheritance (see `extract-terraform.md` step 3) covers the clustering need. Adding a
  containment edge would restate derivable information and give a second thing to keep
  in sync.
- **Observability links.** An Application Insights component's `workspace_id`, and
  diagnostic-setting targets, point at resources that are all Skip Mappings, so no
  design decision consumes the link. They belong in `config` (where the report reads
  them), not in `edges[]` — an edge implies a dependency the architecture has to
  preserve, and this one does not survive the migration at all.

### Drift records

`{ "field": "<path>", "values": [{ "source": "terraform", "value": ... }, { "source": "live", "value": ... }], "won": "live" }`

A disagreement between sources is **never** silently reconciled. Both values are kept
with their sources and the winner recorded, so the report can say "your Terraform
declares `Standard_D2s_v3`, your tenant is running `Standard_D4s_v3`". Drift the
customer did not know they had is a deliverable, not a nuisance.

## `azure_type_provenance`

**REQUIRED on every `resources[]` entry.** How the canonical type was resolved:

| Value                    | Means                                                                                                                                                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `table`                  | A row in `arm-type-canonicalization.md`. Authoritative                                                                                                                                                                      |
| `derived`                | Not listed, so derived per that file's § Deriving a type that is not listed, and the namespace **is** declared in `fast-path-services.json` → `namespace_routing` — a second artefact agreed                                |
| `derived_uncorroborated` | Derived the same way, but the namespace is **not** in that list. Still a valid entry: the cross-check is a signal, not a veto. Design routes it to a model-chosen category. Carries a `type_derived_uncorroborated` warning |
| `user_confirmed`         | A derived or unresolvable type the user confirmed (the `confirm` phase, once it lands)                                                                                                                                      |

A `derived` type is a normal, expected outcome — the table is an exception list, not a
coverage list, and 79% of its rows were restating a derivable pattern. What matters is that
the artifact says which happened, so a reviewer can tell a verified type from a resolved
one without re-deriving it.

**A `derived` type can never carry `confidence: deterministic` downstream.** Design's
`deterministic` tier requires a `direct_mappings` row AND a `fast_path_row` naming it; a
derived type reaching such a key by luck still yields `inferred`, because the type itself
was not verified.

`iac_metadata` carries the two collections that follow from this:

- **`derived_types`** — Terraform types resolved by derivation. Expected to be non-empty on
  any real repo. Report them, so a run is honest about how much of its inventory was
  derived rather than looked up.
- **`untranslated_types`** — types you **cannot name at all**. Not "no table row", and not
  "namespace unrecognised" — both of those are derived and retained. This is the residual
  case where the skill genuinely cannot say what the service is, and it is the only route to
  a halt from Discover. Expect it to be empty on almost every repo.

## Warnings

`warnings[]` is a **top-level array on the inventory**, always present, `[]` when
clean. Three files mandate writing to it (`discover-iac.md`, `extract-terraform.md`,
`discover.md`'s postconditions), so it is defined here, once.

```jsonc
{
  "code": "untranslated_terraform_type", // from the closed vocabulary below
  "azure_id": "<azure_id>", // when the warning is about a resource that HAS one
  "identifier": "azurerm_dev_test_lab.sandbox", // when it does not (a skipped or unresolvable thing)
  "detail": "<one sentence, customer-readable, naming the consequence>"
}
```

At least one of `azure_id` / `identifier` is required — a warning nobody can attribute
to anything is noise. `detail` states the **consequence**, not just the fact: "its
resources were not discovered" is useful, "module not found" is not.

**The vocabulary is closed.** Inventing a code makes the report's warning grouping
unstable and makes a fixture assertion on any code unreliable. Add a row here first.

| `code`                        | Emitted when                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type_derived_uncorroborated` | the ARM type was derived and its namespace is not declared in `namespace_routing`. NOT an error — the resource is retained and Design routes it to a model-chosen category. `detail` names the namespace                                                                                                                                                                                                                                                |
| `untranslated_terraform_type` | a Terraform type is absent from `arm-type-canonicalization.md`; the resource is skipped, never guessed                                                                                                                                                                                                                                                                                                                                                  |
| `module_not_resolved`         | a `module` block's source is a registry or git address whose content is not in the workspace                                                                                                                                                                                                                                                                                                                                                            |
| `private_endpoint_consumed`   | a private endpoint was read for its edge and skipped as a target; names the edge produced                                                                                                                                                                                                                                                                                                                                                               |
| `resource_group_unresolved`   | neither an explicit `resource_group_name` nor a resolvable parent exists                                                                                                                                                                                                                                                                                                                                                                                |
| `name_expression_unresolved`  | one or more resources' `name` is an expression, so `name` is `tf:<local>` and `azure_id` is **not** a real ARM ID — those resources cannot be drift-matched against a live capture. **ONE entry per run**, listing the affected `tf_address`es in `detail`, not one per resource: it routinely applies to most of a repo (a corpus naming everything `${var.prefix}` produced 21 of 25 warnings) and per-resource entries bury every actionable warning |
| `subscription_id_unresolved`  | the subscription id came from a variable or the environment, so `azure_id` carries the `<subscription-unknown>` placeholder. One entry per run, not per resource                                                                                                                                                                                                                                                                                        |
| `multiplicity_unresolved`     | a `count` / `for_each` expression was not evaluated; the entry represents an unknown number of real resources                                                                                                                                                                                                                                                                                                                                           |

Secret discarding is **not** warned about. A count of discarded fields still discloses
that they existed and roughly how many — the whole point of discarding rather than
redacting is to leave no trace.

Design writes its own `warnings[]` with a separate vocabulary; see
`phases/design/design-infra.md` § Warning codes.

## `azure-resource-clusters.json`

```jsonc
{
  "phase": "discover",
  "clusters": [
    {
      "cluster_id": "<stable slug>",
      "seed_resource_group": "<rg>", // the seed, not the answer
      "tier": "compute", // network_identity_secrets | data | compute | edge
      "members": ["<azure_id>"],
      "member_roles": {}, // azure_id -> deployment | data | configuration | network | observability | identity | idle
      "primary": "<azure_id>", // the resource the cluster is named for; see clustering/classification-rules.md
      "justification": "seed:resource_group", // REQUIRED — see below
      "edges": [], // the edge set that JUSTIFIED this grouping
      "pattern_id": "unclassified",
      "pattern_confidence": "inferred"
    }
  ],
  "unclustered": []
}
```

`edges` is not decoration. The Clarify assumption sheet needs it to explain _why_ five
resources were called one workload, and a cluster the user cannot see the reasoning
for is a cluster they cannot validate.

**`justification` exists because an unrefined cluster has a real reason that is not an
edge.** Before the split/merge refinement lands (build step 4), a cluster is one
resource group and `edges[]` is legitimately empty — the members are grouped because
they share a group, not because anything connects them. Without this field, "grouped by
the resource-group seed" and "grouped for no recorded reason" are indistinguishable,
and the phase's postcondition on the justifying edge set can only pass by not being
evaluated.

| `justification`           | Meaning                                                                                                                                                                      |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `seed:resource_group`     | the unrefined seed — every member shares one resource group, `edges[]` is empty                                                                                              |
| `edges`                   | refinement ran; `edges[]` is non-empty and is the actual justification                                                                                                       |
| `split:no_internal_edges` | carved out of a seed whose contents had no relationship between them — `edges[]` is legitimately EMPTY, because the justification is an ABSENCE and there is nothing to show |
| `merge:cross_group_edges` | merged across resource groups because a non-ambient edge crossed the boundary — `edges[]` MUST contain those crossing edges                                                  |

`justification: "edges"` or `"merge:…"` with an empty `edges[]` is a contradiction and must
fail validation. **`split:…` is exempt**, and getting this wrong is not hypothetical: an
earlier draft required a non-empty `edges[]` for every non-seed justification, which made
a correct split unrepresentable — a capability run had to mislabel nine clusters
`seed:resource_group` to pass the gate, destroying the very information the field exists
to carry.

`tier` is a fixed classification, not a computed topological depth. Fixed tiers are
what Generate's cutover sequencing actually wants, and they are stable under partial
discovery in a way a depth calculation is not.

## Validation Checklist

- [ ] Every `resources[]` entry has `azure_id`, `azure_type`, `resource_group`, `subscription_id`, `source`, `config`.
- [ ] No `azure_type` value matches `azurerm_*` — translation happened during extraction.
- [ ] `azure_id` is unique across `resources[]`.
- [ ] `metadata.discovery_sources` lists only sources that contributed at least one resource.
- [ ] For each dialect whose files were found in the workspace, at least one resource carries that dialect as its `source`.
- [ ] No app-setting value, connection-string value, storage key, or Key Vault secret value appears anywhere.
- [ ] `warnings[]` is present (possibly empty), and every entry has a `code` from the closed vocabulary, a `detail`, and an `azure_id` or an `identifier`.
- [ ] Every `edges[]` entry's `type` appears in the § Typed edges table.
- [ ] Every inventory resource is either a cluster member or listed in `unclustered[]`.
- [ ] Every cluster has `cluster_id`, `tier`, `members`, `primary`, `member_roles`, and a `justification`.
- [ ] `primary` is a member of its own cluster, and is never a `Microsoft.Web/sites` resource.
- [ ] `member_roles` has an entry for every member except the primary.
- [ ] No resource is a member of two clusters.
- [ ] Any cluster whose `justification` is `edges` or `merge:*` has a non-empty `edges[]`. A `split:*` cluster may legitimately have an empty one.

## Status — skeleton (build step 1)

The shapes above are the real contract and downstream phases are written against them.
Per-type `config` schemas land with each dialect and source (step 2); the reservation
and utilization profiles land with the RDfA fragment (step 2); `pattern_id`'s value set
lands with the pattern catalog (step 4).

`split:*` and `merge:*` are reachable as of build step 4. A cluster still carrying
`seed:resource_group` is one that survived both refinement steps untouched — a genuine
outcome for a single-workload resource group, not a sign that refinement did not run.
