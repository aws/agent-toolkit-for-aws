---
_fragment: database
_of_phase: clarify
_contributes:
  - preferences.json (data section)
---

# Clarify — Database

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.
>
> **This fragment asks nothing.** It returns rows; `clarify-assemble.md` presents them.

Fires when the inventory contains a relational database, a cache, or a Cosmos account.
Category D.

**The availability row (Q-D1) is the most consequential row in the entire phase.** It
selects RDS versus Aurora, which is roughly a 2× difference on the database line, and it is
the one answer that cannot be read from the estate.

## Step 1: Extract before proposing

| Read from the inventory                                                           | Resolves                                                                       |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| each flexible server's `high_availability.mode` and `zone`                        | the source's HA posture — **context for Q-D1, never the answer**               |
| `sku_name`, `storage_mb`, `version`, `backup_retention_days`                      | sizing inputs and the engine-version floor                                     |
| `Microsoft.Sql/servers/databases` `sku_name` (DTU or vCore) and `elastic_pool_id` | the Azure SQL tier; an `elastic_pool_id` routes to the specialist gate instead |
| Cosmos `kind` / `capabilities`                                                    | which API, and therefore whether Q-D5 fires at all                             |
| Cosmos `throughput` and per-container `throughput`                                | the RU/s figure Q-D5 converts                                                  |

## Step 2: The rows

### Q-D1 — Availability — the override gate's input

**Disposition:**

- **ESSENTIAL** when any source database is zone-redundant or HA-enabled. You must not
  silently downgrade resilience the customer is already paying for.
- PROPOSED otherwise. **Default:** `single-az`.

```
What availability do your databases need on AWS?

[A] Single-AZ — one instance, automated backups           (dev-tier default)
[B] Multi-AZ — synchronous standby, automatic failover, roughly 2x the cost
[C] Multi-AZ with high availability — Aurora, fastest failover
[D] Multi-region — Aurora Global Database
```

Interpret → `data.availability`:

| Answer | Write          | When `global.user_geography` is not `global`                                                                                                                                   |
| ------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [A]    | `single-az`    | —                                                                                                                                                                              |
| [B]    | `multi-az`     | —                                                                                                                                                                              |
| [C]    | `multi-az-ha`  | —                                                                                                                                                                              |
| [D]    | `multi-region` | Still write `multi-region` (the user picked [D]). Design honors it and says in the rationale that global infrastructure was requested without global users (`database.md` §1). |

Canonical `clarify-availability.md`: Catastrophic + `user_geography: "global"` is the
combination that **warrants** Aurora Global. Do not auto-upgrade [C] to `multi-region`
because geography is global — that would invent Aurora Global without the recorded
availability answer. Do not refuse [D] when geography is `single-region` / `multi-region`.

**Consequence line (PROPOSED case):** _Assuming single-AZ → the smallest defensible
database line. Multi-AZ roughly doubles it and buys automatic failover; Aurora is a
different operational model again._

**Consequence line (ESSENTIAL case — say this instead):** _Your `pg-contoso-store` is
configured `ZoneRedundant` with a standby in zone 2 today. We will not assume you want to
keep paying for that, and we will not assume you want to give it up. This one needs an
answer._

Two rules, and both matter:

1. **Do not read the source's HA setting as the answer.** It tells you what they _bought_,
   not what they _need_. Zone-redundancy is frequently a default nobody chose, and plenty
   of single-zone databases are load-bearing.
2. **When no answer is given, the default is `single-az`, explicitly not Aurora.**
   Inferring Aurora from the source's HA inflates the estimate with no visible cause, and
   the customer has no way to see which of their own inputs drove it.

Either way, if the source is zone-redundant and the answer resolves to single-AZ, Design
emits an `availability_downgrade_from_source` finding — the downgrade is a decision, so it
gets said out loud rather than buried in a sizing table.

`database.md` §1 turns this row into the RDS-versus-Aurora family selection as a
**post-rubric override**: it beats whatever the six criteria would have chosen, because
availability is never inferable from configuration.

### Q-D2 — Database cutover — **ESSENTIAL**

**Disposition:** ESSENTIAL when any relational database is present. **No default.**

```
How should the data move?

[A] AWS DMS with continuous replication — near-zero downtime,
    more setup, needs logical replication enabled on the source
[B] Dump and restore during a maintenance window — simpler,
    downtime proportional to database size
```

No default, for the same reason as the VM cutover question: the two produce **different
runbooks**, not different numbers. DMS is a replication project with a validation phase; a
dump/restore is a scheduled outage. Guessing makes every Generate artifact wrong.

Pair the row with the extracted size so the choice is informed — a 60 GiB database and a
6 TiB database make [B] a very different proposition.

### Q-D3 — Traffic pattern

**Disposition:** DETECTED when every source is a burstable/dev tier (the answer is
`steady`); PROPOSED otherwise. **Default:** `steady`.

```
[A] Steady — roughly constant query load                      (default)
[B] Read-heavy with peaks — would benefit from read replicas
[C] Spiky / unpredictable
```

**Consequence line:** _Assuming steady → sized from current capacity, no read replicas.
Read-heavy workloads add replicas, which adds cost but usually less than upsizing the
primary._

### Q-D4 — Storage I/O

**Disposition:** PROPOSED. **Default:** `medium`.

```
[A] Low        [B] Medium — gp3 general purpose        (default)        [C] High — needs provisioned IOPS
```

**Consequence line:** _Assuming medium I/O → gp3 storage. High-IOPS workloads need io2 or
provisioned IOPS, which is a materially different storage line._

**Storage size is never right-sized downward from utilization.** Shrinking allocated
storage is not an online operation on RDS, so a too-small guess is expensive to undo.
Carry `storage_mb` across as allocated GiB and keep the source's headroom.

### Q-D5 — Cosmos read/write split — **ESSENTIAL when it fires**

**Disposition:** ESSENTIAL when a Cosmos **Core (SQL) API** account is present; **N/A**
otherwise — the four wire-protocol APIs (Mongo, Cassandra, Gremlin, Table) are fast-path
rows and need no conversion.

```
Your Cosmos account cosmos-contoso-catalog is provisioned at 4,000 RU/s.
Converting that to DynamoDB capacity depends entirely on the read/write mix.

[A] Read-heavy — roughly 90% reads
[B] Balanced — roughly 50/50
[C] Write-heavy — roughly 90% writes
```

No default, because **the answer moves the result by multiples.** A write costs
substantially more RU than an eventually-consistent read, so the same 4,000 RU/s converts
to very different WCU/RCU depending on the mix — and only the customer knows theirs. A
silent assumption here produces a confident number that can be wrong by 5×.

Also record, as findings rather than questions:

- **Consistency does not convert.** Cosmos has five levels, DynamoDB has two. Session
  consistency in particular has no equivalent and is the commonest source setting, so the
  application may depend on read-your-writes.
- **A serverless Cosmos account has no provisioned RU/s to convert.** Recommend DynamoDB
  on-demand and say so, rather than inventing a throughput figure. An autoscale account's
  `max_throughput` is a ceiling, not a demand.

### Q-D6 — Redis module usage

**Disposition:** DETECTED when the source is `Microsoft.Cache/Redis` (plain Azure Cache
for Redis has no modules — the answer is no); PROPOSED when it is
`Microsoft.Cache/redisEnterprise`. **Default:** `false`.

**Consequence line:** _Assuming no Redis modules → ElastiCache Redis is a drop-in.
RediSearch, RedisJSON and RedisTimeSeries have no ElastiCache or MemoryDB equivalent, and
that is a feature gap rather than a sizing difference._

## Step 3: Rows returned

```jsonc
"data": {
  "availability":      { "disposition": "ESSENTIAL", "value": null, "default": null,
                         "source_ha_context": "pg-contoso-store: ZoneRedundant, standby zone 2" },
  "db_cutover":        { "disposition": "ESSENTIAL", "value": null, "default": null },
  "traffic_pattern":   { "disposition": "PROPOSED",  "value": null, "default": "steady" },
  "storage_io":        { "disposition": "PROPOSED",  "value": null, "default": "medium" },
  "cosmos_rw_split":   { "disposition": "N/A",       "value": null, "default": null },
  "redis_modules":     { "disposition": "DETECTED",  "value": false, "default": false }
}
```

`source_ha_context` is carried so the assembler can print the ESSENTIAL row's consequence
line with the actual resource named. A generic "your source may be HA" is ignorable; naming
the server is not.

## Who consumes these

| Row                             | Consumer                                                               |
| ------------------------------- | ---------------------------------------------------------------------- |
| `availability`                  | `database.md` §1 — the post-rubric override that selects RDS vs Aurora |
| `db_cutover`                    | Generate's migration runbook, and the DMS-versus-dump tooling choice   |
| `traffic_pattern`, `storage_io` | Estimate's instance class and storage type                             |
| `cosmos_rw_split`               | `database.md` §4's RU/s → WCU/RCU conversion                           |
| `redis_modules`                 | `database.md`'s ElastiCache eliminator                                 |

## Status — build step 5

Implemented for Postgres/MySQL Flexible Server, Single Server, Azure SQL Database, Cosmos
Core, and Redis. Managed Instance and elastic pools never reach this fragment — they are
specialist gates, and the sheet should say they were deferred rather than leaving them
silent.
