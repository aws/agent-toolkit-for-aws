# Mode 1 — Manual inputs

Use this mode when the user does not have a running Cassandra cluster, or when they prefer to type traffic estimates directly.

If the user mentions a running Cassandra cluster or DataStax deployment, always offer Mode 2 first — diagnostic data produces a more accurate estimate. Fall back to Mode 1 only when diagnostic captures (`nodetool tablestats` + `nodetool info`) are unavailable.

## Parameters

All positional, in this exact order:

| Position | Name | Required | Format | Notes |
|---|---|---|---|---|
| 1 | region | yes | AWS region code (e.g. `us-east-1`, `eu-west-1`, `ap-southeast-2`) | Must exist in `assets/data/regions.json`. |
| 2 | reads_per_second | yes | integer ≥ 0 | Strongly-consistent reads. Halved in output for eventual-consistency pricing. |
| 3 | writes_per_second | yes | integer ≥ 0 | Single-row inserts/updates. Does not include TTL auto-deletes (column 6). |
| 4 | avg_row_size_bytes | yes | integer | Typical 256-4096. Include partition key, clustering key, and all column bytes; exclude internal Cassandra overhead. Default `1024` only when truly unknown. |
| 5 | storage_gb | yes | number | Single-replica compressed storage in GB. Keyspaces applies replication internally at RF=3; pass the compressed single-replica figure. |
| 6 | ttl_deletes_per_second | no (default `0`) | integer ≥ 0 | TTL-expiring writes per second. Priced at the same rate as regular writes (writes are billed; reads/deletes are implicit). |
| 7 | pitr_enabled | no (default `false`) | `true` / `false` | Backups/point-in-time-recovery. Adds a per-GB-month surcharge. |

## Command

```bash
cd scripts
npx ts-node --project tsconfig.scripts.json calculate.ts \
  <region> <reads/s> <writes/s> <rowSizeBytes> <storageGB> [ttl/s] [pitr] \
  | tee /tmp/keyspaces-calc.json
```

Example:

```bash
npx ts-node --project tsconfig.scripts.json calculate.ts \
  us-east-1 1000 500 1024 100 0 false | tee /tmp/keyspaces-calc.json
```

## Output shape

```json
{
  "region": { "short": "us-east-1", "long": "US East (N. Virginia)" },
  "inputs": { ... the 7 parameters ... },
  "units_per_operation": { "write": 1, "read": 1, "ttl": 1 },
  "on_demand":               { "reads_strong": …, "reads_eventual": …, "writes": …, "ttl_deletes": …, "storage": …, "backup": …, "total": … },
  "provisioned":             { ... same shape ... },
  "savings_plan_available":  true | false,
  "on_demand_savings_plan":  { ... same shape or null ... },
  "provisioned_savings_plan":{ ... same shape or null ... },
  "report_data":             { datacenters, regions, estimateResults, pricing }
}
```

Values are monthly US dollars unless otherwise noted.

## Units-per-operation

Keyspaces bills by the capacity unit, not the raw row count. One **Write Capacity Unit (WCU)** covers up to 1 KB written; one **Read Capacity Unit (RCU)** covers up to 4 KB read (strongly consistent) or 4 KB per 2 RCUs (eventually consistent). Rows larger than the threshold consume more units per operation.

`units_per_operation.write` — ceil(row_size_bytes / 1024).
`units_per_operation.read` — ceil(row_size_bytes / 4096).
`units_per_operation.ttl`  — same as write.

Surface these when explaining why a row size change (for example going from 1024 to 2048 bytes) flips the recommendation between on-demand and provisioned.

## Presenting the result

Show the user:

1. A one-row **inputs summary** — region, reads/s, writes/s, row size, storage, PITR.
2. A **two-column cost table** — On-demand vs Provisioned, with line items for reads, writes, TTL deletes, storage, and backup, totaling at the bottom. Include a Savings Plan row when `savings_plan_available` is true.
3. A clear **recommendation** — whichever mode is cheaper at the user's stated traffic pattern, with a one-line reason tied to the read/write ratio.
4. A line noting the user may generate a PDF via Step 6 if wanted.

## Common follow-ups

**"What if I double the writes?"** — rerun with the new value; writes are linear in cost for both pricing modes.

**"What if I add PITR later?"** — rerun with `true` in position 7; PITR cost scales with `storage_gb` only.

**"Should I use on-demand or provisioned?"** — Provisioned wins for steady, predictable traffic (utilization > 18% of peak). On-demand wins for spiky or unknown traffic. The script already applies the breakeven; state the recommendation from the totals, then cite which mode won.

**"Can you compare two traffic scenarios?"** — run `calculate.ts` twice to different `/tmp/*.json` paths, then a single `generate-pdf.ts --input A --input B` to produce a consolidated PDF (see [pdf-reporting.md](pdf-reporting.md)).
