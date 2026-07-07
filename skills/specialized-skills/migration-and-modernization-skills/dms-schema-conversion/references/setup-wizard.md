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
- You MUST present one phase at a time — do NOT ask for all parameters at once
- You MUST confirm each resource was created successfully before moving to the next phase
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
- After the customer provides a name, you MUST check for existing resources that would be created under that prefix. Run all of the following lookups and present a consolidated summary before proceeding:

  ```
  aws dms describe-migration-projects --filters Name=migration-project-identifier,Values=<project_name>-migration-project
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
  | Migration Project `<project_name>-migration-project` | EXISTS / will be created |
  | Instance Profile `<project_name>-instance-profile` | EXISTS / will be created |
  | Subnet Group `<project_name>-subnet-group` | EXISTS / will be created |
  | Source Data Provider `<project_name>-source` | EXISTS / will be created |
  | Target Data Provider `<project_name>-target` | EXISTS / will be created |
  | S3 Bucket `<project_name>-sc-bucket-<aws_account_id>-<aws_region>` | EXISTS / will be created |
  | Secrets IAM Role `<project_name>-sc-secrets-role` | EXISTS / will be created |
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

**Supported target engines:** `aurora-postgresql`, `mysql`, `aurora-mysql`, `redshift`, `mariadb`, `postgresql`. See [DMS SC supported target databases](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-target.html) for the full list.

**Constraints:**

- Accept `live` or `virtual` (case-insensitive); store as `use_virtual_target`
- **If live:** Ask for the target engine type (e.g., `aurora-postgresql`, `mysql`, `redshift`). Then ask:
  > "Is your target an Amazon RDS/Aurora instance or Redshift cluster? If yes, provide the ARN and I'll retrieve connection details automatically. Otherwise, provide hostname, port, database name."

  - **If ARN provided:** Call `aws rds describe-db-instances` (or `describe-db-clusters` for Aurora, or `aws redshift describe-clusters` for Redshift) to fetch `target_hostname`, `target_port`, and `target_database_name`. Also extract `target_vpc_id`, `target_subnet_ids`, and `target_security_group_ids` from the instance/cluster metadata. Inform the customer of what was found.
  - **If no ARN:** Ask for the target database connection info (hostname, port, database name). Also ask for the VPC ID, subnet IDs, and security group IDs associated with the target.

  Store as `target_engine`, `target_hostname`, `target_port`, `target_database_name`, `target_vpc_id`, `target_subnet_ids`, `target_security_group_ids`.
- **If virtual:** Ask for the target engine type (e.g., `aurora-postgresql`, `mysql`, `redshift`). Store as `target_engine`.

---

## Phase 3 — Source Database

**Goal:** Collect source engine and connection details.

### 3a — Source type

Ask for source engine. Supported source engines: `sqlserver`, `oracle`, `mysql`, `postgresql`, `db2-luw`, `db2-zos`, `sybase`. See [DMS SC supported source databases](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Introduction.Sources.html#CHAP_Introduction.Sources.SchemaConversion) for the full list. The customer may provide the engine name in any format — map it to the correct API identifier automatically.

### 3b — Source mode (online / offline)

**If source engine is `sqlserver`**, ask:
> "Would you like to connect directly to the source database (online mode), or use exported DDL scripts from S3 (offline mode)?
>
> - **Online** — DMS connects to your database to read metadata directly.
> - **Offline** — DMS reads metadata from DDL scripts you've uploaded to S3. No database connectivity required."

Store as `source_mode` (`online` or `offline`).

**If offline:** Proceed to [Phase 3d — Offline Source Configuration](#3d--offline-source-configuration).

**If source engine is NOT `sqlserver`**, set `source_mode = online` (offline is available only for SQL Server).

### 3c — Source connection (online mode only)

**Skip this step if `source_mode = offline`.**

Ask for hostname, port, and database name in a single prompt. If the source is an RDS instance, offer to look up the connection details automatically:
> "Is your source database an RDS instance? If yes, provide the RDS instance ARN or identifier and I'll retrieve the connection details automatically. Otherwise, please provide the hostname, port, and database name."

- **If RDS source:** Call `aws rds describe-db-instances` (or `describe-db-clusters` for Aurora) to fetch `source_hostname`, `source_port`, and `source_database_name`. Inform the customer of what was found.
- **If not RDS:** Ask for hostname, port, and database name directly.

Store as `source_hostname`, `source_port`, `source_database_name`.

### 3d — Offline source configuration

**Skip this step if `source_mode = online`.**

#### Step 1 — DDL Scripts (Offline Source)

Ask:
> "What is the current state of your DDL scripts?
>
> 1. Already exported and uploaded to S3
> 2. Already exported but not yet uploaded to S3
> 3. Not yet exported — I'd like help"

**Option 1 (exported + uploaded):** Proceed to Step 2.

**Option 2 (exported, not uploaded):** Ask for the local path and target S3 bucket. Upload using:

```
aws s3 sync <local_path>/ s3://<bucket>/<database_name>/ --sse AES256
```

Verify upload: `aws s3 ls s3://<bucket>/<database_name>/ --recursive | head -10`. Proceed to Step 2.

**Option 3 (not exported):** Ask:
> "Would you like me to extract the DDL scripts from your database via CLI, or would you prefer to do it yourself?"

- **Agent extracts (with customer permission):** Read [Export SQL Server database objects](https://docs.aws.amazon.com/dms/latest/userguide/export-sql-server-database-objects.html) for the CLI extraction approach. Then:
  1. Ask for database connection details (hostname, port, database name). For credentials, ask if they are stored in AWS Secrets Manager (provide the secret ARN) or provide directly — credentials will not be logged or persisted.
  2. Verify the customer's environment has the required tools (PowerShell, `SqlServer` PowerShell module — provides SQL Server Management Objects for scripting database objects). If not, guide installation: `Install-Module SqlServer`.
  3. Generate the PowerShell SMO export script configured for the customer's database, following the settings and approach from the user guide.
  4. Ask the customer for permission to execute the script on their machine. If granted, run it via CLI. If not, provide the script for the customer to run manually.
  5. After extraction completes, upload results to S3 with `aws s3 sync <output_dir>/ s3://<bucket>/<database_name>/ --sse AES256`.
  6. Proceed to Step 2.

- **Customer extracts:** Provide the link: [Export SQL Server database objects](https://docs.aws.amazon.com/dms/latest/userguide/export-sql-server-database-objects.html). Inform the customer about the DDL structure requirements (below) and wait for them to complete. Then ask whether scripts are uploaded to S3 (→ Option 1) or need uploading (→ Option 2).

**DDL structure requirements** (inform customer if they export themselves):

- One SQL file per database object
- Each file contains exactly one `CREATE` statement
- `USE [DatabaseName];` at the top of each file
- All objects for one database under a single S3 prefix
- No DML or DROP statements

#### Step 2 — S3 Configuration (Offline Source)

1. **S3 path:** Ask:
   > "Please provide the S3 path to your DDL scripts (e.g., `s3://my-bucket/MyDatabase/`)."

   Store as `ddl_s3_path`.

2. **Verify S3 content:** List objects to confirm scripts are present:

   ```
   aws s3 ls <ddl_s3_path> --recursive | head -10
   ```

   If empty or path not found, inform the customer and ask to correct.

3. **S3 access role:** Ask:
   > "Do you have an IAM role that grants DMS read access to this S3 bucket? If yes, provide the ARN. If no, I'll create one."

   - **If provided:** Validate with `aws iam get-role`. Store as `offline_s3_access_role_arn`.
   - **If not provided:** Create the role in [Phase 9e](#9e--s3-access-role-for-offline-source).

4. **KMS encryption (optional):** Ask:
   > "Are the S3 objects encrypted with a customer-managed KMS key? (yes / no)"

   - **If yes:** Ask for the KMS key ARN. Store as `s3_kms_key_arn`.
   - **If no:** No additional configuration needed.

#### Step 3 — Prepare Source Data Provider Settings (Offline Source)

Store the following for use in Phase 7a:

```
source_engine = "sqlserver"
source_mode = "offline"
source_settings = {
  "MicrosoftSqlServerSettings": {
    "ServerName": "offline",
    "Port": 1433,
    "DatabaseName": "offline",
    "SslMode": "none",
    "S3Path": "<ddl_s3_path>",
    "S3AccessRoleArn": "<offline_s3_access_role_arn>"
  }
}
```

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

Ask if the customer needs help setting up source database credentials. Guide the customer based on [source data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-source.html) for required permissions.

Ask for the Secrets Manager secret ARN containing the source database credentials:
> "Please provide the ARN of the Secrets Manager secret with your source database username and password. If your source is an RDS instance, you can find the secret in the RDS console under 'Connectivity & security'."

**Important:** The secret must contain a JSON with keys `username` and `password`. Warn the customer that the RDS-managed admin secret has extensive privileges that Schema Conversion does not need. Recommend creating a dedicated database user with minimal required permissions. See [required permissions](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-source.html) for the full list.

Store as `source_secret_arn`.

### 6b — Target credentials

Ask if the customer needs help setting up target database credentials. Guide the customer based on [target data provider prerequisites](https://docs.aws.amazon.com/dms/latest/userguide/data-providers-target.html) for required permissions.

**If virtual target:** A secret is still required by DMS even though it won't be used for an actual connection. Create a placeholder secret automatically (the password is non-sensitive — used only to satisfy the API schema requirement):

```
aws secretsmanager create-secret \
  --name <project_name>-target-dummy-secret \
  --secret-string '{"username":"virtual_placeholder","password":"'"$(openssl rand -base64 16)"'"}'
```

On `ResourceExistsException`, reuse the existing secret. Store the ARN as `target_secret_arn`.

**If live target (RDS/Aurora/Redshift):** If the customer provided an ARN in Phase 2, automatically retrieve the associated secret ARN from the instance/cluster metadata (e.g., `MasterUserSecret.SecretArn` from `describe-db-instances` or `describe-db-clusters`). Inform the customer of the secret found. If no secret is associated with the instance, fall back to asking manually.

**If live target (other or manual):** Ask:
> "Please provide the ARN of the Secrets Manager secret with your target database username and password."

**Important:** Warn the customer that managed admin secrets have extensive privileges that Schema Conversion does not need. Recommend creating a dedicated database user with minimal required permissions and storing those credentials in a separate secret.

Store as `target_secret_arn`.

---

## Phase 7 — Create Data Providers

**Goal:** Register source and target data providers in DMS.

### 7a — Source data provider

Use the settings prepared in Phase 3c (online) or Phase 3d (offline). See [create-data-provider CLI reference](https://docs.aws.amazon.com/cli/latest/reference/dms/create-data-provider.html) for engine-specific settings structures.

```
aws dms create-data-provider \
  --data-provider-name <project_name>-source \
  --engine <source_engine> \
  [--virtual] \
  --settings '<source_settings>'
```

Pass `--virtual` only if `source_mode = offline`.

Store `source_data_provider_arn`. Do NOT include credentials in settings.

**SSL/TLS:** For offline mode, SslMode is already set to `"none"` in the prepared settings — do NOT ask the customer. For online mode, ask the customer which SSL mode to use for the database connection (e.g., `none`, `require`, `verify-ca`, `verify-full`). Recommend `require` or higher for encryption in transit. Set the `SslMode` field in the data provider settings accordingly.

### 7b — Target data provider

- **If virtual target:** Use placeholder settings matching `target_engine` (use `"virtual"` as the server name and the default port for the engine). You MUST also pass `--virtual` to mark the data provider as virtual:

  ```
  aws dms create-data-provider \
    --data-provider-name <project_name>-target \
    --engine <target_engine> \
    --virtual \
    --settings '{...placeholder settings...}'
  ```

- **If live target:** Use the actual connection values from Phase 2 (`target_hostname`, `target_port`, `target_database_name`). Use the same engine-specific settings structure as the source data provider (e.g., `AuroraPostgreSqlSettings`, `MySqlSettings`, `RedshiftSettings`, etc.) with the real values. Do NOT pass `--virtual`.

Store `target_data_provider_arn`.

---

## Phase 8 — S3 Bucket

**Goal:** Ensure an S3 bucket exists for migration artifacts.

Ask if the customer has an existing bucket. If yes, validate with `aws s3api head-bucket`. If no, create `<project_name>-sc-bucket-<aws_account_id>-<aws_region>`.

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
- Do NOT configure SSE-KMS — DMS Schema Conversion only supports SSE-S3 (default)
- Store `bucket_name`

---

## Phase 9 — IAM Roles

**Goal:** Create IAM roles: Secrets Manager access role, S3 access role, DMS VPC role, and DMS CloudWatch Logs role.

### 9a — Secrets Manager Role

Ask if an existing role is available. If yes, validate with `aws iam get-role`. If no, create:

1. Create the role with trust policy (includes condition keys to prevent confused deputy):

   ```
   aws iam create-role \
     --role-name <project_name>-sc-secrets-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'
   ```

2. Attach a policy granting access to the secret ARNs used by the migration project. See [IAM policies for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-policies) for the required permissions (Secrets Manager and KMS actions). Scope the resource to `<source_secret_arn>` and `<target_secret_arn>`.

Store `secrets_role_arn`.

### 9b — S3 Role

Ask if an existing role is available. If yes, validate. If no, create:

1. Create the role with trust policy (includes condition keys to prevent confused deputy):

   ```
   aws iam create-role \
     --role-name <project_name>-sc-s3-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'
   ```

2. Attach a policy granting S3 access to the migration bucket. See [IAM policies for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-policies) for the required permissions. Scope the resource to `arn:aws:s3:::<bucket_name>` and `arn:aws:s3:::<bucket_name>/*`.

Store `s3_role_arn`.

### 9c — DMS VPC Role

Required by DMS to manage VPC and ENI resources. The role name MUST be exactly `dms-vpc-role` — DMS looks it up by this fixed name. See [IAM roles for DMS](https://docs.aws.amazon.com/dms/latest/userguide/set-up.html#set-up-iam-roles) for details.

First check if the role exists:

```
aws iam get-role --role-name dms-vpc-role
```

If the role already exists (found in Phase 1 lookup or via the check above), skip creation. Otherwise create it:

1. Create the role with trust policy for `dms.amazonaws.com` (includes condition keys to prevent confused deputy):

   ```
   aws iam create-role \
     --role-name dms-vpc-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'
   ```

2. Attach the AWS managed policy:

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

1. Create the role with trust policy for `dms.amazonaws.com` (includes condition keys to prevent confused deputy):

   ```
   aws iam create-role \
     --role-name dms-cloudwatch-logs-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'
   ```

2. Attach the AWS managed policy:

   ```
   aws iam attach-role-policy \
     --role-name dms-cloudwatch-logs-role \
     --policy-arn arn:aws:iam::aws:policy/service-role/AmazonDMSCloudWatchLogsRole
   ```

### 9e — S3 Access Role for Offline Source

**Skip this step if `source_mode = online` or the customer already provided `offline_s3_access_role_arn` in Phase 3d.**

Create an IAM role allowing DMS to read DDL scripts from the customer's S3 bucket (the bucket from `ddl_s3_path`, NOT the migration artifacts bucket from Phase 8):

1. Create the role with trust policy:

   ```
   aws iam create-role \
     --role-name <project_name>-sc-s3-access-role \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"dms.amazonaws.com"},"Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"<aws_account_id>"},"ArnLike":{"aws:SourceArn":"arn:aws:dms:<aws_region>:<aws_account_id>:*"}}}]}'
   ```

2. Attach S3 read policy scoped to the DDL scripts bucket (extract bucket name from `ddl_s3_path`):

   ```
   aws iam put-role-policy \
     --role-name <project_name>-sc-s3-access-role \
     --policy-name S3ReadAccess \
     --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::<ddl_bucket_name>"},{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::<ddl_bucket_name>/*"}]}'
   ```

3. **If `s3_kms_key_arn` is set**, add KMS decrypt:

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

Ask if the customer wants transformation rules (rename schemas, tables, columns). If yes, help them build the rules JSON. See [Transformation rules in DMS Schema Conversion](https://docs.aws.amazon.com/dms/latest/userguide/sc-transformation-rules.html) for format and options. Store as `transformation_rules`. If no, set to `null`.

---

## Phase 12 — Create Migration Project & Summary

### 12a — Create Migration Project

Build source descriptor (always includes secret):

- `{"DataProviderIdentifier": "<source_data_provider_arn>", "SecretsManagerSecretId": "<source_secret_arn>", "SecretsManagerAccessRoleArn": "<secrets_role_arn>"}`

Build target descriptor (always includes secret):

- `{"DataProviderIdentifier": "<target_data_provider_arn>", "SecretsManagerSecretId": "<target_secret_arn>", "SecretsManagerAccessRoleArn": "<secrets_role_arn>"}`

```
aws dms create-migration-project \
  --migration-project-name <project_name>-migration-project \
  --instance-profile-identifier <instance_profile_name> \
  --schema-conversion-application-attributes '{"S3BucketPath":"s3://<bucket_name>","S3BucketRoleArn":"<s3_role_arn>"}' \
  --source-data-provider-descriptors '[{"DataProviderIdentifier":"<source_data_provider_arn>","SecretsManagerSecretId":"<source_secret_arn>","SecretsManagerAccessRoleArn":"<secrets_role_arn>"}]' \
  --target-data-provider-descriptors '[{"DataProviderIdentifier":"<target_data_provider_arn>","SecretsManagerSecretId":"<target_secret_arn>","SecretsManagerAccessRoleArn":"<secrets_role_arn>"}]'
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
| Source Secret | customer-provided | ARN |
| Target Secret | customer-provided | ARN |
| S3 Bucket | `<bucket_name>` | bucket name |
| Secrets IAM Role | `<project_name>-sc-secrets-role` or existing | ARN |
| S3 IAM Role | `<project_name>-sc-s3-role` or existing | ARN |
| Migration Project | `<project_name>-migration-project` | ARN |

Then inform the customer:
> "Setup complete."
