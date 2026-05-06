# Creating S3 Tables with Spark DDL in Glue ETL

Use when building Glue ETL pipelines that create and write to S3 Tables. Tables created via the S3 Tables API (`aws s3tables create-table --metadata`) are also readable by Spark.

## Critical Requirements

- **Glue 5.1 or higher** is required (Spark 3.5.6, Iceberg 1.10.0). Do NOT use Glue 4.0.
- **`--datalake-formats iceberg`** MUST be set as a job argument
- Table bucket and namespace MUST exist before running the job

## Static Config Gotcha (Most Common Failure)

In Glue 5.x, catalog configs are **static** and MUST go in `--conf` job arguments. Using `spark.conf.set()` throws:

```
AnalysisException: Cannot modify the value of a static config: spark.sql.extensions
```

**Rule:** All `spark.sql.catalog.*` configuration goes in `--conf`, never in the PySpark script.

**Rule:** Catalog and database names containing hyphens MUST be backtick-escaped in Spark SQL (e.g., `` `my-catalog`.`my-db`.my_table ``). Without backticks, Spark returns `INVALID_IDENTIFIER`.

## Access Methods

| Method | Athena/Redshift access | Recommended |
|--------|----------------------|-------------|
| Analytics Integration (GlueCatalog) | Yes | Yes, if multi-service |
| REST Endpoint | No (Glue-only) | Yes, if Glue-only |

### REST Endpoint (simplest)

```
spark.sql.catalog.<name>=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.<name>.type=rest
spark.sql.catalog.<name>.uri=https://s3tables.<region>.amazonaws.com/iceberg
spark.sql.catalog.<name>.warehouse=<table_bucket_arn>
spark.sql.catalog.<name>.rest.sigv4-enabled=true
spark.sql.catalog.<name>.rest.signing-name=s3tables
spark.sql.catalog.<name>.rest.signing-region=<region>
spark.sql.catalog.<name>.io-impl=org.apache.iceberg.aws.s3.S3FileIO
```

### Analytics Integration (for Athena/Redshift access)

```
spark.sql.catalog.<name>=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.<name>.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog
spark.sql.catalog.<name>.glue.id=<account_id>:s3tablescatalog/<table_bucket_name>
spark.sql.catalog.<name>.warehouse=<table_bucket_arn>
```

The `warehouse` parameter is required — without it Spark fails with "Cannot derive default warehouse location".

## `--conf` Format Rules

The `--conf` argument is a single string with space-separated `--conf key=value` pairs:

```json
"--conf": "spark.sql.catalog.s3tables=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.s3tables.type=rest --conf ..."
```

First key-value has no `--conf` prefix. Use `--cli-input-json file://config.json` to avoid shell escaping.

## Glue Job Config Example (REST Endpoint)

**job-config.json:**

```json
{
    "Name": "my-etl-job",
    "Role": "arn:aws:iam::<ACCOUNT>:role/<GLUE_ROLE>",
    "Command": {
        "Name": "glueetl",
        "ScriptLocation": "s3://<BUCKET>/scripts/my_etl.py",
        "PythonVersion": "3"
    },
    "DefaultArguments": {
        "--datalake-formats": "iceberg",
        "--conf": "spark.sql.catalog.s3tables=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.s3tables.type=rest --conf spark.sql.catalog.s3tables.uri=https://s3tables.<REGION>.amazonaws.com/iceberg --conf spark.sql.catalog.s3tables.warehouse=<TABLE_BUCKET_ARN> --conf spark.sql.catalog.s3tables.rest.sigv4-enabled=true --conf spark.sql.catalog.s3tables.rest.signing-name=s3tables --conf spark.sql.catalog.s3tables.rest.signing-region=<REGION> --conf spark.sql.catalog.s3tables.io-impl=org.apache.iceberg.aws.s3.S3FileIO",
        "--catalog_name": "s3tables",
        "--namespace": "<NAMESPACE>",
        "--table_name": "<TABLE_NAME>"
    },
    "GlueVersion": "5.1",
    "NumberOfWorkers": 2,
    "WorkerType": "G.1X"
}
```

For Analytics Integration, replace the `--conf` value with: `spark.sql.catalog.s3tablescatalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.s3tablescatalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.s3tablescatalog.glue.id=<ACCOUNT>:s3tablescatalog/<BUCKET_NAME> --conf spark.sql.catalog.s3tablescatalog.warehouse=<TABLE_BUCKET_ARN>`

## PySpark Script

Catalog config is in `--conf`, so the script is clean:

```python
import sys
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'catalog_name', 'namespace', 'table_name'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Do NOT call spark.conf.set() for catalog config in Glue 5.x
# catalog_name must match spark.sql.catalog.<name> from --conf

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {args['catalog_name']}.{args['namespace']}.{args['table_name']} (
  col1 STRING,
  col2 INT
)
USING iceberg
PARTITIONED BY (col1)
""")
# No LOCATION clause -- S3 Tables manages storage

job.commit()
```

## IAM Requirements

The Glue service role needs: `AWSGlueServiceRole` plus `s3tables:GetTableBucket`, `s3tables:GetNamespace`, `s3tables:ListNamespaces`, `s3tables:CreateTable`, `s3tables:GetTable`, `s3tables:ListTables`, `s3tables:UpdateTableMetadataLocation`, `s3tables:GetTableMetadataLocation`, `s3tables:GetTableData`, `s3tables:PutTableData`, and `glue:GetCatalog`, `glue:GetDatabase`, `glue:GetTable`, `glue:passConnection`. Table bucket, namespace, and Glue catalog MUST be created before the Glue job runs (Steps 3-5 in SKILL.md). For exact resource ARN scoping, see `access-control.md`.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Cannot modify static config" | Remove `spark.conf.set()`. Use `--conf` job argument. |
| "Access Denied" on S3 Tables | Check Glue role has granular `s3tables:` permissions. See IAM Requirements above. |
| Shell escaping breaks `--conf` | Use `--cli-input-json file://config.json`. |
| Table not visible in Athena | REST endpoint tables aren't in Athena. Use Analytics Integration. |
| Catalog not found | Ensure catalog name in script matches `spark.sql.catalog.<name>` from `--conf`. |

## Additional Resources

For latest Glue ETL guidance, search AWS docs for `"Running ETL jobs on Amazon S3 tables with AWS Glue"`.
