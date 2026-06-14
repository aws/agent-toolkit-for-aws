# Aurora Express Configuration

## Overview

Express configuration is a single-API-call provisioning path for Aurora PostgreSQL. It creates an Aurora serverless cluster fronted by an AWS-managed connectivity layer (no customer VPC).

Use this sub-skill when the user asks about creating Aurora with express configuration, evaluating fit, or comparing express vs full. The `create` sub-skill routes here when express is the right default; route back to `create` for any workload needing a customer VPC, custom KMS, custom parameters, or Aurora MySQL.

Execute commands via the AWS MCP server when connected (sandboxed, audit-logged). Fall back to the AWS CLI or shell otherwise.

## Workflow

### 1. Determine fit

Express is the right default for Aurora PostgreSQL when ALL of these are true:

- Engine is PostgreSQL (not MySQL)
- The application can use AWS-managed connectivity (no customer VPC required)
- AWS owned key (SSE-RDS) for encryption at rest is acceptable (no customer-managed KMS)
- Default cluster parameter group is acceptable
- Default min/max ACU range is acceptable

If any fail, route to full configuration. Load [use-cases.md](express-create-use-cases.md) for canonical scenarios on either side of the boundary.

### 2. Acquire parameters

Required: cluster identifier, region. Optional: anything else the user supplies (most defaults cannot be overridden in express).

### 3. Confirm before creating

State the configuration explicitly for confirmation. MUST surface:

- Aurora serverless (not provisioned)
- AWS-managed connectivity (internet access gateway, no customer VPC)
- AWS owned key (SSE-RDS) for encryption at rest
- Default ACU range (verify in AWS User Guide for current value)

Wait for explicit confirmation ("yes", "proceed", "confirmed").

### 4. Execute via single API call

Express is one API call. Use the AWS CLI as the primary path (the `--with-express-configuration` flag requires AWS CLI v2.33+); fall back to the boto3 SDK only if the environment has an older CLI.

**AWS CLI (primary — requires v2.33+):**

```bash
aws rds create-db-cluster \
  --db-cluster-identifier <cluster-id> \
  --engine aurora-postgresql \
  --with-express-configuration \
  --region <region> \
  --tags Key=created_by,Value=aurora-skill Key=generation_model,Value=<your-model-id>
```

**boto3 (alternative — for environments with AWS CLI older than v2.33):**

```python
import boto3
client = boto3.client("rds", region_name="<region>")
client.create_db_cluster(
    DBClusterIdentifier="<cluster-id>",
    Engine="aurora-postgresql",
    WithExpressConfiguration=True,
    Tags=[
        {"Key": "created_by", "Value": "aurora-skill"},
        {"Key": "generation_model", "Value": "<your-model-id>"},
    ],
)
```

If the CLI returns `Unknown options: --with-express-configuration`, the installed version is too old — update the CLI (`aws --version` should show 2.33+) or use the boto3 fallback above.

Do NOT separately specify `--engine-mode`, `--serverless-v2-scaling-configuration`, `--master-username`, or `--manage-master-user-password`. The express flag sets all of these automatically.

### 5. Post-creation: enable CloudWatch log exports

After the cluster is available, enable PostgreSQL log export to CloudWatch for operational visibility:

```bash
aws rds modify-db-cluster --db-cluster-identifier <cluster-id> --region <region> \
  --cloudwatch-logs-export-configuration '{"EnableLogTypes":["postgresql"]}'
```

These logs can contain sensitive data (query text, table/column names), so ensure the CloudWatch log group is encrypted (KMS) and access-restricted, and treat the logs as sensitive when sharing.

### 6. Connect using IAM authentication

**Express clusters use IAM-only authentication via the Internet Access Gateway. There is no master password.** When the user asks how to connect or run SQL, walk them through the IAM auth token flow — do NOT offer to run SQL yourself, suggest the Data API as a workaround, or try to set a master password. The skill creates the cluster and provides the connection workflow; it does NOT execute SQL.

Full workflow (wait-for-available, IAM token generation, Data API caveats, adding users): see [connect-iam.md](express-create-connect-iam.md).

## Response requirements

When explaining what express IS or proposing it for a new cluster, you MUST include ALL of:

1. State that it provisions an **Aurora serverless** cluster (not just "Aurora" or "Aurora PostgreSQL")
2. Mention the **internet access gateway** as the connectivity mechanism (no customer VPC)
3. State that the cluster will be **ready in seconds**
4. Cite the AWS User Guide page (`https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html`)
5. MUST NOT claim Aurora MySQL is supported in express configuration
6. State that authentication is **IAM-only** — no master password.
7. **Name the connection command explicitly.** When you mention how the user connects after creation, you MUST name the literal command `aws rds generate-db-auth-token` — required even on a create/propose turn. "Connect using a short-lived IAM auth token" alone is INCOMPLETE; it must be paired with the `aws rds generate-db-auth-token` command name.

## Constraints

- MUST NOT use express for Aurora MySQL — it is PostgreSQL-only
- MUST NOT use express when the user requires a customer VPC, customer-managed KMS, or custom parameter group
- MUST NOT enumerate AWS regions inline — point users to the AWS User Guide for regional availability and for verifying current behavior before production decisions
- MUST execute with `--with-express-configuration` flag, not by composing individual `--engine-mode` / `--serverless-v2-scaling-configuration` flags
- MUST NOT promise to execute SQL against the cluster — the skill provisions and walks through the IAM connection flow; the user runs SQL themselves
- MUST NOT suggest setting a master password / `--manage-master-user-password`, or recommend the Data API as a workaround for connection issues — express is IAM-only (see section 6). Data API is out of scope for the connect flow; only mention it if the user explicitly asks.

## Routing back to full configuration

When any of these appear, route to the `create` sub-skill (full configuration):

- VPC, subnet group, security group, or any customer networking
- Customer-managed KMS key
- Custom cluster parameter group
- Specific engine version (express uses the AWS default)
- Aurora MySQL
- Provisioned instance class (express is Aurora serverless only)

Load [comparison.md](express-create-comparison.md) for a side-by-side feature matrix.

## Reference files

- [connect-iam.md](express-create-connect-iam.md) — Full IAM-auth connection workflow (token generation, Data API caveats, adding users)
- [feature-overview.md](express-create-feature-overview.md) — AWS-managed connectivity, multi-AZ routing, preconfigured defaults
- [constraints.md](express-create-constraints.md) — Full constraint catalog with AWS doc citations (engine, networking, capacity, storage, security, feature incompatibilities)
- [comparison.md](express-create-comparison.md) — Express vs full side-by-side
- [use-cases.md](express-create-use-cases.md) — Canonical scenarios that fit (or don't) express
- [migration.md](express-create-migration.md) — Migrating between express and full configuration
- [documentation-links.md](express-create-documentation-links.md) — Curated AWS doc links

## Source documentation

- [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html) — primary reference
- [Aurora serverless](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html)
- [Aurora PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html)
