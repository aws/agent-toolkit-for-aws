# Discovering Connections and Candidate Sources

Before creating a new Glue connection, check what exists and what the user has available in their account. Users often forget about previously registered connections or don't realize they already have running databases that can be registered.

## Contents

- [Existing Glue Connections](#existing-glue-connections)
- [RDS and Aurora Candidates](#rds-and-aurora-candidates)
- [Redshift Candidates](#redshift-candidates)
- [Presenting Candidates](#presenting-candidates)

## Existing Glue Connections

List all connections, optionally filtered by type:

```bash
# All connections
aws glue get-connections --region <REGION> --query 'ConnectionList[].{Name:Name,Type:ConnectionType,LastUpdated:LastUpdatedTimestamp}'

# Filter by type
aws glue get-connections --filter ConnectionType=JDBC --region <REGION>
aws glue get-connections --filter ConnectionType=SNOWFLAKE --region <REGION>
aws glue get-connections --filter ConnectionType=BIGQUERY --region <REGION>
```

Inspect a specific connection's properties (credentials are redacted in the response):

```bash
aws glue get-connection --name <NAME> --region <REGION>
```

If a connection matching the user's intent already exists, confirm with the user and skip creation. Re-test it (Step 7 of the skill) before handing off.

## RDS and Aurora Candidates

**RDS instances:**

```bash
aws rds describe-db-instances \
  --query 'DBInstances[].{Id:DBInstanceIdentifier,Endpoint:Endpoint.Address,Port:Endpoint.Port,Engine:Engine,DBName:DBName,VpcId:DBSubnetGroup.VpcId,Status:DBInstanceStatus,IAMAuth:IAMDatabaseAuthenticationEnabled}' \
  --region <REGION>
```

**Aurora clusters:**

```bash
aws rds describe-db-clusters \
  --query 'DBClusters[].{Id:DBClusterIdentifier,Endpoint:Endpoint,ReaderEndpoint:ReaderEndpoint,Port:Port,Engine:Engine,DatabaseName:DatabaseName,IAMAuth:IAMDatabaseAuthenticationEnabled}' \
  --region <REGION>
```

Prefer the Aurora reader endpoint for ETL reads to avoid impacting the writer. The reader endpoint is load-balanced across reader instances.

Note `IAMDatabaseAuthenticationEnabled: true` -- if set, recommend IAM DB auth over password per [credential-security.md](credential-security.md).

## Redshift Candidates

**Provisioned clusters:**

```bash
aws redshift describe-clusters \
  --query 'Clusters[].{Id:ClusterIdentifier,Endpoint:Endpoint.Address,Port:Endpoint.Port,DBName:DBName,VpcId:VpcId,IAMRoles:IamRoles[*].IamRoleArn,Status:ClusterStatus}' \
  --region <REGION>
```

**Serverless workgroups:**

```bash
aws redshift-serverless list-workgroups \
  --query 'workgroups[].{Name:workgroupName,Endpoint:endpoint.address,Port:endpoint.port,Status:status}' \
  --region <REGION>
```

## Presenting Candidates

When you find candidates, present them as a numbered list and let the user pick. Example:

```
I found these databases in your account. Which would you like to register?

1. RDS PostgreSQL: analytics-prod (analytics-prod.abc123.us-east-1.rds.amazonaws.com:5432, DB: analytics, IAM auth: enabled)
2. Aurora MySQL cluster: orders-writer (orders.cluster-abc123.us-east-1.rds.amazonaws.com, reader: orders.cluster-ro-abc123..., DB: orders)
3. Redshift: warehouse-prod (warehouse-prod.abc123.us-east-1.redshift.amazonaws.com:5439, DB: analytics)
4. None of these -- I want to register a source outside my account.
```

Never auto-select. The user may have multiple candidates or want to register a source that isn't visible to these discovery APIs (on-premises, peered account, Snowflake, BigQuery).

Snowflake and BigQuery sources are not discoverable via AWS APIs -- always ask the user for account/project details directly.
