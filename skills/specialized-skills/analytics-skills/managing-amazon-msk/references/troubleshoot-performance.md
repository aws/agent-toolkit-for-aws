# Troubleshoot MSK Performance

## Step 1: Determine broker type

Run `aws kafka describe-cluster-v2 --cluster-arn <arn>`. If instance type starts with `express.`, skip all EBS-related checks — Express has no customer-managed EBS.

## Step 2: Check CPU and request handler utilization

Get `CpuUser` and `RequestHandlerAvgIdlePercent` from CloudWatch (PER_BROKER level, namespace `AWS/Kafka`).

**Decision tree:**

- **CpuUser + CpuSystem > 60% AND RequestHandlerAvgIdlePercent < 30%**: Request handler threads are saturated. Go to Step 3 (batch size analysis).
- **CpuUser + CpuSystem > 60% AND RequestHandlerAvgIdlePercent > 30%**: CPU is consumed by non-request work. Check: compression (broker-side recompression when `compression.type` is not `producer`), message format conversions — `FetchMessageConversionsPerSec`, `ProduceMessageConversionsPerSec` **(Standard only)**, log compaction (`log.cleaner.min.cleanable.ratio` too low), high GC — `HeapMemoryAfterGC` > 60% **(Standard only — Express does not emit this metric)** (reduce `transactional.id.expiration.ms` from 7 days to 1 day to lower memory footprint), or excessive Prometheus scraping (use 60s+ scrape interval).
- **CpuUser + CpuSystem < 60% AND RequestHandlerAvgIdlePercent < 30% with high latency**: Request handlers are saturated despite low overall CPU. This is common on larger instance types (m5.4xl+/m7g.4xl+) where 8 default request handler threads can be fully busy while other cores sit idle. Go to Step 3 (batch size analysis) first. If batch sizes are healthy, check `num.io.threads`/`num.network.threads` — see [size-and-choose-cluster.md](size-and-choose-cluster.md) for recommended values.
- **CpuUser + CpuSystem < 60% AND RequestHandlerAvgIdlePercent > 30% with high latency**: Go to Step 4 (EBS throughput check, Standard only), Step 5 (network/traffic shaping), or Step 6 (Express throttling).

## Step 3: Diagnose small batch / high request rate

Compute average message size: `BytesInPerSec / MessagesInPerSec`. If average message size is very small (under 1 KB) and `MessagesInPerSec` is very high relative to `BytesInPerSec`, the root cause is likely small producer batches.

**Confirm with** (PER_BROKER level): `RequestHandlerAvgIdlePercent` < 30% and `NetworkProcessorAvgIdlePercent` dropping. **If monitoring is DEFAULT**: the average message size calculation (`BytesInPerSec / MessagesInPerSec`) combined with high CPU is sufficient — tiny messages (< 1 KB) with high message rates confirm small-batch saturation without needing PER_BROKER metrics.

**Root cause**: Poor producer batching configuration — typically `linger.ms=0` (sends immediately, no batching), small `batch.size` (default 16 KB), and no compression. Each message becomes its own produce request, consuming a request handler thread regardless of payload size.

**Fix**: Recommend client-side batching changes — see [configure-clients.md](configure-clients.md). All three settings matter: `linger.ms >= 5` (recommend 25ms), `batch.size >= 65536` (64-128 KB), and `compression.type = lz4` or `zstd`. These work together — `linger.ms` allows time to fill the batch, `batch.size` sets the batch capacity, compression reduces the final payload. Do NOT recommend broker scaling as the first action.

**Other CPU contributing factors** (check if batch size is not the cause):

- Compression type: Broker-side recompression (when `compression.type` is not `producer`) consumes CPU
- Record format conversions: Clients using older message format versions force conversion
- Log compaction: `log.cleaner.min.cleanable.ratio` set too low (e.g., 0.01 instead of 0.5)
- High partition count: More partitions = more metadata overhead and GC pressure
- Connection creation spikes: High `ConnectionCreationRate` especially with SASL/SCRAM or IAM auth
- Too many consumer groups: List groups with `kafka-consumer-groups.sh --bootstrap-server <bootstrap> --list | wc -l` — excessive consumer groups increase coordinator overhead and heap memory usage

## Step 4: EBS throughput bottleneck (Standard only)

**Skip this step for Express brokers.**

Check the EBS volume type and size. MSK Standard brokers use EBS volumes with throughput ceilings:

- **GP2**: Throughput = min(250 MiB/s, max(128 MiB/s, 0.75 × VolumeSize_GiB)). The 250 MiB/s cap is reached at ~334 GiB. Volumes also have `BurstBalance` that depletes under sustained IO.
- **GP3** with MSK provisioned throughput: Default 250 MiB/s for volumes 10 GiB+, provisionable up to 1000 MiB/s depending on broker size. Requires `kafka.m5.4xlarge`+ or `kafka.m7g.2xlarge`+.

**Calculate effective throughput demand**: `BytesInPerSec × ReplicationFactor`. For RF=3 and 83 MiB/s ingress, total write IO = 250 MiB/s, hitting GP2 ceiling.

**Confirm with CloudWatch** (PER_BROKER level): `VolumeWriteBytes`, `VolumeReadBytes`, `VolumeTotalWriteTime`, `VolumeTotalReadTime`, `VolumeQueueLength`. Elevated queue length and write time confirm EBS saturation. **If monitoring is DEFAULT**: check `CpuIoWait` — sustained elevation indicates threads blocked on disk I/O, a free proxy for EBS saturation.

**Fix options** (in order of preference):

1. Enable provisioned throughput (GP3) — requires broker size `kafka.m5.4xlarge` or larger (or `kafka.m7g.2xlarge` or larger). Max throughput varies by broker size (593 MiB/s for m5.4xl up to 1000 MiB/s for m5.12xl+).
2. Upgrade broker instance type to one with higher EBS-to-EC2 network bandwidth.
3. Migrate to Express brokers — eliminates EBS management entirely.

## Step 5: Network bandwidth and traffic shaping (Standard only)

**Skip this step for Express brokers — go to Step 6.**

Standard brokers run on EC2 instances with network bandwidth limits enforced by the hypervisor. When exceeded, packets are shaped (dropped/delayed), causing latency spikes without high CPU.

**Check these PER_BROKER level metrics:**

- `BwInAllowanceExceeded` > 0: Inbound bandwidth exceeded
- `BwOutAllowanceExceeded` > 0: Outbound bandwidth exceeded
- `PpsAllowanceExceeded` > 0: Packets-per-second limit exceeded (many small messages)
- `ConntrackAllowanceExceeded` > 0: Connection tracking limit exceeded (too many concurrent connections)
- `TrafficShaping` (DEFAULT level) > 0: Aggregate indicator that any shaping is occurring

**If any traffic shaping metrics are nonzero:**

1. **Check for AZ skew**: Compare per-broker `BytesInPerSec` and `BytesOutPerSec`. If some brokers handle 2-3x more traffic than others, the load is unevenly distributed.
   - Common cause: Consumers deployed in a single AZ with `client.rack` set, causing all reads to route to brokers in that AZ.
   - Common cause: Partition leadership concentrated on brokers in one AZ after a maintenance event (check `LeaderCount` per broker).
2. **Check if throughput exceeds the instance type's network baseline**: Each EC2 instance type has a network bandwidth baseline and burst limit. Sustained throughput above baseline triggers shaping.

**Fix options:**

- Spread producer and consumer clients across all availability zones
- If AZ-local reads (`client.rack`) are required, ensure write traffic and partition leadership are balanced across AZs first
- Upgrade to a larger instance type with higher network baseline bandwidth
- Use Cruise Control to rebalance partition leadership across brokers/AZs

## Step 6: Express throughput throttling

Express brokers do NOT have EC2-level traffic shaping metrics (`BwInAllowanceExceeded`, `BwOutAllowanceExceeded`, etc. are not emitted). Instead, Express enforces per-broker throughput quotas directly. When exceeded, MSK throttles client traffic at the Kafka protocol level.

**Check these PER_BROKER level metrics:**

- `ProduceThrottleTime` > 0: Ingress quota exceeded — producers are being throttled
- `FetchThrottleTime` > 0: Egress quota exceeded — consumers are being throttled
- `ProduceThrottleByteRate` / `FetchThrottleByteRate`: Bytes/sec being throttled
- `ProduceThrottleQueueSize` / `FetchThrottleQueueSize`: Requests queued due to throttling

Check the [MSK Express broker quotas](https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-quota) for current per-broker throughput limits. Each Express broker size has a sustained threshold (no degradation) and a maximum quota (hard throttle). Between sustained and max quota, you get higher throughput but with degraded performance (higher latency). At max quota, MSK hard-throttles client traffic.

**Also check for AZ skew on Express**: Compare per-broker `BytesInPerSec` and `BytesOutPerSec`. If some brokers are throttled while others have headroom, the issue is uneven traffic distribution — same causes and fixes as Standard (consumer `client.rack` in one AZ, unbalanced partition leadership).

**Fix options:**

- Scale to a larger Express broker size
- Add more brokers — Express clusters with Intelligent Rebalancing enabled will automatically redistribute partitions. If Intelligent Rebalancing is disabled, manually rebalance (limit to 20 partitions per reassignment call).
- Spread consumers across all AZs to balance egress load
- Reduce consumer group count if egress is the bottleneck (each consumer group multiplies egress)
