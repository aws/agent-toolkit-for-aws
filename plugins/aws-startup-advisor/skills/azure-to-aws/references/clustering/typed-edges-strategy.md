# Clustering — typed-edge strategy

The edge VOCABULARY is defined once, in `references/shared/schema-discover-azure.md`
§ Typed edges, and the per-dialect extraction is in `extract-terraform.md` § Edges. This
file is the strategy: what each edge is worth as evidence, and why the weights differ.

## Azure's advantage over GCP, and the one place it is worse

gcp-to-aws builds its graph from Terraform reference expressions, so **the graph exists
only when IaC does** — a live-capture-only GCP run has no edges at all. Azure embeds full
ARM resource IDs inside resource _properties_ (`serverFarmId`, `subnetId`,
`privateLinkServiceId`, a Key Vault reference in an app setting), so every edge type
survives a live `az` capture and an RDfA archive. Clustering therefore works on the
live-first path, which is the default here.

The one place Azure is worse: **Terraform-sourced `data_ref` edges depend on
interpolation**. If an app's `DATABASE_URL` is a literal connection string rather than
`azurerm_postgresql_flexible_server.store.fqdn`, there is no reference to follow and the
edge does not exist — the app and its database stay in separate clusters. A live capture
does not recover it either, because the setting VALUE is never captured (it is a secret).
So an app-to-data edge can be genuinely undiscoverable, and the honest response is that
the Clarify assumption sheet asks rather than the algorithm guessing.

## Evidence weight

The distinction that matters is **specific versus ambient**. A specific edge was created
to connect two particular resources; an ambient edge connects almost everything to a small
number of shared resources.

| Edge                | Weight  | Merges? | Reasoning                                                                                                                                               |
| ------------------- | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hosted_on`         | hard    | yes     | Not evidence of relatedness — it _is_ the relationship. An app and its plan are one compute unit, and this edge is also what prevents the 5× cost error |
| `data_ref`          | strong  | yes     | Someone wrote this app's config to address this database. Specific by construction                                                                      |
| `private_link`      | strong  | yes     | A private endpoint is deliberately created to reach one resource. The most explicit app-to-data signal Azure offers                                     |
| `declared_affinity` | strong  | yes     | An `app=` / `workload=` tag is the customer stating intent. Declared intent outranks inference                                                          |
| `identity_grant`    | medium  | yes     | "App X can read storage Y" — a real dependency, and cleaner in Azure than GCP because the role-assignment scope names the target                        |
| `network`           | ambient | **no**  | Every workload in a VNet shares subnets. Merging here collapses the estate into one cluster                                                             |
| `secret_ref`        | ambient | **no**  | One Key Vault typically serves everything. Same collapse                                                                                                |

An ambient edge is still **recorded** and still counts for internal connectivity in the
split step. It just cannot pull two candidate clusters together. Sharing a subnet is weak
evidence that two resources are related and perfectly good evidence that two
already-related resources belong together — the asymmetry is the point.

## Why not weight-and-threshold instead

A tempting alternative is to sum edge weights and merge above a cutoff. Rejected, for the
reason the plan gives for avoiding tunable constants generally: the threshold would have no
defensible source, it would need re-tuning per estate shape, and its failures would be
silent and hard to explain to a customer. A binary merges/does-not per edge type is
explainable in one sentence per row, and every row above has a stated reason.

## What an edge is not

- **Not containment.** A child's link to its parent needs no edge: an ARM `azure_id`
  contains its parent's as a literal prefix, so it is derivable by truncation from any
  source. See `schema-discover-azure.md`.
- **Not an observability link.** A component's `workspace_id` points at a Skip Mapping and
  no design decision consumes it. It belongs in `config`.
- **Not a Terraform `depends_on`.** That is an ordering hint for the apply, not an
  architectural relationship, and it is frequently added to work around a provider bug.

## Status — build step 4

Implemented. Consumed by `clustering-algorithm.md` Steps 2 and 3.
