# Mode 4 — SQL to Keyspaces migration

Use when the user provides SQL `CREATE TABLE` statements and wants a Keyspaces migration plan. This mode translates the relational schema into three Keyspaces data models, prices each via `calculate.ts`, and recommends the best fit.

## Step 1 — Parse the SQL

Extract:

- **Tables** — name, columns (name + SQL type), primary key(s), UNIQUE constraints.
- **Foreign keys** — `(source_table, source_col)` → `(target_table, target_col)`.
- **Access queries** — any `SELECT` statements provided. These drive partition-key choice.

## Step 2 — Estimate field sizes

| SQL type | Bytes |
|---|---|
| `BOOL` / `BOOLEAN` | 1 |
| `SMALLINT` | 2 |
| `INT` / `INTEGER` / `SERIAL` / `DATE` / `FLOAT` / `REAL` | 4 |
| `BIGINT` / `DOUBLE` / `TIMESTAMP` / `DATETIME` / `DECIMAL` / `NUMERIC` | 8 |
| `UUID` | 16 |
| `VARCHAR(n)` / `CHAR(n)` | n |
| `VARCHAR` / `TEXT` / `CLOB` (no length) | 64 |
| `BLOB` / `BINARY` | 512 |

`row_size_bytes` per table = sum of all column byte sizes.

## Step 3 — Ask for workload inputs

If not already supplied, ask for:

- **Rows per table** (integer).
- **Reads/s** and **writes/s** — per table, or combined if the user cannot split.
- **AWS region** (default `us-east-1`).

Storage-only reasoning misses the dominant pricing driver, so do not skip rates.

## Step 4 — Apply the three strategies

### Option A — Full denormalization

Merge all foreign-key-related tables into one.

- `merged_row_size_bytes` = sum of all unique column sizes (deduplicate FK columns).
- `merged_row_count`      = row count of the many-side table (the table with the FK column). For 1:many relationships, this equals the child table row count since each child row maps to exactly one parent. For many:many relationships through a join table, use the join table row count.
- `storage_gb`            = `(merged_row_count × merged_row_size_bytes) / (1024^3)`.
- `reads_per_sec`  = sum of reads across original tables.
- `writes_per_sec` = sum of writes across original tables.
- **CQL:** one merged table. Partition key = the FK column matching the access query. Clustering key = child-table PK.

### Option B — Normalized with lookup tables

Keep original tables; add one lookup table per FK for application-side joins.

- **Original tables:** map 1:1 to CQL. `storage_gb = (row_count × row_size_bytes) / 1024^3` per table.
- **Lookup table** per FK `(source.col → target.pk)`, named `target_by_source`:
  - Columns: FK column + target PK column.
  - `lookup_row_size_bytes` = size(FK col) + size(target PK col).
  - `lookup_storage_gb` = `(target_row_count × lookup_row_size_bytes) / 1024^3`.
- `total_storage_gb`  = sum of original + all lookup storage.
- `reads_per_sec`     = sum of original reads + (FK lookups required per query × reads using them).
- `writes_per_sec`    = sum of original writes + (1 extra write per lookup table per insert).
- **CQL:** original tables unchanged + one lookup table per FK.

### Option C — Denormalized with reverse index

Same merged table as Option A, plus one reverse-index table per non-PK FK column.

- Merged table — identical to Option A.
- Reverse index per non-PK FK column — partition key = FK col, clustering key = merged PK, all merged columns duplicated (full copy).
  - `reverse_row_size_bytes` = `merged_row_size_bytes`.
  - `reverse_row_count`      = `merged_row_count`.
- `total_storage_gb`  = `merged_storage_gb × (1 + number_of_reverse_indexes)`.
- `reads_per_sec`     = same as Option A (no extra read; correct table picked per query).
- `writes_per_sec`    = `Option A writes_per_sec × (1 + number_of_reverse_indexes)`.
- **CQL:** merged table + one reverse-index table per non-PK FK column.

## Step 5 — Price each option

```bash
cd scripts
npx ts-node --project tsconfig.scripts.json calculate.ts \
  <region> <reads/s> <writes/s> <avg_row_size_bytes> <storage_gb> 0 false \
  | tee /tmp/keyspaces-sql-optionA.json

# Repeat for B → /tmp/keyspaces-sql-optionB.json
# Repeat for C → /tmp/keyspaces-sql-optionC.json
```

Extract `provisioned.total`, `on_demand.total`, and `provisioned_savings_plan.total` from each JSON.

## Step 6 — Present the comparison

### Three-model summary table

| | Option A — Denorm | Option B — Normalized | Option C — Reverse Index |
|---|---|---|---|
| Storage | — | — | — |
| Reads/s | — | — | — |
| Writes/s | — | — | — |
| Bytes/row (avg) | — | — | — |
| Backup | off / on | off / on | off / on |
| Lookups per query | — | — | — |
| **Provisioned + Savings Plan/mo** | **$—** | **$—** | **$—** |
| **On-demand + Savings Plan/mo** | **$—** | **$—** | **$—** |

- **Lookups per query** — number of separate Keyspaces reads required to satisfy one user-facing query (1 = single-table read; 2 = lookup + data; N = lookup returns N keys each needing its own read).
- **Backup** — reflects the `pitr_enabled` input (`PITR on` / `off`).

### CQL

Generate the full table definitions for each option.

### Recommendation

Pick based on:

- **Cost** — cheapest total at the user's read/write mix.
- **Query fit** — does the primary access path match the partition key?
- **Write amplification** — Options B and C add writes (B: lookup writes; C: N-way fanout for each reverse index).
- **Storage trade-offs** — Option C can 2× or 3× storage versus A.

State the recommended option first, then the one-line reason.

## Consolidated PDF

After displaying the comparison, ask the user whether they want a PDF. If yes, use one invocation with all three `--input` flags (see [pdf-reporting.md](pdf-reporting.md)):

```bash
npx ts-node --project tsconfig.scripts.json generate-pdf.ts \
  --input /tmp/keyspaces-sql-optionA.json --label "Option A — Denorm" \
  --input /tmp/keyspaces-sql-optionB.json --label "Option B — Normalized" \
  --input /tmp/keyspaces-sql-optionC.json --label "Option C — Reverse Index" \
  --output /tmp/keyspaces-sql-comparison.pdf
```
