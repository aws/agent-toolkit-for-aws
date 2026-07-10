# Neptune

- **Docs**: https://docs.aws.amazon.com/neptune/
- **Docs (llms.txt)**: https://docs.aws.amazon.com/neptune/latest/userguide/llms.txt
- **Data model**: Graph (property graph and RDF)
- **Query language**: openCypher, Apache TinkerPop/Gremlin, SPARQL
- **Compatibility**: openCypher (Neo4j-compatible), Gremlin (TinkerPop standard), SPARQL (W3C standard)
- **Serverless**: Yes (both Database and Analytics)
- **Serverless type**: Capacity — Serverless mode auto-scales compute, but you still manage a cluster (no scale to zero)
- **Scale to zero**: No (Serverless scales to minimum NCU)
- **VPC required**: Yes (Database); No (Analytics). Database supports public endpoints but still requires VPC configuration.
- **Multi-region**: Global Database (disaster recovery, <1 second RPO, up to 5 secondary regions)
- **Free Tier**: None
- **Min cost**: ~$75/month (provisioned db.t3.medium) or ~$120/month (Serverless min NCU) or ~$30/month (Analytics 16 m-NCU stopped)
- **Time to first query**: 10-15 min (Database, VPC + cluster); 2-5 min (Analytics, no VPC required)
- **Engine variants**: Neptune Database (transactional OLTP on Aurora storage) and Neptune Analytics (in-memory OLAP, algorithms, vector search)
- **Key features**: Three query languages, Neptune Analytics (PageRank, community detection, shortest path, connected components), vector search (HNSW, up to 65K dimensions), GraphRAG with Bedrock Knowledge Bases, NetworkX integration, MCP server for agent frameworks, Geospatial (ISO spatial types)
- **Limitations**: Graph-only (no SQL/tabular), VPC required for Database, learning curve for graph query languages, no native full-text search, fine-grained access control (FGAC) not yet supported
- **Best for**: Relationship traversals, fraud detection, knowledge graphs, identity resolution, social networks, recommendation engines, GraphRAG, agentic memory, supply chain analysis, network topology
- **Not for**: Tabular/relational data, simple key-value, time-series, full-text search only, workloads without meaningful relationships between entities, vector-only search without graph structure
