# Error Remediation Guide

**Scope:** Valkey and Redis OSS engines only. Memcached uses SASL authentication (1.6.12+) and does not support RBAC user groups or IAM auth. Memcached error patterns differ and are not covered here.

ElastiCache-specific errors that require non-obvious remediation. Generic errors (AUTH required, TLS handshake, DNS resolution, timeouts, replication lag, throttling, slow commands) are omitted; see monitoring/troubleshooting.md for metric-based diagnosis of those.

## 1. Connection Refused

**Symptom:** Client gets `Connection refused` or `ECONNREFUSED` when connecting to the cache endpoint.

**Causes:**

- Security group does not allow inbound TCP on port 6379 (or 6380 for serverless read port) from the client's security group or IP.
- The cache endpoint is incorrect or the cache is not in `available` state.
- The client is outside the VPC (ElastiCache has no public endpoints).
- Subnet routing issue: the client's subnet cannot reach the cache's subnet.

**Next steps:**

1. Verify the cache is in `available` status: `aws elasticache describe-serverless-caches` or `describe-replication-groups`.
2. Check the security group attached to the cache allows inbound from the client's security group on port 6379.
3. Confirm the client is in the same VPC or has a valid network path (VPC peering, transit gateway, or tunnel).
4. For serverless, verify both ports 6379 (primary port for reads and writes) and 6380 (read port for eventually-consistent reads via READONLY) are allowed; both use the same hostname.
5. Run: `python3 scripts/test_connection.py <endpoint>`

## 2. WRONGPASS / Invalid Credentials

**Symptom:** `WRONGPASS invalid username-password pair` or `ERR invalid password`.

**Causes:**

- Incorrect password or expired IAM auth token.
- RBAC user password was rotated but the client is using the old password.
- IAM auth token expired (tokens are valid for 15 minutes).
- Wrong username specified.

**Next steps:**

1. For IAM auth: regenerate the token. Tokens expire after 15 minutes for new AUTH/HELLO; an already-authenticated connection remains valid for up to 12 hours. Sending AUTH (or HELLO with auth) using a new IAM token resets the 12-hour disconnect timer.
2. For password auth: retrieve the current password from Secrets Manager.
3. Verify the username matches an active RBAC user associated with the cache's user group.
4. If the password is correct but commands still fail, check for NOPERM errors (section 7), which indicate access-string restrictions rather than credential issues.

## 3. MOVED Error

**Symptom:** `MOVED <slot> <ip>:<port>` response from the server.

**Causes:**

- The client sent a command to a node that does not own the hash slot for the key. This happens with cluster-mode-enabled deployments when the client is not using a cluster-aware driver.

**Next steps:**

1. Use a cluster-aware client library (e.g., `redis-py` with `RedisCluster`, `ioredis` with `Cluster` mode, Lettuce with cluster topology refresh).
2. Do not use a standalone client to connect to a cluster-mode-enabled cache.
3. Verify the client is connected to the configuration endpoint, not an individual node endpoint.

## 4. ASK Error

**Symptom:** `ASK <slot> <ip>:<port>` response during a resharding operation.

**Causes:**

- The cluster is in the middle of a slot migration (resharding). The target node holds the key temporarily.

**Next steps:**

1. This is transient during resharding. Cluster-aware clients handle ASK redirects automatically.
2. Ensure the client library supports ASK redirect handling.
3. If resharding is not expected, check for ongoing maintenance or scaling operations.

## 5. OOM / Maxmemory Reached

**Symptom:** `OOM command not allowed when used memory > 'maxmemory'` or `ERR command not allowed when maxmemory is set and the server is currently unable to free memory`.

**Causes:**

- The cache has reached its configured `maxmemory` limit and the current eviction policy (`maxmemory-policy`) does not allow the write.
- `noeviction` policy is set, preventing automatic key eviction.

**Next steps:**

1. Check `DatabaseMemoryUsagePercentage` in CloudWatch.
2. If the eviction policy is `noeviction`, consider changing to `allkeys-lru` or `volatile-lru` depending on the use case.
3. Scale up the node type for more memory, or add shards to distribute data.
4. Review TTLs on keys; ensure transient data has appropriate expiry.
5. Use `MEMORY USAGE <key>` to identify large keys consuming disproportionate memory.

## 6. CROSSSLOT Error

**Symptom:** `CROSSSLOT Keys in request don't hash to the same slot`.

**Causes:**

- A multi-key command (MGET, MSET, pipeline with multi-key operations, Lua script with multiple keys) targets keys that hash to different slots in a cluster-mode-enabled deployment.

**Next steps:**

1. Use hash tags to force related keys to the same slot: `{user:123}:profile`, `{user:123}:sessions`.
2. Split multi-key operations into per-slot batches.
3. If the workload cannot use hash tags, consider a single-shard deployment (if data fits).
4. Review the client library's support for automatic slot-aware batching.

## 7. Permission Denied (RBAC ACL)

**Symptom:** `NOPERM this user has no permissions to run the '<command>' command` or `NOPERM... on key '<key>'`.

**Causes:**

- The RBAC user's access string does not permit the command category or key pattern.
- The user is restricted to specific key prefixes and the application is accessing keys outside that prefix.

**Next steps:**

1. Check the user's access string: `aws elasticache describe-users --user-id <user-id>`.
2. Update the access string to include the required command categories and key patterns.
3. Common fix: change `on ~app:* +@read` to `on ~app:* +@read +@write` if writes are needed.
4. Access string changes (via `aws elasticache modify-user`) take effect immediately on **all** existing connections authenticated as that user — not just new ones. However, setting a user to `off` only prevents new `AUTH` attempts (it does not disconnect existing connections). To delete a user, use `aws elasticache delete-user`; ElastiCache does not support the `ACL DELUSER` command. Deleting a user via the API removes them from all associated user groups.

## 8. READONLY Error

**Symptom:** `READONLY You can't write against a read only replica`.

**Causes:**

- The client is sending write commands to a read replica instead of the primary.
- The client is connected to the reader endpoint instead of the primary endpoint.
- After a failover, the client's cached topology is stale.

**Next steps:**

1. Ensure writes go to the primary endpoint and reads go to the reader endpoint.
2. For cluster-mode, verify the client refreshes topology after failover.
3. Check if a failover recently occurred and the client reconnected to the wrong node.

## 9. LOADING Error

**Symptom:** `LOADING Redis is loading the dataset in memory`.

**Causes:**

- The node is starting up and loading data from a snapshot (RDB) or AOF file.
- Occurs after a restart, failover, or restore from backup.

**Next steps:**

1. Wait for the loading to complete. Duration depends on data size.
2. Monitor the node status in the console or via `describe-replication-groups`.
3. If loading takes excessively long, check the snapshot size and node type (more memory = faster load).

## 10. CLUSTERDOWN Error

**Symptom:** `CLUSTERDOWN The cluster is down` or `CLUSTERDOWN Hash slot not served`.

**Causes:**

- One or more hash slots are not covered (a shard is unavailable).
- Cluster is in a degraded state after multiple node failures.

**Next steps:**

1. Check cluster health: `describe-replication-groups` for node status.
2. If a shard is down, automatic failover should promote a replica. Verify failover status.
3. If no replica was available for the failed shard, manual intervention may be needed.
4. Check the `cluster-allow-reads-when-down` parameter if read availability during partial failure is important.

## 11. Max Clients Reached

**Symptom:** `ERR max number of clients reached`.

**Causes:**

- The node has reached its maximum connection limit.
- Connection leaks in the application (connections opened but never closed).
- Missing connection pooling.

**Next steps:**

1. Check `CurrConnections` metric in CloudWatch.
2. Implement connection pooling in the application.
3. For node-based: scale up the node type (larger nodes support more connections). For serverless: connection scaling is automatic; max-clients errors indicate per-connection ECPU starvation or client-side connection leaks, not server capacity.
4. Investigate and fix connection leaks (common in Lambda without reuse across invocations).
5. Check for idle connections that can be closed with `timeout` parameter.

## 12. Snapshot/Backup Failure

**Symptom:** Snapshot creation fails or takes excessively long.

**Causes:**

- Insufficient memory for the fork operation (background save requires memory overhead).
- Node type with limited resources.

**Next steps:**

1. Ensure `reserved-memory-percent` leaves enough headroom for fork operations. The default is 25 for accounts created after March 16, 2017. Older accounts may default to 0. AWS recommends 25% for all deployments.
2. Schedule snapshots during low-traffic periods.
3. Scale up the node type if memory is tight during snapshot creation.

## 13. Parameter Group Incompatibility

**Symptom:** `InvalidParameterCombination` when creating or modifying a cluster.

**Causes:**

- Parameter group family does not match the engine and version.
- Conflicting parameters specified.

**Next steps:**

1. Verify the parameter group family matches the engine. Documented valid values include: `memcached1.4`, `memcached1.5`, `memcached1.6`, `redis2.6`, `redis2.8`, `redis3.2`, `redis4.0`, `redis5.0`, `redis6.x`, `redis6.2`, `redis7`, `valkey7`, `valkey8`. Use `describe-engine-default-parameters` to confirm the correct family name for your engine version.
2. Check `describe-engine-default-parameters` for valid parameter names and ranges.
3. Create a new parameter group from the correct family.

## 14. IAM Auth Token Generation Failure

**Symptom:** Client fails to generate or use an IAM auth token. `ElastiCacheSigningError` or similar.

**Causes:**

- The IAM role/user does not have `elasticache:Connect` permission.
- The IAM auth token was generated for the wrong cache or user.
- Clock skew on the client machine (IAM tokens are time-sensitive).

**Next steps:**

1. Verify the IAM policy includes `elasticache:Connect` with the correct resource ARNs.
2. Ensure the token is generated for the correct `--replication-group-id` or `--serverless-cache-name`.
3. Check system clock synchronization.
4. Use the IAM policy simulator to validate permissions.

## 15. MULTI/EXEC Failure with IAM Auth

**Symptom:** `NOPERM` or authentication error during a `MULTI`/`EXEC` transaction on an IAM-authenticated connection.

**Causes:**

- The IAM auth token expired during the transaction and the client attempted to re-AUTH (call `AUTH` again) inside the `MULTI` block. Re-authentication inside a transaction is not supported.
- MULTI/EXEC itself works correctly on IAM-authenticated connections. The limitation is that token refresh cannot happen between `MULTI` and `EXEC`.

**Next steps:**

1. Refresh the IAM auth token **before** issuing `MULTI`, not inside the transaction. Ensure the token will remain valid for the duration of the transaction.
2. Use a connection pool that rotates IAM tokens on idle reconnect or before checkout, so connections handed to application code always have a fresh token.
3. If token expiry during long transactions is unavoidable, establish a new connection with a fresh token and retry the transaction.

## 16. Cluster Creation Timeout

**Symptom:** Cluster creation takes longer than expected or appears stuck in `creating` status.

**Causes:**

- Large node types with many shards take longer to provision.
- Region capacity constraints.
- Dependent resource issues (subnet group, security group, KMS key permissions).

**Next steps:**

1. For serverless: creation should take under 1 minute. If stuck, check VPC/subnet/SG configuration.
2. For node-based: creation can take 5-15 minutes. Wait and check status periodically.
3. Verify the KMS key (if specified) grants ElastiCache permission to use it.
4. Check AWS Service Health Dashboard for regional issues.
