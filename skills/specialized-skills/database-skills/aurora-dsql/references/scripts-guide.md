# Aurora DSQL Scripts

Bash scripts for common Aurora DSQL cluster management and connection operations.
These scripts can be executed directly, used as agent tools, or configured as hooks.

## Prerequisites

- AWS CLI configured with credentials (`aws configure`)
- `psql` client installed (for psql-connect.sh)
- `jq` installed (for JSON parsing)
- Appropriate IAM permissions:
  - `dsql:CreateCluster` (for create-cluster.sh)
  - `dsql:DeleteCluster` (for delete-cluster.sh)
  - `dsql:GetCluster` (for cluster-info.sh)
  - `dsql:ListClusters` (for list-clusters.sh)
  - `dsql:DbConnect` or `dsql:DbConnectAdmin` (for psql-connect.sh)

## Using Scripts as Tools

Agents can execute these scripts directly via shell tool calls. Each script supports `--help` for usage:

```bash
# List available clusters
./scripts/list-clusters.sh --region us-east-1

# Get cluster details
./scripts/cluster-info.sh abc123def456

# Connect and run a query
./scripts/psql-connect.sh --cluster abc123def456 --command "SELECT COUNT(*) FROM entities"
```

## Available Scripts

### create-cluster.sh

Create a new Aurora DSQL cluster.

```bash
./scripts/create-cluster.sh --created-by claude-opus-4-6
./scripts/create-cluster.sh --created-by claude-opus-4-6 --region us-east-1
./scripts/create-cluster.sh --created-by claude-opus-4-6 --region us-west-2 --tags Environment=dev,Project=myapp
```

**Output:** Cluster identifier, endpoint, and ARN. Exports environment variables for use with other scripts.

---

### delete-cluster.sh

Delete an existing Aurora DSQL cluster.

```bash
./scripts/delete-cluster.sh abc123def456
./scripts/delete-cluster.sh abc123def456 --region us-west-2
./scripts/delete-cluster.sh abc123def456 --force
```

**Note:** Deletion is permanent and cannot be undone.

---

### psql-connect.sh

Connect to Aurora DSQL using psql with automatic IAM authentication.

```bash
# Pass the cluster id as a positional arg, --cluster flag, or via $CLUSTER:
./scripts/psql-connect.sh abc123def456 --region us-west-2
./scripts/psql-connect.sh --cluster abc123def456 --region us-west-2

# Single-statement command (one trailing semicolon allowed; no statement chaining):
./scripts/psql-connect.sh --cluster abc123def456 --command "SELECT * FROM entities LIMIT 5"

# Multi-statement file (BEGIN/COMMIT, multiple SET LOCAL, migrations, etc.):
./scripts/psql-connect.sh --cluster abc123def456 --script ./migration.sql

# DDL / role grants (IAM admin auth token):
./scripts/psql-connect.sh --cluster abc123def456 --admin --command "CREATE TABLE ..."

# Connection-tracking tag for the model that issued the queries:
./scripts/psql-connect.sh --cluster abc123def456 --ai-model claude-opus-4-6
```

**Features:**

- Automatically generates IAM auth token (valid for 15 minutes); use `--admin` for `dsql:DbConnectAdmin`
- Supports interactive sessions, single-statement `--command`, and multi-statement `--script` files
- Defaults to `sslmode=verify-full` against the OS trust store (`PGSSLROOTCERT=system`)
- Uses `admin` user by default (override with `--user` or `$DB_USER`)
- `--ai-model MODEL_ID` appends model identifier to PostgreSQL `application_name` for connection tracking
- `--skip-cert-verify` downgrades to `sslmode=require` (encrypt only — vulnerable to MITM; do NOT use in production)

---

### list-clusters.sh

List all Aurora DSQL clusters in a region.

```bash
./scripts/list-clusters.sh
./scripts/list-clusters.sh --region us-west-2
```

---

### cluster-info.sh

Get detailed information about a specific cluster.

```bash
./scripts/cluster-info.sh abc123def456
./scripts/cluster-info.sh abc123def456 --region us-west-2
```

**Output:** JSON with cluster identifier, endpoint, ARN, status, and creation time.

---

### Bulk data loading

Bulk loading is not bundled in this skill. For supported file formats, install instructions, and
loader options, see the official AWS guide:
[Loading data into Aurora DSQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/loading-data.html).

---

## Python Helpers

Two Python modules under `scripts/` back Workflow 4a (Rubric-Critical SQL construction):

### safe_query.py

Builds DSQL SQL strings with validator-enforced interpolation — the canonical defense against
SQL injection on raw-SQL paths (`psql -c`, shell pipelines, dynamic identifiers). See
[input-validation.md](input-validation.md) for the full pattern.

Built-in regex patterns: `TENANT_SLUG`, `UUID`, `INT`, `ISO_DATE`. Validators: `allow`, `regex`,
`ident`, `keyword`, `integer`, `literal`. Raises `UnsafeSQLError` on raw-string interpolation.

**Smoke test (recommended after edits):**

```bash
python3 scripts/safe_query.py    # runs the embedded _selftest()
# Expected: "safe_query self-test passed"
```

### tenant_query.py

Demonstrates the canonical multi-tenant `SELECT` pattern using `safe_query.build()` + a
driver-supplied cursor. Illustrative example, not a runtime dependency — useful as a template
when building tenant-scoped queries in application code.

---

## Environment Variables

Scripts respect these environment variables:

- `CLUSTER` - Default cluster identifier
- `REGION` - Default AWS region
- `AWS_REGION` - Fallback AWS region if `REGION` not set
- `DB_USER` - Default database user (defaults to 'admin')
- `AWS_PROFILE` - AWS CLI profile to use

## Quick Start Workflow

```bash
# 1. Create a cluster
./scripts/create-cluster.sh --created-by claude-opus-4-6 --region us-east-1

# Copy the export commands from output
export CLUSTER=abc123def456
export REGION=us-east-1

# 2. Connect with psql
./scripts/psql-connect.sh

# 3. Inside psql, create a table
CREATE TABLE entities (
  entity_id VARCHAR(255) PRIMARY KEY,
  tenant_id VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL
);

# 4. Exit psql and run a query from command line
./scripts/psql-connect.sh --command "SELECT * FROM information_schema.tables WHERE table_schema='public'"

# 5. When done, delete the cluster
./scripts/delete-cluster.sh $CLUSTER
```

## Notes

- **Token Expiry:** IAM auth tokens expire after 15 minutes.
- **Connection Limit:** DSQL supports up to 10,000 concurrent connections per cluster.
- **Database Name:** Always use `postgres` (only database available in DSQL).
