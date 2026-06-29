# DSQL Horizontal Scaling Guide

Part of [DSQL Development Guide](../development-guide.md).

---

## Horizontal Scaling: Best Practice

Aurora DSQL is designed for massive horizontal scale without latency degradation.

> **Note on default limits in this file.** Each "verify via the AWS MCP Server's
> `aws___search_documentation`" reference below assumes the AWS MCP Server is connected. When
> it isn't, fall back to the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/)
> directly, or the defaults table in [SKILL.md](../../SKILL.md).

### Connection Strategy

- **PREFER more concurrent connections with smaller batches** - Higher concurrency typically yields better throughput
- **SHOULD implement connection pooling** - Reuse connections to minimize token overhead; respect 10,000 max per cluster (verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql connection limits`)
- **PREFER initial pool size 10-50 per instance** - Generate fresh IAM auth tokens in pool hooks (e.g., `BeforeConnect`) for 15-minute expiration (verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql authentication token`)
- **MUST set pool max-lifetime under 60 minutes** - DSQL closes connections at the 60-minute cap. Set max-lifetime to ~50 minutes so connections recycle ahead of that and the application never observes a server-initiated close mid-query. Examples: HikariCP `maxLifetime: 3000000` (50 min), psycopg-pool `max_lifetime=3000`, node-postgres pool — pair `idleTimeoutMillis` with a separate lifetime guard.
- **SHOULD retry internal errors with new connection** - Internal errors are retryable, but SHOULD use a new connection from the pool
- **SHOULD implement backoff with jitter** - Avoid thundering herd; scale pools gradually

### Batch Size Optimization

- **PREFER batches of 500-1,000 rows** - Balance throughput and transaction limits (defaults: 3,000 rows, 10 MiB, 5 minutes max — verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql transaction limits`)
- **SHOULD process batches concurrently** - Use multiple connections; consider multiple threads for bulk loading
- **Smaller batches reduce** lock contention, enable better concurrency, fail faster, distribute load evenly

### AVOID Hot Keys

Hot keys (frequently accessed rows) create bottlenecks. For detailed analysis, see ["How to avoid hot keys in Aurora DSQL"](https://marc-bowes.com/dsql-avoid-hot-keys.html).

**Key strategies:**

- **PREFER UUIDs for primary keys** - UUIDs are the recommended default identifier because they avoid coordination; use `gen_random_uuid()` for distributed writes
  - **Sequences and IDENTITY columns are available** when compact, human-readable integer identifiers are needed (e.g., account numbers, reference IDs). CACHE must be specified explicitly as either 1 or >= 65536. See [Choosing Identifier Types](#choosing-identifier-types)
  - **ALWAYS use `GENERATED { ALWAYS | BY DEFAULT } AS IDENTITY`** for auto-incrementing columns (SERIAL is not supported)
- **SHOULD avoid aggregate update patterns** - Year-to-date totals and running counters create hot keys via read-modify-write
  - **RECOMMENDED: Compute aggregates via queries** - Calculate totals with SELECT when needed; eventual consistency often acceptable
- **Accept contention only for genuine constraints** - Inventory management and account balances justify contention; sequential numbering and visit tracking are better served by coordination-free approaches

### Choosing Identifier Types

Aurora DSQL supports both UUID-based identifiers and integer values generated using sequences or IDENTITY columns.

- **UUIDs** can be generated without coordination and are recommended as the default identifier type, especially for primary keys where scalability is important and strict ordering is not required
- **Sequences and IDENTITY columns** generate compact integer values convenient for human-readable identifiers, reporting, and external interfaces. When numeric identifiers are preferred, we recommend using a sequence or IDENTITY column in combination with UUID-based primary keys
- **ALWAYS use `GENERATED { ALWAYS | BY DEFAULT } AS IDENTITY`** for auto-incrementing columns (SERIAL is not supported)

#### Choosing a CACHE Size

**REQUIRED:** Specify CACHE explicitly when creating sequences or identity columns. Supported values are 1 or >= 65536 (verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql sequence cache`).

- **CACHE >= 65536** — suited for high-frequency identifier generation, many concurrent sessions, and workloads that tolerate gaps and ordering effects (e.g., IoT/telemetry ingestion, job run IDs, internal order numbers)
- **CACHE = 1** — suited for low allocation rates where identifiers should follow allocation order more closely and minimizing gaps matters more than throughput (e.g., account numbers, reference numbers)
