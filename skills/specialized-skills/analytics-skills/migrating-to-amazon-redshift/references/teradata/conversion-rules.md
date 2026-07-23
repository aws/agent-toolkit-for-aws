# Teradata → Redshift Conversion Rules (72 validated rules)

> AI-facing knowledge: the validated Teradata→Redshift conversion rules the AI applies
> directly when converting DDL / SQL / stored procedures / macros / BTEQ. **These rules ARE
> the source of truth** — the skill ships no converter; the AI applies them at conversion time
> and reasons from them to fix Redshift errors and handle the manual-rewrite long tail below.

Validated across 518 test cases (94.6% pass rate on the source corpus).

## Critical rules by impact

| Priority | Rule | Impact |
|----------|------|--------|
| 1 | SUBSTR → SUBSTRING | #1 failure cause (64% of TPC-DS failures) |
| 2 | Reserved word aliases | Must double-quote: "returns", "interval", "language", etc. |
| 3 | Column alias in ROLLUP | Use the underlying column name (or position), never the alias |
| 4 | MERGE INTO alias | Redshift MERGE allows **no target alias** (source alias only) — drop it and qualify with the table name |
| 5 | NULL (TYPE) → NULL::TYPE | Common in MDM views |
| 6 | MOD(a,b) → (a % b) | Arithmetic operator difference |
| 7 | CASCADE CONSTRAINTS → CASCADE | DDL simplification |
| 8 | STRTOK → SPLIT_PART | String function mapping |
| 9 | UPDATE table alias | Remove alias from target (RS cannot alias UPDATE target) |
| 10 | QUANTILE(n, col) → NTILE(n) OVER (ORDER BY col) - 1 | Window function mapping |

## SQL function replacements

| Teradata | Redshift | Notes |
|----------|----------|-------|
| SEL | SELECT | Statement shorthand |
| ZEROIFNULL(x) | COALESCE(x, 0) | Null handling |
| NULLIFZERO(x) | NULLIF(x, 0) | Null handling |
| CHARACTERS(x) | LENGTH(x) | String length |
| INDEX(str, sub) | STRPOS(str, sub) | String position |
| SUBSTR(x, y, z) | SUBSTRING(x, y, z) | **Critical** — not supported in RS |
| CSUM(col, order) | SUM(col) OVER (ORDER BY order ROWS UNBOUNDED PRECEDING) | Cumulative sum |
| MAVG(col, n, order) | AVG(col) OVER (ORDER BY order ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW) | Moving average |
| MOD(a, b) | (a % b) | Modulo operator |
| STRTOK(x, ...) | SPLIT_PART(x, ...) | String tokenizer |
| QUANTILE(n, col) | NTILE(n) OVER (ORDER BY col) - 1 | Quantile function |

## Statement transformations

| Teradata | Redshift | Notes |
|----------|----------|-------|
| CREATE VOLATILE TABLE | CREATE TEMP TABLE | Remove ON COMMIT PRESERVE ROWS |
| COLLECT STATISTICS | ANALYZE | Statistics gathering |
| LOCKING table FOR ACCESS | (remove) | Redshift uses MVCC |
| HASHROW/HASHBUCKET | (remove); if a row fingerprint is needed → `MD5(NVL(a::VARCHAR,'') \|\| …)` | No exact RS equivalent — MD5 values **differ** from TD HASHROW (different algorithms); use only as a within-Redshift fingerprint, not to match TD values |
| (expr)(TYPE) | CAST(expr AS TYPE) | Inline type cast |
| DELETE FROM t ALL | DELETE FROM t | Remove ALL keyword |
| MERGE INTO t alias USING | MERGE INTO t USING … (drop the target alias; rewrite alias refs to `t`) | RS MERGE supports a **source** alias only — target alias (bare or AS) is a syntax error |
| NULL (TYPE) | NULL::TYPE | Typed NULL cast |
| SET QUERY_BAND | -- comment out | Use SET query_group instead |
| UPDATE t alias SET alias.col | UPDATE t SET col | RS cannot alias UPDATE target |
| RENAME TABLE t1 TO t2 | ALTER TABLE t1 RENAME TO t2 | DDL syntax |
| CREATE INDEX | (remove) | Not supported in RS |

## Clause handling

| Teradata | Redshift | Notes |
|----------|----------|-------|
| date + INTERVAL 'N' DAY | DATEADD(day, N, date) | Date arithmetic |
| ADD_MONTHS(date, n) | DATEADD(month, n, date) | Month arithmetic |
| (CASESPECIFIC) | (remove) | RS default is case-sensitive |
| col (NOT CASESPECIFIC) | column/DB `COLLATE CASE_INSENSITIVE` (**preferred**); `UPPER(col)` only as an ad-hoc fallback | RS supports case-insensitive collation. TD default is NOT CASESPECIFIC in session mode → affects **most** TD columns; set collation at CREATE time to keep join/filter semantics + sargability (UPPER() kills sortkey use) |
| col (FORMAT 'fmt') | TO_CHAR(col, 'fmt') | Date/number formatting |
| col (TITLE 'title') | col AS "title" | Column alias |
| SELECT TOP N | SELECT ... LIMIT N | Move to end of query |
| QUALIFY ... | **keep as-is** — Redshift supports QUALIFY natively; if QUALIFY directly follows FROM, the FROM relation **must have an alias** (`FROM t x QUALIFY …`) | Reshape to a CTE **only** when QUALIFY is mixed with `GROUP BY` (dedupe-then-aggregate) |
| SAMPLE n | ORDER BY RANDOM() LIMIT n | RS has no `TABLESAMPLE`; use random-order + LIMIT |

## Reserved words requiring double-quoting as aliases

```
returns, interval, language, position, result, trim, user, type,
default, comment, action, condition, connection, current, input,
output, session, system, value, year, month, day, hour, minute,
second, zone
```

## DDL conversion

### Clauses to strip (Teradata-specific, no RS equivalent)

| Clause | Action |
|--------|--------|
| FALLBACK / NO FALLBACK | Remove (RS has automatic RA3/S3 redundancy) |
| NO BEFORE JOURNAL / NO AFTER JOURNAL | Remove |
| CHECKSUM = DEFAULT | Remove |
| MERGEBLOCKRATIO = n / DEFAULT MERGEBLOCKRATIO | Remove |
| CHARACTER SET x | Remove (RS default is UTF-8) |
| DATE FORMAT 'fmt' | Remove |
| WITH DATA | Remove (not needed in RS CTAS) |

### Table type conversion

| Teradata | Redshift | Notes |
|----------|----------|-------|
| CREATE SET TABLE | CREATE TABLE | Add dedup logic if needed (RS allows duplicates) |
| CREATE MULTISET TABLE | CREATE TABLE | Direct replacement |
| CREATE VOLATILE TABLE | CREATE TEMP TABLE | Remove ON COMMIT PRESERVE ROWS |

### Index and key conversion

| Teradata | Redshift | Notes |
|----------|----------|-------|
| UNIQUE PRIMARY INDEX (col) | DISTKEY(col) | Uniqueness not enforced in RS |
| PRIMARY INDEX (col) | DISTKEY(col) | Single column only |
| PRIMARY INDEX (col1, col2) | DISTSTYLE EVEN | Deterministic default: multi-col PI has no single-col equivalent. The optimization pass (`architecture-mapping.md`) may upgrade to DISTKEY on the highest-cardinality join col |
| PARTITION BY RANGE_N(col) | SORTKEY(col) | Range partition → sort key |
| Secondary Index | SORTKEY (partial) | Consider as additional sort key |
| Join Index | Materialized View | Use CREATE MATERIALIZED VIEW |
| CREATE INDEX | Remove | Not supported in RS |

### Compression and encoding

| Teradata | Redshift |
|----------|----------|
| COMPRESS ('val1','val2') | ENCODE bytedict |
| COMPRESS (no values) | ENCODE az64 |

Recommended encodings: CHAR/VARCHAR <250 → LZO; 250+ → ZSTD; DATE/TIMESTAMP/INT/
NUMERIC → AZ64; DOUBLE/FLOAT → ZSTD; first sort-key column → RAW. Use `ENCODE AUTO`
/ `DISTSTYLE AUTO` / `SORTKEY AUTO` when unsure — Redshift will optimize.

## Constructs requiring manual rewrite (no deterministic mapping)

These have **no direct Redshift equivalent** — flag them for review and apply the suggested
structural rewrite rather than a mechanical substitution. Confidence should drop when they appear,
and each should land in the `manual_review.json` backlog (see `reporting.md`) with its location.

| Teradata construct | Suggested Redshift rewrite |
|--------------------|----------------------------|
| `QUALIFY` **mixed with `GROUP BY`** | Plain `QUALIFY` is native in Redshift — keep it (add a FROM alias when QUALIFY directly follows FROM). Only the dedupe-then-aggregate case (QUALIFY + GROUP BY) needs a CTE (`rn=1`) then `GROUP BY`. |
| `SAMPLE n` | `ORDER BY RANDOM() LIMIT n` (Redshift has no `TABLESAMPLE`). |
| `RESET WHEN` | Windowed running calc with a grouping key (LAG/SUM over a partition that restarts on the condition). |
| `EXPAND ON <period>` | Expand the period with `generate_series()` or a recursive CTE. |
| `TD_NORMALIZE_OVERLAP` | CTE using LAG/SUM grouping to merge overlapping periods. |
| `TD_UNPIVOT` | `CROSS JOIN` with `CASE` expressions (or `UNION ALL`). |
| `NONSEQUENCED` (temporal) | No RS equivalent — rewrite the temporal semantics explicitly. |
| `ALTER TABLE … MODIFY` | Not supported — `DROP`/re-`CREATE` the column or table. |
| `PERIOD(...)` type | Split into two columns (see `data-type-mapping.md`). |
| Cursors / triggers / join indexes | Set-based rewrite / Lambda+Step Functions / Materialized View (see `stored-procedure-migration.md`, `architecture-mapping.md`). |

**Workflow:** apply the deterministic rules above to the well-understood bulk, then flag each
manual-rewrite construct with its suggested rewrite. This is the same split the old converter used
(mechanical rules vs. flagged review items) — now applied directly by the AI.

## Complexity assessment

Score a file by summing a weight per matched construct, then map the total to a rating.
**Weights:** low = 1, medium = 3, high = 8.

**Pattern → complexity catalog** (what to scan for; extends the rule tables above):

| Complexity | Constructs |
|------------|-----------|
| **Low (1)** | SEL, ZEROIFNULL/NULLIFZERO, CHARACTERS, INDEX→STRPOS, FALLBACK/journal/CHECKSUM/MERGEBLOCKRATIO strip, BYTEINT, COMPRESS, TOP-N, MOD, CASCADE CONSTRAINTS, STRTOK, RENAME TABLE, CREATE INDEX removal, QUERY_BAND, bare LOGON, COLLECT STATISTICS, LOCKING FOR ACCESS, VOLATILE TABLE |
| **Medium (3)** | PRIMARY INDEX→DISTKEY, UNIQUE PI, PARTITION BY→SORTKEY, QUALIFY+GROUP BY, SAMPLE, CASESPECIFIC, FORMAT clause, MERGE INTO, HASHROW/HASHBUCKET, CLOB, INTERVAL type, JOIN INDEX→MV, QUANTILE, ADD_MONTHS, BTEQ `.LOGON`/`.IMPORT`/`.EXPORT`/`.IF` |
| **High (8)** | PERIOD type, BLOB, UDT, stored procedures, macros, cursors, triggers, RESET WHEN, EXPAND ON, TD_NORMALIZE_OVERLAP, TD_UNPIVOT, NONSEQUENCED, ALTER TABLE MODIFY |

| Score | Rating | Estimate |
|-------|--------|----------|
| < 50 | LOW | 1-2 weeks |
| 50-199 | MEDIUM | 2-6 weeks |
| 200-499 | HIGH | 6-12 weeks |
| 500+ | VERY HIGH | 3-6 months |

## Worked examples (golden input → output)

Concrete targets a correct conversion should match.

**DDL** (MULTISET + FALLBACK + PI + PPI + COMPRESS):

```sql
-- Teradata
CREATE MULTISET TABLE sales (
    id INTEGER, store_id INTEGER, sale_dt DATE, amt DECIMAL(15,2) COMPRESS
) FALLBACK
PRIMARY INDEX (store_id)
PARTITION BY RANGE_N(sale_dt BETWEEN DATE '2020-01-01' AND DATE '2030-12-31' EACH INTERVAL '1' MONTH);
-- Redshift
CREATE TABLE sales (
    id INTEGER, store_id INTEGER, sale_dt DATE, amt DECIMAL(15,2) ENCODE az64
)
DISTKEY(store_id)
SORTKEY(sale_dt);
```

**SQL** (SEL + TOP + SUBSTR + ZEROIFNULL + reserved-word alias):

```sql
-- Teradata
SEL TOP 50 SUBSTR(name,1,3), ZEROIFNULL(amt) AS returns FROM t;
-- Redshift
SELECT SUBSTRING(name,1,3), COALESCE(amt, 0) AS "returns" FROM t
LIMIT 50;
```

**Stored procedure** (fragment):

```sql
-- Teradata:  REPLACE PROCEDURE p(OUT c INTEGER) ... SET c = ACTIVITY_COUNT;
-- Redshift:  CREATE OR REPLACE PROCEDURE p(INOUT c INTEGER) LANGUAGE plpgsql AS $$ ...
--              GET DIAGNOSTICS c = ROW_COUNT; ... $$;
```

**BTEQ → RSQL** (error handling):

```
-- Teradata:  .IF ERRORCODE <> 0 THEN .GOTO ERR
-- RSQL:       \if :ERROR <> 0
--               \echo 'error'
--               \exit 1
--             \endif
```

## Conversion confidence (deterministic rubric)

Score confidence per object from the **complexity of the rules applied** (not a free-form
guess), so it is reproducible across models and drives the HITL gate in `orchestration.md`:

| Highest-weight construct in the object | Confidence | Action |
|----------------------------------------|-----------|--------|
| Only **Low**-weight rules applied | ≥ 0.95 | auto-accept |
| Any **Medium**-weight construct | ≤ 0.85 | accept; note in report |
| Any **High**-weight / manual-rewrite construct | ≤ 0.70 | **auto-flag** → `manual_review.json` |
| Unconvertible kind (trigger, join index, UDT) | 0.0 | always flag |

Weights are the Low/Medium/High tiers in the complexity catalog above. Same input → same
confidence regardless of model.

## `manual_review.json` (contract)

Produced by conversion, consumed by `reporting.md`. One entry per flagged object:

```json
{
  "items": [
    {
      "object": "BANKING_DW.proc_x",
      "object_kind": "procedure|table|view|macro|bteq|sql",
      "construct": "multi-result macro",
      "location": "file/line or statement index",
      "snippet": "…offending source…",
      "suggested_rewrite": "…from the manual-rewrite table above…",
      "confidence": 0.7,
      "status": "open|accepted|rewritten"
    }
  ],
  "summary": { "objects": 0, "needs_review": 0, "min_confidence": 1.0 }
}
```

The `summary` shape matches what the `orchestration.md` HITL gate reports.

## Golden corpus (acceptance scoring key)

Input→output pairs the conversion must reproduce, each tagged with the rule it exercises. Use as
the yardstick for the model-matrix consistency test (`docs/test-plan.md`, Scenario A): a converted
object is "correct" when it matches the intent below **and** runs on Redshift.

### Critical-10 (one per critical rule)

| # rule | Teradata | Redshift |
|--------|----------|----------|
| 1 SUBSTR | `SELECT SUBSTR(name,1,5) FROM t;` | `SELECT SUBSTRING(name,1,5) FROM t;` |
| 2 reserved alias | `SELECT SUM(amt) AS returns FROM t;` | `SELECT SUM(amt) AS "returns" FROM t;` |
| 3 ROLLUP alias | `SELECT region r, SUM(amt) FROM t GROUP BY ROLLUP(r);` | `SELECT region r, SUM(amt) FROM t GROUP BY ROLLUP(region);` |
| 4 MERGE alias | `MERGE INTO tgt t USING src s ON t.id=s.id …` | `MERGE INTO tgt USING src s ON tgt.id=s.id …` (no target alias; qualify with table name) |
| 5 NULL(TYPE) | `SELECT NULL (DATE) FROM t;` | `SELECT NULL::DATE FROM t;` |
| 6 MOD | `SELECT MOD(id,10) FROM t;` | `SELECT (id % 10) FROM t;` |
| 7 CASCADE | `DROP TABLE t CASCADE CONSTRAINTS;` | `DROP TABLE t CASCADE;` |
| 8 STRTOK | `SELECT STRTOK(name,',',2) FROM t;` | `SELECT SPLIT_PART(name,',',2) FROM t;` |
| 9 UPDATE alias | `UPDATE a FROM t1 AS a, s SET c='x' WHERE a.id=s.id;` | `UPDATE t1 SET c='x' FROM s WHERE t1.id=s.id;` |
| 10 QUANTILE | `SELECT QUANTILE(4,salary) FROM emp;` | `SELECT NTILE(4) OVER (ORDER BY salary)-1 FROM emp;` |

### Manual-rewrite constructs

**QUALIFY — native in Redshift (keep as-is); reshape to a CTE only when mixed with `GROUP BY`:**

```sql
-- TD plain QUALIFY → RS keeps it (native). Redshift restriction: when QUALIFY directly
-- follows FROM, the FROM relation must have an alias — add one if the TD source lacks it.
SELECT id, k, d FROM t src QUALIFY ROW_NUMBER() OVER (PARTITION BY k ORDER BY d DESC) = 1;

-- TD QUALIFY mixed with GROUP BY (dedupe-then-aggregate) → RS must reshape to a CTE:
-- TD:
SELECT k, SUM(amt) FROM t GROUP BY k
  QUALIFY ROW_NUMBER() OVER (PARTITION BY k ORDER BY ts DESC) = 1;
-- RS:
WITH deduped AS (
  SELECT t.*, ROW_NUMBER() OVER (PARTITION BY k ORDER BY ts DESC) AS rn FROM t
)
SELECT k, SUM(amt) FROM deduped WHERE rn = 1 GROUP BY k;
```

**PERIOD type → two columns:**

```sql
-- TD
CREATE TABLE emp (id INT, employment PERIOD(DATE));
-- RS
CREATE TABLE emp (id INT, employment_start DATE, employment_end DATE);
```

**RESET WHEN → windowed grouping (running total restarts when flag=1):**

```sql
-- TD
SELECT id, amt,
       SUM(amt) OVER (ORDER BY id RESET WHEN flag = 1 ROWS UNBOUNDED PRECEDING) AS running
FROM t;
-- RS: build a group id that increments on each reset, then sum within the group
WITH g AS (
  SELECT id, amt,
         SUM(CASE WHEN flag = 1 THEN 1 ELSE 0 END) OVER (ORDER BY id ROWS UNBOUNDED PRECEDING) AS grp
  FROM t
)
SELECT id, amt,
       SUM(amt) OVER (PARTITION BY grp ORDER BY id ROWS UNBOUNDED PRECEDING) AS running
FROM g;
```

**TD_UNPIVOT → UNION ALL:**

```sql
-- TD
SELECT * FROM TD_UNPIVOT(
  ON sales USING VALUE_COLUMNS('v') UNPIVOT_COLUMN('quarter') COLUMN_LIST('q1','q2','q3','q4')
) AS x;
-- RS
SELECT id, 'q1' AS quarter, q1 AS v FROM sales
UNION ALL SELECT id, 'q2', q2 FROM sales
UNION ALL SELECT id, 'q3', q3 FROM sales
UNION ALL SELECT id, 'q4', q4 FROM sales;
```

> EXPAND ON, TD_NORMALIZE_OVERLAP, NONSEQUENCED, ALTER TABLE MODIFY, cursors, triggers, join
> indexes → apply the manual-rewrite table above and record each in `manual_review.json`.

### Full DDL (MULTISET + multi-col PI + PPI + COMPRESS + FALLBACK)

```sql
-- TD
CREATE MULTISET TABLE sales (
    a INTEGER, b INTEGER, dt DATE, amt DECIMAL(15,2) COMPRESS
) FALLBACK
PRIMARY INDEX (a, b)
PARTITION BY RANGE_N(dt BETWEEN DATE '2020-01-01' AND DATE '2030-12-31' EACH INTERVAL '1' MONTH);
-- RS  (multi-col PI → DISTSTYLE EVEN; PPI → SORTKEY; COMPRESS → ENCODE; FALLBACK dropped)
CREATE TABLE sales (
    a INTEGER, b INTEGER, dt DATE, amt DECIMAL(15,2) ENCODE az64
)
DISTSTYLE EVEN
SORTKEY(dt);
```

### Macro (type-2, returns rows)
A macro ending in a `SELECT` becomes a procedure returning a **refcursor** (not `RAISE INFO`) —
see `stored-procedure-migration.md` → *Multi-statement macro pattern (type 2)*.

### BTEQ → RSQL block

```
-- TD (BTEQ)
.IF ERRORCODE <> 0 THEN .GOTO ERR
.IMPORT VARTEXT '|' FILE=data.txt
BT;
INSERT INTO staging SELECT * FROM src;
ET;
-- RS (RSQL)
\if :ERROR <> 0
  \echo 'error'
  \exit 1
\endif
-- COPY staging FROM 's3://bucket/data.txt' IAM_ROLE 'arn:aws:iam::acct:role/role' DELIMITER '|';
BEGIN;
INSERT INTO staging SELECT * FROM src;
COMMIT;
```
