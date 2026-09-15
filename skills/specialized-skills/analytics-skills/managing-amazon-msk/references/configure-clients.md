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
| `client.rack` | AZ ID (e.g., `use1-az1`) | Consumer side. Enables nearest-replica reads to eliminate cross-AZ consumer fetch cost. Must be paired with the broker-side selector in the row below. |
| `replica.selector.class` (cluster configuration) | `org.apache.kafka.common.replica.RackAwareReplicaSelector` | Broker-side. Default on MSK is `null` — must be set explicitly by attaching a custom MSK cluster configuration that includes this line, then applying it to the cluster. Without it, `client.rack` has no effect and consumers still fetch from the partition leader regardless of AZ. `broker.rack` itself is set automatically by MSK to the broker's AZ ID (e.g., `use1-az1`) so no manual config is needed there. See [Reduce network traffic costs of your Amazon MSK consumers with rack awareness](https://aws.amazon.com/blogs/big-data/reduce-network-traffic-costs-of-your-amazon-msk-consumers-with-rack-awareness/) for the full setup. |
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

## References

- [MSK Client Best Practices](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-kafka-client.html)

## Custom Domain Name Connectivity (NLB, certificate, DNS)

Custom domain names for MSK brokers are set with the `custom.advertised.listeners` **cluster configuration** property — see [configure-cluster.md](configure-cluster.md) for that property, its validation rules, and the apply/rollback workflow. This section covers the client-facing networking and trust layer you own, which must be in place **before** that property is applied.

Because you cannot change the certificate MSK brokers present, custom domains are fronted by a Network Load Balancer (NLB). See [Configure a custom domain name for your Amazon MSK cluster](https://aws.amazon.com/blogs/big-data/configure-a-custom-domain-name-for-your-amazon-msk-cluster/) for the full walkthrough.

### Prerequisite: build the networking/trust layer BEFORE the property is applied

The `custom.advertised.listeners` property only changes what brokers advertise. The client connectivity and trust layer is a **prerequisite, not a follow-up** — apply the property before it exists and you disconnect clients. Kafka clients do not keep using the address they bootstrapped with: on the next [metadata refresh](https://kafka.apache.org/documentation/#producerconfigs_metadata.max.age.ms) they learn the new advertised listener and use it for all subsequent connections, so if the custom domain isn't resolvable, reachable, and trusted, connected clients cannot reconnect.

Safe two-phase cutover (also how you migrate from Amazon DNS to a custom domain):

1. **Build the networking path first** — NLB, DNS (Route 53 private hosted zone), and TLS certificate — and point clients at the custom bootstrap endpoint while they still connect to brokers over the AWS-generated addresses.
2. **Apply `custom.advertised.listeners`** (see [configure-cluster.md](configure-cluster.md)). At the next metadata refresh clients pick up the custom domain and cut over automatically, with no restart.

### TLS handshake and mTLS

The NLB is a Layer 4 load balancer with **TLS listeners**: it **terminates** the client's TLS connection (presenting the ACM certificate for your custom domain, which the client validates against the cert's CN/SAN), then opens a **separate, independent TLS negotiation** to the target broker. That is two TLS sessions, not one end-to-end session. Because TLS terminates at the NLB and is re-negotiated to the broker, a client certificate presented in the client->NLB handshake is **NOT passed through to the broker** — so MSK **TLS mutual authentication (mTLS) does not work** through this NLB-termination pattern. Use **SASL/SCRAM or IAM** instead; they authenticate above the TLS transport (SCRAM challenge / IAM SASL token) and work correctly through the NLB.

### Certificate

Import a **single** certificate into ACM and associate it with **every** TLS listener on the NLB. Set CN = `bootstrap.example.com` (valid for the bootstrap address) and add SANs for each broker name (`b-1.example.com`, `b-2.example.com`, …). The DNS name a client connects with must match the CN or a SAN or the handshake fails hostname validation. Reference the returned `CertificateArn` on each listener with an ssl-policy. For a private/self-signed CA, clients must import the root and intermediate CA certificates into their trust store (`ssl.truststore.location`); with a public CA they are already in the default trust store.

### Target groups

For an N-broker cluster create N+1 target groups: one bootstrap group containing all brokers, plus one per broker. Each uses **protocol `TLS`**, **target-type `ip`**, is associated with the MSK VPC, and its port is the broker **authentication port** — `9096` for SASL/SCRAM, `9098` for IAM (do NOT use a plaintext/`TCP` target group). Get broker IPs with `aws kafka list-nodes` (`ClientVpcIpAddress`), register each broker's IP into its own target group, and register **all** broker IPs into the bootstrap group.

### Listeners

One TLS listener per target group; the client-facing ports (e.g., 9000 → bootstrap, 9001/9002/9003 → b-1/b-2/b-3) are distinct from the broker auth target port (9096/9098).

### Cross-zone load balancing

Disabled by default on NLBs — each node only forwards to healthy targets in its own AZ, which drops connections (or causes noticeable connection delays as the client tries every IP Route 53 returns) when the healthy target is in another AZ. Enable it:

```
aws elbv2 modify-load-balancer-attributes --load-balancer-arn <arn> \
  --attributes Key=load_balancing.cross_zone.enabled,Value=true
```

Optionally set `dns_record.client_routing_policy=availability_zone_affinity` to reduce cross-AZ data charges.

### Networking does not auto-scale with brokers

When you add or replace brokers, MSK applies `custom.advertised.listeners` to the new broker automatically (see [configure-cluster.md](configure-cluster.md)), but the networking layer does NOT auto-scale — add the corresponding NLB listener, target group, and DNS record for each new broker, matching the `host:port` pattern. Skip that and clients resolve the new broker's custom address but cannot reach it.

### Reference ports

PLAINTEXT/`CLIENT` 9092, TLS/`CLIENT_SECURE` 9094, SASL/SCRAM/`CLIENT_SASL_SCRAM` 9096, IAM/`CLIENT_IAM` 9098 (public variants 9194/9196/9198).

### References

- [Configure a custom domain name for your Amazon MSK cluster](https://aws.amazon.com/blogs/big-data/configure-a-custom-domain-name-for-your-amazon-msk-cluster/) — NLB, Route 53, and ACM walkthrough
- [Amazon MSK simplifies configuring custom domain names](https://aws.amazon.com/blogs/big-data/amazon-msk-simplifies-configuring-custom-domain-names/) — the `custom.advertised.listeners` property (see [configure-cluster.md](configure-cluster.md))
