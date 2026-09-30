# Migration Guide

## When to Activate

User wants to migrate from LiveAnalytics to InfluxDB 3, from self-managed InfluxDB to managed, or from V2 to V3. Covers data export/import and Parquet conversion.

## Migration Paths

### Path 1: LiveAnalytics → InfluxDB 3 (Certified Migration Plugin)

LiveAnalytics is in maintenance mode. Use the **InfluxData certified LiveAnalytics migration plugin** and its companion migration client. **This plugin is recommended for smaller migrations (under 1 billion records / 125GB).** For larger datasets, contact the account team for guidance.

**How it works:**

1. The migration client runs `UNLOAD` to export LiveAnalytics data to S3 in Parquet format
2. The client generates presigned URLs for the Parquet files
3. The client invokes the migration plugin on the InfluxDB 3 cluster
4. The plugin retrieves S3 objects, transforms to line protocol, and writes to InfluxDB 3

**Data mapping:**

| LiveAnalytics Concept | InfluxDB 3 Concept |
|---|---|
| Table | Measurement |
| Dimensions | Tags |
| Measure name | Tag |
| Measures | Fields |
| Time | Timestamp |

**Steps:**

Use a dedicated private export bucket with default SSE-KMS encryption. Before running the migration client, scope both the bucket policy and the KMS key policy to the migration role and any service principals required by the current migration documentation. Grant only the required S3 and KMS actions, require TLS, and block public access.

```bash
# 1. Provision InfluxDB 3 Enterprise cluster (route to getting-started)
# 2. Create S3 bucket for export and apply secure defaults
aws s3api create-bucket --bucket <bucket> \
    --object-lock-enabled-for-bucket --region <region> \
    --create-bucket-configuration LocationConstraint=<region>

aws s3api put-public-access-block \
    --bucket <bucket> \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
    --bucket <bucket> \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "aws:kms",
          "KMSMasterKeyID": "<kms-key-arn>"
        },
        "BucketKeyEnabled": true
      }]
    }'

aws s3api put-bucket-policy \
    --bucket <bucket> \
    --policy '{
      "Version": "2012-10-17",
      "Statement": [{
        "Sid": "DenyInsecureTransport",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "s3:*",
        "Resource": [
          "arn:<partition>:s3:::<bucket>",
          "arn:<partition>:s3:::<bucket>/*"
        ],
        "Condition": {
          "Bool": {
            "aws:SecureTransport": "false"
          }
        }
      }]
    }'

# 3. Run the migration client (recommended on EC2 t3.medium for auto-rotating IAM creds)
export INFLUXDB3_HOST_URL="https://<process-node-endpoint>:<port>"
V3_TOKEN_SECRET_ARN="$(
  aws timestream-influxdb get-db-cluster \
    --db-cluster-id <cluster-id> \
    --query influxAuthParametersSecretArn \
    --output text
)"
INFLUXDB3_AUTH_TOKEN="$(
  aws secretsmanager get-secret-value \
    --secret-id "$V3_TOKEN_SECRET_ARN" \
    --query SecretString --output text |
  python3 -c "import sys,json; print(json.loads(sys.stdin.read())['token'])"
)"
export INFLUXDB3_AUTH_TOKEN
export INFLUXDB3_DATABASE_NAME="<database>"

python3 liveanalytics_influxdb3_migration_client.py \
    --live-analytics-database-name <la-database> \
    --s3-bucket-name <bucket>

unset INFLUXDB3_AUTH_TOKEN V3_TOKEN_SECRET_ARN
```

**Important constraints:**

- Must run on a single InfluxDB 3 Enterprise **process node** (not the cluster endpoint)
- The cluster should not run ingestion or queries during migration (risk of OOM)
- Recommended for migrations under 1 billion records or 125GB per database
- Throughput: ~30M LiveAnalytics records/hour (varies by data characteristics)
- Run on EC2 to avoid presigned URL expiration issues
- Migration can be resumed if interrupted

**Cost note:** Data migration costs (S3 storage, data transfer) may apply. Discuss with account team for large migrations (5TB+).

### Path 2: Self-Managed InfluxDB → Managed

**From self-managed InfluxDB 2:**

1. Export using `influx backup` or line protocol export
2. Provision managed V2 instance → route to `getting-started`
3. Import using `influx restore` or line protocol write

**From self-managed InfluxDB 3 / InfluxDB Cloud:**

1. Export data via SQL queries to CSV/Parquet
2. Provision managed V3 cluster → route to `getting-started`
3. Bulk import via line protocol or Parquet import

### Path 3: Managed V2 → Managed V3

No in-place upgrade path. Requires data migration:

1. Export from V2 using the InfluxDB 2 API `/api/v2/query` with CSV output
2. Provision V3 cluster → route to `getting-started`
3. Re-design schema for V3 → route to `schema-design` (tags/fields may need restructuring)
4. Ingest via line protocol (compatible across versions)

**Note:** InfluxDB 3 uses SQL and InfluxQL — Flux is not supported. Queries must be rewritten.

## Pre-Migration Checklist

- [ ] Inventory source data volume and time range
- [ ] Map source schema to target schema (route to `schema-design`)
- [ ] Estimate target instance/cluster sizing
- [ ] Verify the current Marketplace and licensing prerequisites for the selected V3 engine variant in the service documentation and `CreateDbCluster` API model
- [ ] If the current documentation requires managed policies for first-time activation, attach them only to the activation principal, then remove them immediately and replace them with a scoped custom policy for production (see getting-started)
- [ ] Test with a subset of data before full migration
- [ ] Plan cutover window and rollback strategy
