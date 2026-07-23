# Common Errors, Edge Cases, and Resolutions

## Redshift-specific errors

- **"number of segments exceeds the max allowed (30)"** — complex joins (e.g.
  MicroStrategy). Remove the full outer join VLDB property; simplify joins.
- **"correlated subquery pattern is not supported"** — flatten nested correlated
  subqueries; rewrite as CTEs or JOINs.
- **Reserved-word collision** — double-quote aliases (`returns`, `interval`,
  `language`, `position`, `result`, `trim`, `user`, `type`, `default`, `comment`,
  `value`, `year`, `month`, `day`, `zone`, …).
- **SUBSTR not recognized** — #1 failure cause; replace every `SUBSTR(` with
  `SUBSTRING(`.
- **Window function missing frame** — add explicit frame:
  `SUM(x) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING)`.
- **Derived column order** — Redshift requires a derived column be defined before
  it's referenced in the same SELECT.

```sql
-- Teradata (forward reference allowed)
SELECT pricepaid,
  CASE WHEN discount > 10 THEN 'Yes' ELSE 'No' END discount_flag,
  pricepaid - retailprice AS discount
FROM sales;

-- Redshift (define before use)
SELECT pricepaid,
  pricepaid - retailprice AS discount,
  CASE WHEN discount > 10 THEN 'Yes' ELSE 'No' END discount_flag
FROM sales;
```

## Conversion edge cases (flag for manual review)

- **QUALIFY** — Redshift supports QUALIFY natively; keep as-is (when QUALIFY directly follows
  FROM, the FROM relation must have an alias — add one). Reshape to a CTE with
  `ROW_NUMBER()` and filter in `WHERE` **only** when mixed with `GROUP BY` (dedupe-then-aggregate)
  — see `conversion-rules.md`.
- **RESET WHEN** (HIGH) — CTE with LAG/SUM grouping.
- **EXPAND ON** (HIGH) — `generate_series()` or recursive CTE.
- **TD_NORMALIZE_OVERLAP** (HIGH) — CTE with LAG/SUM grouping.
- **TD_UNPIVOT** (HIGH) — CROSS JOIN with CASE expressions.
- **NONSEQUENCED temporal** (HIGH) — full rewrite required.
- **ALTER TABLE MODIFY** (HIGH) — not supported; DROP+ADD column or recreate table.
- **Cursors** (HIGH) — prefer set-based rewrites.
- **Triggers** (HIGH) — not supported; rewrite as Lambda/Step Functions/app logic.

### QUALIFY example

```sql
-- Plain QUALIFY: keep as-is — native in Redshift. One restriction: when QUALIFY directly
-- follows FROM, the FROM relation must carry an alias (here: o)
SELECT * FROM orders o
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) = 1;

-- QUALIFY mixed with GROUP BY (dedupe-then-aggregate): reshape to a CTE
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) AS rn
  FROM orders
)
SELECT * FROM ranked WHERE rn = 1;
```

## Comparison operators

```sql
-- Integer comparison: don't quote integers
WHERE integer_sk > -13            -- (TD allowed '-13')

-- LIKE ANY/ALL → split into OR clauses
WHERE (col LIKE 'val1') OR (col LIKE 'val2') OR (col LIKE 'val3')

-- Timezone conversion
CONVERT_TIMEZONE('US/Eastern', col)   -- source must be TIMESTAMP w/o TZ
```

## Data migration challenges

- **Large volumes (100TB+)** — TPT parallel unload; Direct Connect or Snowball by
  bandwidth; Vantage unloads directly to S3.
- **Storage footprint** — Redshift uses 1MB blocks; small tables may grow (expected).
- **Character encoding** — TD often ISO-8859-1, RS default UTF-8; size VARCHARs for
  multibyte; set COPY encoding (UTF8/UTF16/…/ISO88591).

## SCT considerations

- **Handled**: secondary indexes → sort keys; join indexes → materialized views;
  PK/FK as optimizer hints (not enforced).
- **Not handled**: range partitioning (manual timeseries setup), SET-table
  uniqueness (needs dedup logic), TITLE keyword, FALLBACK/JOURNAL (removed).
- Run the SCT assessment report before automated conversion to gauge complexity.
