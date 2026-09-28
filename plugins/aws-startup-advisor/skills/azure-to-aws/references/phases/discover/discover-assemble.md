---
_assemble: assemble-inventory
_of_phase: discover
_reads:
  - iac (fragment contribution)
  - app-code (fragment contribution, when source code with an AI signal is present)
_produces:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - ai-workload-profile.json
_knowledge:
  - { file: references/shared/schema-discover-azure.md }
  - { file: references/shared/schema-discover-ai.md, _when: "application code with an AI signal is present OR the IaC contribution contains a Cognitive Services account/deployment or Machine Learning workspace" }
  - { file: references/clustering/clustering-algorithm.md }
  - { file: references/clustering/typed-edges-strategy.md }
  - { file: references/clustering/classification-rules.md }
  - { file: references/clustering/tiering.md }
---

# Discover — Assemble Inventory and Clusters

> **Assembler unit.** Runs after the discover fragments have written their
> contributions. It is the single creator of both phase artifacts and owns their
> final contract. See `discover.md` for how it is composed into the phase.

**Schema reference**: `references/shared/schema-discover-azure.md` — consult for
complete field definitions, per-type `config` schemas, the drift record shape, and
the validation checklist.

## Assembly rules

1. Merge every fragment's contributions into `resources[]`, keyed by `azure_id`.
   One entry per `azure_id`; never two.
2. Each entry carries at minimum `azure_id`, `azure_type` (canonical `Microsoft.*`),
   `resource_group`, `subscription_id`, `source`, and `config`.
3. Write `metadata`: `discovery_timestamp`, `discovery_sources` (only sources that
   actually contributed), `subscriptions_discovered`, `total_resources`, and
   `confidence`.
4. Apply source precedence when two sources describe the same `azure_id`, highest
   first: **live `az`** (current existence and configuration — it is _now_), then
   **RDfA** (utilization, reservations, consumption; loses to live on state because
   an archive may be days old, wins on measurement because live has no rollup), then
   **IaC** (authoritative for provenance, module structure, and declared-but-
   undeployed resources; authoritative for nothing about state), then **billing**
   (fallback only, `billing_inferred`).
5. **Every disagreement becomes a drift entry.** Record both values, both sources,
   and which won, so the report can say "your Terraform declares `Standard_D2s_v3`,
   your tenant is running `Standard_D4s_v3`" instead of quietly picking one.
6. **Merge the fragments' `warnings[]` into one top-level array** on the inventory,
   preserving every entry. The array is always present, `[]` when clean. Every `code`
   comes from the closed vocabulary in `schema-discover-azure.md` § Warnings — do not
   invent one, because an invented code makes the report's grouping unstable and any
   fixture assertion on a code unreliable.
7. Derive `azure-resource-clusters.json` per `references/clustering/`: seed one
   candidate per resource group, **split** a candidate whose members have no edges
   between them, **merge** candidates joined by a non-ambient crossing edge, then assign
   `tier`, `primary`, member roles, and `justification`. `clustering-algorithm.md` is the
   procedure; `typed-edges-strategy.md` says which edge types may merge and which are
   ambient; `classification-rules.md` picks the primary; `tiering.md` assigns the tier.

8. Merge AI-profile contributions by producer. IaC only ->
   `metadata.profile_source: "iac_cognitive"`; app-code only -> `"application_code"`; both ->
   `"merged"`, with code winning conflicts and `infrastructure[]` unioned by `address`.
   Preserve both `sources_analyzed` flags. A strong IaC AI signal without an IaC profile
   contribution is an assembly failure, not an optional absence.

## Confidence vocabulary

Four tiers, set per resource and per mapping decision:

| Label              | Meaning                                                    | Source                                              |
| ------------------ | ---------------------------------------------------------- | --------------------------------------------------- |
| `deterministic`    | fixed 1:1 table lookup                                     | the fast-path Direct Mappings table                 |
| `measured`         | rubric backed by observed utilization, not declared config | RDfA 31-day rollup **or** `az monitor metrics list` |
| `inferred`         | rubric from declared config only                           | IaC, or live CLI without metrics                    |
| `billing_inferred` | billing-only fallback                                      | Cost Management export                              |

`measured` is deliberately not named after one tool. Naming it `rdfa_inferred` would
mean the live path could never earn the tier even when it supplies the same
evidence. User-facing label: **"Measured from your actual usage."**

## Status — build step 4 (clustering real)

Writes both artifacts from the single IaC fragment. Clustering is **real** as of build
step 4: seed, split, merge, tier, primary, roles.

`justification` records WHICH of those produced each cluster, and it is what makes an
empty `edges[]` legitimate rather than a silent gap. A cluster that survived seeding
untouched has a real reason — its members share a resource group — and that reason is not
an edge. Without the field, "grouped by the seed" and "grouped for no recorded reason"
produce identical output, and the phase's postcondition on the justifying edge set could
only pass by not being evaluated. `split:*` and `merge:*` require a non-empty `edges[]`
carrying the evidence.

| Lands in | What                                                                                                                                                            |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| step 2   | The merge-and-drift rules above, exercised once more than one source can contribute                                                                             |
| step 4   | `patterns.md` and the cluster-level `data-pipeline` gate. Until it exists every cluster carries `pattern_status: "catalog_absent"` — a defined state, not a gap |

**Resource group is a good seed and a bad final answer.** It works when there is one
app per group; it splits nothing when there is one group per environment; it actively
separates things that belong together under horizontal groups (`rg-databases`,
`rg-app`); and it carries no signal at all in the single-group startup default. The
refinement is what makes clustering mean anything.

Azure's edge data is richer than GCP's and does not require IaC: ARM resource IDs
are embedded in resource _properties_, so edges survive every discovery source —
`serverFarmId` on a web app, `subnetId`, a private endpoint's `privateLinkServiceId`,
a Key Vault reference in app settings, a managed identity plus its role-assignment
scope, and `app=` / `workload=` tags.

## Step: Assemble

1. Apply the assembly rules above.
2. Validate both artifacts against `schema-discover-azure.md`'s checklist.
3. Stop with a diagnostic ONLY when NEITHER a resource inventory NOR
   `ai-workload-profile.json` was produced — i.e. nothing will produce any artifact
   (matching gcp's rule). When an IaC source contributed resources, write the inventory
   and clusters as usual. When the run is **app-code-only** (the app-code fragment
   produced `ai-workload-profile.json` but no IaC source was found), write ONLY the AI
   profile and leave `azure-resource-inventory.json` / `azure-resource-clusters.json`
   **ABSENT** — never write an empty inventory to satisfy a gate. Clarify detects the
   app-code-only (AI-only) run by the inventory being absent while the AI profile is
   present, and routes to `clarify-ai-only.md`.
