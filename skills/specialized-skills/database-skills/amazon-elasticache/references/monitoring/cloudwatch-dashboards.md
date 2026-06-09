# CloudWatch Dashboard Templates

Pre-built dashboard specifications for ElastiCache serverless and node-based deployments. Deploy via CloudFormation or use as a reference for manual dashboard creation.

## Serverless Dashboard

Metrics focused on consumption-based billing, throttling, latency, and connection health.

### Key Widgets

| Widget | Metric(s) | Statistic | Period | Purpose |
|--------|-----------|-----------|--------|---------|
| ECPU Consumption | ElastiCacheProcessingUnits | Sum | 1 min | Cost driver and usage trend |
| Throttled Commands | ThrottledCmds | Sum | 1 min | Indicates hitting usage limits |
| Cache Hit Rate | CacheHitRate | Average | 5 min | Data access efficiency |
| Read Latency | SuccessfulReadRequestLatency | p99, Average | 1 min | Client-perceived read performance |
| Write Latency | SuccessfulWriteRequestLatency | p99, Average | 1 min | Client-perceived write performance |
| Current Connections | CurrConnections | Maximum | 1 min | Connection pool health |
| New Connections | NewConnections | Sum | 1 min | Connection churn (high values suggest missing pooling) |
| Data Storage | BytesUsedForCache | Maximum | 5 min | Storage consumption vs. configured limit |
| Total Commands | TotalCmdsCount | Sum | 1 min | Overall command throughput |
| Cache Hits | CacheHits | Sum | 1 min | Successful key lookups |
| Cache Misses | CacheMisses | Sum | 1 min | Unsuccessful key lookups |
| Current Items | CurrItems | Maximum | 1 min | Number of items stored in cache |
| Volatile Items | CurrVolatileItems | Maximum | 1 min | Number of items with TTL set |
| Evictions | Evictions | Sum | 5 min | Keys evicted by the cache |
| Network In | NetworkBytesIn | Sum | 1 min | Bytes transferred into cache |
| Network Out | NetworkBytesOut | Sum | 1 min | Bytes transferred out of cache |
| Auth Failures | AuthenticationFailures | Sum | 1 min | Failed AUTH attempts (set alarm to detect unauthorized access) |
| Key Auth Failures | KeyAuthorizationFailures | Sum | 1 min | Failed key access attempts (set alarm to detect unauthorized access) |
| Command Auth Failures | CommandAuthorizationFailures | Sum | 1 min | Failed command authorization attempts (set alarm to detect unauthorized access) |
| IAM Auth Expirations | IamAuthenticationExpirations | Sum | 1 min | Expired IAM-authenticated connections |
| IAM Auth Throttling | IamAuthenticationThrottling | Sum | 1 min | Throttled IAM auth requests |
| String Commands | StringBasedCmds | Sum | 1 min | GET/SET workload volume |
| Hash Commands | HashBasedCmds | Sum | 1 min | Hash-based workload volume |
| Sorted Set Commands | SortedSetBasedCmds | Sum | 1 min | Leaderboard/ranking activity |
| List Commands | ListBasedCmds | Sum | 1 min | List-based workload volume |
| Set Commands | SetBasedCmds | Sum | 1 min | Set-based workload volume |
| Pub/Sub Commands | PubSubBasedCmds | Sum | 1 min | Real-time messaging activity |
| Key Commands | KeyBasedCmds | Sum | 1 min | Key management operations |

Serverless also supports `*ECPUs` companions for each command-family metric (e.g., `StringBasedCmdsECPUs`) to track ECPU consumption by command type.

Use `scripts/generate_dashboards.py` to produce the full CloudFormation template from these widget specifications.

### ECPU Cost Attribution by Command Type

For serverless caches, ElastiCache emits per-command-type ECPU metrics that are critical for understanding cost drivers in a consumption-based billing model:

| Widget | Metric(s) | Statistic | Period | Purpose |
|--------|-----------|-----------|--------|---------|
| Read ECPUs | GetTypeCmdsECPUs | Sum | 1 min | ECPUs consumed by read commands |
| Write ECPUs | SetTypeCmdsECPUs | Sum | 1 min | ECPUs consumed by write commands |
| Hash ECPUs | HashBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by hash commands |
| String ECPUs | StringBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by string commands |
| Sorted Set ECPUs | SortedSetBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by sorted set commands |
| Stream ECPUs | StreamBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by stream commands |
| List ECPUs | ListBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by list commands |
| Set ECPUs | SetBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by set commands |
| JSON ECPUs | JsonBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by JSON commands |
| PubSub ECPUs | PubSubBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by pub/sub commands |
| Key ECPUs | KeyBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by key commands |
| Eval ECPUs | EvalBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by eval commands |
| GeoSpatial ECPUs | GeoSpatialBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by geospatial commands |
| HyperLogLog ECPUs | HyperLogLogBasedCmdsECPUs | Sum | 1 min | ECPUs consumed by HyperLogLog commands |
| NonKey ECPUs | NonKeyTypeCmdsECPUs | Sum | 1 min | ECPUs consumed by non-key commands |

### Generate via Script

```bash
python3 scripts/generate_dashboards.py --serverless <cache-name> --region us-east-1 --output serverless-dashboard.json
```

## Node-Based Dashboard

Metrics focused on engine performance, memory pressure, replication health, and command workload distribution.

### Key Widgets

| Widget | Metric(s) | Statistic | Period | Purpose |
|--------|-----------|-----------|--------|---------|
| Engine CPU | EngineCPUUtilization | Maximum | 1 min | Single-threaded engine bottleneck (most critical for performance) |
| Host CPU | CPUUtilization | Average | 1 min | Overall host CPU including background tasks |
| Memory Usage | DatabaseMemoryUsagePercentage | Maximum | 1 min | Memory pressure; triggers evictions when high |
| Capacity Usage | DatabaseCapacityUsagePercentage | Maximum | 1 min | DatabaseCapacityUsagePercentage is available on all node-based clusters. On data-tiering instances (r6gd), the formula includes SSD storage; on all other instances, it is calculated as `used_memory/maxmemory`. |
| Cache Hit Rate | CacheHitRate | Average | 5 min | Data access efficiency. `CacheHitRate` is available for both serverless and node-based Valkey/Redis OSS clusters. |
| Replication Lag | ReplicationLag | Maximum | 1 min | Replica staleness (seconds); critical for read consistency |
| Current Connections | CurrConnections | Maximum | 1 min | Connection pool health |
| Evictions | Evictions | Sum | 5 min | Keys evicted due to memory pressure |
| Network I/O | NetworkBytesIn, NetworkBytesOut | Sum | 1 min | Bandwidth utilization |
| String Commands | StringBasedCmds | Sum | 1 min | GET/SET workload volume |
| Hash Commands | HashBasedCmds | Sum | 1 min | Hash-based workload volume |
| Sorted Set Commands | SortedSetBasedCmds | Sum | 1 min | Leaderboard/ranking activity |
| Stream Commands | StreamBasedCmds | Sum | 1 min | Event stream workload |
| Search Commands | SearchBasedCmds | Sum | 1 min | Search command activity (includes all Search read and write commands; populates only when Valkey Search is in use) |
| JSON Commands | JsonBasedCmds | Sum | 1 min | JSON document usage |
| Pub/Sub Commands | PubSubBasedCmds | Sum | 1 min | Real-time messaging activity |

Use `scripts/generate_dashboards.py` to produce the full CloudFormation template from these widget specifications.

### Generate via Script

```bash
python3 scripts/generate_dashboards.py --replication-group <cluster-id> --region us-east-1 --output node-dashboard.json
```

## Deploying Dashboards

After generating the CloudFormation template:

```bash
aws cloudformation deploy \
  --template-file serverless-dashboard.json \
  --stack-name my-cache-dashboard \
  --parameter-overrides ServerlessCacheName=my-cache Region=us-east-1 \
  --region us-east-1
```

Or for node-based:

```bash
aws cloudformation deploy \
  --template-file node-dashboard.json \
  --stack-name my-cluster-dashboard \
  --parameter-overrides ReplicationGroupId=my-cluster Region=us-east-1 \
  --region us-east-1
```
