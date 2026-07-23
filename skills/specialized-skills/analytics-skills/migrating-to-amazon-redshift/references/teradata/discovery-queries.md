# Discovery — DBC system-view queries

> AI-facing knowledge: the read-only `DBC` catalog queries the AI uses to **build** a
> discovery runner for the customer's environment, and the `inventory.json` contract the
> runner produces. This doc is the knowledge — the AI generates the actual runner
> (connected) or a portable bundle (disconnected); see `references/teradata/orchestration.md`.

## Purpose

Inventory the source Teradata system — version/parallelism, databases, objects (tables,
views, macros, procedures), storage, AMP skew, and an always-available workload signal —
to produce `output/discovery/result/inventory.json`. Every later phase (conversion,
migration, validation, performance, reporting) reads this contract.

**All queries are SELECT-only against `DBC` catalog views.** No DDL/DML, no user-table
data — safe for a DBA to run on production.

> **Source of truth:** the queries in this doc ARE the source of truth. The skill ships no
> executable collector — the AI generates the runner (a BTEQ driver or a `teradatasql`
> script) at run time from the SQL below, adapting to how the customer can reach the source.
> See **Execution modes** for the BTEQ driver template the AI should emit.

## DBC views used

| View | Purpose | Grain |
|------|---------|-------|
| `DBC.DBCInfoV` | Teradata version / release | system |
| `DBC.DiskSpaceV` | permanent space per database (CurrentPerm/MaxPerm) | per AMP → SUM |
| `DBC.TableSizeV` | permanent space per table and per AMP (skew) | per table × AMP → SUM |
| `DBC.TablesV` | object counts by `TableKind` | per database |
| `DBC.ColumnsV` | column inventory for DDL/conversion | per column |
| `DBC.IndicesV` | PI / PPI / secondary indexes | per index column |
| `DBC.AMPUsageV` | cumulative CPU/IO by account+user (always-on) | per AMP → SUM |
| `DBC.DBQLogTbl` | query history (workload) — often disabled | per query |
| `DBC.ResUsageSpma` | system resource time series — often disabled | per node × sample |

`amp_count` comes from the number of distinct `Vproc` rows in `DBC.TableSizeV` (or
`HASHAMP()+1`). `node_count` is best-effort and not always derivable offline.

## System & version

```sql
-- DBC.DBCInfoV → td_version
SELECT TRIM(InfoKey) || '|' || TRIM(InfoData) AS rec
FROM DBC.DBCInfoV
WHERE InfoKey IN ('VERSION', 'RELEASE')
ORDER BY InfoKey;
```

**Collection manifest** (provenance for `collection_meta`: `collected_at` + `td_version`).
Both rows read `DBC.DBCInfoV` on purpose — a constant `SELECT` with no `FROM` fails inside a
`UNION` (Failure 3888), so the timestamp row is anchored to a 1-row catalog read:

```sql
SELECT 'collected_at|' || CAST(CURRENT_TIMESTAMP(0) AS VARCHAR(40)) AS rec
FROM DBC.DBCInfoV WHERE InfoKey = 'VERSION'
UNION ALL
SELECT 'td_version|' || TRIM(InfoData) FROM DBC.DBCInfoV WHERE InfoKey = 'VERSION';
```

## Storage & skew

```sql
-- Per database (summed across AMPs). HAVING drops empty databases.
SELECT TRIM(DatabaseName) || '|' ||
       TRIM(CAST(SUM(CurrentPerm) AS BIGINT)) || '|' ||
       TRIM(CAST(SUM(MaxPerm)     AS BIGINT)) AS rec
FROM DBC.DiskSpaceV
GROUP BY DatabaseName
HAVING SUM(CurrentPerm) > 0
ORDER BY SUM(CurrentPerm) DESC;

-- Per table (summed across AMPs) — total sizes + largest-table ranking.
SELECT TRIM(DataBaseName) || '|' || TRIM(TableName) || '|' ||
       TRIM(CAST(SUM(CurrentPerm) AS BIGINT)) AS rec
FROM DBC.TableSizeV
GROUP BY DataBaseName, TableName
HAVING SUM(CurrentPerm) > 0
ORDER BY SUM(CurrentPerm) DESC;

-- Per AMP (Vproc) — drives system-wide skew and AMP count (~#AMPs rows).
SELECT TRIM(CAST(Vproc AS INTEGER)) || '|' ||
       TRIM(CAST(SUM(CurrentPerm) AS BIGINT)) AS rec
FROM DBC.TableSizeV
GROUP BY Vproc
ORDER BY Vproc;
```

**System skew** is derived from the per-AMP space: `system_skew_pct = (1 - avg/max) * 100`
over each AMP's `SUM(CurrentPerm)`. High skew on the source is a signal for choosing
Redshift `DISTKEY`/`DISTSTYLE` (see `references/teradata/architecture-mapping.md`).

## Object inventory

```sql
-- Counts by TableKind: T=table, V=view, M=macro, P=procedure; others → 'other'.
SELECT TRIM(DatabaseName) || '|' || TRIM(TableKind) || '|' ||
       TRIM(CAST(COUNT(*) AS BIGINT)) AS rec
FROM DBC.TablesV
GROUP BY DatabaseName, TableKind
ORDER BY DatabaseName, TableKind;
```

For the **conversion** phase, extract column and index detail per table, and the DDL.

> **These are NOT part of the fixed discovery bundle** (the 14 inventory queries above /
> below). They are parameterized or dynamic, so the AI runs them **on demand during
> conversion**, not as static bundle files:
>
> - **Connected mode:** bind `DatabaseName` per user database (loop over the databases found
>   in `dbc_tablesv`), and loop `SHOW TABLE`/`SHOW VIEW` over each object.
> - **Disconnected mode:** the operator either substitutes the target database name into the
>   `WHERE` before running (dropping the `?`), or the AI templates one file per database.
>   `SHOW TABLE`/`SHOW VIEW` must be expanded to concrete object names first — they cannot
>   ship as a single static file.
> Their output is per-conversion, not part of `inventory.json`.

```sql
-- Columns (feeds data-type-mapping + DDL generation).  ? = one user database
SELECT DatabaseName, TableName, ColumnName, ColumnType, ColumnLength,
       DecimalTotalDigits, DecimalFractionalDigits, Nullable, DefaultValue, ColumnId
FROM DBC.ColumnsV
WHERE DatabaseName = ?            -- scope to user databases
ORDER BY DatabaseName, TableName, ColumnId;

-- Indexes → PI/PPI/secondary (feeds PI→DISTKEY, PPI→SORTKEY).  ? = one user database
SELECT DatabaseName, TableName, IndexNumber, IndexType, UniqueFlag, ColumnName, ColumnPosition
FROM DBC.IndicesV
WHERE DatabaseName = ?
ORDER BY DatabaseName, TableName, IndexNumber, ColumnPosition;
```

Authoritative DDL comes from `SHOW` (dynamic — expand `<db>.<table>` from `dbc_tablesv`):

```sql
SHOW TABLE <db>.<table>;     -- canonical DDL (PI/PPI, COMPRESS, MULTISET, etc.)
SHOW VIEW <db>.<view>;
```

## Workload signal

`DBC.AMPUsageV` is the **always-available** coarse signal (cumulative since last reset);
richer history (`DBQLogTbl`, `ResUsageSpma`) is often disabled — see
`references/teradata/performance.md` for those plus sizing.

```sql
-- Coarse cumulative CPU/IO by account+user (always on).
SELECT TRIM(AccountName) || '|' || TRIM(UserName) || '|' ||
       TRIM(CAST(SUM(CpuTime) AS BIGINT)) || '|' ||
       TRIM(CAST(SUM(DiskIO)  AS BIGINT)) AS rec
FROM DBC.AMPUsageV
GROUP BY AccountName, UserName
HAVING SUM(CpuTime) > 0
ORDER BY SUM(CpuTime) DESC;
```

## Availability (optional sources may be off)

DBQL and ResUsage are frequently disabled on a source system. Probe each with a row
count; **0 rows → mark the source `unavailable` and continue** — the inventory always
parses without them.

**Never enable logging on the source.** Do not run `BEGIN QUERY LOGGING` /
`REPLACE QUERY LOGGING` (or any DDL/DCL) on the customer's production system — discovery
is strictly SELECT-only, and changing logging state is a production change with storage
and privilege implications. If DBQL is empty, fall back to `DBC.AMPUsageV` (always-on
cumulative CPU/IO by account) as the workload signal, and note the reduced granularity
in the inventory. Only the *customer's own DBA* may choose to enable DBQL, on their
change process — it is never a step this migration performs.

```sql
SELECT 'dbql'     || '|' || TRIM(CAST(COUNT(*) AS BIGINT)) AS rec FROM DBC.DBQLogTbl;
SELECT 'resusage' || '|' || TRIM(CAST(COUNT(*) AS BIGINT)) AS rec FROM DBC.ResUsageSpma;
```

Wrap each optional source as `{status, reason, row_count}` in the contract (below) rather
than assuming it is present.

## `inventory.json` contract

Facts only — no Redshift/target judgments — so the same shape can describe other sources
later. Optional workload sources are availability-wrapped.

```json
{
  "collection_meta": {
    "collected_at": "2026-06-24T03:00:00",
    "td_version": "20.00.30.77",
    "source_host": "<host>",
    "available_sources": ["ampusage", "dbql"]
  },
  "system": { "amp_count": 24, "node_count": 2, "td_version": "20.00.30.77" },
  "storage": {
    "total_current_perm_bytes": 0,
    "total_max_perm_bytes": 0,
    "by_database": [{ "database": "tpcds", "current_perm_bytes": 0, "max_perm_bytes": 0, "is_system": false }],
    "top_tables": [{ "database": "tpcds", "table": "store_sales", "current_perm_bytes": 0 }]
  },
  "skew": {
    "amp_space": [{ "vproc": 0, "current_perm_bytes": 0 }],
    "system_skew_pct": 0.0
  },
  "objects": {
    "by_database": [{ "database": "tpcds", "tables": 24, "views": 0, "macros": 0, "procedures": 0, "other": 0 }]
  },
  "workload": {
    "cpu_io_by_user": [{ "account": "$M", "user": "tester", "cpu_time": 0.0, "disk_io": 0.0 }],
    "query_log":     { "status": "unavailable", "reason": "DBQL logging off (0 rows)", "row_count": 0 },
    "resource_usage":{ "status": "available",   "reason": "", "row_count": 0 },
    "query_stats": null,
    "resource_stats": null
  }
}
```

| Field | Source | Notes |
|-------|--------|-------|
| `system.amp_count` | distinct `Vproc` in TableSizeV | parallelism driver for sizing |
| `system.node_count` | best-effort | often null offline |
| `storage.by_database[].is_system` | name allowlist | `DBC`, `TD*`, `TDaaS_*`, `Sys*`, … excluded from user storage |
| `skew.system_skew_pct` | `(1 - avg/max) * 100` over per-AMP perm | DISTKEY signal |
| `objects.by_database[]` | `TablesV.TableKind` | `T/V/M/P`, else `other` |
| `workload.query_log` / `resource_usage` | probe row counts | `unavailable` when 0 rows |
| `workload.query_stats` / `resource_stats` | DBQL / ResUsage | populated only when available — see `performance.md` |

## Gotchas (learned on a live Vantage 20.00)

- **`TableSizeV` has no `RowCount` column** and is **per-AMP** → always `SUM(CurrentPerm)
  GROUP BY` table/AMP. For row counts use `SELECT COUNT(*)` per table (or collected stats),
  never TableSizeV.
- **PI on a PPI table reports `IndexType='Q'`**, not `'P'` — identify the primary index by
  `IndexNumber = 1` rather than filtering `IndexType='P'`, or PPI tables lose their PI.
- **Constant `SELECT` without `FROM` fails inside a `UNION`** (Failure 3888). Anchor any
  literal row to a 1-row catalog read, e.g. `... FROM DBC.DBCInfoV WHERE InfoKey='VERSION'`.
- **`GROUP BY 1` fails when column 1 contains an aggregate** (Failure 3625) → group by the
  underlying expression, not the positional alias.
- `DBC.AMPUsageV` is **cumulative since the last reset** — treat it as a coarse relative
  signal, not an absolute window.

## Execution modes

The AI generates the collector at run time — nothing executable ships with the skill.
Pick the mode from how the customer can reach the source:

- **Connected** — the AI generates a runner (e.g. `teradatasql`) that runs the queries and
  writes `result/inventory.json` directly.
- **Disconnected** — the AI emits a portable bundle the operator runs on a reachable host:
  each query as a static `.sql` file plus a thin BTEQ driver (or plain SQL), returning the
  dumps that are then parsed into `inventory.json`.

In both modes the queries above are the single source; the generated driver only runs them.

> **Client prerequisite.** The **BTEQ driver** needs the Teradata client (TTU) — **Linux/Windows
> only, not macOS**. On a host without TTU (e.g. macOS), generate the **`teradatasql`** collector
> instead (pure-Python, cross-platform); reserve the BTEQ driver for hosts that already have TTU.

### BTEQ driver template (disconnected mode)

The AI emits one `.sql` file per query under a `sql/` subfolder, alongside a driver
`collect.btq`. This is a **template to generate, not a shipped file**; it is READ-ONLY
(SELECT against `DBC` only) and safe for a DBA to run on production.

**Fixed bundle contract — generate exactly these 14 files with these names.** The `.sql`
stem, the `.EXPORT` CSV stem, and the parser key are all the same string, so the names are a
contract, not a free choice. Where one `DBC` view backs several queries, the grain suffix
disambiguates:

| `.sql` file (→ same-stem `.csv`) | DBC view | grain / purpose |
|----------------------------------|----------|-----------------|
| `manifest` | DBCInfoV | provenance: collected_at + td_version |
| `dbc_dbcinfov` | DBCInfoV | version / release |
| `dbc_diskspacev` | DiskSpaceV | per-database perm space |
| `dbc_tablesizev_by_table` | TableSizeV | per-table size (top tables) |
| `dbc_tablesizev_by_amp` | TableSizeV | per-AMP space (skew + AMP count) |
| `dbc_tablesv` | TablesV | object counts by TableKind |
| `dbc_ampusagev` | AMPUsageV | cumulative CPU/IO by account+user |
| `dbc_dbqlogtbl` | DBQLogTbl | availability probe (row count) |
| `dbc_dbqlogtbl_summary` | DBQLogTbl | overall stats |
| `dbc_dbqlogtbl_by_statement` | DBQLogTbl | statement-type mix |
| `dbc_dbqlogtbl_by_user` | DBQLogTbl | top users |
| `dbc_dbqlogtbl_by_hour` | DBQLogTbl | count by hour (peak_hour) |
| `dbc_resusagespma` | ResUsageSpma | availability probe (row count) |
| `dbc_resusagespma_summary` | ResUsageSpma | CPU-busy% summary |

`ColumnsV` / `IndicesV` / `SHOW` are **not** in this bundle — they run during conversion (see
"Object inventory" above). Driver step order follows the table top-to-bottom. Example driver:

```bteq
/* collect.btq — generated BTEQ driver (READ-ONLY). Run from the bundle root. */
.LOGON <HOST>/<USER>
.SET WIDTH 500
.SET TITLEDASHES OFF
.SET FOLDLINE OFF

.EXPORT REPORT FILE=dbc_diskspacev.csv
.RUN FILE = sql/dbc_diskspacev.sql
.EXPORT RESET

/* ... one .EXPORT REPORT / .RUN FILE / .EXPORT RESET triple per query ... */

.LOGOFF
.QUIT
```

BTEQ dot-commands used, and why:

| Command | Purpose |
|---------|---------|
| `.LOGON <HOST>/<USER>` | connect; BTEQ prompts for the password (never hard-code it) |
| `.SET WIDTH 500` | widen the line so long pipe-delimited records aren't truncated |
| `.SET TITLEDASHES OFF` | suppress the `---` dashed separator row under column titles |
| `.SET FOLDLINE OFF` | keep each record on one physical line (no wrapping) |
| `.EXPORT REPORT FILE=<view>.csv` | send the next query's output to a text file (`REPORT`, not `DATA` which is binary) |
| `.RUN FILE = sql/<view>.sql` | run the query from its static `.sql` file |
| `.EXPORT RESET` | close the current export before the next one |

Each query emits one `TRIM(...) || '|' || TRIM(...)` record per row (pipe-delimited), so
the output parses without a header. If a view is unavailable (DBQL/ResUsage logging off, or
no permission) that step yields an empty/short file and collection continues.

**How a human runs the bundle:** edit the `.LOGON` line (`<HOST>`/`<USER>`), then from the
bundle root (so the relative `sql/` paths resolve) run `bteq < collect.btq` (BTEQ prompts
for the password) and return every `dbc_*.csv` plus `manifest.csv` produced.

> Source endpoints (host/port/user) come from `migration-config.yaml` — operator-provided,
> never hard-coded in the skill.
