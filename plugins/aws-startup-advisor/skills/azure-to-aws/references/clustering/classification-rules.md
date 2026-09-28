# Clustering — primary and secondary classification

Within a cluster, one member is the **primary** and the rest are secondary. Ported from
gcp-to-aws with Azure's type vocabulary.

## Why the distinction matters

Three things depend on it, and all three degrade quietly if it is wrong:

1. **`cluster_id` is derived from the primary**, so a different primary means a different
   id, which orphans the user's Clarify pattern confirmation on a re-run.
2. **The report names a cluster after its primary.** "The storefront web workload" is
   readable; "the cluster containing 12 resources including a subnet" is not.
3. **The rubric's Cluster Context criterion reads the primary** to decide what the
   surrounding architecture _is_. A cluster whose primary is a NIC tells it nothing.

## Choosing the primary

First match wins:

| Rank | Type                                                                                  |
| ---- | ------------------------------------------------------------------------------------- |
| 1    | `Microsoft.ContainerService/managedClusters` — an AKS cluster is always the story     |
| 2    | `Microsoft.Web/serverfarms` — the App Service Plan, because it is the compute unit    |
| 3    | `Microsoft.Compute/virtualMachineScaleSets`, then `Microsoft.Compute/virtualMachines` |
| 4    | `Microsoft.App/containerApps`                                                         |
| 5    | a relational database — `Microsoft.DBfor*/flexibleServers`, `Microsoft.Sql/servers`   |
| 6    | `Microsoft.DocumentDB/databaseAccounts`                                               |
| 7    | `Microsoft.Storage/storageAccounts` — usually with `static_website`, a static site    |
| 8    | anything else, choosing the member with the **most inbound edges**                    |

**Never the plan's apps.** A `Microsoft.Web/sites` resource is never primary even though
it is the thing a human would name the workload after, because the plan is the compute
unit and naming the cluster after one of five co-hosted apps implies the other four are
subordinate to it. Use the plan, and let the report list the apps it hosts.

**Ties break on `azure_id` lexical order**, not on iteration order. Stability matters more
than which of two equivalent candidates wins.

## Secondary roles

Every non-primary member carries a role, which is what lets the report say _why_ it is in
the cluster rather than just listing it:

| Role            | Members                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------ |
| `deployment`    | `Microsoft.Web/sites` and `/slots` on the cluster's plan — the fan-in apps                       |
| `data`          | databases, caches, storage, messaging the primary addresses                                      |
| `configuration` | Key Vault, App Configuration, and every `config_source` Skip Mapping consumed for its properties |
| `network`       | VNets, subnets, NICs, NSGs, route tables, private endpoints                                      |
| `observability` | `Microsoft.Insights/*`, Log Analytics workspaces                                                 |
| `identity`      | managed identities, role assignments                                                             |
| `idle`          | a resource with **zero** edges in either direction                                               |

**`idle` is a finding, not a filler.** A plan with no apps, a disk attached to nothing, an
orphaned public IP — each is money being spent with no workload behind it, and the report
should say so. It is one of the few places the skill tells a customer something about
their _current_ estate that they did not already know, so do not let it collapse into a
generic "other".

## Status — build step 4

Implemented and consumed by `clustering-algorithm.md` Step 4.
