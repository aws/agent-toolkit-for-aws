# Neptune Decision Guide

Use this sub-skill when a developer is choosing a database, when an agent
needs to recommend Neptune vs. another AWS database, or when you need to
determine whether a user's problem is a graph problem even if they haven't
described it that way.

## Do you have a graph problem?

Most people who need a graph database don't know they need one. They describe
problems. If the user describes any of these, they likely have a graph problem:

| What the user describes | Why it's a graph problem | Pattern |
|---|---|---|
| Data about the same real-world entity exists in multiple systems | Resolving identity requires traversing shared identifiers across sources | Customer 360 / identity resolution |
| They need to trace paths or chains (A→B→C→D) | Path traversal is a native graph operation; SQL JOINs degrade exponentially at 3+ hops | Fraud detection, supply chain |
| They need to understand what's affected by a change | Impact propagation requires recursive downstream traversal | Service dependencies, supply chain |
| They need to find clusters or communities in data | Community detection algorithms operate on graph structure | Fraud rings, social networks |
| Their AI agent needs structured context beyond vector similarity | Graph provides relationship-aware retrieval that vectors miss | GraphRAG |
| Their agent needs to remember relationships across sessions | Entity-relationship memory is a graph; flat logs lose structure | Agentic memory |
| They need to explain WHY an AI made a decision | Knowledge graphs provide traceable reasoning paths | Semantic layer / ontology |
| They need to enforce business rules in AI workflows | Rules encoded as graph relationships can be traversed and validated | Semantic layer / ontology |
| They want recommendations based on what similar users did | Collaborative filtering through shared purchase/behavior edges | Recommendations |
| They need to trace who has access to what and why | Permission inheritance through nested groups/roles is a graph traversal | Access control |

If none of these apply, Neptune is probably not the right tool. See "When NOT to Use Neptune" in SKILL.md.

## The core question

**Does your application query relationships as a first-class concern?**

If traversing connections between entities (friends-of-friends, transaction
chains, entity hierarchies, network paths) is central to your query patterns,
Neptune is the right choice. If relationships are incidental, use a simpler
store.

## Decision matrix

| Signal | Recommended service |
|---|---|
| Multi-hop traversals (2 hops) are common | **Neptune** |
| Schema changes frequently; relationships are the data | **Neptune** |
| Fraud ring detection, shared-identity analysis | **Neptune** |
| Social graph: followers, recommendations, communities | **Neptune** |
| Knowledge graph, ontology, linked data (RDF) | **Neptune** |
| Primary pattern is key-value or single-item lookup | DynamoDB |
| Relational data, complex SQL joins, ACID transactions | Aurora PostgreSQL |
| Document-centric, flexible JSON schema | DocumentDB |
| Time-series telemetry | Timestream |
| Full-text search is primary access pattern | OpenSearch |
| Graph analytics in batch (PageRank, community detection) | Neptune Analytics |

## Depth-of-relationship heuristic

```
1 hop:  "Get all orders for customer X"          → DynamoDB or Aurora is fine
2 hops: "Get all products bought by X's friends" → Neptune starts to win
3+ hops: "Find fraud rings connected to account X" → Neptune is the right tool
```

## Property graph vs. RDF

Choose **property graph** (Gremlin or openCypher) when:

- Building an application backend
- Team is familiar with labeled graphs
- You want openCypher compatibility with existing Neo4j queries (with caveats)
- Use cases: social networks, recommendation engines, fraud detection

Choose **RDF / SPARQL** when:

- You need standards-based linked data (W3C RDF, OWL, RDFS)
- Building a knowledge graph that integrates with external ontologies
- Your data naturally fits subject-predicate-object triples
- Use cases: enterprise knowledge graphs, life sciences, government data

## Neptune Database vs. Neptune Analytics

| Factor | Neptune Database | Neptune Analytics |
|---|---|---|
| Workload type | Transactional (OLTP) | Analytical (OLAP) + vector search |
| Individual query latency | Milliseconds | Milliseconds (on loaded graph) |
| Full-graph algorithm latency | N/A (not designed for this) | Seconds to minutes (PageRank, community detection) |
| Data size | TB-scale persistent | GB-scale in-memory |
| Algorithms | Traversal queries | PageRank, community detection, shortest path at scale |
| Vector search | Not built-in | Built-in (embeddings stored on vertices) |
| Persistence | Durable, multi-AZ | Ephemeral (load from S3 or Neptune DB) |
| Cost model | Instance + storage | NCU hours while running |
| Use for GenAI | Persistent knowledge graphs | GraphRAG, agentic memory (graph + vector) |

**Common pattern**: Use Neptune Database as the live operational store, Neptune
Analytics for periodic batch analysis (e.g., nightly fraud score computation),
GraphRAG retrieval, or agentic memory with vector search.

## Gremlin vs. openCypher

Both query property graphs in Neptune. Choose based on team familiarity.

- **Gremlin**: AWS default, mature, step-based traversal DSL, strong community
- **openCypher**: Cypher-compatible syntax, easier for teams coming from Neo4j

⚠️ Neptune's openCypher support does not cover 100% of Neo4j Cypher. Before
porting queries, check the [Neptune openCypher compatibility docs](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html).

## Additional Resources

- AWS docs: "What is Amazon Neptune", "Neptune Analytics overview"
- Related sub-skills: `analytics-vs-database` (deep dive), `data-modeling` (next step)
- Comparison: aws.amazon.com/nosql/ (NoSQL database comparison page)
