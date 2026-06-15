# Connection Troubleshooting

Diagnoses connection issues for customers connecting to Amazon Keyspaces using Apache Cassandra client drivers. Covers `application.conf` validation, error diagnosis, connection pool sizing, and driver-version-specific behaviors.

## 1. application.conf Validator

When a customer shares their `application.conf` (or equivalent programmatic config), check EVERY item below. Flag any that don't match the required/recommended value.

**You MUST explicitly call out EVERY misconfiguration you find — never silently fix one in a corrected config without naming it as a finding first. If you identify 6 issues, list all 6 individually with explanations before showing the corrected config. Especially do NOT omit `slow-replica-avoidance` or `pool.local.size` — these are the two most commonly missed items.**

### Required settings (will cause failures if wrong)

| Setting | Required value | What breaks if wrong |
|---------|---------------|---------------------|
| `basic.contact-points` | `cassandra.<region>.amazonaws.com:9142` | Connection fails — wrong host or port 9042 won't reach Keyspaces |
| Port | `9142` | Timeout — port 9042 is Cassandra default, not Keyspaces |
| `advanced.ssl-engine-factory.class` | `DefaultSslEngineFactory` | `OperationTimedOut` — Keyspaces requires TLS on all connections |
| `advanced.ssl-engine-factory.hostname-validation` | `false` | Driver sees Keyspaces as single-node cluster; connections fail to peers. TLS hostname verification against the peer IPs will fail because IPs don't match the certificate's CN/SAN. |
| `basic.request.consistency` | `LOCAL_QUORUM` for writes | `InvalidQueryException: Consistency level ONE is not supported` — Keyspaces only supports `LOCAL_QUORUM` for writes and `LOCAL_ONE` or `LOCAL_QUORUM` for reads |
| `basic.load-balancing-policy.local-datacenter` | Must match the AWS region (e.g., `us-east-1`) | `NoNodeAvailableException` — driver can't find nodes in the declared DC |
| TrustStore | Must contain Amazon root CA certificates (AmazonRootCA1 through CA4 + Starfield) | `SSLHandshakeException: PKIX path building failed` — TLS certificate chain validation fails |

### Strongly recommended settings (will cause intermittent issues if missing)

| Setting | Recommended value | What breaks if missing |
|---------|-------------------|----------------------|
| `basic.load-balancing-policy.slow-replica-avoidance` | `false` | Driver may deprioritize nodes that appear "slow" — in Keyspaces all nodes are equivalent endpoints behind a load balancer |
| `advanced.connection.pool.local.size` | `≥ 3` (calculate per workload — see §3) | `PerConnectionRequestExceeded` — too many queries per connection causes `WriteTimeout` / `ReadTimeout` |
| `basic.request.default-idempotence` | `true` | Driver won't auto-retry failed requests — transient errors become application errors |
| `advanced.heartbeat.timeout` (4.x) | `2000 milliseconds` (raise from 500ms default) | `HeartbeatException` → driver closes connection → `NoNodeAvailableException` cascade |
| `advanced.heartbeat.interval` (4.x) / heartbeat interval (3.x) | `30 seconds` (default) | Idle connections may be dropped by intermediate network devices (NAT, NLB idle timeout of 350s) |
| Retry policy | `AmazonKeyspacesExponentialRetryPolicy` (max-attempts ≥ 3, min-wait 10ms, max-wait 100ms) | Transient server errors (`NOT_MASTER`, `METADATA_VERSION_HIGHER`) bubble up as application failures |
| `advanced.reconnect-on-init` | `true` | Driver gives up immediately if first connection attempt fails |
| `advanced.resolve-contact-points` | `false` | May cause issues with VPC endpoint resolution |
| `advanced.prepared-statements.prepare-on-all-nodes` | `false` | Unnecessary overhead — Keyspaces handles prepared statement distribution |

### Settings that differ from open-source Cassandra defaults

Customers migrating from self-managed Cassandra often carry over configs that don't apply or actively harm Keyspaces connectivity:

| OSS Cassandra setting | Keyspaces equivalent | Notes |
|-----------------------|---------------------|-------|
| `TokenAwarePolicy` (load balancing) | `DefaultLoadBalancingPolicy` with `slow-replica-avoidance = false` | Token-aware routing is irrelevant — Keyspaces routes internally |
| `QUORUM` consistency | `LOCAL_QUORUM` | Keyspaces doesn't support `QUORUM` or `EACH_QUORUM` |
| No SSL | SSL required | Always port 9142 + TLS |
| `DefaultRetryPolicy` | `AmazonKeyspacesExponentialRetryPolicy` | Default retry policy tries "next host" which may not exist with VPC endpoints |

## 2. Error → Diagnosis → Fix

### `NoNodeAvailableException` / `AllNodesFailedException`

**Symptoms:** All queries fail. Application needs restart to recover.

**Diagnosis tree:**

1. **All connections lost** → Check heartbeat timeout (§ HeartbeatException below)
2. **Single-node visibility** → Check `hostname-validation = false` and VPC endpoint IAM permissions for `system.peers` population
3. **Retries exhausted** → Check retry policy — default policy tries "next host" but with VPC endpoint there may only be 1-3 hosts. Use `AmazonKeyspacesExponentialRetryPolicy` which retries on same host across different connections.
4. **Verify `system.peers` is populated** → Run `SELECT * FROM system.peers` and count rows. If 0 rows, VPC endpoint IAM permissions are missing (`ec2:DescribeNetworkInterfaces`, `ec2:DescribeVpcEndpoints`).

**Fix:** See required settings in §1. Ensure pool size ≥ 3, heartbeat timeout ≥ 2s, retry policy configured.

---

### `HeartbeatException` → connection closure cascade

**Symptoms:** Application works fine for minutes/hours, then suddenly all connections drop. Logs show `HeartbeatException` followed by `NoNodeAvailableException`.

**Root cause:** The driver sends a heartbeat (OPTIONS message) on idle connections every 30s. If the response isn't received within the heartbeat timeout (default 500ms in 4.x), the driver marks the connection as failed and closes it. When all connections are closed, no queries can execute.

**Why this happens more with Keyspaces:** Keyspaces is a managed service behind a network load balancer. Occasional network jitter (50-100ms) is normal and harmless for queries but can push heartbeat responses past the aggressive 500ms default.

**Fix (4.x driver):**

**You MUST recommend ALL four of these fixes together — never omit any:**

1. Increase heartbeat timeout: `advanced.heartbeat.timeout = 2000 milliseconds`
2. Increase connection pool size: `advanced.connection.pool.local.size = 3` (minimum — provides redundancy so one lost connection doesn't cascade)
3. Configure retry policy: `AmazonKeyspacesExponentialRetryPolicy` (handles transient aborts)
4. Set `basic.request.default-idempotence = true` (enables automatic retries on aborted requests)

**Fix (3.x driver):** Heartbeat timeout is coupled with read timeout in 3.x — there's no separate setting. The default read timeout of 12s is usually sufficient. If you're setting a custom read timeout lower than 2s, heartbeat failures become more likely. Ensure heartbeat interval is at 30s (default).

---

### `PerConnectionRequestExceeded` / `WriteTimeout` / `ReadTimeout`

**Symptoms:** Intermittent timeouts under load. CloudWatch shows `PerConnectionRequestRateExceeded` metric > 0.

**Root cause:** Each TCP connection supports up to 3,000 CQL queries/second. When exceeded, Keyspaces rejects with a timeout error the driver maps to `WriteTimeout` or `ReadTimeout`.

**Fix:** Increase `advanced.connection.pool.local.size`. Calculate using §3 below.

---

### `SSLHandshakeException: PKIX path building failed`

**Symptoms:** Connection fails immediately on TLS handshake. May affect only some IPs (not all endpoints).

**Root cause:** TrustStore doesn't include the correct root CA certificates. AWS has migrated to Amazon Trust Services (ATS) certificates signed by Amazon Root CA 1. The legacy Starfield-only trustStore is insufficient.

**Fix:** Rebuild trustStore with ALL Amazon root CAs:

```bash
curl -O https://www.amazontrust.com/repository/AmazonRootCA1.pem
# Include AmazonRootCA1 through CA4 + Starfield for full coverage
openssl x509 -outform der -in AmazonRootCA1.pem -out temp_file.der
keytool -import -alias amazon-root-ca-1 -keystore cassandra_truststore.jks -file temp_file.der
```

---

### `OperationTimedOutException: Timed out waiting for server response`

**Symptoms:** Client-side timeout fired before receiving a response.

**Diagnosis:**

1. Check CloudWatch `SuccessfulRequestLatency` p100 — if it's below client timeout, the issue is network or driver, not Keyspaces
2. Check if `PerConnectionRequestRateExceeded` > 0 — need more connections
3. Check if `StoragePartitionThroughputCapacityExceeded` > 0 — hot partition, review data model
4. Check if `WriteThrottleEvents` or `ReadThrottleEvents` > 0 — increase provisioned capacity or switch to on-demand

**Fix:** Depends on diagnosis. Most commonly: increase timeout to 5s+ for batch operations, add retry policy, increase connection pool.

---

### `BusyPoolException` (3.x driver)

**Symptoms:** `Pool is busy (no available connection and the queue has reached its max size 256)`

**Root cause:** All connections are saturated and the internal queue is full. Common when driver 3.x has `maxRequestsPerConnection` set too low or connection pool is undersized.

**Fix (3.x):**

```java
PoolingOptions poolingOptions = new PoolingOptions()
    .setCoreConnectionsPerHost(HostDistance.LOCAL, 3)
    .setMaxConnectionsPerHost(HostDistance.LOCAL, 3)
    .setMaxRequestsPerConnection(HostDistance.LOCAL, 512)
    .setMaxRequestsPerConnection(HostDistance.REMOTE, 0);
```

---

### `Connection has been closed` / `ClosedChannelException`

**Symptoms:** Sporadic connection drops, especially after idle periods.

**Possible causes:**

1. **NLB idle timeout** — Connections idle for 350+ seconds get RST from the load balancer. Fix: ensure heartbeat interval < 350s (default 30s is fine).
2. **NAT instance failover** — If customer uses NAT instances with scheduled failover, connections break during route table updates. Fix: use NAT Gateway or VPC endpoint instead.
3. **MTU mismatch** — Rare. If customer is on EC2 with MTU 9001 and path doesn't support jumbo frames, TLS handshake can fail silently. Fix: set MTU to 1500 or use VPC endpoint (which supports 9K MTU end-to-end).

## 3. Connection Pool Sizing Calculator

**Formula:**

```
connections_per_host = CEIL(
  total_queries_per_second
  / (num_instances - 1)
  / num_endpoints
  / 500
)
```

**Variables:**

- `total_queries_per_second` — Target throughput (reads + writes + deletes combined)
- `num_instances` — Application instances with a Keyspaces session. Subtract 1 to account for maintenance/failure.
- `num_endpoints` — Number of Keyspaces endpoints visible to the driver:
  - Public endpoint: 9 (from `system.peers`)
  - VPC endpoint: 2-5 depending on region AZs
  - Cross-account VPC: often 1
- `500` — Best-practice target per connection (not the 3,000 hard max)

**Example:** 20,000 queries/sec, 3 instances, 5 VPC endpoints:

```
20,000 / (3-1) / 5 / 500 = 4 connections per host
```

Set: `advanced.connection.pool.local.size = 4`

**Monitoring:** Watch `PerConnectionRequestRateExceeded` in CloudWatch. If > 0, increase pool size.

## 4. Driver 3.x vs 4.x Differences

| Behavior | 3.x | 4.x |
|----------|-----|-----|
| Heartbeat timeout | Coupled with read timeout (default 12s) | Separate setting (default 500ms — **too low for Keyspaces**) |
| Request timeout scope | Per-attempt | Entire request including retries |
| Default idempotence | false | false (must set `true` explicitly for auto-retry) |
| Retry on `NoNodeAvailable` | Immediate | Requires custom retry policy |
| `hostname-validation` | Not a concept | Defaults to `true` — **must set to `false`** |
| Connection pool config | `PoolingOptions` builder | `advanced.connection.pool.local.size` in config |
| Reconnection to control connection | Generally resilient | Known issues with some versions — ensure latest 4.x patch |

### Migration gotcha: 4.x request timeout includes retries

In 3.x, a 2-second timeout applied to each individual attempt. With 3 retries, the total wall-clock time could be 6+ seconds.

In 4.x, a 2-second timeout applies to the **entire request** including all retries. With the default timeout of 2s and retries taking time, the request may time out before all retries complete. Recommend setting `basic.request.timeout = 5 seconds` for Keyspaces.

## 5. Reference application.conf (recommended starting point)

```
datastax-java-driver {
  basic {
    contact-points = ["cassandra.<region>.amazonaws.com:9142"]
    load-balancing-policy {
      class = DefaultLoadBalancingPolicy
      local-datacenter = "<region>"
      slow-replica-avoidance = false
    }
    request {
      consistency = LOCAL_QUORUM
      default-idempotence = true
      timeout = 5 seconds
    }
  }
  advanced {
    auth-provider = {
      class = software.aws.mcs.auth.SigV4AuthProvider
      aws-region = "<region>"
    }
    ssl-engine-factory {
      class = DefaultSslEngineFactory
      truststore-path = "<path>/cassandra_truststore.jks"
      truststore-password = "<password>"  // Store in Secrets Manager or SSM Parameter Store (SecureString)
      hostname-validation = false
    }
    connection {
      pool.local.size = 3
      connect-timeout = 5 seconds
      init-query-timeout = 5 seconds
    }
    heartbeat {
      interval = 30 seconds
      timeout = 2000 milliseconds
    }
    reconnect-on-init = true
    resolve-contact-points = false
    prepared-statements.prepare-on-all-nodes = false
    retry-policy {
      class = com.aws.ssa.keyspaces.retry.AmazonKeyspacesExponentialRetryPolicy
      max-attempts = 3
      min-wait = 10 ms
      max-wait = 100 ms
    }
  }
}
```

Replace `<region>` and `<path>` with actual values. Store the truststore password in AWS Secrets Manager or AWS Systems Manager Parameter Store (SecureString) rather than hard-coding it in configuration files.

**SigV4 (IAM authentication) is the strongly recommended default** — it uses ephemeral credentials, requires no password management, and integrates with IAM policies for fine-grained access control. Service-specific credentials (PlainTextAuthProvider with username/password) are a less-secure fallback intended only for legacy applications that cannot use IAM auth. If service-specific credentials must be used, store them in AWS Secrets Manager with automatic rotation enabled.

## 6. Useful Links

- [Optimize client driver connections](https://docs.aws.amazon.com/keyspaces/latest/devguide/connections.html)
- [Troubleshooting connection errors](https://docs.aws.amazon.com/keyspaces/latest/devguide/troubleshooting.connecting.html)
- [Troubleshooting general errors](https://docs.aws.amazon.com/keyspaces/latest/devguide/troubleshooting.general.html)
- [Troubleshooting capacity errors](https://docs.aws.amazon.com/keyspaces/latest/devguide/troubleshooting.serverless.html)
- [Amazon Keyspaces retry policy (GitHub)](https://github.com/aws-samples/amazon-keyspaces-java-driver-helpers/blob/main/src/main/java/com/aws/ssa/keyspaces/retry/AmazonKeyspacesExponentialRetryPolicy.java)
- [Spark application.conf example](https://docs.aws.amazon.com/keyspaces/latest/devguide/spark-tutorial-step3.html)
- [VPC endpoint system.peers permissions](https://docs.aws.amazon.com/keyspaces/latest/devguide/vpc-endpoints.html)
