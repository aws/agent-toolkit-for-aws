# Clustering — tiers

A cluster's `tier` is a **fixed classification of what the cluster mostly is**, not a
computed topological depth.

## Why fixed tiers rather than gcp's depth calculation

gcp-to-aws computes `creation_order_depth` by walking the dependency graph. Two reasons
that is the wrong tool here:

1. **Generate wants a cutover order, and the order is always the same.** Network,
   identity, and secrets have to exist before data, data before compute, compute before
   the edge that fronts it. A computed depth reproduces that order on a complete graph and
   produces something arbitrary on an incomplete one.
2. **Depth is unstable under partial discovery**, which is the normal case here. Discover
   over Terraform alone, or over a repo with one unresolvable module, yields a graph
   missing edges — and a missing edge silently changes every downstream depth. A fixed
   tier derived from resource TYPE cannot drift that way.

## The four tiers

Assign in order; the first match wins.

| Tier                       | Cluster contains…                                                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `network_identity_secrets` | only networking, identity, secrets, and observability types — no compute, no data                                                          |
| `data`                     | at least one database, cache, storage, or messaging resource, and **no** compute                                                           |
| `compute`                  | at least one compute resource (plan, site, VM, VMSS, AKS cluster, container app)                                                           |
| `edge`                     | only edge types — Front Door / CDN, Application Gateway, API Management, Traffic Manager, public IP — fronting resources in OTHER clusters |

**`compute` deliberately outranks `data`.** A merged app+database cluster is a compute
cluster: the compute is what gets sized, what dominates the estimate, and what the report
leads with. Calling it `data` because it happens to contain a database would bury the
thing the customer is actually paying for.

A cluster matching none of these (only Skip-Mapping types — an orphan Log Analytics
workspace, a lone diagnostic setting) gets `tier: "network_identity_secrets"`, since that
is where observability lives and it needs no cutover slot of its own.

## What the tier is used for

- **Design orders clusters by tier** (`design.md` § Step: Run the phase), so the network
  and data a compute cluster depends on are already mapped when the compute decision is
  made and the rubric's Cluster Context criterion has something to read.
- **Generate sequences the cutover by tier**, which is the real payoff: it is the
  difference between a migration guide that says "create these 40 resources" and one that
  says what has to exist before what.
- **The report groups by tier**, so a reader sees the shape of the estate before the
  detail.

## What the tier is NOT

Not a priority, not a difficulty estimate, and **not a migration wave**. A wave is a
customer decision about risk and downtime that depends on business context this skill does
not have. Tier is a dependency ordering; presenting it as a schedule would imply a plan
nobody agreed to.

## Status — build step 4

Implemented and consumed by `discover-assemble.md`. Generate's use of it lands in step 6.
