# Solution Fit

Gather enough context to recommend the right ElastiCache configuration, then hand off to the appropriate sub-skill.

## Loading

Read this file first. Load `scripts/price_calculator.py` when estimating cost.

## Check for existing context

Before starting, check if `.elasticache/requirements.json` exists from a previous session. If it does, read it, present the values to the user, and ask if anything has changed. If confirmed accurate, skip directly to **Hand off**.

## Fast path (skip the interview)

If the user already knows what they want, don't interview them. Run the workspace scan silently, then route:

- User names a specific product or engine ("create a Valkey serverless cache") -> skip to **Summarize and hand off**. Ask only for missing critical values (region, VPC). Serverless supports Valkey 7.2, 8.0, and 8.1. If user requests Redis OSS, note that Valkey is the recommended forward path. Redis OSS remains available (highest version on ElastiCache: 7.1), but Valkey receives new feature investments (vector search, Bloom filters, memory-efficient hash table, COMMANDLOG, and more). If the user needs vector search (semantic caching, agentic memory, RAG), note that Valkey 8.2+ is required and is available on node-based clusters only (not available on Serverless or data-tiering r6gd instances).
- User names a specific pattern ("session store", "rate limit my API", "semantic cache for Bedrock") -> confirm inferences from scan, skip to **Summarize and hand off**.
- User names a specific task ("migrate from Redis to Valkey", "check my cache costs") -> route directly to matching sub-skill. Do not run this flow.

## Full flow (for unclear or exploratory requests)

### 1. Workspace Scan (always run first, silently)

Scan the user's workspace for: language/framework, compute/deployment model, networking/region, cache commands, and existing caching solutions. If workspace has docker-compose with a Redis image, redis.conf, .env with Redis URLs, or ElastiCache in existing IaC, route to `migration`. Map discovered commands to patterns:

| Commands in code | Likely pattern |
|-----------------|----------------|
| INCR, EXPIRE, DECR | Rate limiting or counters |
| HSET, HGET, HMSET, HMGET | Sessions, carts, or profile/state |
| ZADD, ZRANGE, ZRANGEBYSCORE | Leaderboards or ranking |
| XADD, XREADGROUP, XACK | Streams or durable queues |
| PUBLISH, SUBSCRIBE | Real-time messaging / pub/sub |
| GET, SET, SETEX with serialized values | Cache-aside / query caching |
| Embedding generation, vector similarity | GenAI (route to `genai`) |

### 2. Present Inferences

Present what you found in a single confirmation block with evidence from file paths.

Inference safety hierarchy:

- **Low risk** (use as default, mention but don't ask): Language, framework, region
- **Medium risk** (present and ask to confirm): Use case pattern, deployment model
- **High risk** (always confirm explicitly): Engine choice, security posture, multi-region

If the workspace scan reveals nothing, skip to step 3.

### 3. Evaluate fit

If caching with ElastiCache is clearly the right approach, skip to step 4.

If the user is unsure, evaluate:

**When ElastiCache is NOT the right fit:**

| Symptom | Better alternative | Can ElastiCache complement it? |
|---------|-------------------|-------------------------------|
| Need complex queries, joins, ACID transactions | RDS, Aurora | Yes, as a read cache in front of it |
| Need a DynamoDB-specific transparent cache | DAX | Yes, as a general cross-service cache alongside DAX |
| Need CDN / static content delivery | CloudFront | Yes, as an app-layer cache behind CloudFront |
| Need a durable message queue with exactly-once delivery | SQS | Yes, for rate limiting in front of SQS |
| Need an event bus with routing rules | EventBridge | No |
| Need search over massive archival datasets | OpenSearch | Yes, as a fast real-time layer alongside OpenSearch |
| Slow DB reads but every query is unique | DB indexing, read replicas, query optimization | No |
| Need a durable primary database with Redis/Valkey API compatibility | MemoryDB | No, use MemoryDB instead of ElastiCache when the workload requires a durable primary database with microsecond reads and single-digit ms writes |

**Common "use both" patterns:**

- ElastiCache + RDS/Aurora: Cache-aside for read acceleration
- ElastiCache + DynamoDB: General cross-service cache layer
- ElastiCache + Bedrock: Semantic cache to reduce LLM cost and latency
- ElastiCache + OpenSearch: Fast real-time search layer with OpenSearch for archival analytics
- ElastiCache + SQS: Rate limiting and deduplication in front of a queue

**Shared or application-local?** (only when the role is cache layer)

| Factor | Application-local sufficient | Shared (ElastiCache) needed |
|--------|------------------------------|----------------------------|
| Multiple app instances need the same data | No | Yes |
| Data must survive app restarts | No | Yes |
| Atomic operations across instances | No | Yes |
| Rich data structures (sorted sets, streams, hashes) | No | Yes |
| Single instance, simple memoization | Yes | Overkill |

If application-local is sufficient, recommend it and stop.

### 4. Route or ask

If the scan + user's message reveal the job, route immediately. Otherwise ask remaining questions 2-3 at a time, skipping anything the scan already answered.

**Questions (only what remains unknown):**

| Category | Question |
|----------|----------|
| Goal | Build new, migrate existing, or troubleshoot? |
| Data source | What is your primary data store? |
| Multi-region | Single-region or multi-region? |
| AI workload | Working with embeddings, LLM inference, or agent memory? |
| Compliance | Any regulatory requirements (HIPAA, PCI DSS, SOC 2, FedRAMP)? |
| Traffic | Expected request rate? Steady or spiky? |
| Connections | Concurrent connections? |
| Data size | GB of cached data? |
| Latency | Sub-millisecond critical, or single-digit ms acceptable? |
| Staleness | How stale can the data be? |
| Budget | Cost sensitive? |

**Signal-to-route mapping:**

| User signal | Route to |
|------------|----------|
| Slow database reads | `setup` + `data-modeling` (cache-aside) |
| Session storage across instances | `setup` + `data-modeling` (session) |
| Real-time rankings or scoring | `setup` + `data-modeling` (leaderboard) |
| API protection or throttling | `setup` + `data-modeling` (rate limiter) |
| Reducing LLM costs or latency | `setup` + `genai` (semantic cache); server-side path requires Valkey 8.2 or above, app-side works on any version |
| AI agent memory across sessions | `setup` + `genai` (conversational memory), requires Valkey 8.2+ |
| Search or recommendations | `setup` + `genai` (vector search / RAG), requires Valkey 8.2+ (node-based clusters only) |
| Real-time event distribution | `setup` + `data-modeling` (pub/sub or streams) |

**Compliance-to-configuration mapping:**

If the user mentions a compliance framework, these ElastiCache settings are non-negotiable:

| Framework | Required configuration |
|---|---|
| HIPAA | In-transit encryption (TLS), at-rest encryption, RBAC or IAM auth, Multi-AZ, slow log + engine log delivery enabled, CloudTrail API logging, VPC-only access |
| PCI DSS | In-transit encryption (TLS), at-rest encryption, RBAC or IAM auth, VPC-only access, no public endpoints, slow log + engine log delivery enabled, CloudTrail API logging, key rotation via Secrets Manager |
| SOC 2 | In-transit encryption (TLS), at-rest encryption, RBAC or IAM auth, CloudTrail enabled, security-relevant metric alarms (e.g., AuthenticationFailures, NewConnections) + CloudTrail |
| FedRAMP | All HIPAA requirements plus: GovCloud region, FIPS endpoints, Config rules for drift detection |

When compliance is flagged, pass the requirement to `setup` so it enforces encryption and auth from the start. At-rest encryption cannot be added after cluster creation; getting this wrong requires a full cluster recreation.

**AWS-stack translation table:**

| AWS context | Default ElastiCache choice |
|---|---|
| RDS or Aurora read-heavy app | Query caching / cache-aside |
| DynamoDB read-heavy app | ElastiCache cache-aside. Mention DAX only if user wants DynamoDB-specific transparent cache. |
| Lambda | VPC connectivity required. Default serverless unless node-based requirement applies. |
| ECS, EKS, or EC2 | Pick pattern per signal above. |
| Bedrock or AgentCore | Route to `genai`, classify Mode 1/2/3. |
| Global app footprint (multi-region) | Node-based with Global Datastore. Limited to specific instance families (M5, M6g, M7g, R5, R6g, R6gd, R7g, C7gn in size large+), max 2 secondary regions, no autofailover across regions (manual promotion only), no IPv6, no Local Zones. |

## Summarize and hand off

Summarize what you learned. Mark inferred values as "(inferred)" so the user can correct them.

### Save requirements artifact

After the user confirms, write to `.elasticache/requirements.json` in the project root. Create `.elasticache/` if needed. Use `null` for undetermined values. If the file exists with an `infrastructure` section, preserve it.

```json
{
  "use_case": "cache-aside for Aurora read acceleration",
  "patterns": ["cache-aside"],
  "runtime": { "language": "python", "framework": "fastapi", "compute": "ecs" },
  "region": "us-east-1",
  "engine": "valkey",
  "deployment_model": null,
  "data_source": "aurora-postgresql",
  "multi_region": false,
  "ai_workload": false,
  "next_steps": ["setup", "data-modeling"],
  "infrastructure": null
}
```

### Hand off

1. `setup` to create and connect
2. `data-modeling` or `genai` to implement the pattern

If the user's request spans multiple patterns, note that both can run on the same cache and plan the data model accordingly.

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."
