# Teradata → Redshift Data Type Mapping

## Complete type map

| Teradata Type | Redshift Type | Notes |
|---------------|---------------|-------|
| BYTEINT | SMALLINT | Smallest integer type in RS |
| SMALLINT | SMALLINT | Direct mapping |
| INTEGER | INTEGER | Direct mapping |
| BIGINT | BIGINT | Direct mapping |
| FLOAT | DOUBLE PRECISION | Floating point |
| DECIMAL(p,s) | DECIMAL(p,s) | Preserve precision and scale |
| NUMBER | NUMERIC | Bare `NUMBER` is flexible-scale (**holds fractions**) — do **not** default to `DECIMAL(38,0)` (drops every fraction). Choose from discovery stats: integer-only observed → `DECIMAL(38,0)`; fractional observed → `DECIMAL(38,18)` or `DOUBLE PRECISION`; stats unavailable → **flag for review** |
| NUMERIC(p,s) | NUMERIC(p,s) | Preserve precision and scale |
| CHAR(n) | CHAR(n) | Fixed-length string |
| VARCHAR(n) | VARCHAR(adjusted_n) | **See multibyte sizing below** |
| CLOB | `VARCHAR(65535)` if ≤ 64 KB, else **flag → S3 offload** | RS stored VARCHAR max = **65,535 bytes** (not 16 MB — that limit is SUPER/in-memory). TD CLOB holds up to 2 GB; offload large CLOBs to S3 and keep a VARCHAR reference column (same as BLOB). |
| BLOB | VARBYTE(1000000) | Or store in S3 with reference |
| BYTE(n) / VARBYTE(n) | VARBYTE(n) | Binary data |
| DATE | DATE | Direct mapping |
| TIME | TIME | Direct mapping |
| TIMESTAMP | TIMESTAMP | Direct mapping |
| TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | Timezone-aware |
| INTERVAL | VARCHAR | Use DATEADD/DATEDIFF for arithmetic |
| JSON | SUPER | RS native semi-structured type |
| XML | VARCHAR(MAX) | No native XML type in RS |
| PERIOD(DATE) | Two DATE columns | Split into start_date, end_date |
| PERIOD(TIMESTAMP) | Two TIMESTAMP columns | Split into start_ts, end_ts |

## VARCHAR multibyte sizing

Teradata `VARCHAR(n)` measures **characters**; Redshift `VARCHAR(n)` measures **bytes**, and
UTF-8 uses up to 4 bytes/char — so size by the column's **character set**, never by a
length tier (a length-only cap silently rejects multibyte rows on COPY). Always clamp to the
65,535-byte max.

| Source column | Redshift size |
|---------------|---------------|
| Known multibyte (`CHARACTER SET UNICODE`/`GRAPHIC`, or discovery shows `MAX(OCTET_LENGTH) > n`) | `min(4 * n, 65535)` |
| Known single-byte (`LATIN` / ASCII) | `n` (as-is) |
| Unknown | `min(2 * n, 65535)` + note to verify |

If `4 * n` would exceed 65,535, clamp to `VARCHAR(65535)` and **flag** if the source can
actually exceed that byte length (candidate for S3 offload, like CLOB).

## PERIOD type handling

No Redshift equivalent — split into two columns:

```sql
-- Teradata
CREATE TABLE employee (emp_id INTEGER, employment_period PERIOD(DATE));

-- Redshift
CREATE TABLE employee (
    emp_id INTEGER,
    employment_start_date DATE,
    employment_end_date DATE
);
```

## Decimal rounding difference

- **Teradata**: banker's rounding — `CAST(22.2345 AS DECIMAL(5,3))` → 22.234
- **Redshift**: standard rounding — `CAST(22.2345 AS DECIMAL(5,3))` → 22.235

This can cause data-validation mismatches; document it for the customer.

## Other notes

- Views: create with `WITH NO SCHEMA BINDING` so base tables can be dropped/recreated
  without dropping dependent views.
- COPY encodings supported: UTF8, UTF16, UTF16LE, UTF16BE, ISO88591.
- Redshift default timezone is UTC (cannot be set at the database level; only per-user
  or via client tools).
