# VPC Patterns for ElastiCache

ElastiCache-specific networking rules. Generic VPC knowledge is omitted (the model already knows how subnets and security groups work).

## Port Requirements

| Deployment Type | Port | Purpose |
|----------------|------|---------|
| Serverless | 6379 | Primary endpoint (read/write) |
| Serverless | 6380 | Reader endpoint (same DNS name as primary, port 6380 for read-optimized access; node-based reader endpoints use a separate DNS name on port 6379) |
| Node-based | 6379 | Valkey/Redis OSS data port (both primary and reader endpoints) |
| Node-based (cluster mode) | 16379 | Cluster bus port (node-to-node, auto-managed) |
| Node-based (Memcached) | 11211 | Memcached data port |
| Serverless (Memcached) | 11211 | Memcached serverless endpoint (TLS mandatory) |

> **TLS note:** TLS is mandatory for all serverless caches (Valkey/Redis OSS and Memcached). There is no option to disable in-transit encryption on serverless deployments.

## Security Group Anti-Patterns

- Do not open `0.0.0.0/0` on any port. ElastiCache is VPC-internal only.
- Do not use IP-based rules when security-group-based rules are possible. SG references survive IP changes.
- Do not allow port ranges (e.g., 6379-6400). Use specific ports only.
- Do not attach the cache to a default security group that allows all inbound from itself.
- For serverless (Valkey/Redis OSS): open ports 6379 (primary) and 6380 (reader) from the app security group. The primary and reader endpoints use the same DNS name on different ports (6379 for primary, 6380 for read-optimized).
- For serverless (Memcached): open port 11211 from the app security group.

## Subnet Group Requirements

- **Node-based clusters** require a cache subnet group. ElastiCache uses the subnet group to select subnets and assign IP addresses to cache nodes.
- **Serverless caches** do not use a subnet group resource. Instead, pass a list of subnet IDs directly during creation.

## Subnet IP Address Capacity

- CIDR blocks for each subnet must be large enough to provide spare IP addresses for ElastiCache to use during maintenance activities.
- Common pitfalls: subnets in the subnet group have too small a CIDR range, or subnets are shared and heavily used by other clusters.
- For large cluster-mode-enabled deployments (up to 500 nodes), ensure sufficient available IP addresses to accommodate scaling.

## PrivateLink and Cross-VPC Access

- **PrivateLink (VPC Endpoints)** covers ElastiCache control-plane APIs only (e.g., `CreateCacheCluster`, `DescribeReplicationGroups`). It does not provide data-plane connectivity to cache endpoints.
- **Cross-VPC data access** requires VPC Peering, Transit Gateway (TGW), AWS Direct Connect, or site-to-site VPN. Use security group references (preferred, when peering supports it) or CIDR-based rules to allow traffic between the application VPC and the cache VPC.
