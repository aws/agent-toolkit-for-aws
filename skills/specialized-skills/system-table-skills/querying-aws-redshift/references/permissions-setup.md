# Permissions Setup: Athena and Redshift Access to Published System Tables

Loaded on demand from `querying-aws-redshift` SKILL.md. Read this before running the IAM, Lake Formation, or auto-mount setup — the SKILL.md summary states the constraints but not the full command sequence.

## For Athena Querying

Requires:

- S3 Tables catalog registered in Glue (`s3tablescatalog/aws-redshift`)
- Athena execution permissions and a workgroup with an output location
- S3 Tables read permissions (see the least-privilege policy in `${SKILL_DIR}/references/security.md`)

**Encrypt the workgroup's output location.** Athena writes full result sets to S3, so `query_text`, `user_name`, and `remote_host` from the `SYS_*` tables land there in plaintext unless the workgroup enforces encryption. Configure SSE-KMS and lock it so query authors cannot override it:

```bash
aws athena update-work-group \
  --region <REGION> \
  --work-group <WORKGROUP> \
  --configuration-updates 'EnforceWorkGroupConfiguration=true,ResultConfigurationUpdates={OutputLocation=s3://<RESULTS_BUCKET>/<PREFIX>/,EncryptionConfiguration={EncryptionOption=SSE_KMS,KmsKey=<KEY_ARN>}}'
```

`EnforceWorkGroupConfiguration=true` is the part that matters — without it a client can pass its own unencrypted `ResultConfiguration` per query. Verify with `aws athena get-work-group --work-group <WORKGROUP>`.

Confirm the catalog is registered:

```bash
aws glue get-databases --region <REGION> \
  --catalog-id "<ACCOUNT>:s3tablescatalog/aws-redshift"
```

- Returns namespaces (databases) → catalog is registered and queryable.
- `EntityNotFoundException` / `CATALOG_NOT_FOUND` → S3 Tables integration not enabled. Enable the S3 Tables integration: S3 console > Table buckets > Enable integration.

## For Redshift Querying (Auto-Mounted S3 Tables Catalog)

Prerequisites:

- A Provisioned RA3 cluster. Auto-mount support depends on node type; confirm the current supported node types in the [Redshift documentation](https://docs.aws.amazon.com/redshift/latest/mgmt/working-with-clusters.html) or via `aws redshift describe-orderable-cluster-options` rather than assuming a fixed list.
- The Glue `s3tablescatalog` S3 Tables catalog must exist (auto-created when the table bucket is integrated with analytics services)

### Step 1: Create IAM Role with Required Permissions

Create a role (e.g., `query_s3_tables`) with:

Trust Policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "redshift.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {"StringEquals": {"aws:SourceAccount": "<ACCOUNT>"}}
    },
    {
      "Effect": "Allow",
      "Principal": {"Service": "lakeformation.amazonaws.com"},
      "Action": ["sts:AssumeRole", "sts:SetContext", "sts:SetSourceIdentity", "sts:TagSession"],
      "Condition": {"StringEquals": {"aws:SourceAccount": "<ACCOUNT>"}}
    }
  ]
}
```

All four actions (`sts:AssumeRole`, `sts:SetContext`, `sts:SetSourceIdentity`, `sts:TagSession`) are mandatory for `lakeformation.amazonaws.com`. Without them, Lake Formation cannot assume the role for federation.

The `aws:SourceAccount` conditions guard against the [confused deputy problem](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html): a bare service principal with no condition can be assumed on behalf of *any* account, so a caller in another account could induce the service to use this role. Restrict to the account that owns the cluster. Use `aws:SourceArn` with the cluster ARN instead if you want to pin to a single cluster.

Create the role and attach the read-only query policy. Pass both documents inline so the commands work unchanged through the AWS MCP server's `call_aws` tool, which cannot read local files:

```bash
aws iam create-role \
  --role-name query_s3_tables \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"redshift.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<ACCOUNT>"}}},{"Effect":"Allow","Principal":{"Service":"lakeformation.amazonaws.com"},"Action":["sts:AssumeRole","sts:SetContext","sts:SetSourceIdentity","sts:TagSession"],"Condition":{"StringEquals":{"aws:SourceAccount":"<ACCOUNT>"}}}]}'

aws iam put-role-policy \
  --role-name query_s3_tables \
  --policy-name S3TablesQueryAccess \
  --policy-document '<the inline policy JSON below, minified>'
```

At a terminal you can substitute `file://trust-policy.json` / `file://inline-policy.json` for the inline strings, which avoids shell-quoting problems with long documents. Inline is the primary form because `file://` silently fails wherever the executing agent has no filesystem.

**Do not attach `AWSLakeFormationDataAdmin` to this role.** The role above is attached to the cluster (Step 2) and is used to *serve queries*; it needs read access only. The Lake Formation setup steps below (`register-resource` in Step 3, `put-data-lake-settings` in Step 4) are data-lake-administrator operations that `AdministratorAccess` alone does not satisfy — Lake Formation gates them on data lake admin status rather than on IAM alone. Run those steps as **the human or automation principal performing setup**, not as the cluster's role, so the cluster never holds administrative Lake Formation permissions at runtime:

```bash
# One-time, on the SETUP principal (not the cluster role):
aws iam attach-role-policy \
  --role-name <YOUR_SETUP_ROLE> \
  --policy-arn arn:aws:iam::aws:policy/AWSLakeFormationDataAdmin
```

  `AWSLakeFormationDataAdmin` is a broad starting point, not a production posture: it grants administrative control over *every* Lake Formation resource in the account, including `PutDataLakeSettings`, which can rewrite the admin list. For production, replace it on the setup principal with a custom policy holding only the setup actions actually used here, and detach it once setup completes:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "lakeformation:RegisterResource",
        "lakeformation:DescribeResource",
        "lakeformation:ListResources",
        "lakeformation:GetDataLakeSettings",
        "lakeformation:PutDataLakeSettings",
        "lakeformation:GrantPermissions",
        "lakeformation:ListPermissions"
      ],
      "Resource": "*"
    }]
  }
  ```

  Once setup is complete, detach it from the setup principal too — nothing in steady-state querying needs it. The cluster's role only ever needs the read-only inline policy below.

- Inline policy for S3 Tables, Glue, and Lake Formation access, scoped to the `aws-redshift` table bucket and its catalog:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableMetadataLocation",
        "s3tables:GetTableData",
        "s3tables:GetNamespace",
        "s3tables:ListTables",
        "s3tables:ListNamespaces",
        "s3tables:GetTableBucket"
      ],
      "Resource": [
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift",
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetDatabases",
        "glue:GetTable",
        "glue:GetTables"
      ],
      "Resource": [
        "arn:aws:glue:<REGION>:<ACCOUNT>:catalog",
        "arn:aws:glue:<REGION>:<ACCOUNT>:catalog/s3tablescatalog",
        "arn:aws:glue:<REGION>:<ACCOUNT>:catalog/s3tablescatalog/aws-redshift",
        "arn:aws:glue:<REGION>:<ACCOUNT>:database/s3tablescatalog/aws-redshift/*",
        "arn:aws:glue:<REGION>:<ACCOUNT>:table/s3tablescatalog/aws-redshift/*/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "lakeformation:GetDataAccess",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceAccount": "<ACCOUNT>"
        }
      }
    }
  ]
}
```

`lakeformation:GetDataAccess` is the one action here that cannot be scoped by resource ARN — the Lake Formation documentation states that `"Resource": "*"` is required and "specifying any other resource for this permission is not supported." The actual data authorization comes from the Lake Formation grants, not from this statement. The `aws:ResourceAccount` condition constrains it to same-account table buckets, so the role cannot be used to vend credentials for a table bucket shared in from another account. Use `StringEquals`, not `StringLike` — `aws:ResourceAccount` is a sensitive condition key and wildcards in it defeat the check.

Note the shape of the Glue database and table ARNs: federated S3 Tables catalogs nest under `s3tablescatalog/<table-bucket>`, so the resource path is `database/s3tablescatalog/aws-redshift/*`, not the bare `database/*`. The bare form would grant metadata read on every database and table in the account's default Glue catalog — far more than querying published system tables needs.

If you hit a permission error during initial setup that the scoped policy above doesn't cover, widen it deliberately and narrow it back down for production — do not fall back to `"Action": "*"` on `"Resource": "*"`.

### Step 2: Attach Role to Cluster

```bash
aws redshift modify-cluster-iam-roles \
  --cluster-identifier <CLUSTER_ID> \
  --add-iam-roles "arn:aws:iam::<ACCOUNT>:role/query_s3_tables" \
  --region <REGION>
```

### Step 3: Register the Table Bucket with Lake Formation

Scope the registration to just the `aws-redshift` table bucket so the role cannot be used to reach other table buckets in the account:

```bash
aws lakeformation register-resource \
  --region <REGION> \
  --resource-arn "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift" \
  --role-arn "arn:aws:iam::<ACCOUNT>:role/query_s3_tables"
```

Note: `VerificationStatus: NOT_VERIFIED` after registration is normal and does not block functionality.

### Step 4: Add Redshift SLRs as Lake Formation Read-Only Admins

```bash
aws lakeformation put-data-lake-settings \
  --region <REGION> \
  --data-lake-settings '{
    "DataLakeAdmins": [
      {"DataLakePrincipalIdentifier": "arn:aws:iam::<ACCOUNT>:role/<YOUR_ADMIN_ROLE>"}
    ],
    "ReadOnlyAdmins": [
      {"DataLakePrincipalIdentifier": "arn:aws:iam::<ACCOUNT>:role/aws-service-role/redshift.amazonaws.com/AWSServiceRoleForRedshift"},
      {"DataLakePrincipalIdentifier": "arn:aws:iam::<ACCOUNT>:role/aws-service-role/redshift.aws.internal/AWSServiceRoleForRedshiftInternal"}
    ]
  }'
```

**WARNING:** `put-data-lake-settings` REPLACES the entire settings object. Always include your existing `DataLakeAdmins` alongside the new `ReadOnlyAdmins`.

### Step 5: Verify Auto-Mount

The cluster polls every 300 seconds. After up to 5 minutes:

```sql
SELECT datname FROM pg_database;
```

Expected output includes: `aws-redshift@s3tablescatalog`

If it doesn't appear after 5 minutes, a cluster reboot triggers immediate discovery.
