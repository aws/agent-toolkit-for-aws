# Data migration patterns

> AI-facing knowledge: patterns + templates the AI uses to **generate** extract/load scripts.
> Distilled from the proven pre-restructure `tools/data_migration/` implementation.

## Purpose
Move table data from Teradata to Redshift reliably and restartably, producing
`output/data_migration/result/migration_manifest.json` for validation to consume.

## The pipeline, per table

```
estimate volume ─▶ extract (TD → file) ─▶ stage to S3 ─▶ COPY into Redshift ─▶ confirm row count
```

Each table is independent: a failure on one is recorded and the rest continue (see *Checkpointing*).

## 1. Estimate volume (before moving anything)
Drives chunking decisions and is reused by validation as the authoritative source count.

- **Size:** `SELECT SUM(CurrentPerm) AS size_bytes FROM DBC.TableSizeV WHERE DataBaseName = ? AND TableName = ?`
  — `CurrentPerm` is split across AMPs, so it **must be summed per table** for total on-disk bytes.
- **Row count:** exact `SELECT COUNT(*) FROM schema.table`. Teradata's catalog has no reliable
  live row count, and the exact count is reused by validation, so pay the `COUNT(*)` cost once.

## 2. Extract — three paths
All write **directly to S3 (no local-disk hop)** and return the `s3://` **prefix** (a
directory of split part-files, per §3 — not a single object).

### When-to-use matrix

| Path | When to use | Mechanism | Output | Notes |
|------|-------------|-----------|--------|-------|
| **WRITE_NOS** (canonical) | Vantage **≥ 17.05** (verify per edition) *and* the cluster is allowed direct S3 egress. **Runs in-database — no Teradata client needed (invoke over any SQL client incl. `teradatasql`), so it works from macOS.** Test cluster is 20.00 → default here. | In-database `WRITE_NOS` — the SQL engine writes **Parquet to S3 in parallel, one object per AMP**, with no external host. | Parquet | No TPT host to install/operate; parallelism = AMP count; native multi-object output already satisfies the split rule (§3). Needs an `AUTHORIZATION` object (IAM role / access keys) and outbound S3 access from the DB nodes. |
| **TPT** | Older Vantage (< 17.05) **or** locked-down sites with no direct DB→S3 egress. **Requires the Teradata client (TTU: `tbuild`/BTEQ) on a Linux/Windows host — not available on macOS**; extract on that TPT host, then stage to S3. | Teradata Parallel Transporter EXPORT operator → `DATACONNECTOR CONSUMER` file-writer on the dedicated TPT host. | **Delimited** (pipe/CSV) | High-throughput, partitioned. **The DataConnector operator does not natively emit Parquet** — its `Format` values are `Delimited`/`Binary`/`Text`/`Formatted`/`Unformatted`. For Parquet use WRITE_NOS; on TPT, extract delimited and COPY as CSV (§4). Verify object-store/format support for **your** TPT version before relying on it. |
| **`teradatasql`** (Python driver) | The **cross-platform, no-client** host-side path (pip-installable — **works on macOS**). Use when there is **no TTU/Linux host** for TPT (and WRITE_NOS isn't available), or for small/medium tables and smoke tests. | `SELECT * FROM table` over `teradatasql` → pyarrow Parquet, written as **multiple row-group part-files** → `s3.put_object` per part. | Parquet | Streams rows through the Python process — not for huge tables. Split into part-files (§3) rather than buffering one giant object in memory. |

**Format:** prefer **Parquet** (WRITE_NOS / interim) over delimited — better COPY throughput
and type fidelity. **Delimited (CSV/pipe) is the fallback**, and is the *only* native option
on the TPT path.

> **Operator-host prerequisites.** TPT and BTEQ require the Teradata client (**TTU**), which is
> **Linux/Windows only — not macOS**. On a Mac (or any host without TTU) the viable extract paths
> are **WRITE_NOS** (in-database, no client) and **`teradatasql`** (pure-Python, cross-platform);
> use TPT only when a Linux TTU host exists.

### WRITE_NOS export (canonical — template the AI generates)

```sql
/* WRITE_NOS export — <schema>.<table> → S3 (parallel Parquet, one object per AMP) */
SELECT * FROM WRITE_NOS (
  ON ( SELECT * FROM <schema>.<table> )
  USING
    LOCATION('/s3/<bucket>.s3.amazonaws.com/<staging-prefix>/<schema>/<table>/<strategy>/')
    AUTHORIZATION(<auth-object-or-role>)     /* Prefer an IAM-role auth object; access keys only as fallback where roles can't attach. Never inline secrets */
    STOREDAS('PARQUET')
    /* MAXOBJECTSIZE intentionally omitted — its valid range is narrow + version-specific */
    /* (Teradata examples use '4MB'; verify your version). WRITE_NOS then writes objects   */
    /* smaller than the 100MB–1GB COPY sweet spot — fine: many small Parquet files still   */
    /* parallelize COPY across slices (§3).                                                */
    COMPRESSION('SNAPPY')
) AS d;
```

`WRITE_NOS` emits multiple Parquet objects under the prefix automatically (one or more per
AMP), so the split rule in §3 is satisfied with no extra work.
Requires Vantage ≥ 17.05 (verify per edition) and DB-node outbound access to S3.

### TPT export script (fallback — template the AI generates)

```
/* TPT EXPORT job — <schema>.<table> (delimited; NOT Parquet — see the matrix above) */
DEFINE JOB EXPORT_<schema>_<table>
(
  DEFINE OPERATOR td_export
    TYPE EXPORT  SCHEMA *
    ATTRIBUTES ( VARCHAR TdpId=@TdpId, VARCHAR UserName=@UserName,
                 VARCHAR UserPassword=@UserPassword,
                 VARCHAR SelectStmt='SELECT * FROM <schema>.<table>;' );
  DEFINE OPERATOR file_writer
    TYPE DATACONNECTOR CONSUMER  SCHEMA *
    ATTRIBUTES ( VARCHAR Format='Delimited', VARCHAR TextDelimiter='|',
                 VARCHAR FileName='<schema>.<table>-${JOBID}.csv',
                 VARCHAR OpenMode='Write' );
  APPLY TO OPERATOR (file_writer) SELECT * FROM OPERATOR (td_export);
);
```

Connection-dependent attributes (`@TdpId`, working dirs) stay as named placeholders the
operator fills in. Emit **multiple part-files** (one per producer instance) to satisfy the
split rule in §3 rather than a single delimited file; then COPY as CSV (§4).

## 3. Stage to S3 — key layout + file splitting
**Staging-bucket security (set up once per migration):** enable default encryption (SSE-S3 or
SSE-KMS); deny non-TLS access via a bucket-policy condition (`"aws:SecureTransport": "false"` →
Deny); enable S3 access logging or CloudTrail S3 data events (audit who touched extracted data);
add a lifecycle rule to auto-expire staged objects after cutover.
Partition by table and strategy so each table's loads are isolated and auditable. Each
table is a **prefix (directory) of multiple part-files**, not a single object:

```
<staging-prefix>/<schema>/<table>/<strategy>/        ← the prefix COPY reads
    part-0001.parquet
    part-0002.parquet
    …
```

Parse `s3://bucket/prefix/` into `(bucket, prefix)`; keep the trailing slash so keys
concatenate cleanly. The manifest's `s3_path` records this **prefix** (see the schema below).

### File-splitting rule (why multiple objects)
A **single** object per table makes Redshift COPY load on **one slice**, serializing the
whole table through a single stream — needlessly slow for large tables (e.g. Scenario B's
`store_sales`, ~2.9M rows). Split every table into multiple objects so COPY parallelizes
across slices:

- **Count:** a **multiple of the cluster's total slice count** (so every slice gets even
  work). Small tables can stay as one file.
- **Size:** target **~100 MB–1 GB per object** (compressed). Below ~100 MB the per-file
  overhead dominates; above ~1 GB you lose parallelism granularity.
- **Per path:** WRITE_NOS produces one or more objects per AMP automatically (already
  split — usually nothing more to do); TPT emits one file per producer instance; the interim
  `teradatasql` path writes one part-file per row-group batch.

Cluster slice count comes from the sizing profile (`sizing.md`) / the target node config.

## 4. Load — Redshift COPY from S3
Full-load is **truncate-then-COPY** so a re-run is idempotent (no duplicate rows). COPY the
**prefix** (not a single file) so it fans the split part-files (§3) across all slices in
parallel:

```sql
TRUNCATE <schema>.<table>;
COPY <schema>.<table>
FROM 's3://.../<schema>/<table>/<strategy>/'   -- prefix: all part-files under it load in parallel
IAM_ROLE '<role-arn>'   -- scope this role to s3:GetObject/List on the staging prefix only (no s3:*);
                        -- trust policy: add aws:SourceAccount/aws:SourceArn (or sts:ExternalId) condition keys
FORMAT AS PARQUET;
```

COPY reads **every object under the prefix**, so the file-splitting rule in §3 (slice-multiple
count, ~100 MB–1 GB each) is what makes this load parallel rather than single-slice. Then read
rows loaded with `SELECT pg_last_copy_count();`.

> On the **TPT (delimited) path**, load the same prefix with `FORMAT AS CSV` + the delimited
> options in the matrix below instead of `FORMAT AS PARQUET`.
>
> **COPY caveats (learned the hard way):**
>
> - **`REGION` is rejected with `FORMAT AS PARQUET`** ("REGION argument is not supported for
>   PARQUET based COPY"). The **staging bucket must be in the cluster's region**. (Region is
>   still needed to build the S3 client, just not in the COPY.)
> - The IAM role must be attached to the cluster and allowed to read the staging bucket.
> - COPY matches Parquet columns **by name** — column order need not match, but names must.

### COPY option matrix (by format)

| Concern | Parquet (preferred) | Delimited (CSV/text fallback) |
|---------|---------------------|-------------------------------|
| Format clause | `FORMAT AS PARQUET` | `FORMAT AS CSV` or `DELIMITER '\|'` |
| NULLs | encoded in Parquet | `NULL AS '\\N'` (must match extract) |
| Dates/times | native types | `TIMEFORMAT 'auto'`, `DATEFORMAT 'auto'` |
| Compression | columnar (built-in) | `GZIP` / `BZIP2` on the staged files |
| Bad-row tolerance | n/a (schema-checked) | `MAXERROR <n>` only if a few bad rows are acceptable — default 0 |
| Encoding | — | `ENCODING 'UTF8'` |

## 5. Confirm row count
Immediately compare the exact source `COUNT(*)` (from step 1) to `pg_last_copy_count()`.
**A mismatch is a load failure, not a success** — record it in `failed_tables` with phase
`validate`; never report a partial load as `success`. Deeper checks live in `validation-patterns.md`.

## Strategies

| Strategy | Status | Semantics |
|----------|--------|-----------|
| `full-load` | implemented | TRUNCATE + COPY. Idempotent; safe to re-run. |
| `incremental` | future | Append rows since a high-water-mark column. Must use an append load, **not** the truncate path. |
| `cdc` | future | Change-data-capture apply. Needs change feed design. |

Reject unknown strategies loudly; fail unimplemented ones with a clear message rather than silently doing a full load.

## Checkpointing (restartability)
Track per-table status so a re-run resumes and skips completed tables. This is the
`migration_manifest.json` — it is also the hand-off to validation.

### `migration_manifest.json` schema

```json
{
  "tables": [
    {
      "source_table": "sales.orders",
      "target_table": "sales.orders",
      "s3_path": "s3://stage/sales/orders/full-load/",
      "source_row_count": 1280344,
      "target_row_count": 1280344,
      "status": "success",
      "duration_seconds": 84,
      "data_size_bytes": 690847232
    }
  ],
  "failed_tables": [
    { "table": "sales.returns", "error": "COPY: invalid timestamp", "phase": "load", "retryable": true }
  ],
  "summary": { "total": 2, "success": 1, "failed": 1, "skipped": 0 }
}
```

- `failed_tables[].phase` is one of `extract` | `stage` | `load` | `validate`.
- `retryable` flags transient failures (network, throttling) vs structural ones (bad type).
- `summary` is derived: a non-zero `failed` count pauses the pipeline for review (see `orchestration.md`).

## Security & reliability rules

- Use a **read-only** Teradata user for extraction. Never hard-code or echo credentials. For
  **production**, reference credentials from **AWS Secrets Manager or Parameter Store**; for
  **local development testing only**, a git-ignored credentials file (with a committed
  `credentials.env.example` template) may be used — the real file is never committed.
- **Validate every identifier** (schema/table) against `^[A-Za-z_][A-Za-z0-9_]*$` before inlining
  it into `COUNT(*)` or `COPY` — those positions can't be parameterized, so this is the injection guard.
- Make connections injectable so generated scripts are testable without live TD/RS/S3.
- Put an explicit **timeout** on every extract, COPY, and S3 call — no indefinite waits.

## See also

- `architecture-mapping.md` / `data-type-mapping.md` — target table DDL, DISTKEY/SORTKEY, type/encoding caveats.
- `sizing.md` — target node config / **cluster slice count** used by the file-splitting rule (§3).
- `validation-patterns.md` — consumes `migration_manifest.json` (source counts, table list).
- `orchestration.md` — where data migration sits in the phase pipeline and its HITL gate.
