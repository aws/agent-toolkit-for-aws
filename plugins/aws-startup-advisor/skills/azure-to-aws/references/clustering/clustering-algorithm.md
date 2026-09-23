# Clustering — resource-group seed, then split and merge

Loaded by `discover-assemble.md`. Produces `azure-resource-clusters.json` per
`references/shared/schema-discover-azure.md`.

## Why not just use resource groups

A resource group is a **filing decision**, not an architectural one, and Azure estates
file four different ways:

| RG layout                                       | Does RG-only clustering work?                                  |
| ----------------------------------------------- | -------------------------------------------------------------- |
| one app per group                               | yes                                                            |
| one group per environment, several apps         | **no** — splits nothing; one cluster holds unrelated workloads |
| horizontal groups by type (`rg-data`, `rg-app`) | **no** — actively separates an app from its own database       |
| one group for everything (the startup default)  | **no signal at all**                                           |

So the group is a good **seed** and a bad final answer. The point of clustering is to
make the recommendation describe _workloads_; a cluster that is really just a filing
folder produces a report that reads like 40 unrelated rows with extra steps.

**Azure's edge data is richer than GCP's and does not require IaC.** GCP's graph comes
from Terraform reference expressions, so it exists only when IaC does. Azure embeds full
ARM resource IDs inside resource _properties_, so `hosted_on`, `network`, `private_link`,
`secret_ref`, `data_ref`, and `identity_grant` all survive a live capture or an RDfA
archive. That is what makes refinement worth doing here.

## The algorithm

### Step 1 — Seed

One candidate cluster per distinct `resource_group` across `resources[]`. A resource with
`resource_group: null` (it carries a `resource_group_unresolved` warning) goes straight to
`unclustered[]` — do not invent a group for it.

Resources whose type is a Skip Mapping still cluster. They are part of the workload's
shape even when they get no AWS target, and excluding them would make the cluster's
member list disagree with the inventory, which the phase's accounting assert catches.

### Step 2 — Split a seed with no internal edges

For each candidate, build the subgraph of relationships **between its own members** and
find the connected components. Two things count as connectivity here:

1. every `edges[]` entry, **treated as undirected** — an app referencing a database and a
   database being referenced are the same relationship. Direction matters for tiering and
   for the report's phrasing, never for connectivity;
2. **containment**, derived from the `azure_id` prefix — but ONLY within the
   `/providers/` chain. A VNet and its subnets, a storage account and its share, a plan
   and its slots are connected (the child's id extends the parent's _past_ the
   `/providers/` segment). Containment is deliberately not an _edge_
   (`schema-discover-azure.md` says why) but it is unquestionably a relationship, and
   omitting it is what over-fragments a seed.

   > **The resource-group scope prefix does NOT count as containment.** A
   > `Microsoft.Resources/resourceGroups` resource has id
   > `/subscriptions/<sub>/resourceGroups/<rg>`, which is a literal prefix of _every_
   > resource in the group — its members' ids all begin
   > `/subscriptions/<sub>/resourceGroups/<rg>/providers/...`. Counting that prefix as
   > containment connects the whole seed through the group resource itself, collapses
   > every component into one, and permanently disables the split step (a real repo that
   > declares its `azurerm_resource_group` hits this; the worked example's corpus omitted
   > it and so missed it). Containment holds between two resources ONLY when the child id
   > extends the parent id _after_ a shared `/providers/` segment — never when the
   > "parent" is the resourceGroups (or subscription) scope itself. Equivalently: the
   > resourceGroups resource contains nothing for clustering purposes; it clusters as an
   > ordinary member of its seed and, being a Skip Mapping with no primary rank, attaches
   > to the largest component as a fragment.

**Split only when TWO OR MORE components each contain a primary-eligible resource** —
ranks 1–7 in `classification-rules.md`. A component with nothing primary-eligible in it is
not a workload, it is a fragment: attach it to the largest component of the same seed
rather than promoting it to a cluster of its own.

Set `justification: "split:no_internal_edges"` on each resulting cluster.

> **A `split:*` cluster legitimately has an EMPTY `edges[]`.** Its justification is the
> _absence_ of a relationship, and there is nothing to show. Only `merge:*` and the bare
> `edges` justification require a non-empty `edges[]` — see `schema-discover-azure.md`.

**Both guards exist because the first draft of this file over-fragmented badly, and its
own worked example proved it.** With containment excluded and singleton components
promoted, a capability run over the corpus below produced **16 clusters** where the example
predicted 3: a VNet separated from its subnets, a storage account from its share, and every
edgeless observability resource elevated to a workload of its own. The example was written
by hand rather than by tracing the algorithm, so the two disagreed and the algorithm was
what shipped. If you change this step, re-trace the example.

### Step 3 — Merge candidates joined by crossing edges

For each edge whose source and target are in **different** candidates, merge those two
candidates. Repeat to a fixed point — merging is transitive, so an app in `rg-app`
referencing a database in `rg-data` which references a vault in `rg-shared` yields one
cluster of three.

Set `justification: "merge:cross_group_edges"`, and `edges[]` **must** contain the
crossing edges that caused it. A merge whose justification cannot be shown is a merge the
user cannot validate on the Clarify assumption sheet.

**Not every edge type should merge.** Two edge types are _ambient_ — they connect almost
everything to a small number of shared resources, so merging on them collapses the whole
estate into one cluster and destroys the partition:

| Edge type           | Merges? | Why                                                                                      |
| ------------------- | ------- | ---------------------------------------------------------------------------------------- |
| `hosted_on`         | **yes** | the strongest edge there is — an app and its plan are one compute unit                   |
| `data_ref`          | **yes** | an app and the database it addresses are one workload                                    |
| `private_link`      | **yes** | an explicit, deliberately-created app-to-data path                                       |
| `declared_affinity` | **yes** | the customer said so; declared intent outranks inference                                 |
| `identity_grant`    | **yes** | "app X reads storage Y" is a real dependency, and Azure exposes it more cleanly than GCP |
| `network`           | **no**  | every workload in a VNet shares subnets. A shared subnet is colocation, not relatedness  |
| `secret_ref`        | **no**  | one Key Vault typically serves the entire estate; merging on it produces one cluster     |

A non-merging edge is still **recorded** on the resource and still counts for Step 2's
internal connectivity — it just does not pull two candidates together. That asymmetry is
deliberate: sharing a subnet is weak evidence of relatedness but perfectly good evidence
that two already-related resources belong in the same cluster.

### Step 4 — Assign identity, tier, and primary

Per cluster: `cluster_id`, `tier` (see `tiering.md`), `primary` and member
classification (see `classification-rules.md`), and the `pattern_id` /
`pattern_status` fields (`patterns.md`, build step 4 — until it exists, every cluster is
`pattern_id: "unclassified"` with `pattern_status: "catalog_absent"`).

**`cluster_id` must be stable across runs of the same repo**, because Clarify records the
user's pattern confirmation against it and a re-run must not orphan those answers. Derive
it from the cluster's `primary` resource — `<resource-group>-<primary-name>` slugified —
and never from iteration order or an incrementing counter.

### Step 5 — Verify before writing

- Every inventory resource is a member of exactly one cluster, or is in `unclustered[]`.
- No resource appears in two clusters (merging must union members, not duplicate them).
- Every `justification` of `edges` or `merge:*` has a non-empty `edges[]`; a `split:*` may be empty.
- Every `azure_id` in `edges[]` and `members[]` exists in the inventory.

## Worked example

Given `rg-app` {**its `resourceGroups` resource**, vnet, 2 subnets, storage account, its
SMB share, key vault, Log Analytics workspace, App Insights, plan-web + 5 web apps,
plan-func + 1 function app}, `rg-data` {postgres, redis, cosmos, event hub namespace,
private endpoint}, `rg-shared` {idle plan, Windows VM, its NIC}. Each group here also
carries its own `azurerm_resource_group` resource, as a real repo does.

1. **Seed** → 3 candidates.
2. **Split.** `rg-app`'s components, once containment counts: {plan-web + 5 apps + vault
   via `secret_ref`}, {plan-func + function app + storage + share via `hosted_on` and
   `data_ref` and containment}, {vnet + both subnets}, {Log Analytics}, {App Insights}.
   Only the first two contain a primary-eligible resource (a `serverfarms` plan, rank 2),
   so **only those two are promoted**; the vnet/subnet, Log Analytics, and App Insights
   fragments attach to the largest component. **The `resourceGroups` resource does NOT
   connect these components** — its id is the scope prefix, not a `/providers/` parent —
   so it is a fragment with no primary rank and attaches to the largest component; it does
   NOT collapse the seed. `rg-shared` splits into {VM + NIC} (rank 3) and {idle plan}
   (rank 2) — two primary-eligible components, so a real split.
3. **Merge.** A web app has a `data_ref` to the postgres server and the private endpoint a
   `private_link` to it, so `rg-app`'s first component merges with `rg-data`. The subnet
   `network` edges are ambient and merge nothing, though they are recorded.
4. **Result: 4 clusters** — the merged app+data workload, the function workload, the
   reporting VM, and the idle plan.

Note what each step bought. The split stopped the idle plan being reported as part of a
reporting-VM workload. The merge stopped the app being costed without its database. The
primary-eligible guard stopped an orphan Log Analytics workspace being presented as a
workload. None of the three is visible from resource groups alone.

## Status — build step 4

Implemented. `patterns.md` and the cluster-level `data-pipeline` gate are the remaining
step-4 items; until `patterns.md` exists every cluster carries
`pattern_status: "catalog_absent"`, which is a defined state and not a gap
(`schema-design-aws.md` § clusters).
