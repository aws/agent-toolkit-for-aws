# DocumentDB — Troubleshooting

Expanded troubleshooting reference for issues beyond the SKILL.md summary. Grouped by failure class.

## Authentication and credentials

**`AccessDenied` / `UnauthorizedOperation`.** Caller lacks permissions for DocumentDB, DMS, CloudWatch, EC2, or Secrets Manager. Attach `AmazonDocDBReadOnlyAccess` + `CloudWatchReadOnlyAccess` for read-only flows. For migration add `AmazonDMSVPCManagementRole` and scoped write actions. Do NOT grant admin as a workaround.

**`ExpiredToken` / `RequestExpired`.** Refresh your credentials (e.g. `aws sso login`, or renew the credentials for your configured profile) and verify with `aws sts get-caller-identity`, then retry.

## Connectivity

**Connection refused / timeout on port 27017.** DocumentDB is VPC-only (no public endpoint). Run `aws ec2 describe-security-groups --group-ids <sg>` — the DocumentDB SG needs inbound TCP 27017 from the client SG. Reference by SG id, not CIDR. From outside the VPC use CloudShell VPC environment, EC2 in the VPC, or SSH tunnel via bastion.

**TLS handshake failed / certificate verify failed.** Download the RDS global bundle: `curl -s https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o global-bundle.pem`. Verify the `tlsCAFile` path matches where the cert actually is. When tunneling, pass `--tlsAllowInvalidHostnames` to mongosh because the hostname resolves to `127.0.0.1`, not the cluster endpoint.

**`Server selection timed out after 30000ms`.** TLS cert at wrong path, or endpoint unreachable. Verify cert path and run `nc -zv <endpoint> 27017` from the client network.

**`getaddrinfo failed`.** Wrong endpoint. Run `aws docdb describe-db-clusters --db-cluster-identifier <name> --query 'DBClusters[*].[Endpoint,Port]'` to get the correct endpoint.

## Driver behavior

**"not master" / "not primary".** Missing `replicaSet=rs0` in the connection string. DocumentDB always uses `rs0`.

**Intermittent write errors under load.** Missing `retryWrites=false`. DocumentDB does not support retryable writes — drivers default to `true`.

**Java driver only connects to primary.** Using `applyToClusterSettings` with a single host sets mode to SINGLE and breaks failover. Use `applyConnectionString` instead — see `references/connection-drivers.md`.

**Connection storm / `DatabaseConnections` spike.** Creating `MongoClient` per request skips connection pooling. Create the client once at module scope (Lambda: outside the handler) and reuse across requests.

**Cursor timeout / `CursorNotFound`.** Idle cursors close after 10 minutes. Process results faster, add early `$match`/`$limit` to reduce set size, or use `noCursorTimeout` sparingly. `cursor.maxTimeMS` resets on each `getMore` — DocumentDB differs from MongoDB here.

## DMS

**DMS task refuses to start — "Test connection should be successful".** DMS requires explicit `aws dms test-connection` calls that pass for both source and target endpoints before starting a task. Call `test-connection` for each endpoint, then poll `describe-connections` until both return `successful`:

```bash
aws dms describe-connections \
  --filters Name=endpoint-arn,Values=<src-arn>,<tgt-arn> \
  --region <region>
```

**DMS target endpoint socket timeout.** Target endpoint MUST use `--ssl-mode verify-full` with `--certificate-arn` pointing to the RDS global bundle imported into DMS. Without TLS, DocumentDB rejects the connection.

Import the RDS bundle into DMS if missing:

```bash
curl -s https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /tmp/global-bundle.pem
aws dms import-certificate \
  --certificate-identifier global-bundle \
  --certificate-pem file:///tmp/global-bundle.pem \
  --region <region>
```

Also verify the DocumentDB SG allows inbound TCP 27017 from the DMS replication instance's SG (self-referencing rule if in same SG, or cross-SG rule).

**DMS CDC task fails — "No tables found at task initialization".** Source has no collections yet. Set `FailOnNoTablesCaptured: false` in the replication task settings.

## Major Version Upgrade (MVU)

**"AllowMajorVersionUpgrade flag must be present".** `--allow-major-version-upgrade` is mandatory on every `modify-db-cluster` MVU command. Include it.

**"Must explicitly specify a new DB cluster parameter group".** The cluster uses a custom parameter group, but you didn't specify one for the target engine family. Create a new PG for the target (e.g. `docdb5.0`, `docdb8.0`) and pass `--db-cluster-parameter-group-name`.

**MVU fails / rolls back.** In-place MVU auto-rolls back on failure. Check cluster events for "Database cluster is in a state that cannot be upgraded." Verify: no db.r4 instances (not supported on 4.0+), no pending OS maintenance, burstable-instance index counts within limits (t4g.medium: 3,000; t3.medium: 10,000). Contact AWS support before re-attempting.

**Post-upgrade performance degradation (5.0→8.0).** Index metadata refresh is running — wait for "Index metadata refresh process completed" event (up to 2 hours). Do NOT reboot or failover the writer during this window.

**MVU CDC migrator connection error.** Source URI must NOT include `readPreference=secondaryPreferred` — change streams only work on the primary.

**Clone creation fails.** Source cluster must be in "available" state. Check encryption settings are compatible. Ensure IAM permissions include `rds:RestoreDBClusterToPointInTime`.

**CDC replication lag not decreasing.** DMS: check CloudWatch logs and increase parallel threads. MVU tool: verify network connectivity and that change stream retention hasn't expired (default 3 hours — raise to 24 hours with `change_stream_log_retention_duration=86400`).

## Performance and operations

**High CPU with no obvious slow queries.** Run `db.adminCommand({currentOp: 1})` — look for index builds. Check CloudWatch `OpcountersInsert` + `OpcountersDelete` for TTL activity. If query volume: scale up instance or add read replicas.

**GC pressure / `AvailableMVCCIds` dropping.** Long-running ops blocking MVCC garbage collection. Kill them: `db.adminCommand({killOp: 1, op: <opid>})`. Recommend avoiding transactions longer than 1 minute.

**`explain()` output differs from MongoDB.** Field names and nesting are different. Read output manually; do not parse it programmatically assuming MongoDB format.

## Throttling and resource availability

**`ReadTimeoutError`, `ThrottlingException`, `Rate exceeded`.** Retry once; if persistent, narrow scope (single cluster, shorter window, smaller batch).

**`DBClusterNotFoundFault`.** Verify region and cluster identifier spelling. For Global Clusters use `describe-global-clusters`. Empty DMS endpoint list — confirm resources exist in the region you queried.

## Escalation

- If a command fails twice with the same error, **stop and show the full error to the user** with a suggested manual step rather than retrying the same command
- Destructive changes (delete cluster, drop collection, force failover) require explicit user confirmation before proceeding
