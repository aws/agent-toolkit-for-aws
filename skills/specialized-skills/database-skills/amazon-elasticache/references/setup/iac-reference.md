# IaC Reference for ElastiCache

ElastiCache-specific gotchas, resource/construct names, and property mappings across all IaC tools. The model can generate full templates/stacks given these constraints.

## Gotchas (apply to all IaC tools)

- **Engine value for RBAC**: User and UserGroup resources accept `valkey` or `redis` for the engine parameter. Use the value that matches your cache engine. Older Redis OSS clusters continue to use `redis`.
- **Subnet handling differs by deployment**: Serverless accepts subnet IDs directly. Node-based requires a separate subnet group resource.
- **Dependency ordering**: The cache resource must depend on its user group. Without explicit dependency, the cache may be created before RBAC is ready.
- **Serverless uses two ports**: Port 6379 (read/write) and port 6380 (reader). Security groups must allow both.
- **Encryption defaults are hard to change**: At-rest encryption cannot be changed after creation. Transit encryption can be enabled on existing node-based clusters via a two-step migration (`preferred` → `required` mode), but cannot be disabled once required. For serverless, TLS is always on. Always set encryption at creation time when possible.
- **CacheName restrictions**: Serverless cache names must be lowercase, start with a letter, letters/numbers/hyphens only, max 40 characters.
- **CDK L2 constructs**: ElastiCache has only L1 constructs in CDK (`CfnServerlessCache`, `CfnReplicationGroup`, `CfnCacheCluster`). No stable L2 construct module is available.

## Resource/Construct Names

| Resource | CloudFormation | CDK (L1) | Terraform |
|----------|---------------|----------|-----------|
| Serverless cache | `AWS::ElastiCache::ServerlessCache` | `elasticache.CfnServerlessCache` | `aws_elasticache_serverless_cache` |
| Node-based cluster | `AWS::ElastiCache::ReplicationGroup` | `elasticache.CfnReplicationGroup` | `aws_elasticache_replication_group` |
| Subnet group | `AWS::ElastiCache::SubnetGroup` | `elasticache.CfnSubnetGroup` | `aws_elasticache_subnet_group` |
| User (RBAC) | `AWS::ElastiCache::User` | `elasticache.CfnUser` | `aws_elasticache_user` |
| User group | `AWS::ElastiCache::UserGroup` | `elasticache.CfnUserGroup` | `aws_elasticache_user_group` |

## Output/Endpoint Attribute Paths

| Deployment | Value | CloudFormation | CDK | Terraform |
|-----------|-------|---------------|-----|-----------|
| Serverless | Primary endpoint | `!GetAtt Cache.Endpoint.Address` | `.attrEndpointAddress` | `.endpoint[0].address` |
| Serverless | Reader endpoint | `!GetAtt Cache.ReaderEndpoint.Address` | `.attrReaderEndpointAddress` | `.reader_endpoint[0].address` |
| Serverless | Port | `!GetAtt Cache.Endpoint.Port` | `.attrEndpointPort` | `.endpoint[0].port` |
| Serverless | ARN | `!GetAtt Cache.ARN` | `.attrArn` | `.arn` |
| Node-based (CME) | Config endpoint | `!GetAtt RG.ConfigurationEndPoint.Address` | `.attrConfigurationEndPointAddress` | `.configuration_endpoint_address` |
| Node-based (CMD) | Primary endpoint | `!GetAtt RG.PrimaryEndPoint.Address` | `.attrPrimaryEndPointAddress` | `.primary_endpoint_address` |
| Node-based (CMD) | Reader endpoint | `!GetAtt RG.ReaderEndPoint.Address` | `.attrReaderEndPointAddress` | `.reader_endpoint_address` |
| Node-based | Port | `!GetAtt RG.ConfigurationEndPoint.Port` | `.attrConfigurationEndPointPort` | (use 6379) |

## Serverless Cost Controls Structure

| Tool | Syntax |
|------|--------|
| CloudFormation | `CacheUsageLimits: { DataStorage: { Minimum: 5, Maximum: 10, Unit: GB }, ECPUPerSecond: { Minimum: 1000, Maximum: 15000 } }` |
| CDK | `cacheUsageLimits: { dataStorage: { minimum: 5, maximum: 10, unit: 'GB' }, ecpuPerSecond: { minimum: 1000, maximum: 15000 } }` |
| Terraform | `cache_usage_limits { data_storage { minimum = 5 / maximum = 10 / unit = "GB" } ecpu_per_second { minimum = 1000 / maximum = 15000 } }` (each `/` is a newline in HCL; commas are not used between block attributes) |
| CLI | `--cache-usage-limits 'DataStorage={Minimum=5,Maximum=10,Unit=GB},ECPUPerSecond={Minimum=1000,Maximum=15000}'` |

> **Note:** `Minimum` values enable pre-scaling (pre-warming) for anticipated traffic spikes. You are charged for the minimum even if actual usage is lower. Set minimums at least 60 minutes before peak events.

## Node-Based Required Properties for Production

| Property | CFN/CDK | Terraform | CLI flag |
|----------|---------|-----------|----------|
| Engine | `Engine: valkey` | `engine = "valkey"` | `--engine valkey` |
| Version | `EngineVersion: '9.0'` | `engine_version = "9.0"` | `--engine-version 9.0` |
| Node type | `CacheNodeType: cache.r7g.large` | `node_type = "cache.r7g.large"` | `--cache-node-type cache.r7g.large` |
| Shards | `NumNodeGroups: 2` | `num_node_groups = 2` | `--num-node-groups 2` |
| Replicas | `ReplicasPerNodeGroup: 1` | `replicas_per_node_group = 1` | `--replicas-per-node-group 1` |
| TLS | `TransitEncryptionEnabled: true` | `transit_encryption_enabled = true` | `--transit-encryption-enabled` |
| At-rest encryption | `AtRestEncryptionEnabled: true` | `at_rest_encryption_enabled = true` | `--at-rest-encryption-enabled` |
| Failover | `AutomaticFailoverEnabled: true` | `automatic_failover_enabled = true` | `--automatic-failover-enabled` |
| Multi-AZ | `MultiAZEnabled: true` | `multi_az_enabled = true` | `--multi-az-enabled` |
| Snapshots | `SnapshotRetentionLimit: 7` | `snapshot_retention_limit = 7` | `--snapshot-retention-limit 7` |

## Secure Defaults Checklist

- Transit encryption enabled (node-based) / always-on (serverless)
- At-rest encryption enabled with optional KMS key
- Multi-AZ with automatic failover (node-based)
- RBAC user group with restricted default user (`off ~* -@all`). Note: for Redis OSS user groups, the `default` user ID must be included in every user group; omitting it causes `CreateUserGroup` to fail with `DefaultUserRequired`. Valkey user groups do not have this requirement — the default user is automatically disabled when a Valkey user group is attached.
- Serverless caches operate in cluster-mode-enabled only; clients must support cluster protocol
- IAM auth for application users (Valkey 7.2+ or Redis OSS 7.0+); RBAC available from Redis OSS 6.0+
- Private subnets only
- Security group scoped to application SG, never `0.0.0.0/0`
- Snapshot retention configured (node-based)
- Cost controls via CacheUsageLimits (serverless)
