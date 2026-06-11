# Configure Kafka Clients for MSK

## Producer Configuration

| Setting | Recommended Value | Why |
|---|---|---|
| `linger.ms` | 5 ms minimum; 25 ms for most use cases | NEVER use 0. A value of 0 sends one request per message, saturating broker request handlers. Even low-latency use cases benefit from 5 ms. |
| `batch.size` | 65536 (64 KB) or 131072 (128 KB) | Larger batches reduce request count and broker CPU. Default 16384 is often too small. |
| `buffer.memory` | 67108864 (64 MB) | Increase when using larger batch sizes to avoid `BufferExhaustedException`. |
| `compression.type` | `lz4` or `zstd` | Reduces network bandwidth and storage. `lz4` for low latency; `zstd` for best compression ratio. |
| `acks` | `all` | Required for durability with MSK default `min.insync.replicas=2` and `RF=3`. Ensures all in-sync replicas acknowledge. Combined with `min.insync.replicas=2`, writes succeed as long as at least 2 of 3 replicas are in the ISR. |
| `retries` | 2147483647 (Integer.MAX_VALUE) | Allow unlimited retries. Use `delivery.timeout.ms` to bound total time. Failure to retry breaks Kafka's high availability during broker failover. |
| `delivery.timeout.ms` | 60000 minimum; 120000 (default) or higher | Upper bound for total send time including retries. Must be ≥ `request.timeout.ms` + `linger.ms`. AWS recommends a minimum of 60 seconds. With RF=3 and `min.insync.replicas=2`, producers only stall during leader election (seconds), so the 2-min default covers most cases. Increase if you observe `TimeoutException` during maintenance. |
| `request.timeout.ms` | 10000 (10 seconds) or higher | Max wait time for a single request before retry. |
| `retry.backoff.ms` | 200 minimum | Prevents retry storms during broker failover. |
| `send.buffer.bytes` | -1 (OS default) | Let the OS manage TCP buffers, especially on high-latency networks. |

## Consumer Configuration

| Setting | Recommended Value | Why |
|---|---|---|
| `session.timeout.ms` | 45000-60000 | Controls how long the broker waits without a heartbeat before evicting the consumer. Higher values tolerate GC pauses and network blips but delay failure detection. When using static membership (`group.instance.id`), must also exceed expected restart time. |
| `heartbeat.interval.ms` | 10000-15000 | Should be less than 1/3 of `session.timeout.ms`. Controls how quickly the group coordinator detects consumer failures. |
| `max.poll.interval.ms` | Based on processing time | If message processing takes > 5 minutes, increase this. Default 300000 (5 min). If exceeded, consumer is evicted from the group. |
| `max.poll.records` | Tune to processing capacity | Reduce if processing is slow to avoid exceeding `max.poll.interval.ms`. |
| `partition.assignment.strategy` | `CooperativeStickyAssignor` | Enables incremental rebalances instead of stop-the-world. **Migration requires two rolling restarts**: first deploy with `RangeAssignor,CooperativeStickyAssignor`, then remove `RangeAssignor`. Mixing eager and cooperative protocols causes `InconsistentGroupProtocolException`. |
| `group.instance.id` | Unique per consumer (e.g., hostname, pod-id) | Enables static group membership. Prevents unnecessary rebalances on short consumer restarts. |
| `auto.offset.reset` | `latest` for new consumer groups | Avoids reprocessing the entire topic on first start, which can overload the cluster. |
| `auto.commit.interval.ms` | 5000 minimum | Prevents excessive commit requests that add broker load. |
| `fetch.min.bytes` | 1024-131072 (1 KB-128 KB) | Reduces number of fetch requests. 1 KB for low-latency use cases; 32-128 KB for throughput-oriented workloads. |
| `fetch.max.wait.ms` | 1000 | How long to wait if `fetch.min.bytes` is not met. |
| `client.rack` | AZ ID (e.g., `use1-az1`) | Enables nearest-replica reads to reduce cross-AZ network costs. |
| `isolation.level` | `read_uncommitted` (default) | SHOULD NOT use `read_committed` when reading from tiered storage unless actively using transactions. |
| `receive.buffer.bytes` | -1 (OS default) | Let OS manage TCP buffers on high-latency networks. |

## Connection Management

- Create Kafka clients (producer, consumer, admin) once per application lifecycle — use singleton pattern. For AWS Lambda, create the client in global/init scope, NOT inside the handler function.
- Add random jitter (random sleep) before creating clients to avoid connection storms during deployments
- Add a shutdown hook with a random sleep before closing clients on SIGTERM — this prevents all clients from disconnecting simultaneously during rolling deployments. The random sleep should fit within the window before SIGKILL occurs.
- Ensure your deployment mechanism does not restart all producers/consumers at once — deploy in smaller batches
- Set `reconnect.backoff.ms = 1000` to handle connection retries gracefully
- Monitor `connection-count`, `connection-creation-rate`, `connection-close-rate` client metrics — these should be stable. High connection creation/termination rates cause unnecessary broker load.

## IAM Authentication

MSK IAM auth client configuration:

```
security.protocol=SASL_SSL
sasl.mechanism=AWS_MSK_IAM
sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;
sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler
```

**Constraints:**

- Maximum 3000 TCP connections per broker with IAM. This limit is adjustable via `listener.name.client_iam.max.connections` dynamic config.
- Maximum 100 new IAM connections per second per broker (M5/M7g); 4 per second on T3. This rate limit is not customer-adjustable.

## SASL/SCRAM Authentication

```
security.protocol=SASL_SSL
sasl.mechanism=SCRAM-SHA-512
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required \
  username="<username>" password="<password>";
```

Store credentials in AWS Secrets Manager. Associate the secret with the MSK cluster. This config format is required for the Kafka CLI (`kafka-console-producer.sh`, etc.). In application code, retrieve credentials from Secrets Manager at runtime and inject into the JAAS config programmatically — do not store passwords in source-controlled config files.

## TLS (mTLS) Authentication

```
security.protocol=SSL
ssl.truststore.location=/path/to/truststore.jks
ssl.truststore.password=<password>
ssl.keystore.location=/path/to/keystore.jks
ssl.keystore.password=<password>
ssl.key.password=<password>
```

This config format is required for the Kafka CLI. In application code, load keystore/truststore passwords from Secrets Manager or SSM Parameter Store (SecureString) at startup — do not commit passwords to source-controlled config files.

If you don't have an existing CA, [AWS Private CA](https://docs.aws.amazon.com/msk/latest/developerguide/msk-authentication.html) can issue and rotate client certificates for MSK mTLS.
