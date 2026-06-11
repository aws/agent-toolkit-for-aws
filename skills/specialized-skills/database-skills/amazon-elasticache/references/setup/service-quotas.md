# Service Quotas and Limits

Default account-level quotas for ElastiCache. Most are adjustable via the Service Quotas console or CLI without filing a support ticket.

## Default Quotas

| Quota | Default | Adjustable | Quota Code |
|-------|---------|------------|------------|
| Nodes per region | 300 | Yes | L-DFE45DF3 |
| Nodes per cluster (cluster mode enabled) | 90 (max 500 for Valkey 7.2+ or Redis OSS 5.0.6+) | Yes | L-AF354865 (verify in your account via `list-service-quotas`) |
| Nodes per cluster (Memcached) | 60 | Yes | L-8C334AD1 |
| Nodes per shard (architectural limit) | 6 | No | — |
| Parameter groups per region | 300 | Yes | L-3F15A733 |
| Serverless caches per region | 40 | Yes | L-BBCDAECC |
| Serverless snapshots per day per cache | 24 | Yes | L-75A7B5A4 |
| Subnet groups per region | 300 | Yes | L-3E7F7726 |
| Subnets per subnet group | 20 | Yes | L-A87EE522 |
| User groups per region | 200 | Yes | L-AD484FC5 |
| Users per region | 2,000 | Yes | L-80E085C7 |
| Users per user group | 100 | Yes | L-943F0F1C |

Nodes per replication group breaks down as: shards x (1 primary + replicas per shard). For example, 6 shards x (1 primary + 5 replicas = 6 nodes/shard) = 36 nodes per group, well under the 90-node default.

Per-cache serverless limits (storage, ECPU) are adjusted directly via `modify-serverless-cache --cache-usage-limits`, not through Service Quotas.

## Checking Current Quotas

**CLI:**

```bash
aws service-quotas list-service-quotas --service-code elasticache --region <region>
```

**Console:** Service Quotas > AWS services > Amazon ElastiCache.

To check applied (effective) values vs defaults:

```bash
aws service-quotas get-service-quota --service-code elasticache --quota-code <quota-code>
```

## Requesting Increases

**Self-service (most quotas):**

```bash
aws service-quotas request-service-quota-increase \
  --service-code elasticache \
  --quota-code <quota-code> \
  --desired-value <value>
```

Find the quota code from `list-service-quotas` output or the table above. Increases are typically approved within minutes for standard quotas.

**Serverless storage/ECPU:** Adjust directly, no quota request needed:

```bash
aws elasticache modify-serverless-cache \
  --serverless-cache-name <name> \
  --cache-usage-limits '{
    "DataStorage": {"Minimum": 1, "Maximum": 10, "Unit": "GB"},
    "ECPUPerSecond": {"Minimum": 1000, "Maximum": 30000}
  }'
```

## Common Quota-Related Errors

| Error pattern | Likely quota | Action |
|---------------|-------------|--------|
| "Maximum number of nodes" | Nodes per region (300, L-DFE45DF3) | Request increase via Service Quotas |
| "Maximum number of cache parameter groups" | Parameter groups (300, L-3F15A733) | Delete unused groups or request increase |
| "Maximum number of subnet groups" | Subnet groups (300, L-3E7F7726) | Delete unused groups or request increase |
| Serverless creation fails at region limit | Serverless caches per region (40, L-BBCDAECC) | Request increase via Service Quotas |
