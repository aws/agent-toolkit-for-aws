# BTEQ → RSQL Conversion Guide

## Command mapping

| BTEQ | RSQL / Redshift | Notes |
|------|-----------------|-------|
| .LOGON host/user,pass | DSN via odbc.ini | Use IAM temp credentials |
| .LOGOFF / .QUIT | \q | Disconnect / exit |
| .QUIT N | \exit N | Exit with return code |
| .RUN FILE=path | \i path | Include/run file |
| .IMPORT VARTEXT 'delim' FILE=path | COPY table FROM 's3://…' IAM_ROLE 'arn' DELIMITER 'delim' | Load via S3 |
| .EXPORT [REPORT] FILE=path | UNLOAD ('SELECT …') TO 's3://…' | Export via S3 |
| .IF ERRORCODE <> 0 THEN .GOTO label | \if :ERROR <> 0 / \echo / \exit N / \endif | Error handling |
| .IF ACTIVITYCOUNT = 0 THEN .GOTO label | \if :ACTIVITYCOUNT = 0 / \echo / \exit 1 / \endif | Row-count check |
| .IF ERRORLEVEL > 0 | -- commented out | No direct equivalent |
| .GOTO label / .LABEL name | -- commented out | No labels in RSQL |
| .SET WIDTH n | -- (not needed) | RSQL handles width |
| DATABASE dbname; | SET search_path TO schema; | Schema context |
| BT; / ET; | BEGIN; / COMMIT; | Transaction control |
| LOGON … (bare, no dot) | -- commented out | Remove bare LOGON |

## Key patterns

### Error handling

```
-- BTEQ
.IF ERRORCODE <> 0 THEN .GOTO ERROR_HANDLER
...
.LABEL ERROR_HANDLER
.QUIT 12

-- RSQL
\if :ERROR <> 0
  \echo "Error — jumping to ERROR_HANDLER"
  \exit 12
\endif
```

### Data loading

```
-- BTEQ
.IMPORT VARTEXT '|' FILE=data.txt
USING (col1 VARCHAR(50), col2 INTEGER)
INSERT INTO schema.table VALUES (:col1, :col2);

-- Redshift
COPY schema.table FROM 's3://bucket/data.txt'
IAM_ROLE 'arn:aws:iam::acct:role/role' DELIMITER '|';
```

### Data export

```
-- BTEQ
.EXPORT REPORT FILE=output.txt
SELECT * FROM schema.table;

-- Redshift
UNLOAD ('SELECT * FROM schema.table')
TO 's3://bucket/output/' IAM_ROLE 'arn:aws:iam::acct:role/role';
```

### Transaction control

```
-- BTEQ
BT;
DELETE FROM staging_table ALL;
INSERT INTO staging_table SELECT * FROM source;
ET;

-- RSQL
BEGIN;
DELETE FROM staging_table;
INSERT INTO staging_table SELECT * FROM source;
COMMIT;
```

## Shell wrapper pattern

For complex BTEQ scripts, use a shell wrapper + RSQL:

```bash
#!/bin/bash
set -e
export PGHOST="redshift-cluster.region.redshift.amazonaws.com"
export PGPORT="5439"
export PGDATABASE="mydb"
export PGSSLMODE="verify-full"   # enforce TLS; never let the connection fall back to cleartext

# Ephemeral IAM-based credentials (preferred over static passwords). One API call —
# each call mints new credentials. No eval; parse fields explicitly.
read -r PGUSER PGPASSWORD < <(aws redshift get-cluster-credentials-with-iam \
  --cluster-identifier my-cluster --db-name mydb \
  --query '[DbUser, DbPassword]' --output text)
export PGUSER PGPASSWORD
# (Serverless: aws redshift-serverless get-credentials --workgroup-name <wg> --db-name mydb)
# Env-var exposure caveat: exported values are visible to same-user processes; on shared
# hosts prefer a ~/.pgpass file (chmod 0600) over exporting PGPASSWORD.

rsql -f converted_script.sql || { echo "Script failed"; exit 1; }
```

## Data migration utilities

- **Teradata Parallel Transporter (TPT)** — parallel unload from Teradata.
- **AWS SCT extractor agents** — automate extraction, scale horizontally.
- **Teradata Vantage** — unload directly to S3, then COPY into Redshift.
- For large volumes consider AWS Direct Connect or Snowball.

## Rules

- `.LOGON` → DSN-based connection; `.IMPORT` → COPY from S3; `.EXPORT` → UNLOAD to S3.
- Comment out `.GOTO`, `.LABEL`, `.IF ERRORLEVEL` (no equivalent).
- `DATABASE` → `SET search_path`; `BT`/`ET` → `BEGIN`/`COMMIT`.
- Apply SQL-level conversions to embedded SQL within the script.

## Validation caveat (no TTU host)

BTEQ/TTU is **Linux/Windows only — not macOS**, so on many operator hosts you **cannot execute
the source BTEQ** to capture a Teradata baseline. In that case, validate the converted RSQL **on
the Redshift side**: run it against the target and reconcile results to the migrated base tables
(row counts / aggregates) rather than diffing against Teradata BTEQ output. Record in the report
that no source-side BTEQ baseline was available.
