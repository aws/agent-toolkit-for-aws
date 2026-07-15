# Aurora DSQL

- **Docs**: https://docs.aws.amazon.com/aurora-dsql/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/aurora-dsql/latest/userguide/llms.txt
- **Data model**: Relational (distributed SQL)
- **Query language**: PostgreSQL SQL (standard SQL)
- **Compatibility**: PostgreSQL wire-compatible (works with PG drivers and ORMs)
- **Serverless**: Yes (only mode)
- **Serverless type**: Operations — no cluster, no instances, no maintenance windows; you interact with a database endpoint only
- **Scale to zero**: Yes, instant (no resume latency)
- **VPC required**: No
- **Multi-region**: Active-active, strongly consistent
- **Free Tier**: Always free — 100,000 DPUs/month + 1 GB storage
- **Min cost**: $0 idle; ~$1-5/month light traffic
- **Time to first query**: ~30 seconds
- **Key features**: No VPC setup, IAM auth, distributed, automatic scaling, optimistic concurrency control, up to 99.999% availability (multi-Region)
- **Limitations**: No extensions (pgvector, PostGIS, pg_trgm), no stored procedures, no triggers, no LISTEN/NOTIFY, no logical replication, no custom types
- **Best for**: New transactional apps, multi-region active-active, scale beyond single instance, minimal operational overhead
- **Not for**: Workloads needing PostgreSQL extensions, stored procedures, or full-text search with custom dictionaries
