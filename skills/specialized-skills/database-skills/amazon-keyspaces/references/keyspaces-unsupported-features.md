# Keyspaces unsupported features

Authoritative list of Apache Cassandra features that Amazon Keyspaces does **not** support. Cited by Modes 2 and 3. Compatibility is binary — every listed feature is either supported or it is not; do not describe detected features as "supported with caveats".

Source: [Amazon Keyspaces functional differences from Cassandra](https://docs.aws.amazon.com/keyspaces/latest/devguide/functional-differences.html).

## Detected by the compatibility tool

The `check-compatibility.ts` script flags these specific features when they appear in CQL schema or prepared statements.

### Secondary indexes (`CREATE INDEX`)

Not supported. Native `CREATE INDEX` statements have no equivalent in Keyspaces.

**Migration:** create a second table keyed by the column you wanted to query on. The application writes to both tables. This is the standard Cassandra denormalization pattern even when secondary indexes are available, because they scale poorly in Cassandra too.

### Triggers (`CREATE TRIGGER`)

Not supported.

**Migration:** move the trigger logic into the application layer or into a stream consumer (for example, an AWS Lambda function reacting to DynamoDB Streams on a mirrored table, or a dedicated CDC pipeline).

### Materialized views (`CREATE MATERIALIZED VIEW`)

Not supported.

**Migration:** maintain a second table in the application via dual-write. Key the second table for the alternate access pattern. Accept eventual consistency between the two tables — Cassandra materialized views have the same tradeoff.

### User-defined functions (`CREATE FUNCTION`)

Not supported.

**Migration:** move the computation client-side (application logic) or into an ETL / stream-processing step (for example, AWS Glue, AWS Lambda, Amazon Kinesis Data Analytics).

### User-defined aggregates (`CREATE AGGREGATE`)

Not supported.

**Migration:** same as UDFs — compute client-side or in a stream/batch job.

### LWT inside `BEGIN UNLOGGED BATCH`

Not supported. Keyspaces rejects any lightweight-transaction (`IF NOT EXISTS`, `IF EXISTS`, `IF <col>=…`) issued inside an unlogged batch.

**Migration:** issue the LWT as a single-statement conditional outside any batch:

```cql
UPDATE users SET email = 'a@b.c' WHERE id = ? IF email = 'old@b.c';
```

If the application requires atomic multi-row semantics previously achieved via batch+LWT, use application-level coordination (e.g., a state machine or idempotent retries) since neither LOGGED BATCH nor LWT-inside-UNLOGGED-BATCH is supported on Keyspaces.

### Aggregate calls in queries

Keyspaces rejects `COUNT(`, `MIN(`, `MAX(`, `SUM(`, `AVG(` in `SELECT` statements.

**Migration:**

- **COUNT** — maintain a counter table updated by the application on every write.
- **MIN / MAX** — maintain pre-aggregated summary rows, or read the first/last row by clustering-key order.
- **SUM / AVG** — compute client-side from a paginated `SELECT`, or maintain rolled-up summary tables updated by a stream processor.

## Not detected by the tool (but still unsupported or different)

The compatibility tool is a first-pass screen, not a full audit. The following differences are not flagged but still matter — point the user at the [functional differences page](https://docs.aws.amazon.com/keyspaces/latest/devguide/functional-differences.html) for the full catalog.

- **`ALLOW FILTERING`** — supported in Keyspaces but may be rate-limited. The tool does not flag it because it is usable.
- **`TRUNCATE`** — supported in Keyspaces as a throughput-controlled operation.
- **`CREATE CUSTOM INDEX` (SASI, SAI)** — Keyspaces does not support custom index implementations. Detected by the schema parser (the regex matches both `CREATE INDEX` and `CREATE CUSTOM INDEX`), so these will appear as secondary index findings in the compatibility report.
- **`COUNTER` columns** — supported in Keyspaces.
- **Clustering-order-reverse queries** — supported.
- **Lightweight-transaction serial consistency (`LOCAL_SERIAL`)** — supported.
- **Consistency level `EACH_QUORUM`** — not supported on reads.
- **Driver-level features** — some drivers expose Cassandra-specific features (e.g. `tuple` types) that Keyspaces supports only partially. Verify against the driver compatibility page.

## Informational (not issues)

### Tables using `USING TTL`

Not a compatibility issue. The compatibility output reports `query_patterns.ttl_tables` so:

- Mode 2 can treat those tables as TTL-driven for write accounting, even when DDL lacks `default_time_to_live`.
- The user can sanity-check that the TTL pricing signal matches their actual workload.

Display as "tables using `USING TTL`: …" — do not style it as an issue.

## Guidance style

When offering migration advice, keep it to **what to do instead**, not **why the feature is limited**. Customers planning a migration want actionable patterns, not rationale about Keyspaces internals. Compare:

- Good: "Create a separate denormalized table keyed by `email`; the application writes to both tables."
- Bad: "Secondary indexes are not available because Keyspaces uses a serverless architecture that cannot efficiently scan partition replicas for filtering."

The functional-differences page already documents the reasoning for anyone who asks.
