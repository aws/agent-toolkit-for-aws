# Stored Procedure & Macro Migration — Teradata → Redshift PL/pgSQL

## Stored procedure rules

| Teradata | Redshift PL/pgSQL | Notes |
|----------|-------------------|-------|
| REPLACE PROCEDURE | CREATE OR REPLACE PROCEDURE | Add `LANGUAGE plpgsql AS $$ … $$` |
| OUT param | INOUT param | Redshift PL/pgSQL requirement |
| SET var = ACTIVITY_COUNT | GET DIAGNOSTICS var = ROW_COUNT | Row count after DML |
| DECLARE EXIT HANDLER FOR SQLEXCEPTION | EXCEPTION WHEN OTHERS THEN | Exception block |
| SQLCODE | SQLERRM | Text message, no numeric code in RS |
| DEFAULT param_value | (remove) | DEFAULT not supported on RS params |
| FORMAT 'fmt' in params | (remove) | Not applicable |

## Macro rules

**Classify the macro first** — it decides the target and whether the *caller* changes:

1. **Single-SELECT macro → `VIEW`** (or inline SQL) — preserves the returned result set; no caller change.
2. **Multi-statement, one result set → `PROCEDURE` returning a refcursor** (or a temp table the caller reads) — caller changes from `EXEC macro` to `CALL proc` + fetch; **flag in `manual_review.json`**.
3. **Multi-statement, *multiple* result sets → split into N single-cursor `PROCEDURE`s.** Redshift opens **only one cursor per session**, so one procedure cannot return several refcursors — emit one procedure per result set (verified on the acceptance run). **Flag in `manual_review.json`.**
4. **Multi-statement, no result set → `PROCEDURE`** (pattern below).

| Teradata | Redshift | Notes |
|----------|----------|-------|
| CREATE/REPLACE MACRO | CREATE OR REPLACE PROCEDURE | Macros don't exist in RS |
| :param binding | direct variable reference | PL/pgSQL uses names directly |
| DEFAULT values | (remove) | Not supported |
| EXEC macro_name | CALL procedure_name | Execution syntax |

## PL/pgSQL wrapper template

```sql
CREATE OR REPLACE PROCEDURE schema.procedure_name(
    IN p_param1 VARCHAR(100),
    INOUT p_param2 INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
    v_error_msg VARCHAR(500);
BEGIN
    -- body

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RAISE INFO 'Step 1 completed: % rows affected', v_row_count;

EXCEPTION WHEN OTHERS THEN
    v_error_msg := SQLERRM;
    RAISE EXCEPTION 'Procedure failed: %', v_error_msg;
END;
$$;
```

## Key paradigm shifts

- **Transaction model**: TD auto-commits each statement (outside BT/ET); Redshift
  atomic SPs (default) wrap everything in one transaction; non-atomic SPs auto-commit
  each DML/DDL outside BEGIN/COMMIT.
- **Error handling**: `SQLCODE` (numeric) → `SQLERRM` (text).
- **Logging**: prefer `RAISE INFO/NOTICE/WARNING` over INSERT into log tables (avoids
  table-level locking). Messages land in `SVL_STORED_PROC_MESSAGES` (7-day retention);
  aggregate to permanent tables daily if needed.
- **Parameter defaults**: not supported — require all params at the call site.
- **Row count**: `ACTIVITY_COUNT` → `GET DIAGNOSTICS var = ROW_COUNT`.
- **Cursors**: similar syntax but different performance; prefer set-based rewrites.

## DECIMAL overflow prevention

`param * 0.8` (DECIMAL) can hit 128-bit overflow in Redshift. Cast first:

```sql
v_result := CAST(p_amount AS DECIMAL(38,10)) * 0.8;
```

## DATEADD returns TIMESTAMP

Redshift `DATEADD` returns TIMESTAMP even for DATE input. Cast when DATE is expected:

```sql
v_date := CAST(DATEADD(day, 30, v_date) AS DATE);
```

## Multi-statement macro pattern (type 2 — returns a result set)

```sql
-- Teradata macro (ends in a SELECT → returns rows to the caller)
REPLACE MACRO schema.my_macro (p_date DATE) AS (
    DELETE FROM staging WHERE load_date < :p_date;
    INSERT INTO staging SELECT * FROM source WHERE load_date = :p_date;
    SELECT COUNT(*) FROM staging WHERE load_date = :p_date;
);

-- Redshift procedure — return the result set via a refcursor (preserves semantics)
CREATE OR REPLACE PROCEDURE schema.my_macro(IN p_date DATE, INOUT rc REFCURSOR)
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM staging WHERE load_date < p_date;
    INSERT INTO staging SELECT * FROM source WHERE load_date = p_date;
    OPEN rc FOR SELECT COUNT(*) FROM staging WHERE load_date = p_date;
END;
$$;
-- caller:  BEGIN; CALL schema.my_macro(DATE '2026-01-01', 'rc'); FETCH ALL FROM rc; COMMIT;
```

> The earlier `RAISE INFO` form only *logs* the count — it does **not** return rows. Use the
> refcursor (or a temp table the caller reads), and **flag type-2 macros** in
> `manual_review.json` (caller changes from `EXEC` to `CALL` + fetch).
>
> **Multiple result sets:** Redshift allows **one open cursor per session**, so a macro that
> returns *several* result sets cannot become one procedure with N refcursors — **split it into
> N single-cursor procedures** (one per result set), each called separately. (On the acceptance
> run a 3-result-set AML macro became 3 procedures; a 2-result-set macro became 2.)

## UDF conversion quick reference

| Teradata | Redshift |
|----------|----------|
| ORDERED_CONCAT | LISTAGG |
| INSTR | STRPOS or REGEXP_INSTR |
| STRTOK_SPLIT_TO_TABLE | SPLIT_PART + REGEXP_COUNT |
| Sel / Format / Substr / Oreplace | SELECT / TO_CHAR / SUBSTRING / REPLACE |
| P_INTERSECT | Custom UDF (PERIOD not supported) |
