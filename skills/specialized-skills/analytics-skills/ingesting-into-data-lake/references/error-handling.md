# Error Handling and Troubleshooting

Complete guide for handling common errors and issues during data import into S3 Tables.

## Overview

This reference covers errors encountered during the data import workflow. Errors are organized by workflow phase and severity.

**Connection errors are out of scope for this skill.** JDBC/Snowflake/BigQuery connection failures (timeouts, auth failures, driver not found, SSL errors) belong to `connecting-to-data-source`. When a Glue job fails with a connection-level error, delegate to that skill's troubleshooting rather than debugging here.

## Common Issues by Category

### Schema Mismatch Errors

**Symptoms**:

- Type conversion failures during load
- Column count mismatches between source and target
- Data truncation warnings
- Null values where not expected

**Root Causes**:

- Source data types don't match target Iceberg types
- New columns in source not present in target table
- Missing columns in source that exist in target
- Incompatible type conversions (e.g., string → int with non-numeric values)

**Solutions**:

1. **Type mismatch - can cast safely**:
   - Present conflict to user with example values
   - Offer to add explicit CAST in transformation
   - See [type-transformations.md](type-transformations.md) for casting patterns

2. **Type mismatch - cannot cast**:
   - Show sample problematic values
   - Options:
     - Filter out invalid rows
     - Store as STRING and convert later
     - Fix source data and re-import
   - Let user decide based on data importance

3. **New columns in source**:
   - Suggest schema evolution via ALTER TABLE ADD COLUMNS
   - Show proposed schema change
   - Execute evolution if user approves
   - See [schema-evolution.md](schema-evolution.md)

4. **Missing columns in source**:
   - Ask user how to handle:
     - Default values (e.g., NULL, 0, empty string)
     - Skip these columns (if nullable)
     - Fail the load (if columns are critical)

**Example Error Message to Present**:

```
Schema Mismatch Detected:
- Column "age": Source type STRING, Target type INT
  Sample values: "25", "thirty", "42", "unknown"
  Issue: Values "thirty" and "unknown" cannot convert to INT

Options:
1. Filter out rows with non-numeric ages (loses ~5% of data)
2. Store age as STRING in target table (requires schema change)
3. Replace non-numeric values with NULL (preserves all rows)

Which approach would you prefer?
```

### Permission Errors

**Symptoms**:

- Access Denied errors from AWS services
- IAM role assumption failures
- S3 bucket access errors
- Glue job fails with permission errors

**Root Causes**:

- Missing IAM policies on Glue service role
- S3 bucket policies blocking access
- S3 Tables permissions not configured
- Cross-account access issues

**Solutions**:

1. **Glue service role missing policies**:
   - Check if role has AWSGlueServiceRole managed policy
   - Check if role has S3 read/write permissions
   - Check if role has S3 Tables inline policy
   - See [iam-role-management.md](iam-role-management.md) for complete setup

2. **S3 bucket access denied**:
   - Verify IAM role has s3:GetObject, s3:ListBucket on source bucket
   - Verify IAM role has s3:PutObject on script/results buckets
   - Check S3 bucket policies don't block the role
   - For cross-account: verify bucket policy allows role ARN

3. **S3 Tables access denied**:
   - Verify inline policy includes:
     - s3tables:PutTableData
     - s3tables:GetTableMetadataLocation
     - s3tables:GetTable
     - s3tables:UpdateTableMetadataLocation
   - Verify resource ARN matches table bucket structure
   - See [iam-role-management.md](iam-role-management.md#s3-tables-inline-policy)

4. **Athena query execution errors**:
   - Verify workgroup has output location configured
   - Verify IAM has athena:StartQueryExecution
   - Verify IAM has s3:PutObject on results bucket

**Example Error Message to Present**:

```
Permission Error Detected:
Glue job failed with: "Access Denied" when writing to table

Root cause: IAM role "GlueServiceRole-import" is missing S3 Tables permissions

Required actions:
1. Add inline policy to role with s3tables:PutTableData permission
2. Resource ARN should be: arn:aws:s3tables:us-east-1:123456789012:bucket/my-table-bucket/namespace/my-namespace/table/*

Would you like me to add this policy to the role?
```

### Data Quality Failures

**Symptoms**:

- Glue Data Quality rules fail
- Row counts don't match expected
- High null percentages in critical columns
- Duplicate primary keys detected

**Root Causes**:

- Source data quality issues
- Incorrect transformation logic
- Schema inference errors
- Data quality rules too strict

**Solutions**:

1. **Row count mismatch**:
   - Compare source row count vs target row count
   - Check Glue job logs for filtering or errors
   - Verify no duplicate writes occurred
   - Check if partitioned data was partially loaded

2. **High null percentage**:
   - Show which columns have unexpected nulls
   - Check if type conversion failures resulted in nulls
   - Ask user if nulls are acceptable or if source needs fixing
   - Adjust data quality thresholds if appropriate

3. **Duplicate keys**:
   - Show sample duplicate values
   - Options:
     - Add deduplication logic (keep latest/first)
     - Investigate source for duplicates
     - Fail load and fix source
   - Add DISTINCT or window function to transformation

4. **Data quality rule failures**:
   - Show which rules failed and why
   - Distinguish critical vs warning rules
   - Options:
     - Adjust rule thresholds (if too strict)
     - Fix source data (if data is actually bad)
     - Proceed with warnings (if non-critical)
   - See [data-quality-validation.md](data-quality-validation.md)

**Example Error Message to Present**:

```
Data Quality Check Failed:
- Rule: IsPrimaryKey "order_id"
- Failure: Found 127 duplicate order_ids (0.5% of total rows)
- Sample duplicates: [10234, 10567, 10892, ...]

This could indicate:
1. Source data has duplicates (check data generation process)
2. Multiple loads without deduplication
3. Partition key included in order_id

Options:
1. Add deduplication keeping the latest record by timestamp
2. Investigate source system for root cause
3. Proceed with warning (not recommended for primary key)

How would you like to proceed?
```

### Large Dataset Timeouts (Athena)

**Symptoms**:

- Athena query exceeds 30-minute timeout
- Query runs out of memory
- S3 read throttling errors

**Root Causes**:

- Dataset too large for single Athena query
- Insufficient Athena engine size
- Too many small files causing S3 throttling
- Complex transformations in single query

**Solutions**:

1. **Break into batches**:
   - Split by date range or partition
   - Load in multiple INSERT queries
   - Example: Load one month at a time

2. **Switch to Glue ETL**:
   - Glue can handle larger datasets with multiple workers
   - Better for datasets > 1GB or millions of rows
   - Provides better monitoring and retry logic
   - See [format-specific-loading.md](format-specific-loading.md) for Glue examples

3. **Increase Athena capacity**:
   - Use Athena v3 engine
   - Increase DPU allocation in workgroup settings
   - Consider Athena provisioned capacity for repeated large queries

4. **Optimize file structure**:
   - Consolidate many small files (use Glue ETL)
   - Use columnar formats (Parquet, ORC)
   - Partition large datasets by date/region

**Example Error Message to Present**:

```
Athena Query Timeout:
Query exceeded 30-minute limit loading 5.2GB of data

Recommendations:
1. Switch to Glue ETL (recommended for datasets > 1GB)
   - Can handle 5.2GB with 5 G.1X workers in ~15 minutes
   - Better error handling and monitoring

2. Batch the load by date partition
   - Load 2024-01 through 2024-06 separately (6 queries)
   - Each query would handle ~850MB

Would you like me to:
A) Create a Glue ETL job for this load (recommended)
B) Set up batched Athena queries by month
```

### Format-Specific Issues

#### CSV Parsing Errors

**Symptoms**:

- Columns shifted or misaligned
- Quoted values not parsed correctly
- Extra or missing columns

**Solutions**:

- Verify delimiter matches file (comma, tab, pipe)
- Set `.option("quote", "\"")` for quoted fields
- Set `.option("escape", "\\")` for escaped characters
- Use `.option("mode", "DROPMALFORMED")` to skip bad rows
- See [format-specific-loading.md](format-specific-loading.md#csv-issues)

#### JSON Parsing Errors

**Symptoms**:

- Multi-line JSON not parsing
- Nested structures flattened incorrectly
- Malformed JSON records causing failures

**Solutions**:

- Set `.option("multiLine", "true")` for multi-line objects
- Use `.option("mode", "PERMISSIVE")` to handle malformed records
- Check JSON schema matches expected structure
- Verify one JSON object per line for JSONL
- See [format-specific-loading.md](format-specific-loading.md#json-issues)

#### Parquet Partition Issues

**Symptoms**:

- Partition columns not detected
- Schema evolution errors
- Missing partitions in results

**Solutions**:

- Verify Hive-style partitioning (key=value/)
- Use `.option("mergeSchema", "true")` for schema evolution
- Check partition column names match across files
- List S3 paths to confirm partition structure
- See [format-specific-loading.md](format-specific-loading.md#parquet-issues)

#### Avro Library Errors

**Symptoms**:

- "Avro library not found" error
- Complex union types failing
- Schema registry connection errors

**Solutions**:

- Add `--datalake-formats: iceberg,avro` to Glue job arguments
- Or provide spark-avro JAR via `--extra-jars`
- Convert complex unions to STRING or handle with conditional logic
- See [format-specific-loading.md](format-specific-loading.md#avro-issues)

## Error Severity Levels

### Critical (Fail Immediately)

These errors should stop the workflow:

- IAM role doesn't exist or can't be assumed
- Source S3 path doesn't exist or is empty
- Target table exists with incompatible schema (cannot evolve)
- Primary key violations in data quality checks

**Action**: Present error clearly, provide remediation steps, wait for user action

### Warnings (Proceed with Caution)

These issues should be flagged but allow continuation:

- High null percentage in optional columns
- Data quality warnings (not critical rules)
- Schema evolution needed (user approval required)
- Source files have malformed records (but most are valid)

**Action**: Show warning with details, ask user if they want to proceed

### Informational

These are expected and don't require action:

- Using CLI fallback because MCP unavailable
- Sampling large files for schema inference
- Automatically inferring schema from source
- Creating IAM role because none exists

**Action**: Log for user visibility, proceed automatically

## Troubleshooting Workflow

When encountering an error:

1. **Identify the phase**: Which workflow phase failed?
2. **Read the error**: Get full error message from CloudWatch/Athena
3. **Check permissions**: Verify IAM role has required policies
4. **Validate data**: Sample source data to check format/quality
5. **Review configuration**: Check Glue job args, Athena settings
6. **Consult logs**: Check CloudWatch logs for detailed stack traces
7. **Search references**: Check relevant reference doc for issue type

## Getting Help

When presenting errors to users:

1. **Be specific**: Show exact error message and where it occurred
2. **Provide context**: What was being attempted when error happened
3. **Offer solutions**: Present 2-3 actionable options
4. **Show impact**: Explain what happens if user chooses each option
5. **Ask clearly**: Make the choice or next action explicit

## Best Practices

1. **Validate early**: Check permissions and schema before starting load
2. **Sample first**: Test with small subset before full load
3. **Monitor actively**: Watch CloudWatch logs during execution
4. **Handle gracefully**: Don't let jobs fail silently - surface errors
5. **Document issues**: Keep track of common errors and solutions
6. **Test transformations**: Verify type casts and filters on sample data

## Summary

Error handling workflow:

1. **Detect error** - Identify error type and severity
2. **Diagnose root cause** - Check logs, permissions, data
3. **Present clearly** - Show error and context to user
4. **Offer solutions** - Provide 2-3 actionable options
5. **Execute fix** - Apply chosen solution and retry
6. **Validate resolution** - Confirm error is resolved

With comprehensive error handling, the skill can guide users through issues confidently and get data loaded successfully.
