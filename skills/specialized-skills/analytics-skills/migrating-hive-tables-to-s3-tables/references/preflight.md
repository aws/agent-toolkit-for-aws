# Pre-flight guardrails

Run ALL of these before `start-table-migration`. Each addresses a real failure mode.

## Contents

- [0. Plan approval gate](#0-plan-approval-gate)
- [0.5 Resource discovery](#05-resource-discovery-discover-first-then-confirm-before-proceeding)
- [1. Credentials and region](#1-credentials-and-region)
- [2. Source is Glue Hive Parquet](#2-source-is-glue-hive-parquet)
- [3. Partition locations](#3-partition-locations)
- [4. Source prefix](#4-source-prefix-let-planning-classify-it)
- [5. Destination bucket and namespace](#5-destination-bucket-and-namespace-exist)
- [6. Lake Formation (stop if registered)](#6-lake-formation-stop-if-registered)
- [7. IAM role and KMS](#7-iam-role-trust-permissions-and-kms)
- [Checklist](#pre-flight-checklist-all-must-pass)

## 0. Plan approval gate

A conversation gate, not a CLI check. Follow the approval rule in "Before you migrate" in
`SKILL.md`; it covers every change, including IAM, KMS, and bucket changes. Read-only checks below
may run first to build the plan.

## 0.5 Resource discovery (discover first, then confirm before proceeding)

The only inputs you need from the customer are the **source table**, the **destination table
bucket**, and the **destination table name**. Discover everything else, and ask only if
discovery fails or is ambiguous:

- **Account id and caller:** from `aws sts get-caller-identity` (§1). Do not ask.
- **Migration service role:** search for an existing one before proposing to create it:

  ```bash
  aws iam list-roles --query "Roles[?contains(RoleName,'igration') || contains(RoleName,'S3Tables')].RoleName"
  ```

  This name match is a coarse first pass (it also matches DMS, MigrationHub, and partner roles).
  A role is a real candidate only if its trust policy names `migration.s3tables.amazonaws.com`
  with `aws:SourceAccount`/`aws:SourceArn`; inspect trust and inline policies (see
  `references/iam-roles.md`). Present a matching role (ARN, trust principal, how it matches) and
  confirm before using it. If none exists, offer to create one. If a role is missing a required
  permission, report what is missing and let the user fix it rather than modifying their role.
- **Report bucket:** propose an existing general-purpose bucket in the migration region. Do not
  reuse an Athena-results or other broadly readable bucket; the reports contain schema and
  data-layout detail. Verify before using it (offer to create one if none passes):
  - **Ownership:** `aws s3api head-bucket --bucket <B> --expected-bucket-owner <ACCT>` succeeds.
  - **Same region:** `aws s3api get-bucket-location --bucket <B>` returns the migration region.
    An empty or `null` `LocationConstraint` means `us-east-1`.
    A cross-region report bucket fails with `reportBucketNotSupported`.
  - **Not public:** `aws s3api get-public-access-block --bucket <B>` shows all four settings
    `true` (a `NoSuchPublicAccessBlockConfiguration` error is a FAIL), and
    `aws s3api get-bucket-policy-status --bucket <B>` reports `IsPublic: false`.
  - **Encrypted:** `aws s3api get-bucket-encryption --bucket <B>` shows SSE-S3 or SSE-KMS.
  - **Owner enforced:** `aws s3api get-bucket-ownership-controls --bucket <B>` shows `BucketOwnerEnforced`.
  - **TLS only:** the bucket policy denies requests where `aws:SecureTransport` is `false`. If it
    does not, read the current policy with `get-bucket-policy`, add one deny statement, show the
    user the full result, and apply it only after approval. Never replace the whole policy.
  - **Retention:** reports contain schema details and object keys. Ask how long to keep them.
  When your coding agent creates a new report bucket (after approval), it sets all four public-access-block
  settings, default encryption, `BucketOwnerEnforced`, a TLS-only bucket policy, and a lifecycle rule
  that expires report objects after the retention period the user chose.
- **Namespace:** default to the source database name, normalized: S3 Tables namespaces allow only
  lowercase letters, digits, and underscores. Lowercase it, replace hyphens and periods with
  underscores, show the mapping, and confirm (reuse it if it already exists, §5).

Take facts from `get-caller-identity` without asking. For resources you select or default (role,
report bucket, namespace), state what you found and confirm before proceeding.

## 1. Credentials and region

```bash
aws sts get-caller-identity
```

- Must succeed. RC 255 or empty output usually means expired credentials; refresh and retry.
- The source Glue region, the destination table bucket region, and `--region` MUST match.
  Same account and same region is a hard constraint.

## 2. Source is Glue Hive Parquet

```bash
aws glue get-table --catalog-id <ACCT> --database-name <DB> --name <TBL> \
  --query '{type:Table.TableType, informat:Table.StorageDescriptor.InputFormat, outformat:Table.StorageDescriptor.OutputFormat, serde:Table.StorageDescriptor.SerdeInfo.SerializationLibrary, location:Table.StorageDescriptor.Location, partitions:Table.PartitionKeys[].Name, params:Table.Parameters, serdeParams:Table.StorageDescriptor.SerdeInfo.Parameters, lf:Table.IsRegisteredWithLakeFormation}'
```

### How to know it is a Hive source

All three together:

- `Table.TableType` = `EXTERNAL_TABLE`.
- `InputFormat` / `OutputFormat` = `org.apache.hadoop.hive.ql.io.parquet.MapredParquet{Input,Output}Format`.
- `SerdeInfo.SerializationLibrary` = `org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe`.

Not a valid source (stop and tell the user):

- An Iceberg table (`Parameters.table_type` = `ICEBERG`, or Iceberg format classes). It is already Iceberg.
- A managed table (`TableType` = `MANAGED_TABLE`); planning fails with `sourceNotSupported`.
- Any non-Parquet format (ORC, Avro, JSON, CSV, text).

### Unsupported table properties (stop if present)

Check `Table.Parameters` and `SerdeInfo.Parameters` from the call above:

| Property | Means | Action |
|---|---|---|
| `transactional` = `true`, or `transactional_properties` set | Hive ACID table | Stop: not supported |
| `storage_handler` set | Table backed by a storage handler (for example HBase, DynamoDB, Kafka) | Stop: not supported |
| `projection.enabled` = `true` | Partition projection; partitions are not in the catalog, so planning cannot enumerate them | Stop and explain; the table needs catalogued partitions |
| `skip.header.line.count` set | Text-file header setting; unexpected on Parquet | Treat as a sign the table is not really Parquet; confirm the format before continuing |

Caveat: these fields prove Hive Parquet *metadata*, not that every data file is valid Parquet. The
object compatibility report from planning is the follow-on gate.

- Record the account id as `catalogId`; it is required in `--source`.

### Lowercase names (capitals break Athena/Glue visibility)

S3 Tables, the Glue Data Catalog, and Lake Formation do not support capital letters in table or
column names. A table with uppercase names migrates and reports `succeeded`, but Athena then
fails with `GENERIC_INTERNAL_ERROR: ... Invalid table or column names`. Confirm the source column
names and destination table name are lowercase before Start. Ref:
[Querying S3 tables with Athena](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-athena.html).

## 3. Partition locations

Every partition location must be under the table location. Partitions stored elsewhere (a
different prefix or bucket, common after `ALTER TABLE ADD PARTITION ... LOCATION`) fail planning
with `UNSUPPORTED_PARTITIONS`. Skip this section for an unpartitioned table.

```bash
TABLE_LOC=$(aws glue get-table --catalog-id <ACCT> --database-name <DB> --name <TBL> \
  --query 'Table.StorageDescriptor.Location' --output text)

aws glue get-partitions --catalog-id <ACCT> --database-name <DB> --table-name <TBL> \
  --query 'Partitions[].StorageDescriptor.Location' --output text \
  | tr '\t' '\n' | awk -v p="${TABLE_LOC%/}/" 'index($0, p) != 1' | head -20
```

- No output: all partitions are under the table location. Continue.
- Any output: those partitions are outside it. Stop, show the user the locations, and explain
  that the table cannot be migrated as is. Do not move data or edit partitions for them.
- Record the partition count (`get-partitions ... --query 'length(Partitions)'`); compare it with
  `planningStats.partitionCount` at plan review.
- `get-partitions` paginates; the CLI follows pages automatically, but very large tables can take
  a while. Use `--segment` for parallel listing if needed.

## 4. Source prefix (let planning classify it)

Start has no exclusion parameter. Do not remove objects from the source prefix; the source is
not modified, and markers such as `_SUCCESS` are read by other jobs.

Planning's object compatibility report names every object it could not process. Non-data objects
(keys with `_`/`.` path components, `$folder$` markers, zero-byte objects) are recorded as
non-data rather than failing the run. If a real data object is flagged, resolve it with the user.

Check one thing up front: a table `Location` under a `_`- or `.`-prefixed path component hides
everything beneath it. A non-recursive listing (`aws s3 ls s3://<SOURCE_BUCKET>/<PREFIX>/`) is
enough; do not run `aws s3 ls --recursive` over a large prefix.

## 5. Destination bucket and namespace exist

```bash
aws s3tables list-table-buckets --region <R>
aws s3tables list-namespaces --table-bucket-arn <DEST_BUCKET_ARN> --region <R>
```

- If the namespace is missing, propose creating it (a missing namespace fails Start with
  `NotFoundException` (404)). Creating it is a change, so
  it is part of the approved plan:

```bash
aws s3tables create-namespace --region <R> --table-bucket-arn <DEST_BUCKET_ARN> --namespace <NS>
```

- To validate in Athena, the destination table bucket must be integrated with the Glue Data
  Catalog; see `references/validation.md` §2.

## 6. Lake Formation (stop if registered)

Glue tables registered with Lake Formation are not supported (confirm current support in the [migration guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)). Planning fails with
`metadata.glueLakeFormation`. Check both the table and its S3 location:

```bash
# Table flag (from §2): Table.IsRegisteredWithLakeFormation
aws glue get-table --catalog-id <ACCT> --database-name <DB> --name <TBL> \
  --query 'Table.IsRegisteredWithLakeFormation'

# Is the table location (or a parent) a registered data location?
aws lakeformation list-resources --query 'ResourceInfoList[].ResourceArn' --output text
```

Compare the registered ARNs with the table location (`arn:aws:s3:::<bucket>/<prefix>`); a
registered parent prefix or bucket also counts.

- If either check shows the table is governed by Lake Formation: stop and tell the user the table
  is not supported.
- Do NOT change Lake Formation settings, deregister locations, or grant permissions to work around
  this. Those are governance decisions that belong to the customer's data lake administrators.
- If `list-resources` is denied, say so and ask the user to confirm the registration status rather
  than assuming it is not registered.

## 7. IAM role trust, permissions, and KMS

See `references/iam-roles.md`: single `migration.s3tables.amazonaws.com` principal with
`aws:SourceAccount` and `aws:SourceArn`, scoped permissions, report bucket write, and KMS.

- If the source data or the report bucket uses a customer managed KMS key, the role needs
  `kms:Decrypt` (source) and `kms:GenerateDataKey` (report and destination writes) on that key.
- If the destination table bucket uses SSE-KMS, the key **policy** must grant
  `maintenance.s3tables.amazonaws.com` `kms:GenerateDataKey` and `kms:Decrypt`. Without it,
  creating the encrypted table fails and planning never completes.

## Pre-flight checklist (all must pass)

- [ ] plan presented and approved (§0)
- [ ] `sts get-caller-identity` succeeds; source and destination in the same account and region
- [ ] source is Glue Hive Parquet (`EXTERNAL_TABLE`, Hive Parquet formats and SerDe); not Iceberg, not managed
- [ ] no `transactional`, `storage_handler`, or `projection.enabled` properties; `skip.header.line.count` explained
- [ ] `catalogId` recorded
- [ ] source table and column names are lowercase
- [ ] every partition location is under the table location; partition count recorded
- [ ] table `Location` not under a `_`/`.` path component
- [ ] destination table bucket and namespace exist (or namespace creation approved)
- [ ] destination bucket integrated with the Glue Data Catalog if validating in Athena
- [ ] table not registered with Lake Formation (table flag and data location both checked)
- [ ] migration role trust and permissions verified; report bucket write covered
- [ ] KMS key access and key policy covered if encrypted
