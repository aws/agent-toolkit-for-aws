# S3 File Import

Import structured data files (CSV, TSV, JSON, Parquet, Avro, ORC) from S3 into tables.

## Workflow

### Phase 0: Understand Intent and Check Tools

1. **Detect load pattern**: One-time ("load this file") vs recurring ("set up a pipeline", "keep updated")
2. **Choose approach**: Glue ETL (default, can be scheduled) vs Athena (fallback for simple loads)
3. **Require Glue 5.1 or higher** for all Iceberg targets (S3 Tables and standard Iceberg).
4. **Discover available MCP tools**: Search for S3 Tables MCP, Data Processing MCP, IAM MCP by keyword -- do not hardcode tool names.

Use MCP tools when available. Fall back to AWS CLI only when MCP tool discovery finds no matching tools.

### Phase 1: Discover Source Data

1. **Identify source**: Ask user for S3 path and file format (CSV, JSON, Parquet, Avro, ORC)
2. **Sample files**: List and download samples to understand structure
3. **Detect partitions**: For Parquet/ORC, look for Hive-style partitioning (`year=2024/month=01/`)

Format-specific guidance: See [format-specific-loading.md](format-specific-loading.md)

### Phase 2: Infer and Validate Schema

1. **Build schema**: CSV (headers + sample values), JSON (type mapping), Parquet/Avro/ORC (embedded schema)
2. **Map types**: Source types to target types (STRING to INT/DATE/TIMESTAMP based on content). See [type-transformations.md](type-transformations.md).
3. **Handle conflicts**: New columns (schema evolution via ALTER TABLE), type mismatches (cast/skip/fail), missing columns (ask user: use NULL or fail)
4. **Nested JSON/arrays** (if detected): Ask the user which approach they prefer before proceeding:
   - **Flatten** -- Expand structs into separate columns, explode arrays into rows
   - **Preserve** -- Keep as STRUCT/ARRAY types
   - Do not proceed until the user has chosen.

Schema evolution and nested data: See [schema-evolution.md](schema-evolution.md)

### Phase 3: Set Up or Verify Target Table

1. **Check if table exists** using MCP or CLI
2. **Create table if needed**: Delegate to [creating-data-lake-table](../../creating-data-lake-table/SKILL.md) for all target types. Pass the target format (S3 Tables, standard Iceberg, or raw files) and schema. See [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md) for target-specific catalog configuration used in the subsequent Glue job.
3. **Evolve schema if needed**: Compare schemas, generate ALTER TABLE ADD COLUMNS, execute via Athena

### Phase 3.5: Verify or Create IAM Role for Glue

1. **Check for existing role**: Look for `AWSGlueServiceRole-*` or `GlueServiceRole-*`
2. **Verify permissions**: AWSGlueServiceRole managed policy, S3 access, S3 Tables inline policy (if S3 Tables target)
3. **Create role if needed**: Trust policy for `glue.amazonaws.com`, attach policies, capture role ARN

Complete IAM setup: Handled by [creating-data-lake-table](../../creating-data-lake-table/SKILL.md).

### Phase 4: Execute Data Load

#### Path A: Glue ETL (Primary)

Create PySpark script, create Glue job with catalog config from [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md), test job, schedule if recurring.

**When to use**: Default for most loads. Required for recurring/scheduled imports, complex transformations, large datasets (millions+ rows).

Guides: [format-specific-loading.md](format-specific-loading.md), [glue-job-config.md](glue-job-config.md), [glue-job-scripts.md](glue-job-scripts.md)

#### Path B: Athena (Fallback)

Create external table, build INSERT INTO query with transformations, execute and monitor, clean up.

**When to use**: Simple one-time loads only. Small to medium datasets. SQL transformations sufficient.

Guide: [athena-loading.md](athena-loading.md)

### Phase 5: Validate Data Load

1. Row count validation
2. Null checks on critical columns
3. Type validation via sample check
4. Spot-check data

See [data-quality-validation.md](data-quality-validation.md)

### Phase 6: Report Results

Present summary: what was loaded, how to query, any issues, next steps.

## Decision Trees

### Glue ETL vs Athena

**Use Glue ETL** when: recurring loads, complex transforms, large datasets, format-specific handling, data quality validation.

**Use Athena** when: simple one-time load, small/medium dataset, SQL transforms sufficient, Glue unavailable.

### Glue Triggers vs MWAA

**Use Glue Triggers** (most cases): single job, simple schedule, no complex dependencies.

**Use MWAA/Airflow** (advanced): multiple sources with coordinated loading, complex dependencies, branching logic.

## Argument Routing

- **S3 path only**: Infer one-time load, proceed with discovery
- **S3 path + table name**: Check if table exists, infer schema, execute load
- **"--recurring" or "--pipeline"**: Force recurring pipeline via Glue
- **No args**: Walk through workflow interactively

## Gotchas

- S3 Tables requires Glue 5.1 or higher. Standard Iceberg also requires Glue 5.1 or higher for proper Iceberg compatibility.
- S3 Tables CREATE TABLE must NOT include a LOCATION clause. Standard Iceberg MUST include one.
- When creating tables for S3 Tables import, use the Spark DDL path (Path B) in creating-data-lake-table to ensure the Glue catalog is configured.
- Target-specific catalog configuration and Glue version requirements are defined in [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md).

## References

- [format-specific-loading.md](format-specific-loading.md)
- [type-transformations.md](type-transformations.md)
- [schema-evolution.md](schema-evolution.md)
- [data-quality-validation.md](data-quality-validation.md)
- [athena-loading.md](athena-loading.md)
- [error-handling.md](error-handling.md)
- [iceberg-catalog-config-and-usage.md](iceberg-catalog-config-and-usage.md)
- [glue-job-config.md](glue-job-config.md)
- [glue-job-scripts.md](glue-job-scripts.md)
