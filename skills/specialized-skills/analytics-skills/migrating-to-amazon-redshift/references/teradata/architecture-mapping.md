# Architecture mapping — Teradata → Redshift

> AI-facing knowledge. Pairs with `conversion-rules.md` (the mechanics) — this doc is the
> *why/when* so the AI makes sound physical-design choices, not just syntactic ones.

## Purpose

Teradata and Redshift distribute and organize data very differently. A syntactically correct
DDL conversion can still perform badly if distribution/sort/encoding are chosen poorly. The
conversion rules in `conversion-rules.md` apply the **mechanical** mapping (e.g.
`PRIMARY INDEX (x)` → `DISTKEY(x)`); use this doc to **reason about and improve** those choices
using discovery data (table sizes, cardinality, join/filter patterns).

## Core construct mapping

| Teradata | Redshift | Notes |
|----------|----------|-------|
| `PRIMARY INDEX (col)` (single) | `DISTKEY(col)` | TD PI drives data distribution; DISTKEY is the closest analog. Distribution only — **uniqueness is not enforced** in Redshift. |
| `PRIMARY INDEX (a, b, …)` (multi) | Mechanical default = `DISTSTYLE EVEN` (per `conversion-rules.md`); this optimization pass may upgrade to `DISTKEY(col)` on one high-cardinality join col (or `DISTSTYLE AUTO`) | Redshift DISTKEY is single-column. Don't blindly pick the first PI column. |
| `UNIQUE PRIMARY INDEX (col)` | `DISTKEY(col)` + enforce uniqueness upstream | Redshift does not enforce PK/unique constraints; declare them (informational) for the optimizer, but dedup in the load/ETL. |
| `PARTITION BY RANGE_N(col …)` (PPI) | `SORTKEY(col)` | TD partitions for pruning; Redshift uses sort keys + zone maps for the same effect. Date/timestamp PPIs → date `SORTKEY`. |
| Secondary Index (SI), Hash Index | *(none)* | No direct equivalent. Rely on SORTKEY + zone maps; for selective lookups consider a `SORTKEY` on the filter column. |
| Join Index | Materialized View | Pre-computed/aggregated join → `CREATE MATERIALIZED VIEW`. |
| `SET TABLE` | `CREATE TABLE` + dedup logic | Redshift allows duplicate rows; if SET (no-dupes) semantics matter, dedup on load (`ROW_NUMBER()`/staging). |
| `MULTISET TABLE` | `CREATE TABLE` | Direct — duplicates allowed in both. |
| `COMPRESS` / `COMPRESS (vals)` | `ENCODE az64` / `ENCODE bytedict` | Column compression. Let `ENCODE AUTO` decide unless you have a reason; bytedict suits low-cardinality. |
| `NO PRIMARY INDEX` (NoPI) | `DISTSTYLE EVEN` | Even, round-robin distribution. |
| `COLLECT STATISTICS` | `ANALYZE` | Run after load; Redshift also auto-analyzes. |

## Choosing DISTSTYLE / DISTKEY

Decide per table using discovery data (`inventory.json` sizes + join/filter info):

- **`DISTSTYLE ALL`** — small dimension tables (roughly < ~2–3M rows / a few hundred MB). Replicates
  the table to every node → eliminates redistribution on joins. Best default for dimensions.
- **`DISTKEY(col)`** — large fact tables. Choose the **column most often joined** to other large
  tables (typically the FK to the biggest dimension), with **high cardinality** and **even
  distribution** (avoid skew). Co-locating both sides of a frequent join on the same DISTKEY is
  the biggest performance win.
- **`DISTSTYLE EVEN`** — large tables with no dominant join column, or staging tables.
- **`DISTSTYLE AUTO`** — reasonable default when unsure; Redshift manages it. Prefer explicit KEY/ALL
  once you know the workload (from `performance.md` query analysis).

**Avoid skew:** don't pick a DISTKEY with heavy value concentration (e.g. a status flag, or a
nullable FK with many NULLs) — it overloads one slice.

## Choosing SORTKEY

- Put the **most common range/filter column first** — usually the date/timestamp used in `WHERE`.
  Map TD PPI columns here directly.
- **Compound SORTKEY** (default) — great when queries filter on a leading prefix of the keys.
- **Interleaved SORTKEY** — only when queries filter on different subsets of columns unpredictably;
  higher maintenance cost (`VACUUM REINDEX`). Default to compound.
- Keep it short (1–3 columns).

## Worked example

```sql
-- Teradata
CREATE MULTISET TABLE sales (
    sale_id     INTEGER,
    store_id    INTEGER,
    sale_dt     DATE,
    amount      DECIMAL(15,2) COMPRESS
)
PRIMARY INDEX (store_id)
PARTITION BY RANGE_N(sale_dt BETWEEN DATE '2020-01-01' AND DATE '2030-12-31' EACH INTERVAL '1' MONTH);

-- Redshift (script does the mechanical mapping; reasoning below)
CREATE TABLE sales (
    sale_id   INTEGER,
    store_id  INTEGER,
    sale_dt   DATE,
    amount    DECIMAL(15,2) ENCODE az64
)
DISTKEY(store_id)     -- store_id is the join FK to the store dimension, high-cardinality → good
SORTKEY(sale_dt);     -- from the monthly PPI; most queries filter by date range
```

If `store` is small, also consider `DISTSTYLE ALL` on `store` so the `sales`↔`store` join is local.

## How this pairs with conversion

Applying `conversion-rules.md` gives the mechanical result (single-col PI → DISTKEY, PPI →
SORTKEY, multi-col PI → `DISTSTYLE EVEN`, COMPRESS → ENCODE). Treat that as the **starting
point**, then revisit DISTKEY/DISTSTYLE/SORTKEY per the heuristics above using discovery sizes
and the representative-query analysis from `performance.md`.

## Case sensitivity (collation)

Teradata defaults to **NOT CASESPECIFIC** in Teradata-session mode, so most string
comparisons/joins are case-insensitive; Redshift is **case-sensitive by default**. To preserve
semantics **without** wrapping columns in `UPPER()` (which defeats sort-key use and sargability),
set **`COLLATE CASE_INSENSITIVE`** at the column or database level on tables this migration
creates. Reserve `UPPER()` for ad-hoc queries against pre-existing case-sensitive columns. This
affects most TD string columns — treat it as a default, not an edge case. (See the clause rule in
`conversion-rules.md`.)

## TODO / extend

- Add table-size thresholds for ALL vs KEY tuned to the target node type (RA3 vs serverless).
- Worked examples for a couple of real `BANKING_DW` / `tpcds` tables from discovery output.
