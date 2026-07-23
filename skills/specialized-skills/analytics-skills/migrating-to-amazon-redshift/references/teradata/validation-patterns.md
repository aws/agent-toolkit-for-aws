# Validation patterns

> AI-facing knowledge: comparison strategies the AI uses to **generate** validation scripts.
> Distilled from the proven pre-restructure `tools/validation/data_validator.py`.

## Purpose
Prove the migrated data matches the source, producing
`output/validation/result/validation_report.json` for reporting to consume. Input is the
table list + source counts from `migration_manifest.json` (see `data-migration-patterns.md`).

## The five checks
Run per table; each contributes to the table's pass/fail verdict.

| Check | What it compares | Source SQL | Target SQL |
|-------|------------------|-----------|-----------|
| **row_counts** | total rows | `SELECT COUNT(*) FROM t` | `SELECT COUNT(*) FROM t` |
| **aggregates** | numeric integrity | `SUM/MIN/MAX/AVG(col)`; `COUNT(DISTINCT key)` | same |
| **sample_data** | row-level fidelity | dialect-aware sample (below) | `... ORDER BY key LIMIT n` |
| **schema_comparison** | column parity | `information_schema.columns` (best-effort) | `information_schema.columns` |
| **null_analysis** | NULL distribution | `COUNT(*) WHERE col IS NULL` | same |

A run defaults to all five; callers can select a subset.

## Tolerance & matching rules

- **Counts (row counts, COUNT DISTINCT, NULL counts):** **exact** match required. Any difference is a failure.
- **Numeric aggregates (SUM/MIN/MAX/AVG):** match within a **relative tolerance** to absorb
  float/decimal representation differences between engines:
  - `FLOAT_TOLERANCE = 0.0001` (0.01%).
  - Equal values match. If source is `0`, target must be `0`. Otherwise match when
    `abs(src - tgt) / abs(src) <= FLOAT_TOLERANCE`.
  - Use exact comparison for integer/decimal keys where any drift is meaningful; reserve the
    tolerance for floating aggregates.
- **NULL handling:** a `NULL` aggregate is treated as `0` for comparison (`... or 0`) so an
  empty column doesn't crash the compare; NULL **counts** themselves are compared exactly.

## Sample comparison (dialect-aware)
Teradata and Redshift differ in row-limit syntax, so generate the source query per dialect and
always order by a stable key so both sides return the same rows:

```sql
-- Teradata source
SELECT TOP <n> * FROM <table> ORDER BY <key>;
-- Redshift source (non-teradata) and Redshift target
SELECT * FROM <table> ORDER BY <key> LIMIT <n>;
```

Compare the returned row sets for equality. Default sample size `100`. For stronger coverage,
sample on a hashed key set rather than just the top-N.

## Schema comparison (best-effort)

- Pull columns from `information_schema.columns` (name, type, nullable) ordered by `ordinal_position`.
- Redshift supports `information_schema`; **Teradata may not** — if the source query fails, treat
  schema validation as **best-effort and pass** rather than failing the table (don't block a
  good data load on a metadata-source limitation). Compare column **count** and **names**
  (case-insensitive); type parity is informational given the TD→RS type mapping.

## Status determination
Per table, collect the failing checks; the table is `fail` if **any** check fails, else `pass`.
A check that **raises an exception** marks the table `fail` (never swallow the error silently).

```
failures = [
  row_count   if row_count present and not match,
  aggregates  if any aggregate not match,
  sample_data if sample rows differ,
  schema      if schema mismatch,
  null        if any null count differs,
]
status = "fail" if failures else "pass"
```

`warning` is reserved for non-blocking discrepancies (e.g. best-effort schema skipped).

## `validation_report.json` schema

```json
{
  "tables": [
    {
      "table": "sales.orders",
      "row_count": { "source": 1280344, "target": 1280344, "match": true },
      "aggregates": [
        { "column": "amount", "metric": "SUM", "source": 98123.45, "target": 98123.45, "match": true }
      ],
      "nulls": [
        { "column": "ship_date", "source_nulls": 12, "target_nulls": 12, "match": true }
      ],
      "schema_match": true,
      "sample_match": true,
      "status": "pass"
    }
  ],
  "summary": { "total": 1, "passed": 1, "failed": 0, "warnings": 0 },
  "confidence_score": 1.0
}
```

- `summary` counts tables by status.
- `confidence_score` = `passed / total` (0.0–1.0) — the headline migration-quality number for the report.

## How failures feed back

- A `fail` table is surfaced in the report with its specific failing checks and the source/target
  values, so the operator can see *what* diverged, not just *that* it did.
- Failures map back to `migration_manifest.json` tables → the operator can **re-migrate just the
  failed tables** (full-load is idempotent: truncate + reCOPY) and re-validate, rather than redoing
  the whole run. See `data-migration-patterns.md`.
- The validation phase pauses as `NEEDS_REVIEW` when any table fails and the diff hasn't been
  accepted — see the HITL gate in `orchestration.md`.

## Security & reliability rules

- **Validate every identifier** (table, column, schema) before inlining it into SQL — same
  injection guard as data migration (`^[a-zA-Z_][a-zA-Z0-9_.]*$` for dotted names).
- Use a **read-only** connection on both sides; put a timeout on every query.
- Run aggregate/sample checks on a representative column set (keys + key numeric/date columns) —
  validating every column on every row doesn't scale; counts + targeted aggregates + sampling
  give high confidence at reasonable cost.
- To inspect COPY load failures, use the **documented** views only: `SYS_LOAD_ERROR_DETAIL`
  (Serverless + provisioned) or `STL_LOAD_ERRORS` (provisioned). There is no
  `SVL_LOAD_ERRORS` — do not invent system-view names; if unsure, verify against the
  public system-tables reference before citing one.

## See also

- `data-migration-patterns.md` — produces `migration_manifest.json` (source counts, table list) consumed here.
- `reporting.md` — consumes `validation_report.json` (`confidence_score`, per-table status).
- `orchestration.md` — validation's place in the pipeline and its HITL gate.
