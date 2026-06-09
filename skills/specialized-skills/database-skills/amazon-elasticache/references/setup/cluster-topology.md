# Cluster Topology

Guidance for cluster-mode selection, shard count, replica count, and IP address planning. Applies only to node-based deployments.

## When to Shard (Cluster-Mode-Enabled)

Use cluster-mode-enabled (multiple shards) when:

- **Data exceeds single-node memory**: A single node maxes out at the largest available instance type. Sharding distributes data across multiple nodes.
- **Write throughput exceeds single-primary capacity**: Each shard has its own primary. More shards means more write capacity.
- **Key space is naturally partitionable**: Hash-tag based routing works well when multi-key operations target the same logical entity.

Use single-shard when:

- Data fits comfortably in a single node's memory.
- Write throughput is within a single primary's capacity.
- The application relies heavily on multi-key operations across unrelated keys (CROSSSLOT errors are a concern with cluster mode).
- Simplicity is preferred and the workload does not need horizontal scaling.

## Cluster-Mode Decision Table

| Factor | Single-Shard | Cluster-Mode-Enabled |
|--------|-------------|---------------------|
| Max data capacity | Limited by largest node type | Scales horizontally across shards |
| Max write throughput | Single primary | One primary per shard |
| Multi-key operations | No slot restrictions | Must use hash tags or limit to same slot |
| Operational complexity | Lower | Higher (shard management, rebalancing) |
| Failover blast radius | Entire dataset | One shard only |
| Online resharding | Not applicable | Supported (add/remove shards live) |

### Node and Shard Limits

The default quota is **90 nodes per cluster** (cluster mode enabled). This can be increased to a maximum of **500 nodes per cluster** for Valkey (all versions) or Redis OSS 5.0.6+ (for versions below 5.0.6, the limit is 250). The regional limit is **300 non-reserved nodes per region** across all clusters. To increase these limits, submit a service limit increase request via the AWS Service Quotas console.

## Replica Count Guidance

| Environment | Recommended Replicas per Shard | Rationale |
|-------------|-------------------------------|-----------|
| Development | 0 | Cost savings; no HA needed (note: cluster-mode-enabled always has automatic failover on, which requires at least 1 replica for HA; Multi-AZ with cluster mode disabled also requires at least 1 replica) |
| Staging | 1 | Mimics production topology without excess cost |
| Production | 2-3 | AWS Well-Architected recommends a minimum of 2 replicas per shard for HA workloads; 3 replicas for read-heavy or higher durability requirements |
| Production (read-heavy) | 2-5 | Scale reads across replicas; balance against replication overhead |

## IP Address Planning

Each node (primary or replica) in a node-based cluster consumes one IP address per subnet. Plan subnet CIDR ranges accordingly:

| Topology | Nodes per Shard | Total Nodes (example: 3 shards) | IPs Needed |
|----------|----------------|--------------------------------|------------|
| 1 shard, 1 replica | 2 | 2 | 2 per AZ used |
| 3 shards, 1 replica | 2 per shard | 6 | 6 distributed across AZs |
| 3 shards, 2 replicas | 3 per shard | 9 | 9 distributed across AZs |

Ensure each subnet in the subnet group has enough available IPs for the planned node count plus headroom for scaling. A /24 subnet (251 usable IPs) is sufficient for most ElastiCache deployments, but tightly-sized /28 subnets (11 usable IPs) can be exhausted quickly if multiple clusters share the same subnets.

## Data Tiering

Data tiering (SSD-backed memory extension) requires the r6gd instance family and Valkey 7.2+ or Redis OSS 6.2+. Node-based only, not available on serverless.
