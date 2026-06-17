# DocumentDB — Migration Executor

End-to-end migration from MongoDB to DocumentDB using AWS DMS for data, the index tool for indexes, and manual steps for users/roles. Produces `artifacts/{app-name}/migration-plan.md`.

## What to ask upfront

- `app_name` (lowercase with hyphens)
- MongoDB source URI
- DocumentDB target endpoint, admin credentials, region
- Migration type: `full-load` or `full-load-and-cdc`

## Prerequisites

Check for the compatibility report first:

```bash
ls artifacts/<app-name>/compatibility-report.md 2>/dev/null || \
  echo "WARNING: Run the compatibility sub-skill first to identify blockers."
```

If missing, warn the user and ask whether to proceed.

## Workflow

### Step 1: Workload discovery

Run against MongoDB source via mongosh:

```javascript
// Counts per collection
db.getCollectionNames().forEach(c => print(c, db[c].countDocuments()))
// Data and index sizes
db.stats()
// Active indexes
db.getCollectionNames().forEach(c => db[c].getIndexes().forEach(i => printjson(i)))
// Index usage
db.getCollectionNames().forEach(c => db[c].aggregate([{ $indexStats: {} }]).forEach(printjson))
```

Record totals for the migration plan.

### Step 2: Index migration

```bash
# Export
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --dump-indexes --dir ./migration-index-export \
  --uri "mongodb://<user>:<pass>@<mongo-host>:27017"

# Check compatibility
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --show-issues --dir ./migration-index-export

# Dry run restore
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --restore-indexes --skip-incompatible --dry-run \
  --dir ./migration-index-export \
  --uri "mongodb://admin:<pw>@<docdb-endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&retryWrites=false"

# Actual restore
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --restore-indexes --skip-incompatible \
  --dir ./migration-index-export \
  --uri "mongodb://admin:<pw>@<docdb-endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&retryWrites=false"
```

Add `--shorten-index-name` for long names and `--support-2dsphere` for 2dsphere indexes. Record the count restored and any skipped.

### Step 3: Users and roles

DocumentDB built-in roles: `read`, `readWrite`, `dbAdmin`, `dbAdminAnyDatabase`, `readAnyDatabase`, `readWriteAnyDatabase`. Custom roles are not supported — map each MongoDB custom role to the nearest built-in.

```javascript
db.createUser({
  user: "<username>", pwd: "<password>",
  roles: [{ role: "readWrite", db: "<database>" }]
})
```

### Step 4: DMS setup (full load + CDC)

**4a. Security group.** DocumentDB SG must allow inbound TCP 27017 from the DMS replication instance's SG. Self-referencing rule if in the same SG:

```bash
DOCDB_SG=$(aws docdb describe-db-clusters --db-cluster-identifier <docdb-id> \
  --query 'DBClusters[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text --region <region>)
aws ec2 authorize-security-group-ingress \
  --group-id $DOCDB_SG --protocol tcp --port 27017 \
  --source-group $DOCDB_SG --region <region> 2>/dev/null || true
```

**4b. DMS replication subnet group** (must be in the same VPC as DocumentDB):

```bash
VPC_ID=$(aws docdb describe-db-instances --db-instance-identifier <docdb-inst> \
  --query 'DBInstances[0].DBSubnetGroup.VpcId' --output text --region <region>)
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text --region <region>)
aws dms create-replication-subnet-group \
  --replication-subnet-group-identifier <app>-migration-sg \
  --replication-subnet-group-description "MongoDB to DocumentDB" \
  --subnet-ids $SUBNET_IDS --region <region>
```

**4c. DMS replication instance:**

```bash
aws dms create-replication-instance \
  --replication-instance-identifier <app>-dms \
  --replication-instance-class dms.r5.large --allocated-storage 50 \
  --vpc-security-group-ids $DOCDB_SG \
  --replication-subnet-group-identifier <app>-migration-sg \
  --no-publicly-accessible --multi-az --region <region>
```

Poll `aws dms describe-replication-instances` until `ReplicationInstanceStatus=available`.

**4d. Import the RDS CA bundle into DMS** (once per region):

```bash
DMS_CERT_ARN=$(aws dms describe-certificates --region <region> \
  --query 'Certificates[?CertificateIdentifier==`global-bundle`].CertificateArn' --output text)
if [ -z "$DMS_CERT_ARN" ] || [ "$DMS_CERT_ARN" = "None" ]; then
  curl -s https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /tmp/global-bundle.pem
  DMS_CERT_ARN=$(aws dms import-certificate \
    --certificate-identifier global-bundle \
    --certificate-pem file:///tmp/global-bundle.pem --region <region> \
    --query 'Certificate.CertificateArn' --output text)
fi
```

**4e. Source endpoint (MongoDB):**

```bash
aws dms create-endpoint --endpoint-identifier <app>-source \
  --endpoint-type source --engine-name mongodb \
  --server-name <mongo-host> --port 27017 \
  --username <u> --password '<pw>' --database-name admin --region <region>
```

For production, keep credentials off the command line: replace `--username/--password` with `--mongo-db-settings` referencing a Secrets Manager secret — `'ServerName=<host>,Port=27017,DatabaseName=admin,SecretsManagerAccessRoleArn=<role-arn>,SecretsManagerSecretId=<secret-arn>'`. The role needs `secretsmanager:GetSecretValue` plus `iam:PassRole`.

**4f. Target endpoint (DocumentDB).** MUST use `--ssl-mode verify-full` with `--certificate-arn` — without TLS DMS hits socket timeouts:

```bash
aws dms create-endpoint --endpoint-identifier <app>-target \
  --endpoint-type target --engine-name docdb \
  --server-name <docdb-endpoint> --port 27017 \
  --username admin --password '<pw>' \
  --ssl-mode verify-full --certificate-arn $DMS_CERT_ARN \
  --database-name "" --region <region>
```

As with the source endpoint (4e), for production keep credentials off the command line by passing `--doc-db-settings` with `SecretsManagerSecretId` + `SecretsManagerAccessRoleArn` instead of `--username/--password`.

**4g. Test both endpoints** (DMS refuses to start a task without passing tests):

```bash
DMS_INSTANCE_ARN=$(aws dms describe-replication-instances \
  --filters Name=replication-instance-id,Values=<app>-dms \
  --query 'ReplicationInstances[0].ReplicationInstanceArn' --output text --region <region>)
SRC_ARN=$(aws dms describe-endpoints --filters Name=endpoint-id,Values=<app>-source \
  --query 'Endpoints[0].EndpointArn' --output text --region <region>)
TGT_ARN=$(aws dms describe-endpoints --filters Name=endpoint-id,Values=<app>-target \
  --query 'Endpoints[0].EndpointArn' --output text --region <region>)

aws dms test-connection --replication-instance-arn $DMS_INSTANCE_ARN \
  --endpoint-arn $SRC_ARN --region <region>
aws dms test-connection --replication-instance-arn $DMS_INSTANCE_ARN \
  --endpoint-arn $TGT_ARN --region <region>

# Poll both until successful
aws dms describe-connections \
  --filters Name=endpoint-arn,Values=$SRC_ARN,$TGT_ARN --region <region>
```

**4h. Migration task** — set `FailOnNoTablesCaptured: false` or the task fails fatally on an empty source:

```bash
TASK_ARN=$(aws dms create-replication-task \
  --replication-task-identifier <app>-migration \
  --source-endpoint-arn $SRC_ARN --target-endpoint-arn $TGT_ARN \
  --replication-instance-arn $DMS_INSTANCE_ARN \
  --migration-type full-load-and-cdc \
  --table-mappings '{"rules":[{"rule-type":"selection","rule-id":"1","rule-name":"include-all","object-locator":{"schema-name":"%","table-name":"%"},"rule-action":"include"}]}' \
  --replication-task-settings '{"TargetMetadata":{"SupportLobs":true,"FullLobMode":false,"LimitedSizeLobMode":true,"LobMaxSize":32},"FullLoadSettings":{"TargetTablePrepMode":"DO_NOTHING"},"ErrorBehavior":{"FailOnNoTablesCaptured":false},"Logging":{"EnableLogging":true}}' \
  --query 'ReplicationTask.ReplicationTaskArn' --output text --region <region>)
```

Wait for `Status=ready`, then start the task using the captured ARN:

```bash
aws dms start-replication-task \
  --replication-task-arn $TASK_ARN \
  --start-replication-task-type start-replication --region <region>
```

Default 32 KB LOB limit truncates larger documents — check the user's largest docs and adjust if needed.

### Step 5: Monitor

```bash
# Progress + CDC latency
aws dms describe-replication-tasks --filters Name=replication-task-arn,Values=$TASK_ARN \
  --query 'ReplicationTasks[0].{Status:Status,Progress:ReplicationTaskStats.FullLoadProgressPercent,CDCLatency:ReplicationTaskStats.CDCLatencySource}'
# Table-level errors
aws dms describe-table-statistics --replication-task-arn $TASK_ARN \
  --query 'TableStatistics[?TableState==`Table error`]'
```

### Step 6: Validation

Compare counts and sample documents on MongoDB and DocumentDB. Acceptable variance < 0.1% during active CDC.

### Step 7: Write the migration plan

`artifacts/{app-name}/migration-plan.md` — collections migrated with counts, indexes restored/skipped, users created, DMS task ARN + status, validation results, planned cutover time.

### Step 8: Cutover

Before switching traffic, complete every item:

#### Data & indexes

- Counts match within < 0.1% on all collections
- Sample docs from 3+ largest collections compare correctly
- All indexes exist on DocumentDB; incompatibles recreated with supported equivalents
- Top 5 queries show IXSCAN (not COLLSCAN) in `explain()`

#### Application

- Every blocker from compatibility report resolved in app code
- Connection string has all five required params (`tls`, `tlsCAFile`, `replicaSet`, `readPreference`, `retryWrites=false`)
- Staged run against DocumentDB with real traffic patterns completed

#### DMS

- Both endpoint tests pass (`successful`)
- CDC lag < 60 seconds, zero table errors, task in `Replication ongoing`

**Cutover steps (in order):**

1. Put app in maintenance mode (stop writes)
2. Wait for DMS CDC lag to reach 0 (`CDCLatencySource`)
3. Stop the DMS task
4. Final count check on both sides
5. Update app connection strings to the DocumentDB endpoint
6. Start the app, run smoke tests
7. Monitor CloudWatch for 15–30 minutes (`CPUUtilization`, `DatabaseConnections`)
8. Keep MongoDB read-only for 24–48 hours as rollback — do NOT write to it

**Rollback within 24–48 hours:** point app back at MongoDB, fix the issue in staging, re-plan cutover.
