# MemoryDB

- **Docs**: https://docs.aws.amazon.com/memorydb/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/memorydb/latest/devguide/llms.txt
- **Data model**: In-memory key-value and data structures (durable primary store)
- **Query language**: Valkey/Redis commands (GET, SET, HSET, ZADD, XADD, JSON.*, FT.SEARCH, etc.)
- **Compatibility**: Valkey/Redis OSS protocol (open-source, same drivers and tools)
- **Serverless**: No (provisioned node clusters with sharding)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Multi-Region active-active (eventually consistent cross-region, strongly consistent within region)
- **Free Tier**: None (covered by $100-200 new-account credits)
- **Min cost**: ~$75/month (db.t4g.small, single shard + 1 replica)
- **Time to first query**: 5-10 min (VPC + cluster creation)
- **Key features**: Microsecond reads / single-digit ms writes, Multi-AZ durable transactional log, vector search (HNSW, single-digit ms at 99%+ recall), JSON document support, data tiering (memory + SSD for nearly 5x capacity at 60% lower cost), 160M+ requests/sec per cluster, 100+ TB storage, sharding, ACLs
- **Limitations**: No scale to zero, VPC required, provisioned capacity only, in-memory cost scales with data size, Multi-Region excludes data tiering and vector search
- **Best for**: Workloads requiring multi-region active-active writes (strongly consistent within region, eventually consistent cross-region) — the capability that distinguishes MemoryDB from ElastiCache
- **Not for**: Single-region workloads (ElastiCache offers the same durability, vector search, and microsecond latency at lower cost with a Serverless option), large analytical datasets, relational data with JOINs, workloads needing scale-to-zero cost efficiency
