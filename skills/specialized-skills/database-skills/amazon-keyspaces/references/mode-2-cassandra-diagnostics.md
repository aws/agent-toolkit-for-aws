# Mode 2 — Cassandra diagnostics

Use when the user has a running Cassandra cluster (or a DataStax / ScyllaDB deployment that can produce Cassandra-compatible diagnostics). This mode derives reads/writes per second from cumulative `nodetool info` counters and keyspace sizing from `nodetool tablestats` — neither can be guessed.

If either `tablestats` or `info` cannot be captured, fall back to Mode 1.

## Intake table

Each **ID** matches a `parse-cassandra.ts` flag (`--<id>`) when passing paths explicitly.

| ID | Captures | Run on | Output | If missing — ask | Default / escalation |
|---|---|---|---|---|---|
| `tablestats` | Live space + per-column-family details | any one node | `tablestats.txt` | — | **Mandatory.** Recapture. Without it, use Mode 1 — `parse-cassandra.ts` exits without `--tablestats`. A single representative tablestats file is sufficient; throughput is scaled by node count from `--info` files. |
| `info` | DC, host id, uptime; used with tablestats counters to derive reads/writes per second | every node | `info.txt` | — | **Mandatory.** Without it, use Mode 1 — RPS cannot be derived. |
| `status` | DC list, node count per DC | any one node | `status.txt` | How many DCs in the cluster? How many nodes per DC? | Capture preferred. Otherwise use the answers, or group `info` files by DC. If topology cannot be established, use Mode 1. |
| `schema` | DDL — feeds compatibility + replication factor | any one node | `schema.cql` | What replication factor for application keyspaces (per DC)? | If absent, parser uses RF=3 internally. Ask the user to confirm so intent matches estimate. |
| `rowsize` | Average row size per table | any one node | `rowsize.txt` | — | Default `1024` bytes. No further questions. |
| `prepared` | Prepared statements — drives compatibility (LWT-in-batch, aggregations) and the `USING TTL` pricing signal | any one node | `prepared_statements.ndjson` | — | Omit `--prepared`. No further questions. |

## Required vs optional

**Mandatory:** `tablestats` AND at least one `info` file.

**Strongly recommended:** `status` (topology), `schema` (compatibility + RF), `prepared` (compatibility signal + TTL pricing).

**Optional:** `rowsize` (per-table accuracy — defaults to 1024 bytes when absent).

## Capture commands

See [cassandra-capture-commands.md](cassandra-capture-commands.md) for the full set with `<auth>` shorthand.

## Running the parser

Prefer `--dir` auto-detection — the parser's filename detectors (`isTablestatsFile`, `isInfoFile`, `isStatusFile`, `isSchemaFile`, `isRowSizeFile`, `isPreparedStatementsFile`) classify each file regardless of naming.

```bash
# Directory auto-detection (recommended)
cd scripts
npx ts-node --project tsconfig.scripts.json parse-cassandra.ts \
  --dir /path/to/diagnostics --region us-east-1 [--pitr] \
  | tee /tmp/keyspaces-calc.json

# Individual files (explicit)
npx ts-node --project tsconfig.scripts.json parse-cassandra.ts \
  --region us-east-1 \
  --tablestats tablestats.txt \
  --info node1-info.txt --info node2-info.txt \
  [--status status.txt] [--schema schema.cql] \
  [--rowsize rowsize.txt] [--prepared prepared.ndjson] \
  [--pitr] | tee /tmp/keyspaces-calc.json
```

Repeat `--info` once per node. When both `--dir` and explicit flags are provided, explicit wins.

## Region selection

Pick `--region` by priority:

1. The DC name in `status` if it matches an AWS region (`us-east-1`, `eu-west-1`, …).
2. The `Datacenter` field in `nodetool info`.
3. The user's stated target region.
4. Default `us-east-1`.

Pass `--region` explicitly whenever inference is wrong or unclear.

## Output

Same shape as Mode 1, plus:

- `source: "cassandra-diagnostic-files"`
- `datacenters` — array of `{ name, nodeCount }` per DC.
- `per_datacenter` — cost breakdown per DC.
- `compatibility` — automatically populated when `--schema` or `--prepared` was supplied (or detected in `--dir`). Shape:

  ```json
  {
    "has_issues": true | false,
    "summary": {
      "total_issues": N,
      "schema":         { ... or null },
      "query_patterns": { ... or null }
    },
    "details": { "schema": { ... }, "query_patterns": { ... } }
  }
  ```

Surface the `compatibility` block when present — see [mode-3-compatibility.md](mode-3-compatibility.md) for display rules.

## Prepared-statement signal

A `prepared_statements.ndjson` capture changes two things:

1. **Compatibility:** detects LWT inside `BEGIN UNLOGGED BATCH`, aggregates (`COUNT`/`MIN`/`MAX`/`SUM`/`AVG`), and calls to user-defined functions (when `schema` is also supplied).
2. **Pricing:** `INSERT … USING TTL` and `UPDATE … USING TTL` mark tables as fully TTL-driven for write accounting, even when DDL lacks `default_time_to_live`. Tables with `default_time_to_live` already follow the `rowsize`-based TTL path.

## Displaying results

Present in this order:

1. **Cluster summary** — DCs, node count per DC, region(s) inferred.
2. **Per-keyspace breakdown** — keyspace name, RF, storage, reads/s, writes/s.
3. **Two-column cost table** (same as Mode 1).
4. **Recommendation** — cheaper mode.
5. **Compatibility findings** if `compatibility.has_issues` is true.
6. Offer PDF per [pdf-reporting.md](pdf-reporting.md).

## Multi-cluster or re-runs

For two or more separate clusters, run `parse-cassandra.ts` once per cluster, writing to distinct `/tmp/keyspaces-*.json` files. Then a single `generate-pdf.ts` invocation with multiple `--input` flags produces a consolidated comparison PDF.
