# Mode 3 — Compatibility check

Use when the user asks whether a Cassandra schema or workload will run on Amazon Keyspaces, without wanting a cost estimate. For combined pricing + compatibility, run Mode 2 instead — it auto-populates the compatibility block.

## Inputs

At least one of:

- `--schema <path.cql>` — CQL DDL (`DESCRIBE SCHEMA` output or hand-written).
- `--prepared <path.ndjson>` — `system.prepared_statements` export as NDJSON (one JSON object per line).

Both may be supplied together. CQL may also be piped on stdin when `--prepared` is absent.

## Command

```bash
cd scripts

# Schema file
npx ts-node --project tsconfig.scripts.json check-compatibility.ts \
  --schema /tmp/schema.cql | tee /tmp/keyspaces-compat.json

# Prepared statements file
npx ts-node --project tsconfig.scripts.json check-compatibility.ts \
  --prepared /tmp/prepared_statements.ndjson | tee /tmp/keyspaces-compat.json

# Both
npx ts-node --project tsconfig.scripts.json check-compatibility.ts \
  --schema /tmp/schema.cql --prepared /tmp/prepared_statements.ndjson \
  | tee /tmp/keyspaces-compat.json

# Schema on stdin (only valid without --prepared)
echo "CREATE TABLE app.users (id uuid PRIMARY KEY, email text);" \
  | npx ts-node --project tsconfig.scripts.json check-compatibility.ts \
  | tee /tmp/keyspaces-compat.json
```

## What it detects

See [keyspaces-unsupported-features.md](keyspaces-unsupported-features.md) for the authoritative list and migration guidance. The tool flags:

**From schema (CQL DDL):**

- `CREATE INDEX` — secondary indexes (per table).
- `CREATE TRIGGER` — triggers (per table).
- `CREATE MATERIALIZED VIEW` — attached to base table.
- `CREATE FUNCTION` — user-defined functions (counted globally).
- `CREATE AGGREGATE` — user-defined aggregates (counted globally).

**From prepared statements:**

- **LWT inside `BEGIN UNLOGGED BATCH`** — any conditional (`IF NOT EXISTS`, `IF EXISTS`, `IF <col>=…`) inside an unlogged batch.
- **Aggregate calls** — `COUNT(`, `MIN(`, `MAX(`, `SUM(`, `AVG(` anywhere in a `SELECT`.
- **Per-table `USING TTL`** — informational only, not an issue; used by Mode 2 to mark tables as TTL-driven for pricing.

UDF usage is intentionally not detected from prepared statements — `CREATE FUNCTION` in schema is the source of truth.

## Output shape

```json
{
  "source": "compatibility-check",
  "input":   { "schema": "<path or null>", "prepared": "<path or null>" },
  "has_issues": true | false,
  "summary": {
    "total_issues": N,
    "schema": {
      "total_issues": N,
      "keyspaces_affected": N,
      "tables_affected": N,
      "functions": N,
      "aggregates": N
    } | null,
    "query_patterns": {
      "lwt_in_unlogged_batch": N,
      "aggregations": N,
      "ttl_tables": N
    } | null
  },
  "details": {
    "schema": {
      "functions": N,
      "aggregates": N,
      "keyspaces": {
        "<keyspace>": {
          "<table>": {
            "indexes":           ["idx_name", …],
            "triggers":          ["trg_name", …],
            "materializedViews": ["view_name", …]
          }
        }
      }
    } | null,
    "query_patterns": {
      "lwt_in_unlogged_batch": [ { "prepared_id": "...", "query_string": "..." } ],
      "aggregations":          [ { "prepared_id": "...", "function": "COUNT", "query_string": "..." } ],
      "ttl_tables":            { "<ks>.<table>": { "uses_ttl": true, "ttl_values": [3600, 86400] } }
    } | null
  }
}
```

## Display rules

Compatibility is binary. Every detected feature is **not supported**. Do not hedge with qualifiers like "supported with restrictions", "supported with caveats", "works when cardinality is high", or "may cause hot partitions" — those qualifiers do not apply here and mislead customers into building unsupported designs.

Present in this order:

1. **One-line verdict** — if `has_issues` is false, say the schema/workload is compatible with Amazon Keyspaces and stop. Otherwise continue.
2. **Per-keyspace / per-table breakdown** — for every keyspace in `details.schema.keyspaces`, list affected tables and their flagged features. Show the feature name (index / trigger / materialized view) and the object name.
3. **Global counts** — `details.schema.functions` and `details.schema.aggregates` (numbers only; names are not captured).
4. **Per-query breakdown** — for each entry in `details.query_patterns.lwt_in_unlogged_batch` and `.aggregations`, show the offending `query_string` truncated to roughly 200 characters. Include the `prepared_id` to help the user find it in their codebase.
5. **`ttl_tables` (informational)** — list as "tables using `USING TTL`: …" so the user can verify the TTL pricing signal Mode 2 uses.
6. **Migration guidance** — for each flagged category, offer guidance from [keyspaces-unsupported-features.md](keyspaces-unsupported-features.md). Keep guidance to *what to do instead*, not *why the feature is limited*.

## PDF generation is not supported for Mode 3

Mode 3 produces a compatibility report only. `generate-pdf.ts` expects pricing JSON and will fail on a compatibility JSON. If the user wants a combined compatibility + pricing PDF, direct them to Mode 2 — it includes compatibility automatically when `schema` or `prepared` is supplied.

## Follow-ups

**"Can I automate this in CI?"** — yes; `check-compatibility.ts` returns non-zero exit only on usage errors, not on `has_issues`. Check `.has_issues` in the JSON to fail a pipeline.

**"How do I fix each issue?"** — see migration guidance in [keyspaces-unsupported-features.md](keyspaces-unsupported-features.md).

**"Does this catch everything?"** — no. Data-type and CQL-syntax-level differences (the full functional-differences list) are not checked. Link the user to the official [Keyspaces functional differences page](https://docs.aws.amazon.com/keyspaces/latest/devguide/functional-differences.html).
