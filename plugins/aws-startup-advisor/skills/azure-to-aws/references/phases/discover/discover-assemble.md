---
_assemble: assemble-inventory
_of_phase: discover
_reads:
  - iac (fragment contribution)
  - live (fragment contribution, when a live-capture/manifest.json was written by the live-az pre-work)
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

8. Merge AI-profile contributions by producer. IaC and/or live only ->
   `metadata.profile_source: "iac_cognitive"`; app-code only -> `"application_code"`;
   any infrastructure signal (IaC and/or live) PLUS app-code -> `"merged"`, with code
   winning field-level conflicts. Union `infrastructure[]` by its per-entry key — an
   IaC-sourced entry's `address`, a live-sourced entry's `azure_id`. **Before
   unioning, reconcile:** for every IaC-sourced entry that carries an `azure_id` (per
   `discover-iac.md` § Step 4.5), check it against every live-sourced entry's
   `azure_id`. An exact match means the two entries describe the SAME deployed
   resource observed by two producers — merge them into ONE `infrastructure[]` entry
   (keep the IaC-sourced shape for provenance, overlay live's `config` where it
   disagrees, live wins on state) rather than keeping both, per
   `schema-discover-ai.md` § infrastructure[] Reconciliation. An IaC-sourced entry
   with no `azure_id`, or whose `azure_id` matches no live entry, is unmerged and
   contributes its own entry as before — that is a genuinely distinct resource, not a
   reconciliation failure. Set every `sources_analyzed` flag (`terraform`, `live`,
   `application_code`) to `true` iff AT LEAST ONE qualifying resource in the merged
   profile came from that source — OR across the whole profile, never assigned
   exclusively per producer (see `schema-discover-ai.md` § profile_source and
   sources_analyzed); a merged entry sets BOTH `terraform` and `live` true, since both
   producers genuinely observed it. A strong IaC AI signal without an IaC profile
   contribution is an assembly failure, not an optional absence; same for a live AI
   signal without a live profile contribution.

9. **Write the Clarify fast-path eligibility verdict** to
   `azure-resource-inventory.json` → `metadata.clarify_fast_path` (shape in
   `schema-discover-azure.md` § metadata). This is the analogue of gcp-to-aws's
   `migration-preview.json` eligibility flags: Discover decides, from the inventory alone,
   whether Clarify may offer the short path, so the decision is auditable and not re-derived
   by the phase that benefits from it. Compute every input first, then apply the rule; record
   **every** failing input in `reasons_ineligible[]` (not just the first) so the Clarify
   offer can say why the full flow is running.

   | Input                  | From                                                                                                                                                         |
   | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
   | `has_ai_profile`       | `ai-workload-profile.json` exists in `$MIGRATION_DIR`                                                                                                        |
   | `has_licensing_signal` | the exact trigger of Clarify's `licensing` fragment: any Windows VM image, any `Microsoft.Sql/*` resource, or a SQL-Server-on-VM image signature             |
   | `has_vm`               | any `Microsoft.Compute/virtualMachines` or `virtualMachineScaleSets`                                                                                         |
   | `has_cosmos_core`      | any `Microsoft.DocumentDB/databaseAccounts` whose API is Core (SQL)                                                                                           |
   | `has_ha_database`      | any relational database whose `config` shows zone-redundant or HA-enabled (the condition that makes Clarify's Q-D1 ESSENTIAL)                               |
   | `multi_region`         | `resources[]` span more than one Azure `location`                                                                                                            |
   | `cluster_count`        | `azure-resource-clusters.json` → `clusters.length`                                                                                                           |
   | `total_resources`      | `metadata.total_resources`                                                                                                                                   |

   ```
   eligible =
        has_ai_profile       == false
    AND has_licensing_signal == false
    AND has_vm               == false
    AND has_cosmos_core      == false
    AND has_ha_database      == false
    AND multi_region         == false
    AND cluster_count        <= 2
    AND total_resources      <= 20
   ```

   Each clause removes a question that Clarify would otherwise have to ask with no default
   (licensing, VM cutover, Cosmos read/write split, HA downgrade, region choice) or a
   category whose rows need the full sheet (AI). What remains on the short path is exactly
   the ESSENTIAL rows that fire for every estate — compliance, and baseline spend when no
   billing source exists (database cutover is PROPOSED-and-deferred, not ESSENTIAL — see
   `clarify-database.md` § Q-D2) — plus documented defaults for everything else. The two size caps are deliberately generous
   because Azure inventories count `$0` networking primitives (see
   `estimate-infra.md` § complexity tier note); the cluster count is the better signal.

   An ineligible verdict is **not** a judgement about the estate — it means at least one
   row has no defensible default, and the full sheet is the right tool. Write
   `{ "eligible": false, "reasons_ineligible": ["has_vm", "has_licensing_signal"] }` and let
   Clarify explain.

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
