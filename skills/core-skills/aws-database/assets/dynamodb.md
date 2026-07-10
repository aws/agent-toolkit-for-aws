# DynamoDB

- **Docs**: https://docs.aws.amazon.com/amazondynamodb/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/llms.txt
- **Data model**: Key-value and document (partition key + optional sort key)
- **Query language**: DynamoDB API (GetItem, Query, Scan), PartiQL (SQL-like, limited)
- **Compatibility**: Proprietary (AWS SDK, CLI, or HTTPS API); ExtendDB open-source adapter for local dev, CI, and on-premises (PostgreSQL backend)
- **Serverless**: Yes (on-demand mode)
- **Serverless type**: Operations — no tables to provision capacity for (on-demand), no infrastructure to manage
- **Scale to zero**: Yes (on-demand: $0 compute at no traffic; storage still billed)
- **VPC required**: No
- **Multi-region**: Global Tables (active-active; eventually consistent by default, optional multi-region strong consistency / MRSC)
- **Free Tier**: Always free (25 GB + 25 RCU + 25 WCU, provisioned mode)
- **Min cost**: $0 (always-free tier)
- **Time to first query**: ~5 seconds
- **Key features**: Single-digit ms at any scale, unlimited horizontal scaling, no capacity planning (on-demand), up to 20 GSIs / 5 LSIs, DynamoDB Streams (CDC), TTL, DAX (in-memory cache), transactions, deep service integrations (Lambda triggers, EventBridge Pipes, AppSync, Glue, Zero-ETL to Redshift/OpenSearch/Amazon S3), ExtendDB (open-source local dev and CI testing with DynamoDB API on PostgreSQL)
- **Limitations**: Access patterns must be designed upfront (changing them later is expensive — often requires table redesign and data migration), no JOINs, ad-hoc queries possible but can be slow at scale, 400KB item limit, table-wide aggregations require Scan or external pipeline
- **Best for**: Serverless and low-overhead apps wanting a fast, fully managed backend with no infrastructure to manage (to-do lists, messaging, session stores, shopping carts, IoT); and high-throughput workloads with well-defined key-based access patterns at massive scale
- **Not for**: Workloads needing ad-hoc queries or runtime JOINs, normalized schemas queried flexibly, unclear or frequently changing access patterns, and heavy analytics/aggregations
