# DMS Schema Conversion: Setup Wizard Reference

## Table of Contents

- [Global Constraints](#global-constraints)
- [Phase 1 — Project Name](#phase-1--project-name)
- [Phase 2 — Target Type Selection](#phase-2--target-type-selection)
- [Phase 3 — Source Database](#phase-3--source-database)
  - [3d — Offline source configuration](#3d--offline-source-configuration)
- [Phase 4 — Network Investigation & Connectivity](#phase-4--network-investigation--connectivity)
- [Phase 5 — Create DMS Subnet Group](#phase-5--create-dms-subnet-group)
- [Phase 6 — Database Credentials](#phase-6--database-credentials)
- [Phase 7 — Create Data Providers](#phase-7--create-data-providers)
- [Phase 8 — S3 Bucket](#phase-8--s3-bucket)
- [Phase 9 — IAM Roles](#phase-9--iam-roles)
- [Phase 10 — Create Instance Profile](#phase-10--create-instance-profile)
- [Phase 11 — Transformation Rules (Optional)](#phase-11--transformation-rules-optional)
- [Phase 12 — Create Migration Project & Summary](#phase-12--create-migration-project--summary)

---

## Global Constraints

> Execute commands using available tools from the AWS MCP server when connected — it provides sandboxed execution, audit logging, and observability. When the MCP server is not available, fall back to the AWS CLI or shell as needed.

- You MUST resolve `aws_account_id` by running `aws sts get-caller-identity` and extracting the `Account` field
- You MUST present exactly one phase at a time. Ask only the current phase's questions, then stop and wait for the customer's answer. Do NOT mention or collect inputs from later phases, even to be efficient. Never gather the essential inputs up front.
- When project selection finds no migration projects, explicitly ask whether to create one and wait for the customer's answer. Do not infer consent from the original conversion request.
- You MUST confirm each resource was created successfully before moving to the next phase
- **Mutation approval:** Immediately before each create, modify, delete, upload, IAM, or S3 write operation, show the exact planned action and wait for explicit customer confirmation. Approval applies only to that action. Do not infer approval from the original migration request or from confirmation of an input value.
- You MUST show a running summary of collected values at the start of each new phase
- You MUST handle `ResourceAlreadyExistsFault` and similar errors by reusing the existing resource
- You MUST NOT display or log passwords at any point
- You SHOULD suggest sensible defaults based on already-collected information

---

## Phase 1 — Project Name

**Goal:** Establish a project name prefix used for all resource names.

Ask:
> "What would you like to name this migration project? This will be used as a prefix for all created resources (e.g., `myproject` → `myproject-instance-profile`, `myproject-s3-bucket`, etc.)."

**Resource Naming Convention — you MUST use these exact names (no variations):**

| Resource | Name pattern |
|----------|-------------|
| Migration Project | `<project_name>-migration-project` |
| Instance Profile | `<project_name>-instance-profile` |
| DMS Subnet Group | `<project_name>-subnet-group` |
| Source Data Provider | `<project_name>-source` |
| Target Data Provider | `<project_name>-target` |
| S3 Bucket (migration artifacts) | `<project_name>-sc-bucket-<aws_account_id>-<aws_region>` |
| Secrets IAM Role | `<project_name>-sc-secrets-role` |
| S3 IAM Role (migration artifacts) | `<project_name>-sc-s3-role` |
| S3 Access Role (offline source, if applicable) | `<project_name>-sc-s3-access-role` |

**Constraints:**

- Resolve `aws_account_id` by running `aws sts get-caller-identity` and extracting the `Account` field
- Ask the customer which AWS region to use. Do NOT attempt to infer it from the STS response. Store as `aws_region`.
- If region resolution fails, ask the customer to provide it manually
- The project name MUST be between 1 and 25 characters, start with a lowercase letter or number, and contain only lowercase letters, numbers, and hyphens. Validate this before proceeding. If the customer provides uppercase characters, auto-lowercase the name and inform them. (The 25-character limit ensures the derived S3 bucket name `<project_name>-sc-bucket-<account_id>-<region>` stays within the 63-character S3 bucket name limit even for the longest AWS region names.)
- Store `migration_project_name = <project_name>-migration-project` and use it for every migration-project operation.
- After the customer provides a name, you MUST check for existing resources that would be created under that prefix. Run all of the following lookups and present a consolidated summary before proceeding:

  ```

  aws dms describe-migration-projects --filters Name=migration-project-identifier,Values=<migration_project_name>
  aws dms describe-instance-profiles --filters Name=instance-profile-identifier,Values=<project_name>-instance-profile
  aws dms describe-replication-subnet-groups --filters Name=replication-subnet-group-id,Values=<project_name>-subnet-group
  aws dms describe-data-providers --filters Name=data-provider-identifier,Values=<project_name>-source
  aws dms describe-data-providers --filters Name=data-provider-identifier,Values=<project_name>-target
  aws s3api head-bucket --bucket <project_name>-sc-bucket-<aws_account_id>-<aws_region>
  aws iam get-role --role-name <project_name>-sc-secrets-role
  aws iam get-role --role-name <project_name>-sc-s3-role
  aws iam get-role --role-name <project_name>-sc-s3-access-role
  aws iam get-role --role-name dms-vpc-role
  aws iam get-role --role-name dms-cloudwatch-logs-role

  ```

- For each lookup, treat `NotFoundException`, `ResourceNotFoundException`, `NoSuchEntity`, or `404` as "not found" — do NOT surface these as errors to the customer
- After all lookups complete, present a table of what already exists vs. what will be created:

  | Resource | Status |
  |---|---|
  | Migration Project `<migration_project_name>` | EXISTS / will be created |
  | Instance Profile `<project_name>-instance-profile` | EXISTS / will be created |
  | Subnet Group `<project_name>-subnet-group` | EXISTS / will be created |
  | Source Data Provider `<project_name>-source` | EXISTS / will be created |
  | Target Data Provider `<project_name>-target` | EXISTS / will be created |
  | S3 Bucket `<project_name>-sc-bucket-<aws_account_id>-<aws_region>` | EXISTS / will be created |
  | Secrets IAM Role `<project_name>-sc-secrets-role` | EXISTS / will be created if required by a provider descriptor |
  | S3 IAM Role `<project_name>-sc-s3-role` | EXISTS / will be created |
  | S3 Access Role `<project_name>-sc-s3-access-role` (offline source) | EXISTS / will be created if needed |
  | DMS VPC Role `dms-vpc-role` | EXISTS / will be created |
  | DMS CloudWatch Role `dms-cloudwatch-logs-role` | EXISTS / will be created |

- If the migration project already exists, inform the customer and ask: "A migration project with this name already exists. Would you like to (1) choose a different name, or (2) continue anyway and reuse existing resources where possible? If you choose option 2, please provide a new name for any resources that need to be recreated."
- You MUST wait for the customer's confirmation before proceeding to Phase 2

---

## Phase 2 — Target Type Selection

**Goal:** Determine whether the target is a live database instance or a virtual target.

Explain:
> "DMS Schema Conversion supports two target modes:
>
> - **Live database** — connects to a live Amazon RDS, Aurora, or Redshift instance. DMS reads its network config automatically.
> - **Virtual** — no live target database needed. Useful for reviewing converted schema without an actual DB.
>
> Which would you like? (live / virtual)"

**Supported target engines:** `aurora-postgresql`, `postgres`, `mysql`, `aurora`, `redshift`, `db2`. See [DMS SC supported target databases](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-target.html) for the full list. A value of `aurora` represents Amazon Aurora MySQL-Compatible Edition.

**Constraints:**

- Accept `live` or `virtual` (case-insensitive); store as `use_virtual_target`
- **If live:** Ask for the target engine type (e.g., `aurora-postgresql`, `mysql`, `redshift`). Then ask:
  > "Is your target an Amazon RDS/Aurora instance or Redshift cluster? If yes, provide the ARN and I'll retrieve connection details automatically. Otherwise, provide hostname, port, database name."

  - **If ARN provided:** Call `aws rds describe-db-instances` (or `describe-db-clusters` for Aurora, or `aws redshift describe-clusters` for Redshift) to fetch `target_hostname`, `target_port`, and `target_database_name`. Also extract `target_vpc_id`, `target_subnet_ids`, and `target_security_group_ids` from the instance/cluster metadata. Inform the customer of what was found.
  - **If no ARN:** Ask for the target database connection info (hostname, port, database name). Also ask for the VPC ID, subnet IDs, and security group IDs associated with the target.

  Store as `target_engine`, `target_hostname`, `target_port`, `target_database_name`, `target_vpc_id`, `target_subnet_ids`, `target_security_group_ids`.
- **If virtual:** Ask for the target engine type (e.g., `aurora-postgresql`, `mysql`, `redshift`). Store as `target_engine`.

  Prepare the target data provider params for use in Phase 7b:

  ```

  target_data_provider_params = {
      "DataProviderName": "<project_name>-target",
      "Engine": "<target_engine>",
      "Virtual": True,
      "Settings": {
          "<TargetEngineSettings>": {
              "ServerName": "virtual",
              "Port": <default_port>,
              "DatabaseName": "virtual",
              "SslMode": "none"
          }
      }
  }

  ```

  Map `target_engine` → Settings key and default port:
  - `aurora-postgresql` or `postgres` → `PostgreSqlSettings`, port 5432
  - `mysql` or `aurora` → `MySqlSettings`, port 3306
  - `redshift` → `RedshiftSettings`, port 5439
  - `db2` → `IbmDb2LuwSettings`, port 50000

---

## Phase 3 — Source Database

**Goal:** Collect source engine and connection details.

### 3a — Source type

Ask for source engine. Supported source engines: `sqlserver`, `oracle`, `mysql`, `postgres`, `db2`, `db2-zos`, `sybase`. See [DMS SC supported source databases](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Introduction.Sources.html#CHAP_Introduction.Sources.SchemaConversion) for the full list. The customer may provide the engine name in any format — map it to the correct API identifier automatically.

### 3b — Source mode (online / offline)

Read [Virtual mode for offline source and virtual target](https://docs.aws.amazon.com/dms/latest/userguide/virtual-data-provider.html). Under **Offline source** → **Prerequisites for an offline source** → **Supported source database dialects**, check whether the selected source engine is listed. Then verify that Phase 3d contains both a matching engine-specific DDL validation section in Step 3 and a `DatabaseName` rule in Step 5.

- **If the engine is listed and both Phase 3d mappings exist**, ask:
  > "Would you like to connect directly to the source database (online mode), or use exported DDL scripts from S3 (offline mode)?
  >
  > - **Online** — DMS connects to your database to read metadata directly.
  > - **Offline** — DMS reads metadata from DDL scripts you've uploaded to S3. No database connectivity required."

  Store as `source_mode` (`online` or `offline`).
- **If the engine is listed but either Phase 3d mapping is missing**, stop and explain that this wizard has no validated offline configuration for the selected dialect. Do not invent DDL validation rules or data-provider settings.
- **If the engine is not listed**, set `source_mode = online`, do not offer offline mode, and continue to Phase 3c.

If `source_mode = offline`, continue to Phase 3d. Otherwise continue to Phase 3c.

### 3c — Source connection (online mode only)

**Skip this step if `source_mode = offline`.**

Ask for hostname, port, and database name in a single prompt. If the source is an RDS instance, offer to look up the connection details automatically:
> "Is your source database an RDS instance? If yes, provide the RDS instance ARN or identifier and I'll retrieve the connection details automatically. Otherwise, please provide the hostname, port, and database name."

- **If RDS source:** Call `aws rds describe-db-instances` (or `describe-db-clusters` for Aurora) to fetch `source_hostname`, `source_port`, and `source_database_name`. Inform the customer of what was found.
- **If not RDS:** Ask for hostname, port, and database name directly.

Store as `source_hostname`, `source_port`, `source_database_name`.

### 3d — Offline source configuration

**Skip this step if `source_mode = online`.**

#### Constraints

- Do not request source database connection credentials during offline source configuration. An offline source does not connect to a database. Migration-project descriptor credential fields, when required by current documentation, are handled separately in Phase 6.
- Do not display, quote, reconstruct, summarize as SQL, log, or retain DDL content while preparing or validating this source. Report object keys, metadata, object names and types, operation statuses, and statistics. Read only the minimum statement fragments required to derive documented identity fields.

#### Step 1 — DDL Scripts (Offline Source)

Read the selected engine's export guidance linked from the virtual-mode documentation used in Phase 3b before preparing or validating the DDL.

Ask:
> "What is the current state of your DDL scripts?
>
> 1. Already exported and uploaded to S3
> 2. Already exported but not yet uploaded to S3
> 3. Not yet exported — I'd like help"

**Option 1 (exported + uploaded):** Proceed to Step 2.

**Option 2 (exported, not uploaded):**

Ensure the DDL scripts are available as individual `.sql` files. If the customer provides an archive (`.zip`, `.tar.gz`, `.tar`), extract it first. Do not treat the archive as DMS input. Step 2 collects and validates the destination before upload.

**Constraints:**

- Do NOT generate presigned URLs as the default upload method — prefer `aws s3 sync` or `aws s3 cp`.
- Do NOT ask the customer about encryption for files the agent uploads — always use `--sse AES256`.
- Do not infer database or schema identity from an archive or folder name.

**Option 3 (not exported):**

Follow the selected engine's documented export procedure. Give the customer clearly marked placeholders to use independently, and do not request or handle database credentials. When the files are available, resume with Option 2.

**If the customer provides a file path or mentions having files at any point**, switch to Option 2 flow immediately.

#### Step 2 — S3 Configuration (Offline Source)

Ask for the S3 path based on the customer's Step 1 selection:

- **Option 1:**
  > "Please provide the S3 path to your DDL scripts (e.g., `s3://my-bucket/MyDatabase/`)."
- **Options 2 or 3:**
  > "Please provide the S3 destination where I should upload your DDL scripts (e.g., `s3://my-bucket/MyDatabase/`)."

Store the selected S3 URI as `ddl_s3_path` and extract `ddl_bucket_name`. If the path identifies a prefix, store it as `ddl_prefix`; otherwise set `ddl_prefix = ""` for the bucket root.

1. Get the bucket Region with `aws s3api head-bucket --bucket <ddl_bucket_name> --query BucketRegion --output text`. Compare the returned Region with `aws_region`, the migration project Region. If they differ, stop before upload and ask the customer for an S3 path whose bucket is in `aws_region`.
2. Verify the bucket belongs to `aws_account_id`. Cross-account offline DDL access is not supported by this flow.
3. If upload is required, show the exact planned upload to `ddl_s3_path` and wait for explicit customer confirmation. After approval, upload only the extracted `.sql` files with `--sse AES256`. Verify that every expected `.sql` file appears under `ddl_s3_path`.
4. Confirm the selected S3 location contains `.sql` objects. If empty or path not found, inform the customer and ask to correct.
5. For a pre-existing S3 location, ask whether the selected `.sql` objects are encrypted with a customer-managed KMS key. If yes, ask for the key ARN and store it as `s3_kms_key_arn`. If no, set `s3_kms_key_arn = null`.
6. For files uploaded by this flow, set `s3_kms_key_arn = null` because the upload uses SSE-S3.

#### Step 3 — DDL Validation (Offline Source)

The selected S3 location must contain separate Unicode-encoded `.sql` files for database objects. Each object file contains one primary `CREATE` statement, uses schema-qualified object names, and excludes DML and `DROP` statements. Documented dependent statements may remain in the same object file.

Apply the selected engine's current export requirements:

**SQL Server**

- Require a separate file containing `CREATE DATABASE [<database_name>]` and require each object file to start with `USE [<database_name>];`. Treat unqualified objects as belonging to `dbo`.
- Collect every database name from `CREATE DATABASE` and `USE` statements in the selected S3 location. Require one consistent name because each data provider has one `DatabaseName`.
- If no name is present, ask the customer to correct the DDL set. If multiple names are present, ask for an S3 path scoped to one database.

**Oracle**

- Require a separate file containing `CREATE USER <schema_name> NO AUTHENTICATION;` for each schema and require object names to be schema-qualified.
- Collect schema names from the `CREATE USER` statements and schema-qualified object names. Require every schema referenced by an object file to have a corresponding `CREATE USER` file.
- If a schema identity is missing or inconsistent, ask the customer to correct the DDL set.

Do not display or retain the inspected statements.

#### Step 4 — S3 Access Role (Offline Source)

Complete [Phase 9e — S3 Access Role for Offline Source](#9e--s3-access-role-for-offline-source) now to obtain `offline_s3_access_role_arn`, then continue to Step 5.

#### Step 5 — Prepare Source Data Provider Settings (Offline Source)

Read the current [`create-data-provider` reference](https://docs.aws.amazon.com/cli/latest/reference/dms/create-data-provider.html) and the selected engine's current DMS source-database documentation. Derive the exact `Engine` value and settings object key from the API reference, and the recommended port from the engine documentation. Do not infer these values. If the documentation does not define them unambiguously, stop before provider creation.

Use the `DatabaseName` rule paired with the engine-specific validation completed in Step 3:

| DDL validation section | DatabaseName |
|---|---|
| SQL Server | The single database name validated from the DDL |
| Oracle | `offline` |

Prepare and retain this structure:

```

source_data_provider_params = {
    "DataProviderName": "<project_name>-source",
    "Engine": "<source_engine>",
    "Virtual": True,
    "Settings": {
        "<SourceEngineSettings>": {
            "ServerName": "<project_name>-source-offline",
            "Port": <default_port>,
            "DatabaseName": "<database_name>",
            "SslMode": "none",
            "S3Path": "<ddl_s3_path>",
            "S3AccessRoleArn": "<offline_s3_access_role_arn>"
        }
    }
}

```

Replace `<source_engine>`, `<SourceEngineSettings>`, and `<default_port>` with the exact values derived from the current references above. Replace the remaining placeholders with the collected values. Set `<database_name>` from the matching rule above: use the single database name validated for SQL Server or `offline` for Oracle. Keep `Virtual: True` embedded in the structure; Phase 7a uses these retained values when creating the source data provider.

---

## Phase 4 — Network Investigation & Connectivity

**Goal:** Determine VPC, subnets, and security groups for the DMS instance profile.

### 4a — Derive or ask for VPC

**Skip Phase 4 entirely (4a, 4b, 4c) if `source_mode = offline` AND `use_virtual_target = true`.** No network configuration is needed — the instance profile will be created without subnet group or security groups.

- **If live target:** Use `target_vpc_id` from Phase 2. Ask if the customer also wants to reuse the target subnets and security groups. If yes, skip to 4c.
  > **Note:** Reusing the same security group is less secure than creating a dedicated SG with minimal permissions.
- **If virtual target AND `source_mode = online`:** Use the VPC where the source database resides. If the source is an RDS instance, derive the VPC from the RDS metadata. Otherwise, ask the customer which VPC the source database is in.

### 4b — Collect subnets and security groups manually

- Ask for at least two subnet IDs from different AZs (comma-separated)
- Validate with: `aws ec2 describe-subnets --subnet-ids <ids> --query Subnets[*].{ID:SubnetId,AZ:AvailabilityZone,VPC:VpcId}`
- Verify all subnets belong to the same VPC and span at least 2 AZs
- Ask for security group IDs (comma-separated)
- After collecting security group IDs, run `aws ec2 describe-security-groups --group-ids <ids>` and check for rules referencing `0.0.0.0/0` or `::/0`. If found, warn the customer and recommend scoping rules to the specific database port and source CIDR or security group reference.

### 4c — Connectivity confirmation

**Skip this step if `source_mode = offline`** — no source database connectivity is needed.

Ask:
> "Does your source database require special network setup to be reachable from this VPC? (VPN, Direct Connect, VPC peering, firewall rules) (yes / no)"

- **If yes:** Guide the customer through the network setup based on https://docs.aws.amazon.com/dms/latest/userguide/instance-profiles-network.html. Read the documentation and help them configure VPN, Direct Connect, VPC peering, or firewall rules as needed.
- **If no:** Reference https://docs.aws.amazon.com/dms/latest/userguide/instance-profiles-network.html#instance-profiles-network-one-vpc. Read the documentation requirements and validate that the customer's network configuration meets all of them.

Store final `vpc_id`, `subnet_ids`, `security_group_ids`.

---

## Phase 5 — Create DMS Subnet Group

**Skip this phase if `source_mode = offline` AND `use_virtual_target = true`.**

**Goal:** Create the subnet group for the DMS instance profile.

Show this create command and wait for explicit customer confirmation. After approval, create or reuse the subnet group:

```

aws dms create-replication-subnet-group \
  --replication-subnet-group-identifier <project_name>-subnet-group \
  --replication-subnet-group-description "Subnet group for <project_name>" \
  --subnet-ids <subnet_ids>

```

Store `subnet_group_identifier`. On `ResourceAlreadyExistsFault`, reuse existing.

---

## Phase 6 — Database Credentials

**Goal:** Collect the Secrets Manager secrets for both source and target database credentials.

### 6a — Source credentials

**If `source_mode = offline`:** Skip source credential collection. Set `source_secret_arn = null` and `source_secrets_role_arn = null`. Preserve either value independently only when the customer already supplied it. Validate a supplied secret as a Secrets Manager secret ARN in `aws_account_id` and `aws_region`, and validate a supplied role as an IAM role ARN. Do not solicit or create either optional value.

**If `source_mode = online`:**

Ask if the customer needs help setting up source database credentials. Guide the customer based on [source data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-source.html) for required permissions.

Ask for the Secrets Manager secret ARN containing the source database credentials:
> "Please provide the ARN of the Secrets Manager secret with your source database username and password. If your source is an RDS instance, you can find the secret in the RDS console under 'Connectivity & security'."

**Important:** The secret must contain a JSON with keys `username` and `password`. Warn the customer that the RDS-managed admin secret has extensive privileges that Schema Conversion does not need. Recommend creating a dedicated database user with minimal required permissions. See [required permissions](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-source.html) for the full list.

Store as `source_secret_arn`.

### 6b — Target credentials

**If `use_virtual_target = true`:** Skip target credential collection. Set `target_secret_arn = null` and `target_secrets_role_arn = null`. Preserve either value independently only when the customer already supplied it, using the same validation as the virtual source. Do not solicit or create either optional value.

**If the target is live:**

Ask if the customer needs help setting up target database credentials. Guide the customer based on [target data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-target.html) for required permissions.

**If live target (RDS/Aurora/Redshift):** If the customer provided an ARN in Phase 2, automatically retrieve the associated secret ARN from the instance/cluster metadata (e.g., `MasterUserSecret.SecretArn` from `describe-db-instances` or `describe-db-clusters`). Inform the customer of the secret found. If no secret is associated with the instance, fall back to asking manually.

**If live target (other or manual):** Ask:
> "Please provide the ARN of the Secrets Manager secret with your target database username and password."

**Important:** Warn the customer that managed admin secrets have extensive privileges that Schema Conversion does not need. Recommend creating a dedicated database user with minimal required permissions and storing those credentials in a separate secret.

Store as `target_secret_arn`.

Set `secrets_role_required = true` when the source or target is non-virtual; otherwise set it to `false`. Build `required_secret_arns` only from non-virtual provider secrets. Optional values supplied for a virtual provider do not trigger role creation or broaden a role policy.

---

## Phase 7 — Create Data Providers

**Goal:** Register source and target data providers in DMS.

For each provider, show the exact create action and wait for explicit customer confirmation before calling `CreateDataProvider`.

### 7a — Source data provider

**If `source_mode = offline`:**

```bash
aws dms create-data-provider \
  --data-provider-name <project_name>-source \
  --engine <source_engine> \
  --virtual \
  --settings '{"<SourceEngineSettings>":{"ServerName":"<project_name>-source-offline","Port":<default_port>,"DatabaseName":"<database_name>","SslMode":"none","S3Path":"<ddl_s3_path>","S3AccessRoleArn":"<offline_s3_access_role_arn>"}}'

```

**If `source_mode = online`:**

```bash
aws dms create-data-provider \
  --data-provider-name <project_name>-source \
  --engine <source_engine> \
  --settings '{"<EngineSettings>":{"ServerName":"<source_hostname>","Port":<source_port>,"DatabaseName":"<source_database_name>","SslMode":"<ssl_mode>"}}'

```

Store `source_data_provider_arn`. Do NOT include credentials in settings.

**SSL/TLS:** For offline mode, SslMode is already set to `"none"` — do NOT ask the customer. For online mode, ask the customer which SSL mode to use (`require`, `verify-ca`, `verify-full`, `none`). Recommend `require` or higher. Warning: `none` transmits credentials and data unencrypted — use only in isolated test environments with no sensitive data.

### 7b — Target data provider

**If virtual target:**

```bash
aws dms create-data-provider \
  --data-provider-name <project_name>-target \
  --engine <target_engine> \
  --virtual \
  --settings '{"<TargetEngineSettings>":{"ServerName":"virtual","Port":<default_port>,"DatabaseName":"virtual","SslMode":"none"}}'

```

Use the same engine → Settings key mapping from Phase 2 (`PostgreSqlSettings`/5432, `MySqlSettings`/3306, `RedshiftSettings`/5439, `IbmDb2LuwSettings`/50000).

**If live target:**

```bash
aws dms create-data-provider \
  --data-provider-name <project_name>-target \
  --engine <target_engine> \
  --settings '{"<EngineSettings>":{"ServerName":"<target_hostname>","Port":<target_port>,"DatabaseName":"<target_database_name>","SslMode":"<ssl_mode>"}}'

```

Do NOT pass `Virtual` for live targets.

Store `target_data_provider_arn`.

### 7c — Verify Virtual flag

You MUST verify both data providers have the correct `Virtual` flag immediately after creation.

Expected values:

- Source: `Virtual = True` if `source_mode = offline`, `False` if online
- Target: `Virtual = True` if `use_virtual_target = true`, `False` if live target

For each data provider, describe and check the `Virtual` field:

```bash
aws dms describe-data-providers \
  --filters Name=data-provider-identifier,Values=<project_name>-source

```

If the `Virtual` flag does not match the expected value, attempt to modify:

```bash
aws dms modify-data-provider \
  --data-provider-identifier <project_name>-source \
  --engine <engine> \
  --virtual \
  --settings '<settings_json_from_describe>'

```

If modify fails ("Cannot convert a non-virtual data provider to virtual"), delete and recreate with the correct flag:

```bash
aws dms delete-data-provider \
  --data-provider-identifier <project_name>-source

aws dms create-data-provider \
  --data-provider-name <project_name>-source \
  --engine <engine> \
  --virtual \
  --settings '<settings_json>'

```

Repeat for the target data provider. After any recreate, re-store the new ARN from the `create-data-provider` response — the old ARN is no longer valid. Do NOT proceed to Phase 8 until both data providers have the correct `Virtual` flag.

---

## Phase 8 — S3 Bucket

**Goal:** Ensure an S3 bucket exists for migration artifacts.

**Response contract:** Report the full migration-artifacts encryption checklist without omitting an item: both supported modes (SSE-S3 and SSE-KMS, including customer-managed keys); the selected mode; full same-Region KMS key ARN when applicable; versioning; Block Public Access; the TLS-only bucket policy; and `BucketKeyEnabled=true` for SSE-KMS.

Ask whether the customer wants to reuse an existing artifacts bucket or create a new one. Record and validate the selected encryption mode without modifying the bucket.

- **Existing bucket:** Validate it with `head-bucket`, confirm it is in `aws_region`, verify versioning is enabled, and inspect default encryption with `get-bucket-encryption`. If it uses a customer-managed KMS key, resolve the configured key ID or alias to a full key ARN and store it as `artifacts_kms_key_arn`.
- **New bucket:** Plan `<project_name>-sc-bucket-<aws_account_id>-<aws_region>`. Ask whether to use the recommended default SSE-S3 encryption or SSE-KMS with a customer-managed key. For SSE-KMS, request a key, resolve it to a full key ARN, validate it is in `aws_region`, and store it as `artifacts_kms_key_arn`.

Before creating or modifying the bucket, show the exact planned bucket changes and wait for explicit customer confirmation before each write operation. For a new bucket, use the Region-specific `create-bucket` form, then enable versioning and block public access:

```

# For us-east-1:
aws s3api create-bucket --bucket <bucket_name> --region us-east-1

# For all other regions:
aws s3api create-bucket \
  --bucket <bucket_name> \
  --region <aws_region> \
  --create-bucket-configuration LocationConstraint=<aws_region>

aws s3api put-bucket-versioning \
  --bucket <bucket_name> \
  --versioning-configuration Status=Enabled

aws s3api put-public-access-block \
  --bucket <bucket_name> \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

```

Configure the selected encryption mode explicitly:

```

# SSE-S3
aws s3api put-bucket-encryption \
  --bucket <bucket_name> \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# SSE-KMS with a customer-managed key
aws s3api put-bucket-encryption \
  --bucket <bucket_name> \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"<artifacts_kms_key_arn>"},"BucketKeyEnabled":true}]}'

```

Add a bucket policy that denies insecure transport, scoped to the bucket and its objects:

```
aws s3api put-bucket-policy --bucket <bucket_name> --policy '{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyInsecureTransport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::<bucket_name>", "arn:aws:s3:::<bucket_name>/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}'
```

**Constraints:**

- The bucket name MUST include the region suffix: `<project_name>-sc-bucket-<aws_account_id>-<aws_region>`
- DMS Schema Conversion supports both SSE-S3 and SSE-KMS for this bucket. Do not reject an existing SSE-KMS bucket.
- A customer-managed KMS key must be in the same Region and its policy must permit the artifacts role as described in [Complete prerequisites for working with DMS Schema Conversion](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html).
- Store `bucket_name` and either `artifacts_kms_key_arn` or `null`

---

## Phase 9 — IAM Roles

**Goal:** Create IAM roles: Secrets Manager access role, S3 access role, DMS VPC role, and DMS CloudWatch Logs role.

**Important — two distinct S3 roles exist. Do NOT confuse them when troubleshooting:**

| Role | Name pattern | Purpose | Permissions |
|---|---|---|---|
| **S3 Role** (9b) | `<project_name>-sc-s3-role` | DMS reads/writes **migration artifacts** (reports, converted DDL, tree data) to the artifacts bucket | `s3:GetObject`, `s3:GetObjectVersion`, `s3:PutObject` + bucket-level `s3:ListBucket`, `s3:GetBucketLocation`, `s3:GetBucketVersioning` on the **artifacts bucket** |
| **S3 Access Role** (9e) | `<project_name>-sc-s3-access-role` | DMS reads **DDL scripts** from the offline source bucket | `s3:GetObject` and prefix-aware `s3:ListBucket` on the **DDL scripts bucket**, plus `kms:Decrypt` when the DDL uses SSE-KMS |

When an S3 permission error occurs during import, the problem is almost always the **S3 Access Role** (9e) — not the S3 Role (9b). When an S3 error occurs during project creation or export, the problem is the **S3 Role** (9b).

Apply the mutation-approval rule separately immediately before each role creation or policy change. Reusing a valid existing role does not require mutation approval.

### 9a — Secrets Manager Role

**Skip this phase if `secrets_role_required = false`.** Optional fields supplied for a virtual provider do not require the wizard to create or modify a role.

Ask if an existing role is available. If yes, validate with `aws iam get-role`. If no, create:

1. Show the exact role creation and wait for explicit customer confirmation. After approval, create the role with trust policy (includes condition keys to prevent confused deputy):

   ```

   aws iam create-role \
     --role-name <project_name>-sc-secrets-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'

   ```

2. Prepare a policy granting access to the secret ARNs used by the migration project. See [IAM policies for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-policies) for the required permissions (Secrets Manager and KMS actions). Scope the resource only to `required_secret_arns`. Show the exact policy change and wait for separate explicit customer confirmation, then attach it.

Store `secrets_role_arn`, then set `source_secrets_role_arn` and/or `target_secrets_role_arn` to this ARN for each non-virtual provider.

### 9b — S3 Role

Ask if an existing role is available. If yes, validate its trust policy and required S3 and KMS permissions. If no, create:

1. Show the exact role creation and wait for explicit customer confirmation. After approval, create the role with trust policy (includes condition keys to prevent confused deputy):

   ```

   aws iam create-role \
     --role-name <project_name>-sc-s3-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'

   ```

2. Prepare a policy granting S3 access to the artifacts bucket. Follow the exact policy from [IAM policies for DMS SC](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam): two statements — bucket-level (`s3:ListBucket`, `s3:GetBucketLocation`, `s3:GetBucketVersioning` on `arn:aws:s3:::<bucket_name>`) and object-level (`s3:PutObject`, `s3:GetObject`, `s3:GetObjectVersion` on `arn:aws:s3:::<bucket_name>/*`). Add `aws:ResourceAccount` condition for least-privilege.
3. If `artifacts_kms_key_arn` is set, add the documented SSE-KMS statement to this policy: allow `kms:Decrypt` and `kms:GenerateDataKey` on that key with `kms:ViaService` set to `s3.<aws_region>.amazonaws.com`. Confirm the KMS key policy delegates access to IAM or explicitly permits this role.
4. Show the exact completed policy change and wait for separate explicit customer confirmation, then attach it.

Store `s3_role_arn`.

### 9c — DMS VPC Role

Required by DMS to manage VPC and ENI resources. The role name MUST be exactly `dms-vpc-role` — DMS looks it up by this fixed name. See [IAM roles for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-roles) for details.

First check if the role exists:

```

aws iam get-role --role-name dms-vpc-role

```

If the role already exists (found in Phase 1 lookup or via the check above), skip creation. Otherwise create it:

1. Show the exact role creation and wait for explicit customer confirmation. After approval, create the role with trust policy for `dms.amazonaws.com` (includes condition keys to prevent confused deputy):

   ```

   aws iam create-role \
     --role-name dms-vpc-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'

   ```

2. Show the exact managed-policy attachment and wait for separate explicit customer confirmation. After approval, attach the AWS managed policy:

   ```

   aws iam attach-role-policy \
     --role-name dms-vpc-role \
     --policy-arn arn:aws:iam::aws:policy/service-role/AmazonDMSVPCManagementRole

   ```

### 9d — DMS CloudWatch Logs Role

Required by DMS to publish schema conversion logs to CloudWatch. The role name MUST be exactly `dms-cloudwatch-logs-role`. See [IAM roles for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-roles) for details.

First check if the role exists:

```

aws iam get-role --role-name dms-cloudwatch-logs-role

```

If the role already exists (found in Phase 1 lookup or via the check above), skip creation. Otherwise create it:

1. Show the exact role creation and wait for explicit customer confirmation. After approval, create the role with trust policy for `dms.amazonaws.com` (includes condition keys to prevent confused deputy):

   ```

   aws iam create-role \
     --role-name dms-cloudwatch-logs-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'

   ```

2. Show the exact managed-policy attachment and wait for separate explicit customer confirmation. After approval, attach the AWS managed policy:

   ```

   aws iam attach-role-policy \
     --role-name dms-cloudwatch-logs-role \
     --policy-arn arn:aws:iam::aws:policy/service-role/AmazonDMSCloudWatchLogsRole

   ```

### 9e — S3 Access Role for Offline Source

**Skip this step if `source_mode = online` or `offline_s3_access_role_arn` is already set.**

Ask if an existing role is available. If yes, validate its trust policy and attached and inline permissions against the requirements below. If it is valid, store its ARN as `offline_s3_access_role_arn`. If it is not valid, explain the gaps and ask the customer to provide another role or create one.

Otherwise, create an IAM role allowing DMS to read DDL scripts from the customer's S3 bucket (the bucket from `ddl_s3_path`, NOT the migration artifacts bucket from Phase 8):

1. Show the exact role creation and wait for explicit customer confirmation. After approval, create the role with trust policy:

   ```

   aws iam create-role \
     --role-name <project_name>-sc-s3-access-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'

   ```

2. Show the exact S3 policy change and wait for separate explicit customer confirmation. After approval, attach the policy for the selected S3 location:

   - **If `ddl_prefix` is non-empty**, scope `s3:ListBucket` and `s3:GetObject` to that prefix:

     ```

     aws iam put-role-policy \
       --role-name <project_name>-sc-s3-access-role \
       --policy-name S3ReadAccess \
       --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::<ddl_bucket_name>","Condition":{"StringLike":{"s3:prefix":["<ddl_prefix>","<ddl_prefix>*"]}}},{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::<ddl_bucket_name>/<ddl_prefix>*"}]}'

     ```

   - **If `ddl_prefix` is empty**, omit the prefix condition and scope `s3:GetObject` to the bucket objects:

     ```

     aws iam put-role-policy \
       --role-name <project_name>-sc-s3-access-role \
       --policy-name S3ReadAccess \
       --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::<ddl_bucket_name>"},{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::<ddl_bucket_name>/*"}]}'

     ```

3. **If `s3_kms_key_arn` is set**, show the exact KMS policy change and wait for separate explicit customer confirmation. After approval, add KMS decrypt:

   ```

   aws iam put-role-policy \
     --role-name <project_name>-sc-s3-access-role \
     --policy-name KmsDecrypt \
     --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"kms:Decrypt","Resource":"<s3_kms_key_arn>","Condition":{"StringEquals":{"kms:ViaService":"s3.<aws_region>.amazonaws.com"}}}]}'

   ```

Store `offline_s3_access_role_arn`.

---

## Phase 10 — Create Instance Profile

**Goal:** Create the DMS instance profile that ties together the subnet group and security groups.

**If `source_mode = offline` AND `use_virtual_target = true`:**

```

aws dms create-instance-profile \
  --instance-profile-name <project_name>-instance-profile

```

**Otherwise:**

```

aws dms create-instance-profile \
  --instance-profile-name <project_name>-instance-profile \
  --subnet-group-identifier <subnet_group_identifier> \
  --vpc-security-groups <security_group_ids>

```

Store `instance_profile_arn` and `instance_profile_name`.

---

## Phase 11 — Transformation Rules (Optional)

You MUST ask the customer about transformation rules before proceeding to Phase 12:
> "Would you like to apply any transformation rules during conversion — such as renaming schemas, converting object names to uppercase/lowercase, or adding prefixes/suffixes? (yes / no)"

If yes, help them build the rules JSON. See [Transformation rules in DMS Schema Conversion](https://docs.aws.amazon.com/dms/latest/userguide/sc-transformation-rules.html) for format and options. Store as `transformation_rules`. If no, set to `null`.

---

## Phase 12 — Create Migration Project & Summary

### 12a — Create Migration Project

Build each descriptor from the provider's `Virtual` status verified in Phase 7c. Use the `migration_project_name` value stored in Phase 1.

- **Virtual provider:** Always include `DataProviderIdentifier`. Include `SecretsManagerSecretId` only when the customer explicitly supplied that value, and include `SecretsManagerAccessRoleArn` only when the customer explicitly supplied that value. Zero, one, or both optional fields are valid.
- **Non-virtual provider:** Include `DataProviderIdentifier`, `SecretsManagerSecretId`, and `SecretsManagerAccessRoleArn`. Both credential fields are required.

Build `source_data_provider_descriptors` and `target_data_provider_descriptors` as one-element lists. Verify each list against the provider's `Virtual` value, then pass the serialized lists as-is.

```

aws dms create-migration-project \
  --migration-project-name <migration_project_name> \
  --instance-profile-identifier <instance_profile_name> \
  --schema-conversion-application-attributes '{"S3BucketPath":"s3://<bucket_name>","S3BucketRoleArn":"<s3_role_arn>"}' \
  --source-data-provider-descriptors '<source_data_provider_descriptors_json>' \
  --target-data-provider-descriptors '<target_data_provider_descriptors_json>'
  [--transformation-rules '<json>' if not null]

```

Store `migration_project_arn` and `migration_project_name`.

### 12b — Verify

If `create-migration-project` returns an error, surface the error message to the customer and refer to [troubleshooting.md](troubleshooting.md) for diagnosis. Common sync errors include `AccessDeniedFault` (IAM permissions), `ResourceNotFoundFault` (instance profile or data provider not found), and `InvalidResourceStateFault`.

### 12c — Summary Table

| Resource | Name | ARN / ID |
|---|---|---|
| DMS Subnet Group | `<project_name>-subnet-group` | identifier |
| Instance Profile | `<project_name>-instance-profile` | ARN |
| Source Data Provider | `<project_name>-source` | ARN |
| Target Data Provider | `<project_name>-target` | ARN |
| Source Secret | required for online source / optional for offline source | ARN |
| Target Secret | required for live target / optional for virtual target | ARN |
| S3 Bucket | `<bucket_name>` | bucket name and SSE-S3/SSE-KMS mode |
| Secrets IAM Role | `<project_name>-sc-secrets-role` or existing, when required by a provider descriptor | ARN |
| S3 IAM Role | `<project_name>-sc-s3-role` or existing | ARN |
| Migration Project | `<migration_project_name>` | ARN |

Then inform the customer:
> "Setup complete."
