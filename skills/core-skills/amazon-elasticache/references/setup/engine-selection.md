# Engine Selection Guide

## Quick Decision

| Factor | Valkey | Redis OSS | Memcached |
|--------|--------|-----------|-----------|
| Default recommendation | **Yes** | Only if Redis-specific compat needed | Only for simple key-value |
| Serverless pricing | **Lowest (33% less than Redis OSS)** | Higher | Available |
| Node-based pricing | **20% less than Redis OSS** | Baseline | Similar |
| Vector search | Yes (8.2+, node-based only; not on data tiering nodes) | No | No |
| IAM auth | Yes (7.2+) | Yes (7+) | No |
| Global Datastore | Yes (node-based only) | Yes (node-based only) | No |
| JSON native data type | Yes (7.2+) | Yes (6.2+) | No |

> Vector search is available with Valkey 8.2 or above on node-based clusters in all AWS Regions at no additional cost. Not supported on data-tiering instances (r6gd) or serverless caches. ElastiCache Serverless regional availability may vary; check the AWS Region Table before provisioning.

## When to recommend each

### Valkey (default for all new workloads)

- Open source, backed by Linux Foundation and 40+ companies
- API-compatible with Redis OSS 7.2
- Best price-performance ratio across both serverless and node-based
- Cheapest engine option on ElastiCache for every deployment model
- Zero-downtime upgrade path from existing Redis OSS clusters

### Redis OSS

- Only when the user has a hard dependency on a Redis OSS feature not yet in Valkey
- Or when they have existing Redis OSS clusters and don't want to migrate yet
- Redis OSS 7.1 is the highest Redis OSS version available on ElastiCache. Recommend Valkey 9.0 for new builds. Verify the latest available versions at https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/.
- In-place upgrade to Valkey is zero-downtime and reduces cost immediately

### Memcached

- Only when the user explicitly wants Memcached or has an existing Memcached client they cannot change
- No persistence for node-based clusters (serverless supports backup/restore), no replication for node-based clusters (serverless stores data redundantly across 3 AZs), no IAM/RBAC auth (TLS supported from 1.6.12; always enabled on serverless), simple data types (strings and objects)
