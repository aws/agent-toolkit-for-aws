# Specialist gates

A gate means **we do not know**, and it is the only honest output for a workload whose
target depends on information this skill deliberately does not carry.

The gate ROWS are data and live in `knowledge/design/fast-path-services.json` →
`specialist_gates`. This file is the contract: what a gate is, where it sits in
precedence, what it emits, and the five deltas from gcp.

## Why this is a table and not a hardcoded check

gcp-to-aws has exactly one gate, expressed as a hardcoded `google_bigquery_` prefix
test inside `design-infra.md`. Azure has five at resource level plus one at cluster
level, so a prefix test would become a chain of five, each one an independent place to
forget a row. The table form also makes the _precedence invariant_ checkable: a
canonical type must resolve to at most one of `skip_mappings`, `specialist_gates`, and
`direct_mappings`, and that is only verifiable when the three sit in one file.

## Precedence — second, above everything except skips

```
skip_mappings  →  SPECIALIST GATES  →  eliminators  →  direct_mappings
               →  pattern constraint  →  six criteria  →  preferred-target substitution
```

A gate sits above eliminators, Direct Mappings, patterns, and the rubric on purpose:
**nothing below may overwrite an admission of ignorance with a confident guess.** The
one thing above it is a Skip Mapping, because a resource with no AWS analogue at all
does not need a specialist either.

Concretely, this ordering is what stops a `data-pipeline` pattern from confidently
routing a Synapse workspace to Redshift because Redshift was the nearest candidate in
its constraint set.

## What a gate emits

A `deferred[]` entry in `aws-design.json`, never a `services[]` entry:

```jsonc
{
  "azure_id": "...",
  "azure_type": "Microsoft.Sql/managedInstances",
  "aws_service": "Deferred — specialist engagement",
  "reason": "<the row's reason, verbatim — it is the customer-facing explanation>",
  "recommendation": "Engage your AWS account team; this workload needs a migration assessment."
}
```

**No `confidence` field.** A deferral did not come from a rubric, so labelling it
`inferred` would claim reasoning that did not happen. This is the one design entry shape
that carries no confidence value, and the design phase's postcondition that requires
`confidence` applies to `services[]` only.

A gate is **not** a failure and **not** a STOP. Design continues; the rest of the
estate is mapped normally, and the estimate simply carries no line item for the
deferred workload. Say that plainly in the report rather than letting a missing cost
read as a free service.

## The five resource-level gates, and why each one is gated

| Type                                                     | The information we do not have                                                                                                                                                          |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Sql/managedInstances`                         | Whether the instance-scoped surface is actually used — VNet injection, cross-database queries, SQL Agent jobs, CLR, instance logins. RDS SQL Server covers a database, not an instance. |
| `Microsoft.Sql/servers/elasticPools`                     | Per-database utilization, and therefore the bin-packing. One RDS instance overprovisions; one per database multiplies the estimate. Both answers are wrong.                             |
| `Microsoft.Synapse/workspaces`                           | Which of the three surfaces is load-bearing — dedicated SQL pools, serverless SQL, or Spark. They land on three different services with three different migration paths.                |
| `Microsoft.DataFactory/factories`                        | The activity graph. Glue, Step Functions, and MWAA each cover part of ADF; naming one understates the work by a large factor.                                                           |
| `Microsoft.Compute/virtualMachines` + a SQL Server image | The licensing posture — Azure Hybrid Use Benefit, core minimums, and any Always-On configuration. **Conditional on the image, not the type.**                                           |

### The SQL-on-VM gate emits TWO entries

It is the only gate on a type that is otherwise a rubric row, and it must not swallow
the host:

- the **VM** still maps to EC2 through `compute.md`, with its own confidence label;
- the **SQL Server workload on it** gets the `deferred[]` entry.

Deferring the whole VM would drop a real compute line item from the estimate and make
the total quietly too low.

## What is deliberately NOT gated

| Considered                           | Decision                                                                                                                                                                                      |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Sql/servers/databases`    | **Not gated.** A single Azure SQL Database on a DTU or vCore tier maps cleanly to RDS SQL Server (owner decision 11.3), and deferring the common case makes the skill look weaker than it is. |
| `Microsoft.Databricks/workspaces`    | **Not gated** — Databricks runs on AWS, so this is a platform move rather than a re-architecture. Full depth in `analytics.md`.                                                               |
| `Microsoft.Cache/redisEnterprise`    | **Not gated** — rubric. The modules (RediSearch, RedisJSON) have no ElastiCache equivalent, but that is a feature-parity finding, not an unknown.                                             |
| Azure Hybrid Use Benefit / licensing | **Not a gate** — `licensing.md`, loaded conditionally from Clarify category I. One essential question (License Included versus BYOL on Dedicated Hosts), no core-minimum math.                |
| Azure Edition Windows Server         | **Not a gate — a hard blocker.** MGN refuses the image until it is re-imaged. There is no option to weigh, so it is a `warnings[]` entry with `severity: "blocker"`, not a question.          |

## The cluster-level gate

The `data-pipeline` pattern is this same mechanism one layer up: a cluster whose shape
is Data Factory / Synapse / Event Hubs + storage + analytics defers as a **whole**
rather than resource by resource, because the pipeline is the unit a specialist would
assess. It lives in `patterns.md` and lands in build step 4.

Recognising it at cluster level matters for the report: five separate deferrals read as
five gaps, while one cluster-level deferral reads as one workload that needs an
assessment — which is what it is.

## Status — build step 3

The gate table is complete and the precedence order is enforced by `design-infra.md`.

| Lands in | What                                                                                   |
| -------- | -------------------------------------------------------------------------------------- |
| step 4   | `patterns.md` and the cluster-level `data-pipeline` gate                               |
| step 5   | `licensing.md`, and the `analytics.md` / `database.md` content the non-gated rows need |

**Untested.** No fixture exercises a gate yet: the `azure-iac-terraform` corpus contains
no Managed Instance, elastic pool, Synapse workspace, Data Factory, or SQL-on-VM image.
The rows above are therefore reviewed, not verified. A gate fixture belongs with build
step 5, when `database.md` exists to be the thing a gate is chosen _instead of_.
