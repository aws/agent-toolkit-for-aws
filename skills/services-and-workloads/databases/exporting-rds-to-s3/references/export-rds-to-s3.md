# Export RDS/Aurora to S3

## Overview

This SOP guides you through exporting Amazon RDS database snapshots or Aurora cluster snapshots to Amazon S3 for analytics, backup archival, long-term storage, or data migration purposes. AWS provides a native snapshot export feature that converts database snapshots to Apache Parquet format in S3, making the data accessible for analytics tools like Amazon Athena, Amazon Redshift Spectrum, and AWS Glue. The SOP handles the complete workflow including snapshot identification or creation, IAM role setup with proper permissions, KMS key configuration for encryption, S3 bucket preparation, export task initiation, progress monitoring, and verification of exported data.

## Parameters

Prompt the user in a single message to provide all required parameters at once. Clearly list the required parameters and their descriptions, and include any optional parameters with their default values. Do not proceed until you have received and confirmed all required parameters. If any required parameter is missing or unclear, you MUST explicitly request the missing information before moving forward.

- **database_identifier** (required): The RDS DB instance identifier or Aurora cluster identifier to export (e.g., "production-mysql", "analytics-aurora-cluster")
- **region** (required): The AWS region where the database exists (e.g., "us-east-1", "eu-west-1")
- **s3_bucket_name** (required): The S3 bucket name where exported data will be stored (e.g., "my-rds-exports")
- **s3_prefix** (optional, default: "rds-exports/"): S3 prefix/folder for exported data (e.g., "rds-exports/", "backups/mysql/")
- **export_type** (optional, default: "latest-snapshot"): Export source type ("latest-snapshot", "specific-snapshot", "create-new-snapshot")
- **snapshot_identifier** (optional): Specific snapshot ID to export (required if export_type is "specific-snapshot")
- **export_only_tables** (optional): Comma-separated list of specific tables to export (e.g., "schema1.table1,schema2.table2", exports all if not specified)
- **iam_role_arn** (optional): Existing IAM role ARN with S3 and export permissions (will create if not provided)
- **kms_key_id** (optional): KMS key ID for encrypting exported data in S3 (will use default S3 encryption if not provided)
- **export_task_identifier** (optional): Custom identifier for the export task (auto-generated if not provided)

Only proceed to the steps below if you have all required information.

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects, consume resources unnecessarily, or trigger actions before the user is ready
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Identify Database and Engine Type

Verify the database exists and determine whether it's RDS or Aurora.

**Constraints:**

- You MUST first attempt to describe the database as an RDS instance: `aws rds describe-db-instances --db-instance-identifier ${database_identifier} --region ${region}`
- You MUST check if the database is actually an Aurora cluster if the instance query fails: `aws rds describe-db-clusters --db-cluster-identifier ${database_identifier} --region ${region}`
- You MUST extract critical information from the response:
  - Database engine type (mysql, postgres, mariadb, aurora-mysql, aurora-postgresql)
  - Engine version
  - Database status (must be "available" for snapshot operations)
  - Storage encrypted status
  - KMS key ID if encrypted
  - DB instance class or cluster size
  - Availability zone(s)
- You MUST verify the database engine supports snapshot export:
  - Supported: MySQL, PostgreSQL, MariaDB, Aurora MySQL, Aurora PostgreSQL
  - NOT supported: Oracle, SQL Server
- You MUST inform the user if the database engine does not support snapshot export to S3
- You MUST determine if this is an Aurora cluster or standalone RDS instance:
  - Aurora cluster: Can export cluster snapshots
  - RDS instance: Can export DB snapshots
- You MUST check current database status and warn if not "available"
- You MUST save all database metadata for subsequent steps

### 3. Select or Create Snapshot for Export

Identify the snapshot to export based on user preferences.

**Constraints:**

- You MUST handle three export type scenarios:

  **Scenario A: latest-snapshot (default)**
  - You MUST list available snapshots for the database:
    - For RDS instance: `aws rds describe-db-snapshots --db-instance-identifier ${database_identifier} --region ${region}`
    - For Aurora cluster: `aws rds describe-db-cluster-snapshots --db-cluster-identifier ${database_identifier} --region ${region}`
  - You MUST filter for snapshots with status "available"
  - You MUST sort by snapshot creation time (most recent first)
  - You MUST select the most recent available snapshot
  - You MUST display snapshot details to user:
    - Snapshot identifier
    - Creation time
    - Snapshot type (automated, manual)
    - Snapshot size
    - Encrypted status
    - Engine version
  - You MUST ask user to confirm using this snapshot or select a different one

  **Scenario B: specific-snapshot**
  - You MUST verify the specified snapshot exists:
    - For RDS: `aws rds describe-db-snapshots --db-snapshot-identifier ${snapshot_identifier} --region ${region}`
    - For Aurora: `aws rds describe-db-cluster-snapshots --db-cluster-snapshot-identifier ${snapshot_identifier} --region ${region}`
  - You MUST verify snapshot status is "available"
  - You MUST verify snapshot belongs to the specified database
  - You MUST extract snapshot metadata (creation time, size, encrypted status)
  - You MUST inform user if snapshot is not found or not available

  **Scenario C: create-new-snapshot**
  - You MUST generate a snapshot identifier: `${database_identifier}-export-${timestamp}`
  - You MUST create a new manual snapshot:
    - For RDS: `aws rds create-db-snapshot --db-instance-identifier ${database_identifier} --db-snapshot-identifier ${snapshot_id} --tags Key=Purpose,Value=S3Export Key=CreatedBy,Value=export-rds-to-s3-script --region ${region}`
    - For Aurora: `aws rds create-db-cluster-snapshot --db-cluster-identifier ${database_identifier} --db-cluster-snapshot-identifier ${snapshot_id} --tags Key=Purpose,Value=S3Export Key=CreatedBy,Value=export-rds-to-s3-script --region ${region}`
  - You MUST poll snapshot status until it becomes "available":
    - Check status every 30 seconds
    - Display progress updates to user
    - Timeout after 2 hours for large databases
  - You MUST inform user of snapshot creation progress:

    ```
    Creating snapshot ${snapshot_id}...
    Status: creating (0:30)
    Status: creating (1:00)
    Status: creating (1:30)
    Status: available (2:15) ✓
    Snapshot created successfully!
    ```

  - You MUST handle snapshot creation failures by surfacing the AWS error code/message to the user and recommending actionable next steps

- You MUST verify snapshot is encrypted if the source database is encrypted
- You MUST save the selected snapshot identifier for the export operation
- You MUST display snapshot details including:
  - Snapshot ID
  - Database identifier
  - Engine and version
  - Creation timestamp
  - Snapshot size (allocated storage)
  - Encrypted status
  - Percent progress (if still creating)

### 4. Verify and Prepare S3 Bucket

Ensure the S3 bucket exists and is properly configured for RDS export.

**Constraints:**

- You MUST verify the S3 bucket exists: `aws s3api head-bucket --bucket ${s3_bucket_name}`
- You MUST check bucket region and warn if different from database region:
  - `aws s3api get-bucket-location --bucket ${s3_bucket_name}`
  - Cross-region exports are supported but may incur data transfer costs
  - Recommend using bucket in same region for cost efficiency
- You MUST verify bucket encryption configuration:
  - `aws s3api get-bucket-encryption --bucket ${s3_bucket_name}`
  - If encryption is not enabled, recommend enabling it for security
- You MUST check if the S3 prefix exists:
  - `aws s3 ls s3://${s3_bucket_name}/${s3_prefix}`
  - Create the prefix if it doesn't exist: `aws s3api put-object --bucket ${s3_bucket_name} --key ${s3_prefix}`
- You MUST verify sufficient bucket permissions:
  - Bucket must allow RDS service to write objects
  - Will be configured via bucket policy in IAM role setup step
- You MUST check bucket versioning status and recommend enabling for data protection
- You MUST estimate required S3 storage space:
  - Parquet format typically uses 30-50% less space than snapshot size
  - Inform user of approximate storage requirements
  - Warn if bucket has lifecycle policies that might delete exports
- You MUST handle bucket access errors:
  - Bucket does not exist: Offer to create it
  - Access denied: Check IAM permissions
  - Bucket in different account: Verify cross-account access is configured
- You MUST present bucket configuration summary to user:
  - Bucket name and region
  - Export path: s3://${s3_bucket_name}/${s3_prefix}
  - Encryption status
  - Versioning status
  - Estimated export size

### 5. Create or Verify IAM Role for Export

Set up IAM role with permissions for RDS to write exported data to S3.

**Constraints:**

- You MUST skip role creation if `iam_role_arn` was provided and verify it instead
- You MUST check if provided IAM role exists: `aws iam get-role --role-name ${role_name}`
- You MUST verify the role has correct trust policy for RDS export service with confused deputy protection:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "export.rds.amazonaws.com"
        },
        "Action": "sts:AssumeRole",
        "Condition": {
          "StringEquals": {
            "aws:SourceAccount": "${account_id}"
          },
          "ArnLike": {
            "aws:SourceArn": "arn:aws:rds:${region}:${account_id}:*"
          }
        }
      }
    ]
  }
  ```

- You MUST obtain the account ID for the trust policy condition: `aws sts get-caller-identity --query Account --output text`
- You MUST create IAM role if not provided:
  - Generate role name: `${database_identifier}-export-role` or `rds-s3-export-role`
  - Create trust policy document (as shown above) with `${account_id}` and `${region}` substituted
  - Create role: `aws iam create-role --role-name ${role_name} --assume-role-policy-document file://trust-policy.json --description "IAM role for RDS snapshot export to S3 for ${database_identifier}"`
- You MUST create IAM policy with necessary S3 permissions:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:PutObject*",
          "s3:GetObject*",
          "s3:DeleteObject*"
        ],
        "Resource": "arn:aws:s3:::${s3_bucket_name}/${s3_prefix}*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "s3:ListBucket"
        ],
        "Resource": "arn:aws:s3:::${s3_bucket_name}"
      }
    ]
  }
  ```

- You MUST add KMS permissions if KMS key is specified:

  ```json
  {
    "Effect": "Allow",
    "Action": [
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey"
    ],
    "Resource": "arn:aws:kms:${region}:${account_id}:key/${kms_key_id}"
  }
  ```

- You MUST create and attach the policy:
  - `aws iam create-policy --policy-name ${policy_name} --policy-document file://export-policy.json`
  - `aws iam attach-role-policy --role-name ${role_name} --policy-arn ${policy_arn}`
- You MUST add tags to the IAM role:
  - `aws iam tag-role --role-name ${role_name} --tags Key=Purpose,Value=RDSSnapshotExport Key=Database,Value=${database_identifier} Key=ManagedBy,Value=export-rds-to-s3-script`
- You MUST wait for IAM role propagation (10-15 seconds):
  - IAM is eventually consistent
  - Recommend waiting before starting export task
- You MUST verify role ARN format is correct:
  - Format: `arn:aws:iam::${account_id}:role/${role_name}`
  - Extract account ID from AWS identity: `aws sts get-caller-identity --query Account --output text`
- You MUST present IAM configuration summary:
  - Role ARN
  - S3 bucket access granted
  - KMS key access granted (if applicable)
  - Trust relationship confirmed
- You MUST handle IAM creation errors:
  - Role already exists: Use existing role
  - Permission denied: Check user's IAM permissions
  - Policy limit reached: Suggest cleanup of unused policies

### 6. Configure KMS Encryption (Optional)

Set up KMS encryption for exported data in S3 if required.

**Constraints:**

- You MUST skip this step if no KMS key was specified and default S3 encryption is acceptable
- You MUST verify the KMS key exists: `aws kms describe-key --key-id ${kms_key_id} --region ${region}`
- You MUST check KMS key status is "Enabled"
- You MUST verify the key is in the same region as the export operation
- You MUST ensure the KMS key policy allows RDS export service to use it:

  ```json
  {
    "Sid": "Allow RDS Export Service",
    "Effect": "Allow",
    "Principal": {
      "Service": "export.rds.amazonaws.com"
    },
    "Action": [
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey"
    ],
    "Resource": "*",
    "Condition": {
      "StringEquals": {
        "kms:ViaService": "rds.${region}.amazonaws.com"
      }
    }
  }
  ```

- You MUST check if snapshot is encrypted with different KMS key:
  - If snapshot has KMS key A and export specifies KMS key B
  - Both keys must be accessible
  - RDS will re-encrypt data during export
- You MUST add KMS key permissions to the IAM role (handled in previous step)
- You MUST verify IAM role can use the KMS key:
  - Role must have kms:Decrypt on snapshot's KMS key (if encrypted)
  - Role must have kms:GenerateDataKey on export's KMS key
- You MUST inform user of encryption details:
  - Source snapshot encryption: Yes/No and KMS key ID
  - Export encryption: KMS key ID or default S3 encryption
  - Re-encryption during export: Yes/No
- You MUST warn about performance impact if re-encryption is required:
  - Re-encryption can increase export time by 20-30%
  - Recommend using same KMS key for snapshot and export when possible
- You MUST handle KMS errors:
  - Key not found: Verify KMS key ID format
  - Access denied: Update KMS key policy
  - Key in wrong region: Use regional KMS key

### 7. Determine Tables to Export (Optional)

Identify specific tables for export if selective export is requested.

**Constraints:**

- You MUST skip this step if `export_only_tables` is not specified (exports entire database)
- You MUST parse the comma-separated table list provided by user
- You MUST validate table name format:
  - Format: `schema.table` or just `table` (for databases without explicit schemas)
  - Valid examples: "public.users", "inventory.products", "customers"
  - PostgreSQL: Include schema name (e.g., "public.users")
  - MySQL/MariaDB: Use database.table format (e.g., "appdb.users")
  - Aurora: Follow engine-specific format
- You MUST warn that table-level export is not validated until export starts:
  - RDS does not provide API to list tables in snapshot
  - Invalid table names will cause export to fail
  - Recommend exporting entire database if unsure about table names
- You MUST inform user of table-level export limitations:
  - Must specify exact table names as they appear in database
  - Case-sensitive for most database engines
  - Schema/database prefix required for PostgreSQL and MySQL
  - Cannot use wildcards or patterns
  - Foreign key relationships are not automatically included
  - Dependent tables must be explicitly listed
- You MUST format table names for export task parameter:
  - Convert comma-separated string to proper array format
  - Ensure proper escaping for special characters
- You MUST ask user to confirm table list before proceeding:
  - Display formatted list of tables to be exported
  - Warn about potential issues (missing dependent tables, etc.)
  - Offer option to export all tables instead
- You MUST estimate reduced export size with selective tables:
  - Cannot calculate exact size without table statistics
  - Inform user that export will be smaller than full snapshot
  - Recommend CloudWatch metrics to monitor export size

### 8. Generate Export Task Identifier

Create a unique identifier for the export task.

**Constraints:**

- You MUST use user-provided `export_task_identifier` if specified
- You MUST generate identifier if not provided:
  - Format: `${database_identifier}-export-${timestamp}`
  - Timestamp format: YYYYMMDD-HHMMSS (e.g., "20251014-153045")
  - Example: "production-mysql-export-20251014-153045"
  - Maximum length: 60 characters
  - Allowed characters: letters, numbers, hyphens
  - Must start with a letter
  - Must be unique across all export tasks in the account/region
- You MUST validate export task identifier format:
  - Check length does not exceed 60 characters
  - Verify only allowed characters are used
  - Ensure starts with letter
  - No special characters except hyphens
- You MUST check if export task identifier already exists:
  - `aws rds describe-export-tasks --export-task-identifier ${export_task_id} --region ${region}`
  - If exists, generate a new identifier with incremental suffix
  - Example: "production-mysql-export-20251014-153045-2"
- You MUST ensure identifier is descriptive and traceable:
  - Include database name for identification
  - Include timestamp for tracking
  - Consider adding environment indicator (prod, staging, dev)
- You MUST save the export task identifier for monitoring and verification

### 9. Initiate Snapshot Export Task

Start the export process to transfer snapshot data to S3.

**Constraints:**

- Before executing the export command, you MUST confirm with the user that Parquet output meets their needs and reiterate its key benefits (columnar storage, compression, analytics tool compatibility); offer alternative approaches if Parquet is not acceptable
- You MUST construct the export task command with all required parameters:

  ```bash
  aws rds start-export-task \
    --export-task-identifier ${export_task_id} \
    --source-arn ${snapshot_arn} \
    --s3-bucket-name ${s3_bucket_name} \
    --s3-prefix ${s3_prefix} \
    --iam-role-arn ${iam_role_arn} \
    --kms-key-id ${kms_key_id} \
    --export-only ${export_only_tables} \
    --region ${region}
  ```

- You MUST construct correct snapshot ARN:
  - For RDS snapshot: `arn:aws:rds:${region}:${account_id}:snapshot:${snapshot_id}`
  - For Aurora cluster snapshot: `arn:aws:rds:${region}:${account_id}:cluster-snapshot:${snapshot_id}`
  - Extract account ID: `aws sts get-caller-identity --query Account --output text`
- You MUST include optional parameters only if specified:
  - `--kms-key-id` only if KMS encryption is configured
  - `--export-only` only if selective table export is requested
- You MUST handle export task creation errors:
  - InvalidExportTaskState: Another export already in progress
  - InvalidS3BucketName: Verify bucket name format
  - InsufficientPrivileges: Check IAM role permissions
  - SnapshotNotFound: Verify snapshot ARN
  - InvalidParameterValue: Check all parameter formats
  - KMSKeyNotAccessible: Verify KMS key permissions
- You MUST capture export task details from response:
  - Export task identifier
  - Status (should be "starting")
  - Source ARN (snapshot)
  - S3 bucket and prefix
  - IAM role ARN
  - KMS key ID (if used)
  - Task start time
  - Percent progress (initially 0)
- You MUST display export task initiation confirmation:

  ```
  ✓ Export task started successfully!

  Export Task ID: production-mysql-export-20251014-153045
  Snapshot: production-mysql-snapshot-2025-10-14
  Destination: s3://my-rds-exports/rds-exports/
  Status: starting
  Started: 2025-10-14 15:30:45 UTC
  ```

- You MUST inform user of expected export duration:
  - Depends on snapshot size
  - Approximate rate: 10-20 GB per hour (varies by instance size)
  - Estimate time based on snapshot size
  - Example: 100 GB snapshot = approximately 5-10 hours
- You MUST save export task identifier for progress monitoring

### 10. Monitor Export Task Progress

Track the export operation until completion.

**Constraints:**

- You MUST poll export task status regularly:
  - `aws rds describe-export-tasks --export-task-identifier ${export_task_id} --region ${region}`
  - Poll every 60 seconds initially
  - Increase interval to 5 minutes after first hour
  - Continue until status is "complete" or "failed"
- You MUST extract and display key information from each status check:
  - Status (starting, in_progress, complete, failed, canceled)
  - Percent progress (0-100)
  - Total amount of data (in bytes)
  - Elapsed time
  - Estimated time remaining (if available)
  - Warning count (if any)
  - Failure message (if failed)
- You MUST display progress updates to user:

  ```
  Exporting snapshot to S3...
  Status: in_progress (5%, 2.5 GB exported, 0:15 elapsed)
  Status: in_progress (15%, 7.5 GB exported, 0:45 elapsed)
  Status: in_progress (30%, 15 GB exported, 1:30 elapsed)
  Status: in_progress (50%, 25 GB exported, 2:30 elapsed)
  Status: in_progress (75%, 37.5 GB exported, 3:45 elapsed)
  Status: in_progress (90%, 45 GB exported, 4:30 elapsed)
  Status: complete (100%, 50 GB exported, 5:00 elapsed) ✓
  ```

- You MUST handle different status outcomes:
  - **starting**: Task is initializing (typically 1-2 minutes)
  - **in_progress**: Export is actively running (display progress percentage)
  - **complete**: Export finished successfully (proceed to verification)
  - **failed**: Export encountered an error (display error message and troubleshooting)
  - **canceled**: Export was manually canceled (inform user)
- You MUST check for warnings during export:
  - Extract warning messages from response
  - Display warnings to user even if export completes
  - Common warnings: Table not found, schema mismatch, permission issues
- You MUST implement timeout handling:
  - Very large databases (>1 TB) can take 24+ hours
  - Recommend not blocking indefinitely
  - If the estimated completion time exceeds 2 hours, you MUST ask the user if they prefer continued real-time updates or to switch to scheduled/asynchronous check-ins and follow their preference
  - Offer option to stop monitoring and provide command to check status later
  - Example: "aws rds describe-export-tasks --export-task-identifier ${export_task_id}"
- You MUST handle export failures gracefully:
  - Extract failure cause from status
  - Provide specific error message
  - Suggest troubleshooting steps based on error type
  - Offer to retry export with corrections
- You MUST inform user they can safely close terminal:
  - Export task runs asynchronously in AWS
  - Closing session does not cancel export
  - Provide command to check status later
  - Save export task identifier for reference
- You MUST calculate export metrics upon completion:
  - Total data exported (in GB)
  - Total time elapsed (in hours and minutes)
  - Average export speed (GB/hour)
  - Number of files created in S3
  - Final S3 path with exported data

### 11. Verify Exported Data in S3

Confirm the export completed successfully and data is accessible in S3.

**Constraints:**

- You MUST list exported files in S3 bucket:
  - `aws s3 ls s3://${s3_bucket_name}/${s3_prefix}${export_task_id}/ --recursive`
  - Export creates folder named after export task identifier
  - Each table is exported to separate subfolder
  - Data files are in Parquet format
- You MUST verify export structure:
  - Check for expected folders and files
  - Typical structure:

    ```
    s3://bucket/prefix/export-task-id/
    ├── schema1/
    │   ├── table1/
    │   │   ├── data1.parquet
    │   │   ├── data2.parquet
    │   │   └── ...
    │   └── table2/
    │       └── data1.parquet
    └── schema2/
        └── table3/
            └── data1.parquet
    ```

  - Each table has one or more Parquet files
  - Large tables are split across multiple Parquet files
- You MUST count total number of files exported:
  - Use S3 list objects to count files
  - Provide summary of files per table
  - Calculate total size of exported data
- You MUST calculate actual export size:
  - Sum file sizes from S3 listing
  - Compare to original snapshot size
  - Show compression ratio (Parquet vs snapshot)
  - Example: "50 GB snapshot → 18 GB Parquet (64% reduction)"
- You MUST verify at least one Parquet file exists for expected tables:
  - If selective export, check specified tables are present
  - If full export, verify major tables exist
  - List all table names found in export
- You MUST check file accessibility:
  - Attempt to read metadata of a sample Parquet file
  - Verify user has permissions to access exported files
  - Test with: `aws s3api head-object --bucket ${s3_bucket_name} --key ${sample_file_key}`
- You MUST verify encryption status of exported files:
  - Check object metadata for encryption information
  - Confirm KMS key ID if specified
  - Verify SSE-S3 or SSE-KMS is applied
- You MUST provide S3 path summary:
  - Full S3 URI: `s3://${s3_bucket_name}/${s3_prefix}${export_task_id}/`
  - AWS Console URL to browse files
  - Total number of Parquet files
  - Total size in S3
  - Compression savings
- You MUST handle verification failures:
  - No files found: Export may have failed, check task status
  - Missing tables: Verify table names were correct
  - Access denied: Check S3 bucket permissions
  - Incomplete data: Check for export warnings or errors

### 12. Provide Data Access Instructions

Guide user on how to query and use the exported data.

**Constraints:**

- You MUST provide multiple options for accessing exported data:

  **Option 1: Amazon Athena**
  - Create external table in Athena to query Parquet data
  - Provide sample CREATE EXTERNAL TABLE DDL:

    ```sql
    CREATE EXTERNAL TABLE IF NOT EXISTS database_name.table_name (
      column1 data_type,
      column2 data_type,
      column3 data_type
    )
    STORED AS PARQUET
    LOCATION 's3://${s3_bucket_name}/${s3_prefix}${export_task_id}/schema/table/';
    ```

  - Provide sample SELECT query:

    ```sql
    SELECT * FROM database_name.table_name LIMIT 10;
    ```

  - Explain need to create Athena database first
  - Mention Athena query costs ($5 per TB scanned)

  **Option 2: AWS Glue**
  - Create Glue crawler to automatically discover schema
  - Provide crawler creation command:

    ```bash
    aws glue create-crawler \
      --name ${database_identifier}-export-crawler \
      --role ${glue_service_role} \
      --database ${glue_database} \
      --targets "S3Targets=[{Path=s3://${s3_bucket_name}/${s3_prefix}${export_task_id}/}]" \
      --region ${region}
    ```

  - Explain how to run crawler and view Data Catalog
  - Mention Glue crawling costs

  **Option 3: Amazon Redshift Spectrum**
  - Create external schema in Redshift pointing to S3 data
  - Provide sample DDL:

    ```sql
    CREATE EXTERNAL SCHEMA spectrum_schema
    FROM DATA CATALOG
    DATABASE 'glue_database'
    IAM_ROLE 'arn:aws:iam::account-id:role/redshift-spectrum-role'
    REGION '${region}';

    SELECT * FROM spectrum_schema.table_name LIMIT 10;
    ```

  - Explain querying from Redshift cluster

  **Option 4: Direct Parquet File Access**
  - Download Parquet files locally:

    ```bash
    aws s3 cp s3://${s3_bucket_name}/${s3_prefix}${export_task_id}/ ./local-folder/ --recursive
    ```

  - Use Python with pandas/pyarrow to read:

    ```python
    import pandas as pd
    import pyarrow.parquet as pq

    # Read Parquet file
    table = pq.read_table('data.parquet')
    df = table.to_pandas()
    print(df.head())
    ```

  - Use Apache Spark:

    ```scala
    val df = spark.read.parquet("s3a://${s3_bucket_name}/${s3_prefix}${export_task_id}/schema/table/")
    df.show()
    ```

- You MUST explain Parquet format benefits when confirming the export approach and again here if the user needs a refresher:
  - Columnar storage for efficient analytics queries
  - Built-in compression (snappy by default)
  - Self-describing schema
  - Compatible with most analytics tools
  - Optimized for AWS analytics services
- You MUST provide schema discovery guidance:
  - Parquet files contain embedded schema
  - Use AWS Glue crawler for automatic schema discovery
  - Or infer schema using pyarrow: `pq.read_schema('file.parquet')`
  - Explain data types may differ from original database types
- You MUST warn about data consistency:
  - Export is point-in-time snapshot
  - Data represents database state at snapshot time
  - No ongoing replication or synchronization
  - Changes after snapshot are not reflected
- You MUST provide cost estimates for common access patterns:
  - Athena: $5 per TB of data scanned
  - S3 storage: ~$0.023 per GB per month (Standard)
  - S3 GET requests: $0.0004 per 1,000 requests
  - Data transfer: Free within same region, varies cross-region

### 13. Generate Export Summary Report

Create comprehensive documentation of the export operation.

**Constraints:**

- You MUST create a detailed export report containing:
  - **Export Overview**:
    - Export task identifier
    - Database identifier and engine
    - Snapshot identifier used
    - Export status (completed, failed, warnings)
    - Start and end timestamps
    - Total duration
  - **Source Configuration**:
    - RDS instance or Aurora cluster details
    - Database engine and version
    - Snapshot size (allocated storage)
    - Snapshot creation timestamp
    - Encrypted status and KMS key
  - **Destination Configuration**:
    - S3 bucket name and region
    - S3 prefix/path
    - Full S3 URI to exported data
    - Exported data size
    - Compression ratio
    - Number of Parquet files
    - Encryption configuration
  - **IAM and Security**:
    - IAM role ARN used
    - IAM policies attached
    - KMS key ID (if used)
    - S3 bucket encryption status
  - **Export Metrics**:
    - Total data exported (GB)
    - Export duration (hours:minutes)
    - Average export speed (GB/hour)
    - Number of tables exported
    - Selective tables (if applicable)
    - Warning count
  - **Access Instructions**:
    - How to query with Athena
    - How to catalog with Glue
    - How to access with Redshift Spectrum
    - How to download and process locally
  - **Cost Summary**:
    - S3 storage cost estimate
    - Export operation cost (if any)
    - Ongoing storage costs
    - Query cost estimates (Athena, Redshift Spectrum)
  - **Cleanup Instructions**:
    - How to delete exported data from S3
    - How to delete the snapshot (if created for export)
    - How to remove IAM role (if no longer needed)
  - **Next Steps and Recommendations**:
    - Set up S3 lifecycle policies for automatic archival
    - Configure S3 Intelligent-Tiering for cost optimization
    - Set up CloudWatch alarms for export failures
    - Document export schedule for recurring exports
    - Consider automating exports with Lambda or Step Functions

- You MUST format the report in clear, readable markdown format
- You MUST include specific commands for all recommendations
- You MUST provide AWS Console URLs for easy access:
  - S3 bucket URL
  - Export task details URL
  - IAM role URL
  - CloudWatch logs URL (if available)
- You MUST save report to file: `rds-export-report-${export_task_id}.md`
- You MUST present the complete report to the user
- You MUST offer to save the report to a local file for reference

### 14. Provide Cleanup and Cost Optimization Guidance

Advise on managing exported data and optimizing costs.

**Constraints:**

- You MUST provide instructions for deleting exported data when no longer needed:

  ```bash
  # Delete exported data from S3
  aws s3 rm s3://${s3_bucket_name}/${s3_prefix}${export_task_id}/ --recursive

  # Delete the snapshot if it was created for export only
  aws rds delete-db-snapshot --db-snapshot-identifier ${snapshot_id} --region ${region}
  # Or for Aurora cluster snapshot:
  aws rds delete-db-cluster-snapshot --db-cluster-snapshot-identifier ${snapshot_id} --region ${region}
  ```

- You MUST recommend S3 lifecycle policies for cost optimization:
  - Transition to S3 Intelligent-Tiering after 30 days
  - Or transition to S3 Glacier after 90 days for archival
  - Delete after retention period expires
  - Example lifecycle policy:

    ```json
    {
      "Rules": [
        {
          "Id": "Archive RDS Exports",
          "Status": "Enabled",
          "Filter": {
            "Prefix": "${s3_prefix}"
          },
          "Transitions": [
            {
              "Days": 30,
              "StorageClass": "INTELLIGENT_TIERING"
            },
            {
              "Days": 90,
              "StorageClass": "GLACIER"
            }
          ],
          "Expiration": {
            "Days": 365
          }
        }
      ]
    }
    ```

  - Apply policy: `aws s3api put-bucket-lifecycle-configuration --bucket ${s3_bucket_name} --lifecycle-configuration file://lifecycle.json`

- You MUST recommend monitoring and alerting:
  - CloudWatch alarm for failed exports
  - S3 storage metrics to track growth
  - Cost alerts for unexpected charges
  - Example alarm creation:

    ```bash
    aws cloudwatch put-metric-alarm \
      --alarm-name rds-export-failures \
      --alarm-description "Alert on RDS export task failures" \
      --metric-name ExportTaskFailures \
      --namespace AWS/RDS \
      --statistic Sum \
      --period 300 \
      --threshold 1 \
      --comparison-operator GreaterThanThreshold
    ```

- You MUST suggest automation for recurring exports:
  - AWS Lambda function triggered by EventBridge (CloudWatch Events) schedule
  - Step Functions workflow for complex export logic
  - Example Lambda trigger setup:

    ```bash
    # Create EventBridge rule to run daily
    aws events put-rule \
      --name daily-rds-export \
      --schedule-expression "cron(0 2 * * ? *)" \
      --state ENABLED

    # Add Lambda function as target
    aws events put-targets \
      --rule daily-rds-export \
      --targets "Id=1,Arn=${lambda_function_arn}"
    ```

- You MUST provide cost optimization tips:
  - Use S3 Intelligent-Tiering for automatic cost optimization
  - Export during off-peak hours to minimize database impact
  - Use selective table export to reduce data volume
  - Compress older exports with S3 lifecycle policies
  - Delete unnecessary snapshots after export
  - Use S3 Storage Lens to analyze storage patterns
  - Consider S3 Batch Operations for bulk actions

- You MUST recommend data retention policies:
  - Determine retention requirements based on compliance
  - Document retention policy in S3 object tags
  - Use S3 Object Lock for compliance requirements
  - Implement MFA Delete for critical exports

## Examples

### Example Input

```
database_identifier: production-mysql
region: us-east-1
s3_bucket_name: analytics-data-lake
s3_prefix: rds-exports/mysql/
export_type: latest-snapshot
```

### Example Output

```
# RDS Snapshot Export to S3 - Summary Report

**Export Task ID:** production-mysql-export-20251014-153045
**Status:** ✓ Completed Successfully
**Generated:** 2025-10-14 20:45:30 UTC

---

## Export Overview

Successfully exported RDS MySQL snapshot to S3 for analytics and backup purposes.

- **Database:** production-mysql (MySQL 8.0.35)
- **Snapshot:** production-mysql-automated-2025-10-14-12-30
- **Export Status:** Complete
- **Duration:** 5 hours 15 minutes
- **Data Exported:** 245 GB → 92 GB Parquet (62% compression)

---

## Source Configuration

### Database Details
- **DB Instance:** production-mysql
- **Engine:** MySQL 8.0.35
- **Instance Class:** db.r5.2xlarge
- **Region:** us-east-1
- **Multi-AZ:** Yes
- **Storage:** 500 GB (gp3)
- **Encrypted:** Yes (KMS key: arn:aws:kms:us-east-1:123456789012:key/abcd1234-...)

### Snapshot Details
- **Snapshot ID:** production-mysql-automated-2025-10-14-12-30
- **Type:** Automated backup
- **Created:** 2025-10-14 12:30:00 UTC
- **Size:** 245 GB
- **Status:** Available
- **Encrypted:** Yes (same KMS key as instance)

---

## Destination Configuration

### S3 Export Location
- **Bucket:** analytics-data-lake
- **Region:** us-east-1 (same as database)
- **Prefix:** rds-exports/mysql/
- **Full Path:** s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/
- **Console URL:** https://s3.console.aws.amazon.com/s3/buckets/analytics-data-lake?prefix=rds-exports/mysql/production-mysql-export-20251014-153045/

### Exported Data
- **Format:** Apache Parquet
- **Compression:** Snappy (default)
- **Total Size:** 92 GB
- **Files:** 1,247 Parquet files
- **Tables:** 87 tables exported
- **Encryption:** SSE-KMS (KMS key: arn:aws:kms:us-east-1:123456789012:key/abcd1234-...)

### Data Structure
```

s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/
├── appdb/
│   ├── users/
│   │   ├── 1.parquet
│   │   ├── 2.parquet
│   │   └── ... (15 files, 8.2 GB)
│   ├── orders/
│   │   ├── 1.parquet
│   │   └── ... (42 files, 18.5 GB)
│   ├── products/
│   │   └── 1.parquet (2.1 GB)
│   └── ... (87 tables total)
└── ...

```

---

## IAM and Security Configuration

### IAM Role
- **Role ARN:** arn:aws:iam::123456789012:role/production-mysql-export-role
- **Trust Policy:** Allows export.rds.amazonaws.com
- **Created:** 2025-10-14 15:25:00 UTC

### IAM Permissions
- **S3 Access:** PutObject, GetObject, DeleteObject on s3://analytics-data-lake/rds-exports/mysql/*
- **S3 List:** ListBucket on analytics-data-lake
- **KMS Access:** Decrypt (snapshot key), GenerateDataKey (export key)

### Encryption
- **Snapshot Encryption:** Yes (KMS key: abcd1234-5678-90ab-cdef-1234567890ab)
- **Export Encryption:** Yes (same KMS key)
- **Re-encryption:** No (same key used)
- **S3 Bucket Encryption:** SSE-KMS enabled

---

## Export Metrics

### Performance
- **Total Data Exported:** 92 GB (Parquet format)
- **Original Snapshot Size:** 245 GB
- **Compression Ratio:** 62% reduction
- **Export Duration:** 5 hours 15 minutes (315 minutes)
- **Average Speed:** 17.5 GB/hour
- **Start Time:** 2025-10-14 15:30:00 UTC
- **End Time:** 2025-10-14 20:45:00 UTC

### Data Details
- **Tables Exported:** 87 (all tables)
- **Parquet Files Created:** 1,247 files
- **Largest Table:** orders (18.5 GB, 42 Parquet files)
- **Smallest Table:** config (12 MB, 1 Parquet file)
- **Warnings:** None

---

## Accessing Exported Data

### Option 1: Query with Amazon Athena

1. **Create Athena Database:**
   ```sql
   CREATE DATABASE IF NOT EXISTS production_mysql_export;
   ```

1. **Create External Table (Example for 'users' table):**

   ```sql
   CREATE EXTERNAL TABLE IF NOT EXISTS production_mysql_export.users (
     id INT,
     username STRING,
     email STRING,
     created_at TIMESTAMP,
     updated_at TIMESTAMP
   )
   STORED AS PARQUET
   LOCATION 's3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/appdb/users/';
   ```

2. **Query Data:**

   ```sql
   SELECT COUNT(*) as total_users FROM production_mysql_export.users;
   SELECT * FROM production_mysql_export.users WHERE created_at > '2025-01-01' LIMIT 100;
   ```

**Cost:** ~$5 per TB scanned (92 GB = $0.46 per full scan)

### Option 2: Catalog with AWS Glue

1. **Create Glue Database:**

   ```bash
   aws glue create-database \
     --database-input "Name=production_mysql_export,Description=Exported from RDS" \
     --region us-east-1
   ```

2. **Create Glue Crawler:**

   ```bash
   aws glue create-crawler \
     --name production-mysql-export-crawler \
     --role arn:aws:iam::123456789012:role/AWSGlueServiceRole \
     --database-targets DatabaseTargets=[{DatabaseName=production_mysql_export,Path=s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/}] \
     --region us-east-1
   ```

3. **Run Crawler:**

   ```bash
   aws glue start-crawler --name production-mysql-export-crawler --region us-east-1
   ```

4. **Query via Athena:**
   - Crawler automatically discovers schemas
   - Query tables through Athena using discovered schemas
   - View Data Catalog in AWS Glue Console

### Option 3: Query with Amazon Redshift Spectrum

1. **Create External Schema in Redshift:**

   ```sql
   CREATE EXTERNAL SCHEMA mysql_export
   FROM DATA CATALOG
   DATABASE 'production_mysql_export'
   IAM_ROLE 'arn:aws:iam::123456789012:role/RedshiftSpectrumRole'
   REGION 'us-east-1';
   ```

2. **Query from Redshift:**

   ```sql
   SELECT * FROM mysql_export.users LIMIT 100;

   -- Join with Redshift tables
   SELECT u.username, o.order_total
   FROM mysql_export.users u
   JOIN local_schema.orders o ON u.id = o.user_id;
   ```

### Option 4: Download and Process Locally

**Download with AWS CLI:**

```bash
# Download all data
aws s3 cp s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/ ./rds-export/ --recursive

# Download specific table
aws s3 cp s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/appdb/users/ ./users-data/ --recursive
```

**Process with Python:**

```python
import pandas as pd
import pyarrow.parquet as pq
import boto3

# Option A: Read from local file
df = pd.read_parquet('users-data/1.parquet')
print(df.head())

# Option B: Read directly from S3
s3 = boto3.client('s3')
obj = s3.get_object(Bucket='analytics-data-lake',
                    Key='rds-exports/mysql/production-mysql-export-20251014-153045/appdb/users/1.parquet')
table = pq.read_table(obj['Body'])
df = table.to_pandas()

# Option C: Read all Parquet files in a directory
df = pd.read_parquet('s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/appdb/users/')
```

**Process with Apache Spark:**

```scala
val df = spark.read.parquet("s3a://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/appdb/users/")
df.show()
df.printSchema()
df.count()
```

---

## Cost Summary

### One-Time Export Costs

- **RDS Export Operation:** Free (no charge for export task)
- **Snapshot Storage (if new):** $0.095/GB-month for snapshot retention
- **Data Transfer:** Free (same region)

### Monthly Storage Costs (S3 Standard)

- **92 GB × $0.023/GB-month = $2.12/month**

### Ongoing Query Costs

- **Athena:** $5 per TB scanned ($0.46 per full 92 GB scan)
- **S3 GET Requests:** $0.0004 per 1,000 requests (~$0.50 for typical usage)
- **Redshift Spectrum:** Included with Redshift cluster costs

### Cost Optimization Recommendations

1. **Transition to S3 Intelligent-Tiering after 30 days:** Save 40-68% on storage
2. **Transition to S3 Glacier after 90 days:** Save 85% on storage ($0.004/GB-month)
3. **Use selective queries in Athena:** Partition data by date to scan less data
4. **Delete exports after retention period:** Set lifecycle policy for auto-deletion

**Estimated Monthly Cost with Optimization:** $0.37/month (Glacier after 90 days)

---

## Cleanup Instructions

### Delete Exported Data (When No Longer Needed)

```bash
# Delete all exported data from S3
aws s3 rm s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/ --recursive

# Verify deletion
aws s3 ls s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/
```

### Delete Snapshot (If Created for Export Only)

```bash
# For automated snapshots (not recommended - managed by RDS)
# For manual snapshots created for export:
aws rds delete-db-snapshot \
  --db-snapshot-identifier production-mysql-manual-export-snapshot \
  --region us-east-1
```

### Remove IAM Role (If No Longer Needed)

```bash
# Detach policies first
aws iam detach-role-policy \
  --role-name production-mysql-export-role \
  --policy-arn arn:aws:iam::123456789012:policy/ProductionMySQLExportPolicy

# Delete policy
aws iam delete-policy \
  --policy-arn arn:aws:iam::123456789012:policy/ProductionMySQLExportPolicy

# Delete role
aws iam delete-role --role-name production-mysql-export-role
```

---

## Recommendations and Next Steps

### Immediate Actions

1. ✓ Verify exported data is accessible via Athena or Glue
2. ✓ Test queries on sample tables to confirm data integrity
3. ✓ Set up Athena workgroup with query result location
4. ✓ Document table schemas and relationships for team reference

### Short-Term Actions

1. **Configure S3 Lifecycle Policy** (Save 40-85% on storage costs)

   ```bash
   # Apply lifecycle policy to automatically transition to cheaper storage
   aws s3api put-bucket-lifecycle-configuration \
     --bucket analytics-data-lake \
     --lifecycle-configuration file://lifecycle-policy.json
   ```

2. **Set Up CloudWatch Alarms** (Monitor export failures)

   ```bash
   aws cloudwatch put-metric-alarm \
     --alarm-name rds-export-failures \
     --alarm-description "Alert on RDS export task failures" \
     --metric-name ExportTaskFailures \
     --namespace AWS/RDS \
     --statistic Sum \
     --period 300 \
     --threshold 1 \
     --comparison-operator GreaterThanThreshold \
     --alarm-actions arn:aws:sns:us-east-1:123456789012:alerts
   ```

3. **Enable S3 Versioning** (Protect against accidental deletion)

   ```bash
   aws s3api put-bucket-versioning \
     --bucket analytics-data-lake \
     --versioning-configuration Status=Enabled
   ```

4. **Tag S3 Objects** (Organize and track exports)

   ```bash
   aws s3api put-object-tagging \
     --bucket analytics-data-lake \
     --key rds-exports/mysql/production-mysql-export-20251014-153045/ \
     --tagging 'TagSet=[{Key=Database,Value=production-mysql},{Key=ExportDate,Value=2025-10-14},{Key=RetentionDays,Value=90}]'
   ```

### Long-Term Actions

1. **Automate Recurring Exports** (Daily/Weekly snapshots)
   - Create Lambda function to trigger exports on schedule
   - Use EventBridge (CloudWatch Events) for scheduling
   - Implement error handling and notifications
   - Example: Export every Sunday at 2 AM UTC

2. **Implement Data Retention Policy**
   - Define retention requirements (e.g., 90 days, 1 year, 7 years)
   - Configure S3 Object Lock for compliance if required
   - Set up MFA Delete for critical exports
   - Document retention policy in corporate wiki

3. **Set Up Data Catalog and Governance**
   - Use AWS Glue Data Catalog for centralized metadata
   - Implement Lake Formation for access control
   - Enable AWS Config for compliance auditing
   - Create data dictionary for business users

4. **Optimize for Analytics Workloads**
   - Partition exported data by date for better query performance
   - Use AWS Glue ETL to transform and optimize data
   - Create materialized views in Athena for common queries
   - Consider Amazon Redshift for complex analytics queries

5. **Monitor and Optimize Costs**
   - Review S3 Storage Lens for usage patterns
   - Set up Cost Anomaly Detection for unexpected charges
   - Use AWS Cost Explorer to track export-related costs
   - Implement chargeback/showback for department budgets

---

## Troubleshooting Reference

### Export Task Failed

- Check IAM role permissions (S3 and KMS access)
- Verify S3 bucket exists and is accessible
- Check KMS key policy allows RDS export service
- Review CloudWatch Logs for detailed error messages

### Missing Tables in Export

- Verify table names were correct (case-sensitive)
- Check that tables existed in snapshot
- Ensure schema prefix was included (PostgreSQL)
- Review export task warnings for table issues

### Cannot Query with Athena

- Verify S3 path is correct in CREATE TABLE statement
- Check Athena query result location is configured
- Ensure IAM user has Athena and S3 permissions
- Verify Parquet files are not corrupted

### High Query Costs in Athena

- Use partition pruning (add partition columns)
- Select specific columns instead of SELECT *
- Use columnar formats (Parquet compression helps)
- Consider caching frequent queries in Redshift

---

## Additional Resources

### AWS Documentation

- [Exporting DB snapshot data to Amazon S3](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ExportSnapshot.html)
- [Querying data with Amazon Athena](https://docs.aws.amazon.com/athena/latest/ug/querying-data.html)
- [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/catalog-and-crawler.html)
- [S3 Lifecycle Policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)

### Related AWS Services

- Amazon Athena: https://aws.amazon.com/athena/
- AWS Glue: https://aws.amazon.com/glue/
- Amazon Redshift Spectrum: https://aws.amazon.com/redshift/spectrum/
- S3 Intelligent-Tiering: https://aws.amazon.com/s3/storage-classes/intelligent-tiering/

### Support

- AWS Support: https://console.aws.amazon.com/support/
- RDS Forums: https://forums.aws.amazon.com/forum.jspa?forumID=60
- Stack Overflow: Tag `amazon-rds` or `amazon-athena`

---

## Summary

Successfully exported 245 GB MySQL database snapshot to S3 in Parquet format (92 GB compressed). Data is now available for analytics via Amazon Athena, AWS Glue, Amazon Redshift Spectrum, or direct file access. Export completed in 5 hours 15 minutes with no errors or warnings, and status updates were delivered on the agreed asynchronous schedule.

**Next Steps:**

1. Verify data accessibility via Athena
2. Set up S3 lifecycle policy for cost optimization
3. Configure CloudWatch alarms for future exports
4. Document export process for team

**Export Details:**

- S3 Path: s3://analytics-data-lake/rds-exports/mysql/production-mysql-export-20251014-153045/
- Export Task ID: production-mysql-export-20251014-153045
- Monthly Storage Cost: $2.12 (can be reduced to $0.37 with Glacier)

---

*Report generated by export-rds-to-s3-script on 2025-10-14 20:45:30 UTC*

```

## Troubleshooting

### Database Not Found

**Symptoms:** DB instance or cluster identifier not found

**Solutions:**
- Verify database identifier spelling and case (case-sensitive)
- Check you're in the correct AWS region
- Use `aws rds describe-db-instances --region ${region}` to list all instances
- For Aurora, use `aws rds describe-db-clusters --region ${region}`
- Verify you have permissions to describe RDS resources

### Export Not Supported for Database Engine

**Symptoms:** Error indicating database engine doesn't support export

**Solutions:**
- Snapshot export is supported for: MySQL, PostgreSQL, MariaDB, Aurora MySQL, Aurora PostgreSQL
- NOT supported for: Oracle, SQL Server
- For unsupported engines, consider alternative backup methods:
  - Native database backup tools (mysqldump, pg_dump)
  - AWS Database Migration Service (DMS) for data replication
  - Third-party backup solutions
- Check engine version meets minimum requirements

### Snapshot Not Available

**Symptoms:** Snapshot status is not "available" or snapshot doesn't exist

**Solutions:**
- Wait for automated snapshots to complete (taken during backup window)
- Check snapshot creation is not disabled on DB instance
- Verify snapshot retention period is not set to 0
- For Aurora, cluster snapshots may be in different namespace than instance snapshots
- List all snapshots: `aws rds describe-db-snapshots --db-instance-identifier ${db_id}`
- Create manual snapshot and wait for "available" status

### IAM Role Permission Errors

**Symptoms:** Export fails with access denied or insufficient permissions

**Solutions:**
- Verify IAM role has trust policy allowing export.rds.amazonaws.com
- Check S3 bucket policy allows RDS export service principal
- Ensure IAM role has PutObject permissions on S3 bucket and prefix
- Verify KMS key policy allows export service to use key
- Wait 10-15 seconds after creating IAM role (eventual consistency)
- Test IAM role with `aws sts assume-role` to verify trust policy
- Check for typos in ARNs (role ARN, bucket ARN, KMS key ARN)

### S3 Bucket Access Denied

**Symptoms:** Export fails with S3 access denied errors

**Solutions:**
- Verify S3 bucket exists and is accessible
- Check bucket is not in different AWS account (cross-account requires additional configuration)
- Ensure bucket policy allows RDS export service:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "export.rds.amazonaws.com"
        },
        "Action": "s3:PutObject",
        "Resource": "arn:aws:s3:::bucket-name/prefix/*"
      }
    ]
  }
  ```

- Verify S3 bucket is not encrypted with SSE-C (use SSE-S3 or SSE-KMS instead)
- Check S3 bucket doesn't have Block Public Access settings preventing writes
- Test bucket write access: `aws s3 cp testfile.txt s3://bucket-name/prefix/`

### KMS Key Access Errors

**Symptoms:** Export fails with KMS key not accessible or decrypt errors

**Solutions:**

- Verify KMS key exists and is in "Enabled" state
- Check KMS key is in same region as export operation
- Ensure KMS key policy grants permissions to export service:
  - kms:Decrypt on snapshot's KMS key
  - kms:GenerateDataKey on export's KMS key
- For cross-account KMS keys, ensure trust relationships are configured
- Verify IAM role has KMS permissions in attached policy
- Use `aws kms describe-key --key-id ${key_id}` to check key status
- Consider using default S3 encryption if KMS permissions are complex

### Export Task Stuck in "starting" Status

**Symptoms:** Export task remains in "starting" status for extended time

**Solutions:**

- Wait at least 5-10 minutes (initialization can take time)
- Check IAM role was created successfully and permissions propagated
- Verify S3 bucket is accessible from RDS service
- Cancel stuck export and retry: `aws rds cancel-export-task --export-task-identifier ${task_id}`
- Check CloudWatch Logs for detailed error messages (if available)
- Verify no account limits preventing export task execution
- Try exporting to different S3 bucket to isolate issue

### Export Task Failed During Progress

**Symptoms:** Export fails after starting successfully

**Solutions:**

- Check export task details for failure reason: `aws rds describe-export-tasks --export-task-identifier ${task_id}`
- Common failure reasons:
  - S3 bucket was deleted during export
  - IAM role was modified during export
  - KMS key was disabled during export
  - Insufficient S3 storage quota
  - Invalid table names in selective export
- Review CloudWatch Logs for detailed errors
- Retry export after fixing identified issue
- Consider creating new snapshot and exporting from that

### Missing Tables in Export

**Symptoms:** Expected tables are not present in S3 export

**Solutions:**

- Verify table names were spelled correctly (case-sensitive)
- Check table names include schema/database prefix where required:
  - PostgreSQL: "schema.table"
  - MySQL: "database.table"
- Ensure tables existed in snapshot at snapshot time
- Review export task warnings for table-specific issues
- Try exporting entire database instead of selective tables
- Verify table was not empty (empty tables may not create files)

### Parquet Files Corrupted or Unreadable

**Symptoms:** Cannot open or query Parquet files

**Solutions:**

- Verify files were fully written (check file size > 0)
- Check S3 storage class allows immediate access (not Glacier Deep Archive)
- Ensure client tools support Parquet format (use pyarrow or pandas)
- Try different Parquet file from same table
- Verify no S3 lifecycle policies moved/archived files during export
- Re-export if corruption is confirmed
- Use AWS Glue crawler to validate Parquet schema

### High Export Costs

**Symptoms:** Unexpected charges for export operation or storage

**Solutions:**

- Export task itself is free, but related costs include:
  - S3 storage for exported data
  - Cross-region data transfer (if bucket in different region)
  - KMS key usage (if encrypting with custom key)
  - Snapshot storage (if new snapshot was created)
- Implement S3 lifecycle policies to reduce storage costs
- Use S3 Intelligent-Tiering for automatic cost optimization
- Delete old exports after retention period
- Export to S3 bucket in same region to avoid transfer fees
- Monitor costs with AWS Cost Explorer

### Athena Query Fails on Exported Data

**Symptoms:** Cannot query exported Parquet files with Athena

**Solutions:**

- Verify S3 path in CREATE EXTERNAL TABLE matches actual export location
- Check Athena has permissions to S3 bucket
- Ensure Parquet files are not encrypted with inaccessible KMS key
- Verify column names and data types in table definition
- Use AWS Glue crawler to automatically generate correct schema
- Check for nested or complex data types requiring special handling
- Try querying with simpler SELECT statement first
- Review Athena query logs for specific error messages

### Slow Export Performance

**Symptoms:** Export taking much longer than expected

**Solutions:**

- Export speed depends on:
  - Snapshot size (larger = longer)
  - Database instance class (affects I/O)
  - Network bandwidth
  - Number of tables and indexes
  - KMS re-encryption (if different keys)
- Typical speed: 10-20 GB per hour
- Export during off-peak hours for better performance
- Consider selective table export to reduce data volume
- Avoid re-encryption by using same KMS key for snapshot and export
- Check for no other heavy operations on same database
- Contact AWS Support if performance is significantly degraded

### Cannot Delete Export Task

**Symptoms:** Export task remains visible even after completion

**Solutions:**

- Export tasks are permanent records and cannot be deleted
- They remain visible in AWS console and API responses
- Use descriptive naming to identify old exports
- Filter by date when listing export tasks
- Export task metadata is free (no storage cost)
- Focus on deleting exported S3 data instead:

  ```bash
  aws s3 rm s3://bucket/prefix/export-task-id/ --recursive
  ```

### Cross-Region Export Issues

**Symptoms:** Export fails or incurs unexpected costs with cross-region setup

**Solutions:**

- Verify S3 bucket region vs database region
- Cross-region exports are supported but have additional costs:
  - Data transfer charges apply (typically $0.02/GB)
  - Higher latency and slower speeds
- Recommend using S3 bucket in same region when possible
- For cross-region requirements:
  - Ensure IAM role permissions include cross-region access
  - Verify KMS key (if used) is accessible from both regions
  - Consider S3 Cross-Region Replication as alternative
- Export to same-region bucket first, then replicate if needed
