# RDS for Db2 — Mainframe Migration Reference

Source blogs:

- https://aws.amazon.com/blogs/database/migrating-tables-from-ibm-db2-for-z-os-to-amazon-rds-for-db2/
- https://aws.amazon.com/blogs/database/choosing-the-right-code-page-and-collation-for-migration-from-mainframe-db2-to-amazon-rds-for-db2/

---

## z/OS to RDS Db2 — Overview

Migrating from Db2 for z/OS is a **replatform** (different OS/endianness). You cannot restore a z/OS backup image to RDS for Db2. The process requires:

1. Schema conversion (DDL extraction + transformation)
2. Data migration (export/load, federation, or replication tools)

---

## Schema conversion (DDL)

### Recommended tool: ADB2GEN (IBM Db2 Administration Tool for z/OS)

ADB2GEN extracts DDL for tables, indexes, views, triggers, check constraints, referential constraints, identity columns, sequences, and GRANT statements with high fidelity.

### Python conversion script

A Python script converts ADB2GEN output to RDS for Db2 compatible DDL:

```bash
python zos_to_luw_ddl_conversion.py <zos_ddl_file> <target_schema> <target_data_tablespace> <target_index_tablespace> <output_file>

# Example:
python zos_to_luw_ddl_conversion.py EMPLOYEE.DDL SCHEMA1 TS_DATA_8K TS_INDEX_8K EMPLOYEE.out
```

### What the script handles

| z/OS DDL feature | Action |
|---|---|
| `FOR SBCS DATA` on CHAR/VARCHAR | Removed (not supported in RDS) |
| `WITHOUT TIME ZONE` on TIMESTAMP | Removed |
| `VOLATILE` / `NOT VOLATILE` in CREATE TABLE | Removed (use ALTER TABLE after creation) |
| `CLUSTER` / `NOT CLUSTER` on indexes | `NOT CLUSTER` removed; `CLUSTER` kept |
| Duplicate unique index for primary key | Removed (RDS auto-creates it) |
| Table compression | `COMPRESS YES` added to all tables |
| `CREATE TABLESPACE` | Removed (create tablespaces separately) |
| GRANT statements | Preserved as-is |

### Create tablespaces before running DDL

```sql
call rdsadmin.create_bufferpool('<DBNAME>', 'BP8K', 10000, 'Y', 'Y', 8192);
call rdsadmin.create_tablespace('<DBNAME>', 'TS_DATA_8K', 'BP8K', 8192);
call rdsadmin.create_tablespace('<DBNAME>', 'TS_INDEX_8K', 'BP8K', 8192);
```

---

## Code page and collation selection (summary)

Code page, collation, and territory are **immutable** after database creation, so choose them before you create the target database with `rdsadmin.create_database(name, pagesize, codeset, territory, collation)`. Quick mapping:

| Mainframe CCSID | RDS code page | Collation |
|---|---|---|
| 37 (US/Canada EBCDIC) | ISO-8859-1 | EBCDIC_819_037 |
| 500 / 1047 / 273 (EBCDIC) | ISO-8859-1 | EBCDIC_819_500 |
| 1141 (German + Euro) | ISO-8859-15 | SYSTEM |
| 930 / 939 (Japanese) | UTF-8 or IBM-943 | EBCDIC_932_5026 / _5035 |
| 1390, 1399 (Japanese + Euro) | UTF-8 | SYSTEM |

Watch-outs: UTF-8 expands accented characters from 1 to 2 bytes (truncation risk — consider `CODEUNITS32`), and ISO-8859-1 silently substitutes out-of-range characters with `0x1A`.

**For full code page and collation guidance, see code-page-collation.md** — the CCSID inventory, the complete decision matrix, `rdsadmin.create_database` examples, CODEUNITS32 vs OCTETS trade-offs, and source-CCSID checks.

---

## Data migration tools for z/OS

| Tool | Full load | CDC | Notes |
|---|---|---|---|
| AWS DMS | Yes | No | Full load only from z/OS |
| Precisely Mainframe Replication | Yes | Yes | Initial load uses inserts |
| Mainframe tools (HPU, File-AID, UNLOAD) | Yes | No | Extract to DEL/IXF, convert EBCDIC→ASCII, load via S3 |
| Db2 Export | Yes | No | Best for small/medium tables; use IXF format |
| Db2 Federation | Yes | No | RDS connects to z/OS; LOAD with CURSOR |
| Qlik Replicate | Yes | Yes | ODBC endpoint for Db2 LUW; no bulk load |
| IBM Q Replication (IIDR) | Yes | Yes | SQL or Q Replication; Q Replication requires IBM MQ |

### Db2 Federation (RDS → z/OS)

RDS for Db2 supports homogeneous federation. Catalog the z/OS database from within RDS, then load data directly:

```sql
-- Catalog the z/OS server in RDS
db2 catalog tcpip node ZOSNODE remote <zos-host> server <port>
db2 catalog database <zos-dbname> as ZOSDB at node ZOSNODE

-- Load from z/OS cursor into RDS table
LOAD FROM (SELECT * FROM ZOSDB.<schema>.<table>) OF CURSOR INSERT INTO <rds-schema>.<table>
```

### Mainframe tools workflow

1. Extract data using HPU/File-AID/UNLOAD in DEL or IXF format
2. Convert EBCDIC → ASCII (mainframe tools or `iconv`)
3. Copy to S3 using AWS CLI on mainframe (Go SDK for AIX where CLI unavailable)
4. Load into RDS from S3:

   ```sql
   CALL SYSPROC.ADMIN_CMD('LOAD FROM DB2REMOTE://myS3/<path/to/file.ixf> OF IXF INSERT INTO <schema>.<table>');
   ```

---

## Best practices for mainframe migration

1. **Run precheck** on source before the final backup (see `migration.md`).
2. **Choose code page early** — immutable after database creation.
3. **Use IXF format** — avoids delimiter conflicts, preserves types.
4. **ADB2GEN** for DDL extraction — highest fidelity for z/OS.
5. **Test character round-trips** — insert international chars, export, import, verify display.
6. **Large tables**: Db2 federation or S3 load for bulk, then CDC via Qlik/Precisely/Q Replication.
7. **Cold data** early; **hot data** near cutover.
8. **Validate with DBeaver / DataGrip / IBM Data Studio** for character display consistency.
