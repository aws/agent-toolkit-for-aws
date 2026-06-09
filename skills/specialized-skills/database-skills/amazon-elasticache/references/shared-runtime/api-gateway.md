# API Gateway + ElastiCache Integration

There is no direct integration path from Amazon API Gateway to ElastiCache. API Gateway cannot connect to a VPC-hosted cache endpoint on its own. All access goes through a compute layer that bridges the public API surface to the private VPC where ElastiCache runs.

## Integration Patterns

### Pattern 1: API Gateway -> Lambda -> ElastiCache (most common)

The simplest and most widely used path. API Gateway invokes a Lambda function that reads from or writes to ElastiCache.

```
Client -> API Gateway -> Lambda (VPC-attached) -> ElastiCache (VPC)
```

Requirements:

- Lambda must be attached to the VPC where ElastiCache resides
- Lambda execution role needs ENI permissions (`ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface`, `ec2:DescribeSubnets`, `ec2:AssignPrivateIpAddresses`, `ec2:UnassignPrivateIpAddresses`). Alternatively, use the managed policy `AWSLambdaVPCAccessExecutionRole` which includes all required permissions.
- Lambda security group must have outbound access to the cache security group on port 6379 (and also port 6380 if using the serverless read-optimized endpoint for lower-latency eventually-consistent reads; routing is handled by the endpoint itself, not by issuing the READONLY command)
- For IAM auth: Lambda execution role needs `elasticache:Connect` permission on both the cache resource ARN (`arn:aws:elasticache:<region>:<account-id>:serverlesscache:<cache-name>` or `arn:aws:elasticache:<region>:<account-id>:replicationgroup:<rg-id>`) and the user resource ARN (`arn:aws:elasticache:<region>:<account-id>:user:<user-id>`). IAM auth requires Redis OSS 7.0+ or Valkey 7.2+, and the ElastiCache user-id and user-name must be identical.
- Default to serverless cache to match Lambda's variable invocation pattern. Note that serverless caches are cluster-mode-enabled only, so your client library must use a cluster-aware client (e.g., `ValkeyCluster`, `RedisCluster`).

Best for: REST APIs, HTTP APIs, WebSocket APIs with caching needs, low-to-medium throughput workloads.

### Pattern 2: API Gateway -> VPC Link -> NLB/ALB -> ECS/EKS -> ElastiCache

For container-based backends that already run in a VPC. API Gateway connects through a VPC Link to a load balancer (NLB for REST APIs, or ALB/NLB for HTTP APIs) in front of ECS tasks or EKS pods.

```
Client -> API Gateway -> VPC Link -> NLB/ALB -> ECS/EKS -> ElastiCache (same VPC)
```

Requirements:

- REST API VPC Links (V1) support NLB only. REST APIs also support VPC Link V2 with ALB as a target. HTTP API VPC Links (V2) support ALB, NLB, or Cloud Map.
- Load balancer must be in the same VPC as ElastiCache
- ECS tasks use `awsvpc` network mode; EKS pods use VPC CNI
- Task or pod security group must allow outbound to cache security group on port 6379

Best for: high-throughput APIs, long-lived connections with connection pooling, workloads already running on containers.

## Distributed Rate Limiting with ElastiCache

Use ElastiCache as the backing store for rate limiting behind API Gateway. This pattern supplements API Gateway's built-in throttling with application-level granularity.

```
Client -> API Gateway -> Lambda/Container -> ElastiCache (rate limit check) -> Backend
```

How it works:

1. API Gateway forwards the request to the compute layer
2. The compute layer increments a counter in ElastiCache keyed by user, API key, or IP
3. If the counter exceeds the limit, the compute layer returns HTTP 429 immediately
4. If within limits, the request proceeds to the backend logic

This enables:

- Per-user or per-tenant rate limits (API Gateway throttling is per-stage or per-key)
- Sliding-window rate limiting using sorted sets
- Shared rate limit state across multiple Lambda functions or container instances
- Custom rate limit rules that change dynamically without redeploying

See `references/data-modeling/common-patterns.md` for the rate limiting data structure pattern.

## Caching Layers: API Gateway Stage Cache vs ElastiCache

These are complementary, not competing, layers.

| Aspect | API Gateway Stage Cache | ElastiCache |
|--------|------------------------|-------------|
| Layer | HTTP response cache at the gateway (REST APIs only, not HTTP APIs) | Application-level cache inside VPC |
| Granularity | Full HTTP response by URL + query params | Any data structure, any key schema |
| Scope | Single API Gateway stage | Shared across all compute in the VPC |
| TTL control | Per-method or per-stage | Per-key, per-pattern |
| Invalidation | Cache flush or TTL expiry | Fine-grained key invalidation, write-through |
| Cost | Included in API Gateway caching charge | Separate ElastiCache pricing |
| Use case | Cache entire API responses for read-heavy public endpoints | Cache database queries, sessions, rate limits, computed results |

When to use both:

- API Gateway stage cache for static or semi-static GET responses that rarely change
- ElastiCache for dynamic, fine-grained caching behind the API (database queries, session lookups, computed aggregations)
- The two layers do not conflict; API Gateway cache reduces calls to Lambda/containers, and ElastiCache reduces calls to databases and external services within those functions

When to skip API Gateway cache:

- POST/PUT/DELETE requests (not cacheable at the gateway)
- Personalized responses that vary per user
- Responses that need sub-second invalidation
- When ElastiCache already handles the caching and the API response is always computed fresh from cached data
