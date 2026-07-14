# DocumentDB (MongoDB compatible)

- **Docs**: https://docs.aws.amazon.com/documentdb/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/documentdb/latest/developerguide/llms.txt
- **Data model**: Document (JSON/BSON documents in collections)
- **Query language**: MongoDB Query Language (MQL), aggregation pipeline
- **Compatibility**: MongoDB 4.0/5.0/6.0/7.0/8.0 compatible (drivers, tools, aggregation pipeline)
- **Serverless**: Yes (elastic clusters, available on DocumentDB 8.0)
- **Serverless type**: Capacity — elastic clusters auto-scale storage and compute, but you still manage a cluster (no scale to zero)
- **Scale to zero**: No
- **VPC required**: Yes
- **Multi-region**: Global clusters
- **Free Tier**: 12 months (750 hrs db.t3.medium + 30 GB storage)
- **Min cost**: ~$0 (free tier) → ~$55/month after
- **Time to first query**: 10-15 min (VPC + cluster)
- **Key features**: MongoDB compatibility, elastic clusters (sharding up to 32 shards), change streams, ACID transactions, flexible schema, vector search (30x faster index builds on 8.0), Serverless auto-scaling (up to 90% savings vs provisioned peak)
- **Limitations**: Not full MongoDB (some operators unsupported), VPC required, no serverless scale-to-zero
- **Best for**: MongoDB migrations, content management, catalogs, user profiles, flexible schema applications
- **Not for**: Simple key-value (DynamoDB is better), time-series (Timestream), graph (Neptune)
