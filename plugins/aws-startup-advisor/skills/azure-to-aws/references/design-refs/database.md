# Database

Pass-2 rubric for every database type `index.md` routes here. Loaded only when the
inventory contains one.

**Outcome is `confidence: inferred`**, or `measured` when observed utilization backed the
sizing.

## 1. The availability override gate — read this before the rubric

**For Postgres and MySQL Flexible Server, the availability answer selects the family, and
it overrides whatever the rubric would have chosen.** Read it from
`preferences.json` → **`data.availability`** — _not_ `design_constraints.availability`,
which is where gcp-to-aws keeps it and where this file wrongly looked until 2026-09-07.
`clarify-database.md` writes it under `data`, and `schema-preferences.md` § data documents
it there.

> **Why that typo was dangerous rather than annoying.** Looking in the wrong place finds
> nothing, and § the absent case below then says to default to RDS single-AZ — which is
> the _same answer_ the corpus produces, so every test stayed green. On an estate where
> the customer answers `multi-az-ha` it silently produces RDS where Aurora was chosen,
> and the artifact records the customer's answer faithfully next to a target that ignores
> it. Capability run 4 found it by reading both files. This is a post-rubric override gate,
> not a criterion, and it is the cleanest lift in the whole port — gcp's Q6 maps across
> unchanged.

| `data.availability` | Target (match the engine from the source) |
| ------------------- | ----------------------------------------- |
| `single-az`         | **RDS PostgreSQL** / **RDS MySQL**        |
| `multi-az`          | **RDS** … **Multi-AZ**                    |
| `multi-az-ha`       | **Aurora** PostgreSQL / MySQL, Multi-AZ   |
| `multi-region`      | **Aurora Global Database**                |

Clarify writes `multi-region` only when the availability answer is Catastrophic **and**
`global.user_geography` is `global` (canonical `clarify-availability.md`). If
availability is `multi-az-ha` and geography is `global`, do **not** upgrade the family
here — that would invent Aurora Global without the recorded availability value. If
geography is `single-region` / `multi-region` and availability is somehow `multi-region`,
still honor the recorded availability row (the user picked [D] on Q-D1) and say in the
rationale that global infrastructure was requested without global users.

**Why an override rather than a criterion:** availability is _never inferable from
configuration_. A source `high_availability { mode = "ZoneRedundant" }` tells you what
they bought, not what they need — plenty of estates carry zone-redundancy nobody asked for
because it was a default, and plenty of single-zone databases are load-bearing. Only the
customer can answer it, so a rubric that inferred it from the source would be
manufacturing a requirement.

**If the answer is absent** — Clarify has not run, or the question was skipped — do **not**
default to Aurora. Default to **RDS single-AZ**, the dev-tier posture in SKILL.md
§ Philosophy, and record in the rationale that availability was not stated. Aurora costs
materially more; inferring it from silence inflates the estimate and the customer has no
way to see why.

> Do not read the source's `zone_redundant` / `high_availability` as the answer. Surface it
> as a **finding** — "your source is zone-redundant; you selected single-AZ, which is a
> deliberate downgrade" — which is a genuinely useful thing to tell someone.

## 2. Eliminators

| Candidate            | Eliminated when                                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Aurora Serverless v2 | the workload needs a **fixed reserved capacity floor** below its minimum ACU billing granularity — a permanently-busy database is cheaper provisioned                                                                                       |
| DynamoDB             | the source uses **joins, transactions across arbitrary keys, or ad-hoc query patterns**. Cosmos Core → DynamoDB is a data-model migration; if the access pattern is relational, it is the wrong target regardless of the source being NoSQL |
| ElastiCache Redis    | the source uses **Redis modules** (RediSearch, RedisJSON, RedisTimeSeries) — no ElastiCache equivalent. MemoryDB does not add them either; this is a feature-parity finding, and the honest output names the gap                            |
| Amazon Keyspaces     | the source relies on **Cassandra materialized views or UDFs**                                                                                                                                                                               |
| RDS SQL Server       | the source is a **Managed Instance** — specialist gate, never a rubric outcome                                                                                                                                                              |

## 3. Per-engine routing

Applied after the eliminators; the availability gate in §1 then overrides the family for
the two Flexible Server engines.

| Source                                                                   | Target                                                                                                                                                       |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Microsoft.DBforPostgreSQL/flexibleServers`                              | RDS or Aurora PostgreSQL — §1 selects                                                                                                                        |
| `Microsoft.DBforMySQL/flexibleServers`                                   | RDS or Aurora MySQL — §1 selects                                                                                                                             |
| `Microsoft.DBforPostgreSQL/servers`, `.../MySQL/servers` (Single Server) | same as Flexible, **plus** a finding: Single Server is retired on Azure, so the migration is also an upgrade and the source version may be below RDS's floor |
| `Microsoft.Sql/servers/databases`                                        | **RDS SQL Server** (owner decision 11.3). Carry the source tier — DTU or vCore — into `aws_config` as the sizing input                                       |
| `Microsoft.Sql/servers`                                                  | the RDS instance hosting its databases; usually a config source rather than its own entry                                                                    |
| `Microsoft.DocumentDB/databaseAccounts` (Core / SQL API)                 | **DynamoDB** — see §4                                                                                                                                        |
| `Microsoft.Cache/redisEnterprise`                                        | ElastiCache Redis, or MemoryDB when durability is required                                                                                                   |
| `Microsoft.Search/searchServices`                                        | routed to `analytics.md` (OpenSearch), not here                                                                                                              |

The four non-Core Cosmos APIs are **fast-path rows**, not rubric decisions — Mongo →
DocumentDB, Cassandra → Keyspaces, Gremlin → Neptune, Table → DynamoDB. The wire protocol
determines the only drop-in target, so they never reach this file.

## 4. Cosmos Core (SQL) API → DynamoDB

The one Cosmos surface with real depth, and the one where the conversion is
assumption-sensitive enough that the caveat matters more than the number.

**RU/s → capacity.** Convert with the divisors in
`knowledge/design/cosmos-dynamodb-conversion.json`, then apply the write-percentage and
consistency multipliers. **State the assumed read/write split in the rationale**, because
the result moves by multiples with it: a 50/50 split and a 95/5 split on the same RU/s
produce very different WCU/RCU, and the customer is the only one who knows which they are.

**Serverless and autoscale sources.** A serverless Cosmos account has no provisioned RU/s
to convert — use consumption data if present, otherwise say so and recommend DynamoDB
on-demand rather than inventing a throughput figure. An autoscale account's `max_throughput`
is a ceiling, not a demand.

**What does not convert.** Cosmos's five consistency levels do not map onto DynamoDB's
two. Session consistency in particular has no equivalent and is the most common source
setting — record it as a finding rather than silently choosing eventually-consistent
reads, because the application may depend on read-your-writes.

## 5. Cluster context and simplicity

The remaining criteria, in order, and both are usually quiet for databases:

- **Cluster context** — a database in a cluster whose primary is already Aurora probably
  belongs on Aurora too; one engine is cheaper to operate than two. Skip when
  `pattern_status` is `catalog_absent` or `unclassified`.
- **Simplicity** — prefer RDS to Aurora when both survive. Aurora is a different
  operational model (cluster endpoints, reader scaling) and the migration is not the
  moment to take that on unless the availability answer required it.

## 6. Right-sizing — post-selection

- **No utilization** → dev-tier default from
  `knowledge/design/flexible-server-rds-sizing.json`, `confidence: inferred`. SKILL.md's
  `db.t4g.micro`-class posture applies — but note **`db.t4g` is Graviton**, and for RDS
  SQL Server it is not available: use `db.t3` there (`graviton.md`'s escape path).
- **P95 available** → bands + aggressiveness slider from
  `knowledge/estimate/rightsizing-thresholds.json`, `confidence: measured`, citing the
  evidence.
- **Storage** — carry `storage_mb` across as allocated GiB and keep the source's growth
  headroom. Do not right-size storage down from utilization: shrinking allocated storage
  is not an online operation on RDS, so a too-small guess is expensive to undo.
- **Backup retention** — carry `backup_retention_days` across verbatim. It is a stated
  requirement, not a sizing knob.

## 7. Output

Per `schema-design-aws.md` § `services[]`, with `rubric_applied: "database.md"` and a
`rationale` naming which criterion or gate fired. When the availability gate decided the
family, **say so explicitly** — "Aurora PostgreSQL, because you selected multi-az-ha"
tells the customer which of their own answers to revisit if the cost surprises them.

## Status — build step 5

Implemented for Postgres/MySQL Flexible Server, Single Server, Azure SQL Database, Cosmos
Core, and Redis Enterprise. `database-specialist-gate.md` content lives in
`specialist-gates.md`. The sizing tables now exist:
`knowledge/design/flexible-server-rds-sizing.json` for Postgres and MySQL Flexible Server,
and `knowledge/design/cosmos-dynamodb-conversion.json` for the Cosmos Core API. Look the
SKU up and stamp `sizing_provenance: "table"`; for a SKU the table does not carry, stamp
`model_prior`, warn, and say the number is not sourced. The Cosmos conversion additionally
REFUSES to run without the read/write split, which is an ESSENTIAL Clarify answer with no
default — an absent split means the conversion is unavailable, not that it should be
guessed.
